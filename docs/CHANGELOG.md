# Changelog

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
