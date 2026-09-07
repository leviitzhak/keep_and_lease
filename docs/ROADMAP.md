# Roadmap

## Phase 1 — correctness foundation

- Complete and test execution timing.
- Implement eligibility-first scoring.
- Implement the linear maturity-boundary adjustment with dimensionless relative scaling.
- Add deterministic daily diagnostics and return reconciliation.

**Exit criterion:** a saved configuration reproduces the same positions and returns, and every selected contract has an auditable score trail.

## Phase 2 — inspection-oriented GUI

- Centralize date selection.
- Add synchronized contract-level day inspection.
- Replace hard-coded tables.
- Add robust empty-state and validation messages.
- Add complete commodity and Treasury scatter views.

**Exit criterion:** a user can explain any day's portfolio directly from the GUI.

## Phase 3 — portfolio extensions

- Finalize weighted Treasury maturity selection.
- Extend the commodity framework consistently beyond silver.
- Improve gradual allocation and turnover controls.
- Add configuration versioning and scenario comparison.

**Exit criterion:** multiple strategies and parameter sets can be compared without changing code.

## Phase 4 — research quality

- Add walk-forward and out-of-sample evaluation.
- Add sensitivity surfaces for major parameters.
- Add transaction-cost and liquidity stress tests.
- Add data-version manifests and automated quality reports.

**Exit criterion:** reported performance includes robustness, cost, and data-quality evidence.

## Phase 5 — operationalization

- Move the default calculation path from browser Pyodide to a versioned server-side asynchronous backtest API.
- Serve the same canonical GUI revision in Sites and Google Cloud, and route both
  GUIs to the same versioned calculation API through deployment-specific,
  authenticated configuration.
- Add a strict server mode for published previews: if the API is unavailable,
  report that error visibly instead of silently falling back to browser Pyodide.
- Display and verify the GUI commit, API/engine commit, and selected execution
  engine together.
- Preserve progress logs, result provenance, cancellation, resource limits, and identical-result caching.
- Validate CPython/Pyodide equivalence before retiring the browser fallback.
- Benchmark a two-instance AWS option: normally available production plus a shared, automatically stopped PR-preview host.
- Separate research signals from broker execution interfaces.
- Add dry-run and paper-trading modes.
- Add risk limits, order reconciliation, and monitoring.

Live execution is outside the current backtest milestone and should begin only after the preceding phases are validated.
