# Changelog

## 2026-07-29

- Limited the active asset selector to silver, gold, Treasuries, and S&P 500.
- Added named strategy presets with automatic suggested names and loading.
- Added independent commodity-specific leg parameter profiles.
- Added inspected-day portfolio composition by commodity, leg, and contract.
- Added a simple-CSV market-data directory and documented current data gaps and
  expected capacity.
- Replaced the damaged gold ZIP with the complete 214-contract archive from its
  original source and materialized those contracts as CSV.
- Refreshed silver/SLV, gold/IAU, S&P 500/SPY, and SHY daily benchmark files
  through July 2026, with coverage and hashes recorded in a manifest.
# 2026-07-29 — common plots, parameter help, and scatter inspection

- Fixed common portfolio plots becoming blank after redraws and period filters.
- Added click/tap explanations beside every strategy parameter.
- Prevented invalid transient numeric values from being saved or submitted.
- Renamed Treasury maturity statistics to explicitly plot observed yield.
- Preserved scatter-specific nearest-point interaction on desktop and mobile.
- Added regression assertions and reproducible GUI specification requirements.
