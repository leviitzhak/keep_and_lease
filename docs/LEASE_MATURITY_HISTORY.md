# Full-history implied lease rate versus maturity

## Scope

`scripts/build_lease_maturity_history.py` is a read-only market-data diagnostic,
not a trading-engine change or portfolio backtest. The default manifest is the
immutable 90-day catalog `52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912`
covering `[2026-06-06, 2026-09-04)` UTC. It does not assert history outside that
catalog. Files are only read from `keep-and-lease-market-data/btc/trades/`;
private result buckets, IAM, credentials and raw exchange APIs are not queried.

## Observation policy

Consider every distinct raw dated-futures trade, not just the futures actually
held, selected by the strategy, or referenced at half-second decision ticks.
Pair it with the last spot trade whose **reported timestamp is at or before**
the futures timestamp. Default maximum gap is one second; this is a diagnostic
screen, not an approved execution-policy parameter. No forward-nearest match or
price interpolation is permitted. Equal timestamps use the last spot source
sequence, with unknown sub-timestamp cross-venue arrival order explicitly noted.
Duplicate timestamp groups are resolved across Parquet batches and the final
spot mark is carried across daily boundaries. A selected subrange has no invented
pre-range mark: prints before its first spot observation are omitted explicitly.

Expired, block/RFQ/combo, unmatched and over-gap observations are counted by
reason. Negative lease rates and arbitrarily short positive maturities are kept.
Full-period color normalization uses the reported futures observation date/time
across the entire selected period; the all-maturity and `D >= 10 days` views
must use the same color bounds. A dense region is a count of trade observations,
not available liquidity, economic opportunity size, or independent samples.

This is a **reported-time market view**, not reproduction of the sequence-order
portfolio clock. Original source-sequence IDs and instrument discrepancy
metadata are retained for auditing timestamp anomalies. A causal reported-time
join does not certify the true arrival order or synchronous executability.
The previous one-day plot used only distinct futures records referenced by the
saved decision grid; counts therefore need not coincide with this broader view.

## Retained calculations

```
D = (expiry_us - futures_observation_us) / 86_400_000_000
premium = F / S - 1
annualized_premium = premium * 365 / D
lease = matched_USD_yield(D) - annualized_premium
```

Use the repository's as-of Treasury and maturity-interpolation implementation.
Date-only closing yields become available at next UTC midnight; there is no
interpolation through future yield observations. Each accepted pair retains
exact decimal source prices/amounts, both timestamps, IDs/sequences, source files,
currencies, sides, maturity, premium, annualized premium, matched yield, lease,
and every Treasury component's observation, availability and interpolation
weight. Source manifest, object generation and SHA-256 receipts are retained.
The defaults preserve USD inverse-futures quotes used as a linear-price research
proxy and Binance BTC/USDT with a parity assumption, not contemporaneous FX.
Historical trade amounts are **executed volume**, not remaining bid/ask depth.
These plots do not implement or certify the size-aware paired-transfer design.

## Run in authenticated Cloud Shell

From a pulled repository checkout containing the helper:

```bash
python3 -m venv "$HOME/.venvs/keep-lease-history"
PY="$HOME/.venvs/keep-lease-history/bin/python"
"$PY" -m pip install -r requirements-trade-data.txt 'numpy>=2,<3'
"$PY" scripts/build_lease_maturity_history.py \
  --io gcloud --max-gap-seconds 1 \
  --output "$HOME/keep-lease-history-$(date -u +%Y%m%dT%H%M%SZ)"
```

`--io adc` supports an already-authorized runner; no login or key is created.
Optional `--start` / `--end` choose a smaller half-open UTC date interval.
Generation-pinned downloads verify full hashes before decoding; default read
budget is 16 GiB and one object is capped at 512 MiB. Data partitions are handled
one UTC day at a time and temporary raw downloads are removed after processing.
Existing output is never overwritten. `summary.json` remains `INCOMPLETE` after
failure; partial output must not be represented as full-period evidence.

Output: `calculations/YYYY-MM-DD.csv.gz` (all accepted pairs, exact details),
`scatter_points.npz` (five documented numeric fields per pair, no point sampling),
`summary.json` (coverage/counts/rejections/receipts/hashes), per-day manifests,
contract metadata and progress. Rendering may use log/signed-log axes to retain
near-expiry extremes; any zoom/clipping must be visibly disclosed.

## Validation

`python -m unittest tests.test_lease_maturity_history -v` checks causal matching,
duplicate timestamps at batch boundaries, previous-day carry, missing data,
all-record retention, the exact formula and Treasury components, strict timing
thresholds, negative rates, near expiry, block/combo exclusion, wrong currencies
and market-only path validation. These are not proof of a completed GCS read;
use the extraction summary and input receipts for live completion evidence.
