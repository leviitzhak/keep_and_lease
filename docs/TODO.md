# TODO

This checklist reflects the application synchronized from the deployed Sites checkpoint in PR #16.

## Higher priority

- [ ] Do not activate the lease book for BTC inverse futures when their required
  BTC collateral is itself held idle and earns no yield. In that construction,
  the collateral drag prevents the lease book from being expected to follow the
  strategy's fully collateralized futures-plus-yielding-Treasury principle.
- [ ] Enable BTC as a strategy commodity after the Deribit/Yahoo coverage
  audit passes: apply the implemented native-payoff conversion throughout the
  return and attribution pipeline, expose regular/inverse mode, its fixed
  conversion-fee rate and its minimum accumulated-BTC conversion threshold,
  add seven-day calendar alignment and weekend Treasury accrual, and choose an
  direct-BTC holding label throughout the GUI and exports.
- [ ] Support BTC-only strategies at any execution/rebalancing frequency allowed
  by the available market-data resolution. For intraday Treasury valuation,
  carry forward the latest observable Treasury yield and accrue the Treasury
  position at that yield until the next observable yield becomes available,
  without using future observations or interpolating between daily marks.
- [ ] Investigate why a NAV-reconstruction difference first appears on
  03.01.1985 for the `strategy full silver long gradual` parameter set.

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

- [x] Align the local ChatGPT Sites GUI/API preview with Google Cloud's versioned
  server calculation method: one checkout supplies the GUI and canonical Python
  engine, `/api/v1` is proxied same-origin, and strict server mode prevents a
  silent browser fallback. Publishing Sites against private IAP remains outside
  this local preview loop and would require an authenticated server-side proxy.
- [x] Generate a spreadsheet for a user-selected date interval containing the
  portfolio composition, component values, and component prices.
- [ ] Investigate and explain the performance of the full-silver long strategy.
- [ ] Support separate minimum-days-before-expiry parameters for long and short
  futures positions.
- [ ] Define the extended book independently from the lease book:
  - every long future held by the extended book must mature earlier than every
    short future it holds;
  - the extended book's long-futures maturities do not have to match the
    long-futures maturities selected for the lease book; and
  - select the extension from the eligible subset of shorter maturities using
    the same construction logic as the lease book, including the same trade-off
    between a replicating-fund position and a Treasuries-plus-long-futures
    position. Here, "extension" means an analogous independently selected
    allocation, not a duplication of the lease book's contracts.
- [ ] Replace the current per-commodity standalone-compounded and
  multiplicative-contribution displays with the following decomposition (do
  not display those two existing plot families for now):
  - plot the values of the unextended futures-plus-Treasuries leg, the
    replicating-fund leg, and their sum (the lease book), all quoted in units of
    the underlying commodity;
  - plot the lease book's daily return quoted in the underlying commodity, with
    the lease-book return scaled by its effective leg proportion;
  - compound that lease-book daily-return series into an index starting at 1;
  - plot the corresponding commodity-quoted value, daily return, and compounded
    daily-return index for the keep book;
  - plot the underlying commodity's price evolution; and
  - retain distribution plots for the commodity-quoted daily-return series.
  Verify for every date that the portfolio value can be reconstructed from the
  underlying price index and the compounded sum of the lease- and keep-book
  commodity-quoted daily returns:
  `NAV(t) = P(t) / P(0) * product_s<=t(1 + r_lease(s) + r_keep(s))`.
- [ ] Implement configurable transaction costs on every buy and sell, including
  both explicit fees and simulated bid-ask spread costs.

## Small fixes

- [ ] Fix the maturity-allocation heatmap preview not rendering on the
  persistent Sites deployment.
- [ ] Use thinner bins in the displayed return-distribution histograms.
- [ ] Show hover information on the return-distribution graphs.
- [ ] Populate the GUI's **Saved strategy** dropdown with the strategy files in
  the repository's `strategies` folder.
- [ ] Add full inspection interactivity to the new log-return decomposition
  graphs.
- [ ] Extend the portfolio contribution-by-asset plot so it also shows the
  values of the individual legs within each commodity sleeve.
- [ ] In each commodity's strategy-versus-direct-hold plot, compare the value
  of the strategy leg with the value of a direct holding of the same initial
  quantity of that commodity.
- [ ] Rename labels referring to "held" short futures: the diagnostic short
  selection can be displayed even when the short book is disabled.
- [ ] For each commodity, retain the plots of leg values through time, but hide
  the standalone-compounded and multiplicative-contribution plots for now; the
  commodity-quoted lease/keep decomposition above will replace them.
- [ ] Update the **Maturity-line allocation formulas** section with the current
  signed-score and SoftMax allocation formula.
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

- [ ] **Lower-priority persistent Sites work:** make the persistent Sites
  deployment able to run a backtest and return its results reliably.

- [x] Define and implement the versioned browser-parameters/server-result API described in `DEPLOYMENT_ARCHITECTURE.md`.
- [x] Add an asynchronous in-process backtest job runner with progress, queued/running cancellation semantics, one-worker concurrency, result limits, caching, and provenance.
- [ ] Add full-data CPython-versus-Pyodide equivalence fixtures; the Pyodide v12 worker is retained as an explicit and automatic fallback.
- [ ] Measure warm/cold duration, peak memory, and result size before selecting server capacity.
- [ ] **Lower priority speed improvement:** precompute and version compact
  per-commodity, per-contract quote-availability indexes; persist a reusable
  jointly-priceable compounding-calendar cache keyed by the active commodity
  set, all contract-selection-relevant strategy parameters, market-data
  version, and requested date range. This avoids rerunning interval discovery
  for equivalent backtests without conservatively dropping dates for contracts
  the strategy does not hold.
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
- [ ] **Lowest priority for now:** make the persistent ChatGPT Site operate smoothly and remain verifiable by
  Codex: keep its packaged runtime assets synchronized with the deployed code,
  support reliable owner-authenticated access, and add an end-to-end smoke test
  that runs a strategy and verifies the plots and downloaded spreadsheet.
- [ ] Keep `CHANGELOG.md`, parameter documentation, data manifest, and this checklist current with every durable behavior change.

## Deferred scoring work

- [x] Add the separate pure-maturity multiplier favoring shorter long positions and longer short positions, with a zero-strength backward-compatible default.
