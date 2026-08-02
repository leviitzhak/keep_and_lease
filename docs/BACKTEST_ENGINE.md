# Backtest Engine

## Time convention

Signals use information available at the close of day `t`. Position changes are executed on the next available trading day. Missing calendar dates must be handled using each instrument's actual trading calendar rather than a fixed one-day timedelta.

## Daily sequence

1. Validate market data for day `t`.
2. Compute derived rates and eligibility.
3. Compute base and adjusted scores.
4. Convert scores to target weights.
5. Queue target changes for execution.
6. Execute queued changes on the next valid trading day.
7. Calculate mark-to-market return from positions held.
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
- One-trading-day execution-delay test.
- Position and weight-cap invariants.
- Return attribution reconciliation.
- Roll continuity and contract identity tests.
- Missing-data and empty-universe tests.
- Reproducibility from saved parameters and data version.
