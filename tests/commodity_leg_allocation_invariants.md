# Commodity leg allocation invariants

This branch implements the following invariants for each commodity sleeve:

- The configured commodity proportion is the complete long commodity leg.
- `max_futures_treasury_fraction` is the maximum share of that leg implemented as Treasury collateral plus long futures.
- When the replicating-fund and cash/long-futures implementations are both enabled, the pre-short-extension shares satisfy `replicating_fund_share + futures_treasury_share = 1`.
- Treasury collateral and long-futures notional use the same futures-replication share.
- `max_short_fraction_of_long_leg` is measured against the complete long commodity leg, rather than the replicating-fund share or total portfolio capital.
- Treasury collateral is not double-counted when calculating the long-leg denominator used by the matched short-book extension.
