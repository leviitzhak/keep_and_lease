# Next implementation: cost-aware, funded paired transfers

Status: implementation underway on 2026-09-16. The opt-in BTC trade-replay
policy, separate funded linear ledger, net KEEP-versus-transfer economics,
durable paired execution, GUI controls and immutable refreshed Treasury snapshot
are implemented. See [COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md)
for the code's exact behavior and remaining limitations. This page retains the
broader acceptance specification; local implementation does not establish full
90-day, native-venue or quote-depth acceptance.

The current adaptive extension implements fee-adjusted effective-lease limits
for spot-to-future entries and separate observation, decision and order-arrival
delays. Reverse/roll adaptive pricing, actual depth/security-level funding and
full outcome acceptance remain broader requirements below. Fixed-limit presets
and their historical results remain available for comparison.

## Objective and invariant

Retain commodity exposure while choosing between direct spot and futures backed
by cash/Treasuries. Change only feasible incremental quantities when conservative
expected NET commodity wealth exceeds the KEEP-current-position alternative by
an adequate safety surplus at a common future horizon. For BTC, compare
USD_NAV / spot, with the same initial wealth, external-flow treatment and risk.
The existing position's historical entry rate is not its forward opportunity
cost. Do not count sunk fees again or assume a forecast guarantees break-even.

The unit of reallocation is the SAME durable transfer instruction for spot ->
(cash/Treasuries + futures), the reverse, and coordinated futures rolls. Both
legs, funds, reservations, fees and incomplete exposure belong to its audit.
Risk/expiry exits may override a discretionary profit target. No automatic spot
churn or disposal of a held future solely because its quote becomes stale.

## Complete specification map

| Component | Detailed specification |
|---|---|
| Coupled transfers, liquidity, funding and partial fills | [PAIRED_TRANSFER_DESIGN.md](PAIRED_TRANSFER_DESIGN.md) |
| Availability delays and observed/executed lease comparison | [QUOTE_LATENCY_AND_CARRY_PLAN.md](QUOTE_LATENCY_AND_CARRY_PLAN.md) |
| Incremental economics versus KEEP, exits and full backtest | [COST_AWARE_PAIRED_TRANSFER_PLAN.md](COST_AWARE_PAIRED_TRANSFER_PLAN.md) |
| Futures marking, cash settlement, margin and fixed commissions | [FUTURES_MTM_AND_COMMISSION_PLAN.md](FUTURES_MTM_AND_COMMISSION_PLAN.md) |
| Exact old Treasury vintage, curve and accrual/pricing behavior | [TREASURY_CARRY_FORWARD_AUDIT.md](TREASURY_CARRY_FORWARD_AUDIT.md) |
| Preliminary examples, not funded strategy acceptance | [COST_AWARE_PRELIMINARY_ANALYSIS.md](COST_AWARE_PRELIMINARY_ANALYSIS.md) |

The remaining items in these component specifications are part of this workstream.
[TODO.md](TODO.md) holds its primary progress checklist. Other
research ideas, UI backlog, Sites and heavy infrastructure remain separate.

## Implementation and acceptance sequence

### 1. Pin the baseline and normalize the inputs

Preserve current tested strategies, engine/data hashes and immutable results.
Audit historical Treasury coverage and source publication/availability times;
refresh as a NEW data version, not by silently changing old results. Convert
bill discount-basis quotes and build/pricetag the chosen bond model explicitly.
Use actual securities when possible, including face, price, coupon, accrued
interest, settlement/trading calendars and fees. Never claim a 1-day quoted bill
when a 91-day benchmark has merely been clamped to that tenor. Establish native
contract multiplier/payoff, collateral/settlement currency and delivery reference;
Deribit inverse-price observations remain a labeled linear proxy unless the
native payoff/collateral is actually modeled.

### 2. Implement the self-financing ledger and fee engine first

Separate spot, Treasury lots, free/posted cash, liabilities, unsettled futures
P&L and pending variation payments. Mark holdings; settle variation without
creating a second profit or a fictitious trade. Finance actual debits using a
cash reserve, realizable Treasury sales or permitted borrowing; account for the
resulting lost interest and fees. Margin and liquidity are distinct tests.

Add optional fixed, minimum-ticket, per-contract and proportional commissions
per product/venue/currency and effective schedule. Distinguish additive fixed
charges from a minimum charge. Aggregate partial fills at the schedule's real
charging unit, with checkpoint-safe cumulative fee state. Include Treasury
transactions and proxy expenses, spread/impact, delivery, FX and funding. Do not
manufacture bond/spot trades on a futures roll that reuses those holdings.

### 3. Make signals causal and execute paired quantities

Keep source, received, available, decision, order-entry, exchange-fill and
response clocks separate. Delay the information, not the underlying market or
settlement obligations. Use either ordering of observations only once both are
available, subject to age/skew. Size the transfer using appropriate bid/ask/depth
for the needed quantity; tape-only participation remains a stated assumption.
Keep pending transfers and funding reservations through signal replacements,
partial fills, rejects, cancels, outages, midnight and checkpoint restart.

### 4. Add the KEEP-versus-SWAP economic decision

Evaluate equal-capital prospective BTC wealth with residual basis, expected
settlement/reference difference, Treasury returns, variation/funding and all
future costs on each alternative. Screen with additional carry times feasible
holding period only as an approximation; the final comparison uses cash flows.
Apply uncertainty/cost-recovery buffers and a no-trade region. Optimize feasible
incremental size, especially with fixed fees; a larger signal movement alone
is not enough. The intended horizon cannot exceed expiry or credible liquidity,
funding and risk limits. Separate signal smoothing, decision cadence, holding
policy, roll lead time and contract maturity.

For discretionary exits, accept a realized net target OR a sufficiently better
forward alternative. Use pair-level price limits and re-evaluation of remaining
quantity; do not erase failed transfers from the sample. Settlements, margin
and explicit risk limits can require an exit before profit. A futures roll need
not touch spot or the Treasury unless exposure or funding requires it.

### 5. Add diagnostics at the same time, not after the backtest

Freeze authorizing quotes, quantities, calculation intermediates and KEEP/SWAP
forecasts. Match actually paired fills under the transfer ID. Compare observed
lease, executed-price-only lease at fixed decision maturity/yield, completion-
time lease and realized BTC return as DISTINCT measurements. Retain input age,
latency, fees, failed/partial instructions, unmatched inventory, collateral and
funding flows, net asset reconciliation and event-level reason codes. Never
reconstruct exact pair IDs from unrelated old fills without validated evidence.

### 6. Validate and accept the full strategy

Test sign/multiplier/native-currency P&L, intermediate/final settlement,
position changes at settlement, NAV invariance of internal cash transfers,
zero-fee baselines, fixed-fee partial fills/replacements, delayed information,
funding and haircut shocks, forced exits, and restart determinism. Reproduce
an economic fully funded cash-only linear long as a baseline. Prepare signed
positions/leverage diagnostics but keep leverage disabled unless explicitly
configured and covered by initial/maintenance-margin and liquidation tests.

Compare short runs from identical starting states before the full 90 days.
Evaluate gross/net BTC wealth and drawdowns, turnover, all costs, paired-fill
ratios, prediction error versus KEEP, collateral calls, forced Treasury sales,
borrowing and failure/censor denominators. Reserve chronological holdout dates
before tuning thresholds. Rate-vintage deficiencies and quote-depth/proxy limits
must be resolved or explicitly limit the acceptance claim. Older completed
90-day research computations stay marked done; they do not certify this NEW
strategy or a freshly funded execution model.

## Delivery boundary

The new implementation is opt-in; the existing policy, source files, saved
strategies and completed results retain their original behavior and provenance.
The 2026-09-16 FRED snapshot is a new checked-in data version. Live trading,
leverage activation and IAM changes are outside this implementation. Group
coherent implementation/test changes before using the single GCP preview;
do not run the deferred local Sites preview. Deployment and full-period
acceptance must be reported from actual completed evidence.
