# Deribit PRD 2 percentage point search

This analysis-only runner reads the pinned June 6 through September 3, 2026
90-day BTC archive. It exports all 90 daily manifests and every raw futures
tape for all 51 dates with at least two contracts remaining 60 days from expiry
through the entire UTC day: June 6 through July 26. Later dates do not provide
a pair satisfying that maturity condition in the collected contract universe.
The local replay searches signed target PRD +2 and -2 percentage points for
at least 0.10 BTC synchronized buy/sell fills in one day, starting flat each day.
All source futures are retained on qualifying dates to preserve sampled index
observations. Target and realized execution APR differences are reported separately.

The range, daily manifests and raw tapes are SHA-256 verified, with object
generation pinned for every download. Total input is bounded to 160 MB, each
tape to 20 MB, and the runner to 15 minutes. It changes no market-data object,
IAM policy or application. Existing operator OIDC access is reused; credentials
remain on the runner. Outputs are AES-GCM encrypted to the existing RSA public
key. Public artifacts contain only ciphertext and transfer counts.

Install these files with [skip ci], then submit only this bounded request:
`{"schema_version":1,"action":"read-deribit-2pct-search","sequence":1}`
at `.cloud-agent/requests/deribit-prd-2pct-search.json` on
`agent/cloud-autonomous-access`. The request-only push triggers the read-only
runner without deploying the application. A successful encrypted artifact is
required before the local search is complete.
