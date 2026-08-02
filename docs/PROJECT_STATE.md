# Keep & Lease — Project State

_Last updated: 2026-08-02_

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

## Current implementation state

1. Registered commodity markets run as independent sleeves through the same engine.
2. Global settings can be overridden independently for every commodity.
3. A generic aggregator combines commodity sleeves and an independent cash/Treasury sleeve under the selected rebalancing schedule.
4. `maturity_scoring.py` is the single formula implementation used by trading and inspected-day diagnostics.
5. The GUI includes synchronized inspection, score audits, per-commodity and Treasury scatters, hierarchical decomposition, statistics, and versioned parameter sets.
6. Unavailable or corrupt market archives are isolated and reported only if the user selects the affected commodity.
7. The pure shorter-long/longer-short maturity multiplier remains explicitly deferred.

## Source-of-truth policy

This file records the current high-level state. Detailed formulas and behavior belong in the linked documents. When a design decision changes, update the relevant detailed document and add a dated entry to `CHANGELOG.md`.
