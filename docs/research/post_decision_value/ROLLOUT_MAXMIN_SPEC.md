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

At an observed state `s`, enumerate a bounded native action grid and positive
horizon grid. The user's requested policy is literal:

`(a*,h*) = argmax V_theta(post(s,a),h) / h`

subject to admissibility, `h >= h_min > 0`, and `V_theta(post(s,a),h) >= v_min`.
Times have one documented unit. Multiplication by seconds/year is a display scale,
not compounding a utility as if it were a financial return. Include wait and
required cancellation/emergency behavior; define deterministic ties and a wait
fallback when nothing meets the discretionary threshold. Safety responses cannot
be disabled by a profit threshold. Never divide a zero-horizon value by zero.

**Benchmark issue kept explicit:** the implemented historical utility is relative
to original episode holdings. With that convention, already accumulated gains
can make `V/h` favor short horizons even without new opportunity. Preserve the
requested raw rule in the initial experiment, require finite `h_min`, and show
wait values, `V(a,h)-V(wait,h)` and `V(a,h)-L_mark(s)` as diagnostics. Do not silently
replace the rule with an incremental-score rule. Whether the threshold/rate should
instead apply to incremental growth remains a preference to resolve before
calibration or economic claims. This does not block the initial zero-gain fixtures.

## Offline rollout labels

For each sampled post-state `x` and outer horizon `H`:

1. Freeze the network, action/horizon grids, threshold, decision clock, exploration
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
   time `r`, eligible positive target horizons satisfy `h <= r`; selecting a new
   lookahead never extends the fixed outer deadline. Advance all exchange events
   exactly. Stop selecting actions at the outer deadline.
5. Only at the endpoint evaluate terminal marked liquidation and joint utility,
   giving `G[j,k]`. Earlier marks may be recorded for diagnostics or boundary
   datasets but are not a maximum-along-time reward or an inner action oracle.
6. Compute `R[j] = min_k G[j,k]`, then `y(x,H) = max_j R[j]`. Train against this
   outcome-derived label, with no current-network prediction in the maximum.
   Labels must allow both downward and upward correction. Retain the full matrix,
   winning controller, joint worst-case replica and ties for audit.
7. Refit, recollect with the improved frozen network and evaluate within one
   bounded collect–fit–improve–evaluate campaign. This is rollout search plus
   regression, not a new actor or recursive MCTS requirement.

`J`, `K`, scenario law/set, candidate seeds, horizon/grid/threshold conventions and
marking mode change the target and belong in its versioned identity. Squared-error
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

## Training tape, held-out evaluation and economic intent

Train and calibrate on training/development history. Test frozen checkpoint/grid/
threshold settings on chronological held-out history, with all full tails kept
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

## Temporary liquidation boundary, separately learnable later

Define a separate `L_mark(state)` valuation interface returning the joint utility
and its supporting net USD/BTC ledger, independent of future-value search. Use
the scalar utility as the horizon-zero regression target. For this initial
experiment the user authorizes an idealized terminal
convention on a COPY of the simulator state:

- Stop strategy decisions, cancel all outstanding and in-flight order instructions
  atomically, and release their reservations. No cancellation fee unless specified.
- Retain USD cash and direct BTC (or the explicitly configured base proxy).
- Close all other inventory at documented contemporaneous market marks; realize
  native futures P&L, charge configured close fees, release collateral and account
  for liabilities. Do not count face/redemption claims and sale proceeds twice.
- Use the last eligible observation at or before the terminal timestamp; record
  source/time/age and missing-mark policy. Never choose a favorable later print.
  Inverse P&L remains native BTC; do not force it into USD without a conversion rule.
- Process due receipts exactly once. Do not forgive debts/future obligations merely
  because positions close; include their explicitly defined discharge/valuation.
  Start with debt-free Treasury fixtures rather than inventing an unsupported model.
- Apply the joint objective to final net USD/BTC and retain prior path failures.

This is a **terminal market-mark proxy with idealized cancellation**, not realized
liquidation or evidence of executable depth. It changes endpoint valuation only:
ordinary in-trajectory orders, delays and cancellation races stay exact. A min
across replicas does not make this optimistic endpoint convention executable.

At horizon zero, use `L_mark` directly as the boundary target for `V(state,0)`;
create separate supervised boundary samples. Do not generate a boundary label from
future-value predictions. A separately supervised liquidation estimator and a
realistic delayed execution/unwind simulator are later extensions. If oracle
valuation uses hidden ledger truth while the network sees only delayed reports,
label the per-replica endpoint honestly; exact value conditioned on observed state
must account for consistent hidden-state uncertainty, not disclose it as a feature.

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
Compute an independent exhaustive reference with the SAME mark convention and
sampled-max–min definition. Use causal controllers: identical observable histories
must receive identical actions, even across different hidden future scenarios.
A pointwise scenario-tree min at every step is not automatically equivalent to
min over a fixed full-path scenario set; enumerate complete causal controllers
for the tiny case or prove the chosen backward recursion matches the scenario model.

Separate exact boundary value, exact sampled-search target, full declared-toy
optimum, and realized frozen-policy results. Test full deterministic action coverage,
controlled +1/-1 actions versus stochastic +1/-1 outcomes, sample-min sensitivity,
independent winning-controller reevaluation, terminal marking/cancellation,
no automatic BTC restoration, and backward learning corrections.

Plot losses plus learned-minus-matching-reference errors. Never compare the new
robust head against expected utility and label that discrepancy a regression error.
Declare all reference supports; no exact claims outside the small specified model.

## Deferred next steps

1. Separate local interactive explorer/Windows package, after the learning task.
2. Broader synthetic market generator for training and stress testing: diverse spot
   paths, premium curves/mean reversion and maturity convergence, rates/cashflows,
   costs, liquidity and execution/funding shocks. Calibrate on training data only;
   preserve positivity, units, cashflow identities and causal information. Keep
   known-opportunity and no-opportunity controls to detect simulator shortcuts.
   Vary spot direction/volatility with economic carry structure held comparable;
   separately vary premiums and costs. Synthetic robustness is not historical proof.
3. Independent liquidation learning and realistic execution-aware closing, then
   historical spot/Treasury/funding/expiry data completion and long-history runner.

Only tiny explicit Treasury fixtures are required now. The broader simulator,
years-long training, UI and new infrastructure are not part of the next learning
implementation. Existing runtime limits remain in force; cap the aggregate J*K
rollout work and fitting budget, and do not launch recursive or unattended searches.
