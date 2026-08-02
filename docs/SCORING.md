# Contract Scoring

## Purpose

Rank eligible futures using both economic attractiveness and maturity preference without allowing maturity to override the lease-rate eligibility rules.

The canonical implementation is `public/maturity_scoring.py`. The deployed browser worker installs `public/canonical_scoring_adapter.py`, which routes the historical backtest's active scoring calls through that module. The older helper definitions retained in `backtest_silver_lease_strategy.py` are compatibility code and are not the deployed scoring implementation.

## Variables

For contract `i` on decision date `t`:

- `r_i`: annualized lease rate. For Treasury instruments, use the annualized interest rate instead.
- `m_i`: maturity measure, preferably year fraction to expiry.
- `b_i`: existing/base economic score before maturity adjustment.
- `L(m_i)`: configured linear boundary in rate–maturity space.
- `d_i`: signed vertical distance from the boundary.
- `k`: boundary-relative adjustment strength.
- `q`: independent pure-maturity preference strength.

Define the boundary as:

```text
L(m) = intercept + slope * m
```

The intended geometry links a longer maturity with a larger absolute rate requirement. The exact slope sign therefore depends on whether the plotted quantity is the signed lease rate or its absolute adverse/favorable magnitude.

## Long-side boundary adjustment

For a signed lease-rate representation, define:

```text
d_long_i = r_i - L_long(m_i)
```

A contract above the long boundary has a positive adjustment; one below it has a negative adjustment.

The adjustment is relative to the existing score:

```text
boundary_long_i = b_i * max(0, 1 + k_long * normalized(d_long_i))
```

where `normalized(...)` is dimensionless and bounded or robustly scaled.

## Short-side boundary adjustment

The short-side signed distance is:

```text
d_short_i = -r_i - L_short(m_i)
```

This follows the project decision that a more negative lease rate should improve the short score while still trading off against maturity.

```text
boundary_short_i = b_i * max(0, 1 + k_short * normalized(d_short_i))
```

The base short score `b_i` is positive for an economically attractive short candidate, for example from the magnitude by which the rate passes the short threshold.

## Independent pure-maturity multiplier

The pure-maturity preference is computed only across eligible contracts. Let `m_min` and `m_max` be the shortest and longest eligible maturities. Map each maturity to a coordinate in `[-1, 1]`:

```text
u_long_i  = (midpoint - m_i) / half_range
u_short_i = -u_long_i
```

If there is only one eligible maturity, both coordinates are zero.

The multiplier is:

```text
M_long_i  = max(0, 1 + q_long  * u_long_i)
M_short_i = max(0, 1 + q_short * u_short_i)
```

Thus positive `q_long` favors shorter long contracts, while positive `q_short` favors longer short contracts. Setting either strength to zero exactly preserves the boundary-adjusted ranking.

The final score is:

```text
final_i = boundary_i * M_i
```

## Eligibility gates

Apply gates before scoring:

```text
long eligible  := r_i >= long_eligibility_threshold
short eligible := r_i <= short_eligibility_threshold
```

An ineligible contract receives no allocation and does not affect the pure-maturity range.

## Boundary normalization requirements

The boundary distance `d_i` has rate units, while its multiplier must be dimensionless. The implementation exposes a rate scale and clipping limit. Preferred properties:

- stable across dates;
- resistant to one outlier contract;
- symmetric for equal distances around the boundary;
- clipped to prevent sign reversal or extreme leverage.

The explicit implementation is:

```text
z_i = clip(d_i / rate_scale, -z_max, z_max)
boundary_i = b_i * max(0, 1 + k * z_i)
```

## Weight conversion

For eligible contracts with positive final scores:

```text
weight_i = book_target * final_i / sum_j(final_j)
```

Alternative concentration controls may be applied afterward, but they must preserve the book target after renormalization.

## Required diagnostics

The inspected-day table and hover data should show:

- contract identifier;
- maturity and rate;
- eligibility result;
- boundary value;
- signed distance;
- base score;
- boundary-relative multiplier;
- boundary-adjusted score;
- pure-maturity coordinate;
- pure-maturity multiplier;
- final score;
- final target weight.

## Tests

At minimum, test that:

1. increasing a long contract's rate while maturity is fixed increases its boundary adjustment;
2. making a short contract's rate more negative while maturity is fixed increases its boundary adjustment;
3. equal boundary distances produce equal boundary-relative multipliers;
4. ineligible contracts never receive weight or affect the maturity range;
5. setting boundary strength to zero removes the boundary adjustment;
6. setting pure-maturity strength to zero preserves the boundary-adjusted ranking;
7. equal-rate long contracts favor the shorter maturity when `q_long > 0`;
8. equal-rate short contracts favor the longer maturity when `q_short > 0`;
9. a single eligible maturity receives a neutral pure-maturity multiplier;
10. normalization and clipping behave consistently at extreme values.
