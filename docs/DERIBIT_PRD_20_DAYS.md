# Deribit PRD 20-day source export

The analysis-only runner reads 20 full UTC days from the existing immutable
90-day range. The qualifying interval is June 6 through July 26, 2026. Dates
are selected before replay at indices round(i * 50 / 19), i=0..19.
The archive has only one >=60-day contract from July 28 onward. July 27 would
take the September contract below 60 days during that day.
It returns every dated-futures raw tape
on those days, retaining the common sampled index observations and metadata.
The local replay selects contracts still at least 60 days from expiry at day end.

The range manifest, each daily manifest, and each compressed source archive are
SHA-256 verified. Reads pin object generations. Total input is bounded to 160 MB,
individual tapes to 20 MB, and execution to 15 minutes. No market-data object,
IAM policy, application, or deployment is changed. Existing operator OIDC access
is reused; credentials stay on the runner. The output is encrypted to the existing
recipient public key and split into 24 MB ciphertext parts. Public artifacts
contain only ciphertext and transfer counts. Private keys and plaintext never
leave the analysis workspace.

Install with [skip ci], then submit only the new bounded request path:
`{"schema_version":1,"action":"read-deribit-20-full-days","sequence":2}`.
The request-only push triggers this runner without deploying the application.
Success requires a completed workflow artifact, not merely a committed request.
