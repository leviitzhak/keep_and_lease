# TODO

This checklist reflects the application synchronized from the deployed Sites checkpoint in PR #16.

## Implemented

- [x] Eligibility gates are applied before maturity scoring.
- [x] Long and short linear maturity/rate boundaries are available.
- [x] Boundary distance is normalized, clipped, and applied as a relative score multiplier.
- [x] Short-side signed distance follows `-lease_rate - line`.
- [x] Per-commodity leg parameters and saved browser strategy presets are available.
- [x] Day inspection shows portfolio composition by commodity, leg, and contract.
- [x] Common plots, calendar-year filtering, synchronized date inspection, and explicit plot diagnostics are implemented.
- [x] Commodity and Treasury maturity scatters are available; Treasury plots use yield.
- [x] Scatter points support hover/click on desktop and tap inspection on mobile.
- [x] Daily hierarchical return attribution reconciles to total return.
- [x] Annual statistics, headline drawdowns, and extreme-return inspection are present.
- [x] Silver, gold, Treasury, and S&P 500 data are organized as plain CSV with a coverage and hash manifest.

## Priority 1 — scoring and attribution correctness

- [x] Use the root Python engine as the canonical implementation and copy it into `public/` only through `scripts/prepare-assets.mjs`; scoring itself has one implementation in `maturity_scoring.py`.
- [x] Add an inspected-day score audit with eligibility, boundary value, signed distance, base score, relative multiplier, final score, and target weight for both sides.
- [x] Verify the one-trading-day execution shift end to end with explicit regression tests.
- [x] Replace residual lease/basis-change attribution with observed-versus-frozen-curve valuation for every held contract.
- [x] Add attribution-versus-maturity scatter plots for each commodity and Treasury yield changes.
- [x] Add no-look-ahead tests that perturb future observations.

## Priority 2 — data

- [ ] Obtain modern individual-contract histories for gold, silver, and S&P 500. Current cross-maturity archives stop in 2002; continuous benchmarks through 2026 cannot replace a maturity curve.
- [ ] Add automated data refresh and structural quality checks to CI.
- [ ] Decide whether large historical CSVs remain directly in Git or move to durable object storage while preserving reproducible manifests.
- [ ] Verify ETF distributions and total-return benchmark treatment.

## Priority 3 — research and usability

- [x] Add schema-versioned current and named strategy presets, including server persistence where available and JSON import/export.
- [ ] Add scenario comparison between saved strategies.
- [ ] Add sensitivity surfaces, walk-forward/out-of-sample evaluation, and transaction-cost/liquidity stress tests.
- [ ] Validate coexistence of short-term long and long-term short books across commodities.
- [ ] Complete previous/next trading-day controls wherever inspection still requires date entry.

## Engineering

- [ ] Define and implement the versioned browser-parameters/server-result API described in `DEPLOYMENT_ARCHITECTURE.md`.
- [ ] Add an asynchronous backtest job runner with progress, cancellation, concurrency limits, and result provenance.
- [ ] Add CPython-versus-Pyodide equivalence fixtures and retain Pyodide as a temporary fallback.
- [ ] Measure warm/cold duration, peak memory, and result size before selecting server capacity.
- [ ] Prototype production and shared PR-preview deployment, including PR-triggered start/deploy and idle preview shutdown.
- [x] Add a plan-first Terraform foundation and AWS operator runbook for the two-host prototype.
- [x] Split GitHub OIDC permissions into master-only production and PR-only preview roles.
- [ ] Implement the Docker image, asynchronous server API, durable activity/job reconciliation, HTTPS/authentication, and GitHub deployment workflows required by `AWS_SETUP.md`.
- [ ] If measured concurrency outgrows two EC2 hosts, implement the ECS/SQS/S3 durable scale-out design and load-test its retry/idempotency behavior.
- [ ] Add GitHub Actions checks for Python tests, the production build, rendered tests, and artifact validation.
- [ ] Remove obsolete generated worker versions and other duplicated deployment artifacts after confirming the canonical build path.
- [ ] Keep `CHANGELOG.md`, parameter documentation, data manifest, and this checklist current with every durable behavior change.

## Deferred to the next scoring change

- [ ] Add the separate pure-maturity multiplier favoring shorter long positions and longer short positions. It is intentionally excluded from the multi-commodity implementation PR.
