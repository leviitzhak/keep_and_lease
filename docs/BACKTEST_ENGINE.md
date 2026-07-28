# Backtest Engine

## Time convention

Signals use information available at the close of day `t`. Position changes are executed on the next available trading day. Missing calendar dates must be handled using each instrument's actual trading calendar rather than a fixed one-day timedelta.

For return and attribution records, a return labelled with date `t` represents the interval from `t-1` to `t`. Exposure characteristics associated with that return, including position maturity, must come from the holdings at the start of the interval: after executions on `t-1` and before executions on `t`.

## Daily sequence

1. Validate market data for day `t`.
2. Mark the positions carried from `t-1` to `t` and calculate their return.
3. Attribute that return using the start-of-period holdings and market changes over `t-1 -> t`.
4. Compute derived rates and eligibility using information available for the new decision.
5. Compute base and adjusted scores.
6. Convert scores to target weights.
7. Queue target changes for execution.
8. Execute any previously queued changes on the applicable valid trading day.
9. Apply transaction costs, fees, financing, ETF expenses, and explicit roll effects at their defined timestamps.
10. Persist positions, diagnostics, and attribution with unambiguous timestamps.

The implementation may organize calculations differently for efficiency, but it must preserve these information and ownership relationships. In particular, a trade executed on `t` cannot affect the market return attributed to the position carried from `t-1` to `t`.

## Accounting

Daily portfolio return should be decomposed into at least:

- ETF price return;
- long-futures return;
- short-futures return;
- Treasury/cash return;
- commodity or spot-price component;
- lease-rate-change component;
- Treasury-yield-change component;
- passage-of-time/carry component;
- financing or borrowing cost;
- ETF expense accrual;
- transaction cost;
- roll-related contribution;
- resizing or allocation-change contribution where required by the chosen accounting convention;
- residual reconciliation term.

The components must reconcile to total return within a documented numerical tolerance.

## Lease-rate-change attribution

For each active strategy-leg and commodity combination, calculate the return caused directly by the change in lease rates over the interval `t-1 -> t`, using only the position held at `t-1`.

The component should compare the observed end-of-period valuation with a counterfactual end-of-period valuation in which maturity has decayed normally but the relevant lease-rate curve has not changed from `t-1`. Conceptually:

```text
rate_change_pnl_t
  = value_at_t(observed curve at t, end-of-period maturity)
    - value_at_t(curve held at t-1, end-of-period maturity)
```

Apply the actual signed start-of-period holdings to that valuation difference. This construction is intended to isolate curve movement from:

- commodity or spot-price movement;
- ordinary passage of time and carry;
- trades and position resizing;
- rolls;
- transaction costs and fees.

If the production pricing model uses a different but mathematically equivalent decomposition, it must document the identity and pass reconciliation tests.

For Treasury positions, calculate the analogous component caused directly by yield changes. Pure cash without maturity or yield sensitivity has no such observation.

Store both normalizations where possible:

```text
portfolio_relative_return = rate_change_pnl_t / portfolio_value_(t-1)
position_relative_return  = rate_change_pnl_t / abs(leg_commodity_notional_(t-1))
```

Define and test the denominator behavior for very small or zero notionals. Zero-position observations must not enter the scatter statistics.

## Position maturity associated with attribution

The maturity paired with the return from `t-1` to `t` is the remaining maturity at `t-1`, because that is the exposure that existed when the rate change occurred:

```text
X_t = maturity_(t-1)
Y_t = rate_change_return_(t-1 -> t)
```

For multiple instruments in one leg–commodity position, use absolute-notional weighting:

```text
weighted_maturity_(t-1)
  = sum_i(abs(notional_i_(t-1)) * remaining_maturity_i_(t-1))
    / sum_i(abs(notional_i_(t-1)))
```

The same start-of-period instrument set and weights must underlie both the weighted maturity and the rate-change P&L. Do not use the end-of-period position, a post-trade position, or the maturity of a replacement contract rolled on `t`.

Persist enough detail to reconstruct each scatter point: interval dates, leg, commodity, instruments, signed notionals, absolute weights, start maturities, weighted maturity, rates or yields before and after, rate-change P&L, both return normalizations, and exclusion reason if no point is emitted.

## Futures

Use consistent contract multipliers, currencies, settlement prices, and expiry calendars. Contract rolls must be explicit transactions rather than symbol substitution. Prevent accidental holding beyond the operational close-or-roll deadline.

## Missing data

Do not silently forward-fill contract prices across invalid periods. Any permitted fill policy must be instrument-specific, limited, and visible in diagnostics. A missing signal may preserve the existing position or trigger a configured fallback, but the behavior must be explicit.

A missing lease-rate or yield observation required for attribution must produce a visible missing-attribution diagnostic. It must not silently become a zero rate-change return.

## Benchmarks

Benchmarks must use the same date range and return convention. Any benchmark expense ratio, financing assumption, or reinvestment convention must be documented.

## Validation tests

- No-look-ahead test using deliberately perturbed future values.
- One-trading-day execution-delay test.
- Position and weight-cap invariants.
- Return attribution reconciliation.
- Lease-rate-change counterfactual-pricing test.
- Treasury-yield-change attribution test.
- Start-of-period ownership test: a trade on `t` cannot change the rate-change return for `t-1 -> t`.
- Maturity alignment test: each scatter point uses maturity and weights from `t-1`.
- Weighted-maturity reconstruction test for multi-instrument positions.
- Roll continuity and contract identity tests.
- Missing-data and empty-universe tests.
- Reproducibility from saved parameters and data version.