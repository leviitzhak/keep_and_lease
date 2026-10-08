# Six-level PRD ladder research

Research-only implementation on the operator branch. No trading API, GUI
catalog change, application deployment or master merge. The bounded request
replays Dec26/Mar27 from 6 June through 3 September 2026 UTC using the original
immutable archive and completed Mar27 extension. The companion local runner
replays Sep26/Dec26 from 6 March through 5 June 2026 UTC.

## Strategy and sizing

PRD is APR_far minus APR_near; APR=(future/index-1)/ACT365 maturity.
Six opening levels: +/-1.5%, 1.6%, 1.7%, 1.8%, 1.9%, 2.0% annualized percentage
points. Positive direction buys near/sells far; negative reverses both legs.
Closing targets have the same signed PRD as the opening direction: +/-1.0%,
0.9%, 0.8%, 0.7%, 0.6%, 0.5%; closing trades reverse the opening trades.

There are six shared slots, 0.1 BTC allocation each; mirrored directions
compete for the same slot. Each slot is rearmed only after its entire original
opening quantity and all six exits complete. There is no daily reset.
The target is converted at the quote to equal USD face on both legs, rounded
down to $10 contracts, using the lower of index and the two opening limits.
An opening fill fixes the native quantity for that cycle. Equal native face
gives an inverse calendar spread; this is not the earlier ideal continuous
BTC-sized replay. **0.6 BTC is an entry allocation cap, not a promise that
marked BTC exposure cannot rise when BTC price falls.** No forced rebalancing
or stop loss is added. Report observed exposure separately.

As paired opening contracts become available, allocate them equally across
the six closing rungs, with remainder contracts assigned from 1.0% downward.
The sum of assigned closes exactly equals the paired opening contracts;
filled closing rungs are never replenished by reallocating existing inventory.
Partial opening and closing legs remain recorded; no unmatched exposure is
discarded. All closing fills consume original native contracts.

### Default asynchronous chunk cap (revision 2)

Each paired execution (an opening rung or one of its closing rungs) may lead
by at most a newly executed 0.02 BTC chunk, rounded down to native $10 face
using the lower of its posted limit and observed index at quote time. The
leading leg pauses until its lagging leg catches up. Every leading fill is
independently checked against 0.02 BTC at its posted limit. This is a per-task
fill cap, not an account-wide unmatched exposure cap. Multiple opening and
closing tasks can be unmatched concurrently; BTC equivalents drift afterward.
The dashboard explicitly displays their aggregate backlog and account net
directional exposure. Original six-slot entry allocations remain 0.1 BTC each.

## Execution model

Base: 500 ms posting/repricing delay, strict trade-through (never touch), fills
at the rounded posted limit, either historical aggressor, and shared native
print capacity across every order in the account. Price then activation time
determines priority. A print is consumed only once. Block/RFQ/combo trades are
excluded from both execution and price observations. Orders cannot consume a
trade at their exact activation timestamp. Timestamp groups are all processed
before their new observations can generate future quotes. Source timestamp
reversals are normalized by per-instrument sequence prefix-maximum time.

At each quote arrival the old quote is canceled; reject a replacement that
would cross any of this account's other resting orders on that instrument.
Retry on subsequent observations. This prevents profit from impossible
simultaneous self-crossing quotes; it does not reconstruct the external book.

After any leading fill, freeze its APR, pause the leading leg and price the
lagging leg from that APR and the signed PRD target. Reprice with the causally
observed index and time. Once balanced, float both legs again after the delay.
This retains the **ideal instantaneous coupling/cancellation gate** of prior
research: cancellation races, exchange queue position, post-only rejection,
external order-book depth and adverse market impact are not
reconstructed. Therefore it is a research fill estimate, not an executable
or guaranteed conservative live P&L forecast. Sparse last-trade references
can be stale. Native trade-attached index and mark prices are carried forward;
there is no independent index/book feed.

Sensitivity cases restrict fills to the opposite historical aggressor,
10% of each print's native volume (rounded down), 1,000 ms delay and 10 ms delay. The
10% case is a capacity sensitivity, not an estimate of actual queue position.

## Accounting and output

Inverse P&L is in BTC: signed face*(1/entry-1/exit). Open positions are marked
using the latest historical Deribit mark_price carried on each instrument's
trade; last-trade marking is also reported. End positions are not assumed
liquidated. Fees are sensitivity inputs of -1, 0, +1 and +5 bp of each fill's
BTC notional. No historical fee tier is claimed. No margin, liquidation,
collateral BTC price gain, tax or capital return is modeled.

Outputs include every fill, full cycles, paired closing completions, daily
equity/inventory, input hashes, exact source receipts, fee sensitivity,
drawdown and unmatched exposure. Test gates cover exact touch and activation,
shared print volume, partial-pair closure assignment, mirrored slot sharing,
and independently calculated inverse round-trip accounting. Every live fill
also asserts native conservation, latency and strict crossing.

Revision 2 also records paired FIFO fill matches with actual near/far APR,
buy/sell APR, actual signed PRD, target PRD, native quantity, each leg's BTC
quantity, and both execution timestamps. Until both legs fill, no actual PRD
is reported. Buy spread means buy far/sell near; sell spread means sell
far/buy near. Cumulative average PRDs use native USD-face weights, combining
opening and closing matched executions in the corresponding spread direction.

Interactive time series retain every fill timestamp plus the first observed
market event in each 15-minute bucket, start and end. No interpolation is used
for strategy decisions. Inventory USD is native face; current BTC equivalents
use the causally carried index. Open pair-equivalent counts each matched pair
once plus unpaired inventory; gross legs count both legs. Backlog sums absolute
outstanding task imbalances without offsetting tasks; account direction nets
all signed native face. Traded quantity counts both legs and both entry/exit;
BTC traded uses each execution price. Total marked USD P&L revalues retained
BTC at current index; realized USD at realization and the subsequent currency
revaluation are distinct series. Fees remain excluded from these gross plots.

Hedge timeout and quote-freshness policies below are proposals, not enabled
in revision 2, so cap and delay effects can be compared without other changes.

## Proposed unmatched-leg and freshness policies

After a leading fill, pause that task, retain native remaining quantity and
start its timer at the first unmatched fill (partial catch-up never resets it).
For an initial test: keep the target for 2 seconds; between 2 and 5 seconds
relax the achievable PRD toward a bounded cost budget; at 5 seconds cancel
and reconcile pending orders, then compare completing the other leg against
undoing the first fill using fresh executable book prices, fees and depth.
Use marketable IOC limit orders with a price cap, not assumed fills at the
deadline. Completing an opening creates the spread; undoing it returns flat.
Completing a closing removes the spread; undoing its first fill restores the
pre-close spread. Late fills must reduce remaining hedge quantities before a
replacement is sent. A portfolio gross-unmatched cap is a separate control.
The 2/5-second schedule and price budget require sensitivity testing, not a
claim of calibration. Tape-only data cannot establish executable IOC prices;
book data is preferred, otherwise label next-opposite-trade plus slippage
stress cases as approximations and preserve any period without liquidity.

For freshness, retain the source timestamps of each futures reference and
index separately from calculation/posting time. Recalculating a price does
not refresh an old observation. Propose a 60-second futures-trade and 5-second
index-age gate for a first tape sensitivity, alongside 5/30/60/300-second
futures thresholds. For live quotes use fresh order-book state, sequence
continuity and feed heartbeat; start by testing a 1-second feed-staleness
threshold. An unchanged book price is not stale merely because it has not
traded. Timers cancel stale opening orders even without another market print,
with cancellation delay respected. A fill during cancellation still counts.
Risk-reducing hedges must not be blocked indefinitely by an entry freshness
gate: they use their own verified current execution feed or stop new entries
and escalate the missing-data condition.

Avoid mixing an old futures dollar price with a fresh index blindly. Test
carrying the APR observed using its contemporaneous index and projecting the
reference future using current index and remaining maturity, while retaining
the original APR timestamp and the same age limit. This is an explicitly
modeled carry assumption, not a new market observation.

Install source with [skip ci] to avoid application deployment. Launch only
the bounded request `.cloud-agent/requests/prd-ladder-research.json` with
`{"schema_version":1,"action":"replay-six-level-prd-0.6-btc","sequence":1}`;
increment sequence (bounded 1..100) to rerun a corrected research revision.
The workflow reads selected GCS market data, writes content-addressed research
results and artifacts, and logs research-result chunks accessible through the
GitHub connector. It never exports credentials or identity tokens.
