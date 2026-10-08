# Requested Deribit history extension

This is a bounded data-only operation on `agent/cloud-autonomous-access`.
It does not modify, deploy, or activate the strategy, GUI, or existing catalog.

| Job | Instrument | UTC start inclusive | UTC end exclusive | Days |
| --- | --- | --- | --- | --- |
| earlier-sep26 | BTC-25SEP26 | 2026-03-06 | 2026-06-06 | 92 |
| earlier-dec26 | BTC-25DEC26 | 2026-03-06 | 2026-06-06 | 92 |
| missing-mar27 | BTC-26MAR27 | 2026-06-06 | 2026-09-04 | 90 |

The March 2027 instrument metadata reports creation at 2026-03-27 08:00:26
UTC. Its first historical trade, sequence 1, is dated 08:26:00.320 UTC that day.
It existed during the old June-September period but was absent from its catalog.
The earlier Sep/Dec pair retains 111 days 8 hours / 202 days 8 hours to expiry
at its June 6 end boundary; its expiry gap is 91 days.

Push only `.cloud-agent/requests/deribit-history-extension.json` with
`schema_version: 1`, action `download-sep-dec-earlier-and-mar27-current`,
and a positive integer `sequence`. The fixed workflow accepts no arbitrary
instruments, dates, bucket, endpoint, or command. Installation uses a separate
`[skip ci]` commit, so no application deployment is triggered.

Follow the GitHub Actions workflow **Download earlier Sep-Dec and missing Mar27
history**. Each of its three jobs logs `DAY_COMPLETE`, a UTC date, completed-day
count, and raw/ordinary trade counts. A successful finished job logs `READY`.
All three jobs must be green before treating both requested datasets as ready.
Coverage reports are attached as `deribit-history-<job>` artifacts for 30 days.

Each day uses the repository's `sequence-envelope-v1` reconciliation module
(source blob `199327043bb1cf955393cf07dc54dd9705cc3d78`), copied unchanged under
`research/deribit_history/`. It retains original fields, API responses, seed
trades and anomaly evidence. Time endpoints anchor a sequence envelope, and all
sequences in that envelope must be present. Original timestamp reversals are
retained. A neighboring full-page guard is a bounded-history assumption, not
proof against arbitrarily backdated records outside the envelope.

An independent raw scan checks instrument, UTC-day membership, counts, positive
prices/index/amount, unique trade IDs, sequence order and native $10 contract
quantities. Ordinary eligible counts exclude block/RFQ/combo flags. Raw records
remain available. Native index observations accompany the futures trades; no
separate continuous spot/index tape is implied.

The existing keyless operator identity creates and reads objects only in the
existing market-data bucket, under `btc/research/deribit-history-extension-v1/`.
Objects are content-addressed and byte-verified after upload. A stable daily
receipt is written last, after all objects validate. Retries verify and reuse
completed days. A complete range manifest is written only when every expected
day passes. Daily failures are logged, other days continue, and the job ends
unsuccessfully with an incomplete report. Rerun failed jobs to resume.

No credentials or private account data are exported. No long-running backtest,
GUI catalog activation, deployment, schedule or notification is started here.
The user will signal completion in chat using the workflow status.
