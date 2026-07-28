# Keep & Lease — Project State

_Last updated: 2026-07-28_

## Purpose

Build an interactive research and backtesting application for strategies that allocate among commodity ETFs, commodity futures across maturities, and Treasury/cash instruments. The application should expose all economically meaningful parameters in a GUI and make the daily decisions auditable.

## Current scope

- Commodities: silver first, with the same analysis framework extended to gold and other supported commodities.
- Cash/Treasuries: treated as another investable curve, using interest rates rather than lease rates.
- Instruments: physical-backed ETFs, futures at several maturities, and Treasury/cash positions.
- Outputs: daily positions, returns, cumulative returns, diagnostics, contract-level inspection, and cross-sectional scatter plots.

## Core design decisions

1. Signals are calculated on day `t`; trades are executed on day `t+1`.
2. Long and short futures books may coexist at different maturities.
3. A long futures contract remains eligible only when its lease rate satisfies the long-side eligibility rule.
4. A short futures contract remains eligible only when its lease rate satisfies the short-side eligibility rule; a maturity bonus must not make an otherwise ineligible contract tradable.
5. Contract ranking combines an existing economic score with a relative maturity/curve adjustment.
6. The maturity adjustment is based on a linear boundary in `(maturity, lease rate)` space.
7. Treasury contract analysis uses the same plots and ranking concepts, replacing lease rate with interest rate.
8. Contract tables belong in the inspected-day view, not as hard-coded data in general statistics.
9. General statistics should provide comparable scatter plots for every commodity.

## Canonical documents

- [STRATEGY.md](STRATEGY.md): portfolio construction and trading rules.
- [SCORING.md](SCORING.md): score definitions and maturity-line adjustment.
- [PARAMETERS.md](PARAMETERS.md): GUI/configuration parameters.
- [GUI_SPECIFICATION.md](GUI_SPECIFICATION.md): application behavior and visual requirements.
- [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md): timing, accounting, and simulation assumptions.
- [DATA_SOURCES.md](DATA_SOURCES.md): required market data and derived quantities.
- [TODO.md](TODO.md): prioritized implementation work.
- [CHANGELOG.md](CHANGELOG.md): durable design decisions.
- [ROADMAP.md](ROADMAP.md): staged development plan.

## Current implementation priorities

1. Replace separate ad-hoc long/short maturity parameters with the linear-boundary scoring model.
2. Scale the maturity adjustment relative to the pre-existing score.
3. Verify the exact short-side sign convention in code and tests.
4. Move contract details into synchronized day inspection.
5. Add commodity-wide and Treasury scatter plots.
6. Add tests for execution delay, eligibility gates, score normalization, and return decomposition.

## Source-of-truth policy

This file records the current high-level state. Detailed formulas and behavior belong in the linked documents. When a design decision changes, update the relevant detailed document and add a dated entry to `CHANGELOG.md`.
