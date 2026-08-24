# Changelog

## 2026-08-24 — Direct Cloud Run IAP implementation

- Added foundation-managed IAP API enablement and IAP administration for the
  keyless deployment identity.
- Added direct Cloud Run IAP and additive machine access bindings for the Codex
  operator and deployment identity; human entries remain private in the Google
  Cloud IAP policy.
- Added repository-variable-controlled IAP activation and automatic IAP OAuth
  client audiences for both deployment health checks and the bounded operator.
- Kept activation fail-closed: IAP requires a non-empty client ID and cannot
  coexist with anonymous invocation.
- Left the no-organization OAuth console activation and end-to-end acceptance
  checks as explicit one-time deployment steps.

## 2026-08-23 — Canonical market database cache

- Switched silver, gold, and S&P 500 server loading from legacy ZIP archives to
  their common materialized CSV layout.
- Added a deterministic build-time SQLite cache and process-local decoded cache
  so repeated calculations reuse the same market snapshot without network I/O.
- Removed the truncated `gc.zip` from Cloud Run API and worker images; valid
  gold data now comes from all 214 materialized contract files.

## 2026-08-23 — Approved-user Cloud Run IAP cutover plan

- Documented direct IAP on the existing `run.app` URL as the approved-user browser
  mode: Google sign-in and an explicit allowlist, with anonymous access still
  disabled.
- Defined roles for approved human users, the Codex operator, the deployment health
  check, and the IAP service agent.
- Recorded the no-organization project's one-time External OAuth console setup,
  Terraform resources, `GCP_IAP_CLIENT_ID` variable, and keyless machine-token
  changes.
- Added a safe cutover order, rollback boundary, and acceptance matrix so enabling
  IAP cannot silently break the verified autonomous operator or deployment health
  check.

## 2026-08-23 — Keyless autonomous Cloud Run operator

- Added a dedicated `keep-lease-codex-operator` identity with Cloud Run invoke
  permission only and GitHub impersonation restricted to the permanent operator
  branch.
- Added a bounded GitHub Actions control path for private health/build checks,
  authenticated Playwright GUI screenshots, and fixed-fixture API smoke tests.
- Kept Google credentials out of Codex and GitHub secrets. Because the repository
  is public, rejected arbitrary parameters and omitted raw logs, result bodies,
  internal URIs, execution names, and error text from one-day artifacts.
- Documented the one-time foundation apply, request schema, evidence boundary,
  revocation path, and the need for a private control plane for deeper diagnostics.
- Applied the foundation delta and verified the first autonomous private run:
  health returned `status=ok` on the `cloud-run-job` backend and the GUI rendered
  with HTTP 200 at application version `1.3`, commit `08b583696f52`.
- Fixed the GUI artifact path after the first run revealed that a relative path
  followed Playwright into its isolated temporary directory; the successful rerun
  captured the screenshot and structured browser report.
- Recorded two initial-load HTTP 404 console messages and a `portfolio_series`
  null-reference page error for follow-up; neither prevented the ready server GUI
  from rendering.

## 2026-08-21 — Cloud Run preview inspection and return to private access

- Deployed the unmerged `agent/pure-maturity-multiplier` branch to Cloud Run and
  repaired corrupted strategy and GUI assets discovered in the deployed image.
- Added an explicit, default-false `allow_unauthenticated` manual-workflow input and
  removed automatic backtest submission on a visitor's first page load.
- Temporarily enabled anonymous invocation to inspect the normal browser GUI, then
  redeployed with `allow_unauthenticated=false` and verified that the `run.app` URL
  returns `403 Forbidden` without authentication.
- Restored the deployment workflow to `master` push plus manual dispatch only. The
  branch remains unmerged; selected-user authentication and allowlisting are
  deferred to the next access-control change.

## 2026-08-20 — Pure-maturity scoring multiplier

- Added independent, bounded multipliers that favor shorter long contracts and
  longer short contracts after lease-rate eligibility and boundary scoring.
- Kept both strengths at zero by default for exact ranking compatibility.
- Exposed the controls per commodity and added the multiplier to inspected-day
  score diagnostics.
- Corrected GUI two-anchor boundary and side-specific rate-scale parsing so the
  displayed controls reach the canonical Python engine.
## 2026-08-20 — Cloud Run operator access and publication plan

- Recorded the successful `master` deployment and authenticated private operator
  GUI path through the Cloud SDK proxy.
- Selected direct Cloud Run IAP as the next normal-browser access mode for approved
  Google identities, including the no-organization OAuth setup and deployment
  health-check changes it requires.
- Kept anonymous access deferred until the public GUI is separated from the private
  calculation API and authentication, ownership, quotas, budget controls, and abuse
  protections are implemented and tested.

## 2026-08-20 — First Cloud Run deployment and production trigger

- Enabled the Google Cloud deployment workflow on pushes to
  `agent/google-cloud-run-design` while retaining manual dispatch, allowing the
  private Cloud Run service and calculation Job to be tested before merge.
- Minted the private health-check ID token through a second OIDC auth exchange
  scoped to the deployed Cloud Run URL, because external-account credentials do
  not support `gcloud auth print-identity-token` directly.
- Deployed the private web service and calculation Job from commit `fc4400e9`, then
  verified `status=ok`, application version `1.2`, and the `cloud-run-job` backend.
- Moved the automatic deployment trigger to pushes on `master`; manual dispatch
  remains available for controlled redeployment.

## 2026-08-19 — Durable Cloud Run web and calculation Job implementation

- Replaced process-local cloud execution with transactional Firestore jobs/cache,
  a Cloud Run Job launcher, a one-shot worker, durable heartbeats and stale-lease
  failure states, and Cloud Run execution cancellation.
- Added immutable gzip results in Cloud Storage with create-only writes, CRC32C
  transport checking, SHA-256 provenance, streamed HTTP delivery, stage timings,
  and peak-RSS recording.
- Added separate minimal web and data-bearing worker images, Cloud Run v2 workload
  Terraform in an independent state prefix, least-privilege runtime bindings, and a
  manual GitHub OIDC workflow that deploys digest-qualified images and verifies the
  private health endpoint.
- Retained the in-memory queue for local/Render compatibility and explicitly
  deferred cloud day inspection plus Parquet/DuckDB/Arrow input migration until
  after the first bounded numerical proof.

## 2026-08-19 — Google Cloud Run intermittent-compute design

- Documented a proposed scale-to-zero Cloud Run web service with separately sized,
  durable Cloud Run Job executions for backtests.
- Specified versioned Parquet market data queried through DuckDB/Arrow, immutable
  manifests, compressed result storage, and durable cross-restart job metadata.
- Added resource sizing, usage-cost estimates, least-privilege service identities,
  OIDC deployment, observability, retention, migration steps, acceptance criteria,
  and teardown requirements.
- Kept the existing AWS infrastructure as an alternative. This entry describes the
  initial design; the later entry above records its implementation.

## 2026-08-13 — server-side computation API foundation (1.2)

- Added a versioned, asynchronous CPython API that queues canonical engine runs,
  reports progress and provenance, caches identical completed requests, enforces
  request/result limits, supports cancellation requests, and returns the existing
  result object unchanged.
- Added the existing inspected-day operation to the API without duplicating its
  calculation logic.
- Added a server-first v13 browser adapter with explicit `server`, `pyodide`, and
  automatic modes; the unchanged v12 Pyodide worker remains the fallback.
- Added a Docker image, Render service definition, CORS/configuration support, API
  tests, and updated architecture/current-state documentation.

## 2026-08-11 — legacy cleanup and stopped production default

- Removed the obsolete duplicate `web/` tree, PR #15 standalone preview files,
  and superseded browser workers v9–v11; v12 remains the canonical worker.
- Made the provisioned production EC2 instance default to Terraform desired state
  `stopped` until production deployment is explicitly activated.
- Updated the root README and AWS runbook to match the canonical source layout and
  production lifecycle.

## 2026-08-09 — AWS setup automation and scale-out path

- Added a plan-first Terraform foundation for VPC, production/preview EC2, ECR,
  Systems Manager, repository-scoped GitHub OIDC, and scheduled preview idle stop.
- Added bootstrap, infrastructure lifecycle, and preview-activity scripts plus a
  security/operations runbook that distinguishes automated infrastructure from the
  server API, authentication, container, and deployment work still required.
- Documented a managed ECS/SQS/S3/DynamoDB scale-out alternative and the additional
  durability, idempotency, autoscaling, observability, and migration work it needs.

## 2026-08-03 — server-computation and deployment plan

- Added `CURRENT_WORK.md` as the single updatable pointer to the active unmerged branch, PR, version, and completion scope; the GUI version and commit remain the authority for the deployed revision.
- Planned migration from browser-side Pyodide calculation to a versioned asynchronous server-side CPython API with progress, provenance, limits, caching, and equivalence testing.
- Clarified that server-side CPython is ordinary direct execution of the repository's Python files, contrasted with Pyodide's browser/WebAssembly port.
- Documented a two-EC2 option with an available production service and a shared PR-preview host that starts on deployment and stops after verified inactivity.
- Recorded the billing and wake-up caveats: stopped EC2 compute is not charged, persistent resources still are, and a stopped server requires an external component to start it.
- Added an indicative fixed infrastructure estimate and separated it from production and preview compute usage.

## 1.1

- Display the branch version and exact deployed commit in the GUI header.
- Generate `build-info.json` during deployment so preview freshness is directly verifiable.

## 2026-08-02 — generalized multi-commodity production pipeline

- Fast-forwarded `agent/multi-commodity-preview` to the architectural work in `master`.
- Made `maturity_scoring.py` the single long/short scoring formula; retained helper names only as compatibility adapters.
- Added rate-scale/clipping controls and inspected-day long/short score audits.
- Added global defaults with nested or flat per-commodity overrides.
- Added an independent Treasury/cash allocation, including Treasury-only portfolios.
- Added contract-level observed-versus-frozen-curve attribution and commodity/Treasury maturity scatters.
- Added schema-versioned current and named parameter sets with load, export, import, and reset.
- Made unavailable or corrupt commodity archives non-fatal unless selected.
- Kept the pure maturity multiplier explicitly deferred.

## 2026-07-29

- Limited the active asset selector to silver, gold, Treasuries, and S&P 500.
- Added named strategy presets with automatic suggested names and loading.
- Added independent commodity-specific leg parameter profiles.
- Added inspected-day portfolio composition by commodity, leg, and contract.
- Added a simple-CSV market-data directory and documented current data gaps and
  expected capacity.
- Replaced the damaged gold ZIP with the complete 214-contract archive from its
  original source and materialized those contracts as CSV.
- Refreshed silver/SLV, gold/IAU, S&P 500/SPY, and SHY daily benchmark files
  through July 2026, with coverage and hashes recorded in a manifest.
# 2026-07-29 — common plots, parameter help, and scatter inspection

- Fixed common portfolio plots becoming blank after redraws and period filters.
- Added click/tap explanations beside every strategy parameter.
- Prevented invalid transient numeric values from being saved or submitted.
- Renamed Treasury maturity statistics to explicitly plot observed yield.
- Preserved scatter-specific nearest-point interaction on desktop and mobile.
- Added regression assertions and reproducible GUI specification requirements.
