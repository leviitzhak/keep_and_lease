# Full-silver long performance investigation

## Reproducible setup

The investigated sleeve uses the repository's materialized silver market data
from 1969-01-02 through 2002-09-30 (8,303 return intervals). It allocates 100% of
capital as long silver-futures notional with Treasury collateral, disables the
short book, and uses a 30-day long expiry floor. Allocation smoothing is
disabled. The baseline uses the shipped shortest-maturity selection; a second
run uses weighted lease-rate SoftMax selection. Headline runs set both
transaction-cost inputs to zero.

This is a historical model result, not a claim about returns after 2002. The
cross-maturity individual-contract archive ends in 2002 and cannot be extended by
a continuous benchmark without losing the curve needed by the strategy.

## Results

| Measure | Shortest maturity | Weighted lease rate | Direct replicating-fund proxy |
|---|---:|---:|---:|
| Compounded return | 58.90% | 358.17% | 95.11% |
| CAGR | 1.38% | 4.61% | 2.00% |
| Maximum drawdown | 93.84% | 88.91% | 93.26% |

The baseline selected contracts with a mean 60-day maturity and a mean annualized
lease signal of 3.53%. Compounded in isolation, its long-futures return stream was
-81.87% and the Treasury return stream was +773.83%. Those isolated compounded
figures must not be added: the strategy earns their simultaneous daily returns on
the same collateral base. Quoted in silver, the baseline lease-book daily-return
stream compounded to -31.21%. The implemented identity reconstructed final NAV
with an absolute floating-point difference below `9e-15`.

The baseline underperformed the direct proxy because short-dated futures roll and
basis behavior more than consumed its collateral advantage when measured in
silver. Weighted selection found a materially higher modeled lease signal: mean
maturity was 222 days, mean lease was 5.82%, and its silver-quoted lease stream
compounded to +98.34%. That produced the stronger 358.17% result, but required
average daily turnover of 79.78% versus 5.85% for shortest-maturity selection.
Selecting the single highest lease rate increased the zero-cost result again to
496.26%, with 89.28% average daily contract turnover. The strategy did not remove
silver's principal risk: every path still experienced drawdowns near 90%.

## Cost sensitivity and interpretation

Weighted selection rebalances across contracts frequently. Consequently, its
zero-cost headline is not a realistic implementable estimate. Shortest-maturity
selection is less cost-sensitive but already underperforms the direct proxy before
costs.

| Selection | Fee | Full spread | Compounded return | CAGR | Arithmetic accumulated cost contribution |
|---|---:|---:|---:|---:|---:|
| Shortest maturity | 0 bp | 0 bp | 58.90% | 1.38% | 0.00% |
| Shortest maturity | 1 bp | 2 bp | 44.17% | 1.09% | -9.72% |
| Shortest maturity | 2 bp | 5 bp | 27.66% | 0.73% | -21.87% |
| Weighted lease rate | 0 bp | 0 bp | 358.17% | 4.61% | 0.00% |
| Weighted lease rate | 1 bp | 2 bp | 21.83% | 0.59% | -132.48% |
| Weighted lease rate | 2 bp | 5 bp | -76.75% | -4.23% | -298.08% |

Each trade pays the stated fee plus half the stated full spread. The accumulated
cost contribution is an arithmetic attribution total, not a separately compounded
return. The sensitivity shows that daily SoftMax rebalancing dominates the
practical conclusion: the apparent lease advantage requires turnover controls,
liquidity assumptions, and out-of-sample data before it can be treated as an
implementable strategy result.
