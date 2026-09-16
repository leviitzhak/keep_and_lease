# Cost-aware funded paired transfers

Implementation: 2026-09-16, opt-in BTC trade-replay research policy.
`trade_strategy="cost_aware_paired"` selects the new accounting, economics and
execution path. `legacy` remains the default; old saved strategies without this
field load the legacy policy. The new mode requires a 100% BTC trade-tape
portfolio, regular/linear futures and no short book. No live orders are sent.

In the GUI select **BTC market data → Trade replay → Transfer strategy →
Cost-aware funded pairs (research)**. The bounded paired example loads June 25,
00:00–00:05 UTC, $100,000, one-second decisions and 10% participation. Its purpose
is to inspect assumptions and execution; a short interval can correctly produce
KEEP throughout. The usual saved-run list, progress, checkpoints, result plots
and selected-period export paths apply.

## KEEP is the opportunity-cost baseline

`paired_transfer_economics.py` evaluates prospective wealth of an incremental
slice from the current position. It compares keeping that slice with transferring
it between spot, a cash-funded long future, or another long future. Both
alternatives begin with the same current marked capital, include already-earned
unsettled P&L once, and finish at the same horizon. Historical entry commissions
are sunk costs and are not charged again. Historical entry lease rates are not
the current KEEP opportunity cost.

The candidate grid uses 25%, 50%, 75% and 100% of the configured maximum transfer
fraction, and the configured holding horizons. Horizons must fit the maximum
forecast length and both affected futures' remaining lives. The calculation
checks funded quantities, reserve requirements, expected variation payments and
future costs. It chooses the accepted candidate with the greatest incremental
BTC wealth. A target's BTC quantity cannot exceed its source quantity; the
remainder stays as cash when fees, limits and reserves reduce the affordable
replacement quantity. Fixed/minimum commissions can make small transfers
unattractive even when an annualized carry signal looks positive.

For each candidate:

```
edge_BTC = expected_terminal_SWAP_BTC - expected_terminal_KEEP_BTC
accept only when edge_BTC exceeds the required safety surplus
```

The safety surplus includes the minimum BTC gain, the uncertainty allowance in
basis points of transferred capital, and additional modeled transaction-cost
coverage when the cost multiplier exceeds one. Future entry/exit costs already
enter the cash-flow forecasts. KEEP remains the outcome when no feasible
candidate clears these requirements; an improved headline lease signal alone
does not authorize a transaction.

The forecasts are conditional research calculations. Spot is held flat; the
current futures basis decreases linearly toward the configured settlement
reference basis as expiry approaches. The latest observable cash-proxy yield is
held constant into the forecast. Residual basis, future close and conversion
costs, reserve cash and unsettled variation are included. Cash compounds with
`exp(r * elapsed_seconds / (365 * 86400))`; scheduled variation payments change
the balance that can earn subsequent interest. Retained spot decays by the
optional annual custody/proxy expense. Terminal wealth includes residual cash
quoted in BTC. These assumptions are not predictions guaranteed by arbitrage,
nor confidence intervals or an assurance that a losing position will recover.

## Funding and settlement

`funded_ledger.py` separates spot units, free cash, posted cash, reservations,
unsettled futures P&L, pending variation and optional synthetic Treasury lots.
Marking a future changes unrealized P&L and NAV. Settlement moves the same P&L
into cash and resets the reference; it does not create a second return or a
fictitious trade. Transfers between free/posted/reserved cash preserve NAV.

The GUI policy uses a **cash-interest proxy** with full-notional funding. It does
not silently buy matched-maturity Treasury securities. The ledger has separately
tested synthetic zero-coupon lots, fees, haircuts, realizable sales and delayed
variation support, but those facilities do not establish security-level Treasury
holdings or exchange margin rules for GUI runs. Borrowing, leverage, short
positions, native inverse payoff/collateral and non-USD fee schedules are rejected.

The policy's periodic variation settlement uses the last observed exchange-side
trade mark on a fixed UTC schedule, daily by default. This is an explicitly
labeled USD-linear research settlement model. Actual marks and settlement
obligations are not delayed by the strategy's feed or fill-response latency.
Final settlement uses the replay's verified delivery metadata; it is a cash
payment under the modeled linear payoff, not physical delivery of BTC.

Deribit inverse USD trade prices are still **linear-price research proxies**.
Binance spot still assumes USDT/USD parity. Refreshing the Treasury data and
correcting discount-basis conversion do not remove those market-data limits.

## One durable transfer, staged funded execution

`paired_transfer.py` assigns one pair ID to the source and replacement legs,
their reservations, fee tickets, quotes and forecast. The same mechanism handles
spot-to-future, future-to-spot and future-to-future transfers. A future roll
reuses funding; it does not create a spot or Treasury transaction merely because
the future changed.

Source fills precede target fills. Additional source quantity is bounded by
observed participation and remaining unpaired-BTC capacity; its actual released
money is reserved before the target can fill. Pending fill acknowledgements
block further execution, and target sizes are rechecked against actual
affordability. Only one transfer is active at a time, preventing two instructions
from promising the same cash or liquidity.

The desired allocation is accumulated through bounded funded transfers. In
`fixed` and `adaptive` modes, each source slice releases cash and its funded
target slice consumes that cash. The empirical mode below instead completes one
small approved source tranche before submitting its funded hedge. The
target/source BTC ratio is fixed by the accepted quantity and can be below one
because fees and the reserve reduce affordable exposure. This is not a sequence
of three independent exchange orders: the third component is the cash-interest
proxy described above. There is no Treasury-security fill to assume complete.

Source/received/available clocks, decision/order eligibility, exchange fills and
fill acknowledgements remain distinct. Either feed can arrive first; signal
quotes must be available, sufficiently recent and sufficiently synchronized.
Delayed fill responses update known inventory later, while actual holdings and
funding change at exchange execution. Checkpoints retain orders, pair state,
reservations, cumulative fee tickets and pending observations, decisions,
order replacements and fill responses.

The fill model uses future trade prints, aggressor-side compatibility and the
configured participation fraction. It does **not** claim historical printed
volume is executable order-book depth. Half-spread and slippage apply adverse
execution adjustments; the forecast also budgets the configured adverse price
limit. In fixed mode an order cannot fill beyond its original limit; adaptive
mode changes that limit through delayed replacement instructions. Stale signal
quotes block new source fills; they do not by themselves liquidate held futures.

At later decisions, the unexecuted source quantity is compared with KEEP again
using current available quotes and the original forecast end time. The fee
comparison uses only the additional charge on the existing partially filled
tickets. If its economic surplus disappears, further source fills stop while
already funded recovery quantities and reservations remain. Mandatory expiry
instructions are not cancelled merely for losing discretionary economic appeal.

In `fixed` and `adaptive` modes, a legging timeout stops additional source fills
and retains the funded target recovery order and unmatched inventory. Missing liquidity cannot be made atomic:
unpaired exposure may remain after the timeout and at the end of the window,
and it stays in the results. The roll lead time excludes near-expiry destination
contracts and prioritizes attempts to exit/roll an entire held contract inside
that window. These risk exits can override the discretionary gain requirement
but still require a funded destination, fresh compatible observations, price
limits and actual future prints. With stale Treasury rates, only an expiry exit
to spot is permitted; new futures allocation remains blocked. Missing execution
liquidity can leave inventory until final expiry handling, so a risk instruction
does not guarantee a completed pre-expiry exit.

## Adaptive effective-lease limits and three delay stages

`paired_repricing_mode="adaptive"` enables adaptive limits for spot-to-future
entries. `fixed` remains the default for older saved files. Reverse transfers,
futures rolls and mandatory expiry instructions retain their existing funded
execution behavior. The adaptive target is derived from the accepted transfer's
economics, rather than treating the initial 10 bp price allowance as the highest
price worth paying. The original quantity, common comparison horizon, fees,
reserve and required surplus still constrain the acceptable futures price.

For a matched entry with spot-sale price `S`, futures-buy price `F`, allocated
entry fees `c_S`, `c_F`, matched quantities `q_S`, `q_F`, cash-proxy annual rate
`r`, and remaining ACT/365 years `T`, the entry diagnostic is:

```
S_net = S - c_S / q_S
F_cost = F + c_F / q_F
effective_entry_lease = r - (F_cost / S_net - 1) / T
```

Fees enter the execution prices before annualization. This measure is a
fee-adjusted entry basis, not the realized net BTC return or the full funded
cash-flow forecast. Unequal source/target quantities, retained cash, daily
variation settlement, compounding and future exit costs remain part of the
KEEP/SWAP comparison. The rate is undefined at expiry or without positive
matched quantities and a positive net spot price.

Before source execution, limits use the other leg's latest usable observation.
Price observations are consumed as they become available between the scheduled
allocation decisions. While one repricing calculation is pending, additional
updates are coalesced for a following calculation; they do not rewrite its
frozen inputs or bypass the configured delays.
Once a source slice fills and its acknowledgement arrives, target recovery
processes the oldest unmatched source fill first, using its actual spot price
and allocated fee. Matched reporting uses quantity-weighted prices across these
filled slices. Repricing
preserves the desired effective entry lease with the remaining maturity, subject
to funding and the economic checks. The futures child remains conditional on
released source cash; merely observing both prices never makes an unfunded buy
executable. Replacement orders retain the same fee ticket.

Three explicit settings model the reaction path:

1. `paired_observation_delay_seconds` delays common market-data availability;
   the optional spot/futures feed delays are additional per-feed delays.
2. `paired_decision_delay_seconds` delays processing of a frozen input snapshot.
   A quote arriving during this delay cannot retrospectively alter that
   decision's observations.
3. `paired_order_delay_seconds` delays order arrival at the market. If omitted,
   the existing Bitcoin `execution_delay_seconds` supplies this stage; an
   explicit paired value overrides it, rather than adding a second transport
   delay.

`paired_response_delay_seconds` separately delays knowledge of an actual fill.
Each adaptive replacement and economic cancellation follows the decision and
order-transport clocks too. A replacement request does
not change the live order: the previous limit remains effective until the
replacement arrives. A later actual print is required for a fill, even when
all configured delays are zero. Stale replacement instructions cannot restore
quantity already filled or revive a stopped source order.

Reservation releases caused by queued acknowledgements or cancellations carry
the queued event's timestamp, even when processed at a later market print.
Queued actions strictly before a scheduled variation settlement execute first;
scheduled variation precedes queued actions at the exact same timestamp. This
keeps the audit chronological across settlement boundaries.

Both legs filling does not, by itself, prove the target lease was obtained.
The strategy observes asynchronous markets, and fills or new prices may occur
while a replacement is in flight. Audit the matched executed quantities, prices,
fees and resulting effective lease. Target and achieved rates are separate
fields; unmatched inventory and failures remain visible. More adaptive limits
can improve completion, but performance improvement requires the comparable
backtest and is not implied by the execution rule.

## Empirical execution costs before fixing the transfer quantity

`paired_repricing_mode="empirical"` adds an execution-cost model for funded
spot-to-futures entries. It asks whether a source quantity can complete both
legs inside `paired_waiting_seconds` at the requested empirical coverage, and
uses the qualifying price budget before calculating the affordable futures
quantity. The accepted amount is therefore funded at the anticipated execution
cost rather than being sized at a favorable observation and later capped by an
unaffordable hedge. Existing fixed and adaptive strategy files retain their
previous behavior.

The calibration model counts unfilled and partially filled attempts in its
completion denominator. Expected terminal-BTC evaluation includes unsuccessful
outcomes and modeled spot-restoration costs, in addition to successful fills.
Missing support does not imply zero cost or certain liquidity. Actual order
limits, partial fills, fees and cash constraints remain binding in the replay.

The empirical instruction completes one small source tranche before its
protected marketable futures hedge. It keeps the admitted entry price bounds
fixed, subjects both entry legs to the decision-start waiting deadline, and
records bounded spot-restoration recovery separately from successful pair
completion. This is a different execution policy from the continuously
repriced `adaptive` mode; the calibration applies to the studied empirical
policy only.

The empirical setting uses a frozen historical calibration interval preceding
the scored run. The first declared test fits June 6–16 and scores June 16–26,
2026 UTC, with ten scored days reviewed before a longer empirical run. The
90-day archive leaves at most 80 scored days after the ten-day calibration
prefix; a 90-day scored empirical run requires additional historical data.
Read [EMPIRICAL_LEASE_EXECUTION.md](EMPIRICAL_LEASE_EXECUTION.md) for the waiting,
slippage, failure/recovery and data-proxy definitions. No live completion
probability or performance improvement is implied by adding the model.

## Commissions and expenses

Each product/child-order ticket uses:

```
commission = max(minimum_ticket,
                 fixed_ticket + per_unit * cumulative_quantity
                 + proportional_bps * cumulative_notional / 10000)
```

The charge for the next partial fill is the increase in that cumulative total.
The minimum is a floor, not an additional fixed fee. Zero fills incur no fee,
and restoring a checkpoint does not restart the fixed/minimum charge. Spot and
futures have independent fixed/minimum controls. The futures per-unit setting
is USD per modeled one-BTC linear unit, not a verified exchange contract fee.
Proportional fees use the existing Bitcoin trading-fee setting.

Optional `slv_expense` in this mode means annual direct-BTC custody/proxy expense;
it reduces spot quantity causally and is included in prospective comparisons.
The existing allocation replay retains its original restrictions and arithmetic.

## Versioned Treasury inputs

The new policy prefers the checked-in snapshot
`public/data/paired-rates/fred-2026-09-16-c2d2c985902c/`, selected by
`current.json`. It contains untouched FRED CSV responses for DTB3, DTB6, DGS1,
DGS2, DGS3 and DGS5 covering June 1–September 4, 2026. Every overlapping numeric
observation matched the retained vintage. No legacy CSV or historical result
was overwritten. The manifest records each retrieval timestamp, URL, raw units,
quote convention, observation coverage, byte count and SHA-256; the loader
verifies the manifest and every file before use. Snapshot identity participates
in checkpoint compatibility.

DTB3 is a bank-discount benchmark, not an annual investment return. For decimal
discount quote `d`, the new normalization first prices the **91-day benchmark**
per unit of face and then expresses its holding return on an ACT/365 basis:

```
P91 = 1 - d * 91 / 360
r_investment = ((1 - P91) / P91) * 365 / 91
```

For the retained 3.71% July 14 quote, `P91 = 0.9906219444444444` and
`r_investment = 3.797137544623342%`. The cash proxy uses this normalized benchmark
yield. It neither invents a one-day bill quote nor relabels constant-maturity DGS
par yields as zero yields. Other tenor files are preserved as provenance and do
not define the cash proxy.

Date-only source rows lack historical receipt/publication timestamps. The NEW
availability model waits for the next modeled US federal business release day,
then the following UTC midnight. For example, July 14 becomes available July
16; June 18 waits through Juneteenth/weekend until June 23. Timestamped records
use their explicit timestamps. This differs intentionally from the legacy next-
midnight assumption recorded in `TREASURY_CARRY_FORWARD_AUDIT.md`.

The delay is a conservative calendar assumption, not verified historical
point-in-time publication or revision data. The Federal Reserve currently posts
H.15 on business afternoons; its September 15 release contains September 14
observations, so observation-date-next-midnight would be too early for that
release. Extraordinary closures, publication exceptions and vintage revisions
remain acceptance limitations. [H.15 release](https://www.federalreserve.gov/releases/h15/)

Rate age is measured from the source observation. Above the configured seven-day
default, discretionary transfers fail closed while the last rate remains usable
for continuing funding valuation. Missing initial observable rates reject the
run. Snapshots expose observation time, assumed availability, age, coverage and
normalization version. Deployments lacking the new snapshot fall back to the
old vintage with the same age gate, rather than pretending July data stayed fresh.

Definition sources: [FRED DTB3 discount basis](https://fred.stlouisfed.org/series/DTB3)
and [TreasuryDirect bill-price formula](https://www.treasurydirect.gov/marketable-securities/understanding-pricing/).
The 91-day investment-yield conversion above follows algebraically from the
bill-price formula; it is not an observed same-day cash deposit rate.

## Audit and acceptance

New audit events include the authorizing decision, KEEP/SWAP terminal BTC,
required surplus, chosen quantity/horizon, frozen input quotes/rate, pair IDs,
child-order/fill IDs, source and availability clocks, cash reservations, actual
fees, unmatched quantity and completion/partial/cancellation reasons. For
spot/future transfers, observed lease and executed-price-only lease keep the
decision maturity/yield fixed; completion-time lease is a separate measurement.
Those price-based quantities are not realized net BTC returns.
Adaptive audits additionally retain the target effective entry lease,
replacement requests and market arrivals, their frozen decision timestamps,
applied/rejected revisions and fee-adjusted matched entry diagnostics. The
standalone `scripts/check-paired-replay-audit.py` applies a replacement only at
its arrival event and independently reconstructs matched fill prices and fees
when the new fields are present; older fixed-order archives remain readable.

Ledger valuation fields expose free/posted/reserved cash, unsettled/pending
variation, synthetic Treasury value, liabilities and BTC-quoted NAV. Paired-run
book plots and reconstruction use cash plus Treasury value plus unsettled P&L
plus signed pending variation less liabilities, then add spot for total NAV.
Reservations are restrictions on existing cash, never a second asset. Funding-
asset and cash-availability plots distinguish economic funding from immediately
spendable cash; missing historical fields remain unknown. The GUI
summarizes submitted, completed, partial, timed-out and unresolved instructions,
so unsuccessful attempts remain in the denominator. Existing saved results are
not assigned invented pair IDs or rerun with the new economics.
When present, GUI diagnostics also show repricing mode, applied replacements,
the three delay stages and separate per-feed/acknowledgement extras, and the
latest pair's target versus matched-fill effective entry lease, matched quantity
and rate shortfall. Historical results without these fields leave them absent.

Selected-period XLSX exports retain Overview, Valuations, Events and Parameters,
and add **Transfer decisions**, **Paired transfers** and **Horizon alternatives**
sheets for the new policy. These expose KEEP/SWAP common-horizon wealth, costs,
size/horizon feasibility, pair IDs, matched fills and lease diagnostics. Flattened
event fields and the full event JSON are both retained. A selected interval can
cut across a transfer lifecycle: absence of its result within that interval does
not establish failure.

Local validation covers common-horizon economics, fees and quantities, funding
accounting, causal rates, delayed information, partial fills and checkpoint
state. The refreshed yield coverage permits a full-window experiment; it does
not certify a new 90-day strategy run. Prior completed 90-day research results
remain completed legacy computations.

Before any threshold tuning, the acceptance split is declared as development
`[2026-06-06, 2026-08-01)` and chronological holdout
`[2026-08-01, 2026-09-04)`. Current defaults are unoptimized. Passing structural
tests or retrieving the full-window rates does not constitute measuring returns
on that holdout.

Remaining acceptance work includes chronological holdout/full-period comparison,
measured realized-versus-KEEP outcome attribution, verified venue margins and
settlement/payment calendars, actual Treasury securities and financing costs,
native inverse acceptance, quote-depth validation, and executable risk/exit
handling under severe funding or liquidity stress. See `TODO.md` and
`NEXT_STRATEGY_IMPLEMENTATION.md` for the retained broader specification.
