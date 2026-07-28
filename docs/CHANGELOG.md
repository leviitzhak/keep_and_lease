# Design Changelog

This log records project-level decisions, not every code commit.

## 2026-07-28

### Added

- Established `docs/PROJECT_STATE.md` as the high-level project source of truth.
- Split detailed specifications into strategy, scoring, parameters, GUI, backtest, data, TODO, and roadmap documents.
- Added per-active-leg and per-active-commodity scatter statistics of rate-change return versus start-of-period position maturity, including Treasury/cash legs where rate-sensitive.

### Confirmed

- Signals are executed with a one-trading-day delay.
- Long and short futures positions may coexist at different maturities.
- Lease-rate eligibility is a hard gate and cannot be overridden by a maturity bonus.
- Maturity preference is represented by a linear boundary in rate–maturity space.
- The maturity boundary is configured through two maturity/rate anchor points; slope and intercept are derived internal values rather than user-facing parameters.
- The maturity adjustment is relative to the pre-existing score.
- The intended short-side added signal follows `-lease_rate - line`, subject to exact sign-convention tests in code.
- General statistics should include scatter plots for all commodities and every active strategy leg.
- Treasury plots should mirror commodity plots using interest rate and yield-change return instead of lease rate and lease-rate-change return.
- For a return over `t-1 -> t`, the associated maturity is the remaining maturity of the position held at `t-1`.
- Weighted maturity uses absolute start-of-period notional weights and the same holdings used to calculate the corresponding rate-change return.
- Trades or rolls executed on `t` are excluded from the maturity and return attribution for the already completed `t-1 -> t` interval.
- The plotted Y value isolates the return caused directly by lease-rate or Treasury-yield changes from spot movement, carry/time decay, rolling, transaction costs, resizing, and allocation changes.
- Contract details should appear in the inspected-day view rather than as a hard-coded table for the final observation.

### Pending confirmation

- Exact default maturity/rate anchor values, scaling constants, and clipping bounds.
- Final production pricing identity used to isolate lease-rate-change and Treasury-yield-change P&L, provided it is equivalent to the documented counterfactual valuation and reconciles to total return.
- Final default width and interpolation function for the ETF/Treasury transition.