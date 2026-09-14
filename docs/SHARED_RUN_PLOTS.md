# Shared daily / trade-replay plots

The `Shared daily / trade-replay plots` panel uses a single catalog and two
read-only adapters in `shared-run-plots.js`. Choose a commodity and plot family.
Only that family is rendered. Switching families releases obsolete chart-registry
entries and canvas bitmaps; the application layout grows to show captions, legends
and the complete chart rather than clipping it to the legacy fixed height.
Existing daily and replay panels, saved results and exports remain available.

## Families

- Performance: normalized strategy/direct NAV, drawdowns from the retained
  history's high-water marks, interval returns and their distribution.
- Holdings/collateral: direct holding, cash/Treasuries, long/short futures,
  target versus actual gross exposure, free collateral and the collateral ratio.
- Activity: traded volume between displayed observations, cumulative turnover,
  recorded costs and oldest held mark age.
- Market: spot/held futures prices, premiums, lease rates and maturities.
- Rates/legs: Treasury yield and accrual/return index, underlying-price index,
  and returns by leg.
- Held-contract scatters: lease rates and premiums against maturity.
- Books: unextended lease components, keep book, commodity-quoted return
  contributions and compounded book indexes.
- Reconciliation: book-return distributions, NAV reconstruction and its error.

Line plots retain the existing desktop hover/click and mobile inspection behavior.
Market-chart tooltips expose recorded held instruments. The observation slider
and previous/next buttons inspect instruments at any displayed point. Existing
chart-period controls filter all shared families. Full-series drawdowns and
cumulative-counter differences are calculated **before** filtering. The drawdown
curve uses the entire retained chart series, not just the selected window; when
that series is sampled, it cannot recover peaks between samples and is not a
replacement for the engine's full-frequency headline maximum drawdown.

## Units and timing

Replay money plots use configured USD capital; NAV plots start at 1. Daily/candle
money plots are values per initial sleeve capital of 1, not an invented funded
USD size. Daily exposures/turnover/costs are recorded at interval start; NAV and
returns are recorded at interval end. The initial daily NAV point is shown.

Replay returns/leg contributions are between displayed valuations. With sampling,
these are not decision-by-decision or calendar-day distributions, and displayed
mean/min/max are not full-frequency risk statistics. Daily book distributions
use all stored interval returns where that separate series exists. Neither
adapter changes the execution frequency or recalculates a strategy.

For replay, the long-only lease book equals NAV: futures variation P&L is already
settled into cash, so futures notional is not added again as an asset. Dividing
cash, direct value and NAV by initial capital and the underlying price index
produces initial-commodity equivalents. The keep/short book is not applicable.
The cash-plus-spot identity is labelled separately from the independent P&L
reconstruction. Daily books use the engine's recorded decomposition.

The collateral ratio is cash/Treasuries divided by **gross** futures notional;
zero notional has no ratio. It is descriptive for daily strategies, not a new
margin requirement. In immediate legacy-close execution the target equals the
modelled actual exposure; delayed/partial candle execution does not fabricate
unrecorded targets. Legacy turnover covers modelled futures trades only; observed
candle and trade replay turnover uses actual simulated fills, not market volume.

Daily per-leg returns retain the engine's leg-specific denominators and are not
additive portfolio contributions. New replay leg contributions use cumulative
spot/futures/interest P&L differences divided by prior displayed NAV; trading costs
remain separate. The Treasury index accrues at each account time transition with
the same observable yield convention, independently of how much cash is held.

## Historical compatibility and boundaries

Older saved results and both completed 90-day benchmarks remain readable. Missing
historical targets, turnover, per-leg P&L, quote ages and instrument snapshots
are **not** filled with zeros or guessed from sampled position changes. Affected
cards explicitly say unavailable. Inactive keep/short books say not applicable.
Existing benchmark NAV/cash/spot data are sufficient for book-value and aggregate
return/reconstruction-identity displays without rerunning the 90-day strategy.

New replay chart points retain sampled instruments and display-only cumulative
P&L/accrual telemetry. Daily counters are accumulated before downsampling. These
additive engine-state fields are checkpointed; source fingerprint changes mean
old checkpoints retain their original engine/data compatibility requirements
for resume or extension. No checkpoint compatibility check is relaxed. Viewing
completed historical results is unaffected and those results remain immutable.

This delivers the shared time-series, distribution and held-contract plot suite.
Full daily curve-attribution scatters, alternative-selection research comparisons,
and decision-frequency annual/leg statistics are not inferred from sampled replay
rows. Those specialised diagnostics remain separately tracked until their needed
full-resolution inputs are retained or explicitly loaded.

The inherited line-chart axis formatter can round small changes to repeated tick
labels, and inherited tooltip precision can also hide tiny changes. The adapter
does not round the stored result values. Adaptive axis/tooltip precision remains
a separate small usability follow-up, not an accounting limitation.

## Validation

Regression tests: `tests/shared-run-plots.test.mjs` and
`tests/test_shared_run_plots.py`. The deployment browser smoke test exercises
both adapters, old benchmark compatibility and mobile rendering. Verified runs,
revisions, evidence and scope limits are recorded in
[SHARED_RUN_PLOTS_VALIDATION.md](SHARED_RUN_PLOTS_VALIDATION.md).
