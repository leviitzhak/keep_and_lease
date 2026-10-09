# Three-month 1OZ full order-book download

The owner approved full order-book acquisition on 9 October 2026 after the
free estimate in workflow run 37906292534: USD 0.164054270089 for MBO.
The fixed scope is GLBX.MDP3, MBO, 9 July 2026 00:00 UTC inclusive to
9 October 2026 00:00 UTC exclusive. It includes these 10 outrights:

`1OZG7 1OZJ7 1OZM7 1OZQ7 1OZV7 1OZZ7 1OZG8 1OZJ8 1OZM8 1OZQ8`.

The downloader saves definitions from 4–9 October and validates actual vendor
expirations before purchasing MBO: at least three calendar months from the
period end, consistent with 1OZ's preceding-month termination, and another
eligible contract expiring within three calendar months. Missing or conflicting
definitions stop the download. Data begins when each contract is available;
absent historical records are not filled with synthetic prices.

## Persistence and recovery

The existing keyless research operator and permanent Databento secret are used.
A request-only push to `.cloud-agent/requests/databento-1oz-mbo.json` on
`agent/cloud-autonomous-access` starts **Download 1OZ full order-book history**.
It runs independently of the ChatGPT thread on a GitHub runner and stores all
licensed data privately in the existing market-data bucket:

`gs://keep-and-lease-market-data/research/databento/gold-1oz-mbo-2026-07-09-to-2026-10-09-v1/`

- `raw/`: compressed DBN files, one per UTC day, plus definitions; paths include
  partition, acquisition-attempt ID and SHA-256 digest.
- `checkpoints/`: immutable append-only state, with a durable cost reservation
  written before each paid call, and completed state only after raw upload.
- `runs/<request-id>/<workflow-run-id>/`: launch receipt, metadata cost plan,
  verified contracts and completion manifest.
- `failures/`: sanitized durable failure receipts.

Repeat the same fixed request using a new request ID, or rerun the workflow to
resume. Completed partitions are checked and reused. An upload acknowledged by
GCS but missing its completion checkpoint is recovered without buying again.
Missing/corrupted completed objects stop instead of silently repurchasing.
Only pending/interrupted partitions need acquisition. Each partition permits
at most two paid attempts across all resumes. Transient gateway/connection
failures may use the second attempt; other failures stop for review.

The cumulative estimated purchase limit is USD 0.25, including definitions and
all failed/uncertain reservations. The full remaining plan is checked before
acquisition; every retry rechecks the budget. This is an estimated-data cap,
not a guarantee of the vendor invoice or a cap on cloud storage costs.

Daily MBO files preserve original order messages, sequence numbers and vendor
snapshots; no downsampling, resampling or price conversion is applied.
Databento includes synthetic midnight UTC order-book snapshots on weekdays,
allowing independent book reconstruction at these daily boundaries. No extra
trades-only or top-of-book dataset is purchased.

The saved data can be checked without new purchases using the fixed
[1OZ data audit](GOLD_1OZ_DATA_AUDIT.md), which verifies files and reports
actual contract activity and overlapping expiry-pair coverage.

The workflow is serialized and has a 350-minute execution limit. There is no
scheduled monitoring or automatic resubmission. After launch, the agent reports
the workflow run ID and storage prefix without polling progress. Installing the
operator-only code uses `[skip ci]`; the launch commit changes only the request
path. Neither requires application deployment.

Validate recovery and purchase controls offline with:
`python -m unittest discover -s research/databento -p 'test_download_1oz_mbo.py'`.

Sources: [MBO schema](https://databento.com/docs/schemas-and-data-formats/mbo),
[midnight snapshots](https://databento.com/docs/standards-and-conventions/mbo-snapshot),
[historical streaming API](https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range).
