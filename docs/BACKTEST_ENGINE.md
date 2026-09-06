# Backtest Engine

## Time convention

Signals use information available at observation `t`. The `reactivity`
parameter executes changes either at that observation (`same_day`) or at the
following available observation (`next_day`). Returns are measured from
execution to the next selected market observation. Missing timestamps use each
instrument's actual trading calendar rather than a fixed timedelta.

For a BTC-only commodity portfolio, `execution_interval_seconds=0` selects every
common spot/futures mark. A positive value selects the next available mark at
that cadence and must be a whole multiple of the finest detected common-market
resolution. Requests finer than the data are rejected. The active BTC path uses
Binance BTC/USDT one-minute trade candles and Deribit one-minute dated-futures
candles, so its finest interval is 60 seconds. Binance prices are a USD proxy
assuming USDT/USD=1, not FX-adjusted USD prices. The continuous packaged window
is 6 June through 3 September 2026 UTC. Candle closes become observable at the
following minute boundary (the final boundary is 4 September 00:00 UTC).
Kraken remains an optional provider with three isolated samples; only that
provider's sample-session manifest restricts runs to its latest complete day.

Treasury accrual is piecewise causal. The latest observable yield is applied
until a later yield mark becomes available, at which point the remaining
interval accrues at the new yield. The engine never backfills from a future mark
and never interpolates through time between daily yields. It may still
interpolate across available Treasury tenors to match a futures maturity.
Loaded immutable Treasury series cache separate daily/intraday availability
indices. Binary searches use those indices instead of repeatedly converting
historical dates. The latest-observable-yield rule and all accrual arithmetic
are unchanged; plain dict/list inputs retain their original lookup path.

## Observation sequence

1. Validate market data for observation `t`.
2. Compute derived rates and eligibility.
3. Compute base and adjusted scores.
4. Convert scores to target weights.
5. Apply the configured allocation half-lives to the long implementation mix
   and short-book size; do not smooth curve inputs or contract ranking.
6. Execute target changes according to `reactivity`.
7. Calculate mark-to-market return to the next selected market observation from the position just established.
8. Apply transaction costs, fees, financing, ETF expenses, and roll effects.
9. Persist diagnostics and attribution.

## Accounting

Daily portfolio return should be decomposed into at least:

- ETF price return;
- long-futures return;
- short-futures return;
- Treasury/cash return;
- financing or borrowing cost;
- ETF expense accrual;
- transaction cost;
- roll-related contribution;
- residual reconciliation term.

The components must reconcile to total return within a documented numerical tolerance.

Lease/basis repricing uses contract-level observed-versus-frozen-curve valuation.
For each held contract, the frozen end price retains the start-of-period implied
lease rate while allowing the observed spot and matched USD rate to move. The
signed holding times the difference between observed and frozen end values is
the rate-change contribution. Stored diagnostics retain symbol, signed notional,
start maturity, rates before/after, both end values, and instrument P&L. Any
remaining difference is reported explicitly as `other`; it is not relabeled as
lease-rate change.

## Futures

Use consistent contract multipliers, currencies, settlement prices, and expiry calendars. Contract rolls must be explicit transactions rather than symbol substitution. Prevent accidental holding beyond the operational close-or-roll deadline.

## Missing data

Do not silently forward-fill contract prices across invalid periods. Any permitted fill policy must be instrument-specific, limited, and visible in diagnostics. A missing signal may preserve the existing position or trigger a configured fallback, but the behavior must be explicit.

## Benchmarks

Benchmarks must use the same date range and return convention. Any benchmark expense ratio, financing assumption, or reinvestment convention must be documented.

## Validation tests

- No-look-ahead test using deliberately perturbed future values.
- Same-day signal/execution timing test.
- Position and weight-cap invariants.
- Return attribution reconciliation.
- Roll continuity and contract identity tests.
- Missing-data and empty-universe tests.
- Reproducibility from saved parameters and data version.
