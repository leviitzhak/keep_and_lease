# GUI Specification

## Goals

The GUI should make parameter changes, backtest results, and daily contract decisions directly inspectable without requiring code changes.

## Main areas

1. **Configuration panel** — grouped strategy parameters with units and tooltips.
2. **Run status** — progress, warnings, data period, and configuration identifier.
3. **Performance view** — cumulative return, periodic return, drawdown, and benchmark comparison.
4. **Allocation view** — ETF, futures, Treasury/cash, long book, short book, gross and net exposure.
5. **Market diagnostics** — rates, lease rates, forward premiums, maturity curves, and cross-sectional scatters.
6. **Day inspection** — synchronized details for the date selected in any chart.

## Day inspection

The selected day should be shared across all relevant charts. Provide previous/next trading-day navigation. The inspected-day panel should contain the contract data that were previously shown as hard-coded last-entry tables.

For each contract display identifier, maturity, price inputs, rate, boundary value, eligibility, base score, adjustment, final score, target weight, executed weight, and return contribution.

## Scatter plots

Provide comparable scatter plots for every commodity, not only the currently selected instrument. At minimum support:

- lease rate versus maturity;
- forward premium versus maturity;
- score or target weight versus maturity;
- subsequent return versus signal where available.

For Treasuries, use interest rate in place of lease rate and retain the same interaction model.

## Interaction

- Hover should reveal exact values and contract identity.
- Clicking or scrubbing a date should update day inspection.
- Changing parameters should mark results stale until rerun.
- A run should not silently use invalid or incompatible parameters.
- Plots should remain readable on desktop and mobile widths.
- Empty plots must show a diagnostic message explaining whether data, filters, or computation produced no points.

## Persistence

Allow save, load, rename, export, and reset of parameter configurations. Store a schema version with each configuration.

## General statistics

Include annualized return, cumulative return, volatility, maximum drawdown, turnover, exposure statistics, yearly summary, benchmark comparison, and component-level return attribution.
