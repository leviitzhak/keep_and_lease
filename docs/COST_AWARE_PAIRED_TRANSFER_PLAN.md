# Next planned analysis: cost-aware incremental paired transfers

Status: owner-requested analysis and full-backtest specification, 2026-09-15.
All engine implementation and strategy acceptance items below remain pending.
This is an extension of [PAIRED_TRANSFER_DESIGN.md](PAIRED_TRANSFER_DESIGN.md)
and [QUOTE_LATENCY_AND_CARRY_PLAN.md](QUOTE_LATENCY_AND_CARRY_PLAN.md), not a
replacement for the existing tested strategy or its immutable results.

## 1. Economic switching threshold rather than a mandatory long holding time

- [ ] Evaluate each proposed quantity delta against keeping the current funded
  position. Use a common future comparison time, matched risk/exposure and the
  current mark-to-market/funding state. Compare the forward economics now, not
  a candidate rate against the old position's historical entry rate.
- [ ] Introduce a no-trade region: require conservatively expected incremental
  BTC wealth to exceed incremental transaction/funding costs plus a configurable
  uncertainty/risk buffer. Do not trade merely because a target weight or
  annualized lease rate moved. Either observation/execution order is allowed
  only under the causal, funded paired-transfer rules.
- [ ] For a preliminary screen, use delta_expected_carry * feasible_days / 365
  > cost_fraction * safety_multiplier + uncertainty_buffer. Equivalently,
  H_break_even ~= 365 * effective_cost_fraction / delta_expected_carry when the
  denominator is positive. This is only a forecast screen, not guaranteed
  earned carry. A forecast of unchanged lease rates until early exit is not an
  identity and must be tested against realized residual basis and funding.
- [ ] Bound the feasible holding period by contract expiry, collateral liquidity,
  exit liquidity, risk limits, and any horizon over which the forecast is
  credible. A short-lived price mismatch must not be extrapolated as certain
  annual carry. A period long enough on paper does not ensure break-even.
- [ ] Optimize feasible incremental transfer size, including fixed/minimum fees,
  market depth, spread/impact and partial completion. Net unchanged exposures
  and reuse existing holdings where appropriate. A futures roll should not
  mechanically generate a spot and Treasury round trip.

One suitable decision quantity is E_t[W_swap_BTC(H) - W_keep_BTC(H)] after each
alternative's future cash flows and fees, exceeding a stated safety margin.
When using gross wealth forecasts instead, subtract the difference in FUTURE
costs between the alternatives exactly once. Past fees are sunk for the current
choice, while complete-lot attribution still reports them. A comparison cannot
charge an old entry fee again or silently give a new position free capital.

## 2. Exit economics, switching opportunities and safety overrides

- [ ] Track lot-level entry cash flows, realized carry, accrued bond value,
  remaining basis, all costs and executable liquidation value in BTC.
- [ ] Test discretionary exit rules that crystallize a target net gain, OR allow
  an exit when switching to the new funded position has a sufficiently higher
  forward expected net return than retaining the current one. Waiting for an
  old entry break-even must not override a clearly superior forward choice.
- [ ] Derive coupled limit prices/size from the pair's minimum net economic edge;
  recheck it when the other leg updates or a partial fill changes the residual
  quantity. An unfilled price limit is not a successful exit. Retain rejected,
  unfilled, reversed, expired and risk-exited instructions in statistics.
- [ ] Keep mandatory collateral/expiry/settlement and explicit risk exits separate.
  Never implement 'hold until profitable' as an unconditional safety rule.
  Desired exit prices and estimated replacement returns cannot be guaranteed.

## 3. Include Treasury transactions and cash availability

- [ ] Model Treasury purchase, sale, roll and redemption separately. Include
  commissions, minimum ticket fees, spread/impact, custody/financing where
  applicable, and any fund expense. Use the actual instrument, lot, nominal
  amount, accrued interest, settlement dates and trading calendar. Redemption
  at maturity is not automatically a secondary-market sale with a trading fee.
- [ ] Charge only changed quantities and actual transactions. Reusing a Treasury
  position or collateral within the same futures roll need not create a bond
  sale/purchase. Conversely, liquidating bonds for variation margin has costs
  and changes the subsequent interest stream.
- [ ] Distinguish full-notional economic funding from cash liquidity accepted by
  the clearing venue. For an ideal fixed-quantity nonnegative-price linear long
  with C0=q*F0, no costs or bond risk, retained variation P&L gives C_t=q*F_t.
  This ideal identity does not itself require fresh outside capital. Actual
  Treasury price changes/haircuts, cash-settlement deadlines, currency/venue
  segregation, broker margin floors/changes and fees can still create liquidity
  calls or a capital shortfall. Do not assume all Treasuries remain intact while
  their cash is simultaneously spent on variation margin.
- [ ] Separate native inverse contracts from linear-price research proxies.
  BTC-collateralized inverse futures do not become USD/Treasury-collateralized
  merely because their displayed prices are in USD.
- [ ] Refresh/audit Treasury source coverage and yield conventions before strategy
  acceptance. The retained six rate files used by the existing 90-day extract
  end on 2026-07-14 and carry forward afterward. DTB3/DTB6 are discount-basis
  observations, not directly an executable zero-coupon yield. Preserve prior
  results, expose data age, and test any corrected model as a new version.

Illustrative cost scale only: 3 bps on each spot/futures entry and exit is about
12 bps for four similar-notional trades, BEFORE Treasury trading costs. Adding
1 bp on each actual Treasury purchase/sale gives roughly 14 bps; assigning 3 bps
also to those two Treasury trades gives roughly 18 bps. These are not broker
quotes. Exact fees use executed quantities/prices, minimum fees and settlement
exceptions; don't charge every leg on an identical fixed capital by assumption.

## 4. Settlement and close-before-expiry study

- [ ] Compare retained official delivery prices with raw same-time spot and the
  spot TWAP over the exchange's actual delivery window. Keep index-reference,
  TWAP-versus-instant, venue/currency and quote-time effects separate.
- [ ] Compare predeclared close times (including 1 day and 5 minutes remaining)
  with actual delivery. Do not use the last observed future print as though it
  were official settlement, or assume F_expiry equals the selected spot price.
- [ ] Preserve exact expiry time, official index/price/source receipt, spot
  observation times/IDs, fill availability and settlement/delivery fees. Report
  unavailable close windows rather than inventing liquid expiry trading.
- [ ] At expiry the annualized lease rate is undefined because remaining time is
  zero. Report settlement basis and realized BTC return instead; never set the
  exit lease rate to zero to manufacture a rate-change statistic.

The retained source instruments are Deribit inverse-price observations. Deribit
cash settles their P&L in BTC and does not deliver title to one BTC per price-unit
future. Final delivery uses an index average from 07:30 to 08:00 UTC, not the
instantaneous Binance spot price used by the current currency proxy.

## 5. Preliminary entry/exit event study (not full strategy acceptance)

- [ ] Use predetermined entry observation times and positive entry lease rates;
  compare exits after 1 and 10 days, at 10 and 1 days remaining, and at expiry.
  Add a near-expiry close. Do not choose entry or exit retrospectively for the
  most profitable outcome. Keep all candidates and exclusions/censored cases.
- [ ] Compare equal initial BTC-equivalent capital, fixed future quantities,
  maturity-matched Treasury valuation, and initial/terminal spot conversion.
  Record the exact funding normalization: initial cash equal to q*F0 is not the
  same construction as cash equal to q*S0 or a bond whose terminal face is q*F0.
- [ ] Price an early bond sale at the then-observed remaining-maturity curve,
  rather than automatically awarding the original full-maturity yield. Use real
  securities where available; label synthetic bond and rate-vintage assumptions.
- [ ] Report gross and net BTC returns, distributions, positivity proportions,
  cost sensitivity, entry lease, exit-entry lease difference, basis changes and
  entry-rate-times-feasible-horizon budgets. Report the denominator, maturity
  mix and holding duration. Supply common-entry-cohort comparisons; overlapping
  examples are not independent trials or a portfolio backtest.
- [ ] Treat a valuation-only study omitting intra-horizon variation-margin
  financing as preliminary, not evidence of continuously fundable execution.
  Native inverse payoff and USD linear proxy results must never be interchanged.

## 6. Full planned backtest and acceptance checklist

- [ ] Implement one causal feed/decision/transfer state machine with separate
  observation, receipt, decision, submission, actual fill and response clocks.
- [ ] Select whether and how much to swap using expected NET incremental BTC
  wealth versus holding the existing portfolio over a feasible horizon.
- [ ] Execute linked partial spot/futures/Treasury changes under a durable transfer
  ID, reservations, size/price limits and bounded legging exposure. Only filled
  deltas incur costs. Carry all states continuously across days and checkpoints.
- [ ] Model marked Treasury prices, actual cash variation flows, available
  collateral/haircuts, funding/borrow rates, trading hours and settlement lags;
  include every reserved or externally provided dollar in both benchmarks.
- [ ] Retain signal and expected economics, rejected alternatives, predicted
  break-even horizon, achieved paired price/rate, realized BTC return, all fees,
  risk exits, and reason codes. Compare both successfully and unsuccessfully
  attempted transfers with holding the original state.
- [ ] Compare cost-aware switching with the current policy and longer-holding
  controls using identical opening state and immutable inputs. Validate first on
  bounded periods, then the complete 90 days, with chronological out-of-sample
  evaluation. No selected threshold is approved merely by in-sample performance.
- [ ] Test zero-fee equivalence, opposite observation/execution orders, monotonic
  cost accounting, unavailable quotes without automatic liquidation, failed
  children, fixed/minimum bond commissions, maturity redemption, wrong-reference
  settlement, late observations, funding stress and restart invariance.

Research outputs may be supplied before all items are complete, but the full
strategy and its expected performance remain unimplemented until these gates
pass. No claim of guaranteed carry or guaranteed break-even is authorized.

## Primary references for mechanics (not validation of this proxy study)

- Deribit inverse futures: https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures
- Deribit settlement: https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement
- Deribit delivery-price API: https://docs.deribit.com/api-reference/market-data/public-get_delivery_prices
- CME daily cash variation: https://www.cmegroup.com/education/articles-and-reports/money-calculations-for-futures-and-options
- Treasury bill pricing conventions: https://www.treasurydirect.gov/marketable-securities/understanding-pricing/
- FRED DTB3 discount-basis definition: https://fred.stlouisfed.org/series/DTB3
