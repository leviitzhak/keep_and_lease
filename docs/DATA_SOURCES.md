# Data Sources and Derived Fields

## Required datasets

### Commodity futures

For every contract and date retain contract identifier, commodity, exchange, currency, multiplier, observation date, expiry or last-trade date, settlement/close price, and quality flags.

BTC dated futures are downloaded from Deribit's public history API. Preserve
Deribit's instrument name, creation and expiration timestamps, instrument type,
contract size, and settlement currency in `btc/coverage.json`. The corresponding
daily OHLCV files retain the exchange's unadjusted USD quote.

The bounded intraday materialization lives under
`btc/intraday/deribit_1m`. Each contract is a deterministic gzip CSV with
`timestamp,open,high,low,close,volume`, using UTC one-minute timestamps and the
unadjusted Deribit TradingView candle. Its manifest records the exclusive end
time, file hashes, contract metadata, row counts, and the number of zero-volume
filled rows. The refresh script requests no more than 5,000 candles at once and
can reuse already-complete contract files.

Strategy-facing intraday code must use `load_intraday_market`, not read exchange
files directly. The loader normalizes current candle files and future Tardis
quote files to `MarketObservation`. Changing the `spot` or `futures` entry in
`active_providers` within `btc/intraday/config.json` therefore changes the
source adapter without changing the strategy engine. Candle close is the
current reference and execution fallback; Tardis quote midpoint is the
reference, while bid and ask are retained for executable sell and buy prices.

### Spot or ETF

Retain adjusted and unadjusted prices, distributions where relevant, expense ratio history, currency, and trading calendar.

The default intraday BTC spot feed is Binance BTC/USDT one-minute trade OHLC,
downloaded from the [official public archive](https://github.com/binance/binance-public-data).
The bounded window matches the futures: `[2026-06-06, 2026-09-04)` UTC.
The downloader checks each archive's published SHA-256, normalizes both Binance
millisecond and microsecond timestamps, and rejects missing/duplicate minutes,
invalid OHLC values and incomplete tails before replacing data. It uses monthly
ZIPs where published and daily ZIPs otherwise. No missing minutes are invented.

Run `python scripts/refresh-binance-intraday-data.py --activate` to download the
window in the Deribit manifest and select `binance_1m` for the spot role. Explicit
`--start` and exclusive `--end` dates are supported. Raw ZIPs are transient;
deterministic `binance_1m/spot.csv.gz` plus its provenance manifest are canonical.
The packaged file contains 129,600 bars (90 complete UTC days), about 2.67 MiB
compressed. `python scripts/check-btc-minute-backtest.py` runs the saved
full-silver-long parameters mapped to a 100% BTC portfolio and reports the
available window, performance, runtime, memory and serialized-result size.
The data rows retain `BTC-USDT`; the provider explicitly maps to the engine's
`BTC-USD` research proxy and retains the source symbol, quote currency and assumed
conversion rate on observations. No bid/ask quotes are synthesized.

**Currency caveat:** no historical FX correction is applied: USDT/USD=1 is an
assumption. USD futures versus unconverted USDT spot mix stablecoin and
cross-venue basis into the implied lease rate and strategy returns. See
[USDT/USD risk and historical deviations](USDT_USD_BASIS.md). These results are
not a calibrated executable arbitrage backtest.

The retained optional Kraken spot feed is its best bid and ask delivered in Tardis'
normalized quote schema. The checked-in free samples cover the complete UTC
days 2026-07-01, 2026-08-01, and 2026-09-01. They contain 2,773,814 valid quote
updates aggregated to 4,320 one-minute midpoint OHLC bars with no missing
minutes. Kraken's `XBT/USD` identifier before 2026-07-10 and `BTC/USD` identifier
afterward are both normalized to `BTC-USD`. The per-file source hashes and the
aggregation convention live in `btc/intraday/kraken_1m/manifest.json`.

The legacy daily BTC path retains Yahoo BTC-USD composite candles for
compatibility when no intraday configuration is present. These spot series are
independent of Deribit's perpetual future.

The legacy loader preserves ISO timestamps when present instead of truncating
them to dates. Backtests infer the finest common BTC spot/futures spacing from
loaded observations. The packaged Kraken samples exercise the complete
one-minute strategy path, but their three isolated days are a plumbing and
accounting validation set, not a continuous performance-research history. The
Kraken-configured backtest therefore selects the latest complete sample day instead
of inventing a holding return across the month-long gaps.

### Treasury/cash curve

Retain instrument or tenor, observation date, maturity, quoted yield/rate, compounding convention, and price or total-return data when available.

## Derived quantities

### Time to maturity

Use a documented year-fraction convention:

```text
maturity_years = year_fraction(observation_date, contract_expiry)
```

### Annualized futures premium

The exact formula depends on price and compounding conventions. Store both the raw price ratio and the annualized result so calculations can be audited.

### Implied lease rate

Document the identity used by the implementation and all assumptions concerning interest rates, storage, convenience yield, ETF expenses, and compounding. Do not label a residual as a pure lease rate unless those components are treated consistently.

### Treasury rate

For Treasury scatter plots, use a consistently annualized rate with the quoted compounding convention converted where necessary.

## Alignment rules

- Never join observations using future data.
- Preserve original source timestamps.
- Record whether a value is observed, carried forward, interpolated across
  maturity tenors, or derived.
- Carry Treasury yields forward through time; never interpolate between daily
  marks or use the next mark before its observable timestamp.
- Use the next valid trading date for delayed execution.
- Avoid mixing settlement and intraday prices without an explicit convention.
- Deribit emits filled TradingView candle samples for minutes without trades.
  Retain them for as-of valuation but mark zero-volume rows as not newly
  observed; do not mistake them for executable quotes.
- A Deribit one-minute candle timestamp labels the minute opening at `t`. Its
  close becomes available to the strategy at `t + 1 minute`. Tardis tick quotes
  become available at their source timestamp. The normalized observation keeps
  both the original timestamp and the first usable time.

## Quality controls

Flag duplicate contracts, non-positive prices, impossible maturities, abrupt identifier changes, stale prices, missing rate inputs, and large unexplained jumps. The GUI should expose excluded observations and exclusion reasons.

## Reproducibility

Each backtest result should record data-source identifiers, extraction date, input-file hashes or version references, date range, and derivation-code version.
