# Parameters

Parameter names in code may differ initially; this document defines their intended meaning.

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
| `long_line_intercept` | Long boundary value at zero maturity. |
| `long_line_slope` | Long boundary change per year of maturity. |
| `long_relative_strength` | Relative score sensitivity to boundary distance. |
| `short_line_intercept` | Short boundary value at zero maturity. |
| `short_line_slope` | Short boundary change per year of maturity. |
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

## GUI requirements

Every parameter must have a label, unit, tooltip, valid range, default, and reset behavior. Saved configurations should be versioned so renamed parameters can be migrated safely.
