# Deribit PRD pilot source export

This analysis-only runner exports the twelve existing June 6, 2026 Deribit
dated-futures raw archives for a local short fill replay. It uses the existing
operator identity and Storage Object Viewer grant; no IAM, deployment, GUI,
strategy, or market-data object is changed. The request is fixed to one date
and twelve instruments, with byte bounds and SHA-256 checks on every source.

The operator branch contains only this access runner. The replay analysis is
performed locally and delivered as a separate research artifact. Source archives
are encrypted using a recipient RSA public key and AES-256-GCM. Only ciphertext
and non-sensitive transfer counts are uploaded to public Actions artifacts;
no token, private key, raw tape, or private backtest result is uploaded.

Setup is committed with `[skip ci]` to respect the user's analysis-only,
no-deployment instruction. The subsequent request-only commit triggers this
bounded read workflow and is already ignored by the deployment workflow.
The request must equal `{"schema_version":1,"action":"read-deribit-2026-06-06","sequence":1}`.

Input manifests: range `52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912`,
day `3453edcaa03f06151b16970875c9a2278131149cbe2ee164bf0b6e1952313c65`.
The fixed specification preserves source hashes, expiry, and prior seed records.
The execution result is established only by a successful workflow artifact.
