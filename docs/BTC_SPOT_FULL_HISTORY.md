# BTC spot history extension

The 90-day matched tape used **Binance BTCUSDT individual trades**, not aggregate
trades and not Kraken. The pinned original downloader is
`scripts/refresh-btc-trade-pilot.py` at
`5712b75f953810115844ad332adfc56dd427faa2`. It fetches
`https://data.binance.vision/data/spot/daily/trades/BTCUSDT/`.
The retained 90-day range covers 2026-06-06 through 2026-09-04 exclusive (UTC).

This research-only downloader extends the same source over whole UTC days covering
the frozen full-history futures archive. The earliest creation/first-trade date
and latest frozen snapshot/last-trade date determine the plan; future contract
expiry dates do not extend it into unobserved time. Existing 90-day dates are
referenced by their verified range manifest and are not downloaded again.

## Source and storage

- Futures plan: `gs://keep-and-lease-market-data/btc/research/deribit-full-history-v1/jobs/btc-full-20261009-archive/plan-reconciled-v2.json`
- Existing spot range: `gs://keep-and-lease-market-data/btc/trades/ranges/52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912/manifest.json`
- New job prefix: `gs://keep-and-lease-market-data/btc/research/binance-spot-full-history-v1/jobs/<job_id>/`
- Immutable raw ZIP objects: `gs://keep-and-lease-market-data/btc/research/binance-spot-full-history-v1/objects/<sha256>/BTCUSDT-trades-<date>.zip`

Each new day is streamed to bounded temporary disk, checked against Binance's
published SHA256 checksum, and uploaded create-only with GCS CRC32C integrity
checking. The ZIP central directory is inspected; the CSV is not fully parsed in
this acquisition job. A receipt records source URL/checksum, object hash, size,
generation, CRC32C, compressed member metadata and provenance. Resumption checks
the existing receipt and immutable object's metadata before skipping that day.
Completed days survive worker cancellation; an interrupted individual day may be
downloaded again. No existing dataset is overwritten.

Binance cannot be assumed to cover every early futures date. HTTP 404 produces an
explicit `SOURCE_UNAVAILABLE` receipt, not an empty successful trading day. Other
HTTP failures fail the shard, except bounded retries for transient errors.
Gaps remain visible and are never filled with Kraken or synthetic trades. A new
job identifier is required to recheck dates previously recorded unavailable.

## Launch and resume

Install the workflow, script, tests and this runbook with a `[skip ci]` commit on
`agent/cloud-autonomous-access`. Then make a separate request-only commit to
`.cloud-agent/requests/btc-spot-history.json`:

```json
{
  "schema_version": 1,
  "action": "download-binance-spot-missing-history",
  "job_id": "btc-spot-20261022-binance-full",
  "sequence": 1
}
```

The `Download missing BTC spot history` workflow uses the existing keyless GCP
operator identity and storage bucket. It has eight fixed shards, at most two
concurrent workers, and a five-hour work budget per worker (330-minute job limit).
No automatic schedule, unbounded retry loop, application deployment, purchase,
IAM change or trading action is part of this workflow.

To resume a paused/failed job, increment `sequence` with the same `job_id` in a
request-only commit, or rerun the workflow. The frozen plan and daily receipts are
reused. Source checksums are pinned per day; later Binance revisions require a
new ingestion job rather than silently replacing accepted objects.

The durable `attempts/<sequence>/<run_id>-<attempt>/summary.json` records pending
days, unavailable source days, verified days and bytes. `manifest.json` is written
only after every planned date has a receipt. Status is `COMPLETE_RAW_ARCHIVE` or
`COMPLETE_WITH_SOURCE_GAPS`; `PAUSED` and `FAILED_OR_INTERRUPTED` do not claim
completion. Inspect status when requested; do not poll the long download.

## Before strategy use

This is a raw archive acquisition, not a claim of a new replay-ready Parquet
dataset. A subsequent conversion must validate timestamps, IDs, positive prices
and quantities, source gaps and daily coverage, then emit the common spot schema.
Binance spot timestamps are milliseconds before 2025 and microseconds from
2025-01-01 onward. Preserve individual trade identity, buyer-maker side and BTC
quantity. UTC timestamps alone are not unique identifiers.

BTCUSDT remains USDT-quoted; USD valuation requires an explicit conversion or
parity assumption. Trade data does not provide order-book depth or queue position.
The earlier proposal to use full-period Kraken BTCUSD is superseded for this
same-source acquisition. An additional venue would be a separately labeled dataset.

Reference: https://github.com/binance/binance-public-data

Tests: `python -m unittest discover -s research/spot_history -p 'test_*.py' -v`
