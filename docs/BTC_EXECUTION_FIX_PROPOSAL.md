# BTC minute execution and output: findings and proposed fix

Investigation date: 6 September 2026. Branch: `agent/btc-binance-minute-data`.
The preserved starting commit is `82e8d7e7c5c13c19912947ecf70ee620d6b6ca92`.
No execution assumptions or cloud resource limits have been changed by this
investigation. Publication remains gated; the design below is not implemented.

## Requested strategy and measured results

The test copies the **silver commodity profile** from `strategies/full silver
long gradual`, maps it to 100% BTC, uses **regular** futures, zero direct-holding
expense, no short book, and 60-second execution. Other allocation, maturity,
roll, Treasury and smoothing parameters are preserved. The original saved
strategy is unchanged. The harness now defaults to regular futures; the GUI's
general BTC default remains inverse unless the BTC profile explicitly overrides it.

The prices remain Deribit inverse-futures candle closes, used as a hypothetical
regular-futures price proxy. Binance BTC/USDT is still a USD proxy assuming parity.

| Full-window run | Strategy return | BTC holding return | Intervals |
| --- | ---: | ---: | ---: |
| Regular futures, original candle marks | +3,640.5349891% | +32.8013623% | 129,599 |
| Inverse futures, handoff result reproduced | +3,637.3487166% | +32.8013623% | 129,599 |
| Regular, execution delayed one observation | +954.7771125% | +32.7732876% | 129,598 |
| Regular, spot-linked stale-mark sensitivity | +409.3534748% | +32.8013623% | 129,599 |
| Regular, both sensitivities | +167.3679213% | +32.7732876% | 129,598 |

All runs have zero missing-return intervals. The delayed runs start at
`2026-06-06T00:02:00` instead of `00:01:00`, explaining their different benchmark.
`next_day` is a legacy parameter name: here it means the **next minute
observation**, not the next calendar day. The full regular GUI calculation
reproduces the streamed engine's strategy and benchmark returns exactly.

The stale-mark control carries the last observed `future/spot` ratio forward on
zero-volume candles and multiplies it by current observed spot. It seeds the
ratio from the first available candle if an earlier trade is unavailable.
It uses no future prices and does not edit data files. **It is a sensitivity
experiment with synthetic marks, not an executable strategy or a validated
replacement feed.** In particular, +167% is not a corrected performance claim.

## Established failure mechanism

The provider preserves `MarketObservation.observed=False` for zero-volume
candles, but `build_intraday_btc_market` drops that flag. It retains volume
without using it to restrict fills. Its one-minute age check measures the
timestamp of the freshly emitted candle, not the age of its underlying trade.
`run_backtest` then resizes positions at these closes unconditionally.

The full regular audit records:

- 255,326 of 406,459 contract-weight changes at zero-volume candles (62.8%).
- 248,287 of 394,215 non-negligible held-contract intervals starting with a
  zero-volume candle (63.0%).
- 272.646 percentage points of the 342.114-point **arithmetic sum** of futures
  return contributions arise in those zero-volume-start intervals. These are
  additive interval contributions, not compounded performance attribution.
- The maximum NAV-reconstruction difference is `6.17e-12`. This establishes
  numerical reconciliation; it does not establish that fills were possible.

Example: at **25 June 2026 14:33 UTC**, the strategy has almost 100% long exposure
to `BTC-17JUL26` at **$58,762.50**, while spot is **$59,630.54**. The future's
last positive-volume candle became available at **14:24**, nine minutes earlier.
Its apparent discount creates a **28.15% annualized lease signal**. At 14:34 its
close updates to **$60,222.50** and the strategy gains **2.4846% in one minute**.
Another large gain, on 11 June at 18:18, uses a `BTC-3JUL26` close last observed
30 minutes earlier. These facts are reconstructed directly from the gzip CSVs.

The strategy can respond to current spot while trading a lagging futures price,
then benefit when that futures print catches up. The counterfactual runs support
a substantial stale-price/timing contribution. They do **not** establish a unique
decomposition or eliminate all other explanations.

Both candle adapters make closes available one minute after the opening label;
no bar-open timestamp leak was found. Nevertheless, observing a completed close
and assuming a fill at that same historical price is an optimistic execution
assumption, even for positive-volume candles. Last-trade bid/ask bounce, sparse
liquidity, volume limits, fees, settlement marks, cross-venue basis, and USDT/USD
can still matter. The imported window contains no independent USDT/USD series.
The near-identical inverse/regular results rule out the inverse payoff formula
as the main explanation for this particular anomaly; the separate idle-BTC
collateral limitation remains.

## Proposed execution correction

1. Preserve observation quality through the engine and audit: actual observation
   time, available time, last genuine trade/quote time, bid, ask, sizes, source and
   whether a mark is synthetic. A new empty candle must not reset genuine quote age.
2. Separate **signals, orders, fills and valuation marks**. Keep the 60-second
   decision grid. Orders can change holdings only at eligible observations after
   the decision and configured latency. A zero-volume carried close cannot fill
   a new order. Retain actual contract quantities while orders are unfilled;
   do not pretend to roll or resize an unavailable instrument.
3. With quote data, buy at ask and sell at bid, subject to quote age and available
   size. With the current candles, expose an explicitly named research fill
   assumption using subsequent observed trades/bars; it cannot claim order-book
   execution accuracy. Do not use future bar volume to select an earlier fill.
4. Mark existing holdings causally and record mark quality separately from fills.
   Keep all minute accounting intervals. If a defensible valuation is unavailable,
   surface the valuation limitation; do not silently delete the interval, liquidate
   the position, or book a catch-up price as though it were a tradable bargain.
   Handle expiry with the actual settlement convention rather than inventing a fill.
5. Charge configurable transaction fees and spread/slippage on **actual quantity
   changes** and reconcile them into the appropriate book. The existing trade
   diagnostics compare portfolio weights; that alone omits quantity changes
   caused by NAV and price drift and is insufficient for a complete cost model.
6. Repeat the exact requested strategy with these controls, then compare genuine
   USD/FX-adjusted spot and matched-venue observations. Accept results based on
   causal fills and reconciliation, not on whether the return looks plausible.

Simply filtering zero-volume contracts out of `by_day` is not a sufficient fix:
the current target-allocation engine could drop held contracts or skip intervals.
Likewise, delaying by one minute alone leaves the +955% result above.

## Memory and output findings

Two safe changes are implemented locally:

- `run_backtest(..., row_sink=..., retain_fields=...)` emits every finalized
  complete audit row. Normal callers still receive the same full rows. An empty
  retention projection lets a consumer stream all rows to a durable sink.
- Alternative contract-selection calculations retain only their seven summary
  inputs, not their full holding ledgers. The selected comparison already reused
  the main run. An unused statistics pass and lingering comparison-row reference
  were removed; the requested alternative strategies are still calculated.

The full streamed regular audit uses **652.9 MiB** peak RSS including market
loading, with the same 129,599 returns. This is an engine diagnostic path, not
the deployed GUI path. The full GUI now measures **4,231.8 MiB** peak RSS and
**821.97 MiB** of JSON for regular futures. The previous 6,289.5 MiB / 817.31 MiB
measurement was for inverse futures; the slightly different JSON sizes reflect
different ledgers. Unit tests compare the old and projected comparison outputs
exactly. The new full GUI still exceeds 4,096 MiB and 256 MiB, and does not include
the Cloud Run worker's additional `json.dumps(...).encode(...)` buffer copies.

| Full regular response section | JSON MiB |
| --- | ---: |
| Spreadsheet rows and detailed holdings | 519.37 |
| Rate-change attribution points | 175.61 |
| Portfolio daily attribution | 62.06 |
| Portfolio series | 31.95 |
| All other output | 32.98 |

HTTP gzip/chunked transfer is already implemented. It does not solve full Python
object retention, the uncompressed result limit, or full browser JSON decoding.

## Proposed output correction and UX decision

Keep the existing 4 GiB worker and 256 MiB response limits initially. Implement
one continuous simulation with bounded row consumption, online comparison
statistics, and immutable compressed audit chunks, partitioned by date or a byte
ceiling. **Do not restart positions, Treasury accrual or cumulative NAV at a
chunk boundary, and do not coarsen execution frequency.**

The completed job should publish a small manifest only after every chunk has
been stored and verified. Record row counts, interval boundaries, parameter/data/
engine provenance, checksums and opening/closing NAV. Incomplete/cancelled jobs
must not expose a successful manifest. GCS uploads must be bounded; writing an
unbounded temporary file is not a memory solution on Cloud Run's memory-backed
filesystem.

Move the three largest sections above behind authenticated, owner-scoped date
range reads. The current response would then be approximately **65 MiB** before
any further representation changes. Existing sampled chart series and headline
statistics can remain immediately available. Detailed rate-change plots,
inspection and spreadsheet exports fetch the required chunks for the selected
range. Full audit download remains available without recalculation. All metrics,
distributions and accounting must use the complete interval population; any
display sampling must remain explicit and must not affect execution or exports.

**UX trade-off for review:** the first request for detailed plots or an export
needs a loading step/network access instead of having all 822 MiB preloaded.
Cache fetched chunks, display progress and actionable retry errors, and preserve
the selected range. A full-period spreadsheet may take longer to assemble than
a short-range export; do not silently shorten the range or drop ledger columns.
No cloud resource increase is proposed. This UX/output change has deliberately
not been implemented before that discussion.

Acceptance gates: identical interval/ledger/NAV results on fixed fixtures across
chunk boundaries; complete reassembly and checksum verification; correct access
checks for every chunk; cancellation/partial-upload tests; full-window worker and
browser measurements below current limits; then feature-branch deployment and
private GCP verification of the exact commit. No merge to master without approval.

## Regular-futures data plan

The relevant listed BTC product is **CME Bitcoin futures**, not COMEX silver.
[CME contract specifications](https://www.cmegroup.com/markets/cryptocurrencies/bitcoin/bitcoin/specs)
describe the 5-BTC USD-quoted contract. CME provides historical trades, top-of-book
and depth through [DataMine](https://www.cmegroup.com/datamine.html) and its
[historical data services](https://www.cmegroup.com/market-data/real-time-and-historical-data.html).
No entitled full-window download or free complete minute quote archive was
established in this session; no purchase was made.

Obtain individual BTC/MBT contract quotes/trades with timestamps, sizes, listing
and exact expiry/settlement metadata for the imported window. Confirm licenses,
venue sessions/maintenance periods and continuous coverage. Normalize through
the existing provider interface and preserve source hashes. Continuous rolled
prices or daily settlements alone cannot supply the maturity curve needed here.

Using inverse USD quotes as regular-futures prices is a reasonable **explicit
research proxy**, not an equality guaranteed across collateral, funding, venues
or settlement indices. [Deribit's inverse specifications](https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures)
distinguish USD quotes from BTC margin/settlement. For initial USD notional `N`,
linear P&L is `N*(F1/F0-1)`; inverse P&L converted at spot is
`N*(1/F0-1/F1)*S1`, equal to linear P&L times `S1/F1` for that interval. This
explains why the two tested payoff paths are close when spot and futures are close.
It does not justify identical executable quotes or Treasury-earning BTC collateral.
