# BTC PRD band: direct raw-data preflight

2026-10-13. This is a coverage and hypothetical limit-crossing screen, **not a
portfolio-strategy backtest**. It prepares the requested direct proof of concept
before application integration. No download, purchase or deployment was needed.

## Inputs verified directly

Read all records in the 182 locally available compressed raw-trade files below.
Every compressed-file SHA-256 matches its retained acquisition manifest. Trade
IDs are unique within each instrument/window, all timestamps fall inside the
declared ranges, and block/RFQ/combo flags are excluded from ordinary observations.
No ordinary-record timestamp reversal was found in these inputs.

| Instrument/window (UTC, end exclusive) | Raw rows | Ordinary rows |
| --- | ---: | ---: |
| Sep26, 2026-03-06 to 2026-06-06 | 429,247 | 419,810 |
| Dec26, 2026-03-06 to 2026-06-06 | 234,155 | 227,643 |
| Dec26, 2026-06-06 to 2026-09-04 | 319,976 | 306,692 |
| Mar27, 2026-06-06 to 2026-09-04 | 166,227 | 155,950 |
| **Total** | **1,149,605** | **1,110,095** |

These are the two inspected local datasets. This report does not assert that
they exhaust the separate full-history cloud download or certify its current
completion state. It also does not assume availability of other contract pairs.
The subsequent [full-catalog maturity analysis](BTC_MATURITY_SEPARATION_HISTORY.md)
does verify the frozen archive's completion records and examines all 540
instruments; it finds five qualifying 25% windows across the saved history.
The inputs have native trade-attached index and mark fields; no independent
continuous spot/proxy transaction feed is established by this check.

## The 25% rule excludes both inspected dated pairs

Both expiry gaps are exactly 91 days. Requiring
`gap <= 0.25 * longer_remaining_maturity` requires the farther expiry to be at
least 364 days away. It is already much closer at the start of both samples.

| Pair | Sample | Gap / farther remaining maturity, start to end limit | Eligible pair seconds |
| --- | --- | ---: | ---: |
| Sep26 / Dec26 | Mar 6–Jun 6 | 30.917% → 44.975% | 0 |
| Dec26 / Mar27 | Jun 6–Sep 4 | 31.023% → 44.754% | 0 |

Every ordinary trade in these four filesets satisfies the individual
three-calendar-month condition. The pair rejection is entirely due to the 25%
proximity rule. Both directions have the same expiry eligibility. A futures-only
run starting in cash on exactly these inputs would have zero pair openings;
that would not be evidence of a latency or PRD fill failure.

The owner-approved proxy exception permits testing a proxy/future construction
without changing the requested 25% rule. Other future/future candidates should
be discovered in the wider historical catalog before relaxing that rule.

## Hypothetical strict-through screen for proxy/future limits

Predeclared illustrative screen: proxy expense=0, margin-liquidity surcharge=0,
opening PRD=2%, closing PRD=1%, 500 ms observation-to-decision and 500 ms
decision-to-market. Each future is screened independently against its own
trade-attached index stream. There is no invented spot transaction.

Each ordinary index observation generates a hypothetical future sell limit at
`index * (1 + remaining_years_at_decision * 0.02)` and buy limit at the same
formula with 0.01. Assume a $2.50 price tick, round sells up and buys down,
and activate only after both delays. A print at exact order-arrival time or
exactly at the limit cannot count. New quotes replace old quotes on arrival;
the old quote remains effective until replacement. Predetermined expiry is
31 seconds after the source observation (30-second quote age plus both delays),
or the three-month boundary if earlier. No pre-window seed is assumed.

| Instrument/window | Ordinary prints strictly above opening sell limit | Ordinary prints strictly below closing buy limit |
| --- | ---: | ---: |
| Sep26, Mar 6–Jun 6 | 258,210 | 186 |
| Dec26, Mar 6–Jun 6 | 137,513 | 44 |
| Dec26, Jun 6–Sep 4 | 198,465 | 4 |
| Mar27, Jun 6–Sep 4 | 93,528 | 0 |

These are **quote-crossing records, not simulated fills or available strategy
capacity**. No capital, order size, inventory, fees, matched pair, ladder, margin,
roll or P&L is simulated. The opening and closing screens are independent: a
closing crossing need not follow an earlier opening. Successive prints are not
independent experiments. The report's crossing-volume fields are diagnostic
print totals, not volume available to a trading strategy. A target limit can
also be marketable; without the book, this screen does not establish queue
position or resting-order status.

Inference for the next experiment: the zero-cost proxy construction appears
much more likely to encounter the 2% opening threshold than the 1% closing
threshold in these samples. Capital and inventory could therefore remain
occupied for long periods. This is a motivation to run a funded lifecycle
replay, not a measured portfolio outcome. Expense/surcharge and latency
sensitivities are needed before extending this inference to the intended setup.

## Reproduction and next step

Script: [research/btc_prd_band_input_screen.py](research/btc_prd_band_input_screen.py).
Full machine-readable results and source-file hashes:
[research/btc-prd-band-input-screen.json](research/btc-prd-band-input-screen.json).

```
python docs/research/btc_prd_band_input_screen.py \
  --sep-dec /path/to/sep_dec_history \
  --dec-mar /path/to/dec_mar_verified_inputs \
  --output docs/research/btc-prd-band-input-screen.json
```

The subsequent [execution calibration](BTC_PRD_EXECUTION_CALIBRATION.md) tests
a chronological threshold grid with actual unit fills, synthetic proxy execution
and unfinished-position marks. It confirms that both local dated pairs also
fail the proposed 30% rule. It remains separate from the capital-constrained
cash-start research replay
described in [BTC_PRD_EXPOSURE_BAND_PLAN.md](BTC_PRD_EXPOSURE_BAND_PLAN.md), with
the bootstrap and numerical research settings stated explicitly. The existing
six-level research engine cannot be called this strategy unchanged: it lacks
this band/margin/startup/roll model and its older instant first-fill coupling
does not implement the newly requested delayed fill-notification policy.
