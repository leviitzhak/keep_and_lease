# BTC full-long reference: funded paired policy, 500 ms, estimated fees

Prepared September 16, 2026 at the owner's request. The reference is
`strategies/full-btc-long-gradual-1m-regular.json`; the saved run configuration is
[`research-btc-full-long-gradual-paired-500ms-fee-10bp.json`](../strategies/research-btc-full-long-gradual-paired-500ms-fee-10bp.json).

## Configuration

| Setting | Value |
| --- | --- |
| Policy | `cost_aware_paired` |
| Decision clock | 0.5 seconds |
| UTC period | `[2026-06-06 00:00, 2026-09-04 00:00)`; 90 days |
| Scheduled decisions | 15,552,000; within the preview's 16,000,000 ceiling |
| Opening trade-replay capital | USD 100,000, the replay default |
| Product | BTC only, long-only regular/linear research proxy |
| Execution participation | 100%, copied from the reference |
| Maximum quote age | 60 seconds, copied from the reference |
| Execution/feed/response delays | Zero |
| Proportional transaction fee | 10 bp (0.10%) per spot/futures buy or sell |
| Half spread, slippage, custody expense | Zero, copied from the reference |
| Holding-horizon candidates | 1, 3, 7, 14, 30 days, bounded by expiry |
| Maximum incremental transfer | 25%; funding/liquidity constraints still apply |
| Cash reserve / uncertainty buffer | 1% / 5 bp |
| Rate freshness | Maximum 7 days for discretionary transfers |

All reference parameters are retained except execution frequency and the new
transaction-fee setting. The trade-tape source, paired policy, full-period bounds,
capital and explicit untuned paired defaults are added. Both the global and BTC
profile fee values are set to 10 bp to avoid an override silently retaining zero.
The inherited legacy gradual-allocation and maturity-score fields are kept in the
file but do not drive the new policy: it selects funded transfer sizes and common
horizons by expected net BTC wealth versus KEEP.

## Fee estimate and scope

Official schedules checked September 16, 2026:

- [Binance spot fees](https://www.binance.com/en/fee/trading): regular-user
  maker/taker rate 0.100%, without BNB/VIP discounts.
- [Deribit fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees):
  standard futures maker/taker rates 0.015%/0.035%; nonweekly delivery 0.025%,
  with weekly delivery exempt.

The current paired engine shares one proportional fee between spot and futures.
Ten basis points therefore matches the undiscounted spot estimate and is
conservative relative to the current 3.5 bp futures taker rate. It is not an exact
venue-specific or historically reconstructed account-tier fee schedule. No
maker rebates, discounts or native futures-combo fees are assumed. Fixed,
minimum and per-unit ticket charges remain zero. Existing opening BTC is an
endowment and is not charged a fictitious acquisition fee.

Spread/slippage remain uncalibrated at the reference's zero values. Expiry
delivery fees, actual cross-venue transfers, USDT/USD conversion and native
inverse collateral/settlement are not modeled. These limitations and the
conditional forecast are recorded in the strategy JSON itself.

## Deployment and run status

The latest preview deployment, commit
`d1fb73487e1f9aee42064d57799d55edd8445dd8`, passed the complete
[deployment workflow 35075897193](https://github.com/leviitzhak/keep_and_lease/actions/runs/35075897193),
including the funded paired GUI/workbook and replay-extension checks. No later
deployment was present when checked for this request.

The new preset passes the deployed engine's parameter validation against the
pinned preview catalog, including the decision ceiling, effective 10 bp fee and
preserved 100% participation. This configuration-only commit does not require a
replacement engine; preserve the checked preview with `[skip ci]`.

The full 90-day backtest was submitted through the authenticated application GUI
on September 16, 2026. Its durable server job was confirmed
running in the `trade_ordering` stage, with 8,192 futures records indexed at the
initial check. Completion and performance results have not yet been verified.

This is one untuned full-period evaluation. It does not establish profitable or
native executable performance, and the predeclared holdout is not used to tune
the parameters.

## Three-day validation preset

[`research-btc-paired-3day-validation-500ms-fee-10bp.json`](../strategies/research-btc-paired-3day-validation-500ms-fee-10bp.json)
uses the identical parameters with only `backtest_end` changed to
`2026-06-09T00:00:00`. It covers the first three days and schedules 518,400
valuation ticks; the terminal tick values the portfolio and cancels outstanding
orders, so there are 518,399 strategy decisions when initialization precedes the
first tick. This is an accounting and statistics check, not parameter tuning.

Use the full audit ZIP for independent verification. The current valuation CSV
does not include the paired ledger constituents. Headline returns and drawdown
use every valuation; chart distributions use sampled observations. Terminal BTC
wealth is marked rather than liquidated, and selected forecast horizons may
extend beyond this shorter validation period.

The standalone standard-library checker reads every compressed audit chunk,
verifies its checksums and row counts, reconstructs paired balance identities,
recomputes full-frequency statistics, and checks recorded fills and transfers:

```sh
python scripts/check-paired-replay-audit.py /path/to/full-audit.zip \
  --capital 100000 --fee-bps 10 --interval-seconds 0.5 \
  --output /path/to/validation-report.json
```

Its default participation, unmatched-quantity limit and economic hurdle match
this preset. The report distinguishes independently recomputed quantities from
recorded diagnostics and lists evidence limitations. Passing these checks does
not independently verify omitted exchange marks, forecast accuracy or actual
order-book liquidity.
