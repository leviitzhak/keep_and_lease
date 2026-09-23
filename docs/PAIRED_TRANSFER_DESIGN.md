# Paired-transfer execution requirements

Status: owner-approved specification recorded on 2026-09-14. The BTC research
implementation now covers funded staged execution and optional adaptive
spot-to-future entry limits; see
[COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md) for its precise
scope and [TODO.md](TODO.md) for remaining acceptance. Requirements below retain
the broader native-market design, including depth that the tape does not supply.

The **same transfer instruction** applies to both spot-to-futures and
futures-to-spot transfers, including the cash/Treasury funding movements.

The unit of discretionary reallocation is a funded transfer between direct BTC and BTC exposure implemented by cash/Treasuries plus futures, not two independent targets.

- Separate held inventory, valuation quality, signal validity and permission to trade. A stale or missing new futures observation should not itself set its holdings/target to zero or cause a compensating spot transaction. Continue to expose valuation age and uncertainty. Expiry, settlement, margin shortfalls and explicit risk exits require their own rules, not silent stale-price liquidation.
- A transfer needs recent causal price evidence from both legs with an explicit maximum absolute age and maximum timestamp skew. For a spot-to-futures transfer use the relevant spot sell price and futures buy price; the reverse uses futures sell and spot buy. Last trade, mid, bid/ask and depth-weighted prices are distinct data types.
- Validate available quantities at the relevant sides and depths for the proposed transfer size; normalize contract units. Evaluate carry and costs using volume-weighted prices over the needed depth rather than a tiny best quote governing a much larger target.
- Size a paired partial transfer by the smaller feasible amount across desired delta, both legs' demonstrated liquidity and cash/collateral constraints. Reserve liquidity/collateral to avoid double use by concurrent orders. Do not substitute whole target size for actual fills.
- Spot changes should be linked to matching achieved or conservatively executable futures changes. Bounded staged execution or a pre-funded buffer may be needed; cross-venue execution is not assumed atomic. Futures collateral must be available before exposure is opened; fees, spreads and price differences reduce what can be funded from spot sales. Treat outstanding unmatched exposure, elapsed legging time and maximum prefunding as explicit states/limits.
- Reducing a futures position should release collateral for the corresponding spot purchase; an unfilled futures exit must not release its collateral. Rebalancing between futures maturities also needs both futures legs coordinated; it should not automatically churn spot.
- Keep all original orders, realized fills, funding transfers, costs and reason codes in a pair-level audit. Compare requested versus executed paired quantity, maximum unpaired exposure, quote age/skew/size, and subsequent P&L.

The uploaded files contain no book-side depth or available quote quantity. Historical trade amount, even where present in original raw data, is already executed volume and is not a guarantee of remaining quoted size. A tape-only model can test explicitly labeled participation assumptions without knowing future prints at the decision; it cannot certify depth-aware executability.

This specification does not establish parameter optimality or performance
improvement. The implementation retains fixed-limit strategies/results for
comparison with adaptive entry behavior.

## Acceptance and audit contract

A transfer record has an immutable pair ID, direction, desired quantity,
quoted executable prices and sizes, quote timestamps/age/skew, reserved funding,
submitted/filled quantities for each child order, realized costs and completion,
partial, expired, cancelled or risk-exit status. A replaced signal must not
forget an outstanding pair or reverse already reserved/partially filled funding.
Record and cap maximum unpaired notional and elapsed legging time. Additional
transfers cannot reuse the same liquidity or collateral reservations.

Tests must cover both directions with one leg unavailable, stale prices while
holding, asymmetric liquidity, partial fills, simultaneous transfers, target
reversals while pending, rejected/cancelled children, changing prices/fees,
expiry/settlement and restart from checkpoint. Assert inventory/NAV/cash
reconstruction and no early release or double counting of collateral at each
step. A futures roll should not churn spot solely because the maturity changes.

Acceptance compares the existing model and new execution policy from identical
opening state and source data, including costs and achieved matched exposure.
This design does not claim that cross-venue fills are atomic or that a top quote
or a past trade is executable for arbitrary size. No hard-coded choice of quote
tolerance, transfer size, smoothing or maximum legging time is approved here.

## Planned extensions recorded 2026-09-15

See [QUOTE_LATENCY_AND_CARRY_PLAN.md](QUOTE_LATENCY_AND_CARRY_PLAN.md) for the
open implementation checklist and acceptance criteria:

- delay observed quotes before the trading system can use them, independently
  of order and fill-response delays; allow either observation order once both
  records are available, without imposing a universal execution order;
- compare each transfer's authorizing observed lease rate with the achieved
  matched-fill rate and costs, preserving incomplete transfers and separating
  execution quality from subsequent realized BTC return; and
- study longer holding/roll periods using a funded commodity-denominated
  portfolio, separating horizon, smoothing and maturity and retaining the
  residual-basis, funding, settlement and liquidity risks.

The research implementation now covers deterministic observation/decision/order
delays, staged fills and matched-price diagnostics. Depth, native venue behavior
and subsequent realized-outcome acceptance remain broader requirements; consult
the current guide before treating any item as implemented.

## Next analysis: cost-aware transfers versus keeping current positions

See [COST_AWARE_PAIRED_TRANSFER_PLAN.md](COST_AWARE_PAIRED_TRANSFER_PLAN.md).
This adds the requested economic no-trade threshold as an alternative to merely
lengthening mandatory holding time. It covers incremental expected BTC returns
versus keeping the current position, all spot/futures/Treasury costs, feasible
break-even horizons, profit-taking or compensated-switch exits with risk
exceptions, settlement-reference comparisons, the preliminary holding-horizon
study, and acceptance for a complete causal funded paired-transfer backtest.
The implementation checklist is tracked in `TODO.md`; this retained design
document is not evidence of completed full-period or native-market acceptance.
