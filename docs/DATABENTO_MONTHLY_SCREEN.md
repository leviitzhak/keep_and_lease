# Monthly gold, silver and Bitcoin rate screen

The owner requested October 2025–September 2026 monthly previews and selected
one liquid contract for each historical month. `scripts/databento_year.py` and
`.github/workflows/databento-year.yml` implement this fixed study. They do not
change the strategy, GUI or deployed application. Research code pushes use
`[skip ci]`; request-only pushes execute the private operator workflow.

## Contract selection

For each product, resolve Databento volume ranks 1–10 over the study window.
These rankings use the previous day's trading volume. At the earliest available
ranking date in each calendar month, choose the highest-ranked eligible outright.
Eligibility requires the labeled month to be at least the following month for
MBT, or two months later for 1OZ/SIC, because those metals terminate in the month
before the labeled contract. Keep this single contract throughout the month;
validate its actual expiry from vendor definitions. Record symbol, selection
date, rank, quote coverage, and minimum/median/maximum remaining maturity.

SIC launched February 9, 2026. Earlier months are explicitly unavailable, and
its first partial month begins when volume ranking becomes available. Missing
rankings or insufficient matched quotes are missing results, never zero rates.
This is a monthly cross-section of different maturities, not a constant-maturity
index or a rolling portfolio backtest. It differs from the earlier fixed
December 2026 / October 2026 contract comparison.

## Prices and reference reconstruction

Use actual one-minute futures and ETF bid/ask samples, matching UTC interval
endpoints during regular New York ETF hours. Require displayed quantity for one
futures contract and rounded-up ETF shares. Gold uses IAU, silver SLV and BTC
IBIT; ETF quotes are Nasdaq-specific, not an NBBO guarantee. Entry fees are zero;
exit costs, margin cash flows and settlement-benchmark basis are not modeled.

The issuer download examined did not return historical quantities per share.
The primary estimate therefore reconstructs daily quantities from the October
2, 2026 issuer snapshots using `q(t) = q(snapshot) * exp(fee * elapsed_years)`.
Snapshot ratios are IAU 14,903,267.68 oz / 792,900,000 shares; SLV
493,361,870.50 oz / 546,300,000 shares; IBIT 805,222.42840 BTC /
1,418,840,000 shares. Annual sponsor fees used are 0.25%, 0.50%, and 0.25%.
This is an explicit retrospective, fee-only approximation, not observed daily
holdings. A constant October 2 ratio is computed separately as a sensitivity;
its difference is not a statistical confidence interval. Historical ETF and
futures prices remain unchanged in both cases.

Cash accrues at the latest prior daily FRED DGS3MO observation, applied beginning
the next UTC day, with simple ACT/365 annualization to vendor expiry. The rate
is `cash_yield - (future_ask / normalized_ETF_bid - 1) / maturity_years`.
Monthly outputs include median, p95, maximum, positive-sample fraction, fractions
above 2%, gain to expiry, and coverage. These are sampled indications, not fills.

## Bounded cloud execution and persistence

Requests contain only schema version, unique request ID, `estimate` or `screen`,
and the recipient's RSA public key. Run on the existing
`agent/cloud-autonomous-access` identity. Three asset jobs execute independently;
each enforces a cumulative $1 estimated data ceiling, for a $3 combined ceiling.
Estimates are not invoices or remaining-credit queries. An estimate run performs
free symbology discovery and cost metadata only, with reads of existing private
caches. A screen checks the complete asset plan before paid requests. The fixed
study window, products, schemas and ceiling cannot be changed in a request.

Raw files and append-only acquisition checkpoints use
`gs://keep-and-lease-market-data/research/databento/monthly-2025-10-to-2026-09-v1/`.
Completed September SIC/MBT BBO files are reused when request parameters match.
A failed/uncertain paid request is retained and is not automatically repurchased.
Other months can finish and return partial evidence. Five-day definition windows
cover weekend/holiday starts without repeating full-month definition queries.
Only encrypted summaries return through public workflow artifacts. Private keys,
API keys, licensed records and numeric research output are not committed.

Validate with `python -m unittest discover -s tests -p 'test*databento*.py'`.
No application deployment or GUI verification is required.

## Completed study — October 5, 2026

[Estimate run 37325652697](https://github.com/leviitzhak/keep_and_lease/actions/runs/37325652697)
passed for all assets before acquisition.
[Screen run 37326417493](https://github.com/leviitzhak/keep_and_lease/actions/runs/37326417493)
completed successfully for request `20261005-year-screen-1`, returning all 32
available asset-months. The other four rows are SIC months before launch.
Summaries, samples and reference inputs persist under the private prefix above,
at `runs/20261005-year-screen-1/{asset}/{YYYY-MM}/`. Encrypted return artifacts
contain the monthly and daily statistics; their retention is shorter than the
durable GCS copy. The owner-facing workbook adds remaining maturity, gain to
expiry and a constant-ratio sensitivity beside the primary monthly table.
September SIC and MBT constant-ratio medians reproduce the previous screening
on their respective qualifying sample sets. Different commodities do not use
an intersection of timestamps in this study.

All 32 focused offline tests and all three cloud preflight jobs passed. The
research branch is `agent/databento-1oz-lease-preview`; bounded cloud execution
ran from `agent/cloud-autonomous-access` because that is the authorized identity
ref. These runs acquired BBO and definitions only. They did not acquire MBO,
simulate queue fills, modify the deployed strategy or deploy the application.

Sources: [Databento symbology](https://databento.com/docs/standards-and-conventions/symbology),
[CME SIC launch](https://www.cmegroup.com/notices/market-regulation/2026/02/msn02-04-26b.html),
[IAU](https://www.ishares.com/us/products/239561/ishares-gold-trust),
[SLV](https://www.ishares.com/us/products/239855/ishares-silver-trust-fund),
[IBIT](https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf),
[FRED DGS3MO](https://fred.stlouisfed.org/series/DGS3MO).
