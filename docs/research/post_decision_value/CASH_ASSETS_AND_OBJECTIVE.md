# Spot, proxy and Treasury actions; conditional maximum growth

The later [weighted/event-clock update](WEIGHTED_EVENT_TRAINING_PLAN.md) adds a
continuous weighted objective and changes the default for new CLI runs. This
report and its saved synthetic models retain their original gated-max objective.

Research update, 27 October 2026 (UTC). Branch
`agent/btc-post-decision-value-v1`. No deployment, live orders, infrastructure,
new data acquisition or long training. Earlier historical reports retain their
original data, objectives and checkpoints.

## Objective and carry economics

Let `g_B = (terminal BTC - initial BTC) / initial BTC` and analogously `g_U`.
These refer to **net long-term holdings after obligations**, not gross exposure
or mark-to-market profit. The original `basket` objective is `min(g_B,g_U)`.
It rewards balanced improvement but scores zero when one commodity stays flat
and the other grows. A cash-profitable, equal-BTC-quantity futures pair can
therefore tie hold, even after all dated funding requirements are satisfied.

The new selectable `gated_max` objective is:

```
m = min(g_B, g_U)
M = max(g_B, g_U)
U = m if m < 0 else M
trajectory label = U - failure_penalty * failed
```

The nonnegative branch includes **zero**, so cash-neutral BTC growth and
BTC-neutral cash growth are rewarded. New pilot CLI runs default to this mode;
`--objective basket` preserves the old objective. Low-level `Goal` retains its
old default. Only positive-initial commodities enter the min/max, matching the
original convention; zero-initial assets still need explicit floors/scales.

| BTC growth | USD growth | Original minimum | Conditional maximum |
|---:|---:|---:|---:|
| 0% | +1% | 0% | +1% |
| +5% | 0% | 0% | +5% |
| +2% | +3% | +2% | +3% |
| +5% | −0.0001% | −0.0001% | −0.0001% |

This rule is monotone but discontinuous when the weaker commodity crosses zero.
It also stops rewarding improvement in the smaller positive gain while the
larger gain remains unchanged. Floating-point sign is used without hiding a
small loss behind a tolerance. Training close to that boundary requires careful
calibration. Maximizing its expectation does not guarantee nonnegative growth
on every trajectory. The 90% initial-holding floors, dated funding stress,
inventory restrictions and recorded path failures remain separate. The finite
failure penalty is not a lexicographic guarantee against every risky policy.

The scalar head learns **E[U(g_B,g_U) − penalty | immediate post-state, π]**.
Commodity and probability heads share that same continuation π. It never gates
or maximizes the mean commodity predictions. For example, equally likely
outcomes (+10%,−1%) and (+10%,+1%) have expected utility 4.5%, whereas applying
the rule to their average holdings incorrectly gives 10%.

For a frictionless matched-date illustration, sell `q` BTC at `S`, invest the
proceeds to obtain `q*S*R` USD, and buy `q'` linear futures at `F`. The funded
expiry bridge restores `q'` BTC with net USD residual `q*S*R - q'*F`, assuming
settlement index equals executable spot. If `S*R > F`, either retain the surplus
as USD with `q'=q`, or choose a larger `q'` while keeping the USD residual
nonnegative. Trading fees, margin liquidity, receipt timing, price gaps and
incomplete legs must still be accounted for. Different future expiries require
separate dated bridges, not an assumption that cash flows cancel immediately.

## Implemented cash instruments

- **Spot:** native amount in BTC, price in USD/BTC; a fill changes actual BTC and
  USD balances. No duplicate position claim is created.
- **Proxy:** native shares with an explicitly declared fixed BTC/share ratio;
  cost is paid in USD and owned shares carry modeled BTC look-through units.
  This is a research proxy, not verified physical BTC redeemability or an ETF
  tracking/expense model. Selling unowned shares is rejected.
- **Treasury:** native security units, an all-in USD price per unit, tick/lot,
  listing time, maturity, and explicit USD coupon/principal amounts per unit.
  A zero-coupon bill uses one maturity receipt. Prices must already include
  accrued interest where applicable; annual quoted yields are not trade prices.
  Principal is not counted twice. Partial sales change subsequent entitlements.

Treasury bills pay face value at maturity; fixed-coupon notes/bonds have dated
interest and principal. These distinctions follow
[TreasuryDirect's pricing description](https://www.treasurydirect.gov/marketable-securities/understanding-pricing/).
Future floating-rate resets, inflation index changes and reinvestment are not
fabricated. The synthetic fixtures deliberately compress time and use artificial
cashflows; they do not purport to be actual Treasury issues.

Purchases require settled unpledged USD. Sales require owned unpledged cash
assets. Cash assets cannot fund futures margin merely because their future
receipts or look-through values are positive. Funding stress handles coupons,
principal and futures bridges in date order, conservatively debiting bridges
before same-date receipts. No automatic Treasury/proxy liquidation is assumed.

Orders retain the same pending creation/amendment/cancellation and delayed fill
reports as futures. Hidden fills never enter features early. Native quantities
are reserved for cash sales; purchase cash is reserved without deducting wealth.
At equal timestamps, Treasury payments precede messages/trades, making a new
purchase ex-coupon. Maturity cancels working orders with delayed acknowledgement.
Payment ownership survives checkpoint/resume and is credited only once.

Cash payments in this adapter are **contractual projections**, not observed
account settlements. Even after a modeled payment has become simulated cash,
`projected_receipts` retains its provenance and the outcome stays labeled
`contractual/projected`. Securities trade settlement lags are not modeled;
the funded cash-at-fill convention is explicit. Synthetic future bridges have
explicit fixture prices and are not historical settlement evidence.

## Search, features and training

Spot/proxy/Treasury actions use the existing grid or full-domain search. The
legacy candidate menu is rejected for cash bundles. Instruments are eligible
only after listing, with a received observation, while enabled and before expiry.
Treasury/futures maturities must fit within the claim-resolution horizon.

Default ranges are 0.0001–0.02 BTC equivalent per spot/proxy/futures order,
$100–$2,000 posted notional per Treasury order and ±50 bp around the last received
price. Proxy amounts divide the BTC range by BTC/share. Treasury amounts divide
the USD range by the actual proposed limit. All are rounded to native lots/ticks.
The sparse grid uses endpoints, midpoint and random interior values; bounded
search evaluates feasible immediate post-states. Multiple legs have independent
prices and quantities. Six uncertain order versions bound admission computation;
this is not a 50-action menu or a ban on posting while other orders work.

Schema 2 adds instrument kinds, native quantities, reserved inventory, proxy
ratio, Treasury receipts and the objective flag. Input dimensions are global
35, item 28, history 11. The architecture otherwise remains width 64, two causal
Transformer layers, four attention heads, a shared item encoder and five
outputs: scalar expected utility, BTC/USD growth, failure and attainment.
**88,645 trainable parameters**, versus 87,877 in schema 1. Both checkpoint
formats load; old models explicitly reject new features and require retraining.
Mixed objective/continuation labels are rejected. Source, data, objective and
search configuration enter run/continuation identity.

## Completed bounded synthetic pilot

Artifacts: [cash-smoke-v1.tar.gz](cash-smoke-v1.tar.gz),
[report](cash-smoke-report.json), [receipts](cash-smoke-artifacts.json).
The archive includes exact source snapshot, synthetic tapes and manifests,
configuration, chronological splits, every selected action/candidate audit/fill,
complete-outcome samples, both model/optimizer/RNG checkpoints, all minibatch
training losses, test logs and three through-expiry carry replays.

Six **synthetic** scenario days: 0–1 training, 2–3 validation, 4–5 held-out test.
Each day has 1.8 seconds of compressed-time events, decisions every 200 ms and
seeds 11/29. Instruments are two linear futures, spot, a fixed-ratio proxy and
that day's Treasury. No real calendar period or historical yield is represented.
Search uses 64 proposals, ±25 bp, 0.001–0.01 BTC, $100–$1,000 Treasury notional,
up to three new orders, and explicit seeded delays. Fees are zero in this fixture.

Stage 0 collects the analytical/random continuation and fits 80 updates.
Stage 1 collects the learned greedy continuation with 15% exploration and fits
80 new updates. Each stage has 36 complete labeled post-states from four
episodes. Validation selects stage 1 (`value_v2`); test is untouched until that
selection. Matched hold and analytical policies use the same scenario days,
initial holdings and delay seeds. No tuning was performed on the test results.

| Held-out policy | Mean utility | Mean BTC growth | Mean USD growth | Fills | Failed paths |
|---|---:|---:|---:|---:|---:|
| Hold | 0% | 0% | 0% | 0 | 0/4 |
| Analytical full-fill score | −0.5090975% | +0.5% | −0.5090975% | 16 | 0/4 |
| Selected value network | −8.35% | −8.35% | +8.68654625% | 38 | 0/4 |

**The learned policy underperforms hold and is not accepted.** Low training loss
does not establish useful policy ranking. Stage losses fell from 1.04405 to
0.08270 and from 1.09300 to 0.12164; these are normalized training minibatch losses,
not test losses or investment returns. All fixture paths stay within the 10%
floors, which does not mean growth is nonnegative. These few scenarios cannot
calibrate failure probabilities, target-attainment probabilities or profitability.

The final run took 25.47 seconds, including 8.21 seconds of optimization, one
Torch CPU thread, 252 decisions and 5,685 exchange/report events. It ran beside
a brief focused test process; timings are smoke measurements, not annual
training estimates. Caps: 240 seconds, 2,000 decisions, 10,000 events/episode,
160 optimizer updates, 60 seconds per fit (stricter than project limits).

The separate through-expiry fixtures start with net 1 BTC and $100,000:

| Fixture | Terminal BTC | Terminal USD | Utility |
|---|---:|---:|---:|
| Sell spot, buy Treasury + equal-size future | 1 | 100,010 | 0.01% |
| Sell owned proxy, same carry | 1 | 100,010 | 0.01% |
| Allocate carry surplus to more futures BTC | 1.000096 | 100,000.016 | 0.0096% |

The first two sell 0.01 BTC equivalent for $1,000, buy ten $100 Treasury units
paying $1,050 total, and buy 0.01 futures BTC at $104,000. The third buys
0.010096 futures BTC. Explicit bridge index/spot is $120,000. Replay JSON retains
posted limits, fills, source IDs, pending reports, coupons and settlement states.
These are accounting demonstrations, not trades selected by the trained network.

## Verification, reproduction and historical gap

**193 distinct tests passed:** 110 post-decision tests and 83 existing ledger/
paired-strategy tests, including 13 new cash/objective tests. The post-decision
suite first ran 109 tests; the final focused rerun covers the added 110th and
the subsequent source-time guard. Saved logs retain the exact commands' counts.
Tests cover full-cost accounting, cash/inventory constraints, native sizing,
coupon entitlements, delayed reports, maturity cancellations, exact resume,
hidden-state separation, carry conservation, the zero-growth gate, expectation
versus average holdings, schema/checkpoint compatibility and real Torch fitting.

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover -s tests/post_decision_value -v
python -m unittest tests.test_funded_ledger tests.test_paired_transfer_economics tests.test_paired_execution_study -v
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m research.post_decision_value.cash_smoke --output /tmp/new-cash-smoke
# Once a verified cash bundle is available:
python -m research.post_decision_value.pilot --input /path/to/dec_mar_inputs \
  --cash-input /path/to/cash-bundle --objective gated_max --action-space grid \
  --output /path/to/new-historical-run
```

The cash bundle uses `manifest.json` schema 1, explicit `currency: USD`, typed
`Instrument` metadata and gzip JSONL `Trade` objects. Every object has byte count,
SHA-256, source URI and kind `observed_trade`, `indicative_quote` or
`synthetic_fixture`. Indicative and backdated data cannot authorize fills. Limits
are 8 MB compressed, 100,000 rows and 64 MB expanded per object. The archived
synthetic bundle is an executable format example, not historical input.

Existing delivery values, daily settlements and Treasury indicative quotes are
available, but an executable historical spot/Treasury bundle is not yet verified.
Already acquired raw spot archives need bounded normalization, availability and
currency checks; USD/USDT parity must not be presumed. Proxy holdings need dated
ratio, expenses and custody/redemption evidence. Account financing/margin,
securities settlement lags and executable expiry bridges remain necessary for
realized through-expiry results. No candle interpolation, quote depth, missing
settlement or subsecond cash fill was invented. This extension therefore reports
synthetic validation only; previous historical futures results are unchanged.
