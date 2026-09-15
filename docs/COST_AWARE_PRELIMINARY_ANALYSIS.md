# Preliminary carry / exit-horizon analysis — 2026-09-15

This records a **valuation event study**, not a continuously funded execution
backtest. The full strategy specified in
[COST_AWARE_PAIRED_TRANSFER_PLAN.md](COST_AWARE_PAIRED_TRANSFER_PLAN.md) remains
pending. Existing results and the trading engine are unchanged.

## Inputs and sampling

Market period: [2026-06-06, 2026-09-04), pinned range manifest
`52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912`.
The 2,178,117 preserved ordinary-futures / prior-spot pairs include 1,028,877
with timestamp gap <=50 ms. Descriptive premium plots retain all these trades
and all 93 contracts, including observations immediately before expiry. The
1-day and 3-day remaining-maturity statistics use explicit +/-1-hour windows,
not interpolated fictional prices.

For each contract/day, take the first qualifying timestamp at/after 12:00 UTC
within 15 minutes, resolve equal timestamps by the final source record, then
require a positive entry lease. There are 657 candidates and 550 positive
entries in 88 contracts. Exits use the first qualifying observation at/after the
predeclared trigger, within 15 minutes and before expiry; the five-minute rule
is restricted to the final five minutes. Missing/censored cases are retained.
Expiry uses the retained official delivery price and the first RAW Binance
spot trade at/after 08:00 UTC, not the first spot referenced by a futures print.

## Accounting assumptions

Each example begins with one BTC of capital; the zero-fee benchmark keeps it.
Let S0 and F0 be entry spot/futures prices, fs/ff/fb the proportional spot,
futures and bond fees. Invest A=S0*(1-fs)/(1+ff+fb) in a synthetic same-expiry
zero-coupon bond and hold q=A/F0 BTC-equivalent linear futures. Thus entry
Treasury market value equals the entire initial futures notional, and entry
fees are funded from the same capital. Hold q and bond face constant.

The modeled Treasury price ratio is
G=(1+r0)^(D0/365)/(1+rh)^(Dh/365). Early exits mark the remaining maturity at
its then-observable yield; redemption has Dh=0 and no bond-sale commission.
Terminal cash is A*G+q*(Fh-F0), less applicable bond/futures exit fees, and is
converted back to BTC including a spot purchase fee. Report BTC return versus
the initial one BTC, not USD P&L or the integral of the quoted lease rate.

Main illustrative fees: 3 bps for each spot/futures trade, 1 bp for each actual
Treasury purchase/sale, and 2.5 bps for expiry delivery in place of a futures
exit commission. Zero fees, 0/3-bp Treasury costs, and zero delivery fee are
also retained. These are sensitivities, not an account-specific broker quote;
weekly delivery exemptions need contract-specific treatment in a full replay.

## Provisional results

All returns below are total holding-period basis points in BTC, NOT annualized.

| Exit rule | Examples | Median gross | Median net | Net-positive examples |
|---|---:|---:|---:|---:|
| After 1 day | 401 | 0.36 | -13.63 | 1.0% |
| After 10 days | 249 | 4.32 | -9.66 | 11.6% |
| 10 days remaining | 178 | 3.25 | -10.75 | 21.3% |
| 1 day remaining | 346 | 2.91 | -11.06 | 8.1% |
| 5 minutes remaining | 204 | 6.67 | -7.28 | 19.1% |
| Official expiry | 444 | 6.67 | -5.83 | 29.7% |

These 1,822 examples overlap and have different contract/horizon composition;
they are not independent trials or a strategy equity curve. A common cohort
of 69 entries in seven contracts is also retained: median gross/net BTC bps
are 0.20/-13.79 after one day, 2.29/-11.69 after ten days, 1.99/-11.96 at ten
days remaining, 4.62/-9.18 at one day remaining, 8.23/-5.77 near expiry and
9.77/-2.72 at delivery. Positive entry lease alone is not a sufficient cost
screen. No threshold or exit policy has been selected as optimal.

## Official expiry versus exact raw spot

Read-only market workflow `34997188619` completed successfully; artifact
`expiry-spot-research-34997188619` (ID `10407873968`) retains all 90 date rows,
source generations/checksums and the fixed catalog. Artifact SHA256:
`372bedfc3526ce935363d3330f9d2b85035f941b8280f455ad1abe7c97b47eb7`.

Across 90 observed contract expiries, delivery/first-post-08:00-spot minus one
has median -7.80 bps, median absolute difference 9.20 bps, and 95th percentile
absolute difference 25.84 bps. The spot timestamp lag has median 116 ms and
maximum 983 ms. The official delivery price versus a raw Binance spot
07:30-08:00 LOCF time-weighted average has median -8.70 bps. That comparison
still mixes index composition, venue/currency assumptions and sampling methods;
it does not identify one cause or prove a tradable arbitrage. Exact convergence
to this spot proxy must not be assumed. At expiry, annualized exit lease is
undefined; use delivery basis and BTC return instead.

## Critical limits and acceptance work

- Source Deribit inverse prices are used with a **linear USD payoff proxy** here,
  not the native inverse contract's BTC margin/payoff. This is not demonstrated
  tradability of a Treasury-collateralized position on Deribit.
- Treasury inputs are benchmark yields, not executable same-expiry securities or
  a bootstrapped zero curve. All six retained series end on 2026-07-14 and are
  carried forward afterward. DTB3/DTB6 discount-basis conventions also require
  explicit conversion in a corrected Treasury model. A before-cutoff subset is
  supplied; the main qualitative fee finding persists in that subset.
- The event study does NOT finance every interim variation-margin cash flow.
  A matched Treasury held unchanged plus terminal futures P&L is not proof of
  available cash throughout the path. Cash buffers, sales/repo/borrowing,
  haircuts, fees and external-capital benchmarking remain full-replay gates.
- Trade prints do not prove achievable bid/ask prices, size, latency or paired
  fills. Fixed/minimum commissions, custody, FX and spread/impact are omitted.
- Entry-rate and exit-rate correlations are descriptive and partly linked by
  the same basis-price identity; they are not validated predictors.

The local helper passed 14 accounting/TWAP tests. The premium explorer's actual
JavaScript passed six in-memory source checks including every daily median and
count against independent pandas calculations. Browser navigation was blocked
by the environment, so actual browser rendering of the updated HTML is not
certified. Static PNGs and complete calculation CSVs were produced separately.
