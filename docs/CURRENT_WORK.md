# Current work

## September 14 — user-approved integration

The user approved merging the verified stack from
`agent/operator-results-reader` into `master`. It includes
`agent/current-running-completion`, `agent/todo-batch-completion` and
`agent/shared-run-plots`, together with the standing results-reader declaration
and owner-run diagnostics. The user reported successful Terraform plan/apply and
validation on September 14; this is not an independent live-IAM certification.
The GitHub merge result, not this approval entry, establishes merge completion.

The tested application is the shared daily/replay plot version whose application
commit is `8f83983f4493db490f9941130dde86402d1f181d`. Its final preview acceptance
passed in `34621268667`, after integration `34621160549` (130 Python / 72 JS tests).
Diagnostic/documentation additions do not change its decision, fill or fee rules.
See [SHARED_RUN_PLOTS_VALIDATION.md](SHARED_RUN_PLOTS_VALIDATION.md) and
[TODO_SMALL_BATCH_VALIDATION.md](TODO_SMALL_BATCH_VALIDATION.md).

## Next execution change — specification only

The owner-approved **same transfer instruction** for both directions between
spot and cash/Treasuries plus futures is now in
[PAIRED_TRANSFER_DESIGN.md](PAIRED_TRANSFER_DESIGN.md) and the priority section
of [TODO.md](TODO.md). The engine implementation remains unchecked.

The design couples spot/futures fills and collateral reservations, limits
transfers by both legs' executable quantities, uses close causal price evidence,
and does not treat a stale/missing new futures quote as an instruction to remove
held inventory. It explicitly bounds prefunding and unpaired exposure/legging
time, and separates settlement/risk exits. Existing results remain immutable;
the new policy needs a controlled same-opening-state comparison.

## Full-history market diagnostics

`scripts/build_lease_maturity_history.py` constructs observation-level implied
lease/maturity data across the pinned 90-day market catalog. It reads market data
only, not user run results, and does not simulate another portfolio. It retains
exact source price strings, IDs, timestamps, sizes, premiums, Treasury components
and the original simple annualization. See
[LEASE_MATURITY_HISTORY.md](LEASE_MATURITY_HISTORY.md) for scope and limitations.

The dedicated extraction workflow runs on `agent/cloud-autonomous-access`, not
on the shared preview. Its output is market-derived diagnostics only; no private
strategy parameters, positions, results or credentials are published. Completion
and coverage are established by its `summary.json`, never by synthetic tests.

The earlier current-work record is retained unchanged in
[CURRENT_WORK_HISTORY_2026-09-14.md](CURRENT_WORK_HISTORY_2026-09-14.md).
Earlier branch/deployment statements in that file are historical snapshots.
