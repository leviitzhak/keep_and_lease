# Full available BTC dated-futures history

Data-only operator workflow on `agent/cloud-autonomous-access`. Uses the existing
keyless operator identity and `keep-and-lease-market-data` bucket. No application
deployment, strategy, GUI catalog activation, schedule, or account trading.

## Scope
Discover expired and active dated inverse BTC futures from Deribit's historical
archive, preserve catalog metadata, and freeze each instrument's first/last
available sequence before starting workers. Raw native trades and API response
evidence are retained, including index_price, block/combo flags and timestamp
reversals. This is the project's BTC dated-futures universe; perpetuals, options,
linear USDC futures, order books, and other exchanges are outside this job.

No artificial start date is imposed. A recent-only catalog fails validation.
The earliest available trade and any missing initial sequence prefix are recorded.
"Complete" means all contiguous sequences within archive-reported availability,
not a claim that the exchange archive contains every historical record.
Each active instrument is frozen separately, so the snapshot may contain its
partial launch day and is not a common simultaneous timestamp cutoff.

## Submit and resume
Request path: `.cloud-agent/requests/deribit-full-history.json`.
Required fields: schema_version=1, action=validate or download,
job_id=btc-full-YYYYMMDD-<suffix>, and positive integer sequence.
A request-only push triggers **Download full BTC futures history** and is ignored
by application deployment. Install code/workflow/docs using a separate
`[skip ci]` commit before submitting a request.

Run `validate` first: unit tests, historical catalog and two earliest available trade records,
then a small immutable GCS write/read probe. It does not start the bulk download.
Run `download` with the intended job ID to freeze the plan and launch eight
deterministic shards, at most two running simultaneously.

Persistent root:
`gs://keep-and-lease-market-data/btc/research/deribit-full-history-v1/`
Job plan, receipts, attempts, completed shard records, and final manifest:
`jobs/<job_id>/`. Compressed raw objects: `objects/<sha256>/`.

Each chunk holds up to 10,000 consecutive trade sequences. Requests start with
1,000 records and use `include_old=true`. Archive timeouts (including HTTP 400
with code 13888) reduce the requested count, down to 100, with bounded backoff.
Interrupted response bodies (`IncompleteRead`), disconnects, connection resets,
and invalid/truncated JSON also retry the same sequence with a smaller page.
Requests have at most seven attempts; retry exhaustion remains a real failure
and preserves the exception type and request parameters in failure evidence.
Other permanent HTTP errors retain the error body and fail explicitly.
See Deribit's institutional setup guide, Historical Data section:
https://statics.deribit.com/files/DeribitInstitutionalSetupGuide.pdf.

Policy `archive-reconcile-v2` treats API sequence bounds as hints. It collects by
returned sequence, discards out-of-chunk records only from the selected trade file
(the complete response remains in evidence), deduplicates identical overlaps,
and seeks again when a shifted page misses the next sequence. Conflicting records,
wrong instruments and unresolved gaps remain fatal for that chunk. A chunk is
complete only when every expected sequence has exactly one consistent record.

Raw finite zero/negative or missing numeric fields are preserved unchanged.
`anomalies.jsonl.gz` identifies affected trade IDs/sequences, field-specific flags,
and `eligible_for_execution=false`. Such records must not supply simulated fill
capacity. Non-finite JSON values are rejected. This does not activate these raw
research files in any GUI or backtest.

Failed chunks persist API responses and errors under `failure-evidence/<sha256>`;
attempt reports link the evidence object. A failed chunk never gets a COMPLETE
receipt. Isolated source-data failures do not prevent trying later chunks.
Ten consecutive operational failures still stop a worker; the work-time limit
also remains in force. Upload content-addressed objects
and verify downloaded bytes before committing the immutable receipt. On resume,
verify existing receipt/object hashes and skip its API download. Incomplete
chunks retry. Sequence gaps fail rather than silently skipping records.

Workers check a 300-minute work budget between chunks (330-minute Actions timeout).
If work remains without chunk failures, they save a `PAUSED` attempt report with
reason `work_time_budget` and exit successfully. Logs and the Actions job summary
state that the archive is not yet complete. Actual chunk failures still produce
`INCOMPLETE` and a failing worker, even if its time budget also expires.
The finalizer accepts only completed shard records or clean pause reports from
the current run attempt. A paused run writes `attempts/<run>-<attempt>/summary.json`
and no final manifest; Actions success means the bounded attempt ran cleanly,
not that all history has been downloaded.

Resume with a new request using the same job ID and an incremented sequence.
This uses the latest installed code and retries chunks without valid receipts.
No automatic agent monitoring or recurring retry loop.
Storage persists independently of GitHub Actions runner lifetime.
The final manifest exists only after all eight shards have completed.

Verification:
`python -m unittest discover -s research/deribit_history -p test_full_history.py -v`.
Tests cover gaps, timestamp reversals, sharding, resume skips, atomic publication,
failed uploads and corrupt stored data. Recovery tests additionally cover shifted
windows, out-of-range extras, identical/conflicting duplicates, genuine unresolved
gaps, numeric anomaly retention, timeout-driven smaller pages and durable failure
evidence.
Transport/pause tests cover interrupted response recovery, retry exhaustion,
durable pause reports, real failures at the time boundary, rejection of stale or
missing reports, and withholding the final manifest until every shard completes.

## October 9 recovery
The first bulk attempt saved 183 verified chunks (1,685,145 trades), then stopped
on archive window shifts, zero-amount records and server query timeouts. Recovery
keeps the same job ID and storage root. The original plan remains immutable.
`plan-reconciled-v2.json` adds corrected expired-contract tail boundaries: the
maximum of the original last sequence and a descending tail sample of up to 1,000 records.
Per-instrument boundary receipts make this preparation resumable. Active-contract
cutoffs remain frozen. Existing full chunks retain their keys; only a changed
final partial chunk needs a new receipt. This bounded tail check does not prove
absence of arbitrarily misplaced archive records.
Previously verified chunks whose bounds are unchanged remain compatible and are reused. Submit a new
request-only push after installing the fix: GitHub's rerun button on the original
failed run would execute the old code revision.

Recovery verification: 19 local unit tests pass. Four live previously failing
ranges passed with complete selected sequence coverage: BTC-29SEP17 30001-40000
(11 API attempts), BTC-29DEC17 50001-60000 (10 attempts; one zero-amount row
preserved), BTC-30MAR18 1-10000 (11 attempts), and BTC-29SEP17 350001-359794
(10 attempts). The expired-tail probe separately found sequence 359795 in a
larger tail response although count=1 returned 359794.

## October 11 resume hardening
Run `37916313719` saved 9,841 verified chunks representing 97,109,121 trades,
including the 183 chunks reused from the first attempt. All eight workers reached
their five-hour work budget. The only observed chunk failure was an interrupted
HTTP response for BTC-28JUN24 sequences 840001–850000. The earlier sequence and
zero-amount failures did not recur in that attempt.

The transport retry and explicit pause changes retain job ID
`btc-full-20261009-archive`, the reconciled plan, and all compatible receipts.
Validation: 27 local unit tests pass. Install with `[skip ci]`, then submit request
sequence 6 to resume using the existing operator workflow without application
deployment. Launching this request does not establish download completion.
