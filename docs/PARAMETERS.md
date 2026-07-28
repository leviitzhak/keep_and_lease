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

The GUI exposes two points for each maturity boundary. Slope and intercept are implied internally and are not editable primary parameters.

| Parameter | Meaning |
|---|---|
| `long_line_maturity_1` | First maturity anchor for the long boundary. |
| `long_line_rate_1` | Long-boundary lease rate at `long_line_maturity_1`. |
| `long_line_maturity_2` | Second maturity anchor for the long boundary; must exceed the first. |
| `long_line_rate_2` | Long-boundary lease rate at `long_line_maturity_2`. |
| `long_relative_strength` | Relative score sensitivity to boundary distance. |
| `short_line_maturity_1` | First maturity anchor for the short boundary. |
| `short_line_rate_1` | Short-boundary lease-rate value at `short_line_maturity_1`, using the scoring boundary's documented sign convention. |
| `short_line_maturity_2` | Second maturity anchor for the short boundary; must exceed the first. |
| `short_line_rate_2` | Short-boundary lease-rate value at `short_line_maturity_2`, using the scoring boundary's documented sign convention. |
| `short_relative_strength` | Relative score sensitivity to boundary distance. |
| `score_rate_scale` | Rate scale used to make boundary distance dimensionless. |
| `score_adjustment_clip` | Maximum absolute normalized adjustment. |

For either boundary:

```text
slope     = (rate_2 - rate_1) / (maturity_2 - maturity_1)
intercept = rate_1 - slope * maturity_1
```

Saved configurations using the former intercept/slope fields must be migrated by evaluating the old line at the selected default anchor maturities. Migration must preserve the represented line exactly, subject only to numeric precision.

## Gradual allocation

| Parameter | Meaning |
|---|---|
| `neutral_band` | Region around neutral signal with no or minimal position. |
| `full_allocation_threshold` | Signal magnitude reaching maximum allocation. |
| `allocation_shape` | Linear or another explicitly documented interpolation. |
| `etf_transition_band` | Gradual Treasury/ETF transition band; intended default about ±1 percentage point around expense ratio. |

## Treasury selection

Treasury parameters should mirror commodity parameters where meaningful, replacing lease rate with interest rate. The GUI should support shortest-maturity rolling and weighted allocation across maturities.

## Statistics controls

| Parameter | Meaning |
|---|---|
| `statistics_minimum_position_size` | Optional minimum absolute position size for inclusion in maturity-versus-rate-change-return scatters. |
| `statistics_return_normalization` | Display the rate-change return relative to total portfolio capital or to the relevant leg–commodity position. |
| `statistics_regression_enabled` | Show or hide the optional linear regression overlay and associated statistics. |

These controls affect presentation and statistical summaries only; they must not alter the backtest positions or returns.

## GUI requirements

Every parameter must have a label, unit, tooltip, valid range, default, and reset behavior. Saved configurations should be versioned so renamed parameters can be migrated safely. The anchor maturities must use the same maturity unit as contract scoring, and the anchor rates must use the same annualized-rate unit as the underlying lease-rate or Treasury-rate data.