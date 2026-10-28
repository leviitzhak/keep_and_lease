# State-value explorer: separate next implementation

Updated 28 October 2026. **Planned, not built, hosted or deployed.** Implement after the
[Treasury learning/reference task](TREASURY_LEARNING_NEXT_PROMPT.md); this document
does not authorize starting the UI during that task. A failed checkpoint can be
inspected for diagnosis but must retain its failed acceptance status visibly.

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
This is the **failed** model, not a new accepted checkpoint. No online checkpoint
catalog or UI download control exists yet.

The learning task must publish immutable small inference bundles and a manifest
with URL, hash/size, source identity, model/feature/normalization versions,
objective, continuation policy, supported horizons, training domain, acceptance
result and oracle support. New bundles also identify J/K, uncertainty scenarios,
candidate-controller law, positive horizon grid/minimum, utility threshold, growth
benchmark and terminal marking mode. UI task: add a run/checkpoint selector, user-triggered
download, hash verification, bounded safe extraction/local cache and load-from-file.
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
and positive target horizons, the selected V/h ratio, v_min/h_min eligibility and
wait/incremental comparisons. V(state,0) is a separate boundary view, never divided
by zero. The new scalar predicts a sampled max–min search score; it is not called
expected utility or a guaranteed worst-case value. Any auxiliary BTC/USD/growth/
failure/attainment outputs must name their aggregation (mean or joint-worst replica)
and share one candidate controller. Never independently optimize commodity heads.
Display objective, benchmark, horizon, scenario/search budgets, marking mode and
checkpoint domain. Preserve different semantics when loading older checkpoints.

For supported synthetic states show side by side:

1. Independent terminal marked value `L_mark`, with the temporary idealized
   cancellation/close-at-mark convention visibly identified.
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
  add a horizon selector and V/h view; mark infeasible/ineligible pairs separately.
- Compare several order portfolios against wait.
- Optional seeded forward replay after inference, showing decisions, arrivals,
  fills, cash, inventory, maturity receipts and final outcomes versus predictions.
  Keep future tape/hidden exchange state out of the inference input. The replay
  uses the selected declared policy, including later decisions where applicable.
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
