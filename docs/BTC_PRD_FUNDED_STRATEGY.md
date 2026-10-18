# Funded BTC PRD strategy

Complete operating specification - 18 October 2026

This is the single current description of the proposed funded strategy. It
consolidates the agreed rules and the latest expiry-completion addition. It is
an internal implementation specification, not a claim of tested profitability.
The funded portfolio engine described here has not yet been implemented.

Scope: regular linear dated futures, cash and direct BTC or an optional
long-only BTC proxy. Quantities are underlying units unless explicitly stated.
Existing inverse-futures historical experiments retain their original scope.

**Decision status.** Rules described as requested or agreed reflect the owner
discussion. Rules marked proposed are implementation recommendations. Numerical
examples are illustrations, not selected live parameters. Section 18 lists the
remaining choices needed for a reproducible first funded test.

## 1. Objective and complete lifecycle

Maintain net long BTC exposure within a configured minimum and maximum while
using funded long/short futures opportunities to earn additional return. Rank
openings by the short APR minus the long APR (PRD), with a separate ladder for
each oriented pair. Size orders from actual available exposure, leverage,
cash, underlying and margin capacity.

Seek early profitable closure using the change in the executed futures price
spread. When positions approach expiry, consider a funded roll using the same
admission machinery as an opening. If the remaining package is not closed or
rolled, retain it to expiry and execute the planned spot purchase or sale,
provided its funding and settlement capacity remain valid.

The earlier before-60-day retirement target now serves as a planning/review
objective, not an unconditional liquidation deadline. This follows the latest
request to include hold-until-expiry completion. Stop discretionary new openings
in retiring contracts; continuing to hold an existing funded contract is a
different action. Funding failure still requires recovery; expiry permission
does not waive collateral obligations.

The lifecycle is: reconcile balances; calibrate initial policies; establish the
minimum exposure; reserve and execute eligible openings; manage partial fills
and ladders; close profitably or roll; otherwise complete through expiry;
release reservations and reconcile the complete cash and inventory history.

## 2. Quantities, prices and return definitions

Let A denote the long instrument, B the short instrument, S(t) spot, F_i(t)
the current futures price, T_i expiry, and K_i an actual entry execution price.
Keep the A/B orientation throughout a lot's life even if market APRs cross.

```
tau_i(t) = (T_i - t) / (365 days)
a_i(t)   = (F_i(t) / S(t) - 1) / tau_i(t)
D(t)     = a_B(t) - a_A(t)
```

PRD D is a difference in simple annualized premiums. Store 2% as 0.02 and a
0.1 percentage-point increment as 0.001. A positive PRD does not by itself
prove positive funded profit when the maturities differ.

For equal quantities q and simultaneous entry marks:

```
entry_price_spread = K_B - K_A
                  = S_entry * (a_B * tau_B - a_A * tau_A)
gross_completion_cash_gain = q * (K_B - K_A)
```

The completion identity assumes the expiry spot trades described in section
14, no costs or cash interest, and spot execution at the settlement index.
It is not a futures-only hold-to-expiry payoff without those spot trades.
Actual financing, fees, interest, proxy decay and execution mismatch are
separate dated cash flows. Benchmark cash interest foregone is an opportunity
cost, not a second transaction expense.

Baseline research sizing matches equal underlying units on the two legs.
Unequal quantities require explicit treatment of the residual long/short
exposure; the optional unit-targeted alternative is described in section 15.

## 3. Configuration and persistent state

| Configuration group | Required inputs and status |
| --- | --- |
| Capital and exposure | Initial cash/positions, minimum and maximum net BTC exposure; 30%-60% is illustrative |
| Leverage and liquidity | Gross futures leverage cap, account margin model, eligible collateral, cash reserve and stress scenarios; values unselected |
| Entry and ladders | Per-pair base H0, incremental PRD, rung quantity and completion probability objective; infer from prior observations |
| Maturity eligibility | At least three calendar months for new futures; separation ceiling configurable; 30% and one-third remain comparison cases |
| Waiting | Fast/slow entry horizons, curvature, catch-up policy, close-review cadence and deadline responses; calibrate before testing |
| Exits and rolls | Lot net-profit targets, cost assumptions, roll lead time, relaxation schedule, funded expiry completion enabled |
| Execution | Observation delay, order delay, strict-through participation, native ticks/lots and broad posting-distance threshold |
| Proxy and costs | Expense e, optional liquidity-cost APR c, actual fee schedules, signed rebates, settlement/spot mismatch assumptions |

Persist actual balances and positions; settlement state; immutable executions;
pair and lot ownership; entry prices and APR anchors; current-leg PRD; remaining
qualified ladder quantities; cash/underlying backing allocations; margin and
order reservations; pending commands and acknowledgements; clocks; calibration
versions; and the last processed market/account event identifiers.

Pair identity is account + strategy + long instrument + short instrument.
Execution lineage connects old and new pairs during rolls and netting. A
logical pair cannot own more than the actual position available in its account.

## 4. Startup, restart and initial calibration

1. Import actual cash, holdings, signed futures, contract definitions, settled
   and unsettled P&L, working orders, pending transfers and known recent fills.
2. Restore prior lot ownership, backing dependencies, ladder state and in-flight
   events. Reconcile them against the account. A pause does not cancel orders.
3. If this is a new cash-start test, start with no fabricated holdings or pair
   history. If importing positions, preserve them even when outside a limit.
   Unknown entry prices/APRs remain unknown; report post-import P&L separately.
4. Construct the funding schedule in section 6. Repair missing backing or margin
   before discretionary risk. Resolve unknown orders and possible late fills.
5. At first initialization, calibrate pair bases, ladder parameters, execution
   horizons and price-profit exits using only preceding observations. Freeze
   bases for the first experiment; fills and closes change occupied rungs.
6. Initialize a newly eligible pair from information available when it appears.
   A restart restores its previous calibration rather than recalibrating it.

This initial-calibration policy is the proposed first experiment. It adapts
thresholds to accumulated inventory, but does not automatically estimate a new
market center. Periodic refitting remains a separate later comparison.

Missing-history import needs a deterministic allocation policy. Proposed:
identify feasible current pairings, retain unpaired residuals, and classify
unknown-PRD inventory separately. It still consumes risk and funding capacity.
Do not manufacture historical profits or ladder fills.

## 5. Exposure, leverage and baseline acquisition

For the regular-linear research approximation:

```
U_proxy = proxy_shares * current_BTC_per_share
delta   = direct_BTC + U_proxy + sum(signed_futures_BTC)
E       = marked account NAV, including collateral and P&L once
x       = S * delta / E
L_gross = sum(abs(net_contract_quantity_i) * F_i) / E
```

The band applies to net BTC exposure x, not gross holdings alone. Paid direct
BTC/proxy counts in exposure and NAV, but is excluded from gross futures
leverage. Net positions only within the same actual contract and account.
An equal-q long/short pair may add almost no net delta while using leverage.
Use product-specific sensitivities for a native model; the sum above assumes
unit futures response to spot. Stop new risk if NAV cannot be valued.

When below the minimum, suppress new shorts and acquire the eligible long
with minimum APR. Include the proxy when enabled. Size only to the required
exposure and available resources; do not wait for a high-PRD pair to restore
the floor. Proposed tie-breaks are cost, observed liquidity and later expiry.
Baseline acquisitions initially sit outside the PRD ladder, because no paired
high-PRD fill occurred. Reassignment later must transfer ownership explicitly.

Inside the band, permit new long quantity only within reserved headroom. At
or above the maximum, post no new exposure-increasing longs. A price-only
increase above the maximum does not trigger compulsory selling. Authorized
margin recovery, closing and rolling still require their own admission checks.

At frozen marks, an initial sizing bound is:

```
q_long_headroom = max(0, x_max * E / S - delta - reserved_up_delta)
q_short_room   = max(0, delta - x_min * E / S - reserved_down_delta)
```

The allocator then rechecks fees/NAV, all possible partial-fill outcomes,
funding, margin and leverage. No candidate can reserve the same capacity twice.
Order quantity is the minimum of the applicable resource limits and native
lot rounding; no arbitrary small child-order cap is imposed.

## 6. Cash and underlying backing across all expiries

Maintain two linked views: an economic completion schedule and the actual
cash/collateral ledger. The economic schedule describes effective purchases
and sales; the actual ledger records when money really moves. They must not
both post the same profit or purchase cost to cash.

In the simplified zero-cost completion schedule:

| Committed event | Effective cash change | Underlying change |
| --- | --- | --- |
| Long expiry purchase | -q K_long | +q |
| Short expiry sale | +q K_short | -q |

Process events by actual availability time, currency and account. Starting
with allocated resources, every chronological prefix must remain backed.
Positive final balances do not excuse a deficit at an earlier event. Include
known costs and conservative funding assumptions, and project proxy units
after decay. Do not assume today's Treasury valuation is spendable cash at
a future time without its sale/maturity and transfer rules.

An earlier long can back a later short only if the long's purchase is funded.
An earlier short can fund a later long only if the short's sale is covered and
the unallocated proceeds are sufficient. Multiple downstream claims may share
a receipt only up to its amount. Unfilled orders are contingent obligations,
not assets already received. Same-day receipts cannot fund earlier payments
without supported netting or a separately funded bridge.

The actual ledger includes margin posting/release, variation payments,
settlement cash, spot trades, transfers, FX/stablecoin conversion, fees and
interest. Futures variation may already have paid part of the lifetime P&L
before expiry [1]. Net economic cost K is not necessarily the cash purchase
ticket at expiry, which is q times the then-current spot price.

One exact reconciliation identity, before costs/interest and with spot equal
to settlement, helps prevent double counting. Let P_open be cumulative price
P&L on still-open futures, including already-paid variation and unsettled
marks. Starting from C0:

```
cash + unsettled_futures_PnL - P_open
  = C0 + realized_PnL_on_closed_futures
       - sum(completed_long_spot_quantities * their_entry_prices)
       + sum(completed_short_spot_quantities * their_entry_prices)
```

Include free and posted cash once on the left; encumbered cash is not freely
spendable. Add actual costs/interest and non-expiry spot trades explicitly when
present. The left-hand planning amount is not an extra account balance.
Future obligations and possible margin losses remain separate reservations.

Revalidate the whole schedule after a fill, partial close, roll, proxy sale,
settlement or import. A locally profitable close can still remove a long
needed to cover another pair's later short. Decline or restructure that action
unless the resulting portfolio remains funded. Persist all dependency changes.

## 7. Candidate selection and opening economics

For new dated futures, require at least three calendar months remaining.
For two dated legs, apply:

```
separation_ratio = abs(T_A - T_B) / max(T_A - now, T_B - now)
separation_ratio <= configured_ceiling
```

Compare 30% and one-third in research; neither guarantees executable liquidity.
The original 25% remains a historical comparison. A proxy has no invented
expiry and can pair with any otherwise eligible future, without a separation
test. It can be long only. Existing exits and expiry completion remain allowed
after a contract becomes ineligible for new openings.

Choose direction by APR difference, with no near-long/far-short restriction.
For each orientation, compute executable prices/quantity, current ladder H,
the funded schedule, costs and gross leverage. Proposed ordinary admission:
require both the opening PRD target and a positive estimated net completion
gain under the declared cash/holding benchmark. Funding feasibility alone does
not imply profitability. Baseline acquisition is evaluated separately.

For unequal maturities, a positive annualized PRD can coexist with a negative
price spread. Any interest credited to rescue that economics must be stated,
available and supported by the funding model; it cannot be assumed silently.
Do not call uncertain future reinvestment rates locked cash receipts.

## 8. Available waiting time inside the exposure band

The exposure band determines urgency and capacity, but does not mathematically
determine a number of seconds or hours. A time policy and empirical execution
distribution are needed. Use separate clocks for new exposure, matching an
already-filled leg, ordinary closing and funded settlement.

For a new exposure-increasing long, the proposed first-test policy is:

```
u = clip((x - x_min) / (x_max - x_min), 0, 1)
W_band(x) = W_fast + (W_slow - W_fast) * u^gamma
W_new = min(W_band(x), remaining_entry_eligibility,
            remaining_committed_resource_availability)
```

Require W_slow >= W_fast >= 0 and gamma > 0. Measure these horizons from the
decision; they include order-to-market delay. Observation delay already
elapsed to reach that decision. Record execution and fill-notification times
separately. A horizon shorter than the required causal delays cannot promise
completion. Clip deadlines using actual submission/cancellation timing.

For illustration only, a 30%-60% band with W_fast=5 minutes, W_slow=60 minutes
and gamma=1 yields the following new-long review horizons:

| Net exposure | New-long waiting allowance |
| --- | --- |
| Below 30% | Baseline acquisition takes priority; no new shorts |
| 30% | 5 minutes |
| 45% | 32.5 minutes |
| 57% | 54.5 minutes |
| 60% or above | No new exposure-increasing long order |

The 60-minute endpoint is a limit approached from below, not permission to
buy at the maximum. Actual q also decreases as headroom disappears. These
numbers demonstrate the function only; select real horizons from data.

Estimate P(T_matched <= w | target_PRD, quantity, state) from causal replay,
including nonfills, partial fills, both delays and shared market volume.
Calibrate H0, rung increments and W parameters jointly. A longer horizon near
the upper band permits waiting for a better entry; it does not silently alter
the committed rung or assume a profitable eventual fill.

At the new-entry review deadline, cancel/reconcile the unfilled part and
reevaluate. A cancellation request is not an immediate release of capacity.
For the first fixed-base experiment, no automatic target relaxation follows
from a timeout. Changing an entry threshold requires an explicit tested policy.

Short catch-up after a long fill reduces exposure and may be more urgent near
the maximum. It therefore does not inherit W_new's increasing patience.
Use a separately calibrated catch-up horizon, bounded by funding, expiry and
exposure capacity. At its review, either keep the valid funded commitment,
cancel the unmatched remainder, or execute the declared recovery policy.
Never erase a filled leg or assume the pending short filled. Existing unmatched
longs remain real inventory with their own funded expiry purchase obligation.

Ordinary closes also have a separate review horizon. Failure to close can lead
to continued funded holding or a roll. Under the current lifecycle, expiration
of a discretionary closing timer does not force a loss merely because 60 days
remain. Margin or settlement incapacity can require recovery independently.

## 9. Reserve, post and execute an opening

1. Build the complete prospective actual portfolio after netting each candidate
   fill. Recompute the cash/underlying schedule, exposure, gross leverage and
   margin. Include existing live, submitted and cancellation-pending orders.
2. Reserve resources for every possible permitted fill sequence. At the floor,
   stage the long first; a short-first fill cannot be admitted if it breaches
   the floor. Inside the band either order is possible only if its intermediate
   state is admissible. Shorts may lag longs within the maximum exposure.
3. Compute opening limits from causal S, remaining tenors, the other leg's
   observed APR and the committed PRD H:

```
F_A_limit = S * (1 + tau_A * (a_B - H))
F_B_limit = S * (1 + tau_B * (a_A + H))
```

4. Round buy limits down and sell limits up to preserve the intended inequality.
   Reject invalid prices and unsupported native lot amounts. Recheck funding
   using the actual limits and conservative costs.
5. Post only limits sufficiently close to a valid observed market, with a broad
   configurable proximity band. Distant candidates remain calculated locally.
   An always-posted comparison disables this proximity filter only.
6. After a first fill, freeze its executed APR and original tranche target.
   For long A first, target short APR = executed long APR + H. For short B
   first, target long APR = executed short APR - H. Recompute the counterpart
   price with its current remaining tenor and causal index; do not use the old
   unexecuted quote. Recheck price-based funded economics before adding risk.
7. Attribute each partial fill to its own quantity and anchor. Do not raise an
   existing catch-up target when later opening inventory raises the ladder.

There are two configured delays: market/fill observation to decision, and
decision to order arrival. A market event at t can affect a new order no
earlier than t+d_observation+d_order. Exchange inventory changes at fill time;
strategy knowledge changes only after observation delay. Reserve for that gap.

In historical trade replay, a buy fills only on an eligible later trade
strictly below its limit, and a sell strictly above. Fill at the resting limit,
subject to compatible aggressor, available trade volume and participation.
Equality alone does not fill. Allocate each print's volume once across the
account, using deterministic priority. An order arriving after a print cannot
use it. Trade-only replay remains an approximation to queue execution.

Limit age alone is not a cancellation rule. Validate the causal price/index
inputs, distinguish sparse trading from a feed outage, and use a declared
outage policy. No arbitrary numerical quote-age cutoff is agreed.

## 10. Per-pair ladders and recorded fills

Use H_k = H0 + k * increment, with a configured reference quantity per rung.
Derive occupancy from remaining actual matched lots. Each lot's current
executed PRD equals its current short leg's executed APR minus its current
long leg's executed APR; unchanged legs retain their original anchors.

Proposed research reconstruction: sort remaining lots by current executed PRD,
break ties by stable lot ID, and fill consecutive rungs from low to high.
Split a lot at rung boundaries. A fragment qualifies only when its own PRD
meets that rung. Unqualified/unknown-PRD quantity remains visible risk inventory.
Do not use an average PRD to qualify a below-threshold lot.

Closing quantity restores lower levels as occupancy falls. Pending or unmatched
quantity retains separate reservations; one closing-leg fill does not release
the entire pair. A retiring pair stays closed to new openings even if its
ladder falls. Rolls update every affected pair, using the actual new legs.
There is no transferred credit accumulated from closed legs or realized gains.

## 11. Ordinary early closing and profit targets

For a matched equal-q lot with both futures still open, let X_A be its actual
long sale price and X_B its actual short buyback price:

```
gross_close_PnL = q * ((K_B - K_A) - (X_B - X_A))
net_close_PnL   = gross_close_PnL - attributable_cycle_costs
```

Costs include relevant entry/exit fees and funding; rebates enter with their
sign. Use accrued costs once and estimates for unexecuted costs. Ordinary exits
target an explicit cash profit g, so the executable exit-spread ceiling is:

```
R = K_B - K_A - (g + estimated_total_cycle_costs) / q
require X_B - X_A <= R
```

After selling A at X_A, buy B no higher than X_A+R. After buying B at X_B,
sell A no lower than X_B-R. Recalculate for actual partial quantities/costs.
For independently resting legs, first-leg execution does not guarantee the
second; maintain reservations and the declared recovery policy.

The numerical g and its dependence on holding time/remaining opportunity need
calibration. A proposed grid can compare fixed cash-per-unit targets or a
fraction of the positive estimated completion gain. The previous 2%/1% APR
grid is historical context, not a guarantee of a profitable price-based exit.

If the residual price spread lies between zero and the positive entry spread,
early closure realizes part of the gross completion gain. A negative residual
spread can realize more; a wider spread can lose money. If one leg has expired,
evaluate the remaining cash/spot/futures package instead of the two-live-leg
formula. Closing must also preserve backing allocated to other positions.

## 12. Rolling as an opening transformation

Treat each roll as an opening-style candidate against the portfolio's current
funding schedule, as requested. First net its trades against actual positions;
then evaluate the resulting positions and every intermediate fill state.

For example, replacing long A with long C proposes sell A / buy C. Selling
the existing A long closes it; it does not leave a new A short for that quantity.
Remove A's future purchase/receipt obligation, record its realized P&L and
replace it with C's funded purchase/receipt. A retained B short must still be
covered on time. Buying C after B expires cannot provide that earlier backing
unless other unallocated holdings or funded receipts do so.

Replacing short B with short D similarly proposes buy B / sell D. Net the B
close, remove its covered sale/proceeds, add D's obligations and revalidate
later purchases previously relying on B. Excess trade quantity beyond a close
is a real new position and must pass normal admission.

Prefer minimum-APR eligible replacement longs and maximum-APR replacement
shorts, maintaining the staying counterpart's maturity proximity when possible.
Consider a joint two-leg roll if no single replacement forms an eligible pair.
This enlarges eligible combinations; it does not guarantee either execution.
All turnover costs and possible unmatched intermediate states remain explicit.

A roll need not pass the ordinary new-pair high-PRD threshold to serve its
retirement purpose; it must pass funding/risk checks and the declared roll
economic criterion. Its resulting lots occupy the destination ladder only
where their actual current-leg executed PRDs qualify. Preserve realized roll
P&L separately, update old and new pairs, and never add old APR credit.

Use one allocator for opens, closes and rolls. Prohibit conflicting ownership
or reuse of the same backing. Cancellation and partial replacement leave the
old obligations active until actual fills remove them. If neither order of
independent execution is funded, the roll cannot be posted that way; reduce
size, use a supported atomic spread, provide a bridge, or retain funded holdings.

## 13. Retirement reviews and the expiry fallback

Begin retirement planning around three months remaining; stop new discretionary
openings in that contract. Seek economical closing or rolling, with a review
objective before 60 days. The latest hold-to-expiry addition supersedes treating
60 days as a compulsory loss-taking exit.

At review, classify each remaining quantity explicitly: closing in progress;
rolling in progress; funded and reserved for expiry; or requiring funding
recovery. For the expiry path, confirm available cash/underlying, actual account
settlement times, spot/proxy execution access and margin reserve. Persist the
decision so a restart cannot reopen the retiring pair or forget its obligation.

If close-target relaxation is enabled, relax the price-based profit target on
a declared schedule. The old increasing-PRD schedule must not be reused as a
price-profit guarantee. A deadline alone does not authorize losses or a market
order. Under the baseline expiry fallback, continue funded holding when no
acceptable exit/roll fills. Actual funding failure follows the recovery policy,
which can realize losses and must report them.

## 14. Settlement and spot trades, step by step

Cash settlement of a future does not itself deliver BTC [2]. For each actual
net position surviving to expiry:

1. Reconcile the final native settlement and all previously paid variation.
   Credit/debit only the unpaid remainder; remove the expired future once.
2. For a long q, purchase q BTC at the modeled executable spot price. For a
   short q, sell q of its allocated BTC. If using a proxy, convert shares and
   underlying-equivalent quantity under the declared execution/decay model.
3. Apply actual availability times, fees and delays. Do not count final futures
   cash as available before the venue makes it usable.
4. Transfer the resulting underlying or cash to its downstream commitments;
   retain the remaining leg and reservations. Recompute exposure and leverage.
5. When all economic legs have completed, close the lot/cycle, release only
   unused backing and report its full realized result. Residual inventory stays
   on the account and may satisfy baseline exposure or another funded commitment.

Evaluate each settlement plus its planned spot trade as one economic transition
while funding any real timing gap. In the unit-delta approximation, removing
a q-unit long future and buying q spot preserves net BTC exposure; removing
a short and selling its covered q spot does likewise. A planned replacement
purchase is not an extra discretionary long layered on top of the old future.

Remove expired legs from actual pair/ladder inventory. After a long expires,
allocate the resulting spot/proxy and remaining short to their resulting pair,
using the proxy's applicable APR and retaining the short's executed anchor.
After a short expires, retain the remaining long and committed cash as an
unpaired funded package, not a fictitious live short. Preserve original cycle
lineage and realized futures P&L through both transitions; a spot purchase has
its actual spot cost basis, without booking the effective K cost a second time.

At ideal settlement spot S_A and S_B, the lifetime effects are:

```
long:  q*(S_A-K_A) - q*S_A = -q*K_A, with +q BTC
short: q*(K_B-S_B) + q*S_B = +q*K_B, with -q BTC
```

For long-first completion, cash finances the effective purchase and later sale
returns cash. For short-first completion, initial BTC is sold and subsequently
replaced, leaving the original quantity plus the net cash surplus or deficit.
Previously funded/covered earlier positions can supply those resources.

With actual spot executions P_A and P_B instead of their settlement indices:

```
gross_cash_gain = q*((K_B-K_A) + (P_B-S_B) - (P_A-S_A))
```

Spot approximately equal to final futures settlement is the base assumption;
also test mismatch and delay sensitivities. A settlement index may be a time
average rather than the price available for an instantaneous spot trade [3].

## 15. Worked cash and underlying-unit examples

**Why the earlier example needs $250.** At entry spot $100,000, short 1 BTC
with 0.75 years remaining at 5% APR, so K_B=$103,750. Long 1 BTC with one year
remaining at 4% APR, so K_A=$104,000. The positive 1-point PRD coexists with a
negative $250 price spread; maturity separation is 25%.

Suppose spot is $120,000 at short expiry. Selling the BTC receives $120,000,
while total short futures P&L is -$16,250: combined effective proceeds are
$103,750. Suppose spot is $80,000 at long expiry. Buying replacement BTC costs
$80,000, while total long P&L is -$24,000: combined effective cost is $104,000.
Restoring the BTC therefore consumes $250 from other cash, before interest and
costs. This is a lifetime net deficit, not a prediction of a $250 margin call
or an assertion that the spot buy ticket must equal $104,000.

**Convergence versus entry price.** At expiry, spot and the then-current
settlement price can be treated as close. That settlement price need not equal
the original K_A. The future plus spot purchase fixes the effective cost K_A
for its contracted q units. An additional, uncovered purchase uses current
spot; its price has not been fixed by that q-unit future.

For example, if equal-q completion leaves $2,000 cash and final spot/futures
settlement is $80,000, that surplus buys 0.025 BTC. At $120,000 it buys about
0.016667 BTC. Both use spot equal to final futures price. Dividing by the old
entry price would assume an additional hedge that was not held.

**Optional deliberate unit targeting.** Additional future quantity can lock
the effective purchase price for additional units. Ignoring costs/interest,
choose quantities satisfying q_long*K_long = q_short*K_short. Then the
completion cash difference is zero and the underlying change is
q_long-q_short. For K_long=$100,000, K_short=$102,000 and q_short=1 BTC,
q_long=1.02 BTC yields 0.02 additional BTC after completion, provided every
dated obligation is funded. This introduces 0.02 BTC residual long exposure
and extra leverage. It is an optional sizing extension, not the equal-q
baseline, and must obey the band and actual execution prices/lot rounding.

The cash-first equal-q strategy does not guarantee outperforming BTC purchased
with all initial cash. Report the declared cash/holding benchmark explicitly.
Positive cash profit expressed in BTC and total BTC-denominated portfolio
performance are different measurements.

## 16. Proxy expense, liquidity costs and performance accounting

The proxy's agreed ranking APR is a_proxy=e/(1-e)+c, with annual expense
0 <= e < 1 and optional liquidity-cost term c. It has no maturity and no
separation restriction; the real futures partner retains its eligibility rules.

With a gross index and annual retention convention, projected BTC-equivalent
units are U(t)=U0*(1-e)^elapsed_years. A real net-of-expense price series replaces
this explicit decay. Do not subtract the ranking APR again from cash. Direct
BTC can be modeled with e=0; any custody/transaction costs remain explicit.

If margin requires proxy sales and later repurchases, record actual quantities,
prices and fees and recheck expiry backing. Use c as a forecast/sensitivity
when these cash flows are not simulated; never charge the forecast and the
same realized cost twice. No portfolio-margin offset is assumed without an
explicit account model. Avoid reducing proxy backing twice for a sale and an
estimated decay representing that same sale.

Report completed-cycle realized net gain, realized items in unfinished cycles,
and remaining unrealized marks separately. Daily realized variation does not
mean the strategy cycle is closed. Attribute baseline BTC movement, matched
trading, unmatched intervals, rolls, interest/funding, expense and fees/rebates.

Show NAV and P&L in USD and BTC; actual holdings and net delta; gross leverage;
funding and margin reservations; each dated cash/underlying obligation; pair
PRDs and rungs; targets versus executed prices; waits/nonfills; and expiry
completion. Plot open/close/roll/settlement events with quantity, both APRs,
PRD, prices and timing. Include unfinished losses and terminal inventory.

## 17. Event loop, validation and research sequence

At each effective account/market event: apply actual executions and cash flows
once; deliver observations after their delay; reconcile pending messages;
update valuations, proxy units and resources; rebuild affected commitments
and ladders; then plan admissible orders. Proposed scheduling priority is
funding/settlement recovery, committed catch-up and retirements, ordinary
exits, baseline restoration, then discretionary entries. Suppress conflicting
short orders immediately upon entering baseline-acquisition mode, subject to
real cancellation delay. Urgent baseline acquisition can preempt discretionary
work without invalidating already reserved obligations.

Write the event journal and affected allocations atomically before submitting
new commands. Deduplicate fills. Preserve cancellation overlap, pending fills
and expiry clocks. A resumed run must match an uninterrupted run for actual
positions, cash, fees, reservations, ladders and event sequence.

First build a regular-linear funded replay with the above ledger and state.
Use causal preceding-data calibration and held-out execution. Estimate entry
PRD/time/quantity surfaces and exit profit/time distributions from identical
initial states. Retain nonfills, partials, cancellations and censored outcomes.
Run continuously through rolls and settlement without resetting profitable
cycles. Include the same baseline acquisition policy without pair trading as
a benchmark; label a separate 100% BTC comparison.

Required sensitivities include 30% versus one-third maturity separation; zero
fees, ordinary fees and conditional maker rebates; 1 ms on each delay leg
versus slower settings; posting proximity versus always-posted; proxy costs
and margin offsets; expiry execution mismatch; and hold versus roll choices.
Do not assume maker rebates apply to marketable orders or settlement charges.

Acceptance cases must cover both expiry orders, positive PRD with negative
price spread, delayed settlement availability, insufficient earlier proceeds,
no double pledging, early close of an upstream backing position, partial rolls,
netting beyond the old position, proxy decay/sale, variation-margin stress,
unit-targeted sizing when enabled, and exact restart equivalence. The existing
inverse unit studies are not acceptance evidence for this funded linear model.

## 18. Remaining numerical choices and sources

The complete lifecycle is now specified, including funded expiry fallback.
Before implementing a scored experiment, freeze the following choices in a
versioned configuration rather than treating illustrations as approvals:

- Exact band and gross leverage cap; margin, collateral and stress-reserve model.
- 30% or one-third maturity ceiling; calendar-month and settlement-time rules.
- H0 calibration window/objective, rung quantity and increment, and treatment
  of missing-history inventory/pending rung reservations.
- W_fast, W_slow, gamma, catch-up/close review horizons, completion-probability
  objective and permitted actions when a timer expires.
- Price-profit exit targets, roll economic criterion and any target relaxation.
- Entry completion-gain check, actual interest/funding assumptions, fees,
  liquidity participation, posting threshold and spot settlement mismatch.
- Equal-q baseline versus the optional unit-targeted sizing extension.

No new funded return, calibrated numerical winner or application deployment
is claimed by this document. The deferred multi-agent exchange simulation is
outside this work.

External sources support settlement mechanics; strategy rules and algebra above
are the project's design and derivations, not recommendations by these sources.

1. [CME Group: Money Calculations for Futures and Options](https://www.cmegroup.com/education/articles-and-reports/money-calculations-for-futures-and-options) - futures cash variation.
2. [CME Group: Futures Expiration and Settlement](https://www.cmegroup.com/education/courses/introduction-to-futures/get-to-know-futures-expiration-and-settlement) - closing, rolling and cash settlement.
3. [Deribit: Linear Futures](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures) - an example of linear settlement against a time-averaged index; actual venue specifications must be selected for implementation.

This document is the current source of strategy rules. Earlier PRD plans,
expiry derivations and calibration reports are historical detail/evidence;
they do not override its funded settlement permission or price-based exits.
