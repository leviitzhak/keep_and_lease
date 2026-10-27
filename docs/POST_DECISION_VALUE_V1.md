# Post-decision commodity value research v1

This standalone, CPU-only research pipeline implements the 25 October 2026
[specification](https://chatgpt.com/library?file_id=libfile_538f5a61a28c8191a0a06e56709bc1a6&account_id=personal).
It does not connect to an exchange, change the application, deploy, acquire data,
or provision resources. Research branch: `agent/btc-post-decision-value-v1`.

## Integration and branch choice

Base: GitHub `master` `80be0fc4c30904a0f4dfb16e097de2a001424e64`.
Operator lead inspected: `09468c3f0dd441367e4f16ecbf8a0fe058f39591`.
Master contains `funded_ledger.py`, `paired_transfer_economics.py`,
`paired_execution_study.py`, `trade_ordering.py` and `replay_checkpoints.py`.
The operator branch has newer data exporters, but lacks several funded strategy
components. The existing long-only `FundedLedger` explicitly rejects inverse
payoffs and shorts; extending it in place would silently change its consumers.
The new signed ledger therefore lives under `research/post_decision_value/` and
reuses existing source ordering and immutable checkpoint codecs. No existing
application strategy is redirected to it.

The GCP deployment workflow explicitly excludes this branch on push and guards
its deploy job on manual dispatch. Other push workflows target unrelated named
branches. Research commits additionally use `[skip ci]`. These exceptions are
specific to this branch; stable and other preview behavior is unchanged. Do not
merge this research branch to master without separately reviewing deployment.

## Accounting contract

`accounting.py` stores native balances, collateral restrictions, signed positions
at their *remaining* settlement basis, dated receivables/liabilities and fees.
Long-term equivalents are spot/native balances plus signed contractual claims:
linear `(q BTC, -qK USD)`; inverse `(N/K BTC, -N USD)`. A variation payment changes
both the settled native balance and remaining basis. Closing or reversing a
position realizes only the remaining payoff. Inverse aggregation uses a harmonic
basis. Neither collateral pledging nor borrowing creates wealth.

Cash instruments can now be supplied explicitly: direct BTC spot, fixed-ratio
BTC proxy shares and Treasury units with known dated coupon/principal receipts.
Purchases debit their full USD cost; sales require owned, unpledged inventory.
The old direct `buy_treasury` helper remains opt-in. Treasury income is not an
automatic interest credit on idle cash; no future rollover is synthesized.
Contractual payments remain labeled projected even after the simulated cash
credit. Credit defaults to zero; enabled borrowing
requires a fixed principal limit, due date and explicitly priced interest.

A linear expiry bridge settles the future and buys/sells `q` BTC. An inverse
bridge settles BTC P&L and buys/sells `N/index` BTC using cash. Signed quantities
handle shorts. Observed index, executable spot and an explicit conversion fee
are required to label a bridge realized. Unknown expiry evidence truncates the
replay; it never creates a realized label. Open claims at the policy deadline
are reported as **contractual/projected**, with their complete dated schedule.
Actual marked USD/BTC wealth is separate. Treasury claims without supplied
market prices are explicitly flagged as unmarked.

The pilot's contractual valuation is before unknown future bridge slippage and
conversion fees; current trading fees are deducted once. Funding stress reserves
an adverse 10 bp spot/index gap, but does not describe that hypothetical loss as
realized. This distinction must be retained when interpreting growth.

Admission evaluates every endpoint subset of up to six uncertain native orders,
including old and replacement amendment versions. This deliberately overstates
some races. It checks initial BTC/USD floors, dated liquidity through the last
claim date, and a separate 0.02 BTC aggregate asynchronous package cap. The
funding scenarios use index factors 0.5, 1 and 2, hypothetical 10% initial margin,
no automatic sale of BTC to fund cash deficits, and bridge debits before same-date
receipts. These finite scenarios do not prove universal path safety. Reservations
are restrictions, not deductions from holdings. Fees and floors are checked
after every actual partial fill, not only after both legs finish.

Each positive initial commodity has a 90% initial-quantity floor by default; `Goal.drawdown` also accepts a BTC/USD dictionary for distinct allowances; this is not a
high-water mark. Zero quantities require explicit absolute floors and positive
normalizers; negative initial positions are excluded. Target composition uses
fixed reference prices, a deadline, tolerances and optional band maintenance.
The 60/40 exact-target minimum-value check is $225,000 for the specification's
example. Target utility is labeled a surrogate; attainment is a separate flag.
The archived historical pilot remains the initial-basket experiment, not target training.
New pilot CLI runs default to `--objective weighted_growth`, a weighted sum of
positive growth minus a configurable penalty for every negative growth.
`--objective basket` retains minimum growth and `gated_max` retains the previous
conditional maximum. See the [weighted/event-clock update](research/post_decision_value/WEIGHTED_EVENT_TRAINING_PLAN.md).

## Execution, candidates and observations

`engine.py` separates `ObservableState` and `HiddenExchangeState`. Policy code
accepts only copies of the observable type. It has received market history,
confirmed orders, uncertain remaining orders, pending instructions and resource
reservations. True fills, future prints and sampled message arrival times are
never features. A canceled order stays possible until its report arrives.

There are separate observation, computation, delivery and report delays.
Counter-keyed seeded draws include a shared minute congestion factor and are
made once per event. FIFO message and report channels, replacement-of-remaining
quantity and loss of amendment priority are *hypothetical adapter assumptions*.
Amendments of already completed orders are rejected. At equal timestamps,
contractual Treasury payments precede messages, messages precede trades and
reports follow trades. A purchase at a coupon timestamp is ex-coupon. These tie rules are saved
research conventions, not inferred historical exchange behavior.

Trades fill only strict-through opposite-aggressor orders at their posted limit.
A shared print capacity is consumed once, with native lot rounding and partial
fills. Block/combo prints remain observations but cannot fill an order. For
linear experiments using inverse-source prints, BTC capacity is `USD amount /
print price`, then multiplied by participation. Quotes, depth and queue position
are not invented. Cash execution requires an explicitly supplied typed tape;
historical results already published contain no spot execution.

`--action-space full` samples the full native tick/lot domain
within configurable bounds: 0.0001–0.02 BTC equivalent per order and ±50 bp of
the last received trade. All eligible observed instruments have sampling support.
Order sizes, sides and posted prices are independent; there is no fixed leg ratio.
Working orders permit additional postings and combined creations/amendments/
cancellations, subject to the existing funding, floor and six-uncertain-version
admission checks. Defaults allow up to two new orders per decision (configurable
to six). Stochastic global proposals and local refinement use 128 attempts over
four rounds, selecting the best scalar value among feasible evaluated post-states;
this is an approximate argmax, not exhaustive enumeration or a 128-action domain.
The state encoder retains actual orders without a 32-item cutoff. A pure builder
adds pending intent and reservations without pretending an order filled. Proposal
payloads, admission results and selected actions are retained.

The current default `--action-space grid` uses price/quantity endpoints, a midpoint
and up to two random interior native steps, with 32 proposal attempts. It prioritizes
boundary proposals, then samples combinations and amendments. Budget, rounds and
random points have CLI controls; insufficient coverage of boundary proposals is
reported. See [carry, grid and expiry inputs](research/post_decision_value/CARRY_GRID_AND_EXPIRY_INPUTS.md)
for measured costs and public settlement/rate downloads. Spot/proxy/Treasury
actions now enter this same search. Treasury quantities use a separate default
$100–$2,000 purchase-notional range; proxy sizes divide BTC units by the declared
BTC/share ratio. Prices remain near the latest received price. Native inventory,
pending orders and dated receipts enter schema-v2 network features. See the
[cash/objective report](research/post_decision_value/CASH_ASSETS_AND_OBJECTIVE.md)
for the input contract and remaining historical evidence gaps.

`--action-space legacy` preserves the old 96-candidate pilot menu, 0.005/0.01 BTC
sizes, 0.99/1 leg ratios, -50/0/+50 bp offsets and suppression of new packages
while instructions remain unresolved. Frozen earlier reports used that menu.
The legacy menu rejects cash bundles; use grid or full search for those assets.

The emergency action cancels all known possible orders and admits no new risk.
It cannot instantly undo a late fill or guarantee recovery. A failure is retained
and penalized. There is no invented emergency market liquidity.

## Learner and policy improvement

`model.py`: shared instrument/order/obligation item encoder, stable identity
features, masked item pooling, 64 received-history steps, two causal transformer
layers of width 64 with four attention heads. Explicit trailing volatility and native-to-USD volume summaries use received history only. Features use fixed economic scales;
label normalization is fitted only on training outcomes. Price offsets are
encoded relative to the received price so small posted-price differences are
visible to the learner. The optional MLP history mode is available for ablation.

Independent outputs predict the expected scalar trajectory utility, normalized
terminal BTC/USD holdings, failure probability and target attainment. All outputs
share the same versioned continuation. Scalar ranking never maximizes individual
commodity heads and never substitutes utility of mean holdings. The default
CLI scalar label is the weighted sum of positive growth minus `loss_aversion`
times the sum of negative growth magnitudes, per complete trajectory, minus a
finite penalty of 1 for failed paths. Defaults: equal growth weights and loss
aversion 10. `--objective basket` and the low-level `Goal` default preserve the original
minimum label. All objectives use positive-initial commodities; explicit floors
and scales remain necessary for zero-initial assets. No actor, desired-return token, tree search,
fill gradient or intermediate reward double counting is used.

Schema 1 has 87,877 parameters. Schema 2 has 88,645: item input 28, history input
11, global input 35, otherwise the same width-64/two-layer/four-head architecture.
Old checkpoints remain loadable for their original schema, but cannot score the
new schema. New objective labels and continuation fingerprints require new
training. The fit report now retains every training minibatch loss.

Schema 3 adds weighted-objective parameters, has 39 global inputs and 88,901
parameters. New weighted models require new training. Optional event-clock
decisions use only received price/premium/account changes, known dates and a
heartbeat while the engine processes every event exactly. The clock is part of
the continuation and engine checkpoint. See the
[design, tests and cloud proposal](research/post_decision_value/WEIGHTED_EVENT_TRAINING_PLAN.md).

Stage 0 collects a declared stochastic analytical/random behavior policy and
fits complete-outcome labels. Stage 1 collects fresh closed-loop trajectories
from stage 0's greedy policy with 15% exploration, then fits that continuation
only. Old labels are not relabeled or pooled as new-policy values. Validation
chooses between frozen stage 0 and stage 1 models. Chronological test blocks
compare the selected greedy policy, hold and the analytical full-fill-contractual
baseline from identical initial portfolios and delay seeds. A separate test
calibration replay follows the model's actual training continuation. The final
greedy improvement is an approximate policy improvement, not an exact evaluation
of itself or a profitability guarantee.

## Reproduction and bounded persistence

Use Python 3.12 in a dedicated environment:

```bash
python -m venv .venv-pdv
. .venv-pdv/bin/activate
python -m pip install numpy 'torch==2.14.1' --index-url https://download.pytorch.org/whl/cpu
python -m unittest discover -s tests/post_decision_value -v
python -m unittest tests.test_funded_ledger tests.test_paired_transfer_economics tests.test_paired_execution_study -v
python -m research.post_decision_value.pilot \
  --input /path/to/existing/dec_mar_inputs \
  --output /path/to/new/pilot-weighted --objective weighted_growth
```

Input is an **existing** export containing `specification.json`, `seeds.json`,
`input_coverage.json`, `source_receipts.json` and `inputs/YYYY-MM-DD-SYMBOL.jsonl.gz`.
Every raw object is matched to the receipt's SHA-256, byte count and row counts.
The output manifest gives persistent GCS source URIs and metadata hashes. The
loader never downloads. This pilot needs June 6–13, 2026; 01:00–02:00 UTC decision
windows; four training, two validation and two held-out days. There are no
settlement-tail labels: each horizon is a complete contractual endpoint before
expiry. All scenarios from one market day stay in the same split.

`--cash-input /path/to/bundle` attaches additional cash tapes after hash, currency,
native-unit and provenance checks. Indicative quotes cannot fill orders. There
is no implicit USD/USDT conversion. An example synthetic bundle, complete
multi-asset training audit and through-expiry carry fixtures can be reproduced:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m research.post_decision_value.cash_smoke \
  --output /path/to/new/cash-smoke
```

This separate smoke uses a 240-second overall cap, 2,000-decision cap, 160 total
optimizer updates and one Torch thread. It does not estimate historical returns.

Limits: 20,000 decisions; 2,000 cumulative pilot optimizer updates; 1,200 seconds
training; 3,600 seconds pilot; 100,000 input rows; 8 MB compressed input; 30,000
exchange/report events per episode. Defaults are two seeds, 120-second cadence,
160 updates per stage, one CPU thread and 10% print participation. Short episodes
and coarse cadence bound work without claiming finer spot information.

Outputs include source/code/config fingerprints, splits, complete trajectories,
full candidate/fill audits, model and optimizer checkpoints, torch/numpy RNG
states, reports and fixed-continuation calibration. Small deliverables are
committed alongside repository research reports; their original raw objects
remain in the existing market-data bucket. No new infrastructure is required.
`checkpoint.py` reuses `DirectoryCheckpoints` and `GcsCheckpoints` for typed engine
state (including pending events and draw identities). GCS writes require the
existing authorized operator; none are performed by this local pilot.

```bash
python -m research.post_decision_value.pilot \
  --input /path/to/existing/dec_mar_inputs \
  --output /path/to/new/pilot-weighted --objective weighted_growth --resume
```

Resume reuses completed training stages, verifies source/config/data identities,
retains the original source commit and returns an already complete report without
retraining. An interrupted unfinished stage is recollected. Model optimizer/RNG
and individual engine journals additionally support exact continuation (tested).
Only trusted tensor-only model checkpoints are loaded. Runtime/data truncation
is explicitly incomplete and receives no invented terminal target.

## Final pilot result

See [the final report](research/post_decision_value/RESULTS.md): 43 new tests and 83 existing regression tests passed. The final 49-second counterfactual historical pilot underperformed hold (joint held-out growth -2.095% versus 0%). The learner is not accepted for trading. The existing spot acquisition was verified as complete with source gaps but unparsed; see the report for the distinction between raw coverage and execution-ready data.

## Acceptance scope and remaining extensions

Tests cover signed payoffs, repeated variation, funded cash/long, borrowing,
collateral, Treasury receipts, dated cross-expiry funding, bridges, zero holdings,
floor boundary, target feasibility, nonlinear utility, hidden-state isolation,
strict fills, lot/volume conservation, edit/cancel races, seeded resume, causal
attention, known price-dependent optimal action, head independence and exact
optimizer resume. Historical replay is a software smoke test with two held-out
market days; block-level ranges/errors are reported instead of treating duplicate
seeds as independent evidence.

Full native inverse learning, target-composition training, empirical latency,
verified historical margin/account capabilities, live spot execution, historical
settlement bridges and wider out-of-time evaluation remain separate research.

The subsequent [complete cached 90-day analytical study](research/post_decision_value/ANALYTICAL_90_DAY.md)
adds a neural-dependency-free runner with fixed 54/18/18-day calibration,
validation and test sets, continuous portfolios within each set, all raw trades
and hourly decisions. It documents the exact candidate count and larger-universe
truncation bias. This extension does not rerun or change the neural pilot.

The [initial unified data and replay extension](research/post_decision_value/UNIFIED_DATA_AND_REPLAYS.md)
preserves three exact historical replay excerpts and legacy 100/500 ms CPU probes.
The subsequent [completed union and expanded action search](research/post_decision_value/FULL_ACTIONS_AND_UNION.md)
reconciles all 486,203 daily records against the native multi-year archive and
publishes one logical 120,105,433-row dataset. It adds a lazy causal chunk reader,
full bounded order-domain search, restored Torch validation, a new chronological
learning smoke test and updated runtime measurements. Trade unification is
complete; verified settlement/spot bridges and annual learning remain outstanding.
