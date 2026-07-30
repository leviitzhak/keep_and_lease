# Contract Scoring

## Purpose

Rank eligible futures using economic attractiveness, the rate–maturity boundary, and a separate pure-maturity timing preference without allowing maturity to override the lease-rate eligibility rules.

## Variables

For contract `i` on decision date `t`:

- `r_i`: annualized lease rate. For Treasury instruments, use the annualized interest rate instead.
- `m_i`: maturity measure, preferably year fraction or calendar days to expiry.
- `b_i`: existing/base economic score before maturity adjustment.
- `L(m_i)`: configured linear boundary in rate–maturity space.
- `d_i`: signed vertical distance from the boundary.
- `k`: boundary-distance relative adjustment strength.
- `q_long`, `q_short`: independent pure-maturity preference strengths.

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

The intended short-side signed distance is:

```text
d_short_i = -r_i - L_short(m_i)
```

This follows the project decision that a more negative lease rate should improve the short score while still trading off against maturity.

```text
boundary_short_i = b_i * max(0, 1 + k_short * normalized(d_short_i))
```

The base short score `b_i` is positive for an economically attractive short candidate, for example from the magnitude by which the rate passes the short threshold.

## Pure-maturity timing multiplier

The pure-maturity multiplier is independent of lease rate and independent of the boundary distance. It reflects only the timing advantage:

- long futures favor shorter maturities because the underlying is obtained sooner;
- short futures favor longer maturities because delivery is deferred longer.

Calculate the maturity range using eligible contracts only. Let `m_min`, `m_max`, and `m_mid` be the minimum, maximum, and midpoint eligible maturities. For more than one eligible maturity:

```text
u_long_i  = (m_mid - m_i) / ((m_max - m_min) / 2)
u_short_i = -u_long_i
```

Both coordinates lie in `[-1, 1]`. When only one maturity is eligible, use `u_i = 0` so the multiplier is neutral.

```text
pure_long_i  = max(0, 1 + q_long  * u_long_i)
pure_short_i = max(0, 1 + q_short * u_short_i)
```

A strength of zero exactly preserves the boundary-adjusted ranking. Long and short strengths are independent parameters.

## Final score

Apply the boundary multiplier first and the pure-maturity multiplier second:

```text
final_long_i  = boundary_long_i  * pure_long_i
final_short_i = boundary_short_i * pure_short_i
```

The pure-maturity preference changes relative allocation only. It does not determine total book exposure and cannot make an ineligible contract eligible.

## Eligibility gates

Apply gates before calculating either multiplier:

```text
long eligible  := r_i >= long_eligibility_threshold
short eligible := r_i <= short_eligibility_threshold
```

An ineligible contract receives no allocation and does not affect the eligible maturity range.

## Boundary normalization requirements

The distance `d_i` has rate units, while the boundary multiplier must be dimensionless. The implementation must expose or document the scale. Preferred properties:

- stable across dates;
- resistant to one outlier contract;
- symmetric for equal distances around the boundary;
- optionally clipped to prevent sign reversal or extreme leverage.

One explicit form is:

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
- boundary value and signed distance;
- base score;
- boundary multiplier and boundary-adjusted score;
- pure-maturity coordinate and multiplier;
- final score;
- final target weight.

## Tests

At minimum, test that:

1. increasing a long contract's rate while maturity is fixed increases its boundary adjustment;
2. making a short contract's rate more negative while maturity is fixed increases its boundary adjustment;
3. equal boundary distances produce equal boundary multipliers;
4. ineligible contracts never receive weight or affect the maturity range;
5. setting `k = 0` reproduces the base-score ranking before pure-maturity adjustment;
6. setting `q_long = q_short = 0` reproduces the boundary-adjusted ranking;
7. equal-rate long contracts rank from shorter to longer when `q_long > 0`;
8. equal-rate short contracts rank from longer to shorter when `q_short > 0`;
9. a single eligible maturity receives a neutral pure-maturity multiplier;
10. normalization and clipping behave consistently at extreme values.
