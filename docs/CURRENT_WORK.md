# Current work

## Empirical execution costs for funded BTC transfers — 2026-09-16

The owner requested implementation of feasible funded transfers and holding
horizons evaluated by expected net BTC wealth versus keeping the current
position. The opt-in `trade_strategy="cost_aware_paired"` path is implemented
beside the preserved default allocation policy. The GUI provides a strategy
selector, economics/funding/latency/fee controls and a bounded example.

The current extension studies joint spot/futures completion and execution-price
slippage at explicit waiting deadlines, then budgets that cost before approving
and sizing a transfer. The research setting is opt-in
`paired_repricing_mode="empirical"`; `fixed` and `adaptive` retain their existing
meaning. Read [EMPIRICAL_LEASE_EXECUTION.md](EMPIRICAL_LEASE_EXECUTION.md) for the
calibration, deadline and evaluation protocol, and
[COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md) for the underlying
funding and economics. Key components are `funded_ledger.py`,
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

The adaptive-entry extension adds `paired_repricing_mode="adaptive"` for
spot-to-future transfers. The desired effective entry lease comes from the
existing net-BTC economic hurdle; target limits incorporate acknowledged source
fill prices and fees. Explicit observation, frozen-snapshot decision and
order-arrival delays also apply to repricing. Replacements take effect on
arrival, and durable audit records preserve requested versus applied limits.
Old presets remain fixed, while reverse transfers and rolls retain their
existing funded execution. Partial slices accumulate the requested delta using
the accepted funding ratio; cash accrual is the third component, with no actual
Treasury-security fill or atomic cross-venue guarantee.

Six FRED series were retrieved as an immutable NEW snapshot covering June
1–September 4, 2026, under `public/data/paired-rates/`. The overlap matches the
retained source observations. DTB3 discount quotes are normalized through a
91-day benchmark price into an ACT/365 investment yield. The new availability
model waits for the next federal business release day and following UTC
midnight; actual historical publication timestamps remain unverified. Source
hashes, retrieved times, normalization version and rate-age gating are audited.

## Validation and limits

The original fixed-limit implementation includes focused tests for economics, funding and fee
accounting, causal Treasury normalization/availability, paired execution and
checkpoint continuity, runner integration and detailed exports. All 219 Python
and 33 JavaScript checks passed. The complete preview deployment, paired GUI and
workbook checks, and replay extension passed for commit
`d1fb73487e1f9aee42064d57799d55edd8445dd8`. See
[COST_AWARE_FUNDED_VALIDATION.md](COST_AWARE_FUNDED_VALIDATION.md) for the workflow,
preview URL, exact results and research limitations.

The adaptive extension passed 257 Python and 37 relevant JavaScript checks.
Preview workflow `35140804706` passed for
`663e60c5b10bb98675baf7785b66b64d18ea6b34`. Its three-day fixed/zero-delay
adaptive/100-ms-per-stage comparison completed on `[2026-06-06, 2026-06-09)`.
All three full audits passed, but none completed a pair. Their ending differences
from direct holding were respectively −$0.68229, −$0.07773 and −$0.00555;
remaining unmatched spot quantities were 0.01, 0.00114 and 0.00008 BTC. Smaller
losses came from less unmatched selling and lower fees, not demonstrated lease
income. The original fixed target quantity made the funding cap bind despite
repricing. The empirical extension therefore evaluates execution cost before
fixing its funded target quantity.

The empirical extension is pushed and deployed on
`agent/cost-aware-funded-transfers` at
`6fd1ae2a4fa24b28a8a5972e8445975a2f5a8fd2`. Local validation passed 311 Python
and 34 GUI tests. [Workflow 35147345496](https://github.com/leviitzhak/keep_and_lease/actions/runs/35147345496)
passed every application health, rendered-GUI/multi-commodity, subsecond,
paired-export and replay-extension check. **The overall workflow failed** solely
at the final `actions/upload-artifact` evidence finalization with `403 Forbidden`;
it must not be reported as an overall successful workflow. An authenticated
browser check independently verified the exact deployed SHA and ready server
engine at the [GCP preview](https://keep-and-lease-preview-web-vfk2j2rgoq-zf.a.run.app/).

The empirical job `69d512c2e4da4cd8b1fa27a9870c0769` started at 20:40 UTC on
September 16. It froze 67,452 execution labels from calibration
`[2026-06-06, 2026-06-16)` and is scoring `[2026-06-16, 2026-06-26)`, both UTC.
The comparable adaptive baseline job `d1da8ce988ec49d890d61e89aa8fe040` is running
on the prior immutable engine `663e60c5b10bb98675baf7785b66b64d18ea6b34` over the
same ten scored days. Results, independent audit acceptance, empirical
completion and out-of-sample coverage remain pending. The scored ten days must
be inspected before starting a new 90-day empirical run; implementation and
synthetic tests alone do not establish the requested completion probability.

A separate audit-checker correction for a pending initial decision censored
before any fill has 14 passing focused checks and is included in this follow-up. It does
not change the simulation engine or the immutable engines of these running jobs.

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
