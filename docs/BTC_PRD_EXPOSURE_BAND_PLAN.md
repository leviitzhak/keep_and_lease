# BTC PRD strategy with an exposure band

Date: 2026-10-13. Status: **revised after owner clarification; application strategy not implemented**.

Prepared against GitHub master `80be0fc4c30904a0f4dfb16e097de2a001424e64`
on `docs/btc-prd-exposure-band-plan`. This is a new opt-in strategy, not a
change to existing saved strategies. The owner requested a direct raw-data
proof of concept before application integration and authorized the remote push.
A bounded raw-data preflight is recorded in
[BTC_PRD_BAND_DATA_PREFLIGHT.md](BTC_PRD_BAND_DATA_PREFLIGHT.md); it is not a
capital-constrained portfolio replay. The full saved catalog's daily maturity
minima and exact 25% windows are in
[BTC_MATURITY_SEPARATION_HISTORY.md](BTC_MATURITY_SEPARATION_HISTORY.md).
No data purchase or deployment is part
of this work. Examples below are not approved production defaults.

Audience and purpose: this is our internal research and implementation
specification, rather than an external strategy presentation. It preserves
agreed behavior, marks recommendations as proposals, maps them to accounting,
order/pair/checkpoint state and modules, and supplies future acceptance cases.
It is useful implementation input, but a proposed rule in this file is not an
owner decision. The material unresolved policies are collected in section 10.
The first raw-data execution calibration is recorded in
[BTC_PRD_EXECUTION_CALIBRATION.md](BTC_PRD_EXECUTION_CALIBRATION.md). No final
H/L values or funded portfolio-performance findings exist yet.

## 1. Requested behavior

- Configure minimum and maximum capital proportions in long BTC exposure /
  holdings, for example 30% and 60%, and a maximum leverage on total positions.
- Configure high opening PRD and low closing PRD, for example 2% and 1%.
- Calibrate both the opening/closing gap and its absolute level against data;
  the example rates are placeholders, not fixed experiment settings.
- Optionally raise the opening PRD with active opening inventory; closing
  positions restores lower opening levels (owner-confirmed). Ladders are
  per pair, not account-wide (owner-confirmed).
- Continuously consider futures pairs with both expiries at least three months
  away and a configurable expiry-separation ceiling relative to the longer
  remaining maturity. Original example: 25%; owner now proposes considering
  30%, which is recommended as the first research setting below, not a deployed
  default. Preserve 25% as a historical comparison.
- Post opening pair limits at high PRD while long exposure and leverage permit.
  Permit shorts to lag executed longs within the maximum net-long exposure.
- Post closing limits at low PRD for pairs with inventory, up to the smaller
  available position in the two legs.
- Admit the optional proxy as a long instrument with APR `e / (1 - e)` plus an
  optional annualized margin-liquidity cost term. It is eligible with any dated
  future otherwise eligible; it has no maturity-separation restriction.
- Roll futures approaching less than three months to expiry: seek the lowest
  APR replacement long or highest APR replacement short, preserving the paired
  counterpart and the maturity-separation constraint where possible. Stop new
  openings in retiring pairs; aim to have the old positions removed strictly
  before 60 days to maturity. Three months remains the opening/retirement-start
  boundary; 60 days is the owner's current completion target.
- When no permissible roll exists, progressively increase closing PRD from L
  over time. Move actual surviving/replacement lots to the resulting pair;
  derive its ladder from their current executed APR differences. Do not add
  cumulative credit from completed legs.
- Every affected pair keeps updated executed PRD and immutable execution
  history, including when a new opening nets an existing opposite leg.
- Select direction by APR difference, without a near-long/far-short restriction.
- First portfolio proof of concept starts entirely in cash. Before application
  integration, define import/recovery from arbitrary holdings and orders.
- Below minimum exposure, suppress short openings and acquire lowest-APR longs.
  Price-only drift above maximum exposure blocks new longs without forced
  exposure reduction.
- Model market-event-to-decision and decision-to-market latency separately;
  the initial experiment can set them to the same value.
- Derive order quantities from exposure-band headroom, subject to leverage,
  funding and shared reservations. Submit only limits sufficiently close to
  the observed market, with a broad configurable proximity threshold.

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

### Calibrate both the gap and its location

The owner's 2%/1% values are placeholders. Parameterize `H = L + w`, with
positive entry/exit gap w, and calibrate both w and L to causal historical
observations. The gap measures targeted APR-spread convergence; its location
determines entry/exit frequency, time holding inventory, and roll frequency.
It does not alone determine actual paired P&L for unequal maturities.

Owner clarification, 14 October: both location and gap must come from recent
observations and update while the strategy runs. The fixed-grid studies do not
implement this requirement. [Live calibration and market-simulation research](BTC_PRD_ADAPTIVE_MARKET_RESEARCH.md)
specifies a proposed causal estimator, policy-selection schedule, inventory
transitions and competing-agent feasibility plan. Numerical windows/cadences,
adaptive held-exit behavior and ladder transitions remain research choices.

For equal-BTC USD-linear legs and quantity q, before costs:

```
PnL / q = (F_B_entry - F_A_entry) - (F_B_exit - F_A_exit)
F_B - F_A = S * (a_B * tau_B - a_A * tau_A)
          = S * (tau_B * D + (tau_B - tau_A) * a_A)
```

Thus the common APR level, both maturities and spot also matter. For example,
hold S at $100,000: at entry, tau_A=0.75, tau_B=1.00, a_A=3%, a_B=5%, so
D=2% and the price spread is $2,750. After 0.10 year, let a_A=8%, a_B=9%:
D=1% but tau_A=0.65, tau_B=0.90 and the price spread is $2,900. A one-BTC
long-A/short-B pair loses $150 before costs despite the one-point PRD narrowing.
This is an algebraic illustration, not an observed result. Native inverse
contracts require their actual BTC cash-flow/P&L accounting, not this formula.

Calibrate on chronologically prior windows; freeze the adaptive algorithm on
each evaluation window, allowing numerical H/L updates from information already
received exactly as in live operation. Screen eligible pairs' causal APR/PRD distributions, then
measure H/L combinations with actual strict-through fills, both latency legs,
partial positions, costs, funding, bootstrap, ladder and roll/exit rules. Compare
net P&L, drawdown, capital utilization, time to close, censored unfinished pairs
and forced-exit losses. Include terminal inventory marking and sensitivity to
costs/delays. Do not select only completed profitable pairs or tune levels on
the same future data used to claim performance. A quote-crossing count cannot
calibrate portfolio returns by itself.

### Concrete proposed calibration procedure

1. Freeze the experiment's capital, exposure band, leverage, native payoff and
   margin model, costs, capacity-based sizing, two delays, proxy assumptions and roll/exit
   policy. Recommend 30% separation for the main research case, with 25% and
   one-third as declared sensitivities. Compare H/L candidates under identical
   inputs, initial cash and order state. A subsequent walk-forward path carries
   its own real inventory forward rather than resetting at every refit.
2. Build causal PRD histories for eligible pairs using a common contemporaneous
   spot/index convention and explicit observation ages. Keep futures/futures
   and proxy/futures populations separate. Inspect both APR-driven directions,
   retaining original orientation for every owned pair. Estimate time-weighted
   distributions, entry excursions and conditional time to lower levels; do not
   let the most frequently traded contract dominate merely by print count.
   Raw distribution statistics are screening evidence, not executable spreads.
3. Predeclare a small coarse search over `L` and positive `w`, with `H=L+w`.
   Training-window PRD quantiles can locate the search range; avoid a separate
   fitted parameter set for every named expiry. Use broad maturity categories
   only if they have enough independent history. Equal gaps at different
   locations, and several gaps at each location, must both be compared. Expand
   a range only under a recorded development rule, not by inspecting test P&L.
4. Replay each candidate through actual strict-through futures fills at limits,
   both delays, shared print volume and risk capacity, partial/unmatched legs,
   funding, proxy costs, rolls and escalating no-roll exits. First inspect H/L
   with the optional ladder disabled, then validate shortlisted levels with the
   chosen ladder and all final lifecycle rules. A crossing probability or
   apparent round-trip APR gap is not the selection objective.
5. Rank full NAV/cash-flow results net of costs, using a predeclared objective:
   proposed incremental return over the same baseline-acquisition policy
   without discretionary pair trading, subject to drawdown and funding limits.
   Also report directional BTC contribution, matched spread P&L, capital/margin
   occupied, duration, exit/roll losses and unfinished positions. Include every
   attempted trade; mark residual inventory. Return per capital-day is a useful
   diagnostic, not a reason to ignore unmatched losses or unused cash.
6. Select the adaptive rule on prior training/validation blocks and evaluate
   that rule unchanged on later blocks, permitting causal numerical refits.
   A starting example is six months for development and the next
   three months for testing, repeated chronologically; extend blocks if too few
   completed/rolled cycles are observed. Training must not use an eventual exit
   beyond its cutoff: mark open positions there. Preserve a final untouched
   test period and record every candidate tried. Reusing test results to choose
   another setting makes that period development data.
7. Prefer a broad region of similar results in the L/w heatmap across time
   blocks, over an isolated historical maximum. Check costs, delays, fills,
   proxy assumptions and maturity ceiling around the chosen region. A lack of
   stable candidates is a valid result; no profitable H/L pair is presumed.
   The owner now requires live refitting of location and gap. Preserve executed
   tranche anchors and committed catch-up obligations. The current proposal
   compares adaptive ordinary closing targets with entry-frozen targets and
   rebuilds ladder qualification from remaining fills under each new base.
   Threshold updates must retain actual risk inventory and reservations;
   retirement escalation remains explicit. See the adaptive research design
   for the proposed cash-P&L guard and unresolved transition choices.

The immediate next research output can be eligible PRD distributions and
coarse fill/holding-time screens. Selecting final H/L needs the isolated funded
lifecycle replay already on the TODO; it does not require GUI integration.
Statistical caution: searching many configurations raises false-positive risk;
an ordinary holdout alone does not resolve repeated selection. See Bailey et al.,
[The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
The procedure above is our proposed protocol, not a claim that this paper
validates this strategy or guarantees out-of-sample performance.

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
Owner direction: while below the minimum, suppress new short-opening orders
and acquire the lowest-APR eligible long (including the enabled proxy). This
acquisition need not wait for a high-PRD pair opportunity. Transition to NORMAL
only after confirmed exposure reaches the minimum, allowing for costs, lot
rounding and already reserved orders. Track time below target. Apply the same
policy after a later below-minimum condition; reducing existing shorts may also
restore exposure, with selection and attribution recorded separately.

Use current causal, valid APRs; rank by raw APR, then proposed tie-breaks of
lower turnover cost, deeper observed liquidity and later expiry. A standalone
future must satisfy the three-month floor plus the selected roll buffer; it
does not need a hypothetical short counterpart to pass the pair-separation
test. Reserve aggregate acquisition capacity, cash and margin before posting.
Do not buy an unlimited amount of the apparently cheapest contract or ignore
its collateral/roll cost. Keep raw-APR selection and cost-adjusted sensitivity
separate so the requested objective remains visible. If no eligible long can
be funded or filled, stay ACQUIRING and report the shortfall.

Cancel/reconcile existing strategy short-opening orders on entry to ACQUIRING;
late fills remain possible and must be reserved, not deleted. Previously owned
shorts need not be liquidated merely to forbid new shorts. For the proof of
concept, label minimum-exposure acquisitions as baseline inventory outside the
PRD ladder, because they did not execute a high-PRD opening. Reassignment of a
baseline lot to a later qualifying pair/roll transfers ownership explicitly
and counts it once. A different baseline-ladder seed is an explicit scenario.

A cash-only native inverse run must explicitly buy or
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
5. If below the band, use the acquisition policy above. If above it, block new
   long-opening capacity; do not presume that an imported excess requires
   liquidation. Preserve a known price-drift cause across restart; for an
   unknown cause, pause new longs and report it under the import policy. If leverage
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

Owner-confirmed: **price-only drift above the maximum does not trigger active
exposure reduction**. Block new long openings and cancel/reconcile outstanding
long-opening capacity, accounting for late fills. Do not add a rebalance deadline
or force a sale merely to return inside the band. Ordinary pair exits, reserved
short catch-up and required rolls may still proceed under their own conditions.
An eventual return inside the band is not guaranteed or required on a timer.

Proposed controls remain conservative futures leverage, separate cash/eligible
margin reserve, shared order reservations and spot/basis/liquidity stresses.
Cash/margin emergencies and expiry deadlines remain distinct risk actions.
Replacement longs or short buybacks required for these actions are not new
discretionary long openings: prefer sequences/chunks that do not worsen the
excess, and explicitly report any unavoidable temporary excursion. A max band
is an order-admission rule with a price-drift exception, not a promise that the
marked fraction can never cross it. Keep fill errors, funding and imported
uncertainty separately classified rather than treating every crossing as drift.

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
abs(expiry_A - expiry_B) <= max_separation_ratio * (max(expiry_A, expiry_B) - t)
```

Current research recommendation: `max_separation_ratio=0.30`; compare 0.25 and
one-third separately. At 30%, the saved catalog admits at least one pair on
193/282 daily samples in 2026 through October 9, versus 1/282 at 25%. The rates
are about 67% in both 2024 and 2025; one-third passes every daily sample in
those three year slices. These are 00:00 UTC metadata-eligibility counts, not
fill opportunities or exact fractions of intraday trading time. See the
[threshold comparison](BTC_MATURITY_SEPARATION_HISTORY.md#threshold-comparison).

Use remaining duration, not the contract's original tenor or a date number.
Approximate examples: 3/6 months fails (50%); 9/12 months passes (25%);
3/4 months passes (25%). Eligibility can disappear as time passes even with
unchanged contracts. Inspect historical listing/expiry and contemporaneous
trade coverage before choosing a replay window; an empty eligible set is valid.
No inference of newly downloaded data coverage from an old manifest.

New opening quantities require current eligibility, current usable market
observations and risk capacity. When a held future approaches the three-month
boundary, initiate the roll described below and cancel unused opening capacity.
Once marked RETIRING, a pair accepts no new discretionary opening quantity even
if a partial retirement lowers its ladder. Resolve pending/late fills explicitly.
Complete removal of the approaching-expiry instrument before
`expiry - 60 * 86400 seconds`; this replaces any implication that every roll
must finish at the three-month instant. Imported positions already beyond the
target enter urgent recovery. It is a strategy deadline, not exchange expiry.
Exits stay allowed. Losing the configured ratio alone stops new openings; whether it
also triggers an early roll is a remaining policy choice. Perpetuals are outside
this dated-futures rule. The proxy is exempt from maturity/separation tests;
its real futures partner still observes the three-month rule.

### Pair-aware rolling

Owner rule: replace an expiring long with a lowest-APR eligible long, and an
expiring short with a highest-APR eligible short, retaining the counterpart's
identity and the configured separation condition where possible. Pair/tranche lineage
is therefore required state, including through restarts and partial rolls.

Proposed refinements:

- Start planning before the three-month threshold, with configurable lead time;
  stop new openings on retirement. Owner completion target: strictly before 60
  days remaining, giving roughly a month between starting retirement and the
  target. A proposed operational buffer is to aim for completion by 65 days
  remaining; 65 is an example, not a newly imposed deadline. Report failure
  rather than fabricating a fill. Forbid re-opening a contract being retired.
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
- Keep immutable parent/tranche lineage, but allocate resulting holdings to the
  destination oriented pair (or create it). Record old/new execution prices,
  realized P&L, fees, surviving-leg entry anchors and replacement executed APRs.
  Derive current PRD from the resulting open legs; no path credit. Update the
  old and destination records as in
  section 6. The old pair remains retired; its decreasing ladder is bookkeeping,
  not permission to reopen. Destination occupancy is handled in section 7.
- Replacing with the same contract as the staying opposite leg would net the
  position: classify this as closing the pair, not as a new zero-gap pair.
- If no replacement preserves the ratio: consider rolling both legs to an
  eligible pair; otherwise close the pair using the escalating exit rule below,
  or retain the counterpart temporarily
  only under an explicit unmatched-exposure policy. Any relaxed-ratio fallback
  must be separately enabled with a ceiling and deadline. Do not silently turn
  'if possible' into unrestricted maturity mismatches.
- If both legs need rolling, optimize their replacements jointly. The
  individually lowest long APR and highest short APR may not form an eligible
  pair. Existing counterpart closings and roll reservations must not compete
  for the same inventory.

Why considering two replacements can help: an expiring leg near three months
may be paired with a staying four-month leg. If the only replacements have six
and seven months left, replacing just the expiring leg fails: 4/6 gives 33.3%
and 4/7 gives 42.9%. Replacing both with 6/7 gives 14.3%, which passes. The
improvement is in the set of geometrically eligible pairs, not in the liquidity
or fill probability of either individual order. Four transactions can cost
more and introduce more partial-fill risk. Joint planning still executes via
the same delayed, volume-limited independent orders. Prefer a feasible single
roll unless the joint alternative has a documented advantage.

### No-roll exit escalation

Owner-confirmed: when a pair must be retired and no permissible roll is found,
begin closing at the ordinary low PRD L and progressively **increase** the
allowed closing PRD. With the original orientation `D = APR(short)-APR(long)`,
the close condition is `D <= L_exit`; raising L_exit makes it less restrictive.
A proposed deterministic schedule is:

```
L_exit(t) = min(L_exit_cap, L + exit_increment_pp * floor((t - t_start) / exit_interval))
```

"Starting escalation" means starting the clock for progressively relaxing the
closing target, not opening more positions or increasing leverage. Set t_start
when retirement/no-roll exit begins: start at L, then raise it at the declared
intervals. Persist this clock through pauses/restarts; it must not reset on
every unsuccessful replacement search. Retirement begins around the three-month
boundary and must target completion strictly before 60 days remaining. For
example, begin at L around three months and reach a more permissive ceiling by
65 days remaining, leaving five days of operational buffer. The schedule's
increments and cap require calibration; no example schedule is yet selected.
The exit ceiling may exceed
ordinary H; forced-exit losses are permitted and separately reported. Never
raise the ordinary entry threshold just because exit urgency increased.

Apply relaxation to unfinished exit quantities, including catch-up after a
first closing-leg fill. Preserve its actual execution APR; change only the
authorized target and resulting counterleg limit. Cancel/replace obeys both
latencies, with old orders and reservations live until reconciliation. Continue
to seek feasible rolls only for inventory not committed to conflicting exits.
At the deadline, declare a bounded aggressive-exit scenario or an unresolved
position. Trade-only strict-through data cannot guarantee an exit, even with
a very permissive limit; never fabricate execution or classify expiration as
a successful timely roll. Strict-through fills cannot guarantee meeting the
60-day target even with a permissive limit. Persist/report remaining quantity
and a deadline miss; an aggressive-exit assumption must be declared separately.

## 5. Orders, reservations and execution

### Shared capacity

All pairs share one account risk allocator. Listing all candidates does not
authorize a full-size order on every candidate using the same capacity.
Reserve capacity for live orders, submitted/unacknowledged orders, replacement
overlap, possible late fills and the unfinished paired leg. For each feasible
fill combination, enforce exposure admission, gross leverage, cash and margin
constraints after costs, with the startup and price-drift exceptions above.
Do not assume both legs fill together. Existing outside-band positions are
preserved; the allocator must still admit authorized recovery/exit sequences.

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

Owner rule: quantity is determined by available exposure-band capacity. At
fixed marks in the simple linear approximation, before fees and lot rounding:

```
additional_long_BTC  <= max(0, x_max * NAV / spot - current_delta_BTC - reserved_long_BTC)
additional_short_BTC <= max(0, current_delta_BTC - x_min * NAV / spot - reserved_short_BTC)
```

These are directional order-admission bounds, not a full native margin model.
Further constrain quantities by gross leverage (including the eventual other
leg), cash/margin and available owned quantity for exits. Reserve combined
capacity across all live/in-flight orders: if the account can acquire 0.30 BTC,
ten candidates cannot each independently reserve 0.30 BTC. Nominal paired
neutrality does not remove the need to reserve all possible asynchronous fills.

"Child order" means one submitted piece of that total quantity. Splitting can
be needed for different PRD ladder levels, native lot sizes or routing; it is
not an additional strategy exposure cap. No independent 0.02-BTC child limit,
0.02-BTC unmatched cap, 0.6-BTC total cap or arbitrary per-pair cap is selected
for this strategy. Partial tape fills already limit immediate execution by
observed volume. Optional execution slicing may be studied later without
changing the total allowed quantity.

Allocation among competing pairs still needs a deterministic rule. Proposed:
funding/expiry actions, exits and catch-up before new openings, then round-robin
allocation among candidates in the posting band with stable tie-breaking.
Do not reserve all capital indefinitely for an unsubmitted distant candidate;
reserve when submitting, including both leg scenarios. Log candidates that
could not be quoted. No capacity is freed until cancellations are reconciled.

### Submit only limits close enough to market

Owner requirement: retain candidate calculations locally but post only limits
within a broad configurable distance of a valid current market reference.
For positive best bid/ask, a proposed measure of passive distance is:

```
buy_distance  = max(0, (best_ask - buy_limit) / best_ask)
sell_distance = max(0, (sell_limit - best_bid) / best_bid)
submit when distance <= posting_band
```

Marketable limits have zero passive distance; do not accidentally exclude them
by taking an absolute distance. The PRD-derived limit is unchanged by this
filter; it determines when the order is submitted, not a replacement price.
Use a broad band and optionally a wider removal band than submission band to
avoid repeated cancel/repost near one boundary. Apply account capacity,
retirement and self-cross checks before sending. Treat pending catch-up and
urgent exits explicitly; never label a distant unsubmitted order as resting.

Live operation can use bid/ask updates. A trade-only replay has no historical
bid/ask guarantee: any last-trade proximity reference must be labeled as an
approximation and use only observed information. Admission becomes effective
only after decision/order latency. A jump can cross a candidate limit before
submission arrives, so no finite band guarantees that no opportunity is missed.
Calibrate a broad band against an otherwise identical always-posted reference,
comparing missed fills, P&L, resting orders and message volume. Never backfill a
missed trade or waive latency because the target was already calculated locally.

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
Quote age means the age of market information used to calculate a price, not
the lifetime of a resting order. An old trade in an illiquid future does not
by itself prove a disconnected feed or justify cancelling its orders. Frozen
executed APR anchors do not expire. A numerical maximum-observation-age filter
is optional and is not selected as an additional trading restriction here.
Always reject missing/invalid/future information; record input ages and distinguish
a healthy feed with infrequent trades from a feed outage or stale index.
Current index/time still matters when calculating a counterleg's dollar limit.
On a known feed outage, stop new discretionary submissions and follow the
declared outstanding-order recovery policy, respecting cancellation latency.
There is no generic rule to cancel a valid resting order merely because it is
old. A separate good-till-time or stale-price cancellation policy would need
to be selected explicitly. Timeout, allowed slippage, market fallback and target relaxation remain
separate parameters; ordinary catch-up relaxation is off unless expressly
selected. The owner-authorized no-roll exit escalation is a separate exception.

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
must not manufacture extra closeable inventory or freed leverage. Owner
clarification permits a roll or a nominal new opening to close an opposite
existing leg. Replace the earlier proposed blanket prohibition on such
allocations with explicit netting and reassignment. Do not record both a new
gross long and an old gross short when the actual position has netted them.
The same execution may affect an old pair and a resulting pair, but its native
quantity, fee and cash flow occur only once. A third pair may also be affected
when the destination already owns inventory: update every touched record.

### Updated executed PRD from the current pair's fills

Owner clarification, 2026-10-13: use the **actual executed APR difference of the
currently owned legs** as the pair's current PRD and derive its ladder from its
remaining fills. There is no separate transferred credit and no cumulative
initial-plus-roll PRD for ladder decisions. The previously proposed
`effective_path_PRD` / `closed_leg_APR_credit` policy is superseded.

For each matched lot:

```
current_executed_PRD = short_leg_executed_APR - long_leg_executed_APR
Long A -> X replacement: new PRD = retained_B_short_APR - executed_X_long_APR
Short B -> Y replacement: new PRD = executed_Y_short_APR - retained_A_long_APR
```

An unchanged leg retains its actual original executed APR, even when the roll
occurs later. A newly filled leg gets its own execution-time APR. This is not
today's market PRD. Closing executions, realized native P&L and fees remain in
the immutable history; completed legs do not raise the new pair's opening rung.

Example: buy A at 3%, sell B at 5%; then buy back B at 4% and sell Y at 6%.
The new A/Y pair has current executed PRD **6% - 3% = 3%**. The B exit belongs
in realized P&L and trade history. Adding initial 2% and transfer 2% to make 4%
would mix a completed leg into the current pair's ladder and is not used.

A pair can contain differently executed lots. Retain each lot's native quantity,
frozen reference BTC weight and both executed APRs; display the remaining-weight
average PRD, but qualify ladder quantity from individual lots. A profitable lot
must not make a below-threshold lot qualify through averaging. If anchors are
missing on import, PRD is unknown; do not invent a zero anchor or past execution.
The arbitrary-position import policy remains required before application use.

Nominal openings that net old inventory follow the same rule. With A-long/B-short,
buying B and selling Y closes the old B short and leaves A-long/Y-short. It does
not create a fictitious B/Y position for the netted amount. Excess beyond the
old B short can create a real B/Y pair with its own executed anchors. Update all
affected pairs, including any existing destination inventory, once.

Deterministic allocation procedure (FIFO lot selection is the research policy):

1. Reserve affected lots under a persistent transfer ID. Preserve immutable
   execution IDs and original order targets; do not duplicate cash or fees.
2. Apply fills to actual native positions/cash once. Exchange inventory changes
   on execution; strategy knowledge still arrives after the observation delay.
3. Separate completed replacements from pending fragments. Never fabricate an
   executed replacement APR before its fill. Pending fragments keep real risk
   capacity and execution reservations.
4. Move the surviving leg's ownership to the resulting pair and attach the
   replacement fill. Recompute that pair's current lot PRDs and derived ladder,
   including its preexisting lots. Recompute the old pair from its remaining lots.
5. A pair with no remaining matched lots has null current PRD, not zero. Keep its
   history and show any unmatched residual explicitly. The old retiring pair
   remains closed to new openings even when its derived ladder falls.
6. Persist all affected allocation versions and journal entries atomically.
   Reconcile delayed cancellations and fills without assigning one surviving
   quantity to two pairs or reviving a completed order on restart.

A small research reference and deterministic tests now exercise current-leg
PRD, partial lot removal, replacement and ladder rebuilding:
[research/btc_prd_pair_lots.py](research/btc_prd_pair_lots.py). This is not yet a
native account ledger or durable multi-pair execution implementation.

## 7. Optional per-pair opening ladder

Owner-confirmed: opening inventory raises levels; closing it restores lower
levels; each oriented pair owns its ladder and remaining fill records. The
ladder is derived from those records, not lifetime turnover, accumulated roll
profits or a separately transferable credit balance. Account/strategy/long
symbol/short symbol define a pair; transfer lineage is stored separately.

Use `H_k(t) = H_0(t) + k * increment_pp`, with a configured reference BTC amount per
rung. Frozen entry reference quantities avoid rung changes merely from BTC
price movements. Risk accounting still uses current native positions and marks.
A replacement lot is treated by exactly the same executed-PRD rule as another
lot in the resulting pair. An empty destination has no inherited old-pair rung.

The first **research convention**, made explicit for reproducibility, is:

- Rebuild contiguous occupied rungs from remaining completed lots in ascending
  current executed PRD order, breaking ties by stable lot ID. Split quantities
  at rung boundaries. A fragment qualifies only if its actual current PRD is
  at least that rung's threshold (including equality at an intended limit).
- Preserve low/unknown-PRD quantity as owned risk inventory even when it cannot
  qualify a rung. Do not erase it or lend it a completed leg's APR. It is visible
  as unqualified quantity in the research reference.
- Use each lot, not the pair-wide average, to populate rungs. Derived counted
  quantity determines the next opening threshold. Closing a lower lot allows
  remaining qualifying lots to move down and restores lower opening levels.
- Reserve unfinished orders and unmatched quantities separately. They cannot
  be reused for new orders just because a completed matched PRD is not yet
  available. A first closing-leg fill does not release the entire allocation.
- Keep catch-up targets for already committed lots; rebuilding a new-opening
  ladder never reprices old executions or silently changes those targets.

Example: H_0=2%, increment=0.5 percentage point, amount=0.10 BTC. Owned lots
0.10 BTC at actual PRD 2.1% and 0.10 BTC at 3.1% fill the 2% and 2.5% rungs;
new openings start at 3%. Closing the first lot leaves 0.10 BTC, fills the 2%
rung and restores the next threshold to 2.5%. A transferred lot at 3% cannot
qualify a 3.5% rung by adding the profit from a now-closed leg.

This research convention resolves the reconstruction algorithm for tests;
exact pending-order reservations and import seeding still belong to the funded
replay. The first empirical execution calibration disables ladder increments
so level/location effects can be measured before capacity/ladder interaction.
For adaptive H_0, the proposed versioned transition rebuilds qualification against
the new thresholds while retaining every remaining lot and risk reservation.
Unqualified inventory does not disappear or free account capacity. Exact update
cadence and held-exit semantics are in the adaptive research design and have not
been selected as production defaults.

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

### Research accounting clarification (2026-10-14)

The synthetic index starts gross of proxy expenses. The current unit experiments
use `a_proxy` only in quote construction and reduce BTC-equivalent exposure once
as `q(t)=q(0)*(1-e)^years`. They do not also debit the APR from cash. These are
BTC-equivalent units represented by the holding, not an assertion that the
number of actual ETF shares changes. A net-of-expense proxy price series would
replace this explicit expense decay, not supplement it.

The experimental `proxy_cost` sensitivity additionally multiplies those units by
`exp(-c*years)` as a deliberately simplified liquidity-cost model. This is not
observed margin turnover or a second expense-ratio charge. The funded strategy
must replace that approximation with actual sale/rebuy/conversion/cash flows
where modeled, and never charge both for the same economic cost.

Reporting now requires three mutually reconciling buckets: completed-cycle
realized net P&L; realized P&L and paid fees/rebates in the still-unfinished
cycle; and unrealized marks of remaining holdings. Show proxy price change,
expense effect, liquidity surcharge, native futures P&L and transaction fees
separately. An unfinished cycle is not automatically wholly unrealized.

Negative futures maker fees are conditional sensitivities with separately
configured proxy costs. `always_posted` disables the near-market admission
filter only; it does not bypass inventory, lifecycle, entry expiry or latency.
The 1 ms comparison means 1 ms observation-to-decision plus 1 ms
 decision-to-market. No monotonic gain in completed cycles is assumed.

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
   pairs have zero eligible seconds under the 25% rule. The wider completed
   540-contract catalog has only five archive-supported 25% windows totaling
   about 618 hours; see the maturity history for daily values and limitations.
2. Freeze a declared proof-of-concept configuration (cash capital, net band,
   futures leverage, margin model, bootstrap, per-pair ladder amount, proxy expense
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
  repriced. A retiring pair does not reopen when its ladder falls; a roll transfers
  actual surviving lots to the destination pair, with its derived ladder and
  updated current-leg executed PRD, without double-counting either allocation.
- Native inverse versus linear accounting, collateral exposure, lot/dust
  handling and closed-round-trip P&L; reject unsupported combinations.
- Proxy disabled/enabled, e=0, expense/surcharge units, synthetic 24/7 pricing,
  offset-recognized/unrecognized margin scenarios, first post-arrival index
  observation, expiry-filter exception and no forecast-cost double charging.
- Cash-only ACQUIRING state; arbitrary long/short/proxy imports inside/outside
  bands, missing historical pair metadata, unknown pending orders and late fills.
- Pair-aware one-/two-leg rolls with partial fills, unavailable ratio-preserving
  replacements, increasing exit ceilings, delayed cancel/replacement, persisted
  escalation clocks and a target strictly before 60 days remaining. Record misses.
- Long/short/two-leg replacement uses current executed anchors; partial lot
  removals update the old weighted PRD; an empty pair has null current PRD;
  no completed-leg APR credit enters the new ladder or cash accounting.
- A nominal new opening nets an old opposite leg, updates all affected pairs,
  and creates actual new inventory only for excess quantity. Restart cannot
  duplicate transferred surviving legs, costs or occupancy.
- Headroom-derived order amounts, multiple candidates competing for one reserve,
  rung splits without an arbitrary child cap, and native rounding.
- Broad proximity posting versus always-posted comparison, marketable limits,
  jumps during submission delay, no retrospective fills, and separate healthy
  sparse trades versus feed outage; resting-order age alone does not cancel it.
- Lowest-APR acquisition from cash/below minimum without short openings, partial
  acquisition, missing liquidity, fees/lot overshoot and baseline-ladder attribution.
- Price-only above-maximum drift never creates a compulsory rebalance; cancel
  new long openings while permitting authorized expiry/funding/exit sequences.
- H/L location versus gap sensitivity, chronological held-out calibration,
  unequal-maturity P&L identity and inclusion of unfinished/forced-exit losses.
- Continuous versus resumed runs have identical positions, orders, reservations,
  ladder counters, fees, P&L and audit sequence; immutable input/version hashes.

Required outputs: net exposure versus band; holding and long/short futures
exposures; gross leverage and reserved headroom; actual and reserved margin;
open matched/unmatched quantities in BTC and USD; cumulative matched and gross
turnover separately; realized/unrealized P&L and NAV in USD/BTC; fees/funding;
per-pair target ladder and execution PRDs; opening/closing markers with quantity,
both APRs, original targets/current executed PRD and timestamps. Include breach/recovery
and rejection reasons, nonfills/timeouts, and matched-only weighted bought/sold
PRDs. Benchmark against the same initial BTC/cash portfolio as well as any
separately labeled 100% BTC comparison. The exposure band changes that benchmark.

## 10. Decision register after owner clarification

| ID | Topic | Confirmed scope and remaining choice |
| --- | --- | --- |
| D1 | Exposure | Proxy/direct holdings count alongside signed futures; current-NAV delta definition proposed |
| D2 | Leverage | Exclude paid proxy; use gross futures notional / NAV; choose cap, venue/payoff and separate margin/cash model |
| D3 | Startup/restart | Cash-only first POC; acquire lowest-APR longs below minimum and suppress short openings; arbitrary allowed-product holdings/orders before integration; baseline outside ladder proposed |
| D4 | Pair direction/maturity | APR determines sides; no near/far restriction; retire around three months and target exit before 60 days remaining; no new openings in retiring pairs; calendar-month interpretation and ratio-only early rolls remain proposed |
| D5 | Asynchrony | Shorts may lag within exposure capacity; long-first at floor and safe either-leg-first inside band proposed |
| D6 | Ladder | Per-pair confirmed; open positions raise levels, closes restore them; derive occupancy from current-leg executed APR differences in remaining per-pair lots; no separate transfer credit; contiguous-rung reconstruction is the declared research policy |
| D7 | Latency/sizing | Two equal configurable delays; quantity derives from exposure headroom, leverage/funding and reservations; no arbitrary child cap or selected numerical age filter; broad near-market posting required |
| D8 | Catch-up PRD | Executed-leg APR anchor proposed; common-time diagnostic separate; no silent relaxation |
| D9 | Rolling/recovery | Lowest-APR long / highest-APR short preserving counterpart ratio where possible; target before 60 days; no-roll exits raise closing PRD over time from L; slope/step, cap, buffer and final missed-deadline action remain to choose |
| D10 | Proxy | e/(1-e), any eligible partner, synthetic 24/7 near-spot execution, optional annual margin-liquidity surcharge confirmed; numerical costs/offset model to choose |
| D11 | Research sequence | Direct raw-data analysis before integration; raw preflight, full-catalog maturity history and first chronological unit execution calibration completed; capital-constrained strategy replay pending |
| D12 | Price drift | No active reduction solely for price-driven excess above maximum; stop new longs; expiry/funding actions remain separate |
| D13 | Calibration | 2%/1% are examples; infer both location and gap from recent observations and update live; select a causal adaptive rule using actual net P&L, delays, costs and incomplete trades; held-target transitions remain proposed |
| D14 | Updated PRD/netting | Each affected pair updates when rolls or new openings close a leg; immutable fills plus actual current-leg executed PRD confirmed; no completed-leg credit or phantom opposite positions |

"Ownership, accounting and execution rules" means concrete mechanics:

- Ownership: which actual position quantities belong to each logical pair and
  which surviving quantity moves when a leg is closed or replaced.
- Accounting: update actual quantities, costs, cash, native P&L, current executed PRD
  and ladder occupancy once, preserving their historical provenance.
- Execution: decide admissible amount and PRD limit, whether it is close enough
  to submit, when it becomes live after latency, and how partial/late fills and
  cancellations change reservations. It is not an extra selection strategy.

### Material policies still to settle

These are not extra agreed requirements. Some have been mentioned in discussion
without their precise implementation semantics; others were introduced as
engineering proposals and need to be visible before coding.

| Policy | Current proposal | Why it changes behavior |
| --- | --- | --- |
| Maturity ceiling and drift | 30% first research setting; apply to new/replacement pairs; do not force an exit merely because a held pair later crosses it | At 30%, roughly a third of recent daily samples have no eligible dated pair; forcing ratio-driven rolls could cause unnecessary exits |
| Three-month definition | Calendar months in UTC, not a fixed 90 days | Changes entry and retirement boundaries |
| Baseline inventory | Minimum-exposure acquisitions sit outside PRD ladder until explicitly reassigned to a qualifying allocation | Otherwise the first discretionary trade can begin above H_0 even though no high-PRD entry occurred |
| Ladder reconstruction | Current-leg executed PRD confirmed; research fills contiguous rungs from individual remaining lots, with low/unknown-PRD inventory separately visible | Pending reservations and missing-history seeding must preserve risk capacity; no cumulative credit from closed legs |
| Partial fills and capacity competition | Long-first at floor; stage exits using available headroom; reserve account capacity once; prioritize expiry/funding, exits and catch-up, then deterministic opening allocation | Not all pairs can rest full orders against the same capital; first-leg direction matters at either band edge |
| Shared actual contracts | Net opposing actual quantities and transfer affected pair allocations; FIFO proposed | User permits openings that close existing legs; choice of old lot changes remaining PRDs, cost attribution and ladder state |
| Price anchor and feed health | Retain executed APR; refresh causal index/time; numerical age cutoff optional and unselected; record sparse trade age separately from outage | An old resting order or old print is not automatically invalid; bad/missing data must not create assumed current prices |
| Posting proximity | Broad passive price-distance band, with optional wider removal band | Bounds live orders but can miss jumps during latency; compare against always-posted reference, not a guarantee of all fills |
| Retirement fallback | Start around three months; target before 60 days; optional 65-day working target; persist exit-relaxation clock | Schedule, cap and final no-fill response remain choices; the 60-day target itself is now settled |
| Funding and proxy | Native inverse payoff/collateral adapter for native claims; explicit cash reserve, fees and proxy liquidity cost/offset assumptions | A gross leverage cap does not specify when collateral must be funded or proxy sold |
| Recovery without pair history | Import actual positions/orders, infer feasible labeled allocations and ladder seed without inventing past profits | Required before application integration; cash-start research may precede this adapter |
| Calibration objective and refit | Live updates of location and gap confirmed; propose recent weighted quantiles plus causal policy selection, versioned ladder rebuilding and cash-aware adaptive held exits; entry-frozen exits as control | Maximizing raw total return, turnover or matched-only P&L can select different rules; target changes affect held inventory and working orders |

Numerical configuration can remain adjustable rather than requiring one
permanent answer: capital, band, leverage, rung size/increment, optional slicing,
delay, optional maximum observation age, posting proximity, participation, fees, reserve, proxy surcharge,
roll lead time and exit escalation schedule. Predeclare values for each test.
By contrast, ledger semantics, ladder ownership, netting and event ordering must
be deterministic and documented before interpreting that test's performance.

Numeric inputs still needed include capital, actual x_min/x_max, maximum
leverage, H/L, optional ladder amount/increment, delays, posting band and
risk-recovery settings. Quantities derive from headroom; numerical age gates
and execution slicing are optional. Example values in the request remain examples. Use
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
- [Deribit buy-order API](https://docs.deribit.com/api-reference/trading/private-buy)
  (checked 2026-10-13): order price, quantity, time-in-force, reduce-only and
  tracking labels are separate fields. Market-data age, order lifetime and
  our internal pair-ownership allocation must likewise remain distinct concepts.
- [Deribit portfolio margin](https://support.deribit.com/hc/en-us/articles/25944756247837-Portfolio-Margin)
  and [cross-collateral specifications](https://support.deribit.com/hc/en-us/articles/25944777203869-Cross-collateral-specifications)
  (checked 2026-10-13): margin depends on the account model, recognized equity,
  stress scenarios and collateral eligibility. These sources do not establish
  margin recognition for an external BTC proxy or historical replay settings.
