# Design Changelog

This log records project-level decisions, not every code commit.

## 2026-07-28

### Added

- Established `docs/PROJECT_STATE.md` as the high-level project source of truth.
- Split detailed specifications into strategy, scoring, parameters, GUI, backtest, data, TODO, and roadmap documents.

### Confirmed

- Signals are executed with a one-trading-day delay.
- Long and short futures positions may coexist at different maturities.
- Lease-rate eligibility is a hard gate and cannot be overridden by a maturity bonus.
- Maturity preference is represented by a linear boundary in rate–maturity space.
- The maturity adjustment is relative to the pre-existing score.
- The intended short-side added signal follows `-lease_rate - line`, subject to exact sign-convention tests in code.
- General statistics should include scatter plots for all commodities.
- Treasury plots should mirror commodity plots using interest rate instead of lease rate.
- Contract details should appear in the inspected-day view rather than as a hard-coded table for the final observation.

### Pending confirmation

- Exact default slopes, intercepts, scaling constants, and clipping bounds.
- Exact weighted-Treasury maturity formula.
- Final default width and interpolation function for the ETF/Treasury transition.
