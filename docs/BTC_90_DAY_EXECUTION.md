# Long BTC trade replays

The `agent/btc-90day-subsecond` branch extends the previously verified one-day
GUI implementation onto current GitHub master. The live catalog still selects
the June 25 pilot. The 90-day range is **published and verified, but not yet activated in the GUI**.
Real 1/7/30/90-day performance and full-range deployed acceptance remain required.

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
HTML/JavaScript checks also pass. Arrow and FastAPI were initially unavailable locally;
the dependencies were subsequently installed and the expanded suites pass locally. A required pre-deployment CI job installs
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
completed with 77 successful daily ingestions and 13 failed daily ingestions.
The request-validation job also passed; complete-range publication was skipped.
[Benchmark continuation 34195750155](https://github.com/leviitzhak/keep_and_lease/actions/runs/34195750155)
stopped at the ingestion-success gate; no staged measurements ran.
The later [preview deployment 34195659697](https://github.com/leviitzhak/keep_and_lease/actions/runs/34195659697)
passed 61 Python tests and authenticated GUI acceptance at
`c9e2e58f46ea55a71b286f7d5b85626346ff8cbe`.

`btc-trade-benchmark.yml` can follow that run with the bounded request
`{"schema_version":1,"action":"benchmark-90day-btc-500ms","source_commit":"<reviewed SHA>","ingestion_run_id":34194533429}`
in `.cloud-agent/requests/btc-benchmark.json`. Its initial read-only job waits
up to four hours for that exact operator ingestion workflow to succeed, then
validates and hashes the final 90-day manifest artifact. The four benchmark
stages run strictly in 1/7/30/90-day order; each uses a stable GCS checkpoint ID
across workflow retries. The measurements run on GitHub Actions CPU, so final
Cloud Run acceptance is still required. This continuation does not enable the
90-day catalog, change worker resource limits or merge into master.


## Research policy for discrepant trade records

Status: implemented on the feature branch; production range activation still
requires ingestion, staged measurements and private Cloud Run acceptance.
The downloader archives canonical endpoint responses and a hashed anomaly ledger,
permits documented reversals and endpoint extras, and rejects gaps/conflicting
versions inside its inspected sequence envelope. This does not resolve the
historical cause or recover live arrival order.

### Evidence observed on 2026-09-08

Twelve failed days reported decreasing timestamps in instrument sequence order:
July 21 and 26; August 21-26, 28 and 30; September 2 and 3. June 26 reported
unequal downloaded/checker final sequences for BTC-26JUN26. Its original error
did not include the actual and expected values; "Missing end of trade window"
does not establish which retrieval contained more records.

Fresh public queries returned maximum sequence 2308892 at
2026-06-26 07:58:41.591 UTC in the descending day-filtered response, while a
sequence-range response also contained 2308893 at 08:00:00.048 UTC. These are
observations from later queries, not preserved responses from the failed job.
Archive repeat responses before treating the discrepancy as reproducible.
The extra record is 48 ms after the contract's scheduled 08:00 UTC expiry:
retain it as evidence, but never allow it to fill an expired futures order.

Deribit defines an instrument-local trade sequence, millisecond trade timestamp,
and an optional Starbase causal timestamp. The
[API schema](https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_instrument_and_time)
does not resolve precedence when they disagree. Clock changes, delayed reporting,
or processing differences remain hypotheses. Equal timestamp precision alone
does not explain a backwards timestamp.

### Ingestion and evidence

Preserve original records and fields, including IDs, sequence, timestamps,
prices, amounts and block/combo/Starbase fields. Reconcile the union of records
returned by time and sequence queries, deduplicating only identical records
with the same instrument/trade ID. Preserve conflicting versions for diagnosis;
do not arbitrarily choose a price or volume. Keep checksum, identity, bounded
pagination and coverage checks. Replace the single tail equality assertion
with a recorded comparison of both sets and explicit discrepancy classification.

Do not stop pagination at the first out-of-window timestamp. Establish and
validate sequence coverage independently, inspect adjacent boundary records,
then assign raw records to UTC days by their original timestamp. Reordering
must be bounded in memory, using disk/Parquet batches if necessary. Preserve
all day-boundary dependencies; a fixed overlap alone is not proof of completeness.
A missing sequence remains an unresolved coverage question, not a trade to
invent. Permit documented ordering/endpoint discrepancies in research data;
do not call unresolved coverage gaps a complete lossless 90-day dataset.

Maintain a versioned anomaly ledger with: stable anomaly ID; instrument and UTC
day; all conflicting/neighboring trade IDs and sequences; original timestamp
differences; exact endpoint parameters and retrieval times; pagination flags;
immutable raw-response paths and hashes; classification; chosen treatment;
resolution status and later exchange explanation. Record the smallest failing
reproduction. Where source data are unavailable, record the evidence limitation.

### Two explicit replay scenarios

The default reference scenario preserves sequence order within each instrument.
For each successive sequence, set an additional effective replay timestamp to
the maximum of its original timestamp and the previous effective timestamp.
This delays a backwards timestamp to the last reached time without changing its
raw value. Process equal effective timestamps in sequence order, retaining every
eligible print and its original volume. This is an assumed timeline, not a
reconstructed historical receive timestamp or a guaranteed conservative bound.

The selectable comparison scenario sorts by original trade timestamp, with sequence as a
deterministic instrument-local tie breaker. It assumes the reported event times
are authoritative and that records were observable at those times. That
observability assumption can be false for late reports and must be stated.

Merge instruments by the selected scenario's effective time. Use a documented
deterministic cross-instrument tie rule; instrument-local sequences establish no
global exchange order. Apply the same data-treatment policy to the strategy and
direct-holding comparison. Include the policy version in dataset/result identity,
cache keys, checkpoints and export metadata so scenarios cannot mix on resume.
Carry ordering state through midnight and initialize it before the selected
window; never reset a delayed record backwards at a new day boundary. Select
and audit executions by effective time while retaining raw day membership.

In each scenario, a trade can affect signals, prices or fills only once reached
on that scenario's timeline. Preserve the existing strict order-submission and
execution-delay eligibility rule, participation limits, fees and exclusions.
Do not reuse a same-timestamp print to fill an order generated from that print.
Expiry settlement follows the contract schedule and verified delivery price;
prints at/after expiry, or delayed to expiry, cannot execute that future.
Treasury observations retain their own availability timestamps. No interpolation,
fabricated trades or rewritten original timestamps is introduced.

### Results and acceptance

Run both scenarios over the same continuous period with the same parameters,
decision schedule and eligible trade universe; expiry eligibility differences
caused by delayed effective time must be counted. Compare final NAV/return,
drawdown, fees, turnover, fill quantities and counts, missed executions and
order-level differences. Report anomaly counts by type/instrument/day, affected
volume, largest raw reversal, largest effective delay and delayed/excluded fills.
Attribute differences by linking ledger IDs to affected signals/orders/valuations.
If rolling holding marks or Treasury accrual differs, keep that in the financial
comparison rather than comparing only fills.

Every result and export must identify its ordering assumption and link the
hashed anomaly ledger. A small difference supports robustness only to these
tested scenarios; it does not prove true chronology or bound all reporting
delays. Materiality must be assessed against the strategy's claimed advantage
and execution interval, not selected afterwards to obtain a pass.
Keep the historical cause open for later investigation. Corrected data/policies
produce new immutable versions and new results, preserving prior evidence.

Targeted tests cover reversals across pages and UTC days, equal-time fill
eligibility, endpoint-only records, gaps/conflicting duplicates, Parquet value
and sequence preservation, receipt restoration, and checkpoint/audit identity
with a reversed timestamp. Full real-range acceptance is still pending.

### Implementation details, recovery and remaining limitations

- The time-anchored sequence envelope extends backwards/forwards through a full
  900-sequence neighboring page and validates every sequence within the span.
  It does not stop at the first out-of-window timestamp. Out-of-day records are
  retained in endpoint evidence; selected raw trades remain in sequence order.
  This explicit bounded-envelope assumption is not proof that arbitrarily
  backdated records outside that span do not exist. A day without any anchor
  fails for investigation rather than being declared empty.
- Conversion sorts only futures on disk, retaining the original schema's raw
  timestamp and sequence. The independent raw/Parquet check sorts raw records
  separately. Existing immutable daily Parquet data remain readable.
- `trade_ordering=sequence` (default) builds a temporary SQLite futures index
  over the whole pinned range, seeded with captured pre-range time anchors.
  Its per-instrument prefix maximum crosses midnight and selected-window bounds.
  `trade_ordering=timestamp` streams the original timestamp-sorted partitions.
  Spot streams without a full-range cache in both modes. SQLite page cache is
  8 MiB and its database limit is 512 MiB. Benchmark headroom includes twice
  the ordering database size because Cloud Run temporary files consume memory.
- The GUI exposes both assumptions and delayed-trade counts/max delay. Result
  and audit provenance include policy version, discrepancy summaries and GCS
  evidence references. Fill rows retain reported timestamps and source sequences;
  valuations retain original mark timestamps. Post-expiry prints are excluded
  from execution, with raw/ordering-induced exclusion and delayed-fill counts.
- Each benchmark stage runs both policies with separate immutable audit and
  checkpoint IDs, then emits `comparison.json` with aggregate financial/fill
  differences and evidence links. Automated per-order difference attribution
  remains future work; complete orders/fills are available in each audit.
- The original run retained 77 successful `btc-day-*` artifacts, all unexpired
  when inspected. No failed-day raw artifacts were retained. Restore these
  receipts instead of redownloading successful market data. The new recovery
  workflow computes missing days from restored receipts; its publication job
  combines them with new receipts and verifies all referenced manifest hashes.
  Future failures retain raw/evidence artifacts (`btc-failed-*`) for diagnosis.
  Successful raw and response files upload to immutable content-hashed GCS keys.
- Retained days passed the earlier strict downloader, not the new envelope
  reconciliation. Their per-day source/converter versions remain visible;
  absence of an anomaly ledger for an old day is not a new endpoint-equivalence
  claim. A stricter uniform re-audit can be done later without losing these data.
- Fresh targeted June 26 retrieval passed with 8,280 BTC-26JUN26 records, ending
  at sequence 2308893, and recorded a tail disagreement plus an endpoint-only
  record. Both the extra print and the underlying responses are retained.

The bounded request in `.cloud-agent/requests/btc-recovery.json` is:

```json
{"schema_version":1,"action":"recover-90day-btc","source_commit":"<reviewed full SHA>","reuse_run_ids":[34194533429]}
```

The operator must contain `btc-trade-recovery.yml` and the updated benchmark
workflows before submitting the request. A plain retry of the old run uses its
old pinned source and cannot apply these fixes. Additional completed bounded
recovery run IDs may be included (at most five source runs total) to reuse newly
successful days after a later failed attempt. Neither recovery nor benchmarking
changes the active server catalog or worker timeout automatically.


Local validation of this correction: 71 Python checks (including Arrow/API),
42 JavaScript/HTML checks, and the production build/artifact gate passed.
The targeted July 21 BTC-25DEC26 retrieval retained 3,641 trades, recording one
2 ms timestamp reversal and one sequence-endpoint-only record. These targeted
public-history checks are not the complete 90-day acceptance benchmark.

### Recovery of cloud authentication failures (September 8)

Recovery run 34242246481 completed 11 of the 13 outstanding daily jobs.
August 26 passed raw-to-GCS verification, then failed obtaining an OIDC subject
token while publishing a redundant one-day range manifest. August 28 uploaded
its immutable dataset but failed fetching a token before cloud verification.
Both errors were connection timeouts, not market-data discrepancy failures.
There are 88 preserved completed-day receipts and 89 days with logged passing
cloud verification; August 28 still requires verification.

`recover-btc-uploaded-days.py` pins both daily manifest hashes from those logs,
restores content-addressed raw files from GCS, verifies their hashes and source
identity, and repeats full raw/cloud event comparison before writing receipts.
It never contacts the exchange. The recovery request reuses runs 34194533429
and 34242246481; only the two absent receipts enter the daily matrix.

Daily jobs use `--daily-only`, avoiding redundant range publication. Completed
receipts and evidence are retained even if a subsequent step fails. Cloud
commands retry only recognized transient credential transport failures, at most
three times with 2/4/8-second backoff; integrity and permission failures remain
fatal. Immutable uploads remain create-only and verify existing objects.

The live GUI remains on the pilot until the complete range is published,
paired 1/7/30/90-day benchmarks pass, and the preview catalog and worker limits
are configured and accepted. Engine support does not yet mean a validated live
90-day GUI run. The planned 500 ms interval produces 15,552,000 decisions.

### Completed cloud recovery and publication

[Recovery 34267650300](https://github.com/leviitzhak/keep_and_lease/actions/runs/34267650300)
succeeded on September 8 at 19:19 UTC. August 26 reverified 4,323,107 events;
August 28 reverified 4,862,726 events. All 90 daily receipts are now available.
The published range is:

`gs://keep-and-lease-market-data/btc/trades/ranges/52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912`

Its manifest SHA-256 is the final URI component.
[Preview 34267612174](https://github.com/leviitzhak/keep_and_lease/actions/runs/34267612174)
succeeded at source `5746ecca502ecee22a96d3edc90d20e1f87f9d90`, including
rendered 500 ms/GCS equivalence, CSV, audit, hover and 1 ms fractional-window
acceptance on the pilot. The latest local suite passed 74 tests.
[Paired staged benchmarks 34267691181](https://github.com/leviitzhak/keep_and_lease/actions/runs/34267691181)
follow the successful publication. Full-range benchmark results and GUI catalog/
worker activation remain pending; pilot acceptance is not 90-day acceptance.
