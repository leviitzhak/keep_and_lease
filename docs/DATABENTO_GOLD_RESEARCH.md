# September 2026 gold, silver and Bitcoin lease-rate research

This owner-run CLI first measures sampled, immediately marketable bid/ask lease
indications, then optionally acquires MBO for a later time-to-fill study. It does
not place orders or change the deployed strategy. The default contract is
December 2026 `1OZZ6`. Presets also select December 2026 `SICZ6` and October
2026 `MBTV6`; none uses a rolling continuous series. The month is
`[2026-09-01T00:00:00Z, 2026-10-01T00:00:00Z)`.

## Autonomous cloud execution

The owner has granted access to the stored Databento key. The bounded
[cloud runner](DATABENTO_CLOUD_RUNNER.md) supports the SIC/MBT September
cost check and screen through the existing operator branch, with a combined
$1 cumulative estimate ceiling, private GCS caches and encrypted result return.
Secret access and metadata retrieval were verified by run 37312663540.
ETF conversion inputs in this cloud screen are explicitly snapshot scenarios;
the owner-run CLI below also accepts causal dated reference files.

## SIC and MBT: screen before choosing an MBO candidate

| `--preset` | Futures contract | Units per contract | ETF reference | Reference conversion |
| --- | --- | ---: | --- | --- |
| `gold` (default) | `1OZZ6`, December 2026 | 1 troy oz | IAU | Gold oz/share |
| `sic` | `SICZ6`, December 2026 | 100 troy oz | SLV | Silver oz/share |
| `mbt` | `MBTV6`, October 2026 | 0.1 BTC | IBIT | BTC/share |

IBIT is the user's selected Bitcoin reference. All futures use `GLBX.MDP3`;
all three ETF presets use Nasdaq `XNAS.ITCH`, a single venue, including SLV
which is primarily listed elsewhere. Availability and depth on this venue must
be checked using the account. The CLI does not silently substitute an ETF/feed.
Displayed ETF sizes are shares and futures sizes are contracts.

Pull the feature branch, activate the environment described below, then estimate
the September BBO/definition downloads (metadata only):

```bash
git switch agent/databento-1oz-lease-preview
git pull --ff-only origin agent/databento-1oz-lease-preview
source .venv-databento/bin/activate
python -m pip install -r requirements-databento.txt
python scripts/databento_gold.py estimate --preset sic
python scripts/databento_gold.py estimate --preset mbt
```

New presets are in `strategies/research-sic-dec26-september.json` and
`strategies/research-mbt-oct26-september.json`. They default to **zero fees**;
enter actual futures and ETF commissions/minimums there before an economic net
comparison, or copy a preset and select it with `--config`. A changed config
requires a fresh `--output`. Existing gold config, raw filenames, paid download
state and legacy IAU sample columns remain compatible.

For historical estimates, provide one dated reference CSV per ETF:

```text
available_at,units_per_share,usd_rate,source
```

Use silver troy ounces per SLV share and BTC per IBIT share. The legacy
`ounces_per_share` column is also accepted for metals, but rejected for MBT.
Derive content from same-date issuer holdings divided by shares outstanding, or
an issuer entitlement with the basket size verified. IBIT's holdings quantity
represents BTC; do not use ETF NAV as if it were units per share. Observe the
availability/staleness rules below. Use the same dated cash benchmark for all
contracts to make the cross-contract comparison meaningful.

```bash
python scripts/databento_gold.py preview --preset sic \
  --reference-csv /path/to/slv-and-cash-reference.csv --max-cost-usd 10
python scripts/databento_gold.py preview --preset mbt \
  --reference-csv /path/to/ibit-and-cash-reference.csv --max-cost-usd 10
```

If historical holdings inputs are not ready, a **constant scenario** can be run
immediately. Enter your chosen assumptions at the prompts; these are not verified
historical inputs. Each cost cap below is an example per output directory; two
caps of $10 authorize up to $20 in combined estimates, not a shared $10 budget.

```bash
read -rp 'SLV silver ounces per share (scenario): ' SLV_OZ_PER_SHARE
read -rp 'IBIT BTC per share (scenario): ' IBIT_BTC_PER_SHARE
read -rp 'Annual cash rate in percent, e.g. 4 means 4% (scenario): ' CASH_RATE_PCT
python scripts/databento_gold.py preview --preset sic \
  --units-per-share "$SLV_OZ_PER_SHARE" --cash-rate-pct "$CASH_RATE_PCT" --max-cost-usd 10
python scripts/databento_gold.py preview --preset mbt \
  --units-per-share "$IBIT_BTC_PER_SHARE" --cash-rate-pct "$CASH_RATE_PCT" --max-cost-usd 10
```

Changing reference inputs reuses cached raw quotes. Output directories are
`outputs/databento-sic-sep2026` and `outputs/databento-mbt-sep2026`. Each contains
the same daily/overall quantiles, positive-sample fractions and coverage counts
as gold. Compare locally, without an API key or another download:

```bash
python scripts/databento_gold.py compare --compare-outputs \
  outputs/databento-sic-sep2026 outputs/databento-mbt-sep2026
# Append outputs/databento-1oz-sep2026 to include a completed gold screen.
```

This prints a compact table and writes `lease-comparison.json` and
`lease-comparison.csv` under `outputs/databento-comparison-sep2026`. The table
uses **only timestamps where every selected contract has a size-qualified
sample**, with each contract's own valid-sample statistics retained in JSON.
It rejects mismatched windows/schemas, discloses reference modes and configured
fees, and flags unequal cash assumptions on shared timestamps. Do not rank
contracts under incompatible input assumptions. A small overlap may itself
indicate a poor candidate for a paired execution test.

Candidate metrics include median/p05/p95 annualized after-entry-cost rate,
fraction of common samples above zero, and median gain to expiration in basis
points. The last metric is `annual_rate_pct * maturity_years * 100`: it exposes
the smaller economic cushion behind a large annualized rate for short-dated
MBT. Positive rates mean the cash-funded futures replacement looks favorable
under these inputs; they do not establish executable profit. Favor repeated
positive indications with adequate coverage and cost cushion before acquiring
MBO for a fill study. No contract has yet been confirmed positive by this patch.

The generic calculation uses `U = contracts * units_per_contract`, ETF shares
`ceil(U / units_per_share)`, and prices in USD per underlying unit:

```text
S_bid = ETF_bid / units_per_share
entry_cost_per_unit = (contracts * futures_fee + max(ETF_shares * ETF_fee, ETF_min_fee)) / U
long_lease_after_entry_cost = usd_rate - (future_ask / S_bid - 1) / T - entry_cost_per_unit / S_bid / T
```

The futures multiplier is never applied to the quoted price ratio. The reported
rate covers the matched underlying quantity; excess whole-share exposure is
reported separately. `forward_premium_pct` and `annualized_forward_premium_pct`
are included in samples for auditing the calculation.

Definitions supply the annualization endpoint and must agree with the selected
contract month. SIC ends trading in the month before its named contract month;
MBT October has an October expiry. The CLI labels its horizon
`definition_expiration`: this is a screening convention, not a model of final
cash payment timing. SIC settles against COMEX silver futures; MBT settles
against the CME CF BRR. Neither guarantees convergence to SLV/IBIT quotes, and
IBIT's NAV benchmark is the BRR New York variant. Confirm the applicable
settlement timetable and exit basis before treating an indication as a locked
holding-to-maturity return. Only the ETF's regular weekday session is screened,
even when the underlying futures can trade outside those hours.

Once a candidate is selected, use the same preset for optional MBO and GCS:

```bash
python scripts/databento_gold.py estimate --preset sic --stage mbo
python scripts/databento_gold.py submit-mbo --preset sic --max-cost-usd 100
python scripts/databento_gold.py download-mbo --preset sic
python scripts/databento_gold.py upload --preset sic
```

Replace `sic` with `mbt` to acquire MBT/IBIT. Defaults upload under
`gs://keep-and-lease-market-data/silver/databento/SICZ6/2026-09/` and
`gs://keep-and-lease-market-data/btc/databento/MBTV6/2026-09/` respectively.

## Run in Google Cloud Shell or a VM

```bash
git clone https://github.com/leviitzhak/keep_and_lease.git
cd keep_and_lease
git switch agent/databento-1oz-lease-preview
python3 -m venv .venv-databento
source .venv-databento/bin/activate
python -m pip install -r requirements-databento.txt
python scripts/databento_gold.py estimate
```

An interactive terminal prompts for the key without echoing it. Alternatively,
set `DATABENTO_API_KEY`; it is read by the CLI and is never written to an output
file. Noninteractive use requires that environment variable. For example:

```bash
read -rsp 'Databento API key: ' DATABENTO_API_KEY
export DATABENTO_API_KEY
python scripts/databento_gold.py estimate --stage mbo
```

The estimate commands request metadata only. They do not download market records
or submit batch jobs. The returned symbols/costs must be checked using the actual
account; this implementation has not been validated against a funded API key.
`GLBX.MDP3` covers the future; the default IAU feed is `XNAS.ITCH` (Nasdaq venue
quotes, not consolidated NBBO). Dataset access and record availability depend
on the account. No fallback silently replaces an unavailable dataset.

The default gold preset is `strategies/research-1oz-dec26-september.json`. It defaults to one
futures contract, one-minute BBO and zero entry fees. Set your actual futures
per-contract fee, ETF per-share fee and ETF minimum fee before computing a net
entry indication. Changing config requires a fresh output directory.

## Preview before MBO

MBO is not necessary to examine the range of marketable entry rates. The preview
downloads BBO on interval plus instrument definitions for both legs. Definitions
supply the actual future expiration timestamp: December is the delivery month,
not a justification for using December 31 as maturity. The definition is checked
against December 2026 and against the observation period.

IAU is quoted per share. Accurate conversion needs gold ounces per share and a
cash-rate series available at each observation. Supply a CSV with:

```text
available_at,ounces_per_share,usd_rate,source
```

`available_at` is a timezone-qualified timestamp; `usd_rate` is a decimal annual
rate, not percent. `source` identifies both underlying sources/conventions. Each
row describes the complete state known then. Include a row available by September
1 and update whenever either input changes. The join only looks backward and
rejects observations older than seven days by default. For date-only closing
inputs use next-day 00:00 UTC at the earliest, consistent with the engine's
conservative convention; use later publication times when applicable. Do not
assign retrospective data to times when it was not yet available.

IAU ounces/share should come from same-date issuer ounces and shares or the
issuer's basket entitlement, with its basket size documented. Current holdings
must not be silently used for all historical dates. The issuer's general Data
Download export inspected on October 5 contains historical NAV and shares, but
not historical ounces, so this CLI intentionally does not derive gold content
from NAV alone. The project's legacy `gold/spot.csv` refresh uses `GC=F`; it is
not an executable gold spot quote and is not used here.

```bash
python scripts/databento_gold.py preview \
  --reference-csv /path/to/iau-and-cash-reference.csv \
  --max-cost-usd 10
```

For a preliminary sensitivity study, explicitly supply a constant gold-content
and cash-rate scenario instead. **The following values are examples, not verified
September inputs or a claim about observed lease rates.**

```bash
python scripts/databento_gold.py preview \
  --iau-oz-per-share 0.0188 --cash-rate-pct 4.0 \
  --max-cost-usd 10
```

The result records `constant_scenario`. Re-running with better reference inputs
reuses cached market data; it does not download it again. `--max-cost-usd` bounds
cumulative estimated acquisitions in this output directory (including MBO later),
not each call separately. It does not query the remaining signup allowance or
guarantee invoice cost. Set it to no more than the remaining allowance you intend
to spend. Other jobs/accounts and Google storage costs are outside that ceiling.

## Formula and interpretation

For the long transfer (sell IAU, buy a Treasury-funded 1OZ future), define
`S_bid = IAU_bid / ounces_per_share` and `T = (expiry - quote_time) / (365 days)`.
The preview uses the existing engine's simple ACT/365 convention:

```text
long_lease_gross = usd_rate - (future_ask / S_bid - 1) / T
long_lease_after_entry_cost = long_lease_gross - entry_cost_per_oz / S_bid / T
reverse_lease_boundary = usd_rate - (future_bid / S_ask - 1) / T
```

Positive long rates favor the funded future over current gold-equivalent IAU at
those prices under the stated cash convention. This is an implied rate against
IAU and includes its premium/discount. It is not a pure bullion lending rate.
The reverse boundary is not a net short-strategy return. Reverse size availability
is reported separately; the sample set is selected for the long transfer.

The requested future quantity is an integer; ETF shares are rounded up and both
displayed sizes must cover the long transfer. The small residual gold exposure is
reported. Entry costs are configurable. Exit fees, slippage, future IAU expense
advantage, funding/margin and variation cash-flow effects, taxes and convergence
risk are not included. The cash benchmark is not a locked financing return.

BBO records are aligned by equal `ts_recv` interval endpoints, not `ts_event`
(which is the last trade time in this schema). No missing quotes are filled by
the CLI. Samples are restricted to IAU's 09:30–16:00 New York regular session,
with invalid/crossed/empty books rejected. Provider BBO fields can be carried
within the feed; the age of the last book change is not recoverable from sampled
BBO. Therefore these are **sampled quote indications, not proven simultaneous
executions**. Use MBO/event-level data with observation/decision/order delays for
time-to-fill and actual fillability analysis.

Outputs under ignored `outputs/databento-1oz-sep2026/`:

- `preview-estimate.json`: exact request parameters and estimated costs.
- `raw/*.dbn.zst`: original BBO and definitions, with hashes in `state.json`.
- `references-used.csv`: inputs used for cash/IAU conversion.
- `lease-samples.csv.gz`: aligned prices, sizes, rates, fees and residual exposure.
- `lease-daily.csv`, `lease-summary.json`: min, p05, median, p95, max and fraction
  of valid samples above 0% and 2%, plus coverage/exclusion counts and limitations.

Quantiles and fractions are sample-weighted, not time-weighted. No observations
means no claim about that interval. Subsecond opportunities can be missed by
one-minute sampling; switch the preset to `bbo-1s` and re-estimate in a fresh
output directory if finer screening is needed.

## MBO acquisition and GCS

```bash
python scripts/databento_gold.py estimate --stage mbo
python scripts/databento_gold.py submit-mbo --max-cost-usd 100
# Later, once Databento has prepared the jobs:
python scripts/databento_gold.py download-mbo
python scripts/databento_gold.py upload
```

The numeric caps are user-adjustable examples, not observed prices. Both legs'
MBO and definitions are included so a paired fill study can model both markets.
Requests use DBN + Zstandard with daily splitting. Job IDs are persisted as soon
as each submission returns. Re-running submission skips recorded jobs. Downloads
can be resumed without resubmitting and skip locally verified files. Pending jobs
return exit code 2; there is no background polling loop. An uncertain submission
or interrupted charged streaming request stops for reconciliation instead of
automatically risking another purchase. If the submission response was lost,
retrieve the matching job ID from Databento's Download center and reconcile the
saved state before continuing. Expired batches must be reviewed manually.

`upload` creates a checksum manifest and uses the current gcloud identity to copy
the output to the private existing bucket:

```text
gs://keep-and-lease-market-data/gold/databento/1OZZ6/2026-09/
```

Use `--gcs-prefix gs://...` for another destination. Run with an identity authorized
to create/update objects there. No IAM changes are made. Cloud Shell is suitable
for preview and short transfers; use a VM with enough disk for large MBO batches.
The uploader retains the local copy and does not delete destination objects.
Keep licensed market records and reference exports out of the public repository.

## Validation and remaining research

Run `python -m unittest discover -s tests -p 'test_databento_gold.py'`.
Tests cover causal reference use, interval alignment, bid/ask direction, actual
expiry, entry costs, 100-ounce/0.1-BTC sizing and fee normalization, whole-share
and depth checks, common-timestamp comparisons, cache compatibility, invalid
quotes and purchase resume.
The operator's October 5 execution verified secret access, acquired September
price data and persisted licensed inputs and screening outputs in private GCS.
See the [cloud runbook](DATABENTO_CLOUD_RUNNER.md) for the exact live execution
status and encrypted evidence workflow. No raw records or private numeric
research output is published in this repository. This patch provides acquisition
and rate screening, not the subsequent MBO queue/trade-through fill simulator.
The latter should compare first/partial/full fills, censored unfilled orders and
joint completion versus target rates and configured delays. Trade extraction
must count `T` records once and not also add their passive `F` records.

Sources: [Databento BBO](https://databento.com/docs/schemas-and-data-formats/bbo),
[cost API](https://databento.com/docs/api-reference-historical/metadata/metadata-get-cost),
[batch example](https://databento.com/docs/examples/basics-historical/programmatic-batch-download),
[IAU issuer](https://www.ishares.com/us/products/239561/ishares-gold-trust),
[CME 1OZ FAQ](https://www.cmegroup.com/articles/faqs/faq-1-oz-gold-futures.html).
Additional sources: [CME SIC rulebook](https://www.cmegroup.com/rulebook/COMEX/1a/130.pdf),
[SIC FAQ](https://www.cmegroup.com/articles/faqs/frequently-asked-questions-100-ounce-silver-futures.html),
[CME MBT specifications](https://www.cmegroup.com/content/dam/cmegroup/education/files/getting-started-with-micro-bitcoin-futures.pdf),
[SLV issuer](https://www.ishares.com/us/products/239855/ishares-silver-trust-fund),
[IBIT issuer](https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf).
