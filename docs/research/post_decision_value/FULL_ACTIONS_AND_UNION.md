# Completed futures union and full bounded action search

The later [carry, sparse grid and expiry-input update](CARRY_GRID_AND_EXPIRY_INPUTS.md)
changes the default search to a 32-attempt sparse grid and downloads public
delivery/settlement/Treasury evidence. The union and frozen results here stand.

Research update, 2026-10-26. All dates/times below are UTC. Research branch:
`agent/btc-post-decision-value-v1`. No application deployment, master merge, live
order, data purchase, new infrastructure, exchange acquisition or annual training.

## Actual merge result

The existing operator finished [run 40341311717](https://github.com/leviitzhak/keep_and_lease/actions/runs/40341311717)
successfully at operator commit `2bc6bd7b18650cb1633ae317eecedb120b819a56`.
The fixed request uses the existing metadata-export workflow and credentials.

| Check | Result |
|---|---:|
| Canonical native trades | 120,105,433 |
| Canonical sequence chunks | 12,322 |
| Daily-export records compared | 486,203 |
| Exact semantic matches | 486,203 |
| Additional overlay rows | 0 |
| Native overlap chunks freshly read | 51 / 510,000 rows |
| Existing storage objects read | 292 |
| Compressed bytes read | 21,539,143 |
| Reconciliation elapsed | 118.714 seconds |

All 90-day data is already contained in the larger archive. The completed union
is a single logical dataset of canonical chunk references, not a second physical
copy of 120 million records. Daily origins remain provenance and are not executed
twice. Its content-addressed manifest is:

```
gs://keep-and-lease-market-data/btc/research/unified-futures-v1/objects/bb448ae2b6ae0fb04e3ecc5a2b77e639122a59077cb79205c773a58ae009b4d2/manifest.json
```

The uncompressed manifest SHA-256 is the directory hash above. A byte-identical
compressed copy, result, input pins and workflow provenance are committed as
`unified-v2-manifest.json.gz`, `unified-v2-report.json`, `union-inputs-v2.json` and
`unified-v2-provenance.json`. The downloaded workflow ZIP SHA-256 is
`6db67b12095b829d3b8dfa8dfc8e926ab4eb106a41007b5ee5cbb45185caf4b9`.

Deduplication by `(instrument, native trade_id)` alone would be insufficient.
The worker also checked sequence identity, timestamp, price, amount, aggressor
direction, index price, block/combo execution flags, raw hashes/sizes and sequence
coverage. Conflicts fail before publishing a manifest. The untouched historical
portion relies on the already frozen archive completion evidence: **this was not
a fresh full-archive raw scan**. Unavailable prefixes, empty contracts and source
gaps remain documented; “union complete” does not mean fabricated gap-free data.

The new `logical_data.LogicalArchive` reads canonical chunks lazily using an
injected existing-object transport (local-cache-only by default). It validates
receipt/raw identities and merges selected instruments in causal sequence-prefix
availability order. Backdated prints cannot fill retroactively. Missing prefixes
require verified sequence/time anchors. Receipt integrity outside freshly pinned
overlap reads relies on the existing immutable receipt convention; raw object
hashes are checked when consumed. The actual manifest contains 509 populated
instruments; empty/unavailable entries remain in the original 540-entry plan.

Still required for year-long **realized** accounting: verified historical contract
metadata and listing-aware universes; exchange settlement/delivery indices and
variation events; executable spot prices, fees and available volume at bridge
times; explicit USD/USDT conversion where applicable; funding, collateral and
margin assumptions; causal prefix checkpoints and gap handling. These are replay
and economic-evidence requirements, not outstanding trade deduplication. Current
spot archives do not establish subsecond executable spot or quote depth. Inverse
prints used for linear futures remain a counterfactual experiment. Contractual
claims are not labeled realized settlement receipts.

## Actions and working-order uncertainty

The old generator refused new packages whenever working or pending orders existed.
That was a search shortcut. A working order can fill; a pending cancellation does
not prove it has stopped; an amendment leaves old/replacement possibilities until
acknowledged. The new search allows new postings alongside such orders and batches
of creations, amendments and cancellations. It preserves conservative reservations
and rejects an amendment of an already-filled order even when its fill report is
late. Cancellation does not instantly free exposure.

`ActionDomain` supports every native tick and lot within its configured bounds,
all sides and all eligible observed instruments. Defaults:

| Dimension | Default |
|---|---|
| Order quantity | 0.0001–0.02 BTC equivalent, native lot steps |
| Limit price | Every native tick within ±50 bp of the last received trade |
| New orders per decision | 1–2; configurable up to 6 |
| Existing orders | Arbitrary subsets amended/canceled; combined batches allowed |
| Risk admission | Initial 90% floors, dated funding, 0.02 BTC asynchronous cap |
| Uncertain order versions | At most 6, including old/replacement possibilities |

The received trade is a reference price, not an invented contemporaneous BBO.
Inverse quantities use native USD lots with BTC-equivalent bounds at each limit.
There are no fixed `q`, `r` or paired-offset templates in this search. The immediate
post-state contains actual orders, their sizes/prices and pending instructions.
The encoder's former 32-item cap was removed; it pools the supplied variable set.

One measured two-instrument state has **201,600 single-order possibilities** before
multi-order combinations. Enumerating every combination is computationally
different from adding dimensions to the state. `ValueActionSearch` therefore uses
128 proposal attempts over four rounds by default, combining global stochastic
proposals with refinement of the top eight. The budget is configurable from
4 to 4,096. This limits computation, not legal tick/lot support. Duplicate and
infeasible proposals reduce the number evaluated. The chosen action maximizes
the scalar network value among evaluated feasible post-states, with declared
epsilon exploration; it is **not a guaranteed global maximum**.

Collection uses 50% exploration initially and 15% after improvement; evaluation
uses zero epsilon (seeded approximate search still samples proposals). All heads
describe one continuation, identified by action bounds, search configuration,
exploration and continuation model weights. The scalar head remains expected
complete-trajectory joint utility, not utility of expected holdings. No actor or
differentiable fill model was introduced.

## Torch, validation and bounded learning

Torch was absent from the default runtime, not from the implementation. The
original saved network/checkpoints were PyTorch. Installing official CPU
`torch==2.14.1` into an isolated Python 3.12 environment succeeded. The installed
version is `2.14.1+cpu`; the system interpreter remains unchanged. The earlier
description of neural tests as blocked did not establish an installation barrier.

The network still has **87,877 trainable parameters**: 20-input item MLP with two
64-wide layers; an 8-input history projection plus learned positions; two causal
transformer layers (width 64, four heads, feedforward width 128); pooled item and
history vectors plus 34 global features; a 64-wide readout and five outputs
(joint objective, BTC growth, USD growth, failure and attainment). Identical
received histories are encoded once per search decision. Tests compare cached
inference with full forward evaluation and invalidate caches after weight changes.

**165 unique tests passed:** 76 accounting/constraint/causality/execution/learning
and expanded-search tests, one additional continuation-identity test, five lazy
reader tests and 83 existing funded-ledger/paired-strategy regression tests.
The four committed test logs contain the commands' detailed outcomes. The new
union worker contributes five tests within the 76, not five additional tests.

The new complete-outcome smoke run used these chronological sets, with all seeds
from a market day in one set:

| Set | Market days | Window/cadence | Delay/exploration seeds |
|---|---|---|---|
| Training | June 6–7, 2026 | 01:00–01:05; 30 seconds | 11, 29 |
| Validation | June 8–9, 2026 | same | 11, 29 |
| Held-out test | June 10–11, 2026 | same | 11, 29 |

Two collect–fit stages, 40 records and 80 optimizer updates per stage, 280 total
decision steps across 28 episodes, 112.43 seconds elapsed. Training-only label
normalization; validation selected stage 0 before test evaluation. Test policies
share initial holdings, history, windows, fees, fill rules and delay seeds.

| Held-out policy | Mean joint utility | Mean BTC growth | Mean USD growth | Fills | Failures |
|---|---:|---:|---:|---:|---:|
| Selected value policy | −0.338893% | +0.530000% | −0.338893% | 4 | 0 |
| Hold | 0% | 0% | 0% | 0 | 0 |
| Analytical, expanded domain | 0% | 0% | 0% | 0 | 0 |

These are contractual endpoints on inverse-source trades with hypothetical linear
payoffs. Only two test market days exist; seeds do not multiply independent market
evidence. The learner underperformed hold and is not accepted for trading. This
run validates plumbing, not annual or subsecond performance. Frozen legacy
90-day analytical results and their 54/18/18 split are unchanged.

`expanded-smoke-v2.tar.gz` contains configurations, data references, splits,
transitions, all decision/order/fill journals, validation/test results, model and
optimizer/RNG checkpoints and an exact 18-file source snapshot. Its SHA/size and
equivalence checks are in `expanded-smoke-artifacts.json`. Every action, fill,
outcome and collected regression record matched the pre-history-cache run.
Subsequent continuation-tag hardening changes metadata, not the numerical policy;
the source snapshot preserves exact reproduction of this saved experiment.

## Annual half-second training estimate

A 365-day trajectory requires **63,072,000 decisions at 500 ms**, or **315,360,000
at 100 ms**. Adjacent states are strongly correlated; these counts are not
independent training examples. There is no defensible universal number of annual
trajectories that guarantees adequate learning. Measure held-out learning curves,
tail/failure calibration and coverage of expiry/premium regimes as data increases.

A proposed starting design, conditional on verified historical coverage and
bridges, is training years 2018–2023 × four exploration/latency seeds = **24 annual
rollouts per collection round**; two to three rounds = **48–72 training rollouts**.
Use 2024 for validation and untouched 2025 for final testing, with portfolios reset
between blocks and no labeled trajectory crossing split boundaries. Reject or
shorten incomplete years rather than manufacturing history. This is a proposed
budget/learning-curve experiment, not a launched job or a claim of sufficiency.
It implies 3.03–4.54 billion training decisions at 500 ms, plus evaluation.

Latest warm CPU probes used one Torch thread on an Intel Xeon Platinum 8573C
host (container quota eight vCPU, 8 GiB RAM), the 87,877-parameter checkpoint,
64 history events and 128 search attempts. Eight measurements followed warmup:

| Observable state | Mean CPU / decision | One annual 500 ms rollout | One annual 100 ms rollout |
|---|---:|---:|---:|
| No working orders | 0.447 seconds | about 326 CPU-days | about 1,630 CPU-days |
| Two working orders | 1.317 seconds | about 961 CPU-days | about 4,807 CPU-days |

`expanded-benchmark.json` records all measurements. These are extrapolations from
fixed short-history states, not completed annual simulations. Host timings vary
substantially, and larger universes/portfolios can cost more. At these rates, 24
rollouts require roughly 7,827–23,071 CPU-days per round: current implementation
is not suitable for that experiment. Independent trajectories can run in parallel,
but a trajectory's successive decisions cannot all be parallelized. A GPU alone
does not remove Python state transformation and conservative admission costs.

An engineering **target**, not a measurement, of 5 ms per decision would reduce
one 500 ms annual rollout to 3.65 CPU-days, and 24 to 87.6 CPU-days (ideal 16-worker
elapsed time 5.5 days, before overhead). Reaching this needs profiling, vectorized
admission/features, batched multi-trajectory inference and bounded streaming.
Sampling fewer states for regression reduces fitting/storage, not the required
closed-loop simulation decisions. The small network fits on CPU; collection and
action search dominate. No new hardware or large training was provisioned.

## Faster repricing and the old 0.99 ratio

Faster decisions can exploit shorter-lived premium opportunities and keep limits
from becoming stale. They do not guarantee better realized premiums or portfolio
utility: amendments can lose queue priority, messages arrive late, fills are
adversely selected, legs can remain unmatched and venue rate limits apply. Compare
cadences on identical tapes/seeds and report matched-pair premiums after fees,
fill rates, leg exposure and objective together. Trade-only tapes do not identify
actual queue position or depth. Primary exchange references:
[order management](https://docs.deribit.com/articles/order-management-best-practices),
[rate limits](https://docs.deribit.com/articles/rate-limits),
[exchange rulebook](https://support.deribit.com/hc/en-us/articles/25944555524125-Deribit-Exchange-Rulebook-Deribit-FZE).

The legacy analytical policy approximated full fills immediately and greedily
ranked resulting contractual joint holdings, without learning continuation. For
long `q` in the cheaper future at `F_A` and short `r q` in the dearer at `F_B`:

```
delta BTC = q (1 - r)
delta USD = q (r F_B - F_A) - fees
```

With `r=1`, BTC growth is zero, so the minimum-of-two-growth objective cannot
increase even if USD grows. `r=0.99` was a heuristic to retain some BTC increase
while capturing USD premium when `F_A/F_B < r < 1`, before fees. It is neither an
exchange requirement nor a fundamental optimum. Native rounding matters: old
`q=.005`, `r=.99` becomes `.005` and `.0049` at `.0001` lot size, an actual ratio
of `.98`. The new domain chooses each order quantity independently.

## Reproduction

Run from the repository, using only an existing hash-receipted input cache:

```bash
python -m venv .venv-pdv
. .venv-pdv/bin/activate
python -m pip install numpy 'torch==2.14.1' --index-url https://download.pytorch.org/whl/cpu
python -m unittest discover -s tests/post_decision_value -v
python -m unittest tests.test_funded_ledger tests.test_paired_transfer_economics tests.test_paired_execution_study -v
python -m research.post_decision_value.expanded_validation \
  --root /path/to/existing/dec_mar_inputs --output /path/to/new-expanded-run
python -m research.post_decision_value.expanded_validation \
  --root /path/to/existing/dec_mar_inputs --output /path/to/new-benchmark --benchmark-only
tar -xzf docs/research/post_decision_value/expanded-smoke-v2.tar.gz -C /tmp
```

The full validation runner permits 1,000 decisions/180 seconds for its smoke;
80 updates per stage, two stages, and the existing stricter global pilot caps
remain enforced. Output directories are immutable. Bounded timing precedes the
smoke. For the ordinary runner, `--action-space full` is the default and
`--action-space legacy` explicitly requests the old menu.

To inspect the union without downloading raw objects:

```python
from research.post_decision_value.logical_data import LogicalArchive, local_getter
archive = LogicalArchive.open(
    'docs/research/post_decision_value/unified-v2-manifest.json.gz',
    local_getter('/path/to/existing/object-cache'),
    expected_sha256='bb448ae2b6ae0fb04e3ecc5a2b77e639122a59077cb79205c773a58ae009b4d2')
print(len(archive.by_symbol))  # 509 populated instruments
# archive.trades(start_ms, end_ms, symbols=[...], prefix_anchors={...})
```

The checked-in union worker is the same implementation installed on the operator
branch. Re-running its cloud entrypoint is unnecessary: consume the immutable
manifest. It is bounded to 450 object reads, 64 MB compressed bytes, 100 overlap
chunks, 1.2 million compared rows and 360 seconds between read checks, under the
existing ten-minute workflow timeout. Existing storage only; no exchange calls.
