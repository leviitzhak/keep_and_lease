# Deribit PRD 20-day source export

The analysis-only runner reads 20 full UTC days from the existing immutable
90-day range, June 6 through September 3, 2026. Days are selected before replay
at indices round(i * 89 / 19), i=0..19. It returns every dated-futures raw tape
on those days, retaining the common sampled index observations and metadata.
The local replay selects contracts at least 60 days from expiry at day start.

The range manifest, each daily manifest, and each compressed source archive are
SHA-256 verified. Reads pin object generations. Total input is bounded to 160 MB,
individual tapes to 20 MB, and execution to 15 minutes. No market-data object,
IAM policy, application, or deployment is changed. Existing operator OIDC access
is reused; credentials stay on the runner. The output is encrypted to the existing
recipient public key and split into 24 MB ciphertext parts. Public artifacts
contain only ciphertext and transfer counts. Private keys and plaintext never
leave the analysis workspace.

Install with [skip ci], then submit only the new bounded request path:
`{"schema_version":1,"action":"read-deribit-20-full-days","sequence":1}`.
The request-only push triggers this runner without deploying the application.
Success requires a completed workflow artifact, not merely a committed request.
