# Latest prompt changes — 28 October 2026

These clarifications are relative to `d1d0db2777f7caad0cd04838ee940630d9685f1c`.
[Full standalone prompt](TREASURY_LEARNING_NEXT_PROMPT.md).
[Complete strategy definitions](ROLLOUT_MAXMIN_SPEC.md).
Future-trade liquidation, ignored closing duration, fixed-deadline learning and
later horizon-policy comparisons remain unchanged.

## 1. Clarify feasible joint worst cases

```text
Adverse prices for different legs are allowed together when one feasible joint
execution scenario permits them. Only incompatible cross-scenario combinations
are prohibited; different legs need not close at the same timestamp.
```

Example: if the only allowed joint sell-price scenarios are (90,110) and (110,90),
both yield 200 for one unit of each instrument. Combining their independent minima
as (90,90) invents an outcome outside that set. If the execution model permits both
90 fills together, that joint scenario belongs in the set and may be the worst case.

## 2. Reserve label-data buffers after decision windows

```text
Declare a decision/evaluation window and a longer label-data window for each split.
Reserve a closing-data buffer after the last strategic endpoint, with the next
split beginning after that allocation. For tail cap B and data end E, supported
pairs satisfy a bound such as anchor_time+H+B<=E, with verified instrument coverage.
Even H=0 can lack a label at the raw-data end when positions need future closes.
Mark unsupported/right-censored labels explicitly; never substitute zero utility.
Publish buffers, horizon masks and incomplete counts. Settled USD/BTC-only states
may have a direct zero-horizon label without future trades.
```

Ignoring liquidation time in utility does not create missing tail data. Buffers
are data/runtime bounds, not objective penalties. Do not retain only successful
closing paths or use another held-out allocation to finish training labels.

## 3. Branch several horizons from the same sampled training state

```text
At selected outer-trajectory collection timestamps, evaluate several H_i from the
SAME candidate post-state x, producing (x,H_i,max_j min_k G[i,j,k]). Clone simulator
state/queues/clock/RNG without mutating the parent or leaking hidden state. Give
each branch deadline anchor_time+H_i, retaining the original economic benchmark.
Budget all horizons together, roughly J*K*sum_i L_i decision steps plus other costs.
Inner subtrajectory decisions use only network evaluations; no recursive branching.
A long trajectory's prefixes are not automatically shorter-horizon policy targets.
```

This makes the existing multi-horizon intention explicit. The new max–min collector
has not been implemented; the earlier Treasury run used an initial action and hold.

## 4. Explicitly reuse the existing event-based decision clock

```text
Use DecisionSchedule event mode for the new repeated-decision collector, retaining
fixed cadence as an explicit control. The existing pilot already supports event
mode, though its CLI default remains fixed. Default triggers include 2 bp received
price/index/premium changes, received order/ledger reports, known dates, a 100-ms
minimum gap and a 30-second heartbeat. Process all exchange events exactly; hidden
future events cannot trigger a policy decision before becoming observable.
Record clock settings/anchors/reasons and use them inside subtrajectories. Sparse
Treasury fixtures may explicitly configure a coarser heartbeat within the budget.
```

Nine existing clock regression tests passed in this documentation turn. No training,
new collector implementation or deployment was launched.
