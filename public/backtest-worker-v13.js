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
async function jsonRequest(url, options = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      ...options, signal: controller.signal,
      headers: {"content-type": "application/json", ...(options.headers || {})},
      cache: "no-store",
    });
    if (response.status === 401 || response.status === 403 || response.redirected) {
      throw new Error("Preview sign-in is required or access was denied. Open the preview again to sign in.");
    }
    if (!response.ok) {
      const raw = await response.text();
      let detail;
      try { const body = JSON.parse(raw); detail = body.detail || body.error; } catch { /* HTTP fallback */ }
      const error = new Error(detail
        ? (typeof detail === "string" ? detail : JSON.stringify(detail))
        : `HTTP ${response.status} from ${new URL(url).pathname}`);
      error.retryable = [408, 429, 500, 502, 503, 504].includes(response.status);
      throw error;
    }
    const raw = await response.text();
    if (!raw) throw new Error(`Empty response from ${new URL(url).pathname}`);
    try { return JSON.parse(raw); } catch (error) {
      const type = response.headers.get("content-type") || "unknown content type";
      throw new Error(`Invalid JSON from ${new URL(url).pathname} (${type}). Check preview sign-in. ${error.message}`);
    }
  } catch (error) {
    if (controller.signal.aborted) {
      const timeout = new Error(`Request timed out after ${timeoutMs / 1000}s: ${new URL(url).pathname}`);
      timeout.retryable = true;
      throw timeout;
    }
    if (error instanceof TypeError) error.retryable = true;
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
async function readJobJson(url, jobId, {timeoutMs = 30000, attempts = 5} = {}) {
  for (let attempt = 1; ; attempt++) {
    try { return await jsonRequest(url, {}, timeoutMs); } catch (error) {
      if (!error.retryable || attempt >= attempts) throw error;
      report("Reconnecting to server calculation",
        `Job ${jobId} · ${error.message} · retry ${attempt}/${attempts - 1}`);
      await delay(Math.min(1000 * 2 ** (attempt - 1), 8000));
    }
  }
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
    if (config.browserFallback === false) {
      self.postMessage({type: "error", error: "Browser calculation is unavailable on this deployment. Select the server engine."});
      return;
    }
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
    if (config.requestedEngine === "server" || config.browserFallback === false) {
      self.postMessage({type: "error", error: `Calculation server unavailable: ${error.message || error}`});
      return;
    }
    usePyodide(`calculation server unavailable: ${error.message || error}`);
  }
}
// Retain a disconnected job for a same-parameter retry in this page's worker.
// The server also deduplicates submissions by owner, parameters and provenance.
let pendingBacktest = null;
async function runServerBacktest(base, data) {
  const parameters = JSON.stringify({schema_version: 1, parameters: data.payload || {}});
  let created = pendingBacktest?.base === base && pendingBacktest.parameters === parameters
    ? pendingBacktest.created : null;
  if (data.resumeJobId) {
    if (!/^[a-f0-9]{32}$/.test(data.resumeJobId)) throw new Error("Invalid replay job ID");
    created = await jsonRequest(apiUrl(base, `/api/v1/backtests/${data.resumeJobId}/resume`), {method: "POST"});
    pendingBacktest = {base, parameters, created};
  }
  if (!created) {
    // Never automatically repeat a POST: a lost response may hide a successful submission.
    try {
      created = await jsonRequest(apiUrl(base, "/api/v1/backtests"), {
        method: "POST", body: parameters,
      }, 60000);
    } catch (error) {
      throw new Error(`Could not confirm job submission: ${error.message}. The server may have accepted it; retry with unchanged parameters to recover it.`);
    }
    pendingBacktest = {base, parameters, created};
  }
  const statusUrl = apiUrl(base, created.status_url);
  const jobId = created.job_id;
  try {
    let state = created;
    self.postMessage({type:"jobstate", state});
    report("Server calculation job", jobId);
    while (!['completed', 'failed', 'cancelled'].includes(state.status)) {
      report("Server calculation", state.detail || state.stage, null);
      await delay(Number(state.elapsed_seconds || 0) > 60 ? 5000 : 500);
      state = await readJobJson(statusUrl, jobId);
      self.postMessage({type:"jobstate", state});
    }
    if (state.status !== "completed") {
      pendingBacktest = null;
      throw new Error(state.error || state.detail || `Backtest ${state.status}`);
    }
    report("Downloading calculation result", `${Number(state.elapsed_seconds || 0).toFixed(1)} seconds · job ${jobId}`, 1);
    const result = await readJobJson(apiUrl(base, created.result_url), jobId,
      {timeoutMs: 240000, attempts: 2});
    if (!result || typeof result !== "object" || !result.summary) {
      throw new Error("Calculation server returned a result without a summary");
    }
    pendingBacktest = null;
    return result;
  } catch (error) {
    const recovery = pendingBacktest?.created === created
      ? " The job has not been cancelled. Retry with unchanged parameters to reconnect."
      : "";
    throw new Error(`Job ${jobId}: ${error.message}.${recovery}`);
  }
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
    // Once server execution is selected, preserve its result/error. A browser
    // retry would launch a second calculation and hide the original job status.
    self.postMessage({id: data.id, error: error.message || String(error)});
  }
}
initialize();
