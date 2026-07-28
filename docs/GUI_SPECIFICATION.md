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

## Maturity-boundary configuration

Do not ask the user to enter a slope and intercept directly. For each independently configured long or short maturity boundary, expose:

- first maturity;
- lease rate at the first maturity;
- second maturity;
- lease rate at the second maturity.

Require the second maturity to exceed the first. Draw both anchor points and their connecting line on the corresponding rate-versus-maturity scatter. The implied slope and intercept may be displayed as read-only diagnostics so that existing calculations remain inspectable.

For Treasury selection or scoring, use the same interaction with interest rate replacing lease rate.

## Day inspection

The selected day should be shared across all relevant charts. Provide previous/next trading-day navigation. The inspected-day panel should contain the contract data that were previously shown as hard-coded last-entry tables.

For each contract display identifier, maturity, price inputs, rate, boundary value, eligibility, base score, adjustment, final score, target weight, executed weight, and return contribution.

## Scatter plots

Provide comparable scatter plots for every commodity, not only the currently selected instrument. At minimum support:

- lease rate versus maturity;
- forward premium versus maturity;
- score or target weight versus maturity;
- subsequent return versus signal where available;
- daily return caused directly by lease-rate changes versus the start-of-period maturity of the position.

For Treasuries, use interest rate in place of lease rate and retain the same interaction model.

### Rate-change return versus position maturity

Create a separate scatter for every active strategy-leg and active-commodity combination. Cash/Treasuries count as a commodity for this purpose. Do not merge distinct internal legs merely because they have the same market direction.

Each point represents one return interval from `t-1` to `t`:

```text
X_t = weighted remaining maturity of the position at t-1
Y_t = return from t-1 to t caused directly by the lease-rate change
```

The X value must describe the holdings exposed during the interval. Use positions after executions on `t-1` and before any executions on `t`. A trade or roll executed on `t` must not alter the point for the return already earned from `t-1` to `t`.

For a position containing multiple contracts or instruments, use absolute-notional weighting:

```text
weighted_maturity_(t-1)
  = sum_i(abs(notional_i_(t-1)) * remaining_maturity_i_(t-1))
    / sum_i(abs(notional_i_(t-1)))
```

If only one instrument is held, use that instrument's remaining maturity. Exclude observations with no active position. Pure cash with no maturity or rate sensitivity is excluded; Treasury positions use weighted Treasury maturity and the return caused by yield changes.

The Y component must be the same isolated lease-rate-change or yield-change component used by return attribution. It must exclude spot-price movement, ordinary passage of time/carry, rolling, transaction costs, resizing, and allocation changes.

The default Y normalization should be relative to the relevant leg–commodity position, because that better reveals maturity sensitivity without total position-size changes dominating the scatter. Allow switching to portfolio-capital normalization for contribution analysis.

Each scatter should provide:

- a horizontal zero-return line;
- point count;
- optional linear regression line;
- regression slope, correlation, and `R²` when regression is enabled;
- mean and median maturity;
- mean and standard deviation of the plotted return component.

Hover information should include:

- return date `t` and interval `t-1 -> t`;
- strategy leg and commodity;
- start-of-period weighted maturity at `t-1`;
- portfolio-relative and position-relative rate-change return;
- start-of-period position notional;
- weighted lease rate or Treasury yield before and after the change;
- change in the weighted rate;
- instruments and weights composing the position.

Support filtering by date range, commodity, leg, and minimum position size. Empty plots must state whether the cause is an inactive leg, no qualifying position, missing attribution, or active filters.

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

Include annualized return, cumulative return, volatility, maximum drawdown, turnover, exposure statistics, yearly summary, benchmark comparison, component-level return attribution, and the per-leg/per-commodity maturity-versus-rate-change-return scatters specified above.