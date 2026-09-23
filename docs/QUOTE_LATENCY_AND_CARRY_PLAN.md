# Quote availability, executed lease quality and longer holding periods

Status: broader implementation and research requirements, recorded 2026-09-15.
The current BTC research engine implements deterministic feed, frozen-snapshot
decision, order-arrival and fill-response clocks, durable queues and matched
execution diagnostics, with optional adaptive spot-to-future limits. See
[COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md) and `TODO.md` for
implemented scope. The composite checkboxes below retain additional depth,
measured-receipt, variable-latency and attribution requirements; an unchecked
item does not mean none of its research components exists.
It extends [PAIRED_TRANSFER_DESIGN.md](PAIRED_TRANSFER_DESIGN.md); the same transfer
instruction continues to govern spot <-> (cash/Treasuries + futures).

## 1. Delay observed quotes before the trading system may use them

- [ ] Add configurable market-data/feed delay, separately for spot and futures
  (and by venue where relevant). Preserve exchange/source event time, measured
  receive time when available, modeled delay, and effective availability time.
  When reliable reception time exists, additional modeled delay is applied to
  that time, not silently substituted for it. Otherwise a nonnegative modeled
  source-to-system delay is an explicit assumption, not measured latency.
- [ ] At decision time t, expose only records whose availability time is <= t.
  Keep the latest usable pair whenever either feed updates. Either source-time
  order is permitted after both observations have actually become available;
  absolute source-time skew, source age and time since receipt remain distinct.
  A pair passing a 50 ms skew test can still be old on arrival.
- [ ] Keep feed latency separate from strategy processing delay, order-entry
  latency, execution time, and fill/acknowledgement response latency. Delaying
  the information must not delay or rewrite the actual exchange market history.
  Orders may execute only after reaching the modeled exchange. A delayed local
  fill acknowledgement must not remove the exchange-side fill or release/reuse
  its real funding. Preserve exchange/account state versus locally known state.
- [ ] Start with deterministic nonnegative delays and zero-delay compatibility;
  add measured/seeded variable-delay scenarios with recorded parameters and
  deterministic reordering/tie rules. Distinguish exchange sequence order from
  feed arrival order, and handle late/out-of-order observations explicitly.
- [ ] Persist feed queues, pending transfer/order states and delayed responses
  across checkpoints. Missing/stale information is not a liquidation instruction.
  Expiry/settlement and exchange-side collateral obligations retain their own
  clocks and risk rules; missing receipts do not postpone them.

Acceptance: future-price perturbations must not affect any decision before their
availability time; zero delay reproduces the baseline; asymmetric delays permit
both observation orders; no negative delays or resets of old quote timestamps;
partial fills, response delays, restarts and risk events reconcile actual and
known positions without double-counted liquidity or collateral. Report source
age, source skew, feed delay and order/response latency separately.

## 2. Compare observed lease with the lease implied by executed prices

- [ ] Under each immutable transfer ID, freeze the observations and calculation
  that authorized the transfer: contract, direction, proposed quantity, both
  price sides/depth, source/available/decision times, remaining maturity, matched
  USD rate and its source components, premium, lease rate and thresholds.
- [ ] Attach child orders, modifications, fills, actual quantities, prices,
  fees, funding movements and completion/reversal status to that same ID.
  Match only economically paired quantities; retain unmatched residuals.
  Use quantity-weighted prices for matched partial fills with normalized
  contract units. Never compare a selected candidate rate with a different
  actually traded maturity without recording the selection difference.
- [ ] Compute a gross achieved matched-fill implied lease rate and its deviation
  from the observed rate. For price-only comparison, keep the decision's USD
  rate and remaining maturity fixed. Also report the rate at the transfer's
  completion time with updated maturity/yield, separating clock and yield
  changes from execution-price slippage and temporary unpaired exposure.
- [ ] Compute cost-adjusted economics from actual cash flows, not an arbitrary
  subtraction of trading-fee bps from annualized lease bps. Fees, spread, impact,
  slippage, conversion and funding costs must not be counted twice. A rate
  implied by an executed pair is not the subsequent realized BTC return.
- [ ] Preserve incomplete, rejected, timed-out, reversed and never-filled
  instructions in the denominator. Report completion/paired-fill ratio,
  time-to-pair, maximum unmatched exposure and related recovery costs. A
  completed-only comparison would hide costly failed transfers.
- [ ] Add observed-versus-executed scatter, price-only and total deviations,
  quantity-weighted distributions and breakdowns by contract, direction,
  maturity, delay, quoted size, holding horizon and time of day. Report
  counts and matched quantities with every aggregate.

For positive paired quantities and the current simple annualization convention:

```
lease_observed = r_ref - (F_observed / S_observed - 1) * 365 / D_ref
lease_executed_price_only = r_ref - (F_filled / S_filled - 1) * 365 / D_ref
```

The second expression is a reporting metric, not a tradable forecast available
before fills. For spot-to-futures use spot sales and futures purchases; the
reverse uses futures sales and spot purchases. The economically favorable sign
reverses with direction, so retain raw differences and a direction-adjusted
execution-quality measure. Further reporting must use the executed instruments'
actual payoff type, collateral currency and settlement specification.

Saved runs can be post-processed when signal snapshots, fill provenance and
pair-level attribution exist. Do not invent pair IDs or match unrelated spot
and futures fills in old independent-target runs and call the result exact.
Missing historical attribution must be explicit; reconstruction is separately
validated or a controlled new replay is required.

## 3. Longer rolling/holding periods: commodity-denominated objective

- [ ] Separate five controls: signal-estimation/smoothing window, target-review
  cadence, minimum holding time, roll lead time, and selected contract maturity.
  A smoothed display is not a slower trading policy; a long maturity is not
  automatically a long holding period. Observation/risk processing may remain
  frequent even when discretionary transfers occur much less often.
- [ ] Compare predeclared holding horizons (for example 1, 3, 7, 14 and 30 days)
  and hold-near-expiry variants with documented settlement/risk overrides.
  Hold matched quantities/lots rather than continually restoring target dollar
  weights. Roll directly between futures maturities when appropriate, without
  unnecessary spot round trips. Funding adjustments required by margin are
  separate from discretionary reallocation.
- [ ] Evaluate the complete funded portfolio and benchmark in BTC:
  BTC_NAV(t) = USD_NAV(t) / BTCUSD(t), and normalized BTC return =
  BTC_NAV(t) / BTC_NAV(start) - 1, excluding external flows or adjusting for them.
  Keep currency-proxy effects explicit when USDT-parity spot is used.
- [ ] Decompose cash interest, futures/basis P&L, spot changes, costs and
  incomplete-transfer exposure; retain both gross and net results. Do not
  integrate the displayed implied lease rate as though it were realized carry.
  Early exit retains a residual futures/spot basis; compare entry versus exit
  basis rather than treating a lower subsequent quoted lease as a direct loss.
- [ ] Test break-even carry budgets and opportunity cost over the intended
  holding horizon, with actual spread/fees and settlement costs. Longer holding
  amortizes entry/exit costs only if a genuine position is retained; it does
  not eliminate basis, venue/currency, funding, margin or model risk.
- [ ] Use the same opening state, immutable data and cost assumptions in
  controlled comparisons; report turnover, fees in BTC, matched exposure,
  drawdown, collateral breaches and realized versus predicted carry. Separate
  descriptive market analysis from funded execution replay. Avoid selecting
  a horizon from the same 90 days on which its performance is evaluated;
  reserve chronological out-of-sample periods and report coverage/censoring.

A useful accounting identity, not a funding feasibility assumption: sell one
unit of spot at S0 and hold a linear future for one unit, with no quantity
changes. Let I be net cash interest/funding through exit h and C all costs.
With no external flows or omitted balances, terminal BTC-equivalent wealth is

```
V_BTC(h) = [S0 + I + (Fh - F0) - C] / Sh
V_BTC(h) - 1 = [(Fh - Sh) - (F0 - S0) + I - C] / Sh
```

Additional collateral/reserves must be included in the portfolio benchmark if
needed to make that position fundable; this identity does not authorize opening
unfunded futures. At settlement, F_T = S_T applies only when the futures
settlement reference matches the selected spot reference. Cross-venue/parity
proxies may not satisfy it exactly. Native inverse payoffs need their own
identity. Daily variation settlement changes the cash/interest path. A locked
forward-plus-maturity-matched-bond construction is not automatically equivalent
to the current linear-price proxy with rolling short cash accrual.

## Data and validation boundaries

The retained market-history extract covers [2026-06-06, 2026-09-04) and pairs
ordinary futures trades to the latest preceding spot within one second. The
50 ms chart is a filter of those same pairs, not a feed-latency simulation or a
new both-sided matching method. Trade amounts do not establish remaining quote
size; book-side depth is required to certify quantity-aware executable carry.
The complete requirements represented by the composite checkboxes above remain
open; the current research subset is documented separately.

## Primary implementation references

- HftBacktest latency model documentation distinguishes feed, order-entry and
  order-response clocks: https://hftbacktest.readthedocs.io/en/py-v2.2.0/latency_models.html
- CME mark-to-market explanation for the cash-flow/funding distinction:
  https://www.cmegroup.com/education/courses/introduction-to-futures/mark-to-market

These references motivate implementation distinctions; they do not validate
this project's historical proxy prices or establish profitable execution.
