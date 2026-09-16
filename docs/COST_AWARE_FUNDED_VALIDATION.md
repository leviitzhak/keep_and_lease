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
verification. Deployment outcome will be recorded after the workflow completes.

The first preview run (`35071453092`, implementation commit
`a2c89a29b1a12a2c7ee9014c499146581f196fcd`) passed the deployed paired replay,
30-valuation funding/reconciliation assertions and mobile diagnostics, then
exposed a spreadsheet range-validation bug: the actual opening timestamp
preceded the first scheduled audit valuation. The regression fix accepts the
audited opening interval without inventing an opening valuation. Final preview
verification is pending the corrected deployment.
The same verification sequence also exposed an existing replay-extension
default-catalog issue (`KeyError: uri` in the prior master deployment). Extension
seeding now uses the normal runner's default dataset URI when the catalog does
not explicitly override it, with a focused regression check.

This validates implementation and bounded research execution. It is not a
full 90-day performance result, a calibrated expected-return model, measured
order-book executability, native inverse settlement, or proof of profitable
execution. The predeclared development/holdout split and remaining venue/data
acceptance items are in `COST_AWARE_FUNDED_TRANSFERS.md` and `TODO.md`.
