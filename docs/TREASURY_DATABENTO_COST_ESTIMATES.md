# Treasury futures metadata-only Databento estimate

## Fixed scope

The October 12, 2026 research request uses the existing
`agent/cloud-autonomous-access` operator and `databento-research.yml` workflow.
It selects `study: treasury-three-month-cost-only-v1` and `action: estimate`.
The dates are July 11, 2026 00:00 UTC through October 10, 2026 00:00 UTC,
with the end exclusive (91 days). Dataset: `GLBX.MDP3`.

Quote ZT, ZF, ZN, TN, ZB and UB separately for `trades`, `mbp-1`, `mbp-10`
and `mbo`. The main quote selects each `ROOT.FUT` parent, covering all mapped
expiries and listed futures spreads, excluding options. A separate quote resolves
quarterly raw-symbol candidates (H/M/U/Z) for 2026–2029 through free symbology
and quotes only the resolved symbols. This second selection excludes spreads;
its explicit list and bounded candidate horizon are returned with the estimate.
It does not claim to be a charged definition-based universe validation.

The code fails if the vendor's dataset range cannot cover the exact dates.
It does not silently shorten the window. Estimates are returned in USD with
exact requests, a quotation timestamp, and per-schema sums across the six roots.
The schemas are alternatives; summing all four corresponds to requesting four
separate representations of overlapping market activity.

## Purchase and deployment controls

This study calls only `metadata.get_dataset_range`, `symbology.resolve`, and
`metadata.get_cost`. It never calls timeseries, batch submission, definition
downloads, cache acquisition, or private storage. The Treasury study cannot
be combined with `screen`, recovery instructions, user-selected dates, symbols,
schemas or budgets. Vendor/secret diagnostics remain captured and key-redacted.
Results use the existing recipient-only encrypted artifact mechanism.

Install the runner/test/doc update with `[skip ci]` in its commit message.
Then push only `.cloud-agent/requests/databento-research.json` with a fresh
request ID and RSA public key to start the bounded research workflow. This
two-step sequence suppresses application deployment. Do not merge to master,
purchase data, apply Terraform or deploy the application for this study.

The Databento key stays inside the authenticated GitHub runner. The requesting
workspace retains only the matching result-decryption private key; never commit
it. Read the completed workflow and decrypt its encrypted result to report the
quote. Metadata quotes are not a purchase, invoice, compressed-file-size estimate,
or a check of remaining account credits. Confirm any separate licensing costs
and cash-feed quotation before acquisition.

## Validation

`python -m unittest discover -s tests -p 'test_cloud_databento_research.py'`

The ten focused tests include rejection of purchase/recovery and arbitrary
scope, exact date coverage, 48 quote requests with correct selections/totals,
and assertions that no timeseries or batch method is called.

## Cash Treasury provider research

Start with CME DataMine BrokerTec for historical venue trades and top/depth/full
order books. Check the actual CUSIP coverage (especially off-the-run deliverable
bonds), the New York versus Chicago venue, and timestamp/order-ID conventions.
On-the-run benchmark data alone is insufficient to establish the historical
cheapest-to-deliver bond for every futures contract.

GovPX (CME DataMine / TP ICAP) explicitly covers on-the-run and off-the-run
Treasuries, with historical tick price discovery. It is a strong candidate for
delivery-basket pricing; verify which fields are indicative versus actual
markets and whether every desired CUSIP has sufficiently frequent observations.

LSEG Tick History is a broader multi-source tick/trade/quote candidate; request
an explicit coverage report for the deliverable CUSIPs and relevant contributors.
It must not be assumed to provide an executable consolidated Treasury book.
LSEG's official PCAP coverage list includes BrokerTec US Treasury MDP 3.0
and FENICS benchmark cash on-the-run Treasury feeds.

TraditionData also publishes a US Treasury Bonds specification with historical
tick data (RDF since 2019, legacy wire data since 2014). It is a secondary
contributor-price candidate; confirm CUSIP coverage and quote executability.

FINRA TRACE offers on-the-run Treasury transaction datasets. Its end-of-day file
and delayed enhanced historical data support transaction analysis, with no
resting bid/ask or queue history. The latter's six-month delay does not cover
the July–October 2026 window as of this request.

Official sources:

- <https://databento.com/docs/standards-and-conventions/symbology>
- <https://databento.com/docs/api-reference-historical>
- <https://www.cmegroup.com/markets/brokertec/brokertec-us-treasuries>
- <https://www.cmegroup.com/datamine.html>
- <https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history>
- <https://www.cmegroup.com/market-data/browse-data/catalog/govpx-us-treasury-and-agency.html>
- <https://www.traditiondata.com/product-specs/fii-bnd-ame-ust/>
- <https://www.finra.org/filing-reporting/trace/technical-notice/updated-agreements-non-real-time-trace-data-treasury-end-day-availability>
