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

Define the boundary as:

```text
L(m) = intercept + slope * m
```

The intended geometry links a longer maturity with a larger absolute rate requirement. The exact slope sign therefore depends on whether the plotted quantity is the signed lease rate or its absolute adverse/favorable magnitude.

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

## Separate pure-maturity multiplier

After the rate/boundary multiplier, an optional independent multiplier can
express a preference that does not depend on the lease-rate curve:

```text
u_i = clip(maturity_days_i / pure_maturity_scale_days, 0, pure_maturity_clip)
pure_long_i  = max(0, 1 - long_pure_maturity_strength * u_i)
pure_short_i = max(0, 1 + short_pure_maturity_strength * u_i)
final_i = boundary_adjusted_score_i * pure_side_i
```

It therefore favors shorter contracts in the long book and longer contracts in
the short book. Both strengths default to zero, which exactly preserves prior
rankings. This multiplier is applied only after eligibility, so it cannot make
an otherwise ineligible contract tradable.

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
- boundary value;
- signed distance;
- base score;
- relative multiplier;
- pure-maturity multiplier;
- final score;
- eligibility result;
- final target weight.

## Parameter-only preview

The GUI provides separate previews beside the long and short weighted-selection
controls.  Each heatmap shows only the parameter-driven multiplier

```text
P_side(T, r) = rate_boundary_multiplier_side(T, r)
               * pure_maturity_multiplier_side(T)
```

against signed annualized lease rate and days to maturity.  It does not portray
the lease-edge base score, the contracts available on a particular date, the
normalization across those contracts, or the total book notional.  The preview
must label this distinction and show the complete raw-score and normalized-weight
formulas alongside the heatmap, mapping each formula symbol to its GUI control.

This definition keeps the preview exact in both gradual and fixed-maximum modes.
In fixed-maximum mode the omitted base score depends on that day's cross-sectional
minimum long or maximum short lease rate, so an exact contract-weight preview
would require an actual dated curve.

## Tests

At minimum, test that:

1. increasing a long contract's rate while maturity is fixed increases its long adjustment;
2. making a short contract's rate more negative while maturity is fixed increases its short adjustment;
3. equal boundary distances produce equal relative multipliers;
4. ineligible contracts never receive weight;
5. setting `k = 0` reproduces the base-score ranking;
6. normalization and clipping behave consistently at extreme values.
7. positive pure-maturity strength favors shorter longs and longer shorts;
8. zero pure-maturity strength reproduces the previous score exactly.
