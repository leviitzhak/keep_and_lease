import assert from "node:assert/strict";
import test from "node:test";
import * as fflate from "fflate";

await import("../public/backtest-workbook-v1.js");

const holdingFields = [
  "name", "holding_type", "book", "side", "contract_type", "price",
  "exit_price", "quantity", "end_quantity", "units_expensed",
  "position_pct", "notional_value", "start_value", "end_value",
  "gross_pnl_value", "expense_rate", "expense_value", "pnl_value",
  "internal_transfer_value",
  "spot_price", "exit_spot_price", "premium_pct",
  "matched_usd_rate_pct", "lease_pct", "maturity_days",
];

function holding(values) {
  return holdingFields.map((field) => values[field] ?? null);
}

function cash(book, start, end, internal) {
  return holding({
    name: `${book} cash`, holding_type: "cash", book, side: "cash",
    price: 1, exit_price: 1, quantity: start, start_value: start,
    end_quantity: end, units_expensed: 0, end_value: end,
    gross_pnl_value: 0, expense_value: 0, pnl_value: 0,
    internal_transfer_value: internal,
    spot_price: 100, exit_spot_price: 110,
  });
}

const spreadsheetRows = [
  {
    date: "1969-01-02", exit_date: "1969-01-03", mode: "positive",
    interval_return_pct: 7.4, starting_nav: 1, ending_nav: 1.074,
    slv_price: 100, slv_exit_price: 110,
    lease_book_start_value: 1, lease_book_end_value: 1.074,
    keep_book_start_value: 0, keep_book_end_value: 0,
    lease_book_external_transfer: 0, keep_book_external_transfer: 0,
    holding_ledger: [
      holding({
        name: "Direct silver", holding_type: "direct", book: "lease", side: "long",
        price: 100, exit_price: 110, quantity: 0.006, position_pct: 60,
        end_quantity: 0.006, units_expensed: 0, start_value: 0.6,
        end_value: 0.66, gross_pnl_value: 0.06, expense_rate: 0,
        expense_value: 0, pnl_value: 0.06,
        internal_transfer_value: 0, spot_price: 100, exit_spot_price: 110,
      }),
      holding({
        name: "Treasury collateral", holding_type: "treasury", book: "lease", side: "long",
        price: 100, exit_price: 101, quantity: 0.004, position_pct: 40,
        end_quantity: 0.004, units_expensed: 0, start_value: 0.4,
        end_value: 0.404, gross_pnl_value: 0.004, expense_value: 0,
        pnl_value: 0.004,
        internal_transfer_value: 0, spot_price: 100, exit_spot_price: 110,
        maturity_days: 90,
      }),
      holding({
        name: "SI69K", holding_type: "future", book: "lease", side: "long",
        contract_type: "regular", price: 100, exit_price: 102,
        quantity: 0.004, position_pct: 40, notional_value: 0.4,
        end_quantity: 0.004, units_expensed: 0, start_value: 0,
        end_value: 0, gross_pnl_value: 0.01, expense_value: 0,
        pnl_value: 0.01,
        internal_transfer_value: -0.01, spot_price: 100, exit_spot_price: 110,
        premium_pct: 0, matched_usd_rate_pct: 4, lease_pct: 4, maturity_days: 120,
      }),
      cash("lease", 0, 0.01, 0.01),
      cash("keep", 0, 0, 0),
    ],
  },
  {
    date: "1969-01-03", exit_date: "1969-01-06", mode: "positive",
    interval_return_pct: 100 * (1.13904 / 1.074 - 1),
    starting_nav: 1.074, ending_nav: 1.13904,
    slv_price: 110, slv_exit_price: 121,
    lease_book_start_value: 1.074, lease_book_end_value: 1.13904,
    keep_book_start_value: 0, keep_book_end_value: 0,
    lease_book_external_transfer: 0, keep_book_external_transfer: 0,
    holding_ledger: [
      holding({
        name: "Direct silver", holding_type: "direct", book: "lease", side: "long",
        price: 110, exit_price: 121, quantity: 0.006, position_pct: 61.4525139665,
        end_quantity: 0.006, units_expensed: 0, start_value: 0.66,
        end_value: 0.726, gross_pnl_value: 0.066, expense_rate: 0,
        expense_value: 0, pnl_value: 0.066,
        internal_transfer_value: 0, spot_price: 110, exit_spot_price: 121,
      }),
      holding({
        name: "Treasury collateral", holding_type: "treasury", book: "lease", side: "long",
        price: 101, exit_price: 102.01, quantity: 0.004, position_pct: 37.6163873371,
        end_quantity: 0.004, units_expensed: 0, start_value: 0.404,
        end_value: 0.40804, gross_pnl_value: 0.00404, expense_value: 0,
        pnl_value: 0.00404,
        internal_transfer_value: 0, spot_price: 110, exit_spot_price: 121,
        maturity_days: 87,
      }),
      holding({
        name: "SI69K", holding_type: "future", book: "lease", side: "long",
        contract_type: "regular", price: 102, exit_price: 101,
        quantity: 0.004, position_pct: 37.6163873371, notional_value: 0.404,
        end_quantity: 0.004, units_expensed: 0, start_value: 0,
        end_value: 0, gross_pnl_value: -0.005, expense_value: 0,
        pnl_value: -0.005,
        internal_transfer_value: 0.005, spot_price: 110, exit_spot_price: 121,
        premium_pct: -7.2727272727, matched_usd_rate_pct: 4, lease_pct: 26.1212121212,
        maturity_days: 117,
      }),
      holding({
        name: "lease cash", holding_type: "cash", book: "lease", side: "cash",
        price: 1, exit_price: 1, quantity: 0.01, start_value: 0.01,
        end_quantity: 0.005, units_expensed: 0, end_value: 0.005,
        gross_pnl_value: 0, expense_value: 0, pnl_value: 0,
        internal_transfer_value: -0.005,
        spot_price: 110, exit_spot_price: 121,
      }),
      holding({
        name: "keep cash", holding_type: "cash", book: "keep", side: "cash",
        price: 1, exit_price: 1, quantity: 0, start_value: 0,
        end_quantity: 0, units_expensed: 0, end_value: 0,
        gross_pnl_value: 0, expense_value: 0, pnl_value: 0,
        internal_transfer_value: 0,
        spot_price: 110, exit_spot_price: 121,
      }),
    ],
  },
];

const portfolioFields = [
  "date", "start_date", "interval_return_pct", "start_nav", "nav",
  "silver_contribution_pct",
];
const portfolioRows = spreadsheetRows.map((row) => [
  row.exit_date, row.date, row.interval_return_pct, row.starting_nav,
  row.ending_nav, row.interval_return_pct,
]);
const result = {
  parameters: { weight_silver: "100", weight_treasury: "0" },
  portfolio: { weights: { silver: 1 }, rebalancing: "daily" },
  portfolio_fields: portfolioFields,
  commodity_sleeves: {
    silver: {
      product_label: "Silver",
      holding_fields: holdingFields,
      spreadsheet_rows: spreadsheetRows,
    },
  },
};
const period = {
  start: "1969-01-03", end: "1969-01-06", rows: portfolioRows,
};

test("builds the detailed single-commodity golden-template structure", () => {
  const sheets = globalThis.KeepLeaseWorkbook.buildSheets({ result, period });
  assert.deepEqual(sheets.map((sheet) => sheet.name), [
    "Overview", "Parameters", "Daily Holdings", "Checks",
  ]);
  const daily = sheets[2];
  assert.equal(daily.rows.length, 4);
  assert.equal(daily.freeze.topLeftCell, "F3");
  assert.ok(daily.merges.length >= 9);
  const headers = daily.rows[1].cells.map((cell) => cell.value);
  for (const expected of [
    "Mode",
    "Lease book start — holdings sum",
    "Lease book end — roll-forward",
    "Lease standalone return in underlying",
    "Lease contribution to combined book return",
    "Reconstructed total daily return",
    "Direct gross price contribution",
    "Holding expense contribution",
    "Direct/replicating net contribution",
    "Annual expense rate",
    "Start quantity / units",
    "Units expensed",
    "End quantity / units",
    "Gross P&L before expense",
    "Holding expense",
    "Matched USD rate",
    "Lease rate",
  ]) {
    assert.ok(headers.includes(expected), expected);
  }
  assert.equal(headers.filter((header) => header === "Name").length, 5);
  const calculated = daily.rows[2].cells[headers.indexOf("Calculated holdings return")];
  assert.match(calculated.formula, /^SUM\(/);
  assert.ok(Math.abs(calculated.value - 0.074) < 1e-12);
  const checks = sheets[3];
  const overall = checks.rows.at(-1);
  assert.equal((Array.isArray(overall) ? overall : overall.cells)[1].value, "OK");
});

test("serializes a recalculating xlsx with grouped headers and formulas", () => {
  const sheets = globalThis.KeepLeaseWorkbook.buildSheets({ result, period });
  const bytes = globalThis.KeepLeaseWorkbook.workbookBytes(sheets, fflate);
  const files = fflate.unzipSync(bytes);
  const workbook = fflate.strFromU8(files["xl/workbook.xml"]);
  const daily = fflate.strFromU8(files["xl/worksheets/sheet3.xml"]);
  assert.match(workbook, /name="Daily Holdings"/);
  assert.match(workbook, /fullCalcOnLoad="1"/);
  assert.match(daily, /<mergeCells count="/);
  assert.match(daily, /Lease contribution to combined book return/);
  assert.match(daily, /<f>\(1\+/);
  assert.match(daily, /<autoFilter ref="A2:/);
});

test("rejects multiple commodity sleeves until a portfolio template is defined", () => {
  const multi = {
    ...result,
    commodity_sleeves: {
      ...result.commodity_sleeves,
      gold: { ...result.commodity_sleeves.silver, product_label: "Gold" },
    },
  };
  assert.throws(
    () => globalThis.KeepLeaseWorkbook.buildSheets({ result: multi, period }),
    /exactly one commodity sleeve/,
  );
});

test("streams the same complete workbook without retaining uncompressed worksheets", async () => {
  const sheets=globalThis.KeepLeaseWorkbook.buildSheets({result,period});
  async function* source(){for(const sheet of sheets)yield sheet}
  const blob=await globalThis.KeepLeaseWorkbook.workbookStream(source(),fflate);
  const actual=fflate.unzipSync(new Uint8Array(await blob.arrayBuffer()));
  const expected=fflate.unzipSync(globalThis.KeepLeaseWorkbook.workbookBytes(sheets,fflate));
  assert.deepEqual(actual,expected);
});

test("minute timestamps and signal times survive Excel serialization", () => {
  const rows=structuredClone(spreadsheetRows);
  rows[0].date='2026-06-06T00:01:00';rows[0].exit_date='2026-06-06T00:02:00';
  rows[0].signal_date='2026-06-06T00:00:00';
  const model={...result,commodity_sleeves:{silver:{...result.commodity_sleeves.silver,spreadsheet_rows:[rows[0]]}}};
  const selection={start:rows[0].exit_date,end:rows[0].exit_date,rows:[[rows[0].exit_date,rows[0].date,7.4,1,1.074]]};
  const files=fflate.unzipSync(KeepLeaseWorkbook.workbookBytes(KeepLeaseWorkbook.buildSheets({result:model,period:selection}),fflate));
  const xml=fflate.strFromU8(files['xl/worksheets/sheet3.xml']);
  const serial=ref=>Number(xml.match(new RegExp('<c r="'+ref+'"[^>]*><v>([^<]+)</v>'))[1]);
  assert.ok(Math.abs(serial('B3')-serial('A3')-1/1440)<1e-10);
  assert.ok(Math.abs(serial('A3')-serial('D3')-1/1440)<1e-10);
});

test("execution costs appear in contribution and formula reconciliation", () => {
  const record=structuredClone(spreadsheetRows[0]);
  record.ending_nav-=0.001;record.interval_return_pct-=0.1;record.lease_book_end_value-=0.001;
  const leaseCash=record.holding_ledger[3];
  for(const name of ['end_value','end_quantity','internal_transfer_value'])leaseCash[holdingFields.indexOf(name)]-=0.001;
  record.holding_ledger.push(holding({name:'Execution cost',holding_type:'cost',book:'lease',side:'cash',price:1,exit_price:1,quantity:0,end_quantity:0,start_value:0,end_value:0,gross_pnl_value:0,expense_value:0.001,pnl_value:-0.001,internal_transfer_value:0.001}));
  const model={...result,commodity_sleeves:{silver:{...result.commodity_sleeves.silver,spreadsheet_rows:[record]}}};
  const selection={start:record.exit_date,end:record.exit_date,rows:[[record.exit_date,record.date,record.interval_return_pct,1,record.ending_nav]]};
  const sheets=KeepLeaseWorkbook.buildSheets({result:model,period:selection});
  const headers=sheets[2].rows[1].cells.map(cell=>cell.value),cells=sheets[2].rows[2].cells;
  assert.equal(cells[headers.indexOf('Execution cost contribution')].value,-0.001);
  assert.ok(Math.abs(cells[headers.indexOf('Detailed return difference')].value)<1e-12);
  assert.equal(sheets[3].rows.at(-1)[1].value,'OK');
});
