/* Runs the repository's Python backtest entirely in the visitor's browser. */
const PYODIDE_BASE = new URL("/pyodide/", self.location.origin).href;
const DATA_FILES = [
  "gold_silver.zip", "si.zip", "DGS1.csv", "DGS2.csv", "DGS3.csv",
  "DGS5.csv", "DTB3.csv", "DTB6.csv", "backtest_silver_lease_strategy.py",
  "silver_strategy_gui.py", "maturity_scoring.py", "rate_change_attribution.py",
  "gc.zip", "cl.zip", "w.zip", "c.zip", "s.zip", "sp.zip",
  "DCOILWTICO.csv",
];
let pyodide; let stage = "starting"; const runtimeLogs = []; const startedAt = performance.now();
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const elapsed = () => ((performance.now() - startedAt) / 1000).toFixed(1);
function report(message, detail = "", progress = null) {
  const entry = `[+${elapsed()}s] ${message}${detail ? ` — ${detail}` : ""}`;
  runtimeLogs.push(entry);
  self.postMessage({type: "progress", message, detail, progress, elapsedSeconds: Number(elapsed()), entry});
}
async function fetchAsset(name) {
  const url = new URL(name, self.location.origin).href;
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      report(`Downloading ${name}`, `attempt ${attempt} of 3`);
      const response = await fetch(url, {cache: "no-store", credentials: "same-origin"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const total = Number(response.headers.get("content-length")) || 0;
      let bytes;
      if (response.body && total) {
        const reader = response.body.getReader(), chunks = []; let received = 0, lastReport = 0;
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          chunks.push(value); received += value.byteLength;
          if (received - lastReport >= 512 * 1024 || received === total) {
            report(`Downloading ${name}`, `${(received / 1048576).toFixed(1)} / ${(total / 1048576).toFixed(1)} MB`, received / total);
            lastReport = received;
          }
        }
        bytes = new Uint8Array(received); let offset = 0;
        for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      } else {
        bytes = new Uint8Array(await response.arrayBuffer());
      }
      report(`Downloaded ${name}`, `${(bytes.byteLength / 1048576).toFixed(2)} MB`, 1);
      return bytes;
    } catch (error) {
      lastError = error;
      runtimeLogs.push(`${name}: attempt ${attempt} failed (${error.message || error})`);
      if (attempt < 3) await delay(300 * attempt);
    }
  }
  throw new Error(`Could not load ${name}: ${lastError && (lastError.message || lastError)}`);
}
async function verifyRuntimeAsset(name, expectedMinimum, expectedType) {
  report(`Verifying Python runtime asset`, name);
  const response = await fetch(`${PYODIDE_BASE}${name}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${name} returned HTTP ${response.status}`);
  const bytes = await response.arrayBuffer();
  const type = response.headers.get("content-type") || "(missing content-type)";
  runtimeLogs.push(`${name}: ${bytes.byteLength} bytes, ${type}`);
  if (bytes.byteLength < expectedMinimum) throw new Error(`${name} is truncated (${bytes.byteLength} bytes)`);
  if (expectedType && !type.includes(expectedType)) runtimeLogs.push(`warning: ${name} expected content type containing ${expectedType}`);
}
async function initialize() {
  stage = "loading the bundled Python 3.13 runtime";
  report("Starting initialization", "checking deployed runtime assets");
  await verifyRuntimeAsset("pyodide.asm.wasm", 8_500_000, "application/wasm");
  await verifyRuntimeAsset("python_stdlib.zip", 2_400_000, "application/zip");
  importScripts(`${PYODIDE_BASE}pyodide.js`);
  stage = "starting the Python 3.13 runtime";
  report("Starting Python 3.13 runtime", "Pyodide is loading WebAssembly and the standard library");
  pyodide = await loadPyodide({indexURL: PYODIDE_BASE,stdout: line => report("Python", line),stderr: line => report("Python stderr", line)});
  report("Python runtime ready");
  pyodide.FS.mkdirTree("/data"); stage = "loading historical market data";
  // Fetch sequentially: mobile browsers and authenticated Sites can reject a
  // burst of many simultaneous asset requests with an unhelpful TypeError.
  for (let index = 0; index < DATA_FILES.length; index += 1) {
    const name = DATA_FILES[index];
    report("Loading deployed asset", `${index + 1} of ${DATA_FILES.length}: ${name}`);
    pyodide.FS.writeFile(`/data/${name}`, await fetchAsset(name));
    report("Mounted asset in Python filesystem", name);
  }
  stage = "building the futures and rate curves";
  report("Building futures and rate curves", "parsing archives and constructing market histories");
  await pyodide.runPythonAsync(`
import importlib.util, sys
from pathlib import Path
sys.path.insert(0, "/data")
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
strategy = load_module("backtest_silver_lease_strategy", "/data/backtest_silver_lease_strategy.py")
gui = load_module("silver_strategy_gui", "/data/silver_strategy_gui.py")
gui.MARKET = strategy.build_market(Path("/data"))
gui.MARKETS = gui.build_markets(Path("/data"))
  `); report("Initialization complete", "calculation engine and market histories are ready", 1); self.postMessage({type:"ready", logs: runtimeLogs});
}
self.onmessage=async({data})=>{if(!data||!["run","inspect"].includes(data.type))return;try{stage=data.type==="inspect"?"loading the selected market curves":"running the requested backtest";pyodide.globals.set("request_json",JSON.stringify(data.payload||{}));pyodide.globals.set("request_date",data.date||"");const responseJson=await pyodide.runPythonAsync(data.type==="inspect"?`
import json
json.dumps(gui.inspection_for_day(json.loads(request_json), request_date), allow_nan=False)
    `:`
import json
json.dumps(gui.result(json.loads(request_json)), allow_nan=False)
    `);self.postMessage({id:data.id,result:JSON.parse(responseJson)});}catch(error){self.postMessage({id:data.id,error:error.message||String(error)});}};
initialize().catch(error=>{report("Initialization failed", stage);self.postMessage({type:"error",error:`${stage}: ${error&&(error.stack||error.message)||String(error)}`+(runtimeLogs.length?`\nRuntime details:\n${runtimeLogs.join("\n")}`:"")})});
