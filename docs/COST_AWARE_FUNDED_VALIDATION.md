# Funded paired-transfer implementation validation

Baseline: GitHub master `8205d861b30d869790f97d07941ff6d08e83e981`.
Feature branch: `agent/cost-aware-funded-transfers`.
Local checks completed September 16, 2026.

- The deployment workflow's complete Python gate passed: **219 tests**. This
  includes preserved replay/API/recovery behavior and new funding, economics,
  rates, paired execution, stress, integration and workbook checks.
- GUI, shared-chart and saved-run JavaScript checks passed: **33 tests**.
- Python compilation, browser-smoke script syntax and `git diff --check` passed.
- Integrated synthetic tape runs preserve NAV and full funding, include explicit
  pair IDs, and reproduce uninterrupted financial/audit rows after a real UTC
  midnight checkpoint with delayed feeds/responses and nonzero ticket costs.
- Independent stress cases cover small partial source fills with initial fixed
  fees, VM followed by direct futures roll and reverse transfer, actual versus
  delayed observed marks, custody/spread cost accounting and unmatched timeouts.
- Exact remaining-order forecasts retain the original quantity ratio, child
  execution limits and absolute comparison horizon. Existing ticket charges are
  sunk; future exit fees still use fresh tickets.
- A generated paired replay workbook contains all seven sheets and preserves
  decisions, feasible size/horizon alternatives, incomplete transfers and raw
  source events. The old workbook and chart paths remain covered separately.
- The new FRED snapshot passes checksum and causal freshness checks throughout
  the 90-day market-data period; the old CSV files remain unchanged.

The preview workflow also checks the exact deployed commit, runs its existing
multi-commodity and legacy BTC checks, and now runs a bounded **30-second BTC
paired-policy GUI backtest** with mobile diagnostics and selected-period XLSX
verification. The final deployment outcome is recorded below.

The first preview run (`35071453092`, implementation commit
`a2c89a29b1a12a2c7ee9014c499146581f196fcd`) passed the deployed paired replay,
30-valuation funding/reconciliation assertions and mobile diagnostics, then
exposed a spreadsheet range-validation bug: the actual opening timestamp
preceded the first scheduled audit valuation. The regression fix accepts the
audited opening interval without inventing an opening valuation.
The same verification sequence also exposed an existing replay-extension
default-catalog issue (`KeyError: uri` in the prior master deployment). Extension
seeding now uses the normal runner's default dataset URI when the catalog does
not explicitly override it, with a focused regression check.

The corrected preview run (`35073156588`, commit
`495d8afcdc794347ca86aaa2450ef95cccf22400`) passed the paired GUI, mobile and
spreadsheet checks: 30 valuations, no collateral breaches, and maximum NAV
reconstruction error `1.4551915228366852e-11` USD. This short real-tape window
selected KEEP (zero transfers); synthetic integration tests exercise funded
partial transfers. The final browser assertion exposed an attachment-request classification
issue. A second corrected run (`35074508176`, commit
`4c7fe35470ebedb7d584df6d3103e0a66e5fb375`) repeated the same successful paired
results and verified workbook. The classifier had recorded the workbook's Blob
URL instead of its API request. Both CSV and paired-workbook checks now register
their exact original API paths only after validating the downloaded contents;
unverified failed requests remain errors.

## Successful deployed verification

The full **Deploy Google Cloud workloads** workflow
[35075897193](https://github.com/leviitzhak/keep_and_lease/actions/runs/35075897193)
completed successfully on September 16, 2026, for implementation commit
`d1fb73487e1f9aee42064d57799d55edd8445dd8` on `agent/cost-aware-funded-transfers`.
The private [GCP preview](https://keep-and-lease-preview-web-vfk2j2rgoq-zf.a.run.app/)
was checked against that exact displayed commit and a ready server engine.

- The complete 219-test Python cloud gate passed.
- Authenticated health, rendered multi-commodity GUI, legacy BTC subsecond
  replay, durable run history, charts and published benchmark exports passed.
- The new BTC paired-policy run completed 30 valuations with zero collateral
  breaches and maximum NAV reconstruction error `1.4551915228366852e-11` USD.
  It selected KEEP in this short window. Mobile diagnostics and all paired
  workbook sheets passed download, ZIP and XML verification.
- The completed replay-extension GUI check passed: the parent ended at
  `2026-06-25T01:00:01.000000`, its child resumed from the saved UTC-hour
  checkpoint and reached `2026-06-25T01:00:03.000000` with preserved lineage.

This final documentation-only commit does not redeploy or change the verified
application. The feature remains unmerged pending preview review.

This validates implementation and bounded research execution. It is not a
full 90-day performance result, a calibrated expected-return model, measured
order-book executability, native inverse settlement, or proof of profitable
execution. The predeclared development/holdout split and remaining venue/data
acceptance items are in `COST_AWARE_FUNDED_TRANSFERS.md` and `TODO.md`.
