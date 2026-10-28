# Treasury value learning — implementation plan

28 October 2026. **Implementation delivered; bounded campaign capped during collection.**
This remains the canonical implementation contract. See [actual stage results](TREASURY_MAXMIN_RESULTS.md):
the hold/boundary diagnostic passed, but repeated collection exhausted 20,000
decisions through cancel/repost churn. No robust refit or fresh test evaluation
was performed. The remaining unchecked campaign steps are blocked, not complete.

Deliver a bounded Treasury-learning experiment with a scalar value function,
independent reference values, static data/learning plots and downloadable artifacts.
The [strategy specification](ROLLOUT_MAXMIN_SPEC.md) defines the economic semantics;
this plan defines implementation order, verification gates and delivery. Keep both
consistent. The [UI plan](STATE_VALUE_EXPLORER_PLAN.md) remains a separate later task.

- Repository: [leviitzhak/keep_and_lease](https://github.com/leviitzhak/keep_and_lease)
- Branch: `agent/btc-post-decision-value-v1`
- Pre-task implementation baseline: `968f1afb47d603b3ee53dc2b0f586e423a174ce1`

Later commits update the design. Fetch/inspect the current remote branch and
preserve all subsequent work. Read AGENTS.md and:

- docs/research/post_decision_value/ROLLOUT_MAXMIN_SPEC.md (current strategy)
- TREASURY_SANITY.md, TREASURY_PROMPT_CHANGES.md, WEIGHTED_EVENT_TRAINING_PLAN.md
  and STATE_VALUE_EXPLORER_PLAN.md in that same directory
- research/post_decision_value/{treasury_sanity,model,pilot,accounting,engine,decision_clock}.py
  and the corresponding tests.

## Existing evidence

The previous 88,901-parameter model missed all 16 profitable held-out Treasury
cases and all 32 profitable training cases. Its 1,200 updates took 18 seconds on
one CPU thread; 89.7% of final hidden Tanh activations were saturated. That is a
diagnostic, not a proven cause. 211 software tests passed, but learning failed.
Prior artifacts: [treasury-sanity-v1.tar.gz](treasury-sanity-v1.tar.gz).
Old expected-continuation labels/checkpoints do not implement the new target below.

The optional event clock already exists in the pilot. Its nine focused tests passed
in the preceding documentation turn; those and the old 211-test result do not
validate the proposed collector. No fitted max–min checkpoint exists: the delivered checkpoint is explicitly diagnostic-hold-boundary-v1. The collector and references now exist; see the delivered results.

## Implementation sequence

| Stage | Deliverable | Completion gate |
| --- | --- | --- |
| 0. Freeze experiment | Versioned config, budgets, splits and acceptance rules | Recorded before fitting or fresh-test inspection |
| 1. Establish labels | Treasury fixtures and future-trade liquidation calculator | Independent accounting, causal inputs and supported tails |
| 2. Diagnose learning | Boundary/hold-only overfit and model diagnosis | Tiny controls learned or a specific documented failure |
| 3. Implement collection | Event-driven multi-horizon max–min collector | Isolated branches, reproducible targets and bounded work |
| 4. Build references | Tiny causal oracle, evaluation harness and plots | References match target semantics and declared scope |
| 5. Run bounded cycle | Collect–fit–improve–evaluate results | Frozen validation selection and one fresh held-out evaluation |
| 6. Publish artifacts | Bundle, manifest, report and reproduction commands | Verified restoration/download and research-only push |

Implement in this order. Stages 3–4 may be developed after label verification while
Stage 2 is diagnosed, but do not launch the full cycle with unexplained basic
regression failure. Failure is a result, not permission for an unbounded retry.

## Strategy contract

Learn one scalar decision function V(post_state,h). The post-state includes the
submitted instruction immediately, before any arrival/fill. For the initial
learner, fix each rollout's terminal deadline and choose the admissible action
maximizing V(post(s,a),r), where r is its remaining physical time. Decrease r by
elapsed time; never move the deadline. Allow exploration during collection and
include wait, deterministic ties and mandatory safety responses. At r=0 use the
liquidation boundary. Learn across several initial horizons, with each rollout
counting down independently. Constant-lookahead T and max_h V/h are later policy
experiments, not the initial rule; neither their thresholds nor tuning is required.
Keep weights BTC/USD=.5/.5, loss penalty lambda=10 and existing failure penalties,
financing constraints and initial-holding floors. No actor or MCTS is required.

Use the existing DecisionSchedule event mode for repeated-decision rollouts, keeping
fixed cadence as an explicit control. The existing pilot already supports this
option; its CLI default is still fixed cadence. Existing event defaults: 2 bp
received price/index/premium change, received order/ledger reports, known cashflow/
goal dates, 100-ms minimum gap and 30-second heartbeat. Trigger only on observable
information/known dates; process all exchange events exactly. Record clock settings,
anchors, reasons and counts; use the same mechanism inside subtrajectories. Sparse
Treasury fixtures may explicitly configure a coarser heartbeat within the runtime
budget. Physical remaining time counts down even without a policy wakeup.

## Stage 0 — freeze scope, configuration and budgets

- [x] Fetch the current research branch, read AGENTS.md, preserve unrelated work
  and verify deployment exclusion. The implementation SHA above is a baseline,
  not a request to reset the branch to an earlier revision.
- [x] Recover the old archive if needed; inspect encoders/model, accounting,
  replay, action search, clock, checkpoints and existing artifact infrastructure.
  Record source hashes, actual host, CPU/GPU, thread count and RAM.
- [x] Save a versioned configuration for fixtures, seeds/splits, initial holdings,
  floors, utility, actions, horizons, J/K, exploration, clock, liquidation rule,
  tail caps/buffers, horizon support and all runtime limits. Previously inspected
  test cases become development data; reserve fresh test cases.
- [x] Freeze numeric error tolerances, ranking/tie margins, quantity/constraint
  gates and policy/search acceptance thresholds before fitting or inspecting the
  fresh test set. Do not weaken thresholds after seeing results.
- [x] Cap the first learning campaign at **240 seconds total wall time, 120 seconds
  fitting, 1,200 cumulative optimizer updates and one Torch/BLAS thread**, matching
  the stricter prior Treasury sanity limits. Count diagnoses/ablations, all collection
  branches, refits and evaluation against the shared budget; do not reset per stage.
  Any stricter applicable harness limit wins. These are caps, not a throughput claim.
  They bound executed experiment work, not coding or review time.
- [x] Also retain project ceilings of 20,000 decisions, 30,000 exchange/report events
  per replay, 100,000 input rows and 8 MB compressed input. Bound oracle enumeration
  separately inside the overall budget. Reduce fixtures/grids or stop and checkpoint
  when capped; count liquidation tails and every horizon/controller/scenario branch.

The broader project limits (3,600 seconds/run, 1,200 fitting seconds, 2,000 updates)
do not override the smaller initial-campaign caps. No bulk downloads, purchases,
provisioning, cloud job launch, prolonged polling or unattended training is required.
When access fails, identify the exact blocker and retain explicitly synthetic results.

## Stage 1 — fixtures, split tails and independent liquidation

Calculate L_trade from simulated liquidation on a copy of the terminal state,
using SUBSEQUENT trades sequentially under a fixed declared closing/fill rule.
Keep idealized atomic cancellation of outstanding/in-flight instructions explicit,
release reservations and retain USD/BTC (or configured base proxy). Close other
inventory with native P&L, fees, collateral and net obligations; record trade IDs,
timestamps, source, eligibility and quantity/participation assumptions. No invented
quotes/depth, double-counted receipts or forgiven debt. Start with debt-free fixtures.
Future trades may provide supervised labels; do not expose them to current features
or the policy. This is simulated execution, not proof of executable liquidity.
Ignore liquidation duration in the score: no extension of T, duration discount,
time penalty or rate-denominator adjustment. Keep timestamps for event ordering,
dated accounting and split integrity; never resume strategy trading during closing.
Use the minimum joint liquidation outcome across the same K complete scenarios.
At T=0 the boundary target is min_k L_trade(state,scenario_k), with no strategy
search; deterministic inputs give one outcome. A worst case is one feasible whole
closing sequence, not independent worst prices across legs or arbitrary future prints.
Adverse prices for different legs are allowed together when one feasible joint
execution scenario permits them; only incompatible cross-scenario combinations
are prohibited. The specification gives a two-leg numerical example.
Bound tail scans; all closing data must remain within the assigned split. Missing
tail data/incomplete liquidation must be explicit, never replaced by convenient
marks or omitted adverse cases. Test future-label dependence without feature leakage.
Declare a decision/evaluation window and a longer label-data window for each split,
reserving a closing buffer after the last strategic endpoint. The next split starts
after that allocated buffer. For tail cap B and data end E, only request supported
pairs such as anchor_time+H+B<=E, with verified coverage. Near the raw data end even
H=0 may lack a closing label; mark it unsupported/right-censored, never zero utility.
Settled USD/BTC-only states need no closing trades. Publish buffer boundaries,
per-horizon masks and incomplete counts; do not filter away adverse incomplete paths.
Missing tails prevent reference labels, not querying a trained V(state,0) on
otherwise supported inputs. Distinguish unavailable ground truth from inference.
The network's OWN future-value predictions must not supply boundary ground truth;
this restriction does NOT prohibit future trades. Separately learning liquidation
value/time and using those estimates in decisions is later work. Ordinary rollout
execution delays and cancellation races remain unchanged.
Carry path failures through the terminal score. Do not auto-convert USD into BTC:
after a spot sale and future closing, the policy must explicitly repurchase BTC
through an admissible funded spot action. A finite loss penalty is not a guarantee
that both commodity growths are nonnegative; report them individually.

**Deliverables and gate:** implement the small fixture generator, independent
liquidation calculator, split/buffer manifests and per-horizon support masks.
Check native P&L, fees, partial fills, cancellation, cashflows/redemption, incomplete
tails and liabilities against independent accounting. Include a bounded accounting
fixture for explicit BTC repurchase after a spot-funded futures sequence; this does
not require a new multi-asset training campaign. Never count a sale and redemption
twice, or mix unavailable future information into current features.

## Stage 2 — diagnose boundary and hold-to-maturity learning

Start with one Treasury, a short maturity such as 28 days, short observable
history and small native quantity/price and positive horizon grids. Distinguish
history lookback, financial horizon and dataset date span. Retain maturity tails.
Verify accounting/boundary labels, then overfit a tiny training-only set containing
profitable, overpriced, fee-erased and cash-constrained cases. A one-purchase/hold
regression is Stage A only. Stage B must permit repeated network decisions.
Inspect feature/time scales, gradients, saturation, label scaling and loss balance.
Use a small MLP ablation if useful; do not replace learned choices with an oracle.

**Gate:** independently calculated labels agree within frozen numeric tolerances.
Require declared profitable-versus-wait rankings on deterministic tiny controls,
avoid strictly loss-making buys and select no inadmissible action. Record ties and
constrained cases separately. Report architecture/parameter count, feature/label
scales, loss components, gradients and activation saturation. If a simple training
case cannot be learned, preserve the failure and diagnose it within the same budget.
The hold-to-maturity regression is a training diagnostic, not the final strategy.

## Stage 3 — implement the multi-horizon collector

At each selected outer-trajectory collection timestamp, evaluate several configured
horizons H_i from the SAME candidate post-state x. Clone queues/clock/RNG without
mutating the parent or exposing hidden state to features. Produce separate samples
(x,H_i,y_i), with y_i=max_j min_k G[i,j,k]. H=0 uses the closing boundary directly.
Set each branch deadline to anchor_time+H_i, retaining the original benchmark and
economic constraints; do not reset accumulated growth when changing the horizon.
Record anchor subsampling, horizon grids and support masks. Budget the total over
all horizons, roughly J*K*sum_i L_i decision steps per anchor plus other costs.
This is offline label generation, not future-tape search at held-out policy decisions.
Inner subtrajectory decisions use the network only; do not recursively branch.
Different horizons can induce different actions, so one long trajectory truncated
at several times does not automatically supply these horizon-specific targets.
For each sampled post-state and outer horizon, freeze the network and settings.
Propose J causal candidate continuation controllers using network decisions plus
reproducible exploration. Hold each candidate's action/exploration rule fixed
across K uncertainty replicas; vary specified execution/market uncertainty with
separate seeds. Each replica reacts to its own received observations. Use matched
scenario sets across candidates. Do not replay future-dependent order scripts.
Sample complete paths: draw one next uncertainty outcome per step, reach the
endpoint and repeat K times. Do not branch into K children at every node. Keep K
equal across compared candidates; budget roughly J*K*L decision steps for L-step
paths plus action-grid inference and event processing. Exact worst-case enumeration
is only for tiny reference fixtures. Retain a fresh independent winner audit set;
targeted stress and adaptive screening are optional later enhancements, not exact
worst-case guarantees. Preserve temporal dependence and declared scenario laws.
Inside subtrajectories use network evaluations only for decisions; no nested
rollouts. At remaining strategic time zero simulate closing against subsequent
trades sequentially, then compute liquidation utility G[j,k]. Ignore closing
duration in T and the objective; the sampled path includes this closing tail.
Define R[j]=min_k G[j,k], then training target y=max_j R[j]. Do not maximize over
intermediate values, include the old prediction in y, or discard negative paths.
The target must permit downward corrections. Record all terminal results, the
winning controller and worst joint-utility replica. Never independently minimize
BTC/USD heads or combine incompatible scenario holdings.
This is a sampled conservative search statistic, not expected utility or a
certified worst-case guarantee. Version J,K, scenario law, policy/exploration,
horizons, liquidation mode and benchmark. Keep budgets fixed in comparisons,
reevaluate selected candidates on independent seeds, and report mean/minimum/tails
and failures without silently changing the max–min training objective.
Fit, recollect and evaluate in a bounded cycle. Distinguish search-generated target
from what the network-only policy actually achieves on fresh trajectories.

**Gate:** verify parent state/queue/RNG isolation, several horizons from the same
state, unchanged economic benchmarks, stable controller identity, equal scenario
budgets, observable-only wakeups, physical-time countdown, endpoint-only labels,
downward learning corrections and budget truncation. Save every outcome matrix,
winning controller and coherent worst joint scenario. Incomplete work is never a
completed label. Version the new label/model semantics separately from old artifacts.

## Stage 4 — independent references, evaluation and plots

Implement an independent reference for the tiny finite toy, under identical
valuation, actions/horizons, information and max–min scenario definitions.
Separate calculated liquidation outcomes, the sampled-search target, the full declared-toy
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
toy optimum with matching budgets/conventions. Show future-trade liquidation labels.
Test controlled +1/-1 actions versus stochastic outcomes, sample minima, stable
controller identity, independent reevaluation, sequential liquidation/cancellation,
ignored tail duration, split-contained tails, spot repurchase, causality, fees,
horizon countdown and checkpoint restoration.
Failure is a result. No exponential-tree exact search for long trajectories.

**Gate:** accounting, causality, execution, constraint, split-support and restoration
checks pass. The tiny oracle independently matches supported sampled-search labels;
record its finite action/information/scenario scope and enumeration cap. No exact
claims outside support. Learning acceptance is distinct from software correctness:
report profitable buys, avoidance of overpriced/fee-erased purchases, quantities,
constraint failures, prediction errors and search/executed-policy gaps against
Stage 0 gates. Positive scalar utility alone does not prove both growths are positive.

## Stage 5 — run one bounded collect–fit–improve–evaluate cycle

- [ ] Freeze the diagnosed starting controller and collect complete outcome labels
  with all scenario, horizon, policy and source identities recorded.
- [ ] Fit with training-only normalization and validation checkpoint selection.
  Plot train/validation loss and matching-reference errors against updates; do not
  monitor fresh test loss during training or model selection.
- [ ] Freeze the improved model, recollect under its exploratory continuation and
  refit once within the shared budget. Preserve each dataset/controller identity;
  never silently mix old expected-value labels with the new max–min targets.
- [ ] Compare cash hold, analytical Treasury hold, network-only execution, sampled
  search and supported finite-toy optimum on matched cases and conventions.
  Independently reevaluate selected controllers on fresh uncertainty seeds.
- [ ] Evaluate the final validation-selected policy once on fresh held-out cases.
  Report category choices, both commodity growths, utility, failures, mean/minimum/
  tails, turnover, costs, errors, policy/search gaps and actual wall/CPU resources.
  No search through future test tape may choose its actions.
- [ ] Plot generated data and replay a few trajectories with posted orders, arrivals,
  fills, received/hidden events, inventory/cash, maturity receipts and separate
  subsequent-trade closing tails. Publish the failed cases as well as successes.

Stop on budget, missing data or failed gates and retain diagnostics/checkpoints.
Do not expand to long history or repeatedly inspect fresh tests to hide a failed
sanity check. Further runs require a separately stated bounded scope; this plan
does not authorize an open-ended training campaign.

## Stage 6 — durable artifacts and delivery

Run bounded training in the available environment and report actual host, CPU/GPU,
threads, memory and wall/CPU time. Previous training ran in ChatGPT's Linux workspace,
not the user's Windows computer or a GCP training service. Scratch is not durable.
Its old working directory was /workspace/scratch/54b859a43021/treasury-sanity-v1;
retrieve the committed archive when absent. Preserve configs, seeds, source/data
identities, target matrices, reference values, plots and checkpoints/optimizer/RNG.
Publish a small immutable inference bundle and manifest with real download URL,
SHA256/size, feature/scaling/model versions, target semantics, J/K/scenario identity,
objective/benchmark, horizons/continuation rule, liquidation rule/tail data references,
duration-ignored flag, acceptance status and
examples. Later policies must also record any ratio thresholds.
Verify loading/downloading via existing artifact infrastructure. Do not provision
storage or invent GCS URLs. The later local UI consumes this bundle, without training.

**Gate:** publish configs, source/data identities, split and horizon masks, full
outcome matrices, reference values, checkpoints/optimizer/RNG, static plots, replay
traces and machine-readable acceptance results. Download one real bundle, verify
its checksum, restore it and reproduce inference/reference examples. Failed models
retain visible failed status. The later local UI consumes the bundle without training.

Supply exact config-driven collection/training/evaluation and plot-reproduction
commands once implemented. Do not describe a proposed CLI as already available.
Delivered CLI: `python -m research.post_decision_value.treasury_learning {run,verify,plots}` with `--output`, and `--config` for a new run. Exact commands and artifact restoration are in [the results](TREASURY_MAXMIN_RESULTS.md). Existing baseline checks include:

```bash
python -m unittest tests.post_decision_value.test_weighted_clock -v
python -m unittest tests.post_decision_value.test_treasury_sanity -v
```

These existing suites do not validate the new collector. Add focused semantic
checks and run affected accounting/engine suites; report commands, counts and failures.

## Implementation locations

These are existing integration points. Add new modules/tests only where needed;
list their actual names in the delivery report rather than assuming they exist now.

| Area | Responsibility |
| --- | --- |
| `research/post_decision_value/treasury_sanity.py` | Small fixtures, learning diagnosis and bounded runner integration |
| `research/post_decision_value/accounting.py`, `engine.py` | Native ledgers, isolated branches, event replay and closing outcomes |
| `research/post_decision_value/model.py` | Scalar predictions, feature/label scales, fitting and model identity |
| `research/post_decision_value/pilot.py` | Collection/evaluation integration and continuation metadata |
| `research/post_decision_value/decision_clock.py` | Reuse observable-state triggers and checkpointed clock anchors |
| `tests/post_decision_value/` | Focused accounting, causality, labels, horizons and restoration checks |
| `docs/research/post_decision_value/` | Config/report references, plots, small durable bundles and follow-up plans |

Preserve legacy checkpoint behavior and semantics. A new config/schema identifies
new target semantics rather than silently relabeling old checkpoints.

## Deferred implementations

After multi-horizon learning, compare the initial fixed-deadline policy against:
(a) argmax_a V(post(s,a),T), keeping T constant at every decision, and
(b) argmax_(a,h) V(post(s,a),h)/h over positive supported horizons, investigating
the minimum absolute utility threshold and raw versus incremental growth then.
Use the same frozen checkpoint first; compare attained performance on matched
held-out starts/seeds, common strategic scoring windows and terminal conventions.
Rolling planning deadlines must not extend the strategic period. Subsequent closing
tails follow the common duration-ignored rule and stay inside the split. A changed policy
does not automatically inherit value calibration; record its continuation identity,
data/horizon support and end-of-data handling. Do not implement/tune these policy
experiments during the initial learning task.
Keep the UI in STATE_VALUE_EXPLORER_PLAN.md as a separate later implementation:
localhost Python inference/browser, Windows setup/launch, date/instrument/trades,
portfolio/order editor, checkpoint downloads and matching learned/reference/error
views. Update its schema/reference interface, but implement no UI in this task.
Document a later broad synthetic market generator for economic carry/spread
opportunities across rising/falling/flat spot, premium, rates, liquidity and funding
regimes. Preserve cashflow identities and causality, train-only calibration and
no-opportunity controls. Only tiny explicit Treasury fixtures are required now;
market-independent profitability is a hypothesis to test, not a guarantee.

## Completion and publication

- [x] Every stage has an implemented/failed/blocked status in TREASURY_MAXMIN_RESULTS.md.
- [x] Distinguish software correctness, learning acceptance, synthetic experiments,
  any actual historical results and remaining access/data limitations.
- [ ] Reports contain exact reproduction commands and verified artifact URLs/hashes.
- [x] Update the strategy specification, project status, TODO and explorer interface
  documentation to match the delivered implementation.
- [ ] Push only the research branch with `[skip ci]` after checking deployment
  exclusion. Record branch/full SHA; no merge, deployment or live trading.

Set an aggregate J*K rollout/fitting budget and obey stricter existing runtime
limits; no recursive or large unattended search. Preserve unrelated work, update
docs, and commit/push the research branch only after verifying deployment exclusion.
No master merge, deployment, live orders, data purchases/bulk downloads, new
infrastructure, horizon-policy comparison, broad simulator or years-long training.
Return diagnosis, changes, software/learning results, plots, exact-reference scope,
actual compute location,
reproduction commands, downloadable artifacts, branch/full commit and limitations.
