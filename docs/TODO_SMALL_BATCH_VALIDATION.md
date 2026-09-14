# Small TODO batch — verified preview

## Revision and scope

- Branch: `agent/todo-batch-completion`.
- Requested base: `agent/current-running-completion` at
  `fbf6bc95dcad8b7e7d690f8210896e993590d683`.
- Application commit: `9e367fc295c7930ca4e4689e4e71d4a9d1ff42ad`.
- Private preview: <https://keep-and-lease-preview-web-vfk2j2rgoq-zf.a.run.app/?engine=server>.
- Verified on September 11, 2026. Subsequent documentation-only commits do not
  change the deployed application revision. No merge into `master` was performed.

Four TODO items are completed: the replay capital default/preservation fix,
additional streamed-CSV collateral fields, thinner histogram bins, and measured
detailed-plot loading progress. A fifth item is partially implemented: ordinary
daily/minute full-audit downloads now have preparation/byte progress and
cancellation. Large trade-replay archives retain native browser downloads; their
in-app progress remains pending. No financial engine, fees, maturity-selection,
extended-book, new-data acquisition or heavy infrastructure changes are included.

## Integration checks

[Integration workflow 34615823054](https://github.com/leviitzhak/keep_and_lease/actions/runs/34615823054)
passed 63 selected Python regression tests, all 61 JavaScript tests, and the
production build/artifact validation. Its artifact
`todo-batch-validation-34615823054` contains all three logs and
`SOURCE_COMMIT.txt` with the exact application SHA above.

The earlier integration attempt `34615675716` failed because canonical public
assets had not been generated before the source/mirror consistency check. The
workflow ordering was corrected, then all checks passed. That failed attempt
neither committed application changes nor deployed a preview.

Five isolated actual-source Chromium checks passed: fresh/default and restored
$1 capital, a 300,000-observation histogram with hover, selected-chunk progress
and cancellation, mid-stream audit-download cancellation, and successful archive
download/control recovery. These used a synthetic page with the actual changed
functions, not a local Sites preview. They are separate from the deployed tests.

## Deployed acceptance

[Deploy Google Cloud workloads 34615894666](https://github.com/leviitzhak/keep_and_lease/actions/runs/34615894666)
completed successfully. This was the only GCP deployment for the combined batch.
The authenticated health and rendered-GUI checks matched the full application
SHA above, with the Cloud Run Job backend and server engine ready.

The deployed tests passed:

- A fresh, non-cached silver/gold/S&P 500/Treasury strategy with 4,836 observations
  and all three commodity lease charts rendered.
- A 500 ms BTC replay with 600 valuations, verified GCS/local financial agreement,
  full CSV download, audit access, chart hover and reopening a saved result.
- A 1 ms replay with fractional UTC bounds and 998 observations.
- Viewing both published 90-day benchmark policies and exporting a selected
  five-second interval to XLSX, with 11 exact valuation rows and formula/ZIP/XML
  validation. These checks viewed existing benchmark results; they did not rerun
  a full 90-day backtest.
- GUI checkpoint extension: a parent ending at `2026-06-25T01:00:01.000000` was
  extended to `2026-06-25T01:00:03.000000`, resuming from the hourly checkpoint at
  `01:00:00`. The parent result remained unchanged.

Evidence artifact: `deployment-smoke-preview-34615894666`, artifact ID
`10270732720`. It includes `gui-report.json`, `gui.png`, `subsecond.json`,
`millisecond.json`, `btc-trade-valuations.csv`, `benchmark-period.xlsx`, and
`extension/extension.json`.

The GUI report has no unhandled page errors and `error: null`. Its raw network
records intentionally include the invalid-date HTTP 400 probe and browser
`ERR_ABORTED` attachment navigations. Attachment exceptions were accepted only
after independently validating the downloaded files; they are not missing CSV
or spreadsheet responses.

## Additional deployed CSV verification

The downloaded 600-row CSV was independently checked after deployment. All four
appended columns were present and populated for the new replay. Every row
satisfied `free_collateral_usd = cash_usd - abs(futures_notional_usd)`; each
nonzero-notional ratio matched `cash_usd / abs(futures_notional_usd)`, while
zero-notional ratios were blank. Cumulative turnover was non-decreasing.

The Python API regression additionally covers old rows, missing primitive
fields, signed notional, zero notional and explicit zeros. Unsupported historical
target/turnover values remain blank, and raw immutable audit rows are unchanged.

## Remaining work

Issues #42, #43 and #44 stay open for their broader scopes. In particular,
parameter regrouping, the complete replay diagnostic suite, daily transaction
cost work, separate long/short expiry limits, independent extended-book
construction and export-work estimates are not implemented by this batch.
Fresh full-period Cloud Run acceptance and explicitly delayed/heavy work remain
as listed in [TODO.md](TODO.md).
