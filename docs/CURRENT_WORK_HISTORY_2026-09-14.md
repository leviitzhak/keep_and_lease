# Current work

_Update this file whenever active development moves to another branch or pull
request. Other documents link here instead of duplicating a change-specific PR or
branch._

## Active foundation-only change

Branch: `agent/operator-results-reader`, based on `agent/shared-run-plots` at
`989acd51b8895f868e96a7895a84a2d549ce9d8a`. Adds one persistent results-bucket
objectViewer member for the existing operator. Existing market grants and
impersonation restrictions are unchanged. All 13 permission-scope/operator
request-privacy tests passed locally. These are source tests; native Terraform
validation, the live foundation plan and IAM activation remain pending.

No preview/stable deployment or private-run retrieval is part of this change.
See [OPERATOR_RESULTS_ACCESS.md](OPERATOR_RESULTS_ACCESS.md) for activation and
remaining private-diagnostics work. The verified application below is unchanged.

## Latest verified application change

Active branch: `agent/shared-run-plots`, based on the verified TODO batch at
`4674d0601ea3a180d740e89b78bd05e9ac4ce93b`. PR #46 targets
`agent/todo-batch-completion`, not `master`.

Verified application revision:
`8f83983f4493db490f9941130dde86402d1f181d`.

A common catalog now exposes 30 plot definitions in eight families for daily,
candle and trade-replay results. It includes exposures/collateral, activity,
market/rates/legs, held-contract scatters, books/distributions and reconstruction.
Only the chosen commodity/family is rendered. Replaced canvases are released,
mobile layouts are not clipped, and plot-specific inspection handlers survive
redraws. Missing historical fields and inactive books remain explicit.

The 90-day 500 ms research computations and paired comparison are marked done.
A fresh full-period GUI/Cloud Run operational/resource acceptance run remains a
separate pending task. The plotting work did not rerun the 90-day computations.

## Validation and deployment

Integration workflow `34621160549` passed 130 Python regressions, all 72
JavaScript tests, production build/artifact validation and public-mirror checks.
Actual-source Chromium fixtures covered all 16 daily/replay-by-family combinations
with desktop/mobile layout/inspection and no page errors. Before/after synthetic
numerical checks found identical financial summaries, original series fields,
and complete replay event/valuation audit rows.

Both combined preview workflow `34620772208` and the serialized UI-correction
workflow `34621268667` completed successfully. The latter verified the exact
application SHA above, a fresh 4,836-observation multi-commodity run, shared daily
plots, 500 ms and 1 ms replays, all eight replay plot families, mobile/canvas
lifecycle checks, historical benchmark views/exports, and checkpoint extension.

Private preview:
<https://keep-and-lease-preview-web-vfk2j2rgoq-zf.a.run.app/?engine=server>.

See [SHARED_RUN_PLOTS.md](SHARED_RUN_PLOTS.md) for units, sampling and data limits,
and [SHARED_RUN_PLOTS_VALIDATION.md](SHARED_RUN_PLOTS_VALIDATION.md) for evidence.
Specialised curve-attribution/research plots and exact full-frequency annual/leg
statistics remain separate pending work. Existing checkpoint engine/data identity
requirements remain strict. No merge into `master` or stable deployment was made.

## Previous verified work

The preceding four-item TODO batch and partial audit progress were implemented
at `9e367fc295c7930ca4e4689e4e71d4a9d1ff42ad` and verified in preview workflow
`34615894666`; see [TODO_SMALL_BATCH_VALIDATION.md](TODO_SMALL_BATCH_VALIDATION.md).
That earlier batch did not change the financial engine. The current follow-up
adds diagnostic state/result fields but preserves tested financial behavior.

Earlier project history is retained in
[CURRENT_WORK_HISTORY_2026-09-11.md](CURRENT_WORK_HISTORY_2026-09-11.md).
For current data and longer-run evidence, see
[BTC_BACKTEST_DATA_STATUS.md](BTC_BACKTEST_DATA_STATUS.md),
[BTC_90_DAY_EXECUTION.md](BTC_90_DAY_EXECUTION.md), and [TODO.md](TODO.md).
