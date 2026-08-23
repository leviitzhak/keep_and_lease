# Data layout and capacity

The canonical target layout is `public/data/<asset>/`, with simple CSV files:

- `silver/spot.csv`, `silver/fund.csv`, and `silver/futures/*.csv`
- `gold/spot.csv`, `gold/fund.csv`, and `gold/futures/*.csv`
- `treasuries/yields/*.csv` and optional `treasuries/fund.csv`
- `sp500/spot.csv`, `sp500/fund.csv`, and `sp500/futures/*.csv`

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

The individual-contract archives are historical rather than current: silver,
gold, and S&P 500 end in 2002. Continuous benchmark CSVs extend through July
2026, but they cannot replace a cross-maturity futures curve.
`public/data/manifest.json` is the machine-readable coverage and checksum
inventory.
