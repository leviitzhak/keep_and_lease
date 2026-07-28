# Contract Scoring

## Purpose

Rank eligible futures using both economic attractiveness and maturity preference without allowing maturity to override the lease-rate eligibility rules.

## Variables

For contract `i` on decision date `t`:

- `r_i`: annualized lease rate. For Treasury instruments, use the annualized interest rate instead.
- `m_i`: maturity measure, preferably year fraction to expiry.
- `b_i`: existing/base economic score before maturity adjustment.
- `L(m_i)`: configured linear boundary in rate–maturity space.
- `d_i`: signed vertical distance from the boundary.
- `k`: relative adjustment strength.

## Anchor-point parameterization

The user-facing boundary is defined by two understandable points in rate–maturity space rather than by an intercept and slope:

```text
(m_1, r_1)
(m_2, r_2), with m_2 > m_1
```

The boundary through those points is:

```text
L(m) = r_1 + ((r_2 - r_1) / (m_2 - m_1)) * (m - m_1)
```

The implementation may derive and retain the equivalent slope and intercept internally:

```text
slope     = (r_2 - r_1) / (m_2 - m_1)
intercept = r_1 - slope * m_1
```

Slope and intercept are derived values, not primary GUI parameters. The two maturity values must use the same unit as `m_i`, and the two rate values must use the same annualized-rate convention as `r_i`.

Long and short books may use separate pairs of anchor points. The intended geometry links a longer maturity with a larger absolute rate requirement. The exact direction of each boundary therefore depends on the signed-rate convention used for that book.

## Long-side adjustment

For a signed lease-rate representation, define:

```text
d_long_i = r_i - L_long(m_i)
```

A contract above the long boundary has a positive adjustment; one below it has a negative adjustment.

The adjustment must be relative to the existing score, not an unrelated additive quantity. A recommended implementation is:

```text
final_long_i = b_i * (1 + k_long * normalized(d_long_i))
```

where `normalized(...)` is dimensionless and bounded or robustly scaled. Examples include division by a configured rate scale, cross-sectional robust scale, or clipping after standardization.

## Short-side adjustment

The intended short-side signed distance is:

```text
d_short_i = -r_i - L_short(m_i)
```

This follows the project decision that a more negative lease rate should improve the short score while still trading off against maturity.

A recommended relative combination is:

```text
final_short_i = b_i * (1 + k_short * normalized(d_short_i))
```

The base short score `b_i` should itself be positive for an economically attractive short candidate, for example from the magnitude by which the rate passes the short threshold.

## Eligibility gates

Apply gates before scoring:

```text
long eligible  := r_i >= long_eligibility_threshold
short eligible := r_i <= short_eligibility_threshold
```

An ineligible contract receives no allocation regardless of final score.

## Normalization requirements

The distance `d_i` has rate units, while the multiplier must be dimensionless. The implementation must expose or document the scale. Preferred properties:

- stable across dates;
- resistant to one outlier contract;
- symmetric for equal distances around the boundary;
- optionally clipped to prevent sign reversal or extreme leverage.

One explicit form is:

```text
z_i = clip(d_i / rate_scale, -z_max, z_max)
final_i = b_i * max(0, 1 + k * z_i)
```

The `max(0, ...)` protects against a negative ranking score unless negative scores have a separately defined meaning.

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
- both configured boundary anchor points;
- boundary value at the contract maturity;
- signed distance;
- base score;
- relative multiplier;
- final score;
- eligibility result;
- final target weight.

The rate-versus-maturity scatter should draw the two anchor points and their connecting line. The implied slope and intercept may be shown as read-only diagnostics.

## Tests

At minimum, test that:

1. increasing a long contract's rate while maturity is fixed increases its long adjustment;
2. making a short contract's rate more negative while maturity is fixed increases its short adjustment;
3. equal boundary distances produce equal relative multipliers;
4. ineligible contracts never receive weight;
5. setting `k = 0` reproduces the base-score ranking;
6. normalization and clipping behave consistently at extreme values;
7. the boundary passes exactly through both configured anchor points;
8. the anchor-point formula reproduces the internally derived slope/intercept form;
9. configurations with `m_2 <= m_1` are rejected.