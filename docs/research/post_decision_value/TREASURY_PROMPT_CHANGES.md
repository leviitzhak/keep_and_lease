# Changed passages only

27 October 2026. These passages replace/add to the previous combined learning/UI
prompt. The complete standalone rewrite is
[TREASURY_LEARNING_NEXT_PROMPT.md](TREASURY_LEARNING_NEXT_PROMPT.md).

## Task scope replacement

```text
Focus this task on Treasury learning, exact reference values, static diagnostic
plots and downloadable artifacts. Do not implement the UI yet. Record the UI
and Windows packaging as the separate next implementation in
docs/research/post_decision_value/STATE_VALUE_EXPLORER_PLAN.md.
```

## Continuation replacement

```text
Hold-to-maturity after the initial instruction is only Stage A's regression
diagnostic, not a restriction on the intended strategy. In Stage B, repeatedly
apply the frozen network at future decision times to choose new post-states,
allowing creation, amendments, cancellation and waiting through maturity.

All output heads must describe the same future policy and trajectory distribution.
Freeze model/search/clock/exploration settings for each collection stage. Fit to
complete outcomes, improve the policy and recollect within a bounded cycle.
Distinguish exploratory behavior from greedy evaluation. A model fitted to the
previous policy is not automatically calibrated for its newly improved policy.
```

## Exact-value addition

```text
Implement an independent reference evaluator for the small synthetic model.
Separate exact same-policy value V_pi, optimal attainable value V_star, and one
realized trajectory outcome.

First verify the closed-form one-purchase/hold case. With cash C, n existing units,
face R and q additional units filled at P, terminal USD is
C + n*R + q*(R-P) - fees(q,P), assuming maturity within the horizon and no other
flows. Pending/unfilled orders require separate branches.

Then use a tiny finite multi-decision model: enumerate V_pi and compute V_star
by backward induction under the same observable information, action grid and
constraints. Do not give the oracle hindsight or hidden exchange information.
Exactly average finite stochastic branches; label Monte Carlo estimates and
uncertainty honestly if exact enumeration is unavailable. Define supported states.
Optimal commodity values must follow one jointly optimal policy and tie-break.

Retain complete-outcome training. Direct oracle-label fitting may be a separate
diagnostic; the learned strategy must not use the oracle to choose its actions.
```

## Plot additions

```text
Alongside train/validation losses, plot signed/absolute prediction errors versus
exact same-policy utility and terminal holdings on fixed development probes.
Show V_star - V_pi separately as policy regret, not regression error. Include
predicted/reference curves or heatmaps over price and quantity, scatter plots,
worst-error cases and representative decision/fill/cashflow trajectories.
Keep the fresh final test out of per-update diagnostics and checkpoint selection.
```

## Training location and artifact addition

```text
Report the actual training environment and measured resource use. The previous
run trained in ChatGPT's Linux execution workspace, not the user's laptop or a
GCP training service. Scratch is not durable; its committed research archive
contains best-model.pt and last-model.pt with optimizer/RNG and source identity.

Publish a small versioned inference bundle and manifest for the later UI, with
an actual accessible immutable download URL, SHA256/size, model/features/scaling,
objective/continuation, acceptance status, examples and oracle support. Verify
download/load. Use existing artifact infrastructure; do not invent GCS locations,
provision storage or implement the UI/download catalog in this task.
```

## Replacement for immediate UI and localhost implementation sections

```text
Document the explorer as a separate subsequent task. Preserve its requirements:
date/instrument/last-trade view, portfolio and order editing, actual checkpoint
inference, action/value heatmaps, causal seeded replay and Windows localhost
setup/launcher. Add checkpoint selection/download and hash-verified local caching.

For supported synthetic states display learned value, exact same-policy value
and their difference, with optimal attainable value separately. Show unavailable
outside oracle support, or clearly labeled simulation estimates with uncertainty.
Do not treat the previous policy's values as the improved policy's values.
Training remains separate from UI inference. Do not implement the UI this turn.
```
