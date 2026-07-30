/* Runs the repository's Python backtest entirely in the visitor's browser. */
const PYODIDE_BASE = new URL("/pyodide/", self.location.origin).href;
const DATA_FILES = [
  "gold_silver.zip", "si.zip", "DGS1.csv", "DGS2.csv", "DGS3.csv",
  "DGS5.csv", "DTB3.csv", "DTB6.csv", "backtest_silver_lease_strategy.py",
  "silver_strategy_gui.py", "maturity_scoring.py", "canonical_scoring_adapter.py",
  "rate_change_attribution.py", "gc.zip", "cl.zip", "w.zip", "c.zip", "s.zip",
  "sp.zip", "DCOILWTICO.csv",
];
let pyodide; let stage = "starting"; const runtimeLogs = [];
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function fetchAsset(name) {
  const url = new URL(name, self.location.origin).href;
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(url, {cache: "no-store", credentials: "same-origin"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      runtimeLogs.push(`${name}: ${bytes.byteLength} bytes`);
      return bytes;
    } catch (error) {
      lastError = error;
      runtimeLogs.push(`${name}: attempt ${attempt} failed (${error.message || error})`);
      if (attempt < 3) await delay(300 * attempt);
    }
  }
  throw new Error(`Could not load ${name}: ${lastError && (lastError.message || lastError)}`);
}
function removeLegacyScoringHelpers(bytes) {
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const source = decoder.decode(bytes);
  const start = source.indexOf("def maturity_line_score(");
  const end = source.indexOf("def market_diagnostics_for_day(", start);
  if (start < 0 || end < 0) throw new Error("legacy scoring helper block was not found");
  const canonical = source.slice(0, start) +
    "# Legacy maturity scoring helpers removed from the deployed artifact.\n" +
    "# canonical_scoring_adapter installs the sole production implementation.\n\n" +
    source.slice(end);
  runtimeLogs.push(`canonical strategy source: removed ${source.length - canonical.length} legacy characters`);
  return encoder.encode(canonical);
}
async function verifyRuntimeAsset(name, expectedMinimum, expectedType) {
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
  await verifyRuntimeAsset("pyodide.asm.wasm", 8_500_000, "application/wasm");
  await verifyRuntimeAsset("python_stdlib.zip", 2_400_000, "application/zip");
  importScripts(`${PYODIDE_BASE}pyodide.js`);
  stage = "starting the Python 3.13 runtime";
  pyodide = await loadPyodide({indexURL: PYODIDE_BASE,stdout: line => runtimeLogs.push(`stdout: ${line}`),stderr: line => runtimeLogs.push(`stderr: ${line}`)});
  pyodide.FS.mkdirTree("/data"); stage = "loading historical market data";
  for (const name of DATA_FILES) {
    let bytes = await fetchAsset(name);
    if (name === "backtest_silver_lease_strategy.py") bytes = removeLegacyScoringHelpers(bytes);
    pyodide.FS.writeFile(`/data/${name}`, bytes);
  }
  stage = "building the futures and rate curves";
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
scoring_adapter = load_module("canonical_scoring_adapter", "/data/canonical_scoring_adapter.py")
scoring_adapter.install(strategy, gui)
gui.MARKET = strategy.build_market(Path("/data"))
gui.MARKETS = gui.build_markets(Path("/data"))
  `); self.postMessage({type:"ready"});
}
self.onmessage=async({data})=>{if(!data||!["run","inspect"].includes(data.type))return;try{stage=data.type==="inspect"?"loading the selected market curves":"running the requested backtest";pyodide.globals.set("request_json",JSON.stringify(data.payload||{}));pyodide.globals.set("request_date",data.date||"");const responseJson=await pyodide.runPythonAsync(data.type==="inspect"?`
import json
json.dumps(gui.inspection_for_day(json.loads(request_json), request_date), allow_nan=False)
    `:`
import json
json.dumps(gui.result(json.loads(request_json)), allow_nan=False)
    `);self.postMessage({id:data.id,result:JSON.parse(responseJson)});}catch(error){self.postMessage({id:data.id,error:error.message||String(error)});}};
initialize().catch(error=>self.postMessage({type:"error",error:`${stage}: ${error&&(error.stack||error.message)||String(error)}`+(runtimeLogs.length?`\nRuntime details:\n${runtimeLogs.join("\n")}`:"")}));
