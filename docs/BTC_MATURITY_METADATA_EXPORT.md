# BTC maturity metadata export

Owner-requested preparation, 2026-10-13. The fixed read-only workflow exports
`manifest.json`, `plan-reconciled-v2.json` and eight completed-shard records for
`btc-full-20261009-archive`. It checks that the records cover every planned
chunk exactly once, and records object generations and SHA-256 hashes. It does
not reverify raw trade objects; the completed archive receipts provide that
evidence. No exchange calls, new download, GCS writes, IAM changes, account
data or credentials are exported.

Install code with `[skip ci]`; then push only
`.cloud-agent/requests/deribit-maturity-inputs.json` with schema version 1,
job ID `btc-full-20261009-archive`, action `export_metadata` and sequence 1.
The request starts **Export BTC maturity metadata** and produces the
`btc-maturity-inputs` artifact. It does not deploy the application. The analysis
and strategy design are maintained on `docs/btc-prd-exposure-band-plan`.
