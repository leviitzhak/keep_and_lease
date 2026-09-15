# Planned futures mark-to-market, margin funding and fixed commissions

Status: specified 2026-09-15; engine implementation pending. Part of
[NEXT_STRATEGY_IMPLEMENTATION.md](NEXT_STRATEGY_IMPLEMENTATION.md), not a
separate lower-priority project. Applies to daily and trade-replay backtesting,
with common ledger invariants and venue-specific settlement schedules.

## 1. Current behavior must not be counted twice

In the reviewed code at 173eb302a17b4129982f2a81a697c8f0fb82654d,
`trade_replay.TapeAccount.on_trade` already computes held quantity times the
change from the previous futures price and immediately adds it to cash. Its
`accrue` method pays the shortest observable benchmark rate on that cash.
Thus futures market P&L is NOT absent. What is missing is a separate official-
mark/variation-payment ledger, actual Treasury holdings and cash constraints
between settlements. Replace this immediate-cash shortcut in a versioned mode;
do not add a second variation credit on top of it. Preserve compatibility tests.

The preliminary event study instead reprices an unchanged synthetic Treasury
face and adds total futures P&L at exit. It omits intra-horizon margin financing.
Neither implementation proves that all cash can remain invested unchanged in a
maturity-matched Treasury while variation losses are being paid from it.

## 2. Keep valuation, settlement and funding separate

Maintain signed contract quantities, contract multiplier, native payoff and
currency, position/lot accounting reference since the last settlement or fill,
current valuation mark and its source/time, unsettled P&L, settled cash by venue,
pending payable/receivable variation, collateral reservations and Treasury lots.
Keep exchange/account state distinct from the strategy's delayed knowledge.

For a LINEAR lot of signed quantity n, multiplier m and reference price K:

```
U(t) = n * m * (F_mark(t) - K)
```

At an ordinary market update, update valuation and risk but not settled cash.
Marks and executable quotes are distinct. Prefer the venue's official mark for
risk and official settlement price for settlement; retain a labeled proxy when
missing rather than treating every trade as a venue settlement. A missing signal
quote does not erase held inventory or defer known collateral obligations.

At a variation-settlement event, book P&L from K to the settlement mark for each
open lot, reset its accounting reference, and transfer the amount from U to
cash (or a variation receivable/payable until actually payable/available):

```
VM = n * m * (F_settlement - K)
K_new = F_settlement
cash_new = cash_old + VM   # when the settlement amount is available/payable
U_new = 0                 # at that same settlement mark
```

Recognize the receivable/payable in NAV while payment is pending so equity does
not disappear. Apply cash/margin availability rules for the specific venue.
Daily variation does NOT change the held quantity, close/reopen the contract,
or incur a buy/sell commission. Final expiry closes the remaining position at
the official delivery reference and applies only the actual delivery schedule.

Partial closes realize only the closed quantity's P&L since its accounting
reference; new quantities start at actual fill prices. Signed lots and intraday
fills must reconcile across a settlement. Retain lifetime P&L for attribution
while resetting only the settlement basis. Inverse contracts require their
native reciprocal-price payoff/currency, not this linear expression.

Portfolio equity must reconcile as: actual free/posted cash + Treasury market
value + spot market value + unsettled P&L + other receivables - borrowings and
payables. Count collateral assets once; futures NOTIONAL is exposure, not a paid
asset added to NAV. Moving cash into margin is not an expense or a second asset.
Settling already-marked P&L leaves NAV unchanged absent costs/other price moves.

## 3. Collateral, Treasury funding and eventual leverage

Initial/maintenance margin requirements and optional full-notional policy limits
are separate controls. Value eligible collateral with the venue's historical
haircuts/currency rules; a haircut reduces funding capacity, not the asset's
market value in NAV. Reserve pending orders/transfers only once. Test whether
cash required by a payment deadline is actually available as well as whether
account equity meets margin. Do not assume uncollected P&L is spendable as spot
cash or every posted asset earns the same rate.

When a loss requires cash: use free cash first, then the explicit buffer/sale/
repo/borrowing policy. A Treasury sale reduces its units and future interest,
incurs applicable costs and respects settlement hours/lag; borrowing creates a
liability and interest expense. If neither can meet the deadline, reject new
risk and invoke a documented risk-reduction/liquidation rule at achievable
prices. No unrecorded outside cash or unbounded negative balances. Reinvest gains
only after they become available and under the chosen buffer/commission rule.

For a fixed-quantity, nonnegative-price, frictionless linear long with initial
C0=q*F0, retained variation gives total cash plus unsettled P&L = q*F_t before
interest. This explains why full economic funding need not require outside
capital. It does NOT guarantee operational cash liquidity of posted Treasuries,
cover all haircuts/fees, or hold for unlimited-loss shorts/inverse contracts.

Later leveraged runs use the same ledger with explicit gross/net exposure,
leverage limits, initial/maintenance requirements and collateral/liquidity tests.
Fees and P&L scale with actual contracts, not deposited margin. Futures notional
above equity is not itself a cash borrowing; borrowings arise only from the
funding arrangement. Do not treat margin as a simple constant fraction if a
portfolio-margin model is requested. No leveraged trading is enabled here.

## 4. Optional product-specific fixed commissions

Add versioned schedules by product, venue/account, transaction type and currency,
with proportional fee, per-contract/unit fee, OPTIONAL fixed charge, OPTIONAL
minimum charge and applicable cap/tier. Fixed means added; minimum means floor:

```
variable = bps * filled_notional / 10000 + per_unit * filled_contracts
fee(ticket with fills) = max(minimum_ticket_fee, fixed_ticket_fee + variable)
fee(no fill) = 0  # unless an explicitly modeled non-trade fee applies
```

Caps, rebates and pass-through fees follow their own configured schedule. Zero
fixed/minimum components preserve existing proportional behavior. No broker
schedule is hard-coded or inferred from an illustrative $5 example.

A fee ticket is the broker/exchange charging unit, not a decision tick, valuation
or arbitrary partial fill. For an order-level charge, keep cumulative filled
quantity/notional and fees charged; debit only the increment of the cumulative
fee function. A hundred partial fills must not incur a hundred fixed charges
unless the tariff genuinely charges per execution. Cancellation/replacement may
or may not create a new ticket: make this explicit per schedule, never erase fee
history to avoid a legitimate minimum. No-fill cancels carry no trade fee.
Persist ticket state across checkpoints and session boundaries where required.

Apply to actual spot, futures, Treasury and FX transactions, including forced
liquidations and Treasury sales for VM. Reusing a Treasury or rolling futures
without spot conversion generates no fictitious commissions. Treasury redemption
is not a secondary-market sale; routine VM is not a trade; final delivery has a
separate fee schedule. Fees reduce cash once and their opportunity/funding cost
enters the KEEP-versus-SWAP decision before submission. Record cost currency and
causal FX conversion; don't subtract trade bps directly from an annual lease rate.

## 5. Required tests and observability

- Known long/short paths, multiplier and inverse/payoff tests; unequal partial
  entry/exit lots; fills before/after settlement; expiry exactly once.
- Internal transfer/VM NAV invariance; cumulative market P&L plus actual costs,
  interest, cash flows and liabilities reconstructs USD and BTC equity.
- No fictitious trade/fee on marks or routine settlement, and no doubled P&L.
- Fee fixed/minimum/additive modes, many partial fills, no-fill cancel, schedule-
  specific replacement tickets, multi-currency conversion and restart invariance.
- Sufficient economic collateral but insufficient immediately payable cash;
  Treasury sale/settlement delays, haircut changes, borrowing and forced exits.
- Delayed receipts do not defer exchange obligations or create spendable phantom
  cash; market days, weekends and venue settlement sessions remain distinct.
- Full-funded baseline first, then separately configured leveraged stress cases.

Audit event kinds include valuation_mark, variation_accrual, variation_payment,
collateral_reservation/release, treasury_fill/redemption, funding/interest,
margin_call, forced_exit and commission_charge. Carry transfer/order/ticket IDs,
source price/time and before/after balances. New scenarios are validated on
bounded periods before full 90-day acceptance and out-of-sample comparison.

## Mechanics references (not validation of historical data)

- CME settlement variation: https://www.cmegroup.com/education/articles-and-reports/money-calculations-for-futures-and-options
- Deribit settlement/availability and final delivery: https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement

CME daily cash variation and Deribit daily internal settlement are not identical
payment systems. Configure the chosen venue/payoff explicitly rather than
silently imposing a CME calendar on a Deribit-price research proxy.
