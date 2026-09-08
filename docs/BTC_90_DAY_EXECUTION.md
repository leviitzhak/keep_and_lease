# Long BTC trade replays

The `agent/btc-90day-subsecond` branch extends the previously verified one-day
GUI implementation onto current GitHub master. The live catalog still selects
the June 25 pilot. The 90-day range is **not yet published or activated**: real
1/7/30/90-day performance and deployed acceptance remain required.

## Implemented path

- `scripts/ingest-btc-trade-range.py` downloads and validates each UTC day,
  compares every raw event to Parquet, performs create-only uploads, compares
  the uploaded events to raw inputs, then records a daily receipt. Successful
  uploaded days release local raw/Parquet files. `--assemble-only` requires all
  receipts and publishes the range manifest last. Local ingestion retains daily
  Parquet for replay. Failed conversions never have a completion manifest.
- Range manifests reference immutable, hashed daily manifests. The reader
  rejects missing/overlapping dates and selects only intersecting days. It
  opens one partition per market at a time; warm-up skips spot partitions.
  Within a job, each selected object is checksum-verified once. Remote manifest
  and partition reads are pinned to their recorded GCS object generations.
  The bounded 8 MiB Parquet block cache remains; there is no full-range RAM cache.
- The decision clock, positions, partial fills, pending orders, cash, Treasury
  accrual, smoothing and cumulative statistics remain continuous across days.
  Hourly immutable checkpoints are published after their audit chunks. They
  contain the complete account, cumulative summaries, sampled plot state,
  audit cursor and exclusive event timestamp. All prints at that timestamp
  have been consumed. A restart reads strictly later events and verifies the
  parameter, engine and dataset fingerprint. Checkpoints do not cancel orders.
- A stopped durable trade job can resume through the owner-scoped
  `POST /api/v1/backtests/{id}/resume`. It requires the original deployed
  provenance, a completed checkpoint, and confirmation that the earlier Cloud
  Run execution has terminated. Concurrent resume requests cannot both requeue
  the job. The GUI offers cancellation and resume and retains the job reference
  across page reloads. Failed jobs without a checkpoint require a fresh run.
- Orders/fills and all decision valuations stream directly to the durable audit
  store. Trade chunks use up to 65,536 rows while retaining the 8 MiB byte and
  UTC-day boundaries. This keeps index growth below the former 1,024-row layout.
  Completed audit manifests retain the existing 4 MiB limit. Repeated uploads
  after a crash can reuse only byte-identical immutable objects.
- The direct BTC comparison uses the same causal stream as the strategy. Charts
  remain sampled to approximately 2,000 points; financial summaries use every
  decision valuation. CSV and audit ZIP exports continue to stream complete
  records. Trade XLSX partitioning and asynchronous export jobs are not yet
  implemented; the existing candle spreadsheet path is unchanged.
- Expiring futures settle at their exact expiry, using an archived BTC/USD
  delivery-price record. The downloader records its source URL and response
  digest in the hashed source manifest. The price is applied only at expiry,
  between trades/decisions as needed, never in prior entry signals. Settlement
  cancels the affected order, books the final price change and releases its USD
  proxy collateral. Missing held settlement still fails explicitly. This is
  the existing **regular USD futures proxy**, not native inverse BTC settlement.
  Endpoint specification: [Deribit delivery prices](https://docs.deribit.com/api-reference/market-data/public-get_delivery_prices).

## Operations and activation gates

The new bounded `btc-trade-range.yml` workflow is designed for the permanent
operator branch and this exact request in `.cloud-agent/requests/btc-range.json`:

```json
{"schema_version":1,"action":"ingest-2026-06-06-through-2026-09-03","source_commit":"<full reviewed implementation SHA>"}
```

It ingests `[2026-06-06, 2026-09-04)` as 90 independent daily jobs, at most two
concurrently, using the existing bucket-scoped create/read identity. It accepts
no arbitrary URLs, bucket names, command text or dates. The final job publishes
only after all daily event/checksum gates pass. Artifacts preserve compact daily
receipts/evidence and the final manifest. Re-running failed matrix jobs retains
successful jobs; a fresh workflow invocation does not restore earlier artifacts
automatically. This workflow is not installed on the operator branch merely by
adding it to the application branch.

After publication, run `scripts/benchmark-btc-trade-range.py` in order with
`--days 1`, `7`, `30`, `90`, using the immutable range URI, separate output
folders, and `--interval 0.5`. It runs one continuous full-resolution replay,
checks worker/plot headroom, and records phase timings, RSS, full audit sizes,
chunk hashes and financial summaries. `--gcs-audit` writes research evidence to
unique objects in the already-authorized market bucket; the production worker
continues using the results bucket. Local output needs actual disk capacity.
Resume repeats the same command/output folder. Benchmark reports describe the
current attempt's timing; financial counters include restored history.

Timings distinguish checksum reads, decode/chronological merge, audit encoding/
compression, audit writes and remaining strategy/checkpoint work. Decode timing
includes its nested checksum reads, so those two numbers must not be added.

The server-owned `KEEP_AND_LEASE_TRADE_CATALOG` JSON can pin a verified range
using `id`, `start`, `end`, `uri`, `manifest_sha256`, `maximum_decisions`. Clients
cannot select storage paths. The hard ceiling is 16,000,000 decisions, sufficient
for 90 days at 500 ms (15,552,000 ticks); finer clocks require shorter windows.
Both web and worker must use the same catalog. Terraform exposes
`trade_catalog_json` and `worker_timeout_seconds`; defaults retain the pilot and
1,800-second limit. Do not raise either until staged measurements establish the
necessary worker bound and audit-index headroom. Complete a 90-day private GCP
preview run, check selected-period endpoints, raw/Parquet identity, recovery,
exports and resource limits before treating the full range as available.

## Validation status

Local checks: 23 focused Python tests and 28 HTML/JavaScript tests pass; the
production build and artifact validation also pass. Local synthetic tests pass for midnight recovery with pending orders, exact
financial and complete audit identity, incompatible checkpoints, account JSON
roundtrip and expiry between decision ticks. Existing pure replay tests and GUI
HTML/JavaScript checks also pass. Arrow and FastAPI were unavailable locally;
the package installation was blocked. A required pre-deployment CI job installs
both and runs the Parquet/API/job/audit/recovery suites, without silently
skipping Arrow. No real multi-day benchmark or 90-day acceptance has yet passed.

The initial GitHub push was rejected by automatic approval review. The owner
subsequently explicitly approved the feature push, private GCP preview and
bounded 90-day ingestion workflow. Publication and cloud validation are now
in progress; completed evidence must be recorded before activation.

## Cloud run evidence and staged continuation

The first published implementation is `5712b75f953810115844ad332adfc56dd427faa2`
in [PR #40](https://github.com/leviitzhak/keep_and_lease/pull/40).
[Deployment 34194440773](https://github.com/leviitzhak/keep_and_lease/actions/runs/34194440773)
passed 56 Python checks with Arrow/API dependencies and private rendered GUI
acceptance. The approved [90-day ingestion run 34194533429](https://github.com/leviitzhak/keep_and_lease/actions/runs/34194533429)
is processing daily raw/Parquet/GCS identity gates; June 6 passed first.

`btc-trade-benchmark.yml` can follow that run with the bounded request
`{"schema_version":1,"action":"benchmark-90day-btc-500ms","source_commit":"<reviewed SHA>","ingestion_run_id":34194533429}`
in `.cloud-agent/requests/btc-benchmark.json`. Its initial read-only job waits
up to four hours for that exact operator ingestion workflow to succeed, then
validates and hashes the final 90-day manifest artifact. The four benchmark
stages run strictly in 1/7/30/90-day order; each uses a stable GCS checkpoint ID
across workflow retries. The measurements run on GitHub Actions CPU, so final
Cloud Run acceptance is still required. This continuation does not enable the
90-day catalog, change worker resource limits or merge into master.
