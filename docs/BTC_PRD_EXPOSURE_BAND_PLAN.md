# BTC PRD strategy with an exposure band

Date: 2026-10-13. Status: **revised after owner clarification; application strategy not implemented**.

Prepared against GitHub master `80be0fc4c30904a0f4dfb16e097de2a001424e64`
on `docs/btc-prd-exposure-band-plan`. This is a new opt-in strategy, not a
change to existing saved strategies. The owner requested a direct raw-data
proof of concept before application integration and authorized the remote push.
A bounded raw-data preflight is recorded in
[BTC_PRD_BAND_DATA_PREFLIGHT.md](BTC_PRD_BAND_DATA_PREFLIGHT.md); it is not a
capital-constrained portfolio replay. No data purchase or deployment is part
of this work. Examples below are not approved production defaults.

## 1. Requested behavior

- Configure minimum and maximum capital proportions in long BTC exposure /
  holdings, for example 30% and 60%, and a maximum leverage on total positions.
- Configure high opening PRD and low closing PRD, for example 2% and 1%.
- Optionally raise the opening PRD with active opening inventory; closing
  positions restores lower opening levels (owner-confirmed).
- Continuously consider futures pairs with both expiries at least three months
  away and expiry separation at most 25% of the longer remaining maturity.
- Post opening pair limits at high PRD while long exposure and leverage permit.
  Permit shorts to lag executed longs within the maximum net-long exposure.
- Post closing limits at low PRD for pairs with inventory, up to the smaller
  available position in the two legs.
- Admit the optional proxy as a long instrument with APR `e / (1 - e)` plus an
  optional annualized margin-liquidity cost term. It is eligible with any dated
  future otherwise eligible; it has no maturity-separation restriction.
- Roll futures approaching less than three months to expiry: seek the lowest
  APR replacement long or highest APR replacement short, preserving the paired
  counterpart and the maturity-separation constraint where possible.
- Select direction by APR difference, without a near-long/far-short restriction.
- First portfolio proof of concept starts entirely in cash. Before application
  integration, define import/recovery from arbitrary holdings and orders.
- Model market-event-to-decision and decision-to-market latency separately;
  the initial experiment can set them to the same value.

The sections below distinguish proposed semantics from unresolved decisions.
They are preparation for implementation, not claims about existing behavior.

## 2. Rate, sign and direction

Proposed compatibility with the prior PRD studies:

```
tau_i(t) = (expiry_i - t) / (365 * 86400 seconds)
a_i(t)   = (F_i(t) / S(t) - 1) / tau_i(t)
D_p(t)   = a_B(t) - a_A(t)
```

`A` is the instrument bought at opening and `B` the instrument sold at opening.
Keep that orientation for the lifetime of the pair. `a` is simple annualized
futures premium, not the project's cash-yield-minus-premium lease return.
Opening buys A and sells B when executable D is at least H; closing sells A
and buys B when executable D is at most L. A closing trade's sell-minus-buy
APR is therefore `-D`, not `+D`. Store both side-based and fixed-orientation
diagnostics with distinct names. Store 2% as 0.02 and a 0.1 percentage-point
increment as 0.001, never as a relative 0.1% increase of H.

Direction is owner-confirmed: APR difference determines the long and short,
with no near/far preference. Examine both oriented opportunities. Do not relabel
the owned A/B roles when market APRs cross. Closing reverses owned inventory,
not a fresh negative-PRD opening experiment. Simultaneous conflicting virtual
positions in one actual contract require the netting rules in section 6.

H > L is required. Report actual currency P&L separately: a change from 2% to
1% PRD is not a guaranteed 1% return on capital, particularly with unequal
maturities, changing spot, funding, fees and asynchronous execution.

## 3. Capital, exposure, leverage and funding

Proposed denominator: current marked USD NAV E, net of costs and liabilities,
including free and posted collateral exactly once and unsettled P&L exactly
once. Futures notional is exposure, not an extra NAV asset. Record initial
capital separately. Stop new risk if E is nonpositive or cannot be valued.

The proxy/direct holding **is included** in net BTC directional exposure. The
earlier reference to reporting gross longs separately did not exclude holdings.
For a USD-linear research model with one-dollar futures response
to a one-dollar spot move:

```
delta_BTC = direct_BTC + proxy_shares * BTC_per_share + sum(signed_futures_BTC)
x        = S * delta_BTC / E
x_min <= x <= x_max
```

This is an explicit linear risk approximation. For native contracts use
`delta_BTC = d(NAV_USD)/dS` under a documented futures/spot shock convention;
include BTC collateral, BTC-denominated P&L and each contract payoff once.
Do not treat inverse face value divided by fill price as an exact, permanent
BTC hedge ratio. Report physical holdings, futures long and short exposure,
net delta, and gross notional separately even when the band uses net delta.

Owner clarification: a fully paid, unborrowed proxy is excluded from the
strategy's futures-leverage numerator. It remains part of NAV and net exposure:

```
G_futures = sum(abs(actual position notional by futures contract))
futures_leverage = G_futures / E
```

Cash/Treasuries and paid proxy holdings are excluded from this numerator.
Track spendable/eligible collateral separately. Gross total BTC exposure may
be reported as a diagnostic but is not this leverage limit. Net contracts only within the same
venue/account/instrument, never across expiries or accounts. A matched long /
short pair still consumes gross leverage even when its net delta is near zero.

The leverage cap is independent of spendable cash, initial/maintenance margin,
collateral currency, haircuts and venue/account availability. A funded spot buy
uses its purchase value; a future consumes margin and loss capacity, not an
assumed free loan. No automatic portfolio-margin offsets across pairs or venues.
Use an explicitly selected margin model; native results need native payoff,
settlement and collateral rules. Any linear treatment of inverse price data
must remain clearly labeled a research proxy.

Example, ignoring costs/basis: E=$100,000, S=$100,000, holding=0.30 BTC.
Net exposure and futures leverage start at 30% / 0.00x. Buying 0.10 BTC of A
takes them to 40% / 0.10x. Shorting 0.10 BTC of B returns net exposure to 30%
but raises futures leverage to 0.20x. At 60%, further long-opening fills are
blocked, but reserved short catch-up may proceed down to the lower band.

### Cash bootstrap and arbitrary-state recovery

The first portfolio proof of concept starts with cash and zero positions,
orders and borrowing. This starts below a positive minimum exposure; it is an
explicit ACQUIRING state, not an invalid input or an invented initial BTC fill.
Proposed bootstrap: admit long/proxy acquisition within maximum exposure and
funding limits; defer any short fill that would take projected net exposure
below the minimum. Transition to NORMAL on reaching the band. Whether the
baseline minimum should be bought promptly in the cheapest-APR long/proxy or
acquired only as opening-limit opportunities fill is still a design choice.
Track time below target. A cash-only native inverse run must explicitly buy or
convert collateral if its account model requires BTC; USD cannot silently
serve as native BTC settlement collateral.

Before application integration, support arbitrary positions in the strategy's
allowed products through a RECONCILING state:

1. Import actual balances, holdings, signed contracts, contract metadata,
   settlement/P&L state, pending orders, cumulative fills and last trade IDs.
2. Restore persisted pair/tranche lineage, original APR anchors, ladder
   occupancy, reservations and in-flight messages when available. Reconcile
   them against the account snapshot, which is authoritative for inventory.
3. Do not send new discretionary orders until unknown orders/late fills are
   reconciled. Cancel only the strategy-owned orders under the selected recovery
   policy; do not assume a pause stopped fills.
4. If pair history is missing, label imported lots explicitly. Propose a
   deterministic feasible matching of existing long and short quantities, using
   APR and maturity eligibility; keep leftover longs and shorts unpaired.
   Do not invent historical entry APR, profit or rung history. Mark an explicit
   opening NAV and use a documented inventory-based ladder seed. Unpriceable
   positions block new risk until valued. Missing ownership/pair assignment
   requires an import policy, not an implicit reset to cash.
5. If below the band, allow exposure-restoring acquisitions and safe reductions
   of shorts. If above it, allow reductions/hedges that restore it. If leverage
   or funding is already excessive, prioritize its reduction. Preserve real
   starting positions even if constraints are violated; do not discard them or
   reject the whole recovery merely because they exceed a configured limit.

Restart robustness requires exact native inventory, not only target weights.
Cost basis may be unknown for imported holdings; report post-import P&L from
opening marks separately from unavailable lifetime realized P&L. Expiry repair
and funding safety override discretionary PRD openings during recovery.

### Exposure-band drift is different from a margin shortfall

A conservative futures-leverage cap reduces risk; it does not pin the BTC
fraction to the band. With $60k proxy and $40k cash, a 10% BTC rise produces
$66k/$106k = 62.264% exposure despite zero futures and zero futures leverage.
This is allocation drift, not a margin call.

Funding can also require cash even when the economic hedge works. Illustrative
USD-linear portfolio: $90k proxy, $10k cash and $60k short futures. Initial net
exposure is 30% and futures leverage 0.60x. A 20% spot/futures rise produces
$18k proxy gain and $12k futures loss: NAV rises to $106k, but settling the
$12k loss requires $2k beyond the initial cash. This ignores margin reserves,
which can make available cash smaller. Proxy sales/recognition therefore matter.

Proposed controls: conservative futures leverage, separate cash/eligible-margin
reserve, shared live-order reservations, and spot/basis/liquidity stress
scenarios. For modest allocation drift, stop worsening orders and let planned
closings/catch-up restore the band where feasible; an optional tolerance and
rebalance deadline prevent continual tiny trades. Cash/margin emergencies and
expiry deadlines have an explicit forced-recovery policy. These are proposals,
not an assumption that normal market movement always requires liquidation.

Record breaches by cause (price drift, fill/latency, imported state or funding),
duration and recovery costs. Do not discard actual fills because a mark moved
after acceptance. End positions are marked, with any forced end liquidation
reported as a separate scenario.

## 4. Pair eligibility

Interpret three months as three calendar months at the decision time, in UTC,
with end-of-month clamping; this choice needs confirmation versus 90 days.
At each decision/refresh require both listed, unexpired futures to satisfy:

```
min(expiry_A, expiry_B) >= add_calendar_months(t, 3)
abs(expiry_A - expiry_B) <= 0.25 * (max(expiry_A, expiry_B) - t)
```

Use remaining duration, not the contract's original tenor or a date number.
Approximate examples: 3/6 months fails (50%); 9/12 months passes (25%);
3/4 months passes (25%). Eligibility can disappear as time passes even with
unchanged contracts. Inspect historical listing/expiry and contemporaneous
trade coverage before choosing a replay window; an empty eligible set is valid.
No inference of newly downloaded data coverage from an old manifest.

New opening quantities require current eligibility, current usable market
observations and risk capacity. When a held future approaches the three-month
boundary, initiate the roll described below and cancel unused opening capacity.
Exits stay allowed. Losing the 25% ratio alone stops new openings; whether it
also triggers an early roll is a remaining policy choice. Perpetuals are outside
this dated-futures rule. The proxy is exempt from maturity/separation tests;
its real futures partner still observes the three-month rule.

### Pair-aware rolling

Owner rule: replace an expiring long with a lowest-APR eligible long, and an
expiring short with a highest-APR eligible short, retaining the counterpart's
identity and the 25% separation condition where possible. Pair/tranche lineage
is therefore required state, including through restarts and partial rolls.

Proposed refinements:

- Start planning before the threshold, with configurable lead time. A
  strict-through limit cannot guarantee completion at the three-month instant;
  define a roll deadline and escalation, and report any failure rather than
  fabricating a fill. Forbid re-opening a contract being retired.
- First restrict replacements to contracts sufficiently beyond the three-month
  threshold and satisfying the ratio with the staying leg; then minimize long
  APR or maximize short APR. Require executable size, funding and an acceptable
  turnover-cost budget. Show both raw APR rank and estimated cost-adjusted rank;
  selecting the latter instead is an explicit option. A maturity hysteresis
  buffer avoids rolling straight into another near-threshold contract.
- When enabled, include the proxy in long-replacement candidates using its
  expense-plus-liquidity APR and its maturity exemption. It may preserve the
  short counterpart when no suitable dated long exists. It cannot replace a
  short leg because the proxy is long-only. A compulsory roll need not wait
  for the ordinary low-PRD closing threshold or qualify as a new high-PRD entry.
- Reserve old and replacement orders jointly. Close-first temporarily changes
  net exposure; replace-first temporarily increases gross futures notional and
  margin. Choose the sequence whose possible partial fills fit available
  headroom, or execute bounded chunks. Do not assume an atomic calendar spread
  from two independent trade tapes.
- Keep the economic pair/tranche ID while changing its instrument allocation.
  Record old/new execution prices, realized P&L, fees and actual replacement
  APR. Preserve the original entry target for attribution, but do not reuse
  the retired leg's APR as the replacement's execution anchor. Closing targets
  apply to the current owned pair. Rolling is neither a new PRD opening nor a
  completed strategy exit and must not reset/free its ladder occupancy.
- Replacing with the same contract as the staying opposite leg would net the
  position: classify this as closing the pair, not as a new zero-gap pair.
- If no replacement preserves the ratio: try rolling both legs together to an
  eligible pair; otherwise close the pair, or retain the counterpart temporarily
  only under an explicit unmatched-exposure policy. Any relaxed-ratio fallback
  must be separately enabled with a ceiling and deadline. Do not silently turn
  'if possible' into unrestricted maturity mismatches.
- If both legs need rolling, optimize their replacements jointly. The
  individually lowest long APR and highest short APR may not form an eligible
  pair. Existing counterpart closings and roll reservations must not compete
  for the same inventory.

## 5. Orders, reservations and execution

### Shared capacity

All pairs share one account risk allocator. Listing all candidates does not
authorize a full-size order on every candidate using the same capacity.
Reserve capacity for live orders, submitted/unacknowledged orders, replacement
overlap, possible late fills and the unfinished paired leg. For each feasible
fill combination, require the exposure band, gross leverage, cash and margin
constraints after costs. Do not assume both legs fill together.

In a linear model at frozen marks, exposure checks reduce to the endpoints
where all exposure-increasing orders fill and where all decreasing orders
fill; gross/margin checks require their own conservative envelope. Include
price/fee buffers and revalue at every relevant event. A held long with a
reserved future short must reserve that eventual gross increase too.

At full long exposure, block new long-opening capacity while allowing safe
short catch-up and exits. At the minimum, a short-first opening or a sell-long
closing leg may be inadmissible even if a completed pair would be neutral.
If both opening limits must rest simultaneously, their entire possible fills
must fit inside the band. Otherwise stage long-first at the floor. This is a
real choice: simultaneous independently fillable orders at the lower boundary
are incompatible with a hard prohibition on going below that boundary.

Opening short quantities must belong to an explicit pair/tranche and cannot
create an unrelated naked short. Proposed default: long-first; allow either
leg first only under a separate option with reserved lower-bound headroom.
For exits, buying back the short first increases net exposure, while selling
the long first reduces it; stage whichever direction has headroom. At either
boundary do not disable all closing activity by a generic opening gate.

### Sizing and scheduling

Pending inputs: opening child size, per-pair cap, account concurrency cap,
native lot/dust tolerance, and allocation among competing candidates. Proposed
deterministic allocation: risk/expiry actions, closing and existing catch-up
before new openings; rotate eligible pairs in round-robin order with stable
tie-breaking. A different liquidity/PRD ranking is an explicit policy change.
Reserve the same inventory/capacity only once. Log candidates left unquoted
because insufficient capacity prevents resting every pair simultaneously.

The prior research default of 0.02 BTC per asynchronous leading fill is not
silently imposed as a total unmatched-position cap here. The new request
allows accumulated unmatched longs up to band capacity. Proposed: retain
0.02 BTC as an optional child-order size example; keep any independent total
unmatched cap as a separate configurable restriction requiring confirmation.
Do not inherit the prior six-level 0.6 BTC total cap as an implicit default.

### Limits and partial fills

For a target fixed-orientation PRD D*, proposed initial limit boundaries are:

```
F_A* = S * (1 + tau_A * (a_B - D*))
F_B* = S * (1 + tau_B * (a_A + D*))
```

Open with buy A / sell B at H; close with sell A / buy B at L. Round every
buy limit down and every sell limit up to the historical tick to preserve the
desired inequality. Reject nonpositive prices and unsupported native sizes.

After the first fill of a tranche, freeze its actual execution APR and the
tranche's original target. If A filled, counterpart target is a_B*=a_A_fill+D*;
if B filled, a_A*=a_B_fill-D*. Recompute the remaining leg's dollar limit using
current causal S and its decreasing tau. Do not keep referencing an unexecuted
quote once a fill exists. Carry separate anchors for partial tranches, or a
provably equivalent aggregation that preserves every tranche's target.

This proposes the historical executed-APR anchor. Also report a common-time
PRD by revaluing both executed prices using the same completion spot/time;
these two measures differ when spot/time move. Neither guarantees a currency
profit. Choosing a common-time price anchor instead is a separate pending
economic decision; do not mix the two during one tranche.

Increasing the entry ladder must not raise the catch-up target of an already
filled tranche. Cancel/reprice only unfilled opening capacity. Closing an
unmatched long as a risk action first cancels/reconciles any pending short
catch-up so that a late sell cannot silently leave an unintended short.

Owner-confirmed latency: use `d_observation` from the market trade/fill to the
strategy decision, and `d_order` from decision to arrival at the market. Set
both to the same configurable d in the initial experiment. A trade at t can
therefore affect a new order no earlier than t + 2d. A fill at t_f changes the
exchange position immediately, becomes known at t_f + d, and can produce a
catch-up/replacement arriving at t_f + 2d. Risk reservations cover the period
before notification. Existing orders can fill throughout; no instant local
coupling/cancellation after an as-yet-unobserved fill is allowed.
Apply the same command latency to cancellations/replacements and record any
extra compute/ack delay explicitly instead of double-counting the same d.
Freshness gates apply to observations used for new/repriced limits. A frozen
executed APR has no quote-age expiry; the current index needed to price its
catch-up order still needs valid causal observations. On stale feeds, stop new
discretionary risk and use a declared cancel/recovery policy for existing
orders. Timeout, allowed slippage, market fallback and target relaxation remain
separate parameters; relaxation is off unless expressly selected.

Preserve strict-through tape fills: a buy requires a later trade below its
limit; a sell requires a later trade above its limit. Model execution at the
resting limit, with explicit fees/slippage. Equality alone is insufficient.
One historical print has one participation budget shared across all simulated
orders in the account; allocate price/time priority deterministically. Never
reuse its full volume for every competing pair. Independent strategy scenarios
may replay the same print separately. Prevent self-crossing own orders and
document that tape-based fills still do not reproduce a full queue.

Cancellation keeps remaining reservations until acknowledgement and trade
reconciliation. Accept late fills, deduplicate trade IDs, and only then free
capacity or hedge confirmed imbalance. Tied timestamps must have a documented
causal ordering; no new observation can fill an order retrospectively.

## 6. Pair inventory and closing

Persist pair ID, oriented symbols, ladder epoch/level, opening tranche IDs,
native quantities, BTC risk equivalents, costs, realized P&L, matched and
unmatched quantities, closing reservations, and remaining anchors.

For equal-BTC linear legs, closing quantity is the minimum of the pair's
remaining long BTC and absolute remaining short BTC, less quantities already
reserved for closing. For native contracts, convert through the chosen sizing
adapter, round toward less risk and retain/report residual dust. Do not take
the minimum of raw contract counts for different multipliers. Partial closes
reduce actual inventory immediately; completion counts only the matched amount.
Proposed lot attribution is FIFO within each pair/level.

The account has one net position per instrument/account, even if several virtual
pairs refer to it. Virtual pair lots must reconcile to that actual position and
must not manufacture extra closeable inventory or freed leverage. Proposed
baseline avoids conflicting opposite pair ownership and nets same-direction
orders with explicit allocation. This is a proposed bookkeeping restriction,
not a near/far selection rule. Supporting arbitrary cross-pair opposite
positions requires a specified lot-netting and reassignment algorithm before
it is enabled, including imported positions. Closings cannot create an
unowned short/long accidentally. A virtual closing need not be exchange
reduce-only when virtual opposing allocations have been netted; the permitted
actual order must instead reconcile the entire account allocation explicitly.

## 7. Optional opening ladder

Owner-confirmed: **closing positions restores lower opening levels**. The
earlier cumulative, never-reset ratchet is rejected. Proposed exact semantics:

```
Q_active = sum(max(remaining_long_allocation, remaining_short_allocation)
               for each owned tranche in the ladder scope)
new_opening_level = floor(Q_active / level_amount)
H_new = H_0 + new_opening_level * increment_pp
```

Allocation units are recorded reference BTC equivalents at entry, adjusted
proportionally for actual native-contract closure, not recomputed from changing
spot prices. This avoids ladder changes solely from mark movements. Unmatched
inventory consumes capacity; opening both legs is counted once. An isolated
first closing-leg fill does not release a pair's allocation while its other
leg remains outstanding. A matched partial close releases only its completed
fraction. Explicit disposal of a wholly unpaired tranche also releases its
allocation after cancel/reconciliation.

Reserve ladder capacity for pending orders as well as executed inventory.
Split new children at level boundaries; do not retroactively reprice fills.
Example: Q_active=0.25 BTC with 0.10-BTC levels quotes new capacity at H_2.
A completed 0.06-BTC close leaves 0.19 BTC and restores 0.01 BTC at H_1 before
new inventory crosses 0.20 BTC and returns to H_2. Existing catch-up orders
retain their own original target, even when the new-opening threshold falls.

Proposed scope remains per economic pair family. Rolls preserve that family
and its occupied allocation, so changing symbols does not restart at H_0.
An account-wide ladder is an alternative requiring confirmation. FIFO is a
proposed closing-lot rule; its actual lot P&L remains distinct from the aggregate
level counter. Preserve counters through pause/restart. Reconstruct them from
imported inventory under a declared policy when original history is absent.

## 8. Optional proxy as the long leg

Let e be a fractional annual expense with 0 <= e < 1. Under an annual discrete
retention convention, `1/(1-e)` is a **gross cost factor**. Its net annual cost
rate is `1/(1-e)-1 = e/(1-e)`. At e=0.0025 the factor is 1.0025063 and the
net cost rate is about 0.25063%, not an APR of 100.25063%.

Owner-confirmed ranking convention:

```
a_proxy = e / (1 - e) + c_margin_liquidity
```

`c_margin_liquidity` is an optional nonnegative annualized surcharge for the
expected fees, spread, slippage, conversion, cash drag and inefficiencies of
selling/rebuying proxy to fund MTM when the account does not adequately recognize
it against shorts. Proposed initial control: manual basis points per year,
with a separate `proxy_offsets_shorts_in_margin` scenario switch. Later estimate
the surcharge from expected annualized liquidation/rebuy turnover times costs,
plus cash drag, using only information available before the decision. It is
not an assumed extra return or automatic margin credit. Recognized offsets can
reduce costs without eliminating all residual cash/settlement needs.

This ranking penalty is an ex-ante forecast. Charge actual simulated sale/buy
fees and cash drag to P&L when incurred; do not deduct the forecast again from
realized P&L. Record forecast versus realized cost. Economic ownership is
separate from location/eligibility of collateral: an external proxy cannot
silently be treated as eligible venue collateral.

The proxy is owner-confirmed eligible with any otherwise eligible dated
future: no fictitious proxy expiry and no 25% separation test. The real future
still respects the three-month opening/roll rule. Proxy is long-only; opening
buys proxy and shorts the future, closing sells owned proxy and buys back the
future. Core holdings are excluded from pair closeable inventory unless
explicitly assigned, and the exposure band still applies.

'Executable pricing rule' means the actual assumed cash paid/received and time
for the proxy trade, distinct from its ranking APR. Honor the requested 24/7
near-spot synthetic proxy for the proof of concept:

```
buy_proxy_price(t_arrival)  = available_spot(t_arrival) * (1 + buy_slippage)
sell_proxy_price(t_arrival) = available_spot(t_arrival) * (1 - sell_slippage)
```

Add explicit commissions/conversion costs and BTC-per-share normalization if
shares are used. Near-spot execution is a declared synthetic fill assumption;
the futures leg still requires a strict-through trade. Do not use the old
decision-time spot price as a guaranteed future execution price. If only
trade-attached index data exist, execute at the first suitable causal index
observation after order arrival, record its delay, and do not claim an observed
spot/proxy transaction. Spot slippage should have a sensitivity range. No
real ETF market-hours constraint is added to this synthetic test.

The proxy's APR is fixed by the configured expense/surcharge, so placing the
future limit is the natural way to target the spread. If the future fills
first, the proxy can execute after the prescribed response/order delay; if
proxy fills first, freeze actual quantity/cost and leave an explicit unpaired
long until the permitted future short fills. Report target versus achieved
spread and delay/slippage. Do not let a synthetic proxy fill magically force
the other leg or make an arbitrary APR constraint executable.

For synthetic holdings, accrue the expense once under a documented retention
convention (e.g. annual retention 1-e extended as (1-e)^years). The old ledger's
continuous exp(-e*years) convention differs slightly and must not silently
replace the new convention. Real net-of-expense price series need no duplicate
expense debit. The surcharge forecasts liquidity costs; it is not proxy unit
decay. Cash funding/opportunity cost is separately attributed.

## 9. Implementation map and preparation gates

Inspection at the base commit establishes:

| Component | Existing capability | Required work |
| --- | --- | --- |
| `funded_ledger.py` | USD-linear, long-only, full-notional funding; rejects inverse contracts, shorts and leverage | Add a separately versioned signed-position ledger and explicit margin adapter; reuse proven fee/settlement concepts without relaxing old invariants globally |
| `paired_transfer.py` | Funded transfer lifecycle, partial fills, delayed observations/commands, reservations, restart state | Extract/reuse causal execution primitives; new multi-pair scheduler, opening/closing tranches, account-wide reservations and ledger integration |
| `btc_trade_backtest.py` | Accepts `legacy` and `cost_aware_paired`; durable replay integration | New opt-in selector, proposed name `btc_prd_band`, with independent config validation and checkpoint schema |
| `trade_replay.py`, tape readers | Historical event replay | Global print-volume allocation, native quantity metadata, strict-through and deterministic event ordering |
| GUI, presets, API and exports | Saved settings and shared run inspection | New strategy-specific settings, migration preserving old runs, band/leverage/pair/lifecycle diagnostics |
| Tests/audit framework | Funded ledger, paired execution, backtest, exports and restart tests | New signed accounting and reservation acceptance suite; preserve all prior strategy behavior |

The 'shorts/leverage disabled' statement refers specifically to the integrated
`FundedLedger` used by the existing cost-aware funded-transfer strategy:
`ContractSpec` accepts only USD-linear payoff and `_future_fill` raises
`FundingError("Short futures/leverage is disabled")` if a fill would make a
contract position negative. Its collateral policy requires full long notional.
It is not a statement that the exchange or every earlier project strategy
forbids shorts. Earlier independent PRD research already models signed inverse
positions, but does not provide the proposed cash/margin/band/restart model.

Research first, application integration later:

1. Inspect raw-data coverage and eligibility. The completed local preflight
   verifies 182 compressed files / 1,149,605 raw rows; both inspected dated
   pairs have zero eligible seconds under the 25% rule. See the linked report.
2. Freeze a declared proof-of-concept configuration (cash capital, net band,
   futures leverage, margin model, bootstrap, ladder scope/size, proxy expense
   and surcharge, equal delay d). Use raw strict-through futures trades and
   the declared synthetic near-spot proxy; no application deployment needed.
3. Build an isolated research replay with actual position/reservation accounting
   and margin assumptions. Validate partial fills, cash startup, two-stage
   latency, rung restoration and pair-aware rolling on deterministic cases.
4. Run the direct sample and report every fill, matched/unmatched inventory,
   fee/MTM/collateral cash flows, ladder occupancy and P&L reconciliation. Compare
   equal delays, conservative participation and proxy-cost/offset assumptions.
   Include time without exits and mark residual inventory; do not label a
   quote-crossing screen as portfolio performance.
5. Only after reviewing that proof of concept, integrate a separately versioned
   signed ledger, strategy selector, GUI/API/preset controls and durable worker
   state. Arbitrary-position import and pause/restart equivalence are required
   before integration is accepted. Existing strategies retain their semantics.

Minimum future acceptance cases:

- Expiry rule boundaries, calendar-month edges, newly listed contracts, empty
  eligibility, and continuing exits after an opening filter fails.
- Open/close PRD direction, limit inverses and rounding; first-fill APR versus
  common-time APR after index/time drift; equal-time events cannot look ahead.
- Both exposure boundaries, independent leg fills, partial closes, fees/NAV
  changes, price gaps and simultaneous orders across many pairs.
- Fully matched pair with zero incremental net delta still uses gross leverage;
  catch-up gross capacity remains reserved; no cash or collateral double count.
- Same instrument shared by pairs, no phantom opposite inventory, no duplicated
  close reservations, no duplicated tape liquidity and no self-match.
- Cancel/replace overlap, lost/delayed responses, duplicate/late fills, timeout,
  forced exit and recovery during expiry/margin stress.
- Ladder boundary crossing, partial/lagging legs, restart, closing/reopening and
  lower-level restoration only for released inventory; no executions retroactively
  repriced. Rolling carries rung occupancy and pair identity to new symbols.
- Native inverse versus linear accounting, collateral exposure, lot/dust
  handling and closed-round-trip P&L; reject unsupported combinations.
- Proxy disabled/enabled, e=0, expense/surcharge units, synthetic 24/7 pricing,
  offset-recognized/unrecognized margin scenarios, first post-arrival index
  observation, expiry-filter exception and no forecast-cost double charging.
- Cash-only ACQUIRING state; arbitrary long/short/proxy imports inside/outside
  bands, missing historical pair metadata, unknown pending orders and late fills.
- Pair-aware one-/two-leg rolls with partial fills, unavailable ratio-preserving
  replacements, deadline escalation and no occupied-rung reset on contract change.
- Continuous versus resumed runs have identical positions, orders, reservations,
  ladder counters, fees, P&L and audit sequence; immutable input/version hashes.

Required outputs: net exposure versus band; holding and long/short futures
exposures; gross leverage and reserved headroom; actual and reserved margin;
open matched/unmatched quantities in BTC and USD; cumulative matched and gross
turnover separately; realized/unrealized P&L and NAV in USD/BTC; fees/funding;
per-pair target ladder and execution PRDs; opening/closing markers with quantity,
both APRs, target/original/effective PRD and timestamps. Include breach/recovery
and rejection reasons, nonfills/timeouts, and matched-only weighted bought/sold
PRDs. Benchmark against the same initial BTC/cash portfolio as well as any
separately labeled 100% BTC comparison. The exposure band changes that benchmark.

## 10. Decision register after owner clarification

| ID | Topic | Confirmed scope and remaining choice |
| --- | --- | --- |
| D1 | Exposure | Proxy/direct holdings count alongside signed futures; current-NAV delta definition proposed |
| D2 | Leverage | Exclude paid proxy; use gross futures notional / NAV; choose cap, venue/payoff and separate margin/cash model |
| D3 | Startup/restart | Cash-only first POC; arbitrary allowed-product holdings/orders before integration; prompt baseline buy versus opportunity-driven bootstrap remains open |
| D4 | Pair direction/maturity | APR determines sides; no near/far restriction; three-month roll required; calendar-month interpretation and ratio-only early rolls remain proposed |
| D5 | Asynchrony | Shorts may lag within exposure capacity; long-first at floor and safe either-leg-first inside band proposed |
| D6 | Ladder | Closures must restore lower levels; active-inventory formula proposed; scope, amount and partial-close details to finalize |
| D7 | Latency/sizing | Two equal configurable delay legs for first POC; sizes, freshness, cancellation and concurrency explicit |
| D8 | Catch-up PRD | Executed-leg APR anchor proposed; common-time diagnostic separate; no silent relaxation |
| D9 | Rolling/recovery | Lowest-APR long / highest-APR short preserving counterpart ratio where possible; roll lead time, fallback/deadline, tolerance and cash reserve to finalize |
| D10 | Proxy | e/(1-e), any eligible partner, synthetic 24/7 near-spot execution, optional annual margin-liquidity surcharge confirmed; numerical costs/offset model to choose |
| D11 | Research sequence | Direct raw-data analysis before application integration; preflight completed, capital-constrained strategy replay pending |

Numeric inputs still needed include capital, actual x_min/x_max, maximum
leverage, H/L, optional ladder amount/increment, sizes, delays, quote ages and
risk-recovery settings. Example values in the request remain examples. Use
explicitly labeled scenario values for research; do not turn them silently
into production defaults or claim that a leverage number alone proves funding.

## Sources and related design

- Repository inspection at the base SHA above: `funded_ledger.py`,
  `paired_transfer.py`, `btc_trade_backtest.py`, `docs/TODO.md` and
  [COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md).
- Earlier project PRD studies provide the simple premium-APR, strict-through,
  executed-APR anchor and matched-only measurement conventions; they are
  research references, not evidence that this portfolio strategy is integrated.
- [Deribit inverse futures specification](https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures)
  (checked 2026-10-13): inverse BTC futures use USD-denominated contracts and
  BTC margin/P&L settlement. Historical instrument metadata and rules must be
  versioned for replay rather than replacing history with today's settings.
- [Deribit portfolio margin](https://support.deribit.com/hc/en-us/articles/25944756247837-Portfolio-Margin)
  and [cross-collateral specifications](https://support.deribit.com/hc/en-us/articles/25944777203869-Cross-collateral-specifications)
  (checked 2026-10-13): margin depends on the account model, recognized equity,
  stress scenarios and collateral eligibility. These sources do not establish
  margin recognition for an external BTC proxy or historical replay settings.
