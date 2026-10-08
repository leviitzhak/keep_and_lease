# PRD ladder policy comparison, revision 3

Research only. No application deployment, GUI change, master merge or live
exchange order. Original replay and revision-2 outputs remain unchanged.
Use the bounded research request on agent/cloud-autonomous-access. Install
source with [skip ci], then increment the request sequence in a separate commit.

## Scope and matrix

Both original periods and pairs, full ordinary-trade coverage:
Sep26/Dec26 [2026-03-06,2026-06-06); Dec26/Mar27 [2026-06-06,2026-09-04), UTC.
Six shared 0.1 BTC entry allocations, maximum 0.6 BTC at sizing, inverse $10
face contracts, $2.50 price ticks. Original mirrored opening and closing PRD
ladder unchanged. PRD d=APR_far-APR_near, ACT/365.
Maximum newly leading fill is 0.02 BTC at its execution price. This is not a
portfolio backlog limit; several tasks may be unmatched and BTC value drifts.

At both 500 and 10 ms, compare:
* control: original targets without source-age filtering or a hedge deadline;
* fresh60: 60s futures-reference / 5s index-age filter;
* relax: target held 2s, price concession ramps linearly to 5bp at 5s;
* timed: same relaxation, then cancel/reconcile and complete-or-unwind proxy;
* combined: fresh60 plus timed.
Additional 500ms combined sensitivities: futures-age 5s, 30s and 300s; and
carrying the APR observed at its own contemporaneous index. Fourteen cases per
pair. All comparisons share the revision-3 cancellation model. Revision-2
results may be displayed separately as an ideal-coupling reference, not mixed
with policy effects. This is a predetermined sensitivity grid, not optimization.

## Timing and cancellation

Market observations and private fill notifications are assumed immediate.
Quote arrival, cancellation arrival, and cancellation-return acknowledgment
each take D (500 or 10 ms). After a fill, cancel both old task orders, but leave
them eligible through cancellation arrival. A print exactly at cancellation
arrival is conservatively processed first; a new order cannot fill at its
exact arrival timestamp. At D after cancel arrival, reconcile all fills and
size the next order from the residual. No replacement hedge is sent beforehand.

Resting orders on a leg are modeled as one edited order. An in-flight quantity
edit subtracts cumulative intervening fills. Timers run through intervals
without market prints. Cancellations export request time, exchange-effective
time, acknowledgment time, quantities at request/ack, and late fills. Shared
print volume and own-order crossing rejection remain enforced.

The original ideal lock selecting one mirrored opening direction per slot is
retained. A shadow diagnostic counts strict-through prints against the removed
opposite-direction order during one cancellation-delay window. This diagnostic
does not fill those orders; any positive count is a remaining optimistic model
limitation. It does not capture unactivated mirrored messages. This is not a
full exchange/private-feed or queue simulator. Fully consumed task quantities
are guarded, and complete slot resets retain the original native conservation.

## Freshness and relaxation

The futures-reference gate applies while a task is balanced, before starting
another unmatched opening OR closing attempt. After a first fill, its executed
APR is a historical fact and never expires. The index gate still applies to
APR-derived orders. Stale quotes initiate delayed cancellation, including
fills during cancellation. Quote calculation does not reset source timestamps.
Index data is carried from trade-attached observations, not an independent
index stream. These tight age gates therefore test tape observability as well
as trading policy; sparse futures prints do not establish a stale live book.

When unmatched, retain the first unmatched time through partial catch-up and
late additional fills. The anchor is quantity-weighted executed APR of the
remaining unmatched fills. At time a after first unmatched execution, concession
bp = 5 * clip((a-2 seconds)/3 seconds,0,1). Raise a remaining buy limit or lower
a remaining sell limit by that fraction of its original-target price, rounding
conservatively to the native tick. Record original target, effective target,
and actual paired PRD separately. This caps the price concession at quote time;
it is not a realized-loss or round-trip-profit guarantee as the index moves.

The carry sensitivity holds each observed APR computed from that trade's own
index/time and projects a reference future against current index/time. It keeps
the original observation timestamp and age gate; it invents no new quote.

## Deadline and rescue proxy

At 5 seconds unmatched, cancel and reconcile. With fresh observed index (5s)
and a candidate leg's trade reference no older than 60s, compare:
1. incremental implementation shortfall of completing the counterleg relative
   to its original PRD target, plus assumed rescue fee;
2. loss/gain from reversing the remaining leading fills, plus assumed fee.
Choose the lower modeled cost. These lead to different inventory states: this
is an explicit heuristic, not a proof of economically optimal selection.
Choose using only observations available then; no future print picks the leg.

The selected leg gets a 10bp price cap from its last observed trade. After D,
allow up to one second to find a later opposite-aggressor print. Estimate fill
price at that print plus 2bp adverse slippage, rounded adversely to a tick, only
if inside the cap and with shared available native print volume. The one-second timeout initiates delayed cancellation, so a print during that
cancellation delay can still fill. Use at most one such print per attempt. Cancel/reconcile partial or unfilled remainder;
retry only after a new observed market event. Data gaps remain unmatched.
This is a NEXT-PRINT STRESS PROXY, NOT a reconstructed IOC or market-order fill.
The 5-second deadline starts the rescue process, not guaranteed flatness at 5s.
No estimate uses an assumed fill exactly at the deadline.

Completing an opening creates a matched spread; undoing its leading leg closes
that unpaired inventory. Completing a closing removes the spread; undoing its
first fill restores it at the new execution price. Undo only unpaired quantity,
never previously matched quantities. Reversed opening quantity can be retried
within the original slot allocation; reversed closing quantity returns to its
original closing rung. Native conservation is asserted throughout.

## Accounting, outputs and verification

Both-leg inverse BTC P&L, FIFO realized P&L within each slot/cycle, exact native
positions, turnover and current BTC equivalents. Include fees as an explicitly
assumed sensitivity: 1bp passive/relaxed and 5bp rescue, charged on fill BTC
notional. This is not a historical exchange fee schedule. Gross curves remain
available. No margin, collateral return, funding, liquidation or book impact.

Export fills, matched pairs, episodes, cancellations, daily records and chart
timeline. Preserve every fill timestamp and approximately 15-minute valuation
samples. Matched-only PRDs never include a missing leg or an unwind treated as
a fictional pair. Include actual phases, prices, both APRs, effective/original
PRDs, source age, cancel state, costs and timestamps in event records.
Matched waiting-time statistics condition on eventual matched executions;
unwound and unresolved episodes are separately reported to avoid hiding them.

Focused tests cover delayed leading/counterleg fills, exact reconciliation,
in-flight quantity edits, undo accounting, non-expiring executed anchors,
relaxation direction for all leg/direction/action combinations, and cancellation
without further market prints. Independent output audits recompute inverse
P&L, inventory, print capacity, cap, matching and FIFO balances.

Deribit order-state and cancellation references:
https://docs.deribit.com/api-reference/trading/private-cancel
https://docs.deribit.com/api-reference/trading/private-get_order_state
https://docs.deribit.com/api-reference/trading/private-get_user_trades_by_order

## Verified input export
The separate prd-input-export request copies only the 180 immutable, hash-verified
Dec26/Mar27 trade files, seeds and receipts to an artifact for local replay. It
uses the same bounded loader, reads existing GCS archives, makes no exchange
request, and runs no strategy. No credentials or environment files are exported.
