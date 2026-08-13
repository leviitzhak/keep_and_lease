/* Server-first calculation adapter preserving the v12 worker message contract. */
const startedAt = performance.now();
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const elapsed = () => ((performance.now() - startedAt) / 1000).toFixed(1);
function report(message, detail = "", progress = null) {
  self.postMessage({
    type: "progress", message, detail, progress,
    elapsedSeconds: Number(elapsed()),
    entry: `[+${elapsed()}s] ${message}${detail ? ` — ${detail}` : ""}`,
  });
}
function apiUrl(base, path) {
  return new URL(path, base.endsWith("/") ? base : `${base}/`).href;
}
async function jsonRequest(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {"content-type": "application/json", ...(options.headers || {})},
    cache: "no-store",
  });
  let body = null;
  try { body = await response.json(); } catch { /* handled below */ }
  if (!response.ok) {
    const detail = body?.detail || body?.error || `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}
async function readConfiguration() {
  const ownUrl = new URL(self.location.href);
  const requestedEngine = ownUrl.searchParams.get("engine") || "auto";
  try {
    const response = await fetch("/compute-config.json", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    return {requestedEngine, ...config};
  } catch {
    return {requestedEngine, apiBaseUrl: ""};
  }
}
function usePyodide(reason) {
  report("Using browser calculation", reason);
  const fallback = new Worker("/backtest-worker-v12.js?v=18");
  fallback.onmessage = event => self.postMessage(event.data);
  fallback.onerror = event => self.postMessage({
    type: "error", error: event.message || "Browser calculation worker failed",
  });
  self.onmessage = event => fallback.postMessage(event.data);
}
async function initialize() {
  const config = await readConfiguration();
  if (config.requestedEngine === "pyodide") {
    usePyodide("selected explicitly");
    return;
  }
  const base = config.apiBaseUrl || self.location.origin;
  try {
    report("Connecting to calculation server", base);
    const health = await jsonRequest(apiUrl(base, "/api/v1/health"));
    if (health.schema_version !== 1) throw new Error("Unsupported server schema");
    report("Server calculation ready", health.loaded ? "market cache is warm" : "market data will load on the first run", 1);
    self.postMessage({type: "ready", engine: "server", capabilities: health});
    self.onmessage = event => handleServerMessage(base, event.data);
  } catch (error) {
    if (config.requestedEngine === "server") {
      self.postMessage({type: "error", error: `Calculation server unavailable: ${error.message || error}`});
      return;
    }
    usePyodide(`calculation server unavailable: ${error.message || error}`);
  }
}
async function runServerBacktest(base, data) {
  const created = await jsonRequest(apiUrl(base, "/api/v1/backtests"), {
    method: "POST",
    body: JSON.stringify({schema_version: 1, parameters: data.payload || {}}),
  });
  const statusUrl = apiUrl(base, created.status_url);
  let state = created;
  while (!['completed', 'failed', 'cancelled'].includes(state.status)) {
    report("Server calculation", state.detail || state.stage, null);
    await delay(500);
    state = await jsonRequest(statusUrl);
  }
  if (state.status !== "completed") throw new Error(state.error || state.detail || `Backtest ${state.status}`);
  report("Downloading calculation result", `${state.elapsed_seconds.toFixed(1)} seconds`, 1);
  return jsonRequest(apiUrl(base, created.result_url));
}
async function handleServerMessage(base, data) {
  if (!data || !["run", "inspect"].includes(data.type)) return;
  try {
    const result = data.type === "inspect"
      ? await jsonRequest(apiUrl(base, "/api/v1/inspections"), {
          method: "POST",
          body: JSON.stringify({schema_version: 1, parameters: data.payload || {}, date: data.date || ""}),
        })
      : await runServerBacktest(base, data);
    self.postMessage({id: data.id, result});
  } catch (error) {
    self.postMessage({id: data.id, error: error.message || String(error)});
  }
}
initialize();
