import { readFile, writeFile } from "node:fs/promises";
import * as fflate from "fflate";

await import("../public/backtest-workbook-v1.js");

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) {
    throw new Error(`Missing required ${name} argument.`);
  }
  return process.argv[index + 1];
}

const resultPath = argument("--result");
const outputPath = argument("--output");
const start = argument("--start");
const end = argument("--end");
const result = JSON.parse(await readFile(resultPath, "utf8"));
const fields = result.portfolio_fields || result.fields || [];
const dateIndex = fields.indexOf("date");
if (dateIndex < 0) throw new Error("Backtest result has no portfolio date field.");
const rows = (result.portfolio_series || result.series || []).filter((row) => {
  const date = row[dateIndex];
  return date >= start && date <= end;
});
if (!rows.length) throw new Error(`No completed holding intervals end between ${start} and ${end}.`);
const period = { start: rows[0][dateIndex], end: rows.at(-1)[dateIndex], rows };
const sheets = globalThis.KeepLeaseWorkbook.buildSheets({ result, period });
const bytes = globalThis.KeepLeaseWorkbook.workbookBytes(sheets, fflate);
await writeFile(outputPath, bytes);
console.log(JSON.stringify({
  output: outputPath,
  start: period.start,
  end: period.end,
  observations: rows.length,
  sheets: sheets.map((sheet) => sheet.name),
}));
