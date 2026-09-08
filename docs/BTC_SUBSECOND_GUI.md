# BTC trade replay in the GUI

Select **BTC market data → Trade replay (research)**, then **Load 500 ms BTC
example**. This loads a five-minute run from 25 June 2026, 00:00–00:05 UTC,
with $100,000 initial capital, 10% participation, and the full-long-gradual rule.
Click **Run strategy**. The example is also saved as
`strategies/research-btc-long-gradual-500ms.json`.

The uploaded coverage is **[2026-06-25 00:00, 2026-06-26 00:00) UTC**. Both
bounds must stay inside it; empty bounds select its edges. The server rejects
unsupported dates before launching a calculation. It does not interpolate
minute candles or silently substitute a different period/provider.

The interval is a positive whole millisecond multiple: `0.001`, `0.1`, `0.5`,
`1`, etc. There is a limit of 200,000 scheduled decisions per requested window.
At 500 ms the full uploaded day fits; at 1 ms choose at most 200 seconds.
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
- Initial capital is configurable; volume participation therefore applies to
  actual funded quantities. Trading fees are charged on actual partial fills.
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
`9c05efc03118699303e7a55e14205bed29783683a85c165f99319dd3fabc055d`.
Its publication was verified in workflow run `34113031935`. The deployment-owned
catalog is returned by `GET /api/v1/trade-data`; requests cannot choose arbitrary
file paths or cloud URLs. The manifest and selected partition hashes are
verified, and result/audit provenance records the dataset and partitions.

Trade runs bypass loading the bundled minute/daily commodity histories. They
read the existing causal Treasury files and bounded Parquet batches. A later
start also reads prior futures prints to establish causal marks; current
checksum verification can therefore read the futures partition twice. Hourly checkpointing, multi-day manifest reads and stopped-job resumption are
implemented in [BTC_90_DAY_EXECUTION.md](BTC_90_DAY_EXECUTION.md); the active
catalog remains the one-day pilot pending range acceptance.

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
reconciliation. The existing candle XLSX and book-decomposition charts apply
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
