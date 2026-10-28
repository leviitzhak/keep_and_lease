# State-value explorer: implementation contract and delivery status

Updated 28 October 2026. **Local scalar explorer and optional simulator implemented;
not hosted or deployed.** See [the launch guide and exact delivered scope](STATE_VALUE_EXPLORER.md).
Linux setup and API/inference tests pass. Windows and rendered-browser acceptance
remain unverified: the available cloud browser cannot reach workspace localhost.
Legacy Transformer UI, matching sampled-search references and repeated-replica UI
comparison remain follow-ups. The requirements below describe the full intended
contract, not a claim that every acceptance item is complete. Failed checkpoint
acceptance stays visible. No new training campaign was run for this UI task.

The new [sampled max–min design](ROLLOUT_MAXMIN_SPEC.md) supersedes the earlier
expected-utility-only explorer semantics for future checkpoints. Existing archived
models retain their original semantics. The UI must render the checkpoint's actual
target type rather than silently relabel an old model as conservative.

## Hosting and checkpoint distribution

Use a standalone local Python inference backend and browser UI, separate from the
deployed application. Default address: `http://127.0.0.1:8765`; bind localhost only.
Load the real trained checkpoint; no mock or surrogate predictions. Training is
separate and must never start merely by launching the UI or evaluating a state.

The previous Treasury run executed in ChatGPT's Linux CPU workspace, not the
user's Windows computer or a GCP trainer. Its scratch output was
`/workspace/scratch/54b859a43021/treasury-sanity-v1`. The durable copy is
`docs/research/post_decision_value/treasury-sanity-v1.tar.gz` in research commit
`968f1afb47d603b3ee53dc2b0f586e423a174ce1`, containing `best-model.pt`,
`last-model.pt`, optimizer/RNG state, configurations and exact source snapshot.

Verified repository artifact path:
[previous run archive](https://github.com/leviitzhak/keep_and_lease/blob/968f1afb47d603b3ee53dc2b0f586e423a174ce1/docs/research/post_decision_value/treasury-sanity-v1.tar.gz).
This is the **failed** model, not a new accepted checkpoint. The local UI now offers
a verified download control for the later scalar diagnostic
bundle. This older Transformer remains unsupported by the first UI.

The learning task must publish immutable small inference bundles and a manifest
with URL, hash/size, source identity, model/feature/normalization versions,
objective, continuation policy, supported horizons, training domain, acceptance
result and oracle support. New bundles also identify J/K, uncertainty scenarios,
candidate-controller law, training horizons, countdown rule, growth benchmark and
liquidation rule, complete tail-data identity and duration-ignored flag. Later
policy configurations also declare fixed lookahead or
ratio horizon grids/minima/thresholds. The scalar UI provides a run/checkpoint selector, user-triggered
download, hash verification, bounded archive-member reads/local cache and load-from-file.
Use actual accessible GitHub artifact URLs or an existing verified storage access
path. Do not assume a private GCS URI is a browser-downloadable URL. Bundle an
example model/dataset so offline operation works after setup.

For Windows deliver a setup script checking Python/CPU architecture and creating
an isolated dependency environment, plus `launch_ui.cmd` that starts the backend
and opens the browser. Include stop/error instructions. Test the procedure and
state which OS was actually tested; cloud-workspace localhost is not the user's
machine. Bound historical-data reads rather than loading the full archive.

## Market and state controls

- Dataset, market date/time, checkpoint and supported evaluation horizon.
- Instruments observable at that time: kind, maturity, tick/lot, known receipts,
  recent received trades, last price/quantity, trade time and observation age.
- Last trades are not quotes or guaranteed executable prices. No invented depth.
- Editable BTC/USD balances, instrument inventory, collateral and liabilities;
  preserve the original goal's initial holdings/scales, or explicitly reject
  unsupported goal changes. Include saved example states.
- Multiple limit buys/sells with native price/quantity; working orders and pending
  creations/amendments/cancellations. Use existing engine semantics and show
  admission/rejection reasons. Hypothetical edits never send live orders.

## Predictions, exact references and comparison

Evaluate the immediate post-state before fills. Show the value surface over actions
and supported horizons, ranking actions by V at a selected remaining time for the
initial fixed-deadline policy. Constant-lookahead T and horizon-selected V/h are
separate later policy experiments, not the initial learner's default. Any later
ratio view names its h_min/v_min and raw/incremental convention; compare wait.
V(state,0) is a separate boundary view, never divided by zero. The new scalar
predicts a sampled max–min search score; it is not called
expected utility or a guaranteed worst-case value. Any auxiliary BTC/USD/growth/
failure/attainment outputs must name their aggregation (mean or joint-worst replica)
and share one candidate controller. Never independently optimize commodity heads.
Display objective, benchmark, strategic horizon, scenario/search budgets, liquidation mode and
checkpoint domain. Preserve different semantics when loading older checkpoints.

For supported synthetic states show side by side:

1. Independent calculated liquidation value `L_trade`, using sequential subsequent
   trades, the declared fill rule and temporary idealized cancellation. Show the
   worst joint scenario and underlying closing trades; label these as ex-post
   reference data, unavailable to the model at the selected decision timestamp.
   State that liquidation duration is currently ignored in score/horizon. Show
   unavailable/incomplete when the tail is missing; never replace it silently by marks.
2. Learned `V_hat` and any explicitly defined auxiliary commodity predictions.
3. Exact sampled-search reference under matching J/K/controller/scenario settings,
   with signed error against that reference. Older mean-policy models instead
   require matching expected-policy reference values.
4. Exact full declared finite-toy optimum under the same information, grid and
   uncertainty criterion, displayed separately from sampled-search performance.
5. Actual frozen network-only policy results/robustness on independent replicas,
   separately from the rollout teacher's value. No exact label outside support.

Evaluate each deployed network-only policy separately from its teacher/controller
search. Search-target accuracy is not proof that the network-only policy attains
that score. Store policy, scenario and target identities. All optimal commodity
references follow one jointly selected controller with a documented tie-break;
joint-worst holdings must come from the same replica, not separate currency minima.

Offer exact references only where the synthetic oracle supports the state;
otherwise show **unavailable**, or explicitly **Monte Carlo estimate** with
uncertainty for a supported simulation estimator. Never show synthetic analytic
values as real historical truth. Mark out-of-training-domain inputs.

## Visualizations and replay

- Recent received trades with order-limit lines.
- Quantity/limit-price heatmaps for predictions, oracle references and errors;
  add a horizon selector; mark infeasible pairs separately. Reserve a separately
  labeled V/h view and policy selector for the later horizon-policy study.
- Compare several order portfolios against wait.
- Optional seeded forward replay after inference, showing decisions, arrivals,
  fills, cash, inventory, maturity receipts and final outcomes versus predictions.
  Show the subsequent liquidation tail separately from strategic trading. A later
  value/time-model view is deferred; recorded trade times are provenance now.
  Keep future tape/hidden exchange state out of the inference input. The replay
  uses the selected declared policy, including later decisions where applicable.
  Show whether its horizon counts down or resets; fixed lookahead must not extend
  the replay's strategic scoring window. Closing tails follow the common duration-
  ignored rule and stay inside the split. No exact long-trajectory uncertainty-tree search.
- Distinguish synthetic/historical inputs and contractual/projected versus
  externally observed payments. Retain failed-model status.

## Acceptance

UI output matches direct checkpoint inference and oracle calls. Editing a state
changes its encoding correctly. Future-tape changes cannot alter current features
or predictions. Test date causality, pending orders, price/lot checks, unsupported
oracle states, checkpoint compatibility/hash failure, offline bundled startup,
download/load and training-free inference. Deliver screenshots, example states,
launch instructions and the actual tested environments. No application deployment
or public hosting is authorized by this plan.

## Delivered checkpoint interface (28 October implementation)

See [the bounded result](TREASURY_MAXMIN_RESULTS.md) and
[artifact receipt](treasury-maxmin-v1-artifacts.json). `selected-model.pt` uses
`treasury-scalar-checkpoint-v1`, `treasury-observable-v1` and the active target
`diagnostic-hold-boundary-v1`. Its `label_identity` is explicit; it must never
be presented as an accepted max–min checkpoint. The planned max–min target
remains `sampled-maxmin-sequential-close-v1`.

Use `treasury_model.load_scalar(path, expected_identity)` for tensor-only
restoration, `encode(observable, instruction, goal, instruments, horizon_ms)`
and `model.predict(feature_rows)` for scalar inference. It supports one BILL
and the fixed objective only. Feature scales are checkpoint buffers. The
`inference-manifest.json` and `inference-examples.json` in the bundle identify
the accepted diagnostic domain and failed repeated-policy status. Outside that
domain, mark predictions unvalidated, including intermediate-horizon pending/
cancel states that caused the observed churn. Future-price labels are never inputs.

The bundle includes exact held/boundary arithmetic and a limited causal toy
oracle; missing/incomplete rollout references stay unavailable. Use the receipt's
immutable URL/hash and bounded archive validation before loading. The explorer
reads only the required members without extracting or executing archived source.
The learning task did not build a UI. The subsequent authorized implementation
now supplies the standalone explorer and Windows launcher; see the launch guide.
