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
10% of each print's native volume (rounded down), and 1,000 ms delay. The
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

Install source with [skip ci] to avoid application deployment. Launch only
the bounded request `.cloud-agent/requests/prd-ladder-research.json` with
`{"schema_version":1,"action":"replay-six-level-prd-0.6-btc","sequence":1}`;
increment sequence (bounded 1..100) to rerun a corrected research revision.
The workflow reads selected GCS market data, writes content-addressed research
results and artifacts, and logs research-result chunks accessible through the
GitHub connector. It never exports credentials or identity tokens.
