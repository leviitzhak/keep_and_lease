# Rolling observed lease bounds and market hedges

Implemented as an opt-in replay mode on 2026-09-24. Use **Cost-aware funded
pairs → Expiry-amortized ranking → Rolling worst lease → market hedge**.
No live orders or quote feed are connected. The original fixed, adaptive and
empirical paths remain available for saved-run reproducibility.

## Signal and price limits

At decision time `t`, use only observations already delivered to the strategy,
whose source timestamps are in `[t-window, t]`. The default window is five
seconds; it can be changed independently of the execution decision interval.
During warmup the window contains only available history. If either instrument
has no observation in the window, no new rolling instruction is admitted.
Latest-observation freshness/skew gates still apply to discretionary fills.

For cash rate `r` and remaining maturity `T` years, the existing simple annual
lease convention is `L = r - (F/S - 1)/T`. The Cartesian set of observed price
pairs has exact bounds:

- `L_min = r - (F_max / S_min - 1)/T`;
- `L_max = r - (F_min / S_max - 1)/T`.

These price pairs need not have traded simultaneously. They are historical
bounds over already observed prices, not guaranteed bounds on a future fill.
Extrema retain both source and availability timestamps. Monotone queues avoid
enumerating every combination and are included in durable checkpoints.

For a future being entered, `L_target = L_min - delta`; for a future being
exited, `L_target = L_max + delta`. The GUI accepts the nonnegative magnitude
in annual basis points. For each future let `A = 1 + (r-L_target)*T`; set
`A_spot = 1`. For source `s`, destination `d`, latest observed prices `P_s`,
`P_d`, and expected market-hedge slippage `e` in decimal price units:

- source sell limit: `P_d * (1+e) * A_s/A_d`;
- destination buy limit: `P_s * (1-e) * A_d/A_s`.

These formulas select `paired_limit_anchor="relative_price"` (the default).
Alternatively, `paired_limit_anchor="spot"` sets each futures sell/buy limit to
`S * A_i`, using the frozen observed spot `S`. For a spot leg, invert the other
future's relationship: `S_limit = F_observed / A_future`. This alternative does
not multiply limits by `1±e`; expected hedge slippage remains in the transfer
cost. Both alternatives use the same rolling bounds and signed lease delta.
They generally approach each other when counterpart observations are near their
spot-implied target prices and expected slippage is small. Saved parameters,
checkpoints, order contexts, the GUI summary and Lease limits export retain the
chosen anchor. The per-order `set_lease` still describes the expected executed
pair including hedge slippage; it can differ from the individual target lease.

In relative-price mode, the counterpart price includes expected adverse hedge slippage. For a spot /
future pair the implied lease equals the target lease. A futures roll constrains
the ratio of its two prices. Each order also records each instrument's implied
lease against the frozen spot reference; this can differ from the individual
target bound. The audit reports target and implied setting rates separately.

## Admission and funding

KEEP still uses current observed held-instrument returns, with sunk entry fees
excluded. The candidate uses the rolling execution prices, including the signed
delta. Source-sale shortfall and a spot repurchase premium are explicit costs;
future-entry basis is already included in gross lease and is not charged again.
One expected hedge cost is budgeted conservatively as
`max(source_qty*source_price, target_qty*target_price) * e` and amortized through
the relevant expiry, alongside entry, exit and future expiry/default-position
fees. Re-evaluation uses the unpaid portion of existing commission tickets.

Both limits may lead, but the buy leg needs already available free cash. A
portfolio initialized entirely in BTC must sell spot first. No proceeds from
an unfilled sale are borrowed, and no initial cash buffer is silently created.
Opening tranches and recovery fills are bounded by the configured unmatched
BTC cap, tape participation, remaining order quantity and actual funding.
Small source prints that cannot fund the hedge's minimum/fixed fee are skipped.

After a first fill, its quantity and exact setting context are frozen. The
opposite resting limit can fill during acknowledgement latency. Otherwise it
becomes a market instruction after the response, decision and order delays.
This hedge is not blocked by a subsequent loss of the original opportunity.
It consumes subsequent eligible same-side trade prints using the established
replay participation convention. It is not an immediate or guaranteed fill.
Actual configured spread/slippage is applied to fill prices separately from
the expected admission estimate. Market fills can be worse than the estimate.

One unmatched tranche is recovered before starting another. Either imbalance
direction survives timeout, cancellation and restart. A timeout stops new
exposure but preserves recovery; missing liquidity or insufficient funding can
still leave an unresolved quantity at the end of the run. Once a tranche is
matched, recovery instructions are suspended until new limit revisions arrive.

## Audit and analysis

The full audit and selected-period workbook retain:

- **Lease limits:** initial orders, replacement requests, arrivals and
  rejections, fills, and live order state at each strategy decision. Columns
  include order/revision IDs, price, market/limit state, both window bounds,
  chosen adverse bound, delta, target lease, implied setting lease, window
  timestamps, price extrema and expected hedge slippage. Current bounds at a
  strategy step are separate from the context frozen in the resting order.
- **Lease executions:** one row per matched tranche and futures instrument,
  tied to the exact first-hit order ID/revision, first fill timestamp and limit.
  It compares source/target fill prices with that limit's worst, target and
  implied setting lease. `executed_minus_set_lease` is signed; positive
  `adverse_lease_slippage` always means worse execution. Waiting time runs from
  the first fill to the matching hedge fill.
- **Transfer decisions:** candidate expected hedge cost and execution-price
  cost, annualized returns and frozen rolling evidence. The GUI summary shows
  the latest matched comparison; full-resolution history is in the workbook.

Executed comparisons use the cash rate and maturity frozen when the first-hit
limit was set. They therefore isolate price slippage from later annualization
changes. Rates are decimal annual rates before trading fees; fees are separate
cost fields. A roll's per-instrument lease uses the frozen reference spot,
because there is no executed spot leg. Missing fills produce no fabricated
executed lease. Unfilled/rejected revisions remain visible.

## Validation and remaining measurement

Focused tests cover extrema expiry and delayed observation, no lookahead from
the hitting print, expected cost rejection, both first-leg directions,
partial hedges across restart, exact acknowledgement/transport boundaries,
reverse transfers, rolls, funding/NAV reconciliation and stored export values.
The independent audit checker understands market hedges and both imbalance
directions. A synthetic end-to-end replay completes transfers without collateral
breaches; this does not establish improvement on historical data.

`strategies/research-btc-rolling-lease-3day-500ms-fee-10bp.json` matches the
previous three-day amortized preset except for the new execution mode and its
three explicit research inputs (5 seconds, 5 annual bps, 1 price bp). These
values are not calibrated estimates. A historical comparison should keep dates,
fees, latency, participation and allocation settings identical and report
completion by attempts and by quantity, nonfills, residual exposure, hedge
waiting time, executed-minus-setting lease distribution, fees and net BTC value.
No ten-day historical improvement or deployed-preview validation is claimed yet.
# Separate rolling lease distributions — 2026-09-25

`paired_repricing_mode="rolling_distribution"` implements two distinct
distributions for each candidate future at the current decision/reprice time `t`:

1. Hold current observed future `F(t)` fixed and vary received spot trades `S(u)`.
2. Hold current observed spot `S(t)` fixed and vary received future trades `F(u)`.

Use `L(F,S)=r(t) - (F/S-1)/T(t)` for every sample, where `T(t)` is remaining
ACT/365 years to expiry. The source-time window is `[t-W,t]`, inclusive, and only
observations already delivered through the feed-delay queue are eligible. An
empty history makes that instrument unavailable; no future or full-day median
is substituted. Existing current-quote age/skew and cash-rate gates still apply.

Each observed trade has equal median weight (not volume or time weight).
For each distribution calculate minimum, median and maximum **lease rates**.
With even sample counts, average the two middle rates; for spot history this
requires the mean of the two middle reciprocal prices, not reciprocal of the
mean price. Duplicate-price trades retain their full sample count.

Each provisional target is `median + alpha*(maximum-median)`. Combine the two
targets by `min`, `max` or arithmetic `mean`, independently for each future in
the candidate pair. Spot retains a price factor of one. Configuration:

| Field | Default | Meaning |
| --- | --- | --- |
| `paired_lease_window_seconds` | 5 | Trailing source-time window |
| `paired_lease_target_alpha` | 0.5 | Fraction from median to highest rate, in [0,1] |
| `paired_lease_target_combine` | mean | min, max or mean of the two provisional targets |

The combined target replaces the lease used in expiry-amortized transfer
valuation and limit repricing. All existing prospective costs, funding limits,
the selected price anchor and expected market-hedge slippage remain active.
The older adverse lease delta is **not** additionally applied in this mode.
After one leg fills, the remaining unmatched quantity follows the same funded
market-hedge path; a changed lease target cannot veto recovery. Partial fills,
feed/response queues, the exact hit revision and the rolling samples survive
checkpoints. Audits record both distributions, both targets, alpha, combination,
sample counts, current prices and common rate/maturity reference. Lease-limit
and execution exports retain this evidence. Earlier saved modes keep their
original definitions.

The initial uncalibrated research preset is
`strategies/research-btc-rolling-distribution-90day-500ms.json`: June 6 through
September 4, 2026 (end exclusive), 500-ms decisions, mean, alpha 0.5, 5-second
window, 10-bp fees, and 100-ms observation/decision/order delays. The 90-day
result is a forward application of these declared settings, not evidence of
out-of-sample calibration. No return or completion guarantee is implied.
