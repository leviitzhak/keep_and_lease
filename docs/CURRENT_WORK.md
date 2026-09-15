# Current work

## Next implementation handoff — cost-aware, funded paired transfers

The owner has authorized merging the documentation plan in PR #49 and will
start implementation in a NEW thread. Begin from current GitHub master after
that merge and create a fresh feature branch; no implementation is made here.

Read [NEXT_STRATEGY_IMPLEMENTATION.md](NEXT_STRATEGY_IMPLEMENTATION.md) first.
It groups all next changes in one ordered workstream; [TODO.md](TODO.md) contains
the primary checklist. The existing detailed paired-transfer, quote-latency,
cost-aware decision and preliminary-study documents remain linked specifications.

Next scope: rate-data/convention audit; separate source/receipt/decision/fill
clocks; size-aware paired transfers and reservation states; venue-aware futures
mark-to-market and cash settlement/Treasury funding; optional fixed and minimum
commissions; expected incremental NET BTC wealth versus KEEPING the current
position; executable exits and risk overrides; observed-versus-executed and
realized-return diagnostics; bounded then full-period and holdout acceptance.

[FUTURES_MTM_AND_COMMISSION_PLAN.md](FUTURES_MTM_AND_COMMISSION_PLAN.md)
explains how to replace the existing immediate futures-P&L-to-cash shortcut
without double counting. Signed quantities/margin tests prepare for later
leverage; this merge does not enable it. All new engine work remains pending.

[TREASURY_CARRY_FORWARD_AUDIT.md](TREASURY_CARRY_FORWARD_AUDIT.md) records the
exact July 14 rate vector, next-UTC-day availability, flat node extrapolation,
shortest-rate tape accrual and separate synthetic matched-bond prices. The
preliminary holding study omits intra-horizon VM financing and its Treasury data
freeze after that date; it remains research, not accepted strategy performance.

## Baseline and delivery boundary

The existing tested engine, strategies and saved results are unchanged. No
backtest rerun, application deployment, new data vintage or IAM change belongs
to this documentation patch. Coherent future application changes should use the
single authoritative GCP preview, with the usual tests, not local Sites.

The complete previous current-work document is preserved unchanged in
[CURRENT_WORK_HISTORY_2026-09-15_PRE_STRATEGY_PLAN.md](CURRENT_WORK_HISTORY_2026-09-15_PRE_STRATEGY_PLAN.md).
It records PR #48's prior integration, the verified shared-plots baseline and
completed full-history market extraction. Those milestones are not reset by the
new strategy plan. The completed old 90-day computations remain marked done;
a NEW cost-aware/funded strategy still needs its own acceptance run.
