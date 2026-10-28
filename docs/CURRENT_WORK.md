# Current work

## Clarified rollout strategy — 28 October 2026

[The revised prompt](research/post_decision_value/TREASURY_LEARNING_NEXT_PROMPT.md)
now specifies sampled max–min terminal-outcome labels using complete random paths,
fixed-deadline action selection by V(post-state,remaining time), independently
calculated liquidation from sequential subsequent trades and explicit policy BTC
repurchases. Closing duration is ignored in the current objective/horizon.
[Definitions and later horizon-policy comparisons](research/post_decision_value/ROLLOUT_MAXMIN_SPEC.md).
Constant-lookahead T, horizon-selected V/h, the broader synthetic market generator,
UI, separate liquidation-value/time models and more realistic cancellation are
deferred. Exact search is only for tiny reference toys.
This is documentation only; old models/results remain unchanged and no run launched.
Latest clarification makes multiple horizons from each sampled post-state explicit,
reserves split-local liquidation buffers, and reuses the existing optional event
clock for the planned collector. The new collector remains unimplemented. The nine
existing `test_weighted_clock.ClockTests` passed again (0.092 s test time).

## Next task scope — 27 October 2026

[The revised handoff](research/post_decision_value/TREASURY_LEARNING_NEXT_PROMPT.md)
adds exact synthetic policy/optimal reference values, error plots and repeated
network decisions after an initial hold-only diagnostic. The interactive local
explorer and Windows launcher are a **separate later implementation**, recorded
in [the UI plan](research/post_decision_value/STATE_VALUE_EXPLORER_PLAN.md).
These are documentation changes only; no new training, oracle or UI is claimed.

## Treasury learning gate and long-history readiness — 27 October 2026

The bounded Treasury smoke completed in 18.13 seconds with 1,200 optimizer updates.
All 211 software tests pass, but the policy gate fails: the network chose cash in
all 64 held-out synthetic cases, missing all 16 profitable bills and all 32
profitable training cases. Configs, checkpoints, losses, action predictions and
exact sources are in [the report](research/post_decision_value/TREASURY_SANITY.md).
Years-long training still requires a streaming PDV runner, historical cash/funding/
expiry eligibility, cloud integration and budget gates. No long job was launched.

## Weighted growth and event clock — 27 October 2026

New pilot CLI runs use continuous weighted positive growth with an unweighted
negative-growth penalty (default weights 0.5/0.5, lambda 10). Schema 3 has 88,901
parameters. Optional event triggering uses received price/premium/report changes
and known timers; exchange events remain exact. 207 tests pass; a two-minute
cached hold probe reduced decisions 240 to 6 with identical outcomes and all 14
events processed. This is not an annual speed or profitability result.
Conditional premium orders and a checkpointed Google Cloud training campaign
are documented, not launched. See [the plan](research/post_decision_value/WEIGHTED_EVENT_TRAINING_PLAN.md).

## Cash assets and conditional growth objective — 27 October 2026

The research branch supports spot BTC, fixed-ratio proxy shares and Treasury
units in its exact delayed replay, native action grid and schema-v2 value model.
Cash purchases require settled USD; receipts follow owned units and explicit
dates. At that phase, new pilot runs defaulted to the conditional maximum objective:
minimum growth if negative, maximum otherwise. Old reports/checkpoints keep
their original semantics. The bounded multi-asset learning run is **synthetic**,
underperforms hold, and is not accepted as a trading policy. Historical cash
execution and through-expiry financing evidence remain incomplete. See
[the implementation and validation report](research/post_decision_value/CASH_ASSETS_AND_OBJECTIVE.md).
No deployment, live order or data acquisition was performed.

## Sparse value search and expiry inputs — 26 October 2026

The research-only branch now defaults to a 32-attempt endpoint/random action grid,
with configurable effort. The prior futures union is complete as a logical
120,105,433-row dataset. Bounded public acquisition added delivery values for all
528 expired contracts, 17,695 daily settlement events and 2,703 Treasury quote
dates; 55 expired contracts still have missing daily events. The current neural
action set at that phase remained futures-only, and its minimum-growth score did not reward
growth of only one commodity. The new carry accounting fixtures and
[report](research/post_decision_value/CARRY_GRID_AND_EXPIRY_INPUTS.md) describe
these limits, measured search costs and reproduction. No deployment or annual
training was performed. Earlier phase reports below retain their original scope.

## Full cached analytical study — 26 October 2026

The post-decision research branch now has a separate hourly-decision analytical
runner covering every cached Dec26/Mar27 print over June 6–September 3 (180 files,
486,203 rows). Fixed 54/18/18-day calibration/validation/test sets carry portfolios
continuously within each set. Four predefined size/price grids were compared.
Only the smaller, tighter grid passed calibration; it remained entirely inactive
on validation and test. The original analytical baseline lost 0.13% BTC and gained
0.483782% USD contractually in the held-out test, but failed dated funding stress
in both seeds. These are not observed settlement or liquidation results. See
[the protocol and report](research/post_decision_value/ANALYTICAL_90_DAY.md).
The multi-year archive is not included: only its metadata was verified locally.
No application deployment, new download or neural training was performed.

## Post-decision value research — 25 October 2026

Standalone implementation on `agent/btc-post-decision-value-v1`: signed linear/inverse commodity accounting, delayed observable/exchange replay, constrained candidate search and complete-outcome value learning. No application deployment or integration into existing strategy defaults. See [POST_DECISION_VALUE_V1.md](POST_DECISION_VALUE_V1.md) for conventions, commands, acceptance scope and research limitations. The [final pilot](research/post_decision_value/RESULTS.md) and independent audit are complete: 43 new tests and 83 existing tests pass. The learned policy underperforms hold (-2.095% joint held-out growth versus 0%), so historical profitability and promotion remain unaccepted. Artifacts are retained under `docs/research/post_decision_value/`.


## Rolling worst lease execution — 2026-09-24

Branch `agent/rolling-worst-lease-execution` is based on GitHub master
`ed070c30602a68d54cbb67fb36f301b67946cca9`. The opt-in rolling mode adds causal
price-window bounds, signed execution allowances, expected hedge cost, either
already-funded first leg, market recovery and exact per-limit/per-tranche audit.
Local focused tests cover timing, restart, both directions, rolls, funding,
exports and independent audit checking. Historical completion improvement and
deployed-preview validation remain unverified for this change. See
[ROLLING_LEASE_EXECUTION.md](ROLLING_LEASE_EXECUTION.md).

## Expiry-amortized cost-aware ranking — 2026-09-22

The prior branch `agent/cost-aware-amortized-ranking` implemented the revised
allocation design on top of the funded paired-transfer foundation. The new
`amortized_rank` selector starts in direct BTC, compares destination returns
after every remaining transfer/expiry cost with held KEEP returns that exclude
sunk entry cost, and admits only a buffered annualized improvement. It uses
expiry rather than an arbitrary holding-horizon list, an absolute BTC delta cap,
and symmetric adaptive paired limits. `horizon_wealth` preserves earlier saved
runs and remains the only selector accepted by the empirical calibration.

The declared first real-tape test is `[2026-06-06, 2026-06-09)` at 500-ms
decisions, 10-bp proportional fees, 100-ms observation/decision/order delays,
0.01-BTC maximum delta and 5-bp minimum annual improvement. Its preset is
`strategies/research-btc-amortized-rank-3day-500ms-fee-10bp.json`. Local focused
economic/execution tests and the complete browser suite pass. Deployed job and
audit results are pending and must be recorded here before TODO acceptance.

## Empirical execution costs for funded BTC transfers — 2026-09-16

The owner requested implementation of feasible funded transfers and holding
horizons evaluated by expected net BTC wealth versus keeping the current
position. The opt-in `trade_strategy="cost_aware_paired"` path is implemented
beside the preserved default allocation policy. The GUI provides a strategy
selector, economics/funding/latency/fee controls and a bounded example.

The current extension studies joint spot/futures completion and execution-price
slippage at explicit waiting deadlines, then budgets that cost before approving
and sizing a transfer. The research setting is opt-in
`paired_repricing_mode="empirical"`; `fixed` and `adaptive` retain their existing
meaning. Read [EMPIRICAL_LEASE_EXECUTION.md](EMPIRICAL_LEASE_EXECUTION.md) for the
calibration, deadline and evaluation protocol, and
[COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md) for the underlying
funding and economics. Key components are `funded_ledger.py`,
`paired_transfer_economics.py`, `paired_transfer.py` and
`paired_transfer_rates.py`; `btc_trade_backtest.py` connects them to the
existing durable worker, charts, audit and export flow.

The new ledger separates marks, unsettled P&L and cash settlement, tracks full
funding/reservations and charges fixed/minimum/per-unit/proportional commissions
by durable child-order ticket. Transfers share one pair ID and bounded source-
first funding through partial fills and delayed responses. Economics compare
equal-capital KEEP/SWAP candidates over feasible sizes and common horizons,
including prospective costs and uncertainty allowances. Forecasts assume flat
spot, residual basis converging toward a configured settlement reference and
current normalized cash-proxy yield; they do not guarantee profitable exits.

The adaptive-entry extension adds `paired_repricing_mode="adaptive"` for
spot-to-future transfers. The desired effective entry lease comes from the
existing net-BTC economic hurdle; target limits incorporate acknowledged source
fill prices and fees. Explicit observation, frozen-snapshot decision and
order-arrival delays also apply to repricing. Replacements take effect on
arrival, and durable audit records preserve requested versus applied limits.
Old presets remain fixed, while reverse transfers and rolls retain their
existing funded execution. Partial slices accumulate the requested delta using
the accepted funding ratio; cash accrual is the third component, with no actual
Treasury-security fill or atomic cross-venue guarantee.

Six FRED series were retrieved as an immutable NEW snapshot covering June
1–September 4, 2026, under `public/data/paired-rates/`. The overlap matches the
retained source observations. DTB3 discount quotes are normalized through a
91-day benchmark price into an ACT/365 investment yield. The new availability
model waits for the next federal business release day and following UTC
midnight; actual historical publication timestamps remain unverified. Source
hashes, retrieved times, normalization version and rate-age gating are audited.

## Validation and limits

The original fixed-limit implementation includes focused tests for economics, funding and fee
accounting, causal Treasury normalization/availability, paired execution and
checkpoint continuity, runner integration and detailed exports. All 219 Python
and 33 JavaScript checks passed. The complete preview deployment, paired GUI and
workbook checks, and replay extension passed for commit
`d1fb73487e1f9aee42064d57799d55edd8445dd8`. See
[COST_AWARE_FUNDED_VALIDATION.md](COST_AWARE_FUNDED_VALIDATION.md) for the workflow,
preview URL, exact results and research limitations.

The adaptive extension passed 257 Python and 37 relevant JavaScript checks.
Preview workflow `35140804706` passed for
`663e60c5b10bb98675baf7785b66b64d18ea6b34`. Its three-day fixed/zero-delay
adaptive/100-ms-per-stage comparison completed on `[2026-06-06, 2026-06-09)`.
All three full audits passed, but none completed a pair. Their ending differences
from direct holding were respectively −$0.68229, −$0.07773 and −$0.00555;
remaining unmatched spot quantities were 0.01, 0.00114 and 0.00008 BTC. Smaller
losses came from less unmatched selling and lower fees, not demonstrated lease
income. The original fixed target quantity made the funding cap bind despite
repricing. The empirical extension therefore evaluates execution cost before
fixing its funded target quantity.

The verified preview on `agent/cost-aware-funded-transfers` is
`e02934abf0505da478af9c552983a25dd37dcd18`.
[Workflow 35155749804](https://github.com/leviitzhak/keep_and_lease/actions/runs/35155749804)
**succeeded**, including artifact upload and all application health,
rendered-GUI/multi-commodity, subsecond, paired-export and replay-extension
checks. An authenticated browser check independently verified the exact SHA,
ready server engine and restored completed empirical result at the
[GCP preview](https://keep-and-lease-preview-web-vfk2j2rgoq-zf.a.run.app/).
The latest deployment replay gate passed 315 Python tests; 34 local GUI tests
also passed. The earlier focused zero-fill, pending-decision censoring checker correction passed 14 checks.

The empirical engine was introduced at
`6fd1ae2a4fa24b28a8a5972e8445975a2f5a8fd2`; the later preview revision changes only
the audit checker and documentation, not simulation behavior. Its earlier
workflow `35147345496` passed all application checks but failed overall solely
on final artifact-evidence upload with `403 Forbidden`. That historical failure
remains distinct from the successful replacement workflow.

Empirical job `69d512c2e4da4cd8b1fa27a9870c0769` started at 20:40 UTC on
September 16 on immutable engine `6fd1ae2a4fa24b28a8a5972e8445975a2f5a8fd2`. It
froze 67,452 execution labels from `[2026-06-06, 2026-06-16)` and completed
`[2026-06-16, 2026-06-26)`, both UTC. All 1,727,999 scheduled decisions were KEEP:
zero submitted attempts, fills and fees. Raw-label/event verification passed
for all 67,452 study rows and 219,165 scored events. The corrected independent
full audit also passed all 1,728,000 valuations and dataset checksums with zero
findings. Ending wealth was $90,147.95094856317 or 1.5076420869746658 BTC, exactly
the initial BTC quantity; maximum drawdown was −13.2318505541%. There are no
actual empirical execution-coverage or slippage observations because no
instruction was admitted. The first full valuation audit identified ten near-expiry floating-point comparison discrepancies in a
single June 12 07:56 calibration cohort repeated across size/wait alternatives.
The largest annualized difference was about 3.0716e-7 bp and the independently
recomputed raw-basis difference about 1e-12 bp. Stored annualization exactly
matches stored raw basis divided by original maturity. A checker-only numerical
correction is implemented and reviewed; it retains the independent raw-basis
assertion and tests that stored relation separately. All 17 focused tests pass,
including rejection of a +0.01-bp annualization corruption and forged raw basis.
The original failed audit is preserved. The corrected full-archive audit passed
with zero findings: NAV reconstruction and stored annualization relation errors
were zero, and maximum independent raw-basis error was 4.0714e-12 bp. The
checker/docs patch is pushed at `e02934abf0505da478af9c552983a25dd37dcd18`;
workflow `35155749804` succeeded, including its 315-test replay gate in 21.076
seconds, application checks, replay extension and artifact upload. The exact
new preview SHA, ready engine and restored completed empirical result were
also verified in the authenticated browser. Simulation and historical job
results are unchanged.

No calibrated group with at least 100 observations supports the requested 95%
joint-completion target at any studied size/wait combination: this holds across
252 contract/maturity groups and 196 pooled maturity groups. The strongest
qualifying contract cell completed 269/387 (69.51%) within 60 seconds; the
strongest pooled cell completed 277/425 (65.18%). All 219,143 emitted paired
candidate decisions rejected with `joint_confidence_unattainable` (657,429 size
rejections over three executable sizes). The policy kept the position because
the requested execution coverage was unsupported, not because its realized
trades achieved 95% coverage. Exact distribution examples are recorded in
`EMPIRICAL_LEASE_EXECUTION.md`. Extending scored dates with the same frozen
model and 95% setting cannot create a supported discretionary entry; none of
its sufficiently sampled groups has a finite qualifying budget. A longer-wait
sensitivity study or other explicit change to model support/acceptance is
needed before a longer portfolio replay can answer the execution question.

The same-period adaptive baseline `d1da8ce988ec49d890d61e89aa8fe040` completed on
engine `663e60c5b10bb98675baf7785b66b64d18ea6b34`. Its independent full audit
passed with zero findings across 1,728,000 valuations and 208,501 events. It
ended at $90,147.987215 (−9.852013%), about $0.036266 or 0.000000606523 BTC above
direct holding, after $0.026677 in fees. Eleven attempts produced five fills,
zero complete instructions, two partial, seven timed-out and two cancelled
instructions. The two matched legs took 165.571 and 199.631 seconds; 0.00009 BTC
remained unmatched. This validates accounting, not completion within the desired
30-second waiting time or profitable fully completed transfers.

The ten-day empirical test must be reviewed before any longer empirical run.
The current archive has 90 total days; reserving ten preceding days for causal
calibration leaves at most 80 scored days. A 90-day scored empirical run would
require at least 100 days of suitable data. None is being started as part of
this short-test acceptance, and no calibration or coverage requirement is
relaxed to force trades.

The mode remains a BTC tape-participation, USD-linear research proxy with
cash-interest accrual. Native inverse settlement, historical quote depth,
security-level Treasury prices, verified venue margin/payment calendars,
full-period holdout acceptance and complete realized-versus-KEEP attribution
are not certified. Synthetic Treasury facilities in the ledger are separate
from the GUI's cash proxy. Timeouts preserve unresolved inventory instead of
assuming liquidity existed. No leverage or live trading is enabled.

[NEXT_STRATEGY_IMPLEMENTATION.md](NEXT_STRATEGY_IMPLEMENTATION.md) retains the
complete acceptance specification; [TODO.md](TODO.md) distinguishes implemented
research behavior from remaining venue/data/validation work. The previous
current-work history remains in
[CURRENT_WORK_HISTORY_2026-09-15_PRE_STRATEGY_PLAN.md](CURRENT_WORK_HISTORY_2026-09-15_PRE_STRATEGY_PLAN.md).
Earlier completed 90-day legacy computations stay completed; this new strategy
requires its own performance and holdout assessment. The single GCP preview is
the authoritative deployment target; local Sites remains deferred.

Rolling execution now offers both `relative_price` (default) and `spot` limit
anchors via `paired_limit_anchor`; both are retained in saved audit contexts.
