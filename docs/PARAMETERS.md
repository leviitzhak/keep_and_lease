# Parameters

GUI rates and allocations are percentages; `silver_strategy_gui.parameters`
converts them to decimal engine values. The scoring names below are the
production parameter names.

Trade replay restrictions, fractional execution delay, coverage and CSV/audit outputs
are documented in [BTC_SUBSECOND_GUI.md](BTC_SUBSECOND_GUI.md).

## Cost-aware funded BTC transfers

`trade_strategy` defaults to `legacy`. Select `cost_aware_paired` only with BTC
trade-tape data, 100% BTC portfolio weight, regular/linear futures and no short
book. Old parameter files without this key reset to the legacy policy, and all
new paired settings reset to defaults when absent. Paired settings are global;
the Bitcoin leg still supplies proportional trading fees, half-spread, slippage,
custody/proxy expense, execution delay and quote-age limits. Existing allocation
scores and fixed/minimum-hold controls do not drive the paired policy.

| Parameter | Default | Meaning |
|---|---|---|
| `paired_horizon_days` | `1,3,7,14,30` | Positive calendar-day holding horizons, comma-separated or a JSON array. Both alternatives use the same future time; expiry and maximum forecast length constrain it. |
| `paired_max_horizon_days` | `30` | Maximum credible forecast length. |
| `paired_max_transfer_fraction` | `0.25` | Maximum fraction of each held source position considered per instruction. A grid also evaluates 25%, 50% and 75% of that maximum. |
| `paired_uncertainty_bps` | `5` | Extra BTC-equivalent surplus in basis points of transferred capital. It is a safety allowance, not a confidence interval. |
| `paired_cost_buffer_multiplier` | `1` | Values above one require additional coverage of modeled future transaction costs. Future costs already enter KEEP/SWAP; sunk past costs do not. |
| `paired_min_gain_btc` | `0` | Additional required incremental BTC wealth. |
| `paired_cash_reserve_fraction` | `0.01` | Capital reserve kept outside the transferred position; fraction in `[0,1)`. |
| `paired_max_quote_skew_seconds` | `1` | Maximum source-time gap between the spot/source/target observations used together. |
| `paired_repricing_mode` | `fixed` | `adaptive` derives spot-to-future limits from the net-BTC economic boundary. `empirical` estimates joint completion and price cost at a waiting deadline, then budgets that cost before funded quantity selection. Missing values preserve old strategies. |
| `paired_observation_delay_seconds` | `0` | Common delay before market observations become available, added to the applicable per-feed delay. |
| `paired_decision_delay_seconds` | `0` | Processing time for a frozen observed snapshot, including adaptive replacement decisions. |
| `paired_order_delay_seconds` | omitted | Order/replacement transport delay. Omitted or null inherits Bitcoin `execution_delay_seconds`; an explicit nonnegative value overrides it. |
| `paired_execution_confidence` | `0.95` | Empirical target fraction of all sampled opportunities that complete both legs within the waiting time and price allowance; includes nonfills in the denominator. Not a statistical confidence interval or guarantee. |
| `paired_execution_min_samples` | `100` | Minimum calibration support required for an empirical execution estimate. Unsupported candidates remain KEEP. |
| `paired_calibration_days` | `10` | Historical calibration length preceding the scored empirical replay; the fitted model is frozen for the scored window. |
| `paired_waiting_seconds` | `30` | Empirical pair execution deadline measured from the decision start. Decision and transport consume this budget. Deadline handling retains misses and recovery outcomes. |
| `paired_execution_size_grid_btc` | `0.0001,0.001,0.01,0.1` | Positive source-BTC quantities considered by the empirical execution study and candidate evaluation, subject to position and transfer-fraction limits. |
| `paired_study_max_horizon_seconds` | `60` | Maximum execution waiting horizon studied from the calibration tape. It is an execution-time limit, distinct from forecast holding horizons in days. |
| `paired_spot_feed_delay_seconds` | `0` | Additional spot-specific observation delay. |
| `paired_futures_feed_delay_seconds` | `0` | Additional futures-specific observation delay. |
| `paired_response_delay_seconds` | `0` | Delay from actual exchange-side fill to the strategy's fill acknowledgement. Funding changes at the fill time. |
| `paired_max_unpaired_btc` | `0.01` | Maximum unmatched source quantity newly introduced by a chunk; also caps the entire source tranche of one empirical instruction. Larger size-grid rows can remain diagnostic-only. Missing liquidity can leave residual exposure; the audit retains it. |
| `paired_max_legging_seconds` | `30` | Fixed/adaptive timeout for a pending transfer/unpaired chunk: stops further source fills and retains funded recovery inventory/orders. Empirical entries instead use the explicit waiting deadline and bounded recovery behavior. |
| `paired_price_limit_bps` | `10` | Initial adverse movement allowance from authorizing prices, retained as the fixed-mode limit. Forecasts budget it with half-spread/slippage. Adaptive entry limits use the effective-lease/economic boundary and can move beyond this initial allowance. |
| `paired_max_rate_age_days` | `7` | Maximum source-observation age for new discretionary transfers. Stale rates continue funding valuation. |
| `paired_roll_lead_days` | `1` | Excludes near-expiry destination contracts and prioritizes funded attempts to exit/roll the entire held contract within this window, overriding the discretionary surplus requirement. Freshness, funding and execution constraints still apply; stale rates permit only an expiry exit to spot. |
| `paired_spot_fixed_fee_usd` | `0` | Additive USD charge once per spot child-order ticket, across partial fills. |
| `paired_spot_min_fee_usd` | `0` | Floor on total spot ticket commission, not an extra fixed charge. |
| `paired_futures_fixed_fee_usd` | `0` | Additive USD charge once per futures child-order ticket. |
| `paired_futures_min_fee_usd` | `0` | Floor on total futures ticket commission. |
| `paired_futures_per_contract_fee_usd` | `0` | USD per modeled one-BTC linear contract unit; not an actual venue fee schedule. |
| `paired_settlement_interval_seconds` | `86400` | JSON/API research setting: fixed UTC interval for last-trade-mark variation settlement. Not a verified exchange settlement calendar. |
| `paired_settlement_basis_bps` | `0` | JSON/API forecast assumption for expiry reference relative to flat spot. Does not replace recorded final delivery metadata. |

The empirical waiting time cannot exceed its study horizon. The replay must
have the configured calibration history available before its scored start;
that history does not become part of the scored portfolio. Confidence is
strictly between zero and one, minimum samples is a positive integer, and the
calibration days, waiting time and size-grid values must be positive.

Empirical discretionary entries currently support proportional fees only.
Nonzero fixed, minimum-ticket or per-contract commissions leave those empirical
entries unavailable; the fixed/adaptive modes retain their ticket-fee support.

In the new mode only, `slv_expense` means optional annual BTC custody/proxy expense
(GUI percentage, engine decimal) and decreases directly held BTC over elapsed
time. The forecast uses the same cost. The original allocation tape policy keeps
its original zero-proxy-expense/spread/slippage restriction.

Rates come from the checked-in new FRED snapshot when available. The cash proxy
uses a normalized 91-day DTB3 investment yield, not a quoted one-day bill or a
matched-maturity security. Date-only rates become available after the modeled
next US federal business release day and following UTC midnight. Publication
times are assumed rather than historically verified. See
[COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md) for economic
formulas, funding/execution rules, export diagnostics and acceptance limits.
[EMPIRICAL_LEASE_EXECUTION.md](EMPIRICAL_LEASE_EXECUTION.md) describes the joint
slippage/completion model, causal calibration and separate ten-day test.

## Global

| Parameter | Meaning |
|---|---|
| `execution_delay_days` | Historical placeholder; the current engine executes at the same observed close (delay `0`). |
| `btc_data_source` | `minute` (default) or `trade_tape` for the immutable BTC trade replay dataset advertised by the server. |
| `trade_initial_capital_usd` | Positive initial capital for trade replay; default $100,000. Participation and fully-funded futures capacity apply to actual quantities at this capital. |
| `execution_interval_seconds` | For trade replay, a positive multiple of 0.001 seconds. The selected period must fit the deployment's advertised maximum decision count. For candles: BTC-only strategy evaluation and execution interval, including fractional seconds when supported by the data. `0` uses every common spot/futures observation. A positive value must be a whole multiple of the detected data resolution and may be used when BTC is the sole commodity; a standalone Treasury sleeve is still allowed. |
| `trade_plot_max_points` | Trade-replay chart sampling ceiling, 500–10,000 points; default 3,000. It changes only returned/displayed plot density and never changes execution frequency, order generation, fills, accounting or full-resolution audit rows. |
| `max_total_exposure` | Maximum portfolio gross exposure. |
| `max_long_exposure` | Maximum long-book exposure. |
| `max_short_exposure` | Maximum short-book exposure. |
| `minimum_holding_days` | Optional turnover constraint. |
| `transaction_cost_bps` | Assumed trading cost. |
| `futures_contract_type` | `regular` for linear USD payoff or `inverse` for a native BTC payoff ledger. Configured independently per commodity. |
| `inverse_payoff_conversion_fee` | Fixed proportional fee charged on the absolute USD value whenever accumulated native BTC payoff is converted at the current spot rate. Separate from bid/ask and position-change costs. |
| `inverse_min_conversion_btc` | Absolute accumulated BTC payoff required before conversion and recognition in strategy USD returns. `0` converts every interval. Positive and negative native payoffs net in the pending balance. |

For BTC, the existing fund-side allocation is implemented as a direct holding
of BTC itself. This is a naming and instrument-description distinction only:
it keeps the same spot return, allocation, extension, and decomposition
arithmetic as the generic replicating-fund leg. There is no separate ETF price
series or fund expense for the direct BTC holding.

Trade replay records both the desired futures exposure and the actually filled
exposure. `target_futures_notional_usd` is the strategy target before observed
partial-fill/capacity constraints, `futures_notional_usd` is the marked notional
of filled futures, and `free_collateral_usd = cash_usd -
abs(futures_notional_usd)`. The diagnostic `collateralization_ratio` is
`cash_usd / abs(futures_notional_usd)` while futures are held; the current
fully-funded replay requires a minimum ratio of 1.

## Eligibility

| Parameter | Meaning |
|---|---|
| `long_eligibility_threshold` | Minimum lease rate for long futures eligibility. |
| `short_eligibility_threshold` | Maximum lease rate for short futures eligibility. |
| `minimum_days_to_expiry` | Reject contracts too close to expiry. |
| `maximum_days_to_expiry` | Optional maximum maturity. |

## Maturity-line scoring

| Parameter | Meaning |
|---|---|
| `long_maturity_line_intercept` | Long boundary value at zero maturity. |
| `long_maturity_line_slope_per_year` | Long boundary change per year of maturity. |
| `long_relative_strength` | Relative score sensitivity to boundary distance. |
| `short_maturity_line_intercept` | Short boundary value at zero maturity. |
| `short_maturity_line_slope_per_year` | Short boundary change per year of maturity. |
| `short_relative_strength` | Relative score sensitivity to boundary distance. |
| `score_rate_scale` | Rate scale used to make boundary distance dimensionless. |
| `score_adjustment_clip` | Maximum absolute normalized adjustment. |
| `long_pure_maturity_strength` | Independent relative preference for shorter long maturities; `0` disables it. |
| `short_pure_maturity_strength` | Independent relative preference for longer short maturities; `0` disables it. |
| `long_pure_maturity_scale_days` | Long-side days of maturity corresponding to one pure-maturity adjustment unit. |
| `long_pure_maturity_clip` | Maximum normalized long-side pure-maturity adjustment. |
| `short_pure_maturity_scale_days` | Short-side days of maturity corresponding to one pure-maturity adjustment unit. |
| `short_pure_maturity_clip` | Maximum normalized short-side pure-maturity adjustment. |

## Gradual allocation

| Parameter | Meaning |
|---|---|
| `neutral_band` | Region around neutral signal with no or minimal position. |
| `full_allocation_threshold` | Signal magnitude reaching maximum allocation. |
| `allocation_shape` | Linear or another explicitly documented interpolation. |
| `etf_transition_band` | Gradual Treasury/ETF transition band; intended default about ±1 percentage point around expense ratio. |

## Allocation smoothing and reactivity

| Parameter | Meaning |
| --- | --- |
| `reactivity` | `same_day` executes the close-derived signal at that close; `next_day` executes it at the following available close. The default is `same_day`. |
| `long_allocation_half_life_days` | Calendar-day half-life for moving the replicating-fund versus Treasury-plus-long-futures allocation toward its current target. `0` disables smoothing. |
| `short_allocation_half_life_days` | Calendar-day half-life for moving total short-book notional toward its current target. `0` disables smoothing. |

Smoothing is applied to allocation sizes after the current curve has produced
its targets. It does not average lease-rate inputs or delay current contract
ranking. After one half-life, half of the gap to the current target remains.

## Treasury selection

Treasury parameters should mirror commodity parameters where meaningful, replacing lease rate with interest rate. The GUI should support shortest-maturity rolling and weighted allocation across maturities.

Implemented controls are `treasury_asset`, `treasury_allocation_mode`, and
`bond_mode`. Treasury can be combined with commodities or run as a standalone
portfolio. Treasury yields are aligned causally: the latest observable mark is
carried forward and accrues until the next mark becomes observable. Time-series
interpolation between daily yield marks and backfilling from future marks are
not permitted; interpolation across simultaneously available curve tenors is
still used for maturity matching. On an intraday market timeline, a date-only
Treasury closing mark is conservatively available at 00:00 UTC the next day.

## Per-commodity overrides

Global parameters are defaults for every sleeve. Any parameter can be overridden
through `commodity_parameters`, for example:

```json
{"commodity_parameters": {"gold": {"positive_entry_rate": 2.0}}}
```

Flat keys such as `gold__positive_entry_rate` are also accepted. This avoids a
product-specific scoring path and applies equally to any registered commodity.

## GUI requirements

Parameter schema version 2 supports automatic restore, named save/load, JSON
export/import, and reset. The GCP GUI additionally exposes checked-in files from
`strategies/` in the Saved strategy selector; choosing one loads its exact saved
parameter document, and subsequent edits are marked as modifications of that
repository strategy. Saved server-backtest visibility is separately curated in
the browser so selected runs stay in the default list across sessions while
**Show all runs** remains available.
