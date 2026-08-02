# Parameters

GUI rates and allocations are percentages; `silver_strategy_gui.parameters`
converts them to decimal engine values. The scoring names below are the
production parameter names.

## Global

| Parameter | Meaning |
|---|---|
| `execution_delay_days` | Trading-day delay between signal and execution; default `1`. |
| `max_total_exposure` | Maximum portfolio gross exposure. |
| `max_long_exposure` | Maximum long-book exposure. |
| `max_short_exposure` | Maximum short-book exposure. |
| `minimum_holding_days` | Optional turnover constraint. |
| `transaction_cost_bps` | Assumed trading cost. |

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

## Gradual allocation

| Parameter | Meaning |
|---|---|
| `neutral_band` | Region around neutral signal with no or minimal position. |
| `full_allocation_threshold` | Signal magnitude reaching maximum allocation. |
| `allocation_shape` | Linear or another explicitly documented interpolation. |
| `etf_transition_band` | Gradual Treasury/ETF transition band; intended default about ±1 percentage point around expense ratio. |

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
when its strategy-parameter endpoint is available.
