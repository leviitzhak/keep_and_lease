# Full-history lease/maturity diagnostic — completion evidence

## Integration and execution design

User-approved PR #48 merged into `master` at
`952b980845f1944da3566217cd4d78fea12b0515` on September 14, 2026.
The merge preserves the two strategy-research TODO entries concurrently added
on master at `b26376149dbd99909b28d049de3cea15c1d83ec9`.

The same transfer instruction requirement for spot -> (cash/Treasuries + futures)
and the reverse is now in [PAIRED_TRANSFER_DESIGN.md](PAIRED_TRANSFER_DESIGN.md)
and the priority section of [TODO.md](TODO.md). Its execution-engine work remains
unchecked: liquidity-limited paired fills, collateral reservations, bounded
prefunding/legging exposure, no automatic stale-quote liquidation and close-time
price/size evidence are specified, not implemented. This research extraction
changes no portfolio state or trading rule.

## Completed market-data extraction

Workflow `34901878190`, job `104169490260`, completed successfully, using helper
source commit `6719e43f16b81d2cc4b41dcbcb020f537ec3f4f0`. The workflow is isolated
on `agent/cloud-autonomous-access` and reads the market-data bucket only.
No private run results, credentials or portfolio parameters are in its artifact.

- Coverage: every UTC day in `[2026-06-06, 2026-09-04)`, exactly 90 days.
- Raw futures records evaluated: 2,283,465 across the pinned catalog.
- Accepted pairs: 2,178,117, across 93 observed contracts.
- Accepted pairs with at least 10 days remaining: 1,492,689.
- Exclusions: 49,652 flagged block/combo records, 55,695 beyond the one-second
  backward spot gap, and one expired observation. Counts reconcile to inputs.
- Market input reads: 1,162,265,288 bytes, with object generations and SHA256
  receipts retained. Each raw partition is verified before decoding.

Each ordinary futures trade is joined backward to the latest spot record at or
before its reported timestamp, with a maximum one-second gap. No forward pair,
interpolation, repeated stale decision-grid mark or negative-rate filter is used.
This is a reported-time market view, not the sequence-order portfolio clock.
Amounts are historical executed volume, not available bid/ask depth. The original
USD futures-price / USDT-parity spot assumptions remain unchanged.

Artifact `lease-maturity-history-34901878190`, ID `10370424780`, contains all 90
daily compressed calculation CSVs, scatter_points.npz, summary/progress, source
manifests and contract metadata. It is 226,894,667 bytes; downloaded archive SHA256:
`9e8a4be8eb417c8cf438aec87fc445736bbf5474a9fe8f879f6ba45b8f15c929`.
The temporary GitHub artifact expires after one day; retained user-facing copies
and the reproducible script are separate from artifact retention.

## Verification

The workflow passed 56 offline tests before the cloud read, including all 17 new
causal-pairing, duplicate timestamp/batch boundary, maturity, formula, source
restriction and exclusion tests. The remaining 39 cover existing diagnostics and
operator contracts. The successful read is separate evidence from those tests.

After downloading, independent checks covered all 2,178,117 accepted rows:
all 90 compressed CSV hashes; date coverage and accepted/rejected counts;
nonnegative spot timestamp gap <= 1 second; positive unexpired maturity; ordinary
unflagged trades; F/S premium, simple annualization and implied lease calculations;
and exact alignment of numeric plot values with their source CSV rows. There were
no duplicate (symbol, futures trade ID) pairs across the entire period.

Two static scatters retain all accepted observations: all positive maturities
(log maturity / signed-log annualized rates to retain near-expiry extremes), and
maturities >=10 days (linear axes including outliers). Both use the same full-period
observation-date color scale; point drawing order is permuted, not sampled, to
avoid always covering early observations with later ones.

A self-contained HTML explorer delivered with the research output retains all
2,178,117 points, contract/date/maturity/rate filters, fixed full-period colors,
point inspection and visible-point CSV export. Actual-data Chromium rendering
checks passed full count, >=10-day count, date filter, hover/inspection, CSV export
and mobile overflow checks, with no page errors or external network requests.
The full daily CSVs retain exact decimal source prices/amounts, IDs, timestamps,
Treasury source observations/availability/weights and every formula intermediate.

Neither numerical agreement nor close timestamps establishes executable quote
size or profitability. Observation-weighted distributions are not time-weighted
rates, volume-weighted lending capacity or statistically independent samples.
See [LEASE_MATURITY_HISTORY.md](LEASE_MATURITY_HISTORY.md) for reproduction.
