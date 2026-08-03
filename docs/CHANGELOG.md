# Changelog

## 1.1

- Display the branch version and exact deployed commit in the GUI header.
- Generate `build-info.json` during deployment so preview freshness is directly verifiable.

## 2026-08-02 — generalized multi-commodity production pipeline

- Fast-forwarded `agent/multi-commodity-preview` to the architectural work in `master`.
- Made `maturity_scoring.py` the single long/short scoring formula; retained helper names only as compatibility adapters.
- Added rate-scale/clipping controls and inspected-day long/short score audits.
- Added global defaults with nested or flat per-commodity overrides.
- Added an independent Treasury/cash allocation, including Treasury-only portfolios.
- Added contract-level observed-versus-frozen-curve attribution and commodity/Treasury maturity scatters.
- Added schema-versioned current and named parameter sets with load, export, import, and reset.
- Made unavailable or corrupt commodity archives non-fatal unless selected.
- Kept the pure maturity multiplier explicitly deferred.

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
