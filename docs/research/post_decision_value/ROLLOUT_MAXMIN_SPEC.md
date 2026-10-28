# Value-only rollout search: sampled max–min specification

28 October 2026. **Design update only. Not implemented or trained.** This supersedes
conflicting expected-value/hold-only instructions in earlier handoffs, not the
historical descriptions of completed experiments. The next executable task is
[TREASURY_LEARNING_NEXT_PROMPT.md](TREASURY_LEARNING_NEXT_PROMPT.md); the UI remains
[a separate later task](STATE_VALUE_EXPLORER_PLAN.md).

## Objective and policy

Learn one decision value function `V_theta(x, h)`, where `x` is an observable
immediate post-decision state, including reported holdings and submitted/pending
instructions. Sending an instruction does not simulate its arrival or fill.
The scalar is now a **sampled conservative search score**, not an unqualified
expected-utility prediction. Keep the existing terminal joint utility:

`U(g) = 0.5*positive(g_BTC) + 0.5*positive(g_USD)
        - 10*(positive(-g_BTC)+positive(-g_USD)) - failure_penalty*failed`.

Initial benchmark holdings, scales, persistent failure flags, target and holding
floors remain part of the experiment/state identity. Do not silently relax them.
A large finite loss penalty does not mathematically require both growths to be
nonnegative; imposing that as a terminal constraint would be a separate change.

Initial learning uses a fixed terminal deadline for each rollout. At an observed
state `s` with remaining physical time `r > 0`, enumerate a bounded native action
grid and select:

`a* = argmax_a V_theta(post(s,a), r)`

over admissible actions, with exploration during collection. Include wait,
deterministic ties and required cancellation/emergency behavior. After elapsed
time `dt`, query `r-dt`; never restart the deadline. At `r=0`, stop decisions and
calculate terminal liquidation. Learn this function for several initial horizons
H, with every individual rollout counting down to its own fixed endpoint.

The user's follow-up explicitly defers constant-lookahead and `V/h` selection to
later policy experiments. Neither horizon maximization nor the optional minimum
utility threshold is an initial training-policy requirement. See the dedicated
comparison below; this supersedes the earlier handoff's immediate `V/h` rule.

## Offline rollout labels

For each sampled post-state `x` and outer horizon `H`:

1. Freeze the network, action grid, training horizons, decision clock, exploration
   mechanism and all economic/valuation settings for the collection stage.
2. Propose `J` candidate continuations. Each is a reproducible causal controller:
   the network's grid selection plus a fixed exploration seed/rule, optionally
   with a forced initial choice. Keep this controller fixed across uncertainty
   replicas. Recompute actions from each replica's own received observations;
   do not copy a future-dependent realized order script between replicas.
3. For each candidate `j`, run `K` uncertainty replicas `omega_k`. Vary only
   specified exogenous uncertainty such as delays/fills; keep candidate/controller
   randomness separate. Use the same scenario set across candidates for comparison.
   Do not invent stochastic depth/fills absent an explicit model and provenance.
4. Inside a rollout, use network evaluations for decisions, allowing the candidate's
   prescribed exploration. Do not launch nested rollout searches. At remaining
   time `r`, choose among admissible actions by `V_theta(post(s,a),r)` plus the
   candidate's exploration. Reduce r by actual elapsed time; advance all exchange
   events exactly and stop selecting actions at the fixed outer deadline.
5. At the strategic endpoint stop decisions, then simulate liquidation using
   subsequent trades in chronological order, giving final joint utility `G[j,k]`.
   Ignore the liquidation duration in the objective/horizon for now. Earlier states
   may supply separate boundary samples with their own subsequent-trade tails;
   intermediate marks/values are not a maximum-along-time reward or inner action oracle.
6. Compute `R[j] = min_k G[j,k]`, then `y(x,H) = max_j R[j]`. Train against this
   outcome-derived label, with no current-network prediction in the maximum.
   Labels must allow both downward and upward correction. Retain the full matrix,
   winning controller, joint worst-case replica and ties for audit.
7. Refit, recollect with the improved frozen network and evaluate within one
   bounded collect–fit–improve–evaluate campaign. This is rollout search plus
   regression, not a new actor or recursive MCTS requirement.

`J`, `K`, scenario law/set, candidate seeds, horizon/grid/policy conventions and
liquidation mode change the target and belong in its versioned identity. Squared-error
regression across newly sampled batches learns a conditional average of this
finite-search statistic; it is not a certified worst-case value. Do not silently
mix old expected-continuation labels/checkpoints with this target.

If auxiliary commodity/failure outputs remain, define their aggregation explicitly
under the SAME winning controller. For example, terminal holdings from the
replica minimizing joint utility are different from mean holdings. Never combine
separate worst BTC and worst USD scenarios into a fictitious terminal portfolio.
No auxiliary head may select a different optimal controller.

## What is conservative, and what is not

The minimum is conservative over the scenarios actually sampled. It is generally
optimistic relative to the minimum over a larger uncertainty set. Five independent
samples miss an event of probability 1% with probability `0.99**5 = 95.10%`.
For a fixed candidate and nested samples, increasing K can only reduce its sample
minimum. Increasing J can raise the best score and can select an unusually lucky
scenario fit. Fix budgets for comparisons and independently reevaluate selected
controllers on new seeds/stress cases; report mean, minimum, quantiles and failures.
These diagnostics do not silently replace the requested max–min objective.

The best searched candidate is the best in the sampled controller set. The exact
optimum considers every admissible controller in the declared toy action model
under the same uncertainty criterion. With the SAME full scenario set, restricted
search cannot exceed that optimum. With only sampled uncertainty there is no
unconditional ordering against the full-uncertainty optimum: action restriction
can lower the result while missing adverse scenarios can raise it.

The +1/-1 example has two interpretations. If two controllable deterministic actions
return +1 and -1, choose +1. If one action randomly returns either, +1 is the best
possible outcome, expected value is 0 and worst-case value is -1. Under the sampled
minimum, the label is -1 if a negative replica is seen and +1 otherwise.

Reference: [Dabbene, Maggioni and Pflug, sampled multi-stage robust optimization](https://optimization-online.org/2019/11/7485/).
Its distinctions between sampled and full uncertainty motivate the terminology;
its convex-model guarantees are not claimed for this nonlinear neural experiment.

## Full-path sampling instead of exhaustive long trees

With two feasible uncertainty outcomes at each of L steps, an unrecombined tree
has `2**L` leaves. This is the cost of that exhaustive representation, not a universal
lower bound: small sufficient-state models can merge equivalent states, and some
deterministic Treasury values have closed forms. No such general exact shortcut
is assumed for the full order/market simulator. Exact search is confined to tiny
bounded reference fixtures, never required for long trajectory labels.

For the initial learner sample K complete uncertainty paths for each of J candidate
controllers. At each step of one path draw only the next outcome, continue to the
endpoint, then repeat with another scenario seed. Do not fork every node, resample
a K-way subtree at every step, or enumerate all combinations of local outcomes.
With L decisions per path this takes roughly J*K*L rollout decision steps, plus
the cost of the action-grid network evaluations and exact exchange events.
The sample minimum is an approximation; a small K has no worst-case guarantee.

Recommended initial setup: a fixed matched K across candidates, separate controller
and uncertainty seeds, batched action evaluations where supported, and independent
winner reevaluation. Match common exogenous shocks by event/time identity where
paths diverge; preserve each path's correct joint law and temporal dependence.
Treat all hypothetical market/execution sampling models as explicit configuration.

Possible later improvements are staged candidate screening and targeted adverse
scenario searches. Finalists must receive equal scenario support/budgets before
comparing minima; an adaptive or unequal K otherwise changes the statistic being
compared. Keep a fresh random audit set and separately labeled stress results.
If stresses enter the training minimum, version the new scenario law/support and
target. Neither adaptive sampling nor targeted stress certifies the true worst case.

## Training tape, held-out evaluation and economic intent

Train and calibrate on training/development history. Test frozen checkpoint/grid/
policy settings on chronological held-out history, with all full tails kept
inside their split. The executed held-out policy uses only received information
and network inference. Do not use the realized future test tape to choose its
current action. Offline oracle labels may be computed separately afterward for
clearly labeled diagnostics, not test-time action selection.

It is legitimate to use training futures-in-time for labels. However, choosing the
best continuation on that one realized market tape gives a **tape-conditioned
search target**. Repeating execution seeds only stresses execution; it does not
create alternative market paths. A held-out causal policy test assesses whether
learned economic rules generalize, but cannot turn the training label into a
certified market-independent value. Report search score and attained policy value
separately. Preserve inverse-source/linear-trading counterfactual labeling.

The intended opportunities are commodity/unit growth from carry and premium
spreads, rather than directional spot speculation. Test each claimed economic
mechanism with a cash/BTC ledger and explicit funding, fees and maturity cashflows.
After both legs are established, distinguish contractual price-neutrality from
execution leg risk, margin/funding constraints and the cost of eventual conversion.

## Liquidation boundary from subsequent trades; duration ignored for now

The user's clarification replaces the earlier contemporaneous-mark convention.
Define a separate `L_trade(state, scenario)` calculator returning final joint
utility, net USD/BTC ledger and trade provenance. It obtains labels from simulated
liquidation using trades AFTER the strategic endpoint, not from the value network.
Future observations are legitimate supervised targets; they remain unavailable
to the state encoder and action-selection policy at the decision timestamp.

On a COPY of the simulator state:

- Stop strategic decisions. Retain the initial idealized atomic cancellation of
  outstanding/in-flight instructions and release reservations; label that assumption.
  Ordinary in-trajectory cancellation delays/races remain unchanged.
- Retain USD cash and direct BTC (or the configured base proxy). Submit the fixed
  closing procedure for other inventory; no further discretionary strategy actions.
- Consume eligible subsequent trades chronologically under a predeclared execution
  rule, including native quantities, partial fills, participation assumptions and
  specified execution uncertainty. Preserve trade IDs, timestamps, source and rule
  identity. Trade prints alone do not establish executable depth or guaranteed fills.
- Realize native futures P&L, configured fees, collateral release and net liabilities.
  Honor dated cashflows/obligations encountered in the tail exactly once; do not
  double-count redemption and sale proceeds or invent unobserved settlements.
  Inverse P&L stays BTC absent an explicit conversion. Start with debt-free fixtures.
- Apply joint utility to the resulting net USD/BTC and retain prior path failures.
  Do not automatically buy BTC to repair the portfolio.

**Ignore liquidation duration for now:** T is the strategic horizon only. Do not
add tail duration to T, discount for that duration, add a duration penalty, or use
it in a rate denominator. Retain timestamps for chronological execution, dated
accounting, provenance and split boundaries; this does not make duration an input
to the current objective. Do not restart strategic trading during the closing tail.
Learning a separate liquidation-value model and liquidation-time model, then using
them in decisions/objectives, is deferred. V(s,0) can still be supervised directly
from calculated liquidation outcomes now; that is not an extra liquidation model.

The scenario's complete path includes its liquidation tail. For candidate j take
the minimum of final joint utility across the K sampled paths, then maximize over
candidates as above. At zero strategic horizon there is no continuation search:
the boundary label is `min_k L_trade(s,omega_k)` under the same sampled-minimum
definition. A deterministic tape/execution rule gives a single liquidation outcome;
repeating identical inputs does not create new worst-case cases. Do not add an
unbudgeted nested branching search just for liquidation.

Sequential execution and worst-case evaluation are compatible: each scenario
produces a feasible sequence of closing fills; the minimum selects the least
favorable JOINT portfolio outcome among those sequences. Do not choose separate
worst trades for different legs/currency heads that cannot coexist in one scenario.
An optional adversarial trade-subsequence study would need a declared finite tail
window and feasible quantity/timing constraints. It would change the uncertainty
support/target and is not the initial sequential sampler. An unrestricted minimum
over all future prints is not a defined execution model, even when time is unpriced.

Bound tail scans and require their data to remain entirely within the assigned
training/validation/test split. Exhausted data or incomplete liquidation is explicit
incomplete/failure status under a fixed policy, never silently a favorable mark or
dropped adverse case. Ignoring duration in utility does not permit cross-split labels.
Show simulated outcomes separately from observed executions; preserve synthetic
labels for fixtures and inverse-source/linear-trading counterfactual provenance.

The phrase "future-value predictions must not supply boundary targets" forbids
self-generated ground truth from the value network, NOT future market trades.
Test that later tape changes can alter boundary labels while leaving current
features/predictions unchanged. Hidden exchange truth may affect replica outcomes
but must never leak into observed-state features or exact conditional-value claims.

## BTC repurchases belong to the policy

Include funded spot/proxy buys and sells in the action domain for the later carry
learning stage. Closing a linear future realizes USD P&L; it does not deliver BTC.
After financing a future purchase by selling BTC, the learner should choose an
explicit BTC repurchase when feasible and advantageous under joint utility.
Do not automatically restore BTC in liquidation or count a closed future as BTC.
Price, fee, funding and partial-fill effects must be visible in the training data.
With finite lambda=10, a sufficiently large USD gain can still outweigh a BTC loss;
report each commodity's growth rather than interpreting positive utility as a
guarantee of growth in both. Preserve the existing maximum 10% temporary net-holding
reduction unless a separate user change is made.

## Exact references and staged tests

First diagnose boundary prediction/overfit and one Treasury held to maturity;
that hold-only task is a training diagnostic, not the intended final policy.
Then run a tiny repeated-decision toy with finite actions/horizons/scenarios.
Compute an independent exhaustive reference with the SAME liquidation convention and
sampled-max–min definition. Use causal controllers: identical observable histories
must receive identical actions, even across different hidden future scenarios.
A pointwise scenario-tree min at every step is not automatically equivalent to
min over a fixed full-path scenario set; enumerate complete causal controllers
for the tiny case or prove the chosen backward recursion matches the scenario model.

Separate exact boundary value, exact sampled-search target, full declared-toy
optimum, and realized frozen-policy results. Test full deterministic action coverage,
controlled +1/-1 actions versus stochastic +1/-1 outcomes, sample-min sensitivity,
independent winning-controller reevaluation, sequential future-trade liquidation,
cancellation, ignored duration, complete split-contained tails, no automatic BTC
restoration, and backward learning corrections.

Plot losses plus learned-minus-matching-reference errors. Never compare the new
robust head against expected utility and label that discrepancy a regression error.
Declare all reference supports; no exact claims outside the small specified model.

## Later comparison of horizon-selection policies

Once V(s,h) is learned for several horizons, investigate the following separate
causal policies; do not implement or tune the latter two in the initial sanity task.

| Policy | Decision rule | Horizon evolution |
| --- | --- | --- |
| Fixed deadline, initial baseline | `argmax_a V(post(s,a),r)` | Remaining r decreases to the original terminal date. |
| Constant lookahead, later | `argmax_a V(post(s,a),T)` | T stays constant at every decision; the planning endpoint moves forward. |
| Rate-based lookahead, later | `argmax_(a,h) V(post(s,a),h)/h` | Rechoose h from a supported positive grid at every decision. |

For the rate policy investigate a positive minimum h and the previously proposed
minimum absolute utility v_min. Never divide V(s,0) by zero. Times have a common
physical unit; multiplying by time/year is a display scale, not utility compounding.
The implemented utility is relative to original episode holdings, so accumulated
gains can favor short h without new opportunity. Examine raw and explicitly named
incremental-score variants and wait comparisons before calibrating this later rule.
Thresholds cannot suppress mandatory safety responses. This issue does not block
the fixed-deadline learning experiment.

Compare frozen policies on the same held-out starts, uncertainty seeds, action
domain, strategic evaluation duration and terminal liquidation convention. Freeze policy
selection/hyperparameters on validation data. Require data and trained horizon
support for rolling lookaheads, report end-of-data handling, and do not extend the
strategic scoring window when a planning horizon is reset. Closing tails can follow
that deadline under the common duration-ignored rule, but must stay inside the split.
Record growth, failure/tail
results, turnover, costs and computation. Inspect repeated postponement of expected
gains: a moving planning deadline alone is not realized profit.

Use the same frozen multi-horizon checkpoint for the first policy comparison.
Changing its deployment rule can change the actual continuation; its learned
fixed-deadline search values are not automatically calibrated values of either new
policy. Measure their realized results separately. Any later recollection/refitting
under a new controller must get a new policy/target identity.

## Deferred next steps

1. Horizon-policy comparison above, and a separate local interactive explorer/Windows
   package after the learning task. Expose policy identity and horizon behavior.
2. Broader synthetic market generator for training and stress testing: diverse spot
   paths, premium curves/mean reversion and maturity convergence, rates/cashflows,
   costs, liquidity and execution/funding shocks. Calibrate on training data only;
   preserve positivity, units, cashflow identities and causal information. Keep
   known-opportunity and no-opportunity controls to detect simulator shortcuts.
   Vary spot direction/volatility with economic carry structure held comparable;
   separately vary premiums and costs. Synthetic robustness is not historical proof.
3. Separate liquidation-value and liquidation-time learning/use, more realistic
   cancellation/closing execution, then
   historical spot/Treasury/funding/expiry data completion and long-history runner.

Only tiny explicit Treasury fixtures are required now. The broader simulator,
years-long training, UI and new infrastructure are not part of the next learning
implementation. Existing runtime limits remain in force; cap the aggregate J*K
rollout work and fitting budget, and do not launch recursive or unattended searches.
