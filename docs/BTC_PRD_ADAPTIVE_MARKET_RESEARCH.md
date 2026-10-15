# BTC PRD: execution horizons and calibration choices

## Current direction — 15 October 2026

The owner has put the competing-agent exchange simulation aside and asks to
evaluate PRD jointly with execution time, ordinary exits relative to executed
PRD, and initial calibration followed by inventory-driven ladders. The recommended
first experiment is now startup calibration with fixed base levels, rather than
the periodic refit proposed on 14 October. This records a recommendation under
discussion, not approval of numerical settings or a newly implemented strategy.
The older live-refit proposal and simulation feasibility analysis are retained
below as historical alternatives; they are not the current implementation queue.

### PRD, quantity and time to execution

APR/PRD is defined from prices, index and time remaining to expiry. The PRD
that can be achieved with a chosen probability depends on how long execution
is allowed, order size, starting state and execution policy. Estimate:

```
F_open(h, t, q | X) = P(T_matched_open(h, q) <= t | starting state X)
```

Here h is target PRD, q the required matched quantity in a declared unit, and
X includes the pair, remaining tenors, observed market conditions, exposure,
pending orders and latency. Run the actual strict-through/aggressor/volume
policy, not merely a historical PRD crossing. Keep the same initial state,
start times and data across candidate targets for comparisons. Start the clock
at the decision and include both configured delays; record physical completion
and notification time separately. Full matching must reach q on both legs;
report partial matched quantity and unmatched risk too.

Estimate separately time to first fill, first-fill-to-match duration, full
matched opening, and subsequent closing/roll time conditional on the executed
entry. Waiting before any fill and waiting with an exposed leg have different
risks. Retain no-fill probability: unfinished samples at the data boundary are
censored, not dropped or given an invented eventual fill. A policy cancellation
or retirement exit is an explicit outcome, not automatically independent censoring.
Use common start samples, report uncertainty and thinly sampled regions, and
do not treat overlapping windows as independent trials. Larger horizons give
nondecreasing completion probability for the same continuing policy; changing
target/catch-up paths need not yield a monotone cross-target comparison.

For a declared probability p, the surface can identify the highest admissible
opening PRD with adequate probability of matching q within t. Choose the actual
levels/gaps using native net P&L, close-time distribution and capital usage as
well, since fill probability alone rewards unprofitable trades. No numerical
completion probability or execution deadline has been selected.

### Exposure-dependent patience

The owner's direction is sensible for **new exposure-increasing longs**. One
candidate schedule is `t_new(x)=t_fast+(t_slow-t_fast)*u^gamma`, where
`u=clip((x-x_min)/(x_max-x_min),0,1)` and gamma>0. Near the upper band, less
urgency permits seeking a better entry; at/above the maximum do not admit a new
long. Actual quantity still comes from exposure headroom, leverage, funding and
reservations, so q must vary explicitly with the state rather than holding an
infeasible size constant.

The important exceptions are:

- Below the minimum, acquire an eligible minimum-APR long using the baseline
  policy, with short openings suppressed. Do not wait for a profitable pair to
  restore the required long exposure. A short time budget is not a fill guarantee;
  any fallback to more aggressive execution must be a separately declared rule.
- A short completing an already-filled long **reduces** net long exposure.
  Near the maximum that completion can warrant greater urgency, not a longer
  unmatched wait. Retain its committed PRD unless an explicit recovery policy
  changes it; exposure urgency alone does not authorize silent target relaxation.
- Stage closing/rolling orders according to the direction of their intermediate
  exposure change, not the label 'opening' or 'closing'. Pair occupancy and net
  exposure are distinct: a matched pair may occupy a rung with little net delta.

For the fixed-start experiment, use the initial PRD-time-quantity surfaces to
calibrate the whole rung schedule and a declared state-dependent waiting policy.
Runtime patience/admission can vary without continually recentering the ladder.
A deadline does not by itself lower a committed threshold. If reaching a short
deadline requires changing H, that is an explicit alternative policy to test.

### Ordinary closing targets and profitability

For the convergence strategy, a lot-relative target can be
`L_lot = D_executed_lot - gap_lot`, with gap_lot>0, rather than comparing a close
with today's opening threshold. Use actual current-leg executed APRs, preserving
anchors and updating affected pairs on rolls/netting as already specified.
This lot-relative rule and the size of its gap remain proposals; a fixed common
L below all qualifying entries is another consistent comparison.

Lower closing PRD is **not sufficient** for a positive cash P&L and is not
mathematically necessary for every profitable trade. For equal-BTC linear legs,
before fees, `PnL/q = (F_B_entry-F_A_entry)-(F_B_exit-F_A_exit)`, whereas
`F_B-F_A = S*(APR_B*tau_B-APR_A*tau_A)`. The two APRs and tenors matter separately.
The unequal-tenor counterexample in the main plan narrows PRD from 2% to 1%
yet loses $150 per BTC at unchanged spot, before costs. Conversely, constant
spot with a zero-cost proxy and a linear future premium of 3% over 0.5 years
has a 1.5% price premium; later 4% over 0.25 years is only a 1% price premium.
That short-future/proxy cycle gains 0.5% before costs despite wider annual PRD.
These are algebraic examples, not empirical results or native-inverse formulas.

An inverse-contract counterexample also holds. Keep spot at $100,000 and take
$100,000 USD face long A and short B. Initially A has 0.75 years remaining at
3% APR (price $102,250), and B has 1 year at 5% (price $105,000). After 0.10 year,
A has 0.65 years at 10% ($106,500), and B 0.90 years at 11% ($109,900).
PRD narrows from 2% to 1%, but BTC P&L before costs is
`100000*(1/102250-1/106500+1/109900-1/105000) = -0.0034348711 BTC`, or about
-$343.49 at the unchanged spot. This is a calculated illustration with
simultaneous fills and equal USD face amounts, not a backtest.

Ordinary profit-seeking exits should therefore also evaluate native lot cash
flows after fees, expense decay and other costs, in the chosen reporting currency.
Deribit inverse futures settle profit/loss in BTC, with USD face amounts; use
the inverse payoff rather than substituting the linear example [6]. Pending
second-leg execution makes prospective net proceeds conditional until both fills
occur. Profit-only exits cannot override mandatory expiry/funding recovery;
record any resulting loss explicitly and preserve the before-60-day objective.

### What a fixed-start ladder does and does not adapt to

For the first experiment, initialize pair H0, rung thresholds/amounts and closing
rules from preceding data. Keep the base fixed and let remaining qualified fills
raise the next opening level; closes restore lower levels. Dollar limit prices
still update with the causal index and remaining maturity. Preserve executed
anchors, and do not replace actual execution PRDs with statistical estimates.

This accompanies **inventory accumulation and release**. It does not estimate a
new market center: a persistent upward shift can leave lower closing targets
unreached and inventory full, while a downward shift can leave entries inactive.
The ladder must still obey capital limits when market opportunities exceed its
capacity. Monitor PRD-time behavior and saturation/idleness without automatic
refitting in this baseline; do not assume a ladder eliminates regime risk.

Calibrate newly eligible pairs and new roll destinations with data available
when they appear. Restore persisted calibration on restart; neither a process
restart nor an ordinary completed cycle should silently initialize a new base.
When moving existing lots to a newly calibrated destination, derive occupancy
from their actual current-leg PRDs and retain all risk quantities. Reinitializing
an existing pair, the no-fill response to a waiting deadline, and choosing a
lot-relative versus common closing L remain policies to settle before testing.

Next empirical output: PRD/time/quantity completion surfaces, first-leg and
catch-up durations, closure distributions and net P&L, followed by a continuous
cash-start replay of the initial ladder. No new backtest result is claimed here.

## 1. Earlier live-refit alternative — 14 October 2026

The [full-history study](BTC_PRD_EXTENDED_CALIBRATION.md) fitted grids once and
held them fixed; it did not test periodic live recalibration. The following
alternative is retained for possible later comparison, not the preferred first
experiment after the owner's 15 October reconsideration.

For an oriented pair with long A and short B, define `D = APR_B - APR_A` and
`H0(t) = L(t) + w(t)`, with `w(t) > 0`. Directions follow APR opportunities;
owned pairs retain their original orientation. H0 is the base before that pair's
inventory ladder. Individual outright APR locations depend on the observed
term structure; the strategy should fit pair PRD distributions, not independently
optimize each leg's APR and subtract unrelated optima. Proxy APR remains the
agreed expense/surcharge convention; it is not learned by treating proxy returns
as an additional expense charge.

Use two update speeds:

1. **Market statistics and quotes:** ingest each causally received observation;
   maintain recent PRD location, dispersion, observation ages and uncertainty.
   At scheduled updates, move base H/L with these statistics. Continue updating
   executable limit prices for spot, time to expiry and the latest information
   between calibration updates. Fast order handling does not require fitting a
   new statistical policy on every print.
2. **Policy selection:** less frequently compare a small set of rules using
   earlier execution outcomes and stateful shadow replays. This chooses how
   far above/below the recent location to quote, how wide a gap to require and
   how quickly to adapt. It includes fees, both delays, unpaired inventory,
   unfinished cycles, funding and expiry exits. A distribution alone cannot
   determine a profitable gap.

An initial research configuration could use an exponentially weighted 14-day
half-life, hourly H/L publication, and weekly policy selection on the preceding
90 days. These numbers are starting candidates, not estimates of optimal memory.
Compare a small predeclared set of faster/slower memories and update cadences
in chronological development data; retain the same rule on evaluation periods.
The 2017-2026 archive supplies different regimes for evaluating the rule, not
an equally weighted decade-long average for today's quotes.

### Causal observations and a concrete candidate family

At decision time t, use only messages actually received by t. Exchange timestamps
alone do not determine availability. A mark, trade and index arriving at different
times are separate observations. Record both exchange and receipt timestamps,
missing data, known ages, and the version of every decision input.

For a trailing observation x_i, a recency weight can be
`weight_i = observed_duration_i * 2^(-(t-receipt_i)/half_life)`.
Duration weighting avoids giving a burst of prints disproportionate influence.
Compute durations only through t, never to a later observation not yet received.
Do not let a stale trade carried through a long gap masquerade as hours of
fresh executable prices: distinguish the last-known-state distribution from a
freshness-qualified estimate, report coverage, and predeclare the treatment of
stale intervals. This statistical rule is distinct from canceling an old resting
order; no numerical quote-age cancellation policy has been agreed.

Let Q_p(t) be a weighted quantile and `s(t) = Q_0.75(t) - Q_0.25(t)`.
A small candidate family is:

```
L_q(t)   = Q_q(t),                  q in {0.25, 0.50, 0.75}
w_m(t)   = max(m * s(t), w_floor),  m in {0.5, 1.0, 1.5}
H_q,m(t) = L_q(t) + w_m(t)
```

This is a transparent search family, not an assertion that quantile trading
earns money. It allows location and gap to move independently. `w_floor` is a
positive numerical/configuration bound; economic admission additionally uses
native cash P&L and costs. Fee basis points cannot simply be copied into annual
PRD basis points: tenors, sizes, inverse payoffs and holding time matter. Zero
or negative fees do not establish an edge on their own. If no candidate clears
the economic/risk criteria, there need be no discretionary opening. Baseline
minimum-exposure acquisition and existing-position management remain separate.
Retain the strategy's directional/admission rules when screening candidates;
negative-opening-PRD cases remain labeled research sensitivities, not silently
approved live settings or a reason to relabel owned pairs.

For illustration only, Q50=4% and IQR=1 percentage point with q=.50,m=.5 imply
L=4%, H=4.5%; later Q50=3%, IQR=.6 point imply L=3%, H=3.3%, before any active
floor or ladder. These are not calculated trading recommendations.

Keep proxy/future and future/future populations distinct. Adjust for remaining
tenors and separation; do not concatenate a changing set of expiries as though
it were one stationary pair. Sparse/new pairs can borrow strength from comparable
tenor groups, with uncertainty disclosed, rather than each expiry receiving an
overfit independent model. Training inputs must have existed at that cutoff;
future contract listings cannot leak backward.

### How to select the gap and location jointly

For each rule, measure frequency of completed opening pairs, conditional time
to close, unsuccessful attempts, deadline exposure, and the whole native cash
path. Larger gaps can offer more convergence but fewer entries/exits and longer
inventory duration; smaller gaps may improve turnover while losing to costs,
delay and adverse selection. Quantiles do not identify this trade-off.

The proposed primary objective is incremental marked NAV relative to the same
minimum-exposure baseline without discretionary pair trades, subject to declared
drawdown, margin/liquidity and retirement constraints. Report completed realized,
unfinished realized and unrealized P&L separately, plus unpaired BTC exposure,
fees, margin usage and exit/roll losses. All outstanding positions are included;
do not rank candidates by winners or completed cycles alone. The earlier unit
tests' substantial unpaired-proxy losses make this especially important.

At each historical update, train only on what was known then. An eventual close
beyond the cutoff is unavailable: keep that observation censored and mark the
remaining inventory at the cutoff. Score candidate policies as continuous paths
with their own inventories, orders and pending messages, not cash resets at each
refit. A newly introduced candidate needs a causal warm-up or reconciliation
from the decision-time account state; it cannot assume a convenient historical
portfolio. Shadow replays test hypothetical policies and are not extra claims
on the live account's cash or historical trade volume.

Freeze the **algorithm**, not the numerical H/L path, for evaluation. It may
update from earlier observations during the evaluation period exactly as live
trading would; do not change its rules after inspecting later results. Previously
examined historical periods are development evidence, not a fresh untouched
holdout. Compare neighboring settings across time blocks, delays and costs;
prefer stable performance over one maximum. Serial dependence means hundreds
of prints or overlapping cycles are not hundreds of independent observations.
If evidence is weak, retain a still-valid incumbent policy or suppress new
discretionary risk under a declared rule, rather than forcing an optimum.

## 2. Earlier live-refit transition proposal

| State | Proposed behavior |
|---|---|
| Future openings | Use current H0/L/gap and the pair's remaining-lot ladder; record calibration version. |
| Executed legs | Preserve price, quantity, time, expense treatment and executed APR. A new statistical estimate never rewrites a fill. |
| Ladder | Atomically rebuild from remaining lots against the new base/rung thresholds. Quantity that no longer qualifies remains owned risk inventory; it does not free exposure, margin or pending-order reservations. No transfer credit is introduced. |
| Unmatched committed leg | Retain its committed catch-up rule unless a separate, explicit risk/expiry recovery action changes it; calibration must not silently accept a worse completion. |
| Fully matched existing pair | Research adaptive L as the primary proposal, with a lot-specific native-P&L check for ordinary exits; compare entry-frozen L as a control. Recalibration can change the exit decision, but must expose its economic effect. |
| Retiring pair | Still closed to new openings; follow the explicit roll/no-roll exit schedule and complete retirement before 60 days. A refit must not reset its escalation clock or postpone the deadline. |
| Working orders | Submit cancel/replace with actual latency and priority consequences. Old orders can fill until cancellation is effective; keep reservations and accept late notifications. |

An APR gap to the executed entry is not a cash-profit guarantee, particularly
for unequal maturities. The proposed ordinary-exit check evaluates the lot's
native proceeds, remaining leg execution assumptions, fees and costs. It is an
estimate until both legs execute, not guaranteed proceeds. A minimum-profit or
maximum-loss budget, and whether to preserve or revise it, remain research
choices. Expiry/funding recovery can explicitly override an ordinary profit
target; its losses must be reported rather than hidden by changing L.

Update the ladder base at the calibration cadence; initially keep optional rung
amount/increment separately configured to isolate effects. Compare adaptive rung
increments later. Record effective time, training cutoff, input hashes, Q values,
candidate scores, old/new H/L, ladder reconstruction and any override reason.
Use a declared material-change rule to avoid unnecessary cancel/replace churn.
Persist estimator, selected policy and inventory versions across restart.

Acceptance must cover no look-ahead at refits, censored cycles, late fills during
an update, sparse feeds, regime shifts, unknown imported lots, threshold changes
without new fills, retirement during refit, and deterministic restart. The funded
multi-pair ledger is still needed before claiming strategy-level calibration.

## 3. Deferred: market populated by competing PRD agents

Set aside by the owner on 15 October 2026. This retained analysis does not
authorize simulator work, collection jobs or background experiments.

This is technically feasible as a discrete-event market simulation. It can
measure competition for fills, speed advantage, adverse selection, crowding,
capacity and feedback from adaptive thresholds. It cannot identify the true
market's counterfactual behavior from trade prints alone.

| Experiment | What it can establish | Principal limitation |
|---|---|---|
| Adaptive historical replay | Whether a causal adaptive policy improves our existing strict-through execution results | Prices and background flow do not react to us; queue positions are unknown. |
| Shared-volume competitive replay | How agents divide a finite historical execution budget under declared priority assumptions | Competition changes allocation but not the historical market; this is a limited counterfactual. |
| Interacting futures books with historical spot reference | Endogenous futures prices, queue races, crowding, inventory and cancellations | Spot remains exogenous; background agents and liquidity need calibration. |
| Joint spot/futures/other-venue model | Cross-market impact, price discovery and funding feedback | More unidentified behavior; requires substantially more data and validation. |

Start with three dated-futures books plus the proxy/spot reference, arranged to
include eligible pairs and a replacement expiry. Futures/futures separation
sensitivities and unrestricted eligible proxy partners remain as specified.
Use short windows for queue races and longer windows containing expiry/rolls
for lifecycle behavior. The existing local Dec/Mar sample does not satisfy the
30% dated-pair condition; it can benchmark workload and proxy experiments but
must not be relabeled as an eligible dated-pair execution sample.

### Required market mechanics

- One shared matching engine per instrument, finite orders, partial fills,
  venue-appropriate priority, native ticks/lots, cancellation/amendment rules,
  post-only behavior and applicable maker/taker fees. Every executed unit has
  a unique buyer and seller. A generic price-time baseline is a declared model
  assumption until instrument-specific venue rules are verified.
- Private observed state for each agent, with market-data/fill delay, computation
  delay and order/cancel delivery delay. The current equal d/d convention is a
  controlled special case. Separate delays permit jitter, feed batching, shared
  congestion and exchange processing queues without charging a delay twice.
  For an event at t: receive at t+d_feed, decide after d_compute, reach the engine
  after d_order; its resulting fill notification then incurs d_fill.
- Deterministic causal event ordering and reproducible random seeds. For equal
  arrival times use documented sequencing; randomize symmetric tie priority
  across trials so an agent ID is not a permanent advantage. Test ambiguities
  within the historical timestamp resolution rather than assuming perfect clocks.
- Native signed inventory, collateral, margin, fees and settlement; exposure
  and gross-futures limits, reservations, restarts and the existing pair/roll
  rules. The paid proxy stays outside gross futures leverage. Simulated margin
  stress must use an explicit model, not claim a venue portfolio-margin offset
  merely from the leverage cap.
- A common spot/fundamental and term-structure driver for background valuations.
  Do not draw each maturity independently or overwrite matched prices with the
  historical trade path after our orders have changed the book. First retain
  the explicit synthetic proxy convention; test finite proxy execution capacity
  and cash-transfer delays before drawing capacity conclusions.

Use a mixed population: PRD agents with different delays, capital and adaptation
rules; liquidity providers with inventory constraints; directional/hedging flow;
and spot/futures arbitrageurs. A market containing only identical PRD traders
can have everyone wanting the same trade and nobody supplying the other side.
Giving them arbitrary opposing orders would bake assumed profitability into the
model. Genuine collective gains must reconcile with counterparties' losses,
underlying exposure and explicit external cash flows, less costs.

In the interacting-book experiment, fills come from actual simulated matching.
Do not also apply an independent strict-through fill to each agent, reuse a
print's full quantity across agents, or force an original historical print after
its original liquidity has been consumed. Strict-through remains the conservative
historical-replay comparison. Historical aggressor flow may be injected as a
declared exogenous assumption, but resulting prices then come from the changed
book; this is no longer reproduction of the original tape.

### Data needed and what remains uncertain

We already have trade timing, prices, sizes, aggressor direction, attached index/
mark observations and instrument metadata. These inform turnover, APR regimes,
trade-size distributions and coarse cross-contract dependence. They do not
identify order arrival/cancel rates, depth, individual queue rank, participant
inventory or end-to-end latency. Many different agent markets can generate
similar trade tapes. Fit ranges of plausible market models and stress them;
one visually plausible price path is not validation.

Collect synchronized full-depth snapshots/deltas, trades, index/mark updates,
instrument changes, exchange timestamps and local receipt times. Authorized own
order acknowledgments can inform latency later; do not submit live orders just
to gather a research sample. Deribit's documented book feed supplies price-level
deltas and change IDs, not individual order identities [3]. Thus even L2 leaves
queue placement/cancellation assumptions; it is not market-by-order history.
Raw-feed batching descriptions differ between its channel reference and general
guide (1 ms aggregation versus normally unbatched, with possible coalescing)
[3,4]. Verify the actual subscribed feed behavior before claiming 1 ms realism.

Validate on separate windows: bid/ask spread and depth distributions, signed
volume, cancellations, queue survival/fill rates, returns, volatility clustering,
cross-maturity basis behavior, and impact/recovery after order flow. Match these
before evaluating PRD profits; fitting the simulator to make the strategy earn
money would be circular.

### Framework, scale and experimental sequence

ABIDES is a suitable framework to evaluate: its core is message/event based with
agent-to-exchange latency; ABIDES-Markets supplies an exchange and stylized agents
based on equity-market conventions [1,2]. It is not a ready-made Deribit inverse
futures/margin simulator. Inspect dependencies/license, pin a revision, and
benchmark a small derivative adapter before adopting it. A queue-reactive model
can supply calibrated state-dependent background flow once book data exist [5].
Reinforcement learning is not necessary: begin with deterministic PRD policies
and stochastic background agents. Strategic learning is a later experiment.

A new hash-checked scan of the 180 local files gives this concrete workload
([script](research/btc_prd_market_feasibility.py),
[result](research/extended-results/btc-prd-market-feasibility.json)):

| June 6-September 4, 2026; Dec26 and Mar27 | Value |
|---|---:|
| Ordinary trades, after flagged exclusions | 462,642 |
| Mean / busiest-day ordinary trades | 5,140 / 25,019 |
| Ordinary trades in busiest second, combined | 241 |
| Trades sharing an instrument/millisecond with another trade, Dec / Mar | 156,358 / 63,937 |
| Largest instrument/millisecond batch, Dec / Mar | 55 / 43 |
| Deliveries if 100 agents receive every individual trade in both tapes | 46,264,200 |
| Same calculation for 1,000 agents | 462,642,000 |

These are delivery arithmetic, not measured simulator throughput. Book updates,
agent wakeups, commands, acknowledgments and fills add work. Start with roughly
10-100 strategic agents and aggregated background processes; subscriptions and
decision scheduling should reflect the modeled system. Never reduce feed
frequency silently to improve a latency experiment's runtime.

Use an event queue, not a loop over every millisecond: simulated 1 ms latency
does not require executing in 1 ms wall time. Benchmark events/second, peak RSS,
queue size, audit output and one simulated day's wall time at several populations.
Run independent seeds/scenarios across CPU processes; an individual market path
needs consistent event order. Stream audit logs rather than retaining every
delivery in memory. A CPU workstation with 16-32 GB RAM is a reasonable pilot
budget to test, not a certified whole-history requirement; a GPU is unnecessary
for the proposed rule-based pilot. Existing replay timings do not estimate this
new engine's runtime. Size storage from measured book/log rates before collecting
months of depth data.

Recommended sequence:

1. Implement the causal estimator and versioned target transitions; validate
   them with funded historical replay, retaining fixed-grid controls.
2. Build a bounded three-book matching prototype. Verify causality, finite volume,
   native accounting and symmetric agents, then measure event cost. This is a
   mechanics/feasibility gate, not a profitability result.
3. Calibrate background flow from available book data; otherwise label a broad
   sensitivity envelope as synthetic. Compare 1, 10, 100, 500 and 2,000 ms per
   delay leg, with identical policies/capital initially, then vary population,
   capacity, jitter and adaptation memory. Swap delay assignments across agent
   identities and use repeated paired seeds. Also vary total capital separately
   from agent count to distinguish crowding from splitting the same capital.
4. Measure realized/unrealized P&L, fill share, adverse selection, unpaired
   duration, fee/cancel turnover, basis compression, margin usage and retirements.
   Compare private calibration using only that agent's received messages with
   a shared-estimator control. This tests whether synchronized adaptation itself
   causes crowding or unstable quotes. Faster agents need not always earn more.
5. Add longer roll/restart scenarios, finite proxy execution and cross-market
   feedback only after the smaller model passes its data/mechanics checks.

The full historical archive is valuable for adaptive replay and regime sampling.
Running every simulated order book for the entire decade is not the first
feasibility test; representative calm, volatile, illiquid and retirement windows
will establish whether the model and computational cost justify that expansion.

## Sources consulted

Primary sources checked 14 October 2026; they support the available simulation
methods and feed descriptions, not profitability of this proposed strategy.

1. Byrd, Hybinette and Balch, [ABIDES: Towards High-Fidelity Market Simulation
   for AI Research](https://arxiv.org/abs/1904.12066).
2. JPMorgan Chase, [ABIDES-Core / Markets / Gym repository](https://github.com/jpmorganchase/abides-jpmc-public).
3. Deribit, [full-depth book channel](https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval).
4. Deribit, [market data collection guide](https://docs.deribit.com/articles/market-data-collection-best-practices).
5. Huang, Lehalle and Rosenbaum, [Simulating and analyzing order book data:
   the queue-reactive model](https://arxiv.org/abs/1312.0563).
6. Deribit, [Inverse Futures](https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures), checked 15 October 2026.
7. Deribit, [Position Builder](https://support.deribit.com/hc/en-us/articles/31238900906781-Position-Builder), inverse payoff formula, checked 15 October 2026.
