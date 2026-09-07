# Completed-backtest spreadsheet export

## Design

The detailed spreadsheet is generated from a completed backtest result. Version 1
supports exactly one commodity sleeve and any non-empty selected date interval.
The generator is a declarative JavaScript workbook template rather than a binary
fill-in file: it can size holding rows and columns to the selected result while
keeping formulas, grouped headers, number formats, and checks auditable in source
control.

The workbook has four sheets:

1. `Overview` documents scope, holding-interval timing, futures valuation, book
   definitions, return conventions, and the selected-period summary.
2. `Parameters` records the exact completed-run parameters and expands nested
   commodity parameters.
3. `Daily Holdings` follows the reviewed 1969 workbook architecture. It contains
   one row per holding interval, grouped interval/NAV columns, actual underlying
   spot and normalized index columns, book values reconstructed from attributed
   holdings, independent book roll-forwards, underlying-quoted book returns,
   detailed return contributions, and enough holding groups for the maximum
   simultaneous ledger entries in the selected period. Futures carry zero book
   value after settlement but retain price, quantity, signed notional, spot,
   premium, matched USD rate, lease rate, maturity, and economic P&L. Direct or
   replicating holdings separately show start units, annual expense rate, units
   removed for the expense, end units, gross price P&L, expense, and net economic
   P&L. Unit removal is valued at the interval-end price and preserves the
   strategy's pre-existing net return exactly.
4. `Checks` reconciles holding P&L to source return, formula NAV to engine NAV,
   underlying-price and book returns to total return, detailed holding types to
   total return, holding sums to book roll-forwards, and holding sums to the
   engine's book audit fields.

`public/backtest-workbook-v1.js` is the runtime template and XLSX serializer.
The GUI loads it only when the detailed spreadsheet feature is initialized and
feeds it the already-downloaded completed result, including `holding_ledger`.

## Reference and regression workbooks

- `tests/fixtures/workbooks/full_silver_long_gradual_1969_reference.xlsx` is the
  earlier purpose-built workbook. It is the visual and conceptual reference.
- `tests/fixtures/workbooks/full_silver_long_gradual_1969_golden.xlsx` is the
  reviewed output of template version 1 using the same effective 1969 silver
  parameters. It is the exact opt-in regression fixture.

The saved strategy currently also contains a 100% BTC weight and labels silver
futures as inverse. The historical reference intentionally tests the silver sleeve
only and regular COMEX-style linear futures P&L: the fixture generator sets BTC,
gold, S&P 500, and standalone Treasury weights to zero and sets the silver contract
type to `regular`, while preserving the source strategy file unchanged.

Fast structural tests run with the ordinary JavaScript test suite. The expensive
full-engine comparison is deliberately opt-in and should be run after substantial
engine, ledger, or exporter changes:

```bash
npm run test:workbook-regression
```

An intentional workbook change requires review of the generated workbook and its
`Checks` sheet before replacing the golden fixture.
