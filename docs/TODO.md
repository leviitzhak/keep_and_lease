# TODO

## Priority 1 — scoring and correctness

- [ ] Implement linear rate–maturity boundaries for long and short ranking.
- [ ] Apply eligibility gates before maturity adjustment.
- [ ] Scale maturity adjustment relative to the base score.
- [ ] Confirm and test the short formula `-lease_rate - line` under the code's sign convention.
- [ ] Add robust normalization and clipping.
- [ ] Add unit tests for monotonicity, eligibility, zero-strength behavior, and weight normalization.
- [ ] Verify the one-trading-day execution shift throughout the engine.

## Priority 2 — inspection and plots

- [ ] Remove hard-coded last-entry contract tables from general statistics.
- [ ] Add complete contract details to inspected-day view.
- [ ] Synchronize selected date across plots and inspection.
- [ ] Add previous/next trading-day controls.
- [ ] Add lease-rate/maturity scatters for every commodity.
- [ ] Add equivalent Treasury rate/maturity scatters.
- [ ] Show explicit diagnostics instead of empty plots.

## Priority 3 — portfolio and reporting

- [ ] Finalize weighted Treasury maturity allocation.
- [ ] Confirm gradual ETF/Treasury transition defaults.
- [ ] Validate coexistence of short-term long and long-term short positions.
- [ ] Reconcile daily return components to total return.
- [ ] Add annual tables, turnover, exposure, and drawdown statistics.
- [ ] Persist and version GUI parameter sets.

## Documentation maintenance

- [ ] Link code modules and parameter names to these specifications.
- [ ] Update `CHANGELOG.md` whenever a durable design decision changes.
- [ ] Mark uncertain assumptions explicitly rather than silently treating them as final.
