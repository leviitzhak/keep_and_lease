# Existing BTC futures logical union

The existing **Export BTC maturity metadata** workflow now accepts a second fixed
action through `research/deribit_history/export_maturity_inputs.py`. Install its
reviewed code/tests/descriptor with `[skip ci]`, then push only
`.cloud-agent/requests/deribit-maturity-inputs.json`:

```json
{"schema_version":1,"action":"reconcile-existing-futures-union","sequence":1}
```

No workflow, infrastructure, identity permission or application change is required.
The original metadata-export action remains unchanged. The new action reads only
existing frozen sources through the existing keyless identity. Bounds: 360 seconds
between reads, 450 objects, 64 MB compressed, 100 overlap chunks, 1.2 million raw
rows. The existing workflow timeout is 10 minutes. No exchange downloads, strategy
replay, training, deployment or provisioning occur.

Every fixed 90-day native record must match the canonical full archive by
instrument, trade ID, sequence and execution-relevant fields. Missing records or
conflicts prevent publication. The successful logical manifest references the
full archive once and retains the redundant daily sources as provenance. Existing
archive completion evidence covers non-overlap chunks; these are not freshly
rescanned. Known missing prefixes/gaps are preserved. This is a trade-data union,
not settlement or spot-execution verification.

Immutable verified GCS outputs:
`gs://keep-and-lease-market-data/btc/research/unified-futures-v1/objects/<sha256>/manifest.json`
and `.../results/<sha256>/report.json`. Exact references are returned in logs,
workflow summary and the existing `btc-maturity-inputs` artifact, containing
`manifest.json` and `report.json` for the new action. No automatic polling loop.
