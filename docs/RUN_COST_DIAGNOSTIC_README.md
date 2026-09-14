# Keep & Lease: owner-run fee and position diagnostic

This is a read-only local analysis helper, **not an analysis already performed on
any real saved run**. Execute `scripts/diagnose_run_costs.py` from a pulled checkout
in authenticated Google Cloud Shell. GCS supplies the saved inputs; it does not
execute this script. No scheduled or GitHub workflow is modified or invoked.

## Pull and run

The helper is included on `agent/operator-results-reader`, alongside the
Terraform results-reader grant. Pulling this addition requires no Terraform
apply, GUI deployment, service restart or strategy rerun.

From your existing checkout:

```bash
cd ~/keep_and_lease
git fetch origin
git switch agent/operator-results-reader
git pull --ff-only

read -r -p 'Saved run ID: ' RUN_ID
OUT="$HOME/keep-lease-diagnostics/${RUN_ID}-$(date -u +%Y%m%dT%H%M%SZ)"
python3 scripts/diagnose_run_costs.py \
  --run-id "$RUN_ID" \
  --fee-bps 3 \
  --days 1 \
  --output "$OUT"
```

Requirements: Python 3.10+ (standard library only) and an authenticated `gcloud`
CLI account with read access to the requested result/audit objects. The helper
uses that account; it does not automatically impersonate the operator service
account. No credentials need to be pasted into the repository or chat.

Unlike the original standalone download, the repository copy requires an explicit
`--run-id`, so the public source does not hard-code one user's investigation. Its
analysis logic is unchanged. The fee parameter is the rate to test independently;
the stored effective rate is also recorded and a mismatch produces a warning.

The default date is midnight after the recorded start, when a complete next UTC
day is available. Otherwise it examines an explicitly labelled partial starting
day. To choose a date, add `--day YYYY-MM-DD`. Change `--days` for 1 to 90
consecutive UTC days. The default total compressed read budget is 512 MiB;
`--max-read-mib` controls it explicitly. Prefer a one-day diagnosis first.

## Outputs

The output directory contains ordinary, unencrypted `report.txt` and `report.json`.
Existing output directories are refused to preserve previous evidence. Exit code
0 means no discrepancies in the checks performed; 2 means a discrepancy was
found (or an argument was invalid, as identified by the printed error); 1 means
analysis stopped. Missing historical data is reported as unavailable, not zero.

Only local report files are written. No results, raw records, credentials or keys
are uploaded. The script has no IAM or deployment writes and does not import or
invoke the strategy engine. It uses only signed-in `gcloud` storage describe/cat
reads of known objects under the selected saved run. Storage reads still count
as ordinary storage operations. The default `run-cost-diagnostics/` output is
ignored by Git; keep custom output directories outside the checkout as above.
Share `report.json` in the investigation conversation, not in a public PR/log.

## Included checks

- Selected fill fees versus `abs(quantity) * price * fee_bps / 10000`.
- Daily fees in dollars and basis points of a recorded boundary NAV; gross
  turnover and turnover/NAV. Buys, sells and different maturities count separately.
- Instrument-level fees, buy/sell quantities, net quantities and turnover.
- Cumulative fee/turnover differences versus sums of fills between valuation
  anchors, plus reconstruction of held quantities at those anchors.
- Up to 100 first fills, 100 largest fills and 100 examples of opposite-side
  fills within 60 seconds, including before/after quantities and order targets.
- Compressed/uncompressed audit checksums, row counts, byte counts and source
  generation receipts. Corrupt or oversized chunks stop certification.

## Interpretation and limits

Daily fees use the fill timestamp in the half-open UTC day [00:00, 24:00).
Counter checks use (anchor start, anchor end] to match inclusive valuations.
NAV-reference timestamps and ages are explicit; no missing boundary is
interpolated. A rapid reversal is an indicator, not proof of an avoidable trade.
Targets are reconstructed from submitted deltas, not independently recalculated
signals. Orders predating the inspected slice are reported as unmatched when
necessary. Initial owned BTC and settlement events are not fee-bearing fills
unless the audit itself records a fill.

Only `btc_trade_replay` results are supported. Daily or observed-candle results
stop explicitly instead of applying the wrong units/model. Correct fee arithmetic
does not establish profitable trading, and selected-day checks do not certify
uninspected days or all intra-interval market inputs. Lost/expired source objects
cannot be recovered by this helper. No live run has been certified merely by
adding the script to this branch.

## Repository validation

Nine offline regression tests passed for the repository copy: partial fills and
cancel/replacement, incorrect fees, missing counters, dollar/bps conversion,
corrupt checksums, path restrictions, end-to-end offline analysis, CLI report
preservation and explicit run-ID selection. Syntax compilation and CLI help also
passed. These are synthetic checks, not live GCS or real-run verification.

```bash
python3 -m unittest discover -s tests -p 'test_diagnose_run_costs.py' -v
python3 -m py_compile scripts/diagnose_run_costs.py
```

## Related access and CLI references

See [OPERATOR_RESULTS_ACCESS.md](OPERATOR_RESULTS_ACCESS.md) for the standing
operator grant. This owner-run helper is separate from the protected automatic
operator transport.

- https://docs.cloud.google.com/sdk/gcloud/reference/storage/objects/describe
- https://docs.cloud.google.com/sdk/gcloud/reference/storage/cat
