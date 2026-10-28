# Latest prompt changes — 28 October 2026

These are the follow-up changes relative to the previous max–min handoff at
`12ae4b6df5fbd970e20246f9308fce0abff6d194`. The complete standalone prompt is
[TREASURY_LEARNING_NEXT_PROMPT.md](TREASURY_LEARNING_NEXT_PROMPT.md); definitions
are in [ROLLOUT_MAXMIN_SPEC.md](ROLLOUT_MAXMIN_SPEC.md). The liquidation boundary,
max–min endpoint target, explicit BTC repurchases, and separate later UI remain.

## 1. Initial learning counts down to a fixed deadline

```text
For the initial learner, fix each rollout's terminal deadline and choose the
admissible action maximizing V(post(s,a),r), where r is its remaining physical
time. Decrease r by elapsed time; never move the deadline. Allow exploration
while collecting data. At r=0 use the liquidation boundary. Learn across several
initial horizons, with each rollout counting down independently.
```

This replaces the previous immediate V/h selection and threshold requirement.
No ratio-policy tuning or raw-versus-incremental choice blocks the initial test.

## 2. Sample complete long paths; exact search remains a tiny-toy diagnostic

```text
For each candidate controller sample K complete uncertainty paths. Draw one next
outcome per step, reach the endpoint, and repeat; do not branch into K children
at every node. With J controllers and L decisions per path, budget roughly J*K*L
rollout decision steps plus action-grid inference and exchange-event processing.
Use matched K/scenarios, separate exploration/uncertainty seeds and fresh winner
audits. Preserve temporal dependence. Exact enumeration is only for tiny references.
```

Matched sampling and batching are the initial practical refinements. Adaptive
screening and targeted stress may be studied later, with equal finalist budgets,
fresh audit data, explicit scenario laws and no worst-case guarantee.

## 3. Compare horizon policies later using the same multi-horizon network

```text
After multi-horizon learning, compare the initial fixed-deadline policy against:
(a) argmax_a V(post(s,a),T), keeping T constant at every decision, and
(b) argmax_(a,h) V(post(s,a),h)/h over positive supported horizons, investigating
minimum absolute utility and raw versus incremental growth in that later study.
Use the same frozen checkpoint first, matched held-out starts/seeds and a common
real scoring window. Resetting a planning horizon must not extend that window.
A changed policy does not automatically inherit value calibration; measure actual
performance and record continuation identity, support and end-of-data handling.
Do not implement or tune these later policies in the initial learning task.
```

The UI plan and project status now reflect this separation. No model, training
result, deployment or implementation changed in this documentation update.
