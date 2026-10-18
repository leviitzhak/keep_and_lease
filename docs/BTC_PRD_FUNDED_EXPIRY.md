# BTC PRD: funded completion through expiry

**Current complete strategy:** [BTC_PRD_FUNDED_STRATEGY.md](BTC_PRD_FUNDED_STRATEGY.md).
This note retains the derivation. The latest owner request permits funded
hold-to-expiry completion, with 60 days serving as an earlier review objective.
The consolidated document also explains entry versus settlement conversion
prices and rolls as opening transformations after actual position netting.

Date: 2026-10-18. Status: design clarification; no strategy implementation or
new backtest. This note concerns regular, cash-settled **linear** futures.
The historical inverse-contract unit experiments retain their original scope.

The owner adds spot purchases at long expiry and spot sales at short expiry,
backed by cash and underlying available in chronological order. This is a
funded synthetic-delivery strategy. It changes the completion route relative
to closing a futures-only calendar spread before either leg expires.

## Expiry cash-flow identity

Let A be a long of q underlying units executed at price K_A, and B a short of
the same q executed at K_B. Their maturities are T_A and T_B; no near/far
orientation is imposed. First ignore interest, fees, proxy decay and execution
basis. Assume the expiry spot transaction is possible at the settlement index.

| Leg | Cumulative linear futures P&L | Expiry spot trade | Combined economic effect |
| --- | --- | --- | --- |
| Long A | q(S_A - K_A) | Buy q for q S_A | Spend q K_A; acquire q units |
| Short B | q(K_B - S_B) | Sell q for q S_B | Receive q K_B; release q units |

These are lifetime totals, **not** a claim that all futures P&L is paid at
expiry. Futures variation is settled during the holding period [1, 2]. The
actual cash ledger must record those earlier flows once.

| Expiry order | Natural starting backing | Completion, before costs |
| --- | --- | --- |
| Long first, T_A < T_B | Cash for effective purchase, plus liquidity reserve | Buy q at A; sell q at B; cash increment q(K_B - K_A) |
| Short first, T_B < T_A | q underlying units, plus any cash deficit and liquidity reserve | Sell q at B; repurchase q at A; restore q units and retain cash q(K_B - K_A) |

Thus the nominal gross increment from funded completion is q(K_B-K_A), in
either order. The short-first case is an increment over retaining the initial
underlying quantity. The cash-first case returns cash; it is not a guarantee
of beating BTC purchased with the initial cash at inception. Interest on cash,
financing, fees and proxy costs affect net results. Benchmark opportunity cost
is reported separately from actual cash expenses.

If the actual spot executions are P_A and P_B, the corresponding lifetime
cash increment is:

```
G = q * ((K_B - K_A) + (P_B - S_B) - (P_A - S_A)) - actual_costs
```

Settlement-index/spot mismatch, trading delays and fees must be modeled. A
synthetic index execution is an assumption, not an observed executable quote.
Cash interest and funding flows belong in their own dated ledger entries.

## A positive APR difference is not the secured gain

For simultaneous entries using a common spot S_0 and remaining years tau:

```
D_entry = a_B - a_A
K_B - K_A = S_0 * (a_B * tau_B - a_A * tau_A)
```

Different tenors prevent replacing the price difference with D_entry. For
example, take S_0=$100,000, short B at 5% APR with 0.75 years remaining, and
long A at 4% with 1 year remaining. PRD is positive 1 percentage point and
the maturity-separation ratio is 25%, but K_B=$103,750 < K_A=$104,000.
For q=1, selling the initial BTC at the short expiry does not by itself fund
the later repurchase: $250 additional cash is needed before costs, ignoring
interest. Funding feasibility and profitable completion are separate checks.

Retain APR direction/ranking and per-pair ladders as requested. Recommended
additional admission test for a claimed profitable completion route: price
cash flows, any defensible interest/funding assumptions, costs and reserves
must support positive net gain against the declared cash/holding benchmark.
Do not claim that positive PRD alone passes this test. Baseline acquisition
below the exposure floor remains a separately attributed policy.

For equal q, a positive completed cash surplus G can buy G/S_final additional
underlying units at final conversion. Its sign is positive, but its quantity
is not fixed in advance. In the short-first case the original q units are
restored as well. A predetermined extra underlying quantity would require a
separate sizing/hedging rule; it is not established by an equal-q APR gap.

## Early closing realizes a change in the price spread

Before either expiry, let X_A be the executed sale price closing the long and
X_B the executed purchase price closing the short. For the matched quantity:

```
gross_early_PnL = q * ((K_B - K_A) - (X_B - X_A))
net_early_PnL   = gross_early_PnL - attributable_actual_costs
```

If 0 <= X_B-X_A <= K_B-K_A and the entry price gap is positive, this realizes
part of the nominal gross completion gain and relinquishes the remaining
price spread. It is not always only a part: a negative exit spread can realize
more than the original gap; a wider exit spread can produce a loss.

Ordinary profit-seeking exits should be priced from actual lot entry prices,
native quantities and an explicit net-profit target, not an APR-gap threshold
alone. For target cash gain g and estimated total attributable costs c, an
equal-q quote condition is X_B-X_A <= K_B-K_A-(g+c)/q. Costs already paid are
included once when measuring the cycle; future costs remain estimates until
executed. Asynchronous second-leg fills cannot be assumed to meet that condition.
Keep PRD as a diagnostic and opening-ladder variable. Numerical profit targets
and fill/deadline recovery policy still require calibration.

If one future has already expired, the remaining package includes the spot
holding or cash generated at that expiry. Revalue and close that whole package;
do not apply the two-live-futures formula or orphan downstream commitments.

## Chronological backing and margin liquidity

The owner's backing rule applies to every dated obligation, not only each
pair in isolation. A proposed implementation has two linked views:

1. **Completion commitments:** actual cash/underlying backing, funded earlier
   long receipts and covered earlier short receipts, allocated by quantity,
   currency, account and availability time. Process obligations chronologically.
   In a zero-cost delivery-equivalent planning view, a long contributes
   (-q K_A cash, +q units), and a short (+q K_B cash, -q units). Every chronological
   prefix must be backed; a positive final balance alone is insufficient.
   This is an economic planning view, not extra cash entries in the real ledger.
2. **Actual liquidity:** free and posted collateral, initial/maintenance margin,
   dated variation payments, settlement availability, spot purchases/sales,
   conversions and costs. Reconcile this view with completion commitments without
   posting the delivery-equivalent cash totals a second time. Check a declared
   margin/stress model; a future receipt cannot pay an earlier margin call.

An earlier long counts as future underlying only if its purchase is funded;
an earlier short counts as future cash only if its sale is inventory-backed.
The same units or proceeds cannot back multiple obligations. Account for pending
orders and late fills without assuming an unfilled order is a delivered asset.
One receipt may fund several smaller commitments only up to its unallocated
amount. Available collateral may also be encumbered and unavailable for sale.

Use actual settlement and transfer times, not just expiry dates. Same-day
receipts cannot fund earlier payments unless operational netting or a bridge
is explicitly supported. Recompute dependencies on every partial fill, close,
roll, proxy sale and restart; closing an upstream long can invalidate a later
short's backing even if the local pair exit is profitable. Persist allocations
and verify conservation across actual positions and logical pair ownership.

Proxy backing uses projected underlying-equivalent units after expense decay,
plus a declared execution/basis assumption. Today's q BTC equivalent is not
automatically q available at a later expiry. Expense is charged once in the
ledger; APR is a ranking input, not an additional expense debit. Any modeled
sale/rebuy for margin must reduce and subsequently restore real available backing.

## Relationship to retirement and remaining preparation

The latest owner request includes holding until expiry when early closing or
rolling has not completed. Accordingly the earlier before-60-day target is a
planning/review objective. Fully funded settlement is permitted; funding failure
still requires recovery. Stop new openings in retiring contracts. Preserve this
explicit policy in the next funded replay rather than silently retaining the
older mandatory-liquidation interpretation.

Minimum acceptance cases for the later implementation:

- Both expiry orders reconcile to the same nominal price-gap identity under
  several settlement-price paths; early closure reconciles to the price-spread
  change, including wider and sign-changing exit spreads.
- Positive PRD with a negative price gap is not labeled profitable carry;
  cash-first and holding-first benchmarks and underlying conversions differ.
- Chained receipts, multiple claims, insufficient short proceeds, same-day
  availability, unfilled orders and upstream partial closes preserve funding.
- Variation-margin paths and proxy decay can require extra liquidity/backing
  even when the nominal completion total is positive; no double P&L debit/credit.
- Restart retains obligations, reservations, native quantity and execution-price
  anchors; the selected retirement/settlement policy is enforced and audited.

This analysis supplies accounting identities, not an empirical profitability
result. The existing inverse-contract historical studies do not validate this
regular-linear funded completion model.

Preparation check: decimal arithmetic reconciled six expiry-order/price-path
cases with an intermediate variation payment, three early-close spread cases,
and the positive-PRD/negative-price-gap example. This checks the identities,
not a margin model, execution simulator or strategy return.

Sources for futures cash-flow mechanics (the identities above are derived here):

1. CME Group, [Money Calculations for Futures and Options](https://www.cmegroup.com/education/articles-and-reports/money-calculations-for-futures-and-options).
2. CME Group, [Cash Flow in Metals Futures vs Forwards](https://www.cmegroup.com/education/courses/introduction-to-base-metals/cash-flow-in-metals-futures-vs-forwards).
