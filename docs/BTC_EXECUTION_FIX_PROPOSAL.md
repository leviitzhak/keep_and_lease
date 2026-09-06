# BTC minute execution and output: findings and implemented fix

Investigation date: 6 September 2026. Branch: `agent/btc-binance-minute-data`.
The preserved starting commit is `82e8d7e7c5c13c19912947ecf70ee620d6b6ca92`.
The user approved the execution and on-demand export redesign. It is now
implemented locally; deployment verification is tracked in `CURRENT_WORK.md`.
Cloud resource limits are unchanged. The old assumptions remain reproducible
through an explicit `legacy_close` research preset.

## Implemented result and limits

The saved strategy is `strategies/full-btc-long-gradual-1m-regular.json`. It maps
**full silver long gradual** to 100% BTC, regular futures, no short book, no direct
holding expense and 60-second execution. The original silver preset is unchanged.
The legacy-close reproduction and one-basis-point fee sensitivity also have saved
presets. `scripts/check-btc-minute-backtest.py` reads the regular BTC preset.

| Full 90-day execution model | Strategy return | Direct holding | Intervals / missing |
| --- | ---: | ---: | ---: |
| Legacy regular close | +3,640.5349891% | +32.8013623% | 129,599 / 0 |
| Observed, zero costs | +43.7335811% | +32.8013623% | 129,599 / 0 |
| Observed, 1 bp fee per side | −39.8436771% | +32.8013623% | 129,599 / 0 |

The one-basis-point fee is illustrative, **not a measured fee schedule**. It is
charged to actual futures and direct BTC quantity changes. Spread/slippage remain
zero in that sensitivity. Frequent rebalancing makes costs economically decisive;
the zero-cost +43.73% is not a tradable-performance claim.

The complete deployed-engine simulation, including all four loaded markets and
the exact worker JSON encoder, measures **3,186.3 MiB peak RSS**, **63.54 MiB initial
JSON**, and **311.79 seconds** locally. It fits the existing 4,096 / 256 MiB limits.
This is a local worker-path measurement with a filesystem upload substitute, not
a measurement of live GCS latency or Cloud Run RSS. The full audit contains
129,599 BTC rows in 285 chunks (254.57 MiB compressed) and 129,599 portfolio rows
in 181 chunks (11.66 MiB compressed). Simulation state never restarts at a chunk
boundary. Reports are in `docs/validation/btc-minute/observed*.json`.

`ObservedExecution` holds actual BTC quantities and cash. Each minute produces a
new target when fresh eligible observations exist; only a later eligible bar or
quote can fill an order. A candle's entire interval must follow its order signal.
No-trade candles retain genuine mark age and can value held instruments but cannot
fill orders. A missing valuation/expiry settlement causes an explicit error;
there is no invented settlement or deleted interval. No held expiry was missing
in the full-window run. Treasury remains the existing causal synthetic Treasury
model; this is not a model of actual CME margin calls or broker collateral rules.

Observed mode supports regular long-only intraday BTC. `auto` selects it for
regular intraday data; inverse mode remains the explicitly limited legacy research
path. Daily commodity accounting is unchanged. `next_day` adds one observation of
latency in observed mode while retaining the initial direct-holding interval.
Quotes use ask for buys and bid for sells. Optional sizes must already be
normalized to BTC; raw Deribit USD contract-face amounts are not treated as BTC.
Quote feeds without normalized size expose `size_validated=false` in the audit.
Current candle fills remain a research assumption, with configurable fees,
half-spread, slippage, maximum quote age and volume participation. Initial NAV is
normalized to **USD 1**, with fractional units; participation therefore cannot be
interpreted as capacity for a real account or compliance with exchange lot sizes.

The zero-cost run has 196,775 total futures/spot fill records, 104,009 intervals
with pending orders, 97,047 intervals holding stale marks, and **zero zero-volume
futures fills**. The oldest held valuation mark is 8,760 seconds old. Stale
valuation remains an explicit limitation rather than an executable bargain.

Detailed audit rows include signal and fill times, prices, actual quantity
changes, pending orders, mark quality, costs, and complete accounting ledgers.
Immutable gzip JSONL chunks have SHA-256 checksums for both representations,
counts and NAV boundaries; GCS uses CRC32C-checked, create-only uploads. The
manifest is published after all chunks, and APIs expose it only for completed,
owner-matched jobs. Cancelled/failed jobs cannot expose a successful audit.

The GUI initially loads summaries and its existing sampled chart views; every
statistic, distribution and portfolio interval still uses the full population.
Detailed plots fetch the selected period on request, with progress/cancellation.
Attribution reads one necessary chunk. Complete raw audit downloads do not rerun
the strategy. A full-range XLSX is compressed one numbered ledger/check part at a
time, preserving all minutes, holding fields and source NAV in one workbook.
Its manifest records boundaries and hashes. Formula roll-forwards and normalized
underlying indices restart from each worksheet opening; **engine positions and
NAV never restart**. Timestamp cells now preserve minutes and signal times. The full workbook measures
427,540,700 bytes and 1,711.9 MiB peak RSS in a Node stress test using the actual
GUI export function (372.79 seconds); all 285 check worksheets report OK. This
is a local browser-code test, not a live Chromium memory measurement.
The detailed accounting template still supports exactly one commodity sleeve;
its existing multi-sleeve limitation is an explicit error.

## Requested strategy and measured results

The test copies the **silver commodity profile** from `strategies/full silver
long gradual`, maps it to 100% BTC, uses **regular** futures, zero direct-holding
expense, no short book, and 60-second execution. Other allocation, maturity,
roll, Treasury and smoothing parameters are preserved. The original saved
strategy is unchanged. The harness defaults to the saved observed regular-futures preset; the GUI's
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

## Established failure mechanism in the legacy model

The provider preserved `MarketObservation.observed=False` for zero-volume
candles, but the former `build_intraday_btc_market` dropped that flag. The former
one-minute age check measured the newly emitted candle timestamp rather than
the underlying trade age. Legacy execution resized at those closes unconditionally.

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

## Approved execution design

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

## Memory investigation before the approved redesign

The initial investigation implemented two safe changes:

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

## Approved output design and UX trade-off

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

**Approved UX trade-off:** the first request for detailed plots or an export
needs a loading step/network access instead of having all 822 MiB preloaded.
Bound detail reads, display progress and actionable retry errors, and preserve
the selected range. A full-period spreadsheet may take longer to assemble than
a short-range export; do not silently shorten the range or drop ledger columns.
No cloud resource increase is required by the measured worker path. The user
approved the loading step before implementation.

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

## Why the inverse quote is a usable research proxy

The user's maturity-payoff argument is correct under a shared terminal price.
For `q` BTC of linear futures entered at `F0`, USD payoff at maturity is
`q*(S_T-F0)`. An inverse contract with USD face `N=q*F0` pays
`N*(1/F0-1/S_T)` BTC. Converted at that same terminal `S_T`, it has exactly the
same USD payoff. This is a payoff equivalence, not physical exchange of principal:
[CME Bitcoin futures are cash-settled in USD](https://www.cmegroup.com/education/courses/introduction-to-bitcoin/what-are-bitcoin-futures),
and [Deribit inverse futures settle in BTC](https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures).

Before maturity, closing the inverse position at `F_t` locks a BTC amount.
Converting it immediately at spot `S_t` gives the comparable linear exit payoff
multiplied by `S_t/F_t`. Holding the BTC until maturity does not lock a fixed USD
amount. Daily variation margin, collateral yields, funding/discounting, different
settlement indices and cross-venue liquidity can therefore produce different
quotes and realized cash flows. The test accepts equal **quoted prices** as the
user-authorized research proxy while using regular USD P&L and Treasury accounting;
it does not carry over inverse BTC collateral or claim exact arbitrage equality.
