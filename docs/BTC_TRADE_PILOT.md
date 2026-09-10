# BTC raw-trade pilot

The bounded GUI/worker integration is now implemented separately in
[BTC_SUBSECOND_GUI.md](BTC_SUBSECOND_GUI.md), including millisecond clocks and
full audits. This document records the original one-second research runner.

The matched day now also has a lossless Parquet conversion and bounded replay
reader. See [BTC_TRADE_STORAGE.md](BTC_TRADE_STORAGE.md) for measurements,
reproduction, immutable GCS publication tooling and remaining cloud-access gates.

## Scope and reproduction

The research pilot downloads **2026-06-25 UTC**: Binance BTC/USDT individual
trades and dated Deribit BTC futures in the existing minute provenance manifest
that were alive that day. Perpetuals and options are excluded. It does not
activate new GUI data or change the minute baseline. Parameters are preserved in
`strategies/research-btc-long-gradual-1s-trade-pilot.json`.

```sh
python scripts/refresh-btc-trade-pilot.py
python scripts/check-btc-trade-pilot.py --output work/btc-trade-pilot/run-one-dollar
python scripts/check-btc-trade-pilot.py --capital 100000 --participation 0.1 --output work/btc-trade-pilot/run-capacity
python scripts/check-btc-trade-audit.py work/btc-trade-pilot/run-one-dollar
python scripts/check-btc-trade-audit.py work/btc-trade-pilot/run-capacity
python scripts/measure-btc-trade-storage.py --output work/btc-trade-pilot/storage.json
```

Raw data and full audits use the ignored `work/btc-trade-pilot/` cache. Source
URLs, hashes and compact reports are committed. Later cloud execution should
stream archives from durable object storage, avoiding Git, worker-image copies
and full-history Python object lists. No 90-day/full-history trade download has
been performed.

Binance provides SHA-256 checksums. The downloader checks contiguous spot trade
IDs and monotonic timestamps within the requested UTC day. Deribit raw JSON
records retain all source fields with locally computed hashes. Its history API
can return neighboring trades sharing a boundary millisecond. Pages are sorted,
filtered by sequence, and checked for gaps; the final sequence is checked
independently. Completed instruments can be reused; interrupted instruments are
downloaded again.

## Storage measured on 7 September 2026

These are **BTCUSDT raw spot trade ZIPs**, summed from archive catalog sizes.
Overlapping monthly and daily archives are not counted twice.

| Period | Measured compressed bytes | GiB |
| --- | ---: | ---: |
| 90 days: `[2026-06-06, 2026-09-04)` | 2,018,782,792 | 1.88 |
| August 2017 through 6 September 2026 | 79,267,016,630 | 73.82 |

The history comprises 108 monthly ZIPs through July 2026 and 37 daily ZIPs for
August and 1–6 September. January–July 2017 is not covered. Catalog existence
does not prove tick completeness throughout history; only the pilot data has
been inspected. See `validation/btc-trade-storage-2026-09-07.json`.

The pilot spot day has **5,683,275 trades**, 40,814,230 compressed bytes (38.92 MiB)
and 431,568,870 CSV bytes (411.58 MiB). Its CSV/ZIP factor is about 10.57. Applying
this *single-day* factor gives approximately **19.9 GiB / 780.6 GiB** of expanded
spot CSV for the 90-day/history windows. These are estimates, not measured
historical CSV totals. Streaming compressed files avoids expanded disk storage.
Futures, indexes, normalized copies, audits per run and backups are extra.
Order-book snapshots/updates are a different dataset and are not included.

The 12 dated futures have **56,333 trades**, 1,040,996 gzip bytes (0.99 MiB),
and 13,168,202 uncompressed JSONL bytes (12.56 MiB). Scaling this one day gives
about **0.087 GiB for 90 days**, or **3.43 GiB for 3,536 days** from 1 January 2017
to 7 September 2026. These are planning extrapolations, not measured histories:
the number of listed maturities, activity and API coverage vary through time.
The latter does not assert that every contract or trade exists back to 2017.

Combining measured spot ZIPs with this futures extrapolation gives roughly
**2.11 GB for 90 days / 82.95 GB for history** in decimal units. A provisional
budget of **5 GB / 100 GB** allows one compressed input copy plus a streaming
one-day workspace and some headroom. Persistent normalized copies, multiple
backtests' audits, indexes and backups require separate budgets; this is not a
100 GB budget for all copies and outputs. Keeping expanded text as well would
instead need approximately **25 GB / 1 TB**, with substantial uncertainty in the
single-day compression-factor extrapolation.

## Subsequent-trade VWAP versus order-book depth

For target quantity Q, consume subsequent eligible trade quantities, using only
the required fraction of the final print. The order average is
`sum(price * filled_quantity) / sum(filled_quantity)`. Book each partial fill at
its actual timestamp. The average is a later report, never a price assigned
retroactively to the original decision.

This is a **trade-volume participation model**, not observed market depth:

- Prints record transactions that already happened between other participants.
  They do not reveal resting quantity available to an additional order.
- A market order consumes asks for a buy or bids for a sell in the book available
  after arrival latency. Subsequent prints instead model execution over time,
  with uncertain access to that traded volume.
- The pilot uses buy-aggressor prints for buys and sell-aggressor prints for
  sells. Identified block/RFQ/combo prints cannot fill ordinary outright orders
  or create entry signals. They remain valuation observations, so executable
  end-of-day liquidation values are not established.
- Participation limits the fraction of each print consumed. 100% follows the
  proposed accumulation rule but is optimistic; 10% is an illustrative
  sensitivity, not a calibrated fill probability or queue model.
- Passive limit orders need opposite-aggressor flow, price limits and queue
  assumptions. This pilot does not simulate them.

## Clock and accounting

The saved full-long-gradual rule calls the existing `positions_for_day` every
second, using only causal spot/futures marks within the saved 60-second age
limit. Maturity and Treasury inputs remain causal. Missing fresh signals cancel
pending orders and preserve actual holdings. The first spot print initializes an
already-owned BTC endowment; its timestamp is recorded as warm-up. Every later
raw print remains a distinct event, including multiple prints within a second.

Each decision cancels/replaces unfilled remainders. Orders can fill only strictly
after signal time plus delay. Filled quantities persist across decisions. Cash,
collateral and traded volume constrain fills. The final boundary cancels pending
orders and marks holdings without fictitious liquidation. The audit records
orders, partial fills, cancellations, order VWAP, each second's NAV/holdings and
source mark IDs/timestamps.

The account uses long **regular USD futures**, 100% marked USD collateral,
continuous cash mark-to-market and fractional hypothetical lots. Cash earns the
latest observable short Treasury yield. A spot sale must fund a futures increase;
a futures reduction must release collateral before buying spot. Fees apply to
actual fills. Cash plus spot value reconciles to initial capital plus market P&L
and Treasury interest minus fees. This research convention is not CME's actual
margin/settlement system.

Deribit inverse volume is USD face amount: proxy BTC quantity is
`amount / trade_price`. This conversion does not change the quote provenance or
measure USDT/USD parity. Binance timestamps since 2025 have microsecond precision;
Deribit trades use milliseconds. Integer microseconds retain that precision,
which does not imply an observation every microsecond. Equal-timestamp
cross-venue events use deterministic symbol order. Exchange timestamps alone do
not establish synchronized receipt times or realistic subsecond latency.

## Full-day replay results

Both runs processed all **5,739,608** market events. There were **86,399**
one-second decisions and **86,400** valuation intervals: the first interval starts
at the first spot print, 106,918 microseconds after midnight. No second was
omitted after that explicit warm-up. At 12,526 decisions there was no sufficiently
fresh eligible curve; holdings persisted without invented fills.

| June 25, zero costs and zero added delay | $1, 100% participation | $100,000, 10% participation |
| --- | ---: | ---: |
| Strategy return | −0.105255% | −1.001634% |
| Direct holding return | −2.102230% | −2.102230% |
| Partial fill events, spot and futures | 47,454 | 939,158 |
| Cancelled unfilled remainders | 270,663 | 372,983 |
| Compressed full audit | 16.11 MiB | 36.52 MiB |
| Peak process RAM | 39.79 MiB | 39.79 MiB |
| Local runtime (concurrent runs) | 86.1 seconds | 98.4 seconds |
| Maximum NAV reconstruction error, USD | 5.11e−14 | 2.91e−8 |

These scenarios change both capital and participation; they do not isolate either
effect. Zero-cost results are not claims about realizable profit. At the end,
held July futures marks were 107.871–228.051 seconds old. Marked NAV is therefore
not a verified liquidation value. The small default account uses fractional
hypothetical lots. No inverse collateral, measured FX conversion, CME trade
history, queue model or endogenous market impact is introduced.

The complete manifests, code/input hashes and summaries are in
`validation/btc-trade-pilot/`. Six new accounting tests plus 13 focused existing
tests passed; all 26 rendered-HTML tests passed after `npm run prepare:assets`.
The independent streaming audit checker verifies chronology, delayed fills,
participation, no reused print capacity, order totals/VWAP and every second's
valuation references. This research-only addition was not a repeat of the full
90-day API/XLSX acceptance. The earlier roll-test/FastAPI/generated-copy caveats
and their resolution remain in `BTC_MINUTE_VALIDATION.md`.

## Original activation gates and remaining long-window work

- Review participation, cancel/replace, capital, fees and latency assumptions
  before introducing this model as a GUI option.
- GUI/worker integration now uses an explicit trade data source with bounded
  windows, audit chunks and CSV export. Changing only the candle interval still
  cannot turn minute data into second/subsecond data.
- Measure more matched days before extrapolating futures activity or scaling
  audits to years. A 90-day one-second clock has 7,776,000 decisions, about 60
  times the minute count.
- Acquire actual dated CME regular futures and, separately, historical bid/ask
  and book updates with documented coverage and synchronization. Complete book
  history since 2017 has not been established.
- Measure contemporaneous USDT/USD; a denser BTC/USDT tape does not establish
  parity or eliminate cross-venue basis.

Sources: [Binance schemas and checksums](https://github.com/binance/binance-public-data),
[archive catalog](https://data.binance.vision/?prefix=data/spot/monthly/trades/BTCUSDT/),
[Deribit trade API](https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_instrument).
