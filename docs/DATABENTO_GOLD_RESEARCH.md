# September 2026 December 1OZ / IAU research

This owner-run CLI first measures sampled, immediately marketable bid/ask lease
indications, then optionally acquires MBO for a later time-to-fill study. It does
not place orders or change the deployed strategy. The selected contract is
December 2026 `1OZZ6`, not a rolling continuous series. The month is
`[2026-09-01T00:00:00Z, 2026-10-01T00:00:00Z)`.

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

The preset is `strategies/research-1oz-dec26-september.json`. It defaults to one
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
expiry, entry costs, whole-share/depth checks, invalid quotes and purchase resume.
No real Databento data, numeric September result or GCS upload is claimed until
the owner executes with credentials and inputs. This patch provides acquisition
and rate screening, not the subsequent MBO queue/trade-through fill simulator.
The latter should compare first/partial/full fills, censored unfilled orders and
joint completion versus target rates and configured delays. Trade extraction
must count `T` records once and not also add their passive `F` records.

Sources: [Databento BBO](https://databento.com/docs/schemas-and-data-formats/bbo),
[cost API](https://databento.com/docs/api-reference-historical/metadata/metadata-get-cost),
[batch example](https://databento.com/docs/examples/basics-historical/programmatic-batch-download),
[IAU issuer](https://www.ishares.com/us/products/239561/ishares-gold-trust),
[CME 1OZ FAQ](https://www.cmegroup.com/articles/faqs/faq-1-oz-gold-futures.html).
