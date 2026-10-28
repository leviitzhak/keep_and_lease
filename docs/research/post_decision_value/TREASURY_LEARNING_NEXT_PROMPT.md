# Next thread: Treasury learning with sampled max–min rollout labels

Rewritten 28 October 2026. Design only; no new learning run or UI implementation.
[Changes only](TREASURY_PROMPT_CHANGES.md). [Full definitions](ROLLOUT_MAXMIN_SPEC.md).

```text
Continue the Treasury-learning sanity check in keep_and_lease. Implement bounded
value-only learning, independent reference values and static plots. Do not build
its UI, a broad market simulator or long-history training infrastructure yet.

Repository: https://github.com/leviitzhak/keep_and_lease
Branch: agent/btc-post-decision-value-v1
Latest known implementation commit: 968f1afb47d603b3ee53dc2b0f586e423a174ce1
Later commits update the design. Fetch/inspect the current remote branch and
preserve all subsequent work. Read AGENTS.md and:
- docs/research/post_decision_value/ROLLOUT_MAXMIN_SPEC.md (current strategy)
- TREASURY_SANITY.md, TREASURY_PROMPT_CHANGES.md, WEIGHTED_EVENT_TRAINING_PLAN.md
  and STATE_VALUE_EXPLORER_PLAN.md in that same directory
- research/post_decision_value/{treasury_sanity,model,pilot,accounting,engine}.py
  and the corresponding tests.

CONTEXT
The previous 88,901-parameter model missed all 16 profitable held-out Treasury
cases and all 32 profitable training cases. Its 1,200 updates took 18 seconds on
one CPU thread; 89.7% of final hidden Tanh activations were saturated. That is a
diagnostic, not a proven cause. 211 software tests passed, but learning failed.
Prior artifacts: docs/research/post_decision_value/treasury-sanity-v1.tar.gz.
Old expected-continuation labels/checkpoints do not implement the new target below.

1. DIAGNOSE ON A SMALL ECONOMY
Start with one Treasury, a short maturity such as 28 days, short observable
history and small native quantity/price and positive horizon grids. Distinguish
history lookback, financial horizon and dataset date span. Retain maturity tails.
Verify accounting/boundary labels, then overfit a tiny training-only set containing
profitable, overpriced, fee-erased and cash-constrained cases. A one-purchase/hold
regression is Stage A only. Stage B must permit repeated network decisions.
Inspect feature/time scales, gradients, saturation, label scaling and loss balance.
Use a small MLP ablation if useful; do not replace learned choices with an oracle.

2. VALUE AND ACTION SELECTION
Learn one scalar decision function V(post_state,h). The post-state includes the
submitted instruction immediately, before any arrival/fill. At each decision
search (action,horizon) pairs and choose the greatest V(post(s,a),h)/h, subject
to admissibility, h>=h_min>0 and V>=v_min. Include wait, deterministic ties and a
wait fallback; required safety cancellation must not depend on a profit threshold.
Use documented physical time units and no compounding of utility. Inside a rollout
h cannot exceed remaining time and the outer deadline must never move forward.
Keep the requested literal raw V/h rule. The current utility is relative to
original episode holdings: document that past gains can favor tiny horizons.
Show wait/incremental-value comparisons and test this artifact; do not silently
change the user's rule. Baseline choice is explicitly noted in the specification.
Keep weights BTC/USD=.5/.5, loss penalty lambda=10 and existing failure penalties,
financing constraints and initial-holding floors. No actor or MCTS is required.

3. TERMINAL-ONLY ROLLOUT TARGET
For each sampled post-state and outer horizon, freeze the network and settings.
Propose J causal candidate continuation controllers using network decisions plus
reproducible exploration. Hold each candidate's action/exploration rule fixed
across K uncertainty replicas; vary specified execution/market uncertainty with
separate seeds. Each replica reacts to its own received observations. Use matched
scenario sets across candidates. Do not replay future-dependent order scripts.
Inside subtrajectories use network evaluations only for decisions; no nested
rollouts. At remaining time zero compute terminal liquidation utility G[j,k].
Define R[j]=min_k G[j,k], then training target y=max_j R[j]. Do not maximize over
intermediate values, include the old prediction in y, or discard negative paths.
The target must permit downward corrections. Record all terminal results, the
winning controller and worst joint-utility replica. Never independently minimize
BTC/USD heads or combine incompatible scenario holdings.
This is a sampled conservative search statistic, not expected utility or a
certified worst-case guarantee. Version J,K, scenario law, policy/exploration,
horizons, thresholds, marking mode and benchmark. Keep budgets fixed in comparisons,
reevaluate selected candidates on independent seeds, and report mean/minimum/tails
and failures without silently changing the max–min training objective.
Fit, recollect and evaluate in a bounded cycle. Distinguish search-generated target
from what the network-only policy actually achieves on fresh trajectories.

4. INDEPENDENT LIQUIDATION BOUNDARY
For now calculate L_mark directly on a copy of the terminal state: atomically
cancel outstanding/in-flight instructions, release reservations, retain USD/BTC
(or configured base proxy), and close other instruments at contemporaneous market
marks with native P&L, configured close fees, collateral release and net liabilities.
Record mark source/time/age; no future favorable prices, invented quotes/depth,
double-counted receipts or forgiven debt. Missing marks must be explicit failures
or excluded/incomplete cases, not fabricated values. Start with debt-free fixtures.
This idealized terminal mark/cancellation is a valuation proxy, not observed
execution. It does not change real delays or cancellation races during the rollout.
Use L_mark as independent labels for V(state,0); future-value predictions must not
supply boundary targets. Separately learned liquidation/realistic unwind is later.
Carry path failures through the terminal score. Do not auto-convert USD into BTC:
after a spot sale and future closing, the policy must explicitly repurchase BTC
through an admissible funded spot action. A finite loss penalty is not a guarantee
that both commodity growths are nonnegative; report them individually.

5. EXACT REFERENCES, EVALUATION AND PLOTS
Implement an independent reference for the tiny finite toy, under identical
valuation, actions/horizons, information and max–min scenario definitions.
Separate exact terminal marking, the sampled-search target, the full declared-toy
optimum, and realized policy performance. Enumerate causal controllers or justify
the recursion; a minimum at every stage may not equal minimum over fixed full paths.
Compare learned values to the MATCHING reference, not an expected-value reference
for a robust head. Provide exact values only within supported states.
Use the previously examined test cases as development data. Freeze fresh test
cases and group all candidates/replicas of a case into one split. Predeclare
acceptance gates for profitable buys, avoiding bad buys, quantities, constraints,
prediction errors and robust search/policy gaps. Evaluate final test once after
validation selection. No oracle/future-tape search may choose held-out policy actions.
Training labels can use future training tape; call them tape-conditioned search
labels. Execution reseeding on one tape does not sample market movements.
Plot train/validation loss and reference-error curves, price/quantity/horizon
surfaces, predicted-vs-reference scatter and worst errors. Show generated data
and a few trajectories with decisions, posted orders, arrivals, fills, cash,
inventory and maturity receipts; distinguish observed and hidden events.
Compare cash hold, analytical bill hold, network-only policy, sampled search and
toy optimum with matching budgets/conventions. Show proxy liquidation labels.
Test controlled +1/-1 actions versus stochastic outcomes, sample minima, stable
controller identity, independent reevaluation, terminal marking/cancellation,
spot repurchase, causality, fees and checkpoint restoration. Failure is a result.

6. COMPUTE AND DURABLE ARTIFACTS
Run bounded training in the available environment and report actual host, CPU/GPU,
threads, memory and wall/CPU time. Previous training ran in ChatGPT's Linux workspace,
not the user's Windows computer or a GCP training service. Scratch is not durable.
Its old working directory was /workspace/scratch/54b859a43021/treasury-sanity-v1;
retrieve the committed archive when absent. Preserve configs, seeds, source/data
identities, target matrices, reference values, plots and checkpoints/optimizer/RNG.
Publish a small immutable inference bundle and manifest with real download URL,
SHA256/size, feature/scaling/model versions, target semantics, J/K/scenario identity,
objective/benchmark, horizons/thresholds, marking mode, acceptance status and examples.
Verify loading/downloading via existing artifact infrastructure. Do not provision
storage or invent GCS URLs. The later local UI consumes this bundle, without training.

7. DEFERRED WORK, DOCUMENTATION ONLY
Keep the UI in STATE_VALUE_EXPLORER_PLAN.md as a separate later implementation:
localhost Python inference/browser, Windows setup/launch, date/instrument/trades,
portfolio/order editor, checkpoint downloads and matching learned/reference/error
views. Update its schema/reference interface, but implement no UI in this task.
Document a later broad synthetic market generator for economic carry/spread
opportunities across rising/falling/flat spot, premium, rates, liquidity and funding
regimes. Preserve cashflow identities and causality, train-only calibration and
no-opportunity controls. Only tiny explicit Treasury fixtures are required now;
market-independent profitability is a hypothesis to test, not a guarantee.

LIMITS AND DELIVERY
Set an aggregate J*K rollout/fitting budget and obey stricter existing runtime
limits; no recursive or large unattended search. Preserve unrelated work, update
docs, and commit/push the research branch only after verifying deployment exclusion.
No master merge, deployment, live orders, data purchases/bulk downloads, new
infrastructure, broad simulator or years-long training. Return diagnosis, changes,
software/learning results, plots, exact-reference scope, actual compute location,
reproduction commands, downloadable artifacts, branch/full commit and limitations.
```
