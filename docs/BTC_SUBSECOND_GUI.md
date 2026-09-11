# BTC trade replay in the GUI

Select **BTC market data → Trade replay (research)**, then **Load 500 ms BTC
example**. This loads a five-minute run from 25 June 2026, 00:00–00:05 UTC,
with $100,000 initial capital, 10% participation, and the full-long-gradual rule.
Click **Run strategy**. The example is also saved as
`strategies/research-btc-long-gradual-500ms.json`.

The private preview catalog covers **[2026-06-06 00:00, 2026-09-04 00:00)
UTC**, with a ceiling of 16 million scheduled decisions. Both bounds must stay
inside the server-advertised catalog; empty bounds select its edges. At 500 ms,
the 90 days require 15,552,000 decisions. At 1 ms the same ceiling allows about
4.44 hours, not the whole range. The stable profile keeps the one-day pilot and
200,000 decisions. Unsupported dates/settings fail before worker launch.

The interval must be a positive whole millisecond multiple: `0.001`, `0.1`,
`0.5`, `1`, etc. The GUI displays the current deployment's actual coverage and
ceiling. Full 90-day paired benchmark acceptance is still pending.
The end is always a final valuation boundary, even when it falls between clock
ticks. Prints exactly at the end are excluded. Date inputs and execution delay
preserve milliseconds in saved/imported parameters. Zero interval remains
available only for the existing candle engine's every-observation setting.

## Supported account and signals

- Bitcoin must be the only allocation, without a standalone Treasury sleeve.
- Regular/linear futures proxy, short book disabled, observed/auto execution,
  same-day reactivity, matched-maturity Treasury asset with shortest-rolling
  allocation and accrual valuation. The existing long selection/allocation
  controls and smoothing apply. Other settings fail explicitly.
- Initial capital defaults to $100,000 in the GUI and when an older preset
  omits it. An explicitly saved $1 value remains $1. Volume participation
  applies to the configured funded quantities, not a silent runtime upgrade. Trading fees are charged on actual partial fills.
  Proxy expense, half-spread and slippage must be zero in this version.
- A decision uses only already-observed marks inside the maximum quote age.
  Orders fill strictly after decision time plus the additional delay, using
  same-side aggressor prints and at most the participation fraction of each.
  Equal-timestamp prints cannot fill the newly submitted order. Block, RFQ and
  combo prints can value holdings but cannot fill or create entry signals.
- Each decision cancels/replaces unfilled remainders. Missing fresh signals
  cancel pending orders and retain actual holdings. Stale marks still value
  those holdings, with ending ages disclosed. Expiry without a verified held
  settlement price fails explicitly.
- Each selected window starts a fresh already-owned BTC position at its first
  observed spot trade. Prior futures prints seed causal signals; warm-up is
  disclosed. Treasury cash earns the latest observable yield between events.
  The final account is marked without hypothetical liquidation.

These remain **research assumptions**: Binance USDT/USD is assumed to be 1;
Deribit inverse quotes are used as a regular USD futures price proxy. The model
uses fractional hypothetical lots and 100% marked USD collateral with continuous
cash mark-to-market. Trade prints are not an order book or a guarantee of access
to volume. Native timestamp precision does not establish synchronized feeds,
realistic latency, or one fresh futures price per decision.

## Results, storage and API

The ordinary asynchronous job, owner access, heartbeat, cancellation and result
restoration lifecycle is reused. `btc_trade_backtest.py` streams trades from
the immutable GCS dataset whose manifest SHA-256 is
`52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912`
in preview. The earlier one-day pilot remains archived. The deployment-owned
catalog is returned by `GET /api/v1/trade-data`; requests cannot choose arbitrary
file paths or cloud URLs. The manifest and selected partition hashes are
verified, and result/audit provenance records the dataset and partitions.

Trade runs bypass loading the bundled minute/daily commodity histories. They
read the existing causal Treasury files and bounded Parquet batches. A later
start also reads prior futures prints to establish causal marks; current
checksum verification can therefore read the futures partition twice. Hourly checkpointing, multi-day manifest reads and stopped-job resumption are
implemented in [BTC_90_DAY_EXECUTION.md](BTC_90_DAY_EXECUTION.md); the active
preview catalog now selects the verified 90-day range; full-period performance
acceptance remains pending.

The result has `result_kind=btc_trade_replay`. Its dedicated GUI view shows NAV
versus direct BTC, actual cash/spot/futures exposure, and held-mark ages. Charts
retain roughly 2,000 sampled valuations; every decision valuation is retained
in `btc_trade_valuations`, and all orders, partial fills, cancellations and the
initial holding are retained in `btc_trade_events`. Both use the existing
bounded compressed GCS audit chunks. Full-resolution summary statistics are
computed before chart sampling; drawdowns are measured on decision valuations.

The view offers all-valuation CSV and complete audit ZIP downloads. The CSV
streams from `GET /api/v1/backtests/{job_id}/trade-valuations.csv`, including
exact UTC microseconds, quantities, target quantities, mark IDs/times and NAV
reconciliation. Four appended columns expose `target_futures_notional_usd`,
`free_collateral_usd`, `collateralization_ratio` and `turnover_usd`. Older
audit rows retain blank target/turnover cells when absent. Free collateral
and the ratio are derived only when both cash and actual notional exist;
zero futures notional has a blank ratio. This export never rewrites the
immutable source audit. The existing candle XLSX and book-decomposition charts apply
to candle runs; they are not synthesized from trade results.

Global request parameters are `btc_data_source` (`minute`, default, or
`trade_tape`), `trade_initial_capital_usd`, `execution_interval_seconds`,
`backtest_start` and `backtest_end`. BTC-specific delay, participation, fees,
freshness and long-leg settings use the existing commodity profile. The
calculation worker and standalone API image install pinned Arrow 25.0.0; no market archives are added to images.

## Verification

The full-day one-second GUI runner matches the original pilot's return,
benchmark, trade/decision/fill/order/cancellation counts, interest, fees and
maximum reconciliation error exactly. It processes 5,739,608 events and 47,454
fills, returning −0.10525469949151933% versus −2.102229935492317% direct holding.
The local replay took 67.32 seconds. The five-minute 500 ms example retains 600
valuation intervals and 12,006 events. See `validation/btc-subsecond-local.json`.

Focused tests cover millisecond/fractional clocks, half-open windows, strict
delays, participation, causal pre-window marks, fresh initialization, stale
signals, cancellation, unsupported settings and API rejection before launch.
The deployment workflow additionally runs the rendered GUI on the exact pushed
commit: 500 ms GCS/local equivalence, complete CSV, audit access, chart hover,
and a 1 ms clock with fractional UTC bounds. Deployment status is recorded in
`CURRENT_WORK.md`.

Local checks: 50 focused Python tests and 36 JavaScript/HTML tests passed; the
production build and artifact validation passed. No local Sites preview ran.

The first deployed acceptance passed the 500 ms GCS financial comparison,
complete CSV, audit access and hover. The 1 ms test initially supplied a
noncanonical `.200` datetime fraction which Chromium normalizes to `.2`;
Playwright rejected that redundant trailing-zero representation before running
the strategy. The fixture now uses the canonical form. Its request diagnostics
also distinguish a successfully downloaded CSV from a failed navigation: only
a CSV whose saved content passed row-count verification may ignore the browser
`net::ERR_ABORTED` download-navigation event.

Final private GCP acceptance passed on 7 September 2026 for revision
`ef0000cb294c622d8e8d40973b8c2cb1ca065042`,
[workflow 34149398811](https://github.com/leviitzhak/keep_and_lease/actions/runs/34149398811).
The rendered GUI passed 500 ms/GCS financial equivalence, all 600 CSV valuation
rows, audit access, hover, and a 1 ms decision clock on fractional UTC bounds.
The multi-commodity baseline also passed. The branch is ready for review in
[PR #39](https://github.com/leviitzhak/keep_and_lease/pull/39); it is not merged.

The GUI now takes dates and the decision ceiling from the server catalog and
offers cancel/resume controls for durable trade jobs. Checkpoints are hourly;
runs stopped before the first checkpoint must restart.

## Discrepant trade ordering

The feature branch adds `trade_ordering`, a global saved/API parameter with
`sequence` (default) and `timestamp` values. The GUI selector explains both.
Sequence mode delays backwards timestamps using an instrument-local running
maximum over the pinned futures range; timestamp mode retains reported-time
order. Raw times and IDs are preserved in immutable data and audit provenance.
Neither mode reconstructs historical arrival times. Results show delayed trade
counts and maximum imposed delay; the benchmark workflow compares both modes.
See [BTC_90_DAY_EXECUTION.md](BTC_90_DAY_EXECUTION.md) for anomaly evidence,
coverage assumptions, recovery, memory bounds and remaining acceptance gates.


## Background execution and run history

Click **Run strategy** to save a request and launch its cloud worker. The button
becomes available again after acknowledgement; changing parameters and submitting
another request starts an independent execution. Closing the GUI, disconnecting,
or selecting a different result does not cancel jobs. Cloud quotas still limit
available concurrent resources. The local development backend queues work on one
in-process worker and does not provide cloud durability or parallel execution.

The **Backtests** panel lists this signed-in owner's queued, running, completed,
failed and cancelled jobs, newest first. It refreshes every five seconds and
loads older pages on demand. It shows dates, interval, source, ordering, status,
last progress message, elapsed attempt time and heartbeat age. Percentages are
shown only when the replay reports one; ingestion/preparation stages may be
indeterminate. **Follow progress** selects a queued/running job, reveals its
details in the selected row, and loads its result when complete. Failed and
cancelled jobs instead offer **View details**, which reveals the stopped status,
full run ID, last progress, stage and error where available. The selected details
update on every refresh, including when a followed run fails or is cancelled.
Opening details does not restart a failed job; use **Resume checkpoint** to
request continuation when offered. **View results** switches charts and exports to a completed job;
**Use parameters** explicitly copies its configuration into the form. Editing
the form does not change saved results. The displayed-result label identifies
which run the charts belong to while another run is selected or in progress.

History lives in the deployment's Firestore collection, with results and audits
in GCS. Opening the GUI on another device under the same identity retrieves the
same history automatically. Transient polling failures leave the list intact
and retry; a lost submission response is not blindly posted again. The existing
latest-result startup restoration remains available.

**Cancel** requests worker cancellation. **Resume checkpoint** is offered for
failed/cancelled trade jobs; the server verifies a checkpoint exists, the prior
execution has stopped and the current deployed provenance still matches. If no
checkpoint exists or the engine/image changed, resume is rejected with a reason.
Benchmark CLI runs use separate validation objects and are not GUI-owned jobs.
Cloud history is separate between preview and stable; local browser computation
is not saved into cloud history. Period extension remains a separate CLI feature,
not an alias for Resume.


Saved-run metadata and result retention are separate: the current result bucket
has a 90-day object-deletion lifecycle. Results, audit chunks and checkpoints in
that bucket are not permanent archives; Firestore history may outlive their
objects. Selecting an expired result reports a download failure. Benchmark
validation outputs live in the separate market-data bucket. Changing retention
or adding per-run archival/pinning is not part of this GUI history change.

Private preview acceptance passed for `d06eec62bf18b3e10e54733cae11d6978ffb6f19`
in [workflow 34364647546](https://github.com/leviitzhak/keep_and_lease/actions/runs/34364647546).
Cloud CI passed 93 tests, and 47 JavaScript tests passed locally. Rendered GUI
checks passed the multi-commodity baseline, 500 ms/GCS equivalence, CSV/audit
access, chart hover, a 1 ms fractional window, and reopening the page to select
the earlier completed 500 ms run. The same check verified Run became available
after submission acknowledgement. Full 90-day sequence benchmark recovery has
also passed; timestamp continuation and the paired comparison are still pending.


## Published 90-day benchmarks and period spreadsheets

The Backtests panel includes **90-day BTC benchmark · sequence** and
**90-day BTC benchmark · timestamp**. Select **View results** to open the
completed June 6–September 4 (end boundary) research run without launching a
worker. These fixed published fixtures are separate from owner-scoped GUI jobs;
**Use parameters** copies the benchmark settings for a new run. They retain the
zero-cost baseline, regular-futures price proxy and USDT/USD assumptions.

The strategy/direct-holding chart displays USD values using the original
$100,000 capital. Summary statistics always describe the full run. The replay
section has UTC start/end inputs, **Apply to charts**, **Full period**, and
**Download period spreadsheet**. Chart filtering uses the saved samples; an
interval with fewer than two samples reports that limitation, while its exact
valuation spreadsheet remains available. The Backtests list stays visible.

The XLSX contains Overview, Valuations, Events and Parameters. Both UTC bounds
are inclusive. Every stored valuation and event within those bounds is retained,
including subsecond timestamps, instrument quantities, targets, mark identifiers,
execution prices and fees. Quantities are also numeric columns for the benchmark's
instruments. The first interval's opening NAV can precede the chosen start; its
recorded interval return is retained. Direct BTC value and interval return have
Excel formulas with cached values. Full-run assumptions are included; this is an
export of the original calculation, not a new backtest or a rebased return series.
Futures mark prices were not stored in valuation rows; execution prices are in
Events. JSON columns preserve the complete original nested records.

Only overlapping audit chunks are fetched and their checksums are verified.
The server streams a compressed XLSX with bounded buffers, splitting sheets at
Excel's 1,048,576-row limit. The browser shows MiB received and a cancel button;
it retains the compressed download, not millions of uncompressed JavaScript
rows. There is no fabricated percentage or predeclared final file size. Use short
periods for inspection: large periods can still produce very large downloads.
Requests have a one-hour Cloud Run deadline and at most two simultaneous XLSX
exports per web instance. Cancellation leaves the saved backtest intact.

The API exposes only the two allowlisted fixtures at `/api/v1/benchmarks` and
`/api/v1/benchmarks/{sequence|timestamp}/result`, with audit, CSV and XLSX routes.
XLSX uses `/spreadsheet?start=<UTC>&end=<UTC>`. The same period XLSX endpoint is
available for owner-authorized `/api/v1/backtests/{id}` trade replay jobs.
The web identity receives read-only access restricted to the two published GCS
job prefixes. Foundation Terraform owns the shared identity's conditional binding. The normal
workload deployment account cannot edit market-bucket IAM. An owner must apply
that foundation delta or run `bash scripts/grant-benchmark-read-access.sh` once
from an authenticated Cloud Shell. No additional permissions are granted to the
GitHub deployment account.
Private user jobs cannot be accessed through the benchmark routes.

Chart recovery validates the report's market manifest and parameter hashes,
checks the checkpoint fingerprint, restores historical samples from the last
hourly checkpoint, and reads the final-hour valuation chunks. Its final NAV must
match the completed report. It neither reruns strategy decisions nor changes
existing audit/checkpoint objects. The two recovered results/manifests are cached
per web process. Missing/corrupt objects are reported rather than replaced by
new calculations. Benchmark parameter JSON is packaged with the server and must
continue to match the original report hash.


Live checks on September 10 confirmed access to both real benchmarks, 2,001
chart points per policy, final NAV/report agreement, and a downloaded five-second
XLSX with exactly 11 valuations. The subsequent patch preserves exact microsecond
run endpoints while displaying browser-supported millisecond date inputs. It
also recognizes the attachment request as successful only after independent
workbook validation; other aborted requests still fail the smoke test.


## Shared plots with daily execution

Use **Shared daily / trade-replay plots** below the result, then select a commodity
and plot family. It exposes the common daily/replay suite in either execution
mode, with the existing period controls. Read `SHARED_RUN_PLOTS.md` for sampled
return horizons, initial-capital units and historical fields that were not stored.
Both published 90-day benchmark policies remain completed and viewable; adding
plots does not require repeating their computational backtests.
