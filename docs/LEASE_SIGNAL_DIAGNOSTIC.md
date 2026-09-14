# Full-resolution lease-signal investigation

## Purpose and status

Owner-run companion to `scripts/diagnose_run_costs.py`, on
`agent/operator-results-reader`. It investigates whether intraday changes in
calculated lease signals explain the recorded spot/futures allocation targets.
It does not change the strategy or start a new backtest. Live output for the
selected saved run has not yet been produced by the editing session.

The cost report contains actual fills and selected examples, not the full history
of allocation inputs. It cannot establish the signal history by itself. Do not
substitute sampled held-futures weighted rates for the allocation-driving rate.

## Run from the pulled Cloud Shell checkout

Use the owner's existing authenticated `gcloud` session. No credentials or tokens
are copied into the repository or report. Run from the repository root:

```bash
git fetch origin
git switch agent/operator-results-reader
git pull --ff-only
python3 -m venv "$HOME/.venvs/keep-lease-diagnostics"
"$HOME/.venvs/keep-lease-diagnostics/bin/python" -m pip install pyarrow==25.0.0

RUN_ID="<saved-run-id>"
OUT="$HOME/keep-lease-diagnostics/${RUN_ID}-lease-$(date -u +%Y%m%dT%H%M%SZ)"
"$HOME/.venvs/keep-lease-diagnostics/bin/python" scripts/diagnose_lease_signal.py \
  --run-id "$RUN_ID" --day 2026-06-07 --days 1 --output "$OUT"
```

This uses gcloud object-description and generation-specific read commands only.
The Cloud Shell account must be able to read the run in `keep-and-lease-results`
and the pinned inputs in `keep-and-lease-market-data`. No permission update,
server/API call, exchange download, cloud upload, or deployment is performed.
Files are ordinary unencrypted local reports. Do not commit private outputs.

`--days` supports 1–7 complete UTC days. The default `--max-read-mib 2048` caps
remote input reads; large individual partitions are capped at 512 MiB. There
is no full 90-day simulation or ordering-index rebuild. Downloading the selected
daily source partitions still requires I/O; this is not a zero-work operation.
If stopped or an input fails, the output remains explicitly unvalidated. Use a
new output directory on a retry; existing reports are never overwritten.

## Exact reconstruction, not a new trading path

1. Read the saved result and audit manifest. Recover the recorded engine commit,
   parameters, and immutable market-data manifest identity.
2. Read the checkpoint one hour before the selected UTC day. Recover the exact
   prior smoothed allocation, effective replay time, and known mark values.
3. Extract the original source files and six Treasury CSV inputs from that
   commit using the local Git history. Validate the original engine/parameters/
   rate/data fingerprint against the saved checkpoint. A different current
   engine or newer rates are not silently substituted.
4. Read every saved valuation from that checkpoint to the requested end,
   including one hour of warm-up. Check the full decision-clock grid. For a
   complete 500 ms day the selected output contains 172,800 rows.
5. Join each saved mark ID to its exact raw record in the hashed, generation-pinned
   Parquet partition, or to its recorded checkpoint mark. Retain decimal source
   prices, reported timestamps, effective replay timestamps, IDs and sources.
   Sequence/timestamp decisions are taken from the recorded audit, not recreated
   from a different assumption. No price interpolation or timestamp alignment
   is invented. Source partitions are read in batches, not loaded whole into RAM.
6. Re-evaluate only the original allocation function using those prices and the
   already-recorded holdings/NAV at each decision. Preserve original freshness,
   expiry, minimum-days, scoring, sticky-contract and smoothing behavior.
7. Compare every reconstructed target quantity, including spot, with the actual
   stored target. Warm-up comparisons must pass too. Preserve mismatches rather
   than declaring an approximate match successful.

The original checkpoint and market input bytes must still exist. This initial
utility requires an hourly-aligned decision clock and `reported_mark_us` in the
valuation audit. It supports the existing long-only regular BTC replay. It fails
explicitly for unsupported/missing history rather than inventing it. Original
source history must be available locally (`git fetch origin`); a missing recorded
commit is reported with its full SHA. It neither resets the portfolio at midnight
nor simulates another set of fills.

## Preserved lease and allocation calculations

For each decision and each marked futures contract, preserve:

```
D = (expiry_timestamp_us - decision_timestamp_us) / 86_400_000_000
premium = futures_price / spot_price - 1
annualized_premium = premium * 365 / D
lease_fraction = matched_usd_rate - annualized_premium
```

These are the original engine's simple annualization and 365-day convention,
not a newly substituted logarithmic or compounded formula. Each Treasury
component includes tenor, source row date, modeled availability time, yield and
interpolation weight. Intraday date-only Treasury observations become available
at the next UTC midnight under the original convention; interpolation is across
maturities, not across future observation times.

The selected positive candidate's lease rate determines the **total** futures/
Treasury share in gradual mode. The weighted held-futures rate is a different
quantity. With entry `a`, full-allocation threshold `b`, and cap `M`:

```
strength = clip((selected_lease - a) / (b - a), 0, 1)
raw_futures_share = clip(M * strength, 0, 1)
alpha = 1 - 2 ** (-elapsed_days / half_life_days)
smoothed_share = previous_share + alpha * (raw_share - previous_share)
spot_share = 1 - smoothed_share
spot_target_quantity = spot_share * NAV / spot_price
```

With no qualifying long candidate the original strength is zero; fixed mode
sets it to one. A disabled futures leg sets the unsmoothed share to zero. Zero
half-life bypasses smoothing. A missing eligible curve or stale spot prevents a
new target submission and cancels pending orders under the original rules; it
is not a newly submitted zero target. Contract weights are selected separately,
including the original SoftMax and sticky-contract behavior. Candidate ranking
logits and pre-sticky allocation score details are preserved where applicable.

For adjacent calculations of the same contract, changes in annualized lease
are decomposed in this explicit order: yield change, futures-price change at
old spot/maturity, spot-price change at new futures/old maturity, and maturity
clock change. The components sum to the observed change; a residual is retained.
A contract-selection effect is separate. This sequential attribution is not
unique and is not a causal proof. A daily-scaled annual lease is descriptive,
not a forecast of the next day's realized strategy return.

## Output

- `decisions.csv.gz`: every selected decision, allocation-driving contract/rate,
  thresholds, raw/smoothed target weights, actual weights, prices/quote ages,
  cost counters, target checks and rate-change decomposition.
- `lease-calculations.csv.gz`: one row per decision per marked futures contract,
  exact calculation inputs/intermediates, Treasury source components (JSON cell),
  eligibility reasons, scoring and selected-driver identity. Full numeric values
  are retained, not rounded to chart precision.
- `evolution.html`: self-contained interactive signal, allocation and cost
  charts. It contains all decision rows; at wide zoom it draws min/max envelopes
  to preserve spikes. UTC range controls and pointer inspection expose individual
  points. Recent Chrome/Edge supports its native gzip decompression. No server
  or external chart service is contacted. The CSVs remain the full numerical
  reference if a browser cannot render the local HTML.
- `summary.json`: signal/target ranges, hourly statistics, large allocation
  changes, quote-update/contract-switch classifications, reconstruction checks,
  source hashes and read receipts.
- `parameters.json`, `effective_parameters.json`, `original_engine/`, `inputs/`
  and `observations.sqlite`: original context, checkpoint, checked valuation
  chunks, selected source records and traceability. Full downloaded market
  partitions are deleted after the referenced records are resolved; their
  identities/hashes are retained. Checkpoint-only mark prices are labeled as
  such, not claimed to have original decimal precision from Parquet.

A final `MATCHED_SAVED_TARGETS_AT_EVERY_DECISION` means the reconstruction agrees
with the saved model. It does **not** establish that the inferred cross-venue
lease rates were synchronously executable, that their changes persisted, or
that switching paid for its fees. Fee increments in the decision table cover
`(previous_tick, tick]`; the new target is submitted **at tick**. Do not causally
attribute preceding fills to that newly calculated target. Hourly fee sums use
that explicitly stated boundary convention, not the cost helper's half-open
fill-day accounting.

For analysis in chat, provide `summary.json` and `decisions.csv.gz`. Include
`lease-calculations.csv.gz` to examine the complete retained calculation trail.
Do not replace any of these with a screenshot of a sampled GUI chart.

## Validation

`python -m unittest tests.test_lease_signal_diagnostic -v` checks original-function
identity, signal/held-rate separation, exact formula, stateful smoothing,
freshness/exclusion gates, fixed allocation, target discrepancies, price-change
attribution, original rate availability, exact raw Parquet joins, missing-source
failures, full HTML data retention and output protection. Parquet tests require
`pyarrow`; isolated CI installs it and does not silently skip those tests.
Live GCS retrieval and a full-day numerical extraction require an owner-run
invocation and are not claimed by synthetic tests.
