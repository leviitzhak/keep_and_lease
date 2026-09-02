# Data layout and capacity

The canonical target layout is `public/data/<asset>/`, with simple CSV files:

- `silver/spot.csv`, `silver/fund.csv`, and `silver/futures/*.csv`
- `gold/spot.csv`, `gold/fund.csv`, and `gold/futures/*.csv`
- `treasuries/yields/*.csv` and optional `treasuries/fund.csv`
- `sp500/spot.csv`, `sp500/fund.csv`, and `sp500/futures/*.csv`
- `btc/spot.csv`, `btc/futures/*.csv`, and `btc/coverage.json`

The checked-in materialized data currently occupies about 15 MiB. A complete
daily research set for the four assets should normally remain below roughly
100–250 MiB as plain CSV, depending mainly on the number of individual futures
contracts and whether ETF OHLCV, distributions, and both price and total-return
indices are retained. Compression can be used for transfer, but not as the
canonical on-disk schema.

Server images compile these CSVs at image-build time into the immutable local
`data/market.sqlite3` cache. The strategy reads that cache once per process and
retains the decoded snapshot in memory for subsequent runs. SQLite is an image
local startup optimization, not a second authoritative dataset; deleting it
and rebuilding the image deterministically recreates it from the CSVs. This is
faster and cheaper than issuing one Firestore or network-database query per
quote, while preserving plain CSVs for audit and data refreshes.

The damaged legacy root-level `gc.zip` is no longer copied into server images.
ZIP readers remain only as compatibility fallbacks for assets that have not
yet been migrated to the canonical layout.

Available today:

- Silver: legacy spot/fixing, 272 individual futures, refreshed continuous
  benchmark, and SLV.
- Gold: legacy spot/fixing, 214 individual futures redownloaded from the
  original TurtleTrader source, refreshed continuous benchmark, and IAU.
- Treasuries: six daily yield tenors and SHY.
- S&P 500: 83 individual futures, the cash index, and SPY.
- BTC: 493 Deribit dated contracts were enumerated on 2 September 2026; 462
  contain archived daily candles. Yahoo BTC-USD supplies a spot composite.
  The audited overlap is continuous from 6 January 2017, while at least two
  simultaneously observed contracts are available from 9 February 2017.
  `btc/coverage.json` records exact coverage and contract metadata and can be
  regenerated with `scripts/refresh-btc-market-data.py`.

The individual-contract archives are historical rather than current: silver,
gold, and S&P 500 end in 2002. Continuous benchmark CSVs extend through July
2026, but they cannot replace a cross-maturity futures curve.

Historical Deribit BTC contracts are inverse USD futures. For signed USD
notional `N`, daily prices `F0,F1`, ending BTC spot `S1`, and conversion-fee
rate `c`, inverse mode adds `N(1/F0−1/F1)` BTC to a pending native balance.
Regular mode retains the linear USD payoff. In inverse mode the signed BTC
payoffs net until the absolute balance reaches `inverse_min_conversion_btc`.
The complete balance `B` is then recognized as `S1·B − c·S1·|B|` USD and reset
to zero. A remaining balance is force-converted at the backtest end. Pending BTC
and its current spot value remain diagnostic fields but are not included in USD
strategy NAV before conversion. The fee is distinct from bid/ask and
position-change costs. BTC also requires an explicit seven-day calendar policy
and Treasury accrual across weekends before GUI activation.
`public/data/manifest.json` is the machine-readable coverage and checksum
inventory.
