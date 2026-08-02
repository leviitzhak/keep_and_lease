import { access, copyFile, mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const parentRoot = resolve(projectRoot, "..");
const publicDir = join(projectRoot, "public");
const pyodideDir = join(publicDir, "pyodide");

await mkdir(pyodideDir, { recursive: true });

const repositoryAssets = [
  "gold_silver.zip", "si.zip", "gc.zip", "cl.zip", "w.zip", "c.zip",
  "s.zip", "sp.zip", "DCOILWTICO.csv", "DGS1.csv", "DGS2.csv",
  "DGS3.csv", "DGS5.csv", "DTB3.csv", "DTB6.csv",
  "backtest_silver_lease_strategy.py", "silver_strategy_gui.py",
  "maturity_scoring.py", "rate_change_attribution.py",
];

for (const name of repositoryAssets) {
  let copied = false;
  for (const sourceRoot of [projectRoot, parentRoot]) {
    const sourcePath = join(sourceRoot, name);
    try {
      await access(sourcePath);
      await copyFile(sourcePath, join(publicDir, name));
      copied = true;
      break;
    } catch {
      // Try the next supported source layout.
    }
  }
  if (!copied) {
    await access(join(publicDir, name));
  }
}

const runtimeAssets = [
  "pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm",
  "python_stdlib.zip", "pyodide-lock.json",
];

for (const name of runtimeAssets) {
  await copyFile(
    join(projectRoot, "node_modules", "pyodide", name),
    join(pyodideDir, name),
  );
}

console.log("Prepared market data, Python strategy, and Pyodide runtime assets.");
