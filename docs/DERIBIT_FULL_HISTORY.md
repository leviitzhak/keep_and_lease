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

Workers stop after a 300-minute work budget (330-minute Actions timeout), save
an INCOMPLETE report, and fail visibly if work remains. **Re-run failed jobs**
resumes the same plan and job ID. A new request with the same job ID and incremented
sequence also resumes. No automatic agent monitoring or recurring retry loop.
Storage persists independently of GitHub Actions runner lifetime.
The final manifest exists only after all eight shards have completed.

Verification:
`python -m unittest discover -s research/deribit_history -p test_full_history.py -v`.
Tests cover gaps, timestamp reversals, sharding, resume skips, atomic publication,
failed uploads and corrupt stored data. Recovery tests additionally cover shifted
windows, out-of-range extras, identical/conflicting duplicates, genuine unresolved
gaps, numeric anomaly retention, timeout-driven smaller pages and durable failure
evidence.

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
