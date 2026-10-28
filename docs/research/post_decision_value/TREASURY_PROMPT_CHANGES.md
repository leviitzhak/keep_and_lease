# Specific prompt changes — 28 October 2026

Only the changed instructions are reproduced below. The complete standalone
rewrite is [TREASURY_LEARNING_NEXT_PROMPT.md](TREASURY_LEARNING_NEXT_PROMPT.md).
The precise definitions/caveats are in [ROLLOUT_MAXMIN_SPEC.md](ROLLOUT_MAXMIN_SPEC.md).
UI separation, Windows-local hosting and durable downloads remain required later.

## 1. Replace the expected-continuation target with sampled max–min rollout search

```text
From each post-state and horizon propose J causal candidate continuations using
the frozen network plus reproducible exploration. For each candidate repeat K
uncertainty scenarios while retaining the same controller/exploration rule. Actions
may respond to each replica's own observations; future-dependent scripts may not.
At the fixed endpoint compute G[j,k]=joint terminal liquidation utility.
Train on y=max_j min_k G[j,k]. Use no intermediate-value maximum and no current
prediction in the target. Preserve downward corrections and all failed paths.
```

This replaces the earlier blanket expected-utility description. It is conservative
only over sampled scenarios, not a guaranteed worst case or market-independent
return. Version J/K and uncertainty law; independent winner reevaluation is required.

## 2. Make the action/horizon rule explicit

```text
At each decision choose the admissible (action,horizon) pair maximizing
V(post(state,action),horizon)/horizon, with horizon>=h_min>0 and V>=v_min.
Inside subtrajectories use network evaluations, with exploration, until the fixed
outer deadline; do not run recursive subtrajectory searches or extend that deadline.
Define ties/wait fallback and keep safety responses outside the profit threshold.
```

The requested raw rule is retained. With original-episode growth as the benchmark,
past gains can favor short horizons. Plot wait/incremental comparisons and document
this issue; do not silently replace the rule or claim the benchmark choice settled.

## 3. Replace executable-unwind requirement for the initial boundary

```text
For now L_mark directly values a copy of the portfolio by idealized immediate
cancellation of pending/live orders and closing non-base instruments at contemporaneous
marks, with native P&L, fees, collateral and net obligations accounted for. Retain
USD/BTC or the configured base proxy. Label this a terminal valuation proxy.
Train V(state,0) on this independent calculation. Within-trajectory delay/fill/cancel
semantics remain unchanged. Independently learned liquidation and realistic unwind
are later extensions. Do not treat market marks as executable quotes.
```

## 4. Explicit BTC repurchase belongs to the learner

```text
When a futures purchase was funded by selling BTC, allow the policy to choose an
explicit funded BTC repurchase after closing the future. Do not repair BTC holdings
automatically inside liquidation. Test the full economic sequence. Positive scalar
utility with finite lambda need not imply positive growth in both commodities.
```

## 5. Align ground truth and plots with the new target

```text
Separate marked boundary value, exact sampled-max–min search value, full finite-toy
optimum and attained network-only policy results. Match information/actions/scenarios
and apply nonanticipative controller choices. Plot learned-minus-MATCHING-reference
errors and sampled-search/policy gaps; do not call expected-versus-robust differences
regression error. Test controllable actions separately from uncontrollable outcomes.
```

## 6. Clarify training/test causality and defer broader market simulation

```text
Use future training tape to produce offline labels, and causal network-only action
selection on held-out tests. A test split checks generalization but does not turn
best-on-one-tape labels into uncertainty-robust truth; execution seeds alone do not
sample market paths. Report both search labels and actual held-out policy outcomes.
Document a broader synthetic market generator as later work: vary spot direction,
premiums, rates, liquidity and funding with consistent economics and no-opportunity
controls. Only tiny Treasury fixtures are needed now. The UI also remains a separate
later task; its displayed value semantics and bundle metadata must reflect max–min.
```
