# BTC PRD: live calibration and competing-agent market research

Research design, 14 October 2026. Owner requirement: infer both PRD location
and opening/closing gap from recent historical observations and update them
while trading. The numerical policy and inventory-transition rules below are
proposals for testing, not selected production defaults. No adaptive trading
engine or competing-agent simulator is implemented by this document.

The [full-history study](BTC_PRD_EXTENDED_CALIBRATION.md) trained each contract's
grid once and held it fixed. It did not test live recalibration. The requested
adaptive policy supersedes that fixed-grid approach as the intended strategy.
Historical fixed-grid results remain useful controls. The earlier proposal to
freeze every held closing target is replaced here by an explicit comparison of
adaptive and entry-frozen exits; the owner has not selected those semantics.

## 1. Separate market adaptation from execution decisions

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

## 2. What changes when a calibration version changes

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

## 3. Feasibility of a market populated by competing PRD agents

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
