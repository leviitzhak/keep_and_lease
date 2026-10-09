# Audit of the saved 1OZ full order-book data

The authorized 9 October 2026 audit reads only the completed fixed acquisition
documented in [GOLD_1OZ_MBO_DOWNLOAD.md](GOLD_1OZ_MBO_DOWNLOAD.md).
It never constructs a Databento Historical client, retrieves an API secret,
or purchases additional records. This is research tooling and does not deploy
the application.

Submit a request-only change to
`.cloud-agent/requests/databento-1oz-audit.json` on the permanent
`agent/cloud-autonomous-access` branch. The exact JSON fields are
`schema_version: 1`, `action: "audit"`, a unique lowercase hyphenated
`request_id`, and `result_public_key_pem` (RSA, at least 3072 bits).
Only the public key belongs in the request. Installation commits use
`[skip ci]`; the subsequent request-only commit starts the fixed workflow.

The audit validates the final append-only checkpoint, all 93 completed
partitions (92 daily MBO files and definitions), SHA-256 checksums, DBN schema
and dataset, decoded fields, actual expirations, symbol coverage, duplicate
records, timestamp ordering and partition bounds. Prices are decoded with
the current SDK's `price_type="fixed"` to retain integer precision. Daily empty files are
reported rather than assumed to be acquisition failures.

It reconstructs explicit orders independently for each outright, carrying
state between daily partitions and applying the supplied resets/snapshots.
Partial cancellations reduce quantity. Trade and fill messages do not alter
the book. Book conditions are evaluated only on F_LAST event boundaries;
snapshot messages do not count as live activity or trades. Locked/crossed
states are reported separately because they can occur outside trading hours.
Unknown order modifications/cancellations invalidate the reconstruction until
a reset. Raw channel sequence gaps are not treated as missing instrument
records because acquisition filtered the wider exchange feed.

The report distinguishes defined contracts, live book activity, observed
trades, and two-sided uncrossed quote events. Every contract combination is
listed, including whether actual expiries meet the original three-calendar-
month spacing constraint. Common quote minutes mean both contracts had a
completed non-snapshot two-sided book event in the same UTC minute. They do
not prove continuous overlap or executable simultaneous fills. Contracts with
only snapshots or empty resets are not represented as liquid trading legs.

Detailed JSON is stored privately under the acquisition prefix at
`audits/<request-id>/<workflow-run-id>/summary.json`. The connector-readable
artifact contains only AES-GCM/RSA-OAEP encrypted evidence using the existing
research encryption implementation; raw licensed records and credentials
are never included. The workflow has a 30-minute bound and no schedule or
automatic resubmission.

Offline checks:
`python -m unittest discover -s research/databento -p 'test_audit_1oz_mbo.py'`.

Sources: [MBO order tracking](https://databento.com/docs/examples/order-book/order-tracking),
[GLBX.MDP3 conventions](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3).
