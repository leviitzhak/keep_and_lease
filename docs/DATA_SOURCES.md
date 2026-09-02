# Data Sources and Derived Fields

## Required datasets

### Commodity futures

For every contract and date retain contract identifier, commodity, exchange, currency, multiplier, observation date, expiry or last-trade date, settlement/close price, and quality flags.

BTC dated futures are downloaded from Deribit's public history API. Preserve
Deribit's instrument name, creation and expiration timestamps, instrument type,
contract size, and settlement currency in `btc/coverage.json`. The corresponding
daily OHLCV files retain the exchange's unadjusted USD quote.

### Spot or ETF

Retain adjusted and unadjusted prices, distributions where relevant, expense ratio history, currency, and trading calendar.

BTC spot uses Yahoo BTC-USD composite daily candles. It is deliberately
independent of Deribit's perpetual future. The coverage report records the
daily convention so futures/spot alignment remains auditable.

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
- Record whether a value is observed, interpolated, or derived.
- Use the next valid trading date for delayed execution.
- Avoid mixing settlement and intraday prices without an explicit convention.

## Quality controls

Flag duplicate contracts, non-positive prices, impossible maturities, abrupt identifier changes, stale prices, missing rate inputs, and large unexplained jumps. The GUI should expose excluded observations and exclusion reasons.

## Reproducibility

Each backtest result should record data-source identifiers, extraction date, input-file hashes or version references, date range, and derivation-code version.
