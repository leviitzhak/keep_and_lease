# Latest prompt changes — 28 October 2026

These changes follow the liquidation clarification, relative to the handoff at
`ecc010f83ab660fcc3874b99cd055d98ee4fa7cc`. The full standalone prompt is
[TREASURY_LEARNING_NEXT_PROMPT.md](TREASURY_LEARNING_NEXT_PROMPT.md); the complete
strategy is [ROLLOUT_MAXMIN_SPEC.md](ROLLOUT_MAXMIN_SPEC.md). Fixed-deadline initial
learning, max–min path sampling and later horizon-policy experiments remain unchanged.

## 1. Subsequent trades supply the liquidation labels

```text
Calculate L_trade from simulated liquidation using SUBSEQUENT trades sequentially
under a fixed declared closing/fill rule. Future trades may supply supervised
labels, but never current features or action-selection inputs. Record source trade
IDs, timestamps, quantity assumptions, native P&L, fees and net obligations.
The network's OWN predictions must not supply boundary ground truth; this does
NOT prohibit future market trades. Keep the temporary cancellation idealization
explicit and distinguish modeled fills from observed executions.
```

This replaces the earlier contemporaneous-market-mark requirement. Initial V(s,0)
training still uses independently calculated outcomes, without a separate liquidation
prediction model.

## 2. Ignore liquidation duration for now

```text
T measures strategic continuation only. Ignore liquidation duration in the current
objective: do not extend T, discount for the tail, add a duration penalty or adjust
a rate denominator. Keep timestamps for sequential execution, dated accounting and
data-split integrity. Do not resume discretionary strategy trading during closing.
Separate liquidation-value/time models and using their estimates are later work.
```

## 3. Take the worst complete liquidation outcome

```text
Each sampled scenario includes its sequential closing tail. Compute final joint
utility, then take the minimum across K complete outcomes for a candidate controller.
At T=0 use min_k L_trade(state,scenario_k), without a continuation search. One
deterministic tape/fill rule gives one outcome; repetitions alone add no uncertainty.
Never combine independent worst trade prices across legs into an infeasible result.
Bound tail reads and keep complete tails within the assigned train/validation/test
split. Missing data or incomplete closing is explicit, never a convenient mark
fallback or an omitted adverse case.
```

An alternative worst-trade/subsequence search would need a declared finite window
and feasible timing/quantity constraints; it is not the initial sequential sampler.
The explorer plan now separates ex-post liquidation-reference trades from current
model inputs and identifies ignored duration. No code, checkpoint or run changed.
