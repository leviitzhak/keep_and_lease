# Carry economics, sparse action grids and expiry evidence

Research update, 26 October 2026. All source timestamps and experiment times use
UTC. Research only: no deployment, master merge, purchases, infrastructure or
long training. This updates the action-search default after
[FULL_ACTIONS_AND_UNION.md](FULL_ACTIONS_AND_UNION.md); frozen results remain intact.

## Funding evidence means dated liquidity and financing terms

This means evidence, or explicit assumptions, about whether the portfolio can pay
all obligations along its path: Treasury purchase prices and coupon/principal
dates, futures variation settlement, usable collateral, margin requirements,
haircuts, transfer delays, borrowing limits/rates and financing fees. A Treasury
payable later is not automatically cash available for a margin call today.
There need not be borrowing in a fully funded strategy, but it still needs
liquid margin reserves. This is distinct from perpetual-futures funding payments.

The current research ledger already represents dated Treasury receipts, debts,
collateral and variation payments. It does not establish an actual broker's
historical credit/collateral permissions. Those account-specific terms are not
obtainable from a generic market-price download. A first counterfactual experiment
can use declared conservative assumptions, retaining sensitivity tests and
separating simulated financing from observed market data.

## Bounded public acquisition

`download_expiry_inputs.py` obtains public data without credentials or purchases:

- Deribit BTC/USD historical delivery indices, paginated to the advertised end.
- Deribit daily settlement marks for dated BTC futures through the frozen archive
  boundary, with explicit per-contract coverage. Public platform-wide P&L fields
  are never assigned to the strategy's account. Perpetuals are excluded from the
  normalized dated-futures output.
- Official Treasury bill quotations for 2016–2026, retaining quoted rates and
  the security identifiers/maturity dates supplied by the feed. These are
  indicative bid quotations, not demonstrated executable purchases.

Raw responses have source URLs, retrieval times, SHA-256 hashes and deterministic
gzip storage. Restarts verify and reuse immutable cached responses. Requests are
bounded to 80 per invocation, 24 MB downloaded and 240 seconds checked between
requests; individual network operations have a maximum 15-second timeout. There
is no retry loop. No full trade dataset is downloaded again.

The API returned 100 delivery records despite a requested 1,000. Pagination now
advances by actual records returned and verifies the final unique total. The
Treasury feed uses `INDEX_DATE` and includes CUSIP/maturity fields; the parser also
accepts its older `NEW_DATE` form. Tests cover both cases. An initial bounded pass
was resumed after adapting these observed formats and a request timeout. Cached
raw responses were reused, not fabricated or silently skipped.

Results and hashes are in `expiry-input-report.json` and
`expiry-input-artifacts.json`; `expiry-inputs-v1.tar.gz` contains raw responses,
normalized data, the pinned futures plan and detailed contract coverage.
Exhausting an API is not proof of complete history from every contract's listing:
coverage explicitly reports missing daily events under the 08:00 UTC convention.

The completed cached normalization reports 59 source objects / 13,005,981 raw
bytes: **2,650 delivery dates (2016-03-18 through 2026-10-26), delivery values for
all 528 expired contracts in the frozen plan, 17,695 dated-futures daily settlement
events across 495 instruments, and 2,703 Treasury quote dates**. 473 expired
contracts have all expected daily settlement dates; 55 have missing dates. All
those gaps are retained in `coverage.json`. The API ends its settlement cursor
with the literal string `none`; this is handled explicitly, and backward-progress
checks reject a restarting page. Final normalization made zero network requests,
using the completed cache. There were two bounded network passes; final checks
did not launch another acquisition.

Treasury observations become available no earlier than the next UTC day in the
normalized research view. This is a conservative modeling convention, not a
verified historical publication timestamp. Treasury discount yields and bond
equivalent yields are retained separately; no quoted yield is silently treated
as an overnight deposit return.

Remaining through-expiry work is precise: validate and adapt existing spot trade
archives for execution around bridges; establish USD/USDT conversion where needed;
model spreads, fees, participation and delays; handle uncovered settlement days;
construct Treasury purchases and receipt calendars with executable or explicitly
assumed prices; specify margin, collateral and financing terms. The large spot
archive already exists, so another bulk spot download is not the next step.
An official delivery index is not an executable spot price. These data files do
not by themselves make the current neural pilot a realized through-expiry study.

Primary source documentation:
[Deribit delivery indices](https://docs.deribit.com/api-reference/market-data/public-get_delivery_prices),
[daily settlement events](https://docs.deribit.com/api-reference/market-data/public-get_last_settlements_by_currency),
[Treasury XML feed](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed),
[Treasury rate definitions](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics).

## Sparse search, scalable effort

The normal pilot now defaults to `--action-space grid`. Every decision builds
small native tick/lot sets for each eligible observed instrument: both interval
endpoints, a midpoint, and up to two random interior points. No full price or
quantity lattice is enumerated. Initial proposals cover both price extremes,
both sides and both quantity extremes; existing-order amendments also include
price extremes while retaining current size. Remaining proposals sample single
orders, independent multi-order packages and edits from the sparse sets.

The default is 32 attempts over four rounds. `--search-evaluations` (4–4096),
`--search-rounds` and `--grid-random-points` (0–16) expose the effort tradeoff.
For two instruments, 32 attempts covers all 16 new-order boundary combinations
plus wait/emergency actions and the tested working-order amendments. If the
universe is larger or the budget smaller, not all anchors fit: their order is
seeded and shuffled, and `boundary_proposals_not_attempted` reports omissions.
There is no claim that a tiny budget checks every instrument or all combinations.

Prices reference the last received trade; no BBO is invented. Existing funding,
90% initial-holding floors and six-uncertain-version admission bounds still apply.
Actual orders and their pending effects enter the post-state, not grid parameters.
Selection maximizes the scalar expected joint trajectory score among evaluated
feasible states, with the existing declared exploration during collection. All
heads share one continuation identity including grid and effort settings.

`--action-space full` retains the previous full-domain stochastic search;
`--action-space legacy` retains the original small fixed menu. Changing any search
setting changes the continuation policy, so training labels/checkpoints cannot
silently be mixed across these variants. The network parameter count is unchanged.

Short CPU benchmarks used the same historical states and existing checkpoint,
one Torch thread, 64 history events and four measured repetitions after warmup.
These are inference/search timings, not new learned-policy performance:

| Attempts | No working orders: mean | Two working orders: mean |
|---|---:|---:|
| 16 | 26.6 ms | 26.9 ms |
| 32 | 35.7 ms | 54.7 ms |
| 64 | 57.0 ms | 331.2 ms |

At 32 attempts, a 365-day, 500 ms trajectory extrapolates to about 26–40 CPU-days
for search alone, before tape/event processing. The 64-attempt working-order
probe was variable (98–895 ms); do not assume linear scaling or attribute all
differences from older measurements solely to the code change. Full measurements
are in `sparse-grid-timings.json`. Annual training was not run.

## BTC carry identity and what the current learner can do

Let one initial BTC sell for `S0`, let the investment produce known net cash
`C_T` at expiry, let a linear future's entry price be `F0`, and let `S_T` be both
the final settlement index and executable spot price in the ideal example.
The investment amount must exclude required margin reserves and financing costs.

Holding one BTC of futures exposure yields final cash `C_T + S_T - F0`.
Buying BTC with it gives:

```
BTC_T = 1 + (C_T - F0) / S_T
```

Alternatively, fixing the future's size at `q = C_T / F0` gives final cash
`q S_T`, which buys exactly `q` BTC under the same ideal bridge. Thus `C_T > F0`
allows BTC-unit growth without a directional BTC price forecast. With `S0=100000`,
`C_T=105000` and `F0=104000`, one-BTC exposure preserves one BTC plus $1,000, or
the larger `q=105/104` exposure targets about 1.009615 BTC. The amount of extra BTC
from converting a fixed cash surplus still depends on `S_T`.

Tests verify both constructions at $70,000 and $120,000 terminal BTC prices,
including intervening variation payments. Separate tests verify deductions for
spot/index basis differences and fees. These are deterministic synthetic
accounting fixtures, not historical execution results or a proof of feasible
liquidity under every path. Selling all BTC before the replacement future fills
would violate the 90% BTC floor; execution must be staged and reservations checked
after each partial fill. Treasury maturity timing must precede the cash need.

A neutral long/short futures pair can increase USD while preserving BTC claims.
Treasury cash/futures or Treasury/Treasury relative-value trades likewise require
a precise neutrality definition: equal notionals need not neutralize duration,
and matching DV01 only addresses small parallel yield shifts. Curve, convexity,
repo and delivery-basket risks need their own treatment. See
[CME's DV01 spread discussion](https://www.cmegroup.com/articles/2026/calibrating-treasury-link-dv01-weighted-spreads.html).
The current BTC `Instrument` adapter is not a Treasury-futures adapter.

Two implementation gaps are explicit. First, the learned action domain currently
contains futures orders only. The ledger can represent Treasury receipts and
bridges, but the policy cannot yet choose the full spot-sale/Treasury-purchase/
future/spot-conversion sequence. Second, the existing basket score
`min(BTC growth, USD growth)` gives zero to cash-only growth with unchanged BTC,
and zero to BTC-only growth with unchanged positive initial USD. Such a portfolio
improvement should not be confused with no economic growth. A reward that values
those improvements, or an explicit reallocation of the surplus to both goods,
is needed for this objective. This patch documents and tests that distinction;
it does not silently change frozen utility labels or claim the current model has
learned these missing actions.

## Tests and reproduction

97 post-decision tests and 83 existing ledger/paired-strategy tests passed.
The 15 added tests cover sparse endpoints/lot validity, seeded interior sampling,
budget omissions, closed-loop grid selection, continuation identity, carry and
neutral-pair accounting, delivery pagination, source-cache integrity and Treasury
schema/availability. Logs are committed alongside this report. No new neural
training or annual evaluation was launched.

```bash
python -m unittest discover -s tests/post_decision_value -v
python -m unittest tests.test_funded_ledger tests.test_paired_transfer_economics tests.test_paired_execution_study -v
python -m research.post_decision_value.pilot \
  --input /path/to/existing/dec_mar_inputs --output /path/to/new-run \
  --action-space grid --search-evaluations 32 --grid-random-points 2
python -m research.post_decision_value.expanded_validation \
  --root /path/to/existing/dec_mar_inputs --output /path/to/new-timing \
  --benchmark-only --action-space grid --search-evaluations 32
python -m research.post_decision_value.download_expiry_inputs \
  --plan /path/to/pinned/plan-reconciled-v2.json --output /path/to/expiry-inputs
```

Use the existing Torch 2.14.1 CPU environment. Reusing an acquisition output
directory resumes hash-verified raw responses; simulation/timing output directories
remain immutable. Prefer the saved input archive over repeating public requests.
