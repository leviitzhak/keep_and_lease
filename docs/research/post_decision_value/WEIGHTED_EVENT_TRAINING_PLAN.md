# Weighted growth, event-triggered decisions and longer training

28 October design addendum: [sampled max–min rollout specification](ROLLOUT_MAXMIN_SPEC.md)
and [new learning handoff](TREASURY_LEARNING_NEXT_PROMPT.md) define the next task.
The terminal U formula is retained, but its aggregation changes to sampled max–min;
that is not implemented in the expected-utility models described below. A broader
synthetic market generator and independent realistic liquidation learning are
documented later work, not requirements to launch now.

27 October 2026, UTC. Research branch `agent/btc-post-decision-value-v1`.
Implemented locally: weighted utility, optional causal decision clock, regression
tests and a bounded cached-data clock probe. Conditional orders and cloud training
below are designs, not launched services or accepted profitability results.

Readiness check and Treasury sanity run are complete: software tests pass, but
the learner chooses cash even for profitable bills. See
[TREASURY_SANITY.md](TREASURY_SANITY.md). Years-long training remains blocked by
the learning gate, streaming runner, data eligibility and cloud integration.

The immediate [learning handoff](TREASURY_LEARNING_NEXT_PROMPT.md) now requires
exact synthetic same-policy/optimal references and repeated-decision evaluation.
[The interactive explorer](STATE_VALUE_EXPLORER_PLAN.md) is documented for a
separate task afterward, including checkpoint downloads and reference/error views.

## Continuous weighted utility

For normalized net terminal growth `g_c`, define `x+ = max(x,0)`:

```
U = w_BTC * g_BTC+ + w_USD * g_USD+
    - lambda * ((-g_BTC)+ + (-g_USD)+)
    - failure_penalty * failed
```

Weights are nonnegative and sum to one. The loss penalty is deliberately
**unweighted**: even an asset with zero positive-growth weight is penalized for
a loss. Defaults for new CLI runs are equal weights and lambda=10; these are
explicit research settings, not calibrated optimal choices. `--btc-growth-weight`
sets BTC's weight, with USD receiving the remainder. `--loss-aversion` accepts
any positive finite lambda. No silent normalization or clipping is applied.

This function is continuous and piecewise linear. Its corners do not obstruct
complete-outcome regression: we are not differentiating fills or actions.
With weights 0.5/0.5 and lambda=10, (+5%,+2%) scores +3.5%; (+5%,0%) scores +2.5%;
(+5%,-0.1%) scores +1.5%; and (+5%,-1%) scores -7.5%. Large finite lambda strongly
discourages losses but is not a guarantee that every losing trajectory gets a
negative total score. Existing holding floors, funding constraints and failed
path reporting remain separate. Positive-initial commodities enter the score,
as before; inactive weights are not renormalized for zero-initial commodities.

The independent scalar head learns expected **trajectory utility under one
frozen continuation**. Neither the maximum nor weighted utility is applied to
average predicted holdings. Failure and attainment heads remain auxiliary
trajectory labels. `basket`, `gated_max`, `btc` and `target` remain selectable;
archived results/checkpoints are unchanged and are not relabeled.

Schema 3 includes the objective flag, both weights and `log1p(lambda)` as global
features. Dimensions: global 39, item 28, history 11. The width-64, two-layer,
four-head model has **88,901 parameters**. Schema 1/2 remain loadable for their
original inputs. Objective parameters are fingerprinted and mixed-parameter
labels are rejected. Changing the objective requires collecting/fitting new
labels; no old model is claimed to implement the new preference.

## Event-triggered policy decisions

`--decision-clock event` processes the exact exchange event queue but calls the
action search only when observable information changes sufficiently. No hidden
fill, scheduled message arrival, future print or unreceived report is a trigger
input. The simulator driver reads its queue solely to advance exchange time.

Current triggers, all compared with the last accepted **post-decision** state:

- Relative change in a received instrument price or the latest received BTC
  index, default 2 bp: `10000 * abs(log(new / old)) >= threshold`.
- Absolute premium change, default 2 bp. Futures use price/index minus one;
  fixed-ratio proxies use price/(index*BTC-per-share) minus one; Treasuries use
  remaining contractual receipts/price minus one. These are nonannualized.
- Received order acknowledgements, amendments/cancellations, partial fills,
  ledger/collateral/debt changes or an observed failure; new observed instruments.
- Known coupon, maturity, liability or goal dates; a heartbeat at most every
  30 seconds even if no new market observation arrives.

A default 100-ms minimum gap coalesces bursts. Report/date triggers that occur
inside it are considered at the next allowed decision; the engine still executes
and checks risk at every intermediate event. Small price changes accumulate
relative to the last decision. A known payment date may wake the policy, but
unreported proceeds remain unavailable in its observable ledger. Staleness is
still encoded and the heartbeat permits refreshes. A future extension could add
explicit distance-to-working-limit, volatility and funding-headroom thresholds.

The clock's configuration, anchors and account signature live in the engine
checkpoint. The pilot records trigger reasons with each selected instruction.
The timing rule is part of the continuation identity; changing it requires
new policy evaluation/collection. Fixed cadence remains available with
`--decision-clock fixed --cadence-ms 500`. Event mode does not use that interval.
The terminal horizon and utility remain fixed in physical time; there is no
per-decision reward that can be multiplied by waking more frequently.

### Completed probe and tests

[event-clock-probe.json](event-clock-probe.json) reads existing hash-verified
June 6, 2026 Dec26/Mar27 inverse-source files and replays 01:00–01:02 UTC. It uses
a hold policy, counterfactual linear adapter, matched initial holdings and seed.
There is no neural fitting or new data download.

| Clock | Decisions | Exchange/report events | Measured driver CPU seconds |
|---|---:|---:|---:|
| Fixed 500 ms | 240 | 14 | 0.29387 |
| Event, 2 bp / 100 ms / 30 s | 6 | 14 | 0.00721 |

The 97.5% decision reduction and identical hold outcomes validate scheduling on
this quiet sample. They are not a general speedup or return guarantee: active
markets, working orders and learned actions change trigger frequency. The probe
does not time candidate search or neural inference and ran alongside tests; these
short timings are not stable throughput measurements. Its immutable source hashes,
configuration and every trigger reason are saved in the JSON.

**207 tests passed:** 124 post-decision and 83 existing ledger/paired-strategy
tests. The 14 new tests cover weighted signs and continuity, zero-weight losses,
parameter fingerprints, schema-3 Torch fitting, cumulative changes, debounce,
hidden-state causality, delayed partial fills, known cashflow dates, unchanged
event processing, checkpoint continuation and budget truncation without labels.
Logs: [weighted-event-tests.txt](weighted-event-tests.txt) and
[weighted-event-legacy-tests.txt](weighted-event-legacy-tests.txt).

```bash
python -m unittest discover -s tests/post_decision_value -v
python -m research.post_decision_value.clock_probe \
  --input /path/to/dec_mar_inputs --output /tmp/clock-probe.json
python -m research.post_decision_value.pilot \
  --input /path/to/dec_mar_inputs --cash-input /path/to/verified-cash-bundle \
  --output /path/to/new-run --objective weighted_growth \
  --btc-growth-weight 0.5 --loss-aversion 10 --decision-clock event \
  --trigger-price-bps 2 --trigger-premium-bps 2 \
  --trigger-min-gap-ms 100 --trigger-max-wait-ms 30000
```

The pilot example still has its original bounded historical dates and caps. It
does not launch annual training. The cash bundle argument requires actual input;
existing Treasury rate quotations are not silently converted into executions.

## Conditional premium orders: documented extension

Support conditional order intents when the specific venue/account permits them.
Example: post a spot sale with immutable parent limit `S_limit`; upon its fill,
activate a futures buy with `F_limit = S_limit * (1 + premium_target)`, rounded
down to the future's tick. A negative premium target is permitted. An annualized
target must specify day count and maturity; it must not be confused with a
simple price ratio. The reverse direction needs the corresponding side-aware
inequality. Targets and sizes should be searched jointly with other actions.

Persist parent/child IDs, anchor type and value, premium convention, side,
remaining quantity, activation condition, expiry, linkage/amendment version and
execution host. `parent_limit` implements the requested posted-price anchor;
`actual_fill_price`/filled VWAP is a distinct selectable convention. Parent
amendments must explicitly re-anchor or retain existing children—never silently
change their economic meaning. Partial parent fills activate only proportional
child quantities, with native rounding and an audited residual.

Two adapters must be distinguished:

1. **Venue-hosted conditional order:** activation follows documented exchange
   rules and venue-observable data; reports can arrive later. Support for an
   ordinary stop order does not establish support for cross-instrument linkage.
2. **Client-hosted conditional order:** activate only after the parent fill report
   is received, then incur computation, transmission and exchange delays. A
   cross-venue spot/futures pair cannot be treated as atomic without evidence.

Reserve funding and exposure for reachable contingent branches. Check the
parent-filled/child-unfilled case, partial fills, trigger and cancel races,
child rejection and expiry. Short spot/proxy still needs inventory or verified
borrow capability. Native activation does not guarantee liquidity or a fill.

The observable post-state must encode contingent instructions and their anchors,
not only already-live orders. Hidden activation/fill state remains hidden until
reported. Acceptance tests must cover all races and compare client-hosted versus
venue-hosted latency before claiming their economic benefit. This extension is
**not implemented**, and is not required for the initial Treasury learning test.

## CPU-days and scaling estimates

A CPU-day is 86,400 CPU-seconds. On one continuously busy comparable CPU, X
CPU-days is approximately X days of wall time, plus I/O and orchestration.
A cloud vCPU is not necessarily a physical core; processor generation, clock,
memory, throttling and vectorization affect the conversion. Prior sparse-grid
reports recorded both process CPU and wall time; their 26–40-day annual estimates
were search-only extrapolations from tiny one-thread probes, not annual jobs.

For a batch requiring D CPU-days over independent trajectories, ideal time is
`D / workers`; a more realistic model is `D / (workers * parallel_efficiency)`
plus serial/I/O work. Giving the current single-threaded simulator eight CPUs
does not divide one trajectory's duration by eight. Run separate trajectory
processes or explicitly batch/parallelize candidate evaluation instead.

Illustrative **search-only** arithmetic at 40 ms per decision, 365-day horizon:

| Average decision spacing | Decisions per trajectory-year | Serial search time |
|---|---:|---:|
| 0.5 seconds | 63,072,000 | 29.2 days |
| 5 seconds | 6,307,200 | 2.92 days |
| 30 seconds | 1,051,200 | 11.68 hours |

These are arithmetic scenarios, not measured event-clock annual speeds. All raw
trades, reports, liquidity checks and settlements still need processing. Many
simulated seeds on one year do not provide additional independent market years.

## Proposed Google Cloud campaign, not launched

Use a dedicated research container pinned by Git commit and image digest,
existing GCS source manifests and immutable checkpoint/result prefixes. Do not
run training inside the web service or change stable/preview application limits.
The logical futures union has 120,105,433 rows in 12,322 chunks; stream existing
objects with bounded cache and cursor validation instead of loading an entire
year into `Engine.add_tape`. That streaming training driver is still required.

**Compute proposal:** Google Cloud Batch with initially eight independent
single-CPU rollout tasks, 4 GiB each; one separate 4-vCPU/16-GiB fitting task.
These are starting capacity targets, not proven RAM requirements or provisioned
resources. Profile the small 88,901-parameter model on CPU first; add a single
GPU or shared inference batching only if fitting/inference is the measured
bottleneck. Batch supports task arrays and parallelism and provisions Compute
Engine resources for those tasks. This requires a separately approved resource
and IAM change; existing operator access does not imply Batch is ready.

Cloud Run Jobs are an alternative for bounded CPU chunks. The repository's
preview profile documents 1 vCPU/4 GiB and a 24-hour timeout, not a PDV trainer.
Cloud Run's service maximum is seven days for CPU tasks and one hour for GPU
tasks; those limits do not override stricter project limits. Current PDV caps
remain 3,600 seconds/run, 1,200 training seconds and 2,000 optimizer updates.
Splitting a large campaign into small jobs is not authorization to exceed the
aggregate budget. No job, IAM change, provisioning or dispatch was performed.

### Phases and acceptance gates

1. **Learning sanity:** require correct out-of-sample ranking for cash versus
   Treasury buy-and-hold, including fees, overpriced bills and constrained cash;
   then add spot/futures carry and independently filling pairs. The prior mixed
   model failed to select Treasury postings. Passing accounting tests is not
   equivalent to passing this policy-learning gate.
2. **Data eligibility:** build security-level Treasury terms and an explicit
   daily execution proxy or verified execution tape; normalize existing spot
   sources and USD conversion; verify daily futures settlement, funding and
   executable bridge tails. Preserve inverse-to-linear counterfactual labeling.
   Contractual-only endpoints must remain a separately labeled experiment.
3. **Bounded benchmark:** compare fixed 500-ms and trigger configurations on
   quiet, busy and expiry-adjacent training/validation windows. Measure events/s,
   decisions/year projection, CPU/wall seconds, RAM, bytes, fill differences,
   utility and constraint failures. Preserve fixed seeds. Choose trigger thresholds
   using validation, not the final test period.
4. **Chronological protocol:** start with two independently fitted experiments:
   train 2016–2018 / validate 2019 / test 2020; train 2021–2023 / validate 2024 /
   test 2025–2026 available eligible history. Never train the 2020 evaluator on
   2021–2023. Subject to verified coverage and runtime budget, add annual rolling
   folds (three training years, one validation year, following year testing), and
   compare expanding training windows on development folds. Some 2026 windows
   were already examined in pilots: they are development evidence, not untouched
   final holdouts. Incomplete 2026 cannot supply a complete calendar-year episode.
   Every episode's
   full observation-to-resolution tail must remain inside its split; disallow
   opening contracts whose resolution would cross the boundary. Purge overlapping
   tails; keep seeds/overlapping windows grouped by market history. Publish exact
   eligible intervals before any fitting, and shrink them if evidence is missing.
5. **Initial annual collection:** propose eight complete training trajectories
   (four eligible year-long windows, two delay/exploration seeds), with one frozen
   behavior/model and clock version throughout each trajectory. This is a capacity
   pilot, not a claim that eight trajectories suffice. Broaden market regimes,
   portfolios and initial conditions before merely adding seeds. Increase counts
   only from learning curves and held-out-by-time validation evidence.
6. **Checkpointed execution:** one-hour-or-shorter compute chunks, checkpoint
   at least every five minutes of wall time, retaining source cursors, pending
   queues/orders, ledger, observable history, trigger anchor, RNG, policy identity
   and references to unlabeled records. Resume the *same* financial trajectory
   across jobs. A chunk boundary is not liquidation or a Monte Carlo endpoint.
   Assign complete-outcome labels only after the full year and required tail
   finish. Interrupted or data-incomplete paths remain unlabeled.
7. **Collect–fit–improve:** stream labeled samples from completed paths, normalize
   on training only, and bound fitting updates/time. Sample variable-time decision
   states without treating millions of correlated ticks as independent market
   evidence. Each improved policy collects a new versioned dataset; do not mix
   old continuation labels into new-policy values. Keep checkpoints and full loss
   curves, choose the stage on validation, and finally compare hold, Treasury
   hold-to-maturity, analytical carry and learned policy on identical test windows.

Before launching a campaign, produce a measured estimate:
`CPU_total = sum(event_cost + decision_count * search_cost) + fitting + evaluation`.
Specify aggregate CPU/GPU-hours, maximum worker concurrency, bytes/storage,
retry allowance, absolute wall deadline and hard stop behavior. Choose the
cash-cost cap using current region/machine pricing at that point. Alerts alone
are not a hard spending limit. Do not silently resume indefinitely, start bulk
downloads or assume a GPU fixes Python execution/constraint-checking cost.

### Primary platform references (checked 27 October 2026)

- [Batch components and resources](https://docs.cloud.google.com/batch/docs/get-started)
- [Batch task counts, parallelism and duration](https://docs.cloud.google.com/batch/docs/reference/rest/v1/projects.locations.jobs)
- [Cloud Run job task timeouts](https://docs.cloud.google.com/run/docs/configuring/task-timeout)
