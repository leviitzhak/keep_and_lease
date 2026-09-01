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
- [x] Restore the latest completed Firestore/GCS result and its parameters on GUI
  startup, without recalculation or obsolete state-route requests.
- [x] Display every commodity and Treasury rate-change scatter, filter its points
  with the selected plot period, and show an explicit empty-data state.
- [x] Load the default GUI markets from the canonical materialized/SQLite path
  without probing damaged optional legacy archives.

## Wanted additions

- [ ] Align the ChatGPT Sites GUI and API with the Google Cloud deployment so
  both run the same canonical GUI revision and calculation engine behavior.
- [ ] Generate a spreadsheet for a user-selected date interval containing the
  portfolio composition, component values, and component prices.
- [ ] Investigate and explain the performance of the full-silver long strategy.
- [ ] Support separate minimum-days-before-expiry parameters for long and short
  futures positions.
- [ ] When extending the long book and adding a short book, require the selected
  short maturities to be later than the corresponding long maturities.
- [ ] Refine the daily return decomposition so it reports:
  - the commodity-quoted return of the futures-plus-Treasuries leg and of the
    lease book, with the lease-book return scaled by its effective leg
    proportion;
  - the commodity-quoted return of the keep book; and
  - the total obtained by summing those commodity-quoted returns and compounding
    that sum with the underlying commodity price change.
  Add distribution plots for each of these daily-return series.
- [ ] Implement configurable transaction costs on every buy and sell, including
  both explicit fees and simulated bid-ask spread costs.

## Small fixes

- [ ] Add full inspection interactivity to the new log-return decomposition
  graphs.
- [ ] Update the maturity-weight selection documentation to describe the signed
  score followed by SoftMax that is now used.
- [ ] Keep the displayed name of the currently loaded or saved parameter set
  synchronized with the values in the parameter fields.

## Other requested features

- [ ] Add a scatter plot of lease rates scaled to a daily horizon versus the
  corresponding daily return quoted in the commodity.

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

- [x] Define and implement the versioned browser-parameters/server-result API described in `DEPLOYMENT_ARCHITECTURE.md`.
- [x] Add an asynchronous in-process backtest job runner with progress, queued/running cancellation semantics, one-worker concurrency, result limits, caching, and provenance.
- [ ] Add full-data CPython-versus-Pyodide equivalence fixtures; the Pyodide v12 worker is retained as an explicit and automatic fallback.
- [ ] Measure warm/cold duration, peak memory, and result size before selecting server capacity.
- [x] Add a fixed two-service Render preview definition and GitHub deploy-hook
  workflow that deploys and verifies the same commit on the GUI and API.
- [x] Provision the fixed Render services and configure their deploy-hook secrets
  and public URL variables using `RENDER_FIXED_PREVIEW.md`.
- [ ] Set the existing Render GUI health-check path to `/` and the API health-check
  path to `/api/v1/health`; the workflow already verifies both public endpoints.
- [ ] Prototype production and shared PR-preview deployment with isolated
  per-PR resources and idle preview shutdown if fixed shared preview is no longer
  sufficient.
- [x] Add a plan-first Terraform foundation and AWS operator runbook for the two-host prototype.
- [x] Split GitHub OIDC permissions into master-only production and PR-only preview roles.
- [ ] Extend the implemented Docker image and asynchronous API with durable activity/job reconciliation, HTTPS/authentication, and GitHub deployment workflows required by `AWS_SETUP.md`.
- [x] Implement the Google Cloud durable Firestore job/cache repository, immutable
  gzip result adapter, Cloud Run Job launcher/cancellation, worker heartbeat and
  stale-lease reconciliation, separate web/worker images, workload Terraform, and
  keyless immutable-digest deployment workflow.
- [x] Apply the Google Cloud foundation IAM delta and deploy the private Cloud Run
  workloads with an authenticated health check.
- [ ] Complete the bounded numerical, cancellation, cache-reuse, and
  container-replacement acceptance tests in `GOOGLE_CLOUD_RUN_SETUP.md`.
- [x] Implement direct Cloud Run IAP, private manual human/machine allowlist
  instructions, and dual-mode keyless deployment/operator token audiences.
- [ ] Complete the one-time no-organization OAuth activation, manually add approved
  humans plus the operator and deployment identities in the Google Cloud IAP
  policy, set the `GCP_IAP_*` repository variables, deploy the IAP cutover, and
  verify the full acceptance
  matrix; keep anonymous Cloud Run invocation disabled in the meantime.
- [ ] Move calculation-ready cloud inputs from the worker image to versioned
  Parquet/DuckDB/Arrow objects and restore durable cloud day inspection.
- [ ] If measured concurrency outgrows two EC2 hosts, implement the ECS/SQS/S3 durable scale-out design and load-test its retry/idempotency behavior.
- [ ] Add GitHub Actions checks for Python tests, the production build, rendered tests, and artifact validation.
- [ ] Prefer GitHub's ID-based `noreply` identity for future GitHub API/web and
  command-line commits; leave existing public commit history unchanged unless a
  separate history-rewrite decision is made.
- [ ] Remove obsolete generated worker versions and other duplicated deployment artifacts after confirming the canonical build path.
- [ ] Keep `CHANGELOG.md`, parameter documentation, data manifest, and this checklist current with every durable behavior change.

## Deferred scoring work

- [x] Add the separate pure-maturity multiplier favoring shorter long positions and longer short positions, with a zero-strength backward-compatible default.
