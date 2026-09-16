# Empirical BTC execution costs and waiting deadlines

This research extension is selected by `paired_repricing_mode="empirical"`
within BTC `cost_aware_paired` trade replay. Existing `fixed` and `adaptive`
settings preserve their previous meaning. The empirical discretionary-entry
path supports proportional fees; fixed, minimum-ticket and per-contract fees
currently make empirical entry unavailable rather than using a mismatched
calibration policy. It estimates whether a funded spot-sale/futures-buy transfer can complete within a specified waiting time,
and what adverse price movement must be budgeted to do so. It does not submit
live orders or guarantee execution.

## Why the execution budget precedes quantity selection

The preceding three-day adaptive comparison did not complete a pair. The
futures limit could move, but its approved target quantity was fixed. Released
spot cash, entry fees and the reserve therefore imposed a price ceiling that
remained below the later futures prints. Raising only the limit could not solve
that funding constraint.

The empirical policy evaluates candidate source quantities from a BTC size grid,
capped by `paired_max_unpaired_btc`, available holdings and the transfer-fraction
limit. With the default 0.01 BTC unmatched cap, the 0.1 BTC study row remains
a liquidity diagnostic and is not an executable candidate.
For each size and eligible futures contract it asks the calibration model for
a price budget that meets the requested joint-completion fraction before the
execution deadline. It then calculates the affordable futures quantity using
that budget, fees and the cash reserve **before** fixing the transfer quantity.
The accepted source/target ratio may consequently be below one. Missing or
insufficient calibration support leads to KEEP, rather than an assumed zero
execution cost.

This is still a funded transfer among spot, long futures and a cash-interest
proxy. Source cash must actually be released before it can fund the futures
leg. There is no third exchange order or actual Treasury-security fill. The
underlying KEEP/SWAP horizon calculation, variation settlement and Treasury-rate
availability assumptions are described in
[COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md).

## Which distributions answer the question

Execution slippage and completion time must be measured together. A distribution
containing only filled orders would omit the attempts that waited unsuccessfully
or filled just one leg. The useful completion measure for a size, deadline and
price allowance is the fraction of **all sampled opportunities** that complete
both legs within those constraints.

The report distinguishes:

- **Price movement**, in price-basis basis points, which determines the funded
  execution budget and is interpretable across maturities.
- **Lease-rate slippage**, in annualized lease basis points, measured against
  the observation that authorized the attempt. Positive adverse slippage means
  a lower executed lease. The conversion retains the original observation's
  remaining maturity, so mere passage of execution time cannot masquerade as
  a change in quoted carry.
- **Waiting time**, measured from decision start to the relevant fill or pair
  completion. Missed deadlines and partial fills remain separate outcomes;
  they are not replaced with fictitious fills at the deadline.

Annualization can make a small price discrepancy look large when a contract is
near expiry. Comparisons must therefore retain the contract/maturity context,
price-basis quantity, fee convention and the original observation time.
The fee-adjusted effective entry lease remains a separate diagnostic from
expected terminal BTC wealth or realized strategy profit.

A requested confidence such as 95% is an empirical coverage target, not a
statistical 95% confidence interval, a service guarantee or a promise about
future data. The minimum-sample rule is necessary but does not make overlapping
or serially correlated observations independent. Sparse contracts and large
requested quantities can legitimately have no qualifying budget. Calibration
samples all eligible fresh-quote cohorts, while the strategy trades only the
subset that passes its economic hurdle. That selection, changing liquidity and
market conditions can shift realized slippage/completion away from the fitted
group. The scored comparison must therefore check actual accepted instructions;
a fitted 95% group fraction alone is not evidence of 95% strategy completion.

## Candidate economics includes unsuccessful execution

A candidate uses all modeled execution outcomes, including noncompletion, in
its expected terminal-BTC comparison with KEEP. Fees, funded target quantities,
retained cash and the cost of restoring an unmatched spot sale belong in that
comparison. An outcome beyond the accepted hard price allowance cannot simply
be scored as a successful cheap fill.

An entry must pass both the all-outcome expected gain hurdle and the
conservative budget-priced gain hurdle. These two outcomes are reported
separately. In particular, `expected_edge_btc` is a conservative weighted
empirical estimate, while `conservative_budget_edge_btc` evaluates the approved
price budget. The model charges the worst sampled futures fill price when the
funded hedge is a smaller prefix of the studied hedge. Failed restoration is
valued conservatively against retaining cash; unmeasured restoration fills do
not create assumed BTC profit. Neither outcome is a realized return.

If the mandatory conservative budget-priced forecast already fails its gain
hurdle, the engine rejects that candidate or holding horizon before evaluating
weighted execution scenarios. This avoids unnecessary work without changing
which candidate can be accepted. Skipped `expected_*` fields are null and an
`execution_expected_evaluation` marker explains the omission; the decision's core values
remain the conservative forecast and must not be read as an evaluated empirical
mean. The full forecast still uses the declared holding-horizon assumptions
rather than predicting future spot prices.

## The admitted policy: a small source tranche, then a protected hedge

An empirical instruction is one small source tranche. It accumulates compatible
partial spot prints until the entire approved source quantity has filled, then
waits for all source-fill acknowledgements. Partial source fills do not pause
for each individual acknowledgement; the resting source order remains live. It
then submits the funded futures hedge for the approved target quantity, allowing partial future fills.
It does not alternate spot and future slices within the same empirical
instruction. Further instructions accumulate toward a larger portfolio change.

Both orders are **protected marketable limit orders** under a price allowance
approved at decision time. The spot sell cannot go below its admitted floor;
the futures buy cannot go above its admitted cap or what actual released cash
can fund. The cap is a loss/slippage bound, not a promise that printed liquidity
exists. The target hedge still waits its decision and order-delivery delays
after source acknowledgement and requires subsequent compatible tape volume.

This policy deliberately keeps the admitted small instruction's price budget
fixed. It does not continually tighten a fresh lease/economic threshold or
chase a moving quote during the attempt: the estimated completion fraction is
conditional on the policy actually studied. The earlier `adaptive` mode remains
the separately selectable continually repriced effective-lease policy.

The waiting deadline is measured from decision start, so decision and transport
delays consume part of the allowance. Observation delay determines what was
known when that decision started. Both entry legs expire at the deadline;
prints at exactly the deadline are too late. Only strictly earlier fills count;
noncompletion remains a failed instruction even if subsequent recovery succeeds.
Any source restoration is a separate funded, bounded recovery attempt, with
its own fees and outcome. It reserves only cash released by unmatched spot
sales; collateral for matched futures stays assigned to those futures. After
pending acknowledgements, a fresh observed spot price determines a protected
buy limit and affordable restoration quantity, capped by the unmatched BTC.
The recovery allowance is the larger of the admitted execution budget and
`paired_price_limit_bps`. Decision and order-delivery delays still apply. Recovery receives its own waiting-time budget and can fail
for missing fresh observations, absent prints or its own deadline. Incomplete
recovery leaves explicit residual cash or inventory, with no automatic infinite
retry, rather than a fictitious completed pair or an indefinite active-pair lock.
Finishing both legs is verified from actual quantities, prices and fees,
not inferred from the model confidence.

Forced pre-expiry future-to-spot reductions are a risk-exit exception. They
use bounded source quantities, funded limits and finite deadlines, but have no
calibrated execution prediction. They must not be described as satisfying the
empirical confidence target. Discretionary calibrated entries remain
spot-to-futures only.

## What is calibrated

Hypothetical opportunities start on a 60-second grid when spot and a futures
observation are available, executable, within the configured quote age and
within the configured cross-feed skew. The default study uses source quantities
0.0001, 0.001, 0.01 and 0.1 BTC and waiting horizons 0.5, 1, 2, 5, 10, 30 and 60
seconds. Each size/deadline scenario is an alternative use of the tape, not an
additional simultaneous claim on the same printed liquidity.

The shadow policy first accumulates the full source quantity and then hedges the
same BTC quantity after the acknowledgement, decision and delivery delays. Its
hedge quantity is at least the funded replay's target quantity, which fees and
the reserve can reduce. This conservative quantity convention must remain
explicit when comparing predicted and observed completion.

For an observed spot/future pair `(S_obs, F_obs)` and completed VWAP pair
`(S_exec, F_exec)`, gross price-basis slippage is:

```text
raw_basis_slip_bps = 10,000 × (F_exec / S_exec − F_obs / S_obs)
annualized_lease_slip_bps = raw_basis_slip_bps / original_years_to_expiry
```

The study excludes fees, which enter the economics separately, and includes the
configured adverse spread/slippage adjustment to simulated execution prices.
The required joint price budget is the maximum of zero, the worst adverse
spot-sale price movement and the worst adverse futures-buy price movement
encountered along the completed path. This is distinct from final VWAP basis
slippage: passing a VWAP bound alone would not establish that every fill stayed
inside the posted limits.

Completed-path budgets are conservatively rounded up into fixed basis-point
bins. Failures have no finite qualifying budget. The requested quantile uses
rank `ceil(confidence × all_sampled_opportunities)`, so a 95% setting cannot
ignore nonfills or be satisfied by the 95th percentile of successful fills only.
A contract-and-maturity group is preferred when it has sufficient samples;
otherwise the model pools contracts in the same maturity bucket (0–1, 1–3, 3–7, 7–14, 14–30,
30–90, 90–365 or over 365 days). Quantity and waiting time must match a calibrated
group; unavailable support fails closed.

Completion denominators, status counts and budget-bin counts are exact.
Scenario forecasting and displayed price quantiles use deterministic bounded
samples of actual paths, stratified by status and budget bin, with exact
stratum-count weights. The default retains up to four paths per stratum; VWAP
and quantity-weighted fill times summarize within-path executions. These price
quantiles and expected-cost scenarios are approximations, not a retained copy
of every historical path. The model records this approximation and a hash of
its frozen sufficient statistics, source manifest and configuration.

## Causal calibration and the first scored test

The initial strategy files declare these UTC windows before assessing results:

| Purpose | Window | Use |
|---|---|---|
| Calibration | `[2026-06-06, 2026-06-16)` | Estimate execution outcomes and freeze the empirical model |
| Scored short test | `[2026-06-16, 2026-06-26)` | Evaluate ten subsequent days without fitting to their outcomes |

Calibration excludes an entire cohort when its decision time plus the maximum
studied waiting horizon and fill-acknowledgement delay crosses the cutoff. No
future completion label or partly observed end-of-calibration cohort enters the
frozen model. The scored test must retain its model cutoff, parameters, market-data identity and engine revision. Loading or resuming a
checkpoint must preserve that same fitted state and pending orders.

The initial comparison uses 0.5-second allocation decisions, 100 ms each for
observation, decision and order-to-market delay, and estimated proportional
fees of 10 bp per side. These delays apply to initial instructions, the
conditional hedge and recovery; they also apply to replacements in the adaptive
comparison. Fill acknowledgement is a separate existing setting. The saved adaptive
comparison uses the same scored period and economic parameters without the
empirical execution policy.

Before launching a longer empirical run, inspect at least this ten-day
scored test for completion fractions, waiting-time and slippage distributions,
missed deadlines, partials, recovery outcomes, fees, net BTC versus KEEP/direct
holding, and accounting/audit consistency. A result with no accepted or completed
transfers cannot validate the requested completion coverage. Keep prior fixed
and adaptive runs as separate evidence with their original engine revisions.
The available tape contains 90 total days. Ten preceding calibration days leave
at most 80 scored days; a 90-day scored empirical test requires at least 100 days
of suitable data. No longer empirical run is included in this short-test gate.

## Saved files and inspection

The comparable strategies are saved in the repository:

- `strategies/research-btc-paired-empirical-10day-500ms-latency-100ms-fee-10bp.json`
- `strategies/research-btc-paired-adaptive-10day-500ms-latency-100ms-fee-10bp.json`

The empirical preset exposes confidence, minimum support, calibration days,
execution waiting time, BTC size grid and maximum study horizon. The result's
`trade_replay.execution_study` contains the calibration boundaries, complete /
partial / unfilled / censored counts and the waiting-time distribution tables.
The GUI offers scope/maturity and size selectors to inspect completion,
price-budget, raw-basis and annualized-lease quantiles.

The execution diagnostics compare predicted and actual completion and retain
all instruction outcomes, deadline misses, residual cash and restoration counts.
Waiting-time and slippage statistics include their sample counts, mean, p50,
p90, p95, p99 and maximum when available. The live slippage statistics use
matched executed quantities, which can include a partly completed instruction;
the study's price quantiles use fully completed shadow paths. These sample
counts therefore need not match. Neither percentile substitutes for the
full-attempt completion denominator. Keep each prediction's selected model group, size, budget, deadline and sample count with its realized
outcome so calibration and replay can be compared on the same terms.

The displayed instruction wait is elapsed time to completion, deadline or
end-of-window censoring, rather than completion time among successes alone.
The source wait is to the first source fill; the hedge wait spans first source
fill to last recorded target fill. Summaries retain 1-ms waiting-time and
0.01-bp slippage histogram resolution, with quantiles rounded to their bins.
An end-of-window-censored attempt is displayed as unavailable for deadline
success and excluded from both the resolved completion denominator and mean
prediction. The displayed counts make those denominators explicit. Counts and
endpoint labels are necessary to interpret the mean or percentile.

Selected-period XLSX exports contain `Execution outcomes`; `Execution study`
retains the full frozen calibration summary with its own dates. Individual
cohort rows remain in the full audit's `btc_execution_study` stream. See
[SPREADSHEET_EXPORT.md](SPREADSHEET_EXPORT.md).

## Data and interpretation limits

The available BTC archive contains historical trades and their printed volume,
not bid/ask snapshots or order-book depth. The execution study and replay use
this tape-participation proxy. Printed prices and quantities do not establish
that a resting order had queue priority or that an immediate market hedge could
consume the same liquidity. Any marketable hedge remains a bounded simulation
requiring later compatible printed volume; no fill is invented from a quote.

The study cannot measure unrecorded spread, book depletion, own-market impact,
venue routing failures or security-level Treasury execution. BTC/USDT-to-USD
parity, USD-linearized futures and the cash-interest proxy remain explicit
assumptions. A successful ten-day test is evidence about this model and window,
not certification of native inverse futures or a live trading system.

## Verified deployment and comparison evidence

Preview revision `e02934abf0505da478af9c552983a25dd37dcd18` passed
[workflow 35155749804](https://github.com/leviitzhak/keep_and_lease/actions/runs/35155749804),
including artifact upload and all application checks. Authenticated browser
inspection confirmed the full SHA, ready engine and restored completed empirical
result. The simulation code matches
`6fd1ae2a4fa24b28a8a5972e8445975a2f5a8fd2`; the later revision changes the audit
checker and documentation only. The deployment replay gate passed 315 Python
tests and local GUI validation passed 34 checks; the earlier focused censoring correction passed
14 tests.

The original empirical deployment workflow `35147345496` passed every
application check but failed overall on final artifact-evidence upload with
`403 Forbidden`. It is not reported as a successful workflow; the subsequent
workflow above completed successfully.

| Run | Immutable engine | Status |
|---|---|---|
| Adaptive baseline `d1da8ce988ec49d890d61e89aa8fe040` | `663e60c5b10bb98675baf7785b66b64d18ea6b34` | Completed; independent full audit passed |
| Empirical `69d512c2e4da4cd8b1fa27a9870c0769` | `6fd1ae2a4fa24b28a8a5972e8445975a2f5a8fd2` | Completed with no attempts; corrected independent full audit passed |

Both scored windows are June 16–26 UTC, with the parameters recorded above.
The baseline audit verified 1,728,000 valuations and 208,501 events with zero
findings. Ending marked wealth was $90,147.9872149967, a −9.8520127850% return
and −13.2318217575% maximum drawdown. Excess versus direct holding was
0.000000606523 BTC (about 60.65 satoshis, or $0.036266), after $0.02667675337 in
fees.

Eleven baseline attempts ended as two partial, seven timed-out and two cancelled
instructions, with **zero fully completed instructions**. Its five fills were
three 0.00009-BTC spot sales and two futures fills totaling about 0.0001791315 BTC.
Matched source quantity was 0.00018 BTC and 0.00009 BTC remained unmatched at the
end. The two matched legs took 165.570658 and 199.630893 seconds, while the final
unmatched interval lasted 34,582.955615 seconds. The older adaptive soft timeout
therefore did not implement completion within a 30-second deadline. Timeout
reason counts overlap final-status counts and must not be added as independent
attempts.

The baseline is internally consistent but does not establish profitable complete
transfers or timely execution.

### Empirical result: the requested coverage was unsupported

The empirical replay completed all 1,727,999 scheduled decisions with KEEP.
There were **zero submitted attempts, zero fills and zero fees**. Exact raw-data
verification passed for all 67,452 calibration labels and 219,165 scored events.
The corrected independent full audit passed all 1,728,000 valuations and dataset
checksums with zero findings. Ending wealth was $90,147.95094856317, or
1.5076420869746658 BTC—exactly the initial BTC quantity. Maximum drawdown was
−13.231850554073699%; no orders, fills or fees occurred.

The first full audit flagged ten floating-point comparison discrepancies from
one near-expiry June 12 07:56 calibration cohort repeated across size/wait
alternatives. The maximum annualized difference was about 3.0716e-7 bp, caused
by amplifying an approximately 1e-12-bp raw-basis rounding difference over a
short remaining maturity. The stored annualized value exactly matches its
stored raw-basis value divided by original maturity. The independent checker
now retains its independent raw-price/basis assertion and separately verifies
that stored annualization relation. The implemented and reviewed correction
passes all 17 focused tests, including rejection of a +0.01-bp annualization
corruption and forged raw basis. The original failed audit is retained.
The corrected full-archive audit passed with zero findings. NAV reconstruction
and stored annualization relation errors were zero; the maximum independent
raw-basis error was 4.0714e-12 bp. No simulation data changed. The checker/docs
correction is pushed at `e02934abf0505da478af9c552983a25dd37dcd18`; workflow
`35155749804` succeeded, including the 315-test replay gate in 21.076 seconds,
all application checks, replay extension and artifact upload. Authenticated
browser verification confirmed this exact final preview revision, a ready
engine and the restored completed empirical result.

Among groups with at least 100 calibration observations, none of the 252
contract/maturity/size/wait cells or 196 pooled maturity/size/wait cells has a
finite 95% joint execution budget. The strongest contract cell was
`BTC-31JUL26`, 30–90 days remaining, 0.0001 BTC and a 60-second wait: 269/387
completed, or 69.51%. The strongest pooled cell was 14–30 days remaining,
0.0001 BTC and a 60-second wait: 277/425 completed, or 65.18%. These maxima use
different groups and do not constitute directly comparable same-cell estimates.

All 219,143 emitted paired candidate decisions carried
`joint_confidence_unattainable`; their three executable size checks generated
657,429 rejections, and none was selected. The much larger scheduled-decision
count also includes times without a fresh eligible candidate. The run therefore retained the position because the requested coverage was
unsupported; there are no actual trades from which to verify that coverage.

An exact raw-label example illustrates why completed-only slippage is
insufficient. For the pooled 14–30-day maturity group and 0.001 BTC, there were
425 sampled opportunities:

| Waiting deadline | Completed | Completion fraction |
|---|---:|---:|
| 30 seconds | 222 / 425 | 52.2353% |
| 60 seconds | 269 / 425 | 63.2941% |

Among the 222 **completed** 30-second paths, exact raw-label statistics were:

| Metric | Median | 95th percentile |
|---|---:|---:|
| Gross price-basis slippage | −0.4490 bp | +4.8475 bp |
| Original-maturity annualized lease slippage | −9.597 bp/year | +98.660 bp/year |
| Pair completion wait | 7.250 s | 24.594 s |

Positive slippage means a worse executed lease. These empirical quantiles were
reconstructed from every applicable raw label; they are not the compact GUI
scenario-reservoir approximation. The annualized quantile uses each cohort's
own original remaining maturity. A +98.660 annualized basis-point shortfall is
about 0.9866 percentage points of annualized lease rate, not a 98.66% price loss.

The 203 noncompleted opportunities at 30 seconds remain in the denominator.
A 95th-percentile slippage or waiting time among the 222 completed paths cannot
provide 95% overall completion. No actual-instruction waiting or slippage
statistics exist for the empirical scored run because none was admitted. This
short test therefore does not validate realized 95% coverage or a profitable
paired transfer, and no longer empirical replay has been started.

Extending the scored portfolio period with this same frozen model and 95%
setting cannot create a supported discretionary entry: none of its sufficiently
sampled groups has a finite 95% execution budget. More scored dates do not add
calibration observations or relax that gate. A longer-wait sensitivity study,
additional execution data or a deliberately changed acceptance setting must
first establish usable support before another longer portfolio replay is
informative. Any such change requires a newly declared calibration/evaluation
comparison; it is not an improvement demonstrated by the present no-trade run.
