# Parameters

GUI rates and allocations are percentages; `silver_strategy_gui.parameters`
converts them to decimal engine values. The scoring names below are the
production parameter names.

## Execution and costs

| Parameter | Meaning |
|---|---|
| `reactivity` | Execute a close-derived signal at the same close or the next available close. |
| `long_allocation_half_life_days` | Calendar-day smoothing half-life for the replicating-fund versus futures-plus-Treasury mix. |
| `short_allocation_half_life_days` | Calendar-day smoothing half-life for short-book notional. |
| `transaction_fee_bps` | Explicit fee, in basis points, charged to every one-way buy and sell. |
| `bid_ask_spread_bps` | Full quoted spread, in basis points; each one-way trade pays half of it. |

Trading costs are computed from changes in fund, Treasury, long-futures, and
short-futures positions. Opening trades, rebalances, rolls, and closing trades
are all charged. A trade of notional `N` therefore costs
`N * (transaction_fee_bps + bid_ask_spread_bps / 2) / 10,000`.
Reactivity is portfolio-level. Fee and spread assumptions are stored in each
commodity profile, so commodities can use different execution assumptions.

## Eligibility

| Parameter | Meaning |
|---|---|
| `positive_entry_rate` | Minimum lease signal at which the gradual long-futures leg starts entering. |
| `negative_short_start_rate` | Maximum lease signal at which the gradual short book starts entering. |
| `long_min_days` | Reject long contracts with fewer calendar days remaining. |
| `short_min_days` | Reject short contracts with fewer calendar days remaining. |
| `min_days` | Legacy JSON fallback applied to either side when its side-specific field is absent. |

When a long futures book exists, every selected short contract must also mature
strictly later than the latest selected base-long contract. This is a hard
eligibility rule, including for sticky positions; the independent short expiry
floor still applies when the base long leg is entirely the replicating fund.

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
portfolio.

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
export/import, and reset. The Sites host persists the current set across devices
when its strategy-parameter endpoint is available. The displayed current-preset
name is cleared as soon as a strategy parameter differs from the loaded preset,
and updates immediately after save, load, or delete.
