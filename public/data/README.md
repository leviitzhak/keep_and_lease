# Keep and Lease market data

Market data is organized by underlying and stored as plain CSV files.

| Folder | Available data | Current limitation |
| --- | --- | --- |
| `silver/` | Legacy fixing, 272 individual futures files, refreshed continuous-futures benchmark and SLV | Individual-contract archive ends in 2002; the refreshed continuous series cannot supply a maturity curve. |
| `gold/` | Legacy London fixing, 214 redownloaded individual futures files, refreshed continuous-futures benchmark and IAU | Individual-contract archive ends in 2002; the refreshed continuous series cannot supply a maturity curve. |
| `treasuries/` | 3m, 6m, 1y, 2y, 3y and 5y FRED yield series plus SHY | SHY begins in 2002 and is a fund benchmark, not a substitute for the Treasury curve. |
| `sp500/` | 83 individual futures files, S&P 500 cash index and SPY | Individual-contract archive covers 1982–2002; the current engine still uses the curve archive for lease calculations. |

The currently materialized CSV set is about 15 MiB. The browser backtest keeps
using the compressed individual-contract archives while its loaders are
migrated to the CSV directory. `manifest.json` records the refreshed symbols,
date coverage, observation counts, and SHA-256 hashes.

Run `python3 scripts/refresh-market-data.py` from the Site root to redownload
and verify the gold archive and refresh the benchmark/fund series. If the
authoritative download is temporarily unavailable, the script can salvage
complete local ZIP members. The refresh does not misrepresent a continuous
future as a set of individual maturities.
