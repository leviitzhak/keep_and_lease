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

Strategy-facing intraday code must use `load_intraday_market`, not read Deribit
files directly. The loader normalizes current candle files and future Tardis
quote files to `MarketObservation`. Changing `active_provider` in
`btc/intraday/config.json` therefore changes the source adapter without changing
the strategy engine. Candle close is the current reference and execution
fallback; Tardis quote midpoint is the reference, while bid and ask are retained
for executable sell and buy prices.

### Spot or ETF

Retain adjusted and unadjusted prices, distributions where relevant, expense ratio history, currency, and trading calendar.

BTC spot uses Yahoo BTC-USD composite daily candles. It is deliberately
independent of Deribit's perpetual future. The coverage report records the
daily convention so futures/spot alignment remains auditable.

The legacy loader preserves ISO timestamps when present instead of truncating
them to dates. Backtests infer the finest common BTC spot/futures spacing from
loaded observations. The packaged Yahoo spot series remains daily, so a full
intraday premium backtest still needs a point-in-time one-minute spot/index feed
alongside the packaged one-minute Deribit futures.

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
