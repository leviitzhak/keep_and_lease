# Contract Scoring

## Purpose

Distribute each futures-leg target across eligible maturities using the lease
edge, signed distance from the configured maturity line, and the optional pure
maturity preference. Eligibility and total leg sizing remain separate from
contract weighting.

## Variables

For contract `i`:

- `r_i`: signed annualized lease rate;
- `T_i`: days to maturity;
- `B_i`: non-negative lease edge after eligibility;
- `L(T_i)`: configured linear maturity/rate boundary;
- `s`: configured score-rate scale;
- `k`: relative boundary strength;
- `c`: normalized boundary-distance clip;
- `h`: pure-maturity strength;
- `T_0`: pure-maturity scale;
- `c_T`: pure-maturity clip;
- `Q`: total notional target for the leg.

The boundary is

```text
L(T) = r_1 + (r_2 - r_1) * (T - T_1) / (T_2 - T_1)
```

## Eligibility and base edge

Eligibility is applied before scoring:

```text
long eligible  := r_i >= long_entry_rate
short eligible := r_i <= short_entry_rate
```

Fixed-maximum mode deliberately ignores the entry-rate gate and treats every
contract above the minimum-maturity floor as eligible. Its cross-sectional base
edge is measured from that day's least-attractive available lease:

```text
B_long_i  = r_i - min_j(r_j)
B_short_i = max_j(r_j) - r_i
```

Gradual mode uses the entry threshold:

```text
B_long_i  = r_i - long_entry_rate
B_short_i = short_entry_rate - r_i
```

The entry/full thresholds size `Q`; they do not normalize contract weights.

## Signed logit

Signed line distance is

```text
d_long_i  =  r_i - L_long(T_i)
d_short_i = -r_i - L_short(T_i)
```

and the bounded relative contribution is

```text
z_i = clip(d_i / s, -c, c)
A_rate_i = k * z_i
```

The independent maturity contribution is

```text
u_i = clip(T_i / T_0, 0, c_T)
A_maturity_long_i  = -h_long  * u_i
A_maturity_short_i = +h_short * u_i
```

The complete dimensionless signed score (softmax logit) is

```text
q_i = B_i / s + A_rate_i + A_maturity_i
```

A point below its maturity line can therefore have a negative score. It is not
discarded: if it remains eligible, softmax gives it a smaller positive weight.

## Softmax allocation

Eligible logits are converted to weights with a stable softmax:

```text
q_max = max_j(q_j)
weight_i = Q * exp(q_i - q_max) / sum_j(exp(q_j - q_max))
```

Subtracting `q_max` does not change relative weights and prevents overflow.
The implementation clamps the shifted exponent at `-700` so an eligible
contract does not become an exact zero merely through floating-point underflow.
A final floating-point remainder is placed on the largest weight, ensuring

```text
sum_i(weight_i) = Q
```

even when every signed score is negative or all scores are equal.

The existing score-rate scale `s` controls the sensitivity of both the lease
edge and boundary distance. No separate softmax-temperature parameter is
introduced initially.

## Diagnostics and heatmap

The inspected-day diagnostics show:

- eligibility;
- boundary and signed distance;
- base lease edge;
- signed rate/line adjustment;
- signed pure-maturity adjustment;
- final logit;
- softmax target weight.

The independent long and short heatmaps show either:

- the parameter-only signed logit
  `A_rate(T,r) + A_maturity(T)`; or
- with the toggle enabled, the entry-based diagnostic logit
  `B_entry(r)/s + A_rate(T,r) + A_maturity(T)`.

A heatmap is not a normalized portfolio weight because softmax normalization
depends on all contracts available on the selected date.

## Required invariants

1. Ineligible contracts receive no allocation.
2. Every eligible contract receives a positive softmax weight.
3. Weights exactly sum to the requested leg target.
4. Increasing a long lease rate, other inputs fixed, increases its logit.
5. Making a short lease rate more negative increases its logit.
6. Equal logits split the target equally.
7. Below-line contracts may have negative logits without disappearing.
8. Fixed-maximum mode preserves its full notional independently of entry rates.
