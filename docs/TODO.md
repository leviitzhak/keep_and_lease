# TODO

This checklist reflects the application synchronized from the deployed Sites checkpoint in PR #16.

## Implemented

- [x] Eligibility gates are applied before maturity scoring.
- [x] Long and short linear maturity/rate boundaries are available.
- [x] Boundary distance is normalized, clipped, and applied as a relative score multiplier.
- [x] Short-side signed distance follows `-lease_rate - line`.
- [x] The reusable scoring module implements an independent pure-maturity multiplier with shorter-long and longer-short preferences, separate strengths, neutral zero-strength behavior, diagnostics, and regression tests.
- [x] The deployed browser worker installs the canonical scoring adapter, so active boundary and pure-maturity calculations run through `public/maturity_scoring.py` rather than the legacy helper implementation.
- [x] Per-commodity leg parameters and saved browser strategy presets are available.
- [x] Day inspection shows portfolio composition by commodity, leg, and contract.
- [x] Common plots, calendar-year filtering, synchronized date inspection, and explicit plot diagnostics are implemented.
- [x] Commodity and Treasury maturity scatters are available; Treasury plots use yield.
- [x] Scatter points support hover/click on desktop and tap inspection on mobile.
- [x] Daily hierarchical return attribution reconciles to total return.
- [x] Annual statistics, headline drawdowns, and extreme-return inspection are present.
- [x] Silver, gold, Treasury, and S&P 500 data are organized as plain CSV with a coverage and hash manifest.

## Priority 1 — scoring and attribution correctness

- [ ] Remove the now-inactive legacy maturity scoring helpers from `backtest_silver_lease_strategy.py` after confirming that no external local script imports them directly; keep `public/maturity_scoring.py` as the only implementation.
- [ ] Expose the pure-maturity long and short strength controls visibly in the GUI and persist them independently per commodity. The canonical production adapter already accepts `long_pure_maturity_strength` and `short_pure_maturity_strength` request parameters.
- [ ] Add a complete inspected-day score audit: eligibility threshold, boundary value, signed distance, base timing score, boundary-based relative multiplier, boundary-adjusted score, pure-maturity coordinate and multiplier, final score, caps, and final weight.
- [ ] Verify the one-trading-day execution shift end to end with explicit regression tests.
- [ ] Replace residual lease/basis-change attribution with observed-versus-frozen-curve valuation for every held contract.
- [ ] Add attribution-versus-maturity scatter plots for each commodity and Treasury yield changes.
- [ ] Add no-look-ahead tests that perturb future observations.

## Priority 2 — data

- [ ] Obtain modern individual-contract histories for gold, silver, and S&P 500. Current cross-maturity archives stop in 2002; continuous benchmarks through 2026 cannot replace a maturity curve.
- [ ] Add automated data refresh and structural quality checks to CI.
- [ ] Decide whether large historical CSVs remain directly in Git or move to durable object storage while preserving reproducible manifests.
- [ ] Verify ETF distributions and total-return benchmark treatment.

## Priority 3 — research and usability

- [ ] Add persistent/versioned strategy presets across devices, beyond browser-local storage.
- [ ] Add scenario comparison between saved strategies.
- [ ] Add sensitivity surfaces, walk-forward/out-of-sample evaluation, and transaction-cost/liquidity stress tests.
- [ ] Validate coexistence of short-term long and long-term short books across commodities.
- [ ] Complete previous/next trading-day controls wherever inspection still requires date entry.

## Engineering

- [ ] Add GitHub Actions checks for Python tests, the production build, rendered tests, and artifact validation.
- [ ] Remove obsolete generated worker versions and other duplicated deployment artifacts after confirming the canonical build path.
- [ ] Keep `CHANGELOG.md`, parameter documentation, data manifest, and this checklist current with every durable behavior change.
