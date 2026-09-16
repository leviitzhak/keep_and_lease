# Current work

## Cost-aware funded BTC paired transfers — 2026-09-16

The owner requested implementation of feasible funded transfers and holding
horizons evaluated by expected net BTC wealth versus keeping the current
position. The opt-in `trade_strategy="cost_aware_paired"` path is implemented
beside the preserved default allocation policy. The GUI provides a strategy
selector, economics/funding/latency/fee controls and a bounded example.

Read [COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md) for exact
behavior and assumptions. Key components are `funded_ledger.py`,
`paired_transfer_economics.py`, `paired_transfer.py` and
`paired_transfer_rates.py`; `btc_trade_backtest.py` connects them to the
existing durable worker, charts, audit and export flow.

The new ledger separates marks, unsettled P&L and cash settlement, tracks full
funding/reservations and charges fixed/minimum/per-unit/proportional commissions
by durable child-order ticket. Transfers share one pair ID and bounded source-
first funding through partial fills and delayed responses. Economics compare
equal-capital KEEP/SWAP candidates over feasible sizes and common horizons,
including prospective costs and uncertainty allowances. Forecasts assume flat
spot, residual basis converging toward a configured settlement reference and
current normalized cash-proxy yield; they do not guarantee profitable exits.

Six FRED series were retrieved as an immutable NEW snapshot covering June
1–September 4, 2026, under `public/data/paired-rates/`. The overlap matches the
retained source observations. DTB3 discount quotes are normalized through a
91-day benchmark price into an ACT/365 investment yield. The new availability
model waits for the next federal business release day and following UTC
midnight; actual historical publication timestamps remain unverified. Source
hashes, retrieved times, normalization version and rate-age gating are audited.

## Validation and limits

The implementation includes focused tests for economics, funding and fee
accounting, causal Treasury normalization/availability, paired execution and
checkpoint continuity, runner integration and detailed exports. All 219 Python
and 33 JavaScript checks passed. The complete preview deployment, paired GUI and
workbook checks, and replay extension passed for commit
`d1fb73487e1f9aee42064d57799d55edd8445dd8`. See
[COST_AWARE_FUNDED_VALIDATION.md](COST_AWARE_FUNDED_VALIDATION.md) for the workflow,
preview URL, exact results and research limitations.

The mode remains a BTC tape-participation, USD-linear research proxy with
cash-interest accrual. Native inverse settlement, historical quote depth,
security-level Treasury prices, verified venue margin/payment calendars,
full-period holdout acceptance and complete realized-versus-KEEP attribution
are not certified. Synthetic Treasury facilities in the ledger are separate
from the GUI's cash proxy. Timeouts preserve unresolved inventory instead of
assuming liquidity existed. No leverage or live trading is enabled.

[NEXT_STRATEGY_IMPLEMENTATION.md](NEXT_STRATEGY_IMPLEMENTATION.md) retains the
complete acceptance specification; [TODO.md](TODO.md) distinguishes implemented
research behavior from remaining venue/data/validation work. The previous
current-work history remains in
[CURRENT_WORK_HISTORY_2026-09-15_PRE_STRATEGY_PLAN.md](CURRENT_WORK_HISTORY_2026-09-15_PRE_STRATEGY_PLAN.md).
Earlier completed 90-day legacy computations stay completed; this new strategy
requires its own performance and holdout assessment. The single GCP preview is
the authoritative deployment target; local Sites remains deferred.