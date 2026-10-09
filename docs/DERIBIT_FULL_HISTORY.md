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

Run `validate` first: unit tests, historical catalog and two oldest trade records,
then a small immutable GCS write/read probe. It does not start the bulk download.
Run `download` with the intended job ID to freeze the plan and launch eight
deterministic shards, at most two running simultaneously.

Persistent root:
`gs://keep-and-lease-market-data/btc/research/deribit-full-history-v1/`
Job plan, receipts, attempts, completed shard records, and final manifest:
`jobs/<job_id>/`. Compressed raw objects: `objects/<sha256>/`.

Each chunk holds up to 10,000 consecutive trade sequences, requested in pages of
at most 1,000. Validate sequence coverage, instrument, unique IDs within chunks,
and positive finite prices/amount/timestamps. Upload content-addressed objects
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
failed uploads and corrupt stored data.
