# Current work

_Update this file whenever active development moves to another branch or pull
request. Other documents link here instead of duplicating a change-specific PR or
branch._

## Active change set

### Shared plots follow-up

Active branch: `agent/shared-run-plots`, based on the verified TODO batch at
`4674d0601ea3a180d740e89b78bd05e9ac4ce93b`. A shared plot catalog now serves daily,
candle and trade-replay results. The 90-day computation/Cloud Run acceptance
checklist distinction is corrected. See `SHARED_RUN_PLOTS.md` for implemented
scope and historical-data limitations. Combined CI/private preview verification
is pending for this follow-up; the deployment evidence below is for the prior
small batch. No merge into `master` has been performed.

### Previous verified small batch

Active branch: `agent/todo-batch-completion`, based on
`agent/current-running-completion` at
`fbf6bc95dcad8b7e7d690f8210896e993590d683`.

Application implementation commit:
`9e367fc295c7930ca4e4689e4e71d4a9d1ff42ad`.

The limited batch completes four TODO items: replay capital defaults/preservation,
backwards-compatible collateral fields in streamed CSVs, thinner histogram bins,
and detailed-plot loading progress. It also adds preparation/byte progress and
cancellation for ordinary daily/minute full-audit downloads. The broader audit
progress item stays open because large trade-replay archives still use native
browser downloads rather than a RAM-buffered JavaScript download.

There are no trading-engine/accounting changes and no full-period benchmark
reruns in this batch. Tasks #42, #43 and #44 remain open for their unimplemented
controls, diagnostics, fee/maturity and export-estimation work. Explicitly delayed
Sites work and heavy engineering remain excluded. No merge into `master` is
part of this implementation.

## Validation and deployment

Integration workflow `34615823054` passed all 63 selected Python regressions,
all 61 JavaScript tests, and the production build/artifact validation. Five
isolated actual-source Chromium fixtures also passed without page errors;
these fixtures are not a substitute for deployed acceptance.

The combined implementation was dispatched once to the private GCP preview in
workflow `34615894666`, after integration passed. Follow-up documentation-only
commits do not redeploy it. The exact preview evidence and remaining limits are
recorded in [TODO_SMALL_BATCH_VALIDATION.md](TODO_SMALL_BATCH_VALIDATION.md).

## Earlier milestones

The complete previous current-work document is retained unchanged in
[CURRENT_WORK_HISTORY_2026-09-11.md](CURRENT_WORK_HISTORY_2026-09-11.md).
It is a historical snapshot, not the current implementation/deployment status.
For the present data inventory and longer-run evidence, see
[BTC_BACKTEST_DATA_STATUS.md](BTC_BACKTEST_DATA_STATUS.md),
[BTC_90_DAY_EXECUTION.md](BTC_90_DAY_EXECUTION.md), and [TODO.md](TODO.md).
