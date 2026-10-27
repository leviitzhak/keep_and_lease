# Next thread: Treasury learning and exact reference values

Revised 27 October 2026. Planning only; does not change completed results or
implement a new oracle, learner or UI. Copy the following prompt into a new thread.
UI implementation is deferred to [STATE_VALUE_EXPLORER_PLAN.md](STATE_VALUE_EXPLORER_PLAN.md).

```text
Continue the Treasury-learning sanity check in keep_and_lease. Focus on learning,
exact reference values and static diagnostic plots. Do not implement the UI yet.

Repository: https://github.com/leviitzhak/keep_and_lease
Branch: agent/btc-post-decision-value-v1
Latest known implementation commit: 968f1afb47d603b3ee53dc2b0f586e423a174ce1
Fetch/inspect the current remote branch and preserve any subsequent work.

Read AGENTS.md, docs/research/post_decision_value/TREASURY_SANITY.md,
WEIGHTED_EVENT_TRAINING_PLAN.md and STATE_VALUE_EXPLORER_PLAN.md in that same
directory, plus research/post_decision_value/treasury_sanity.py, model.py,
pilot.py and the corresponding tests.

CONTEXT
The previous 88,901-parameter model chose cash in every held-out synthetic case,
missing all 16 profitable bills and all 32 profitable training cases. Its 1,200
updates took about 18 seconds on one CPU thread. About 89.7% of final hidden Tanh
activations were saturated: a diagnostic observation, not a proven cause.
211 software tests passed; this does not establish successful learning.
The prior run is archived at:
docs/research/post_decision_value/treasury-sanity-v1.tar.gz

1. SIMPLE LEARNING DIAGNOSTIC
- Start with one Treasury, a fixed short maturity (e.g. 28 days), short observable
  history and a small explicit quantity/limit-price grid. Distinguish observation
  lookback, financial horizon and dataset date span; state which is shortened.
- Retain full maturity/payment tails and real time units. Label fixtures synthetic.
- Verify labels independently, then overfit a tiny training-only set containing
  profitable, overpriced and fee-erased purchases, plus funded-order constraints.
- Inspect feature/time scales, gradients, Tanh saturation, label normalization,
  loss balance and whether actual order differences survive encoding. Diagnose
  before increasing compute. A small MLP comparison is an optional ablation.
- Fix the learner rather than replacing its decisions with analytical rules.

2. CONTINUATION POLICY AND REPEATED DECISIONS
- A post-decision state includes a proposed instruction immediately, before
  exchange arrival or fills. At later decision times the policy may evaluate
  new post-states again and create, amend, cancel or wait.
- All heads describe the SAME future policy and distribution of trajectories:
  terminal BTC/USD holdings, expected joint utility, failure and attainment.
  Never optimize the commodity heads independently or use utility of average
  holdings instead of average trajectory utility.
- Stage A may restrict continuation to holding after one initial instruction,
  solely to isolate regression/accounting. Label it explicitly as that diagnostic.
- Stage B must permit several future decisions through maturity, using the
  frozen network checkpoint repeatedly for candidate selection. Freeze model,
  search settings, clock and exploration law throughout each collection stage.
- Fit a new value model to complete outcomes of that versioned policy, improve
  the policy and repeat within a bounded collect-fit-improve-evaluate cycle.
  A new greedy policy is not automatically the policy the prior model evaluated.
- Separate exploratory behavior-policy labels from greedy-policy evaluation.
  Record continuation IDs; do not mix targets from different policies silently.
- Keep objective weights BTC/USD=0.5/0.5 and lambda=10 initially, together with
  existing failure penalties, funding constraints and holding floors. Do not
  silently weaken the objective to pass. No actor, MCTS or desired-return input.

3. EXACT REFERENCE VALUES FOR THE SYNTHETIC MODEL
- Implement an independent reference evaluator for a deliberately small,
  specified synthetic economy and bounded action grid.
- Distinguish: (a) exact value V_pi under the frozen continuation; (b) optimal
  attainable scalar value V_star under the same information/actions/constraints;
  (c) one realized trajectory outcome. These are not interchangeable.
- First use the closed-form one-purchase/hold case. With cash C, n existing units,
  face value R and an additional q-unit purchase at P, terminal USD is
  C + n*R + q*(R-P) - fees(q,P), provided it fills and matures before the horizon,
  with no other flows. Check native quantities, available cash and fees explicitly.
  Unfilled/pending orders require their own branches, not assumed full execution.
- Then build a tiny finite multi-decision model. Evaluate V_pi by enumeration
  and V_star by backward induction, with transitions/probabilities stated exactly.
  Match the policy's observable information. Do not let the oracle act on hidden
  fills or the realized future market path unavailable to the policy.
- For random fills/delays, exactly sum a tractable finite distribution; otherwise
  call the result a Monte Carlo estimate and report its sampling uncertainty.
  If simplifying delays for the exact toy, label that variant and separately
  test the production seeded-delay path. Do not silently change execution semantics.
- Optimal commodity holdings must come from ONE policy maximizing the joint
  objective, with an explicit tie-break; no per-commodity optimal portfolios.
- Keep the main targets as complete-outcome regression. Any direct oracle-label
  supervised fit is a separately reported diagnostic, not evidence that the
  rollout-learning cycle works. The learned policy must not call the oracle.
- Define oracle support explicitly. Unsupported states return unavailable;
  never label an approximation, historical hindsight or arbitrary state as exact.

4. EVALUATION AND PLOTS
- Use training/validation for debugging and model selection. Previous examined
  test cases are development data. Freeze fresh test cases before final evaluation;
  group all candidates and delay replicas from a scenario into the same split.
- Predeclare acceptance criteria for profitable buys, avoiding loss-making buys,
  quantity rankings, funded constraints, prediction errors and policy regret.
- Plot training/validation loss during fitting, plus fixed-probe error versus
  exact V_pi for utility and terminal holdings. Measure V_star - V_pi separately
  as policy suboptimality. A gap to V_star alone is not regression error.
- Show predicted/reference curves or heatmaps over price and quantity, predicted
  versus exact scatter plots, and worst-error examples. Evaluate final test once
  after selection; do not use it for per-update training decisions.
- Visualize fixture prices, fees, maturities and quantities, and a few complete
  trajectories with selected actions, order arrivals/fills, cash, inventory and
  maturity receipts. Show native units as well as normalized values.
- Compare cash hold, analytical Treasury buy-and-hold, learned continuation and
  the finite-model optimum under matched conditions. State oracle scope.
- Report failed gates honestly; software tests and falling loss are insufficient.

5. TRAINING LOCATION AND DOWNLOADABLE ARTIFACTS
- Run bounded training in the available execution environment and report the
  actual host type, OS/architecture, CPU/GPU, threads, wall/CPU time and memory.
  Do not call this the user's Windows machine unless actual access is verified.
- The previous run trained in ChatGPT's Linux execution workspace, not the user's
  laptop or a provisioned GCP training service. Its working output was
  /workspace/scratch/54b859a43021/treasury-sanity-v1; this path is not durable or
  guaranteed to exist in the new thread. Retrieve the committed archive if needed.
- Persist run configs, seeds, datasets, source identity, all loss/error curves,
  oracle results, policies, selected/latest checkpoints and optimizer/RNG state
  using existing research artifact infrastructure. Keep execution scratch distinct
  from durable storage.
- Publish a small, versioned inference bundle plus artifact manifest, with actual
  downloadable URL, byte count and SHA256; include checkpoint, model/feature and
  normalization versions, objective/continuation identity, acceptance status,
  example data and oracle support. Use an immutable commit-pinned GitHub artifact
  for these small runs, or existing configured storage with a verified access path.
  Do not invent GCS locations or provision new hosting.
- A resumed optimizer checkpoint may be separate from the inference bundle.
  Verify loading/downloading the published artifact. The future UI will consume
  this bundle; no UI/backend/catalog implementation is part of this task.

6. NEXT STEP: UI, DOCUMENTATION ONLY
- Update STATE_VALUE_EXPLORER_PLAN.md with the final checkpoint/schema/oracle
  interfaces. Keep interactive controls, localhost server, checkpoint download UI
  and Windows setup/launch scripts for a separate implementation task afterward.
- The future explorer must display learned value, exact same-policy reference
  and their difference for supported synthetic states; show optimal attainable
  value separately. It must display unavailable when no valid exact oracle exists.

LIMITS AND DELIVERY
Proceed with bounded implementation and testing. Respect existing limits and
set an aggregate diagnostic budget; do not bypass it through repeated runs.
Preserve unrelated work, update docs, and commit/push the research branch after
checking deployment exclusion. No master merge, deployment, live orders, data
purchases, bulk downloads, provisioning or long unattended training.
Return diagnosis, changes, learning/software results, reference-value and data
plots, reproduction commands, downloadable artifacts, actual compute location,
branch/full commit and remaining limitations. Do not implement the UI this turn.
```
