# BTC PRD: first execution calibration

2026-10-13. Calibration and testing have started. This is a reproducible **unit
execution experiment**, not the requested funded portfolio proof of concept and
not a selection of production H/L values. No application deployment or live
exchange orders are involved. The current-leg PRD rule is now recorded in the
[implementation plan](BTC_PRD_EXPOSURE_BAND_PLAN.md).

## Findings

- The local dated pairs fail both 25% and 30% maturity separation throughout
  their saved windows. This experiment therefore covers the allowed long-proxy /
  short-future construction only. It provides no futures/futures calibration.
- The location of observed PRD changes materially over time. December median
  APR rises from 3.086% in training to 3.800% in validation and 4.453% in test.
  With a zero-cost proxy, these APRs are the proxy/future PRDs.
- The illustrative H=2%, L=1% has **zero completed cycles** in both later slices;
  each of the two independent instrument experiments ends with a short still
  open. Four training cycles do not establish an exit rate in the later regime.
- More cycles do not imply better economics. Costs, adverse stale-limit fills,
  unhedged proxy waiting and terminal marks change comparisons. None of the
  13 base candidates has positive marked net results in all three periods.
- A limit calculated at H/L does not guarantee that executed PRD: the index can
  change before the later strict-through fill. Record actual executed APRs for
  each lot and never retrospectively remove a valid but unfavorable fill.
- Fixed location is not yet supported by these data. The next calibration
  should evaluate a causal rolling location estimate, with fixed held targets,
  alongside fixed levels. This is an inference, not a tested adaptive policy.

## Inputs and chronology

182 original compressed raw files were hash-verified again: 1,149,605 raw rows,
1,110,095 ordinary rows after excluding block/RFQ/combo records. Ordinary trade
IDs are unique per instrument/window, prices and marks are positive, and no
ordinary timestamp reversal occurs. Every input hash is retained in the JSON.

| Stage | UTC interval, end exclusive | Futures observed |
| --- | --- | --- |
| Training | 2026-03-06 – 2026-06-06 | Sep26, Dec26 |
| Validation | 2026-06-06 – 2026-07-21 | Dec26, Mar27 |
| Fixed-grid test | 2026-07-21 – 2026-09-04 | Dec26, Mar27 |

The grid uses only training observations. Pool the two training instruments by
observed duration, take PRD quantiles 10/25/50/75%, round L to 0.25 percentage
point, and add gaps 0.25/0.50/1.00 percentage point. This gives L values 2.25%,
2.50%, 2.75%, 3.25%, plus the separate 2%/1% reference: 13 candidates total.
Each candidate is evaluated; no winner is chosen from the test period. These
later observations are now examined and must not be called an untouched test
for a subsequently changed policy. Runs reset at each slice; this is not a
continuous walk-forward portfolio with carried positions.

Observed distributions use the last observed APR held forward after 500 ms
observation delay, weighted by elapsed time rather than number of prints.
There is no pre-window seed, interpolation or maximum-age cutoff. This estimates
the observed step process, not continuously executable prices. The largest
carried observation interval reaches 3.69 hours for Mar27 in the test slice.

| Instrument / stage | 10th percentile | Median | 90th percentile |
| --- | ---: | ---: | ---: |
| BTC-25SEP26 / train | 2.005% | 2.595% | 3.131% |
| BTC-25DEC26 / train | 2.569% | 3.086% | 3.519% |
| BTC-25DEC26 / validation | 3.617% | 3.800% | 3.979% |
| BTC-25DEC26 / test | 4.151% | 4.453% | 4.834% |
| BTC-26MAR27 / validation | 3.807% | 3.941% | 4.151% |
| BTC-26MAR27 / test | 4.131% | 4.369% | 4.741% |

## Declared execution experiment

One native USD 10 inverse contract is the diagnostic unit. It is not a proposed
strategy child size, capital allocation or capacity estimate. Each candidate /
instrument / slice is independent and has no funding constraint; losses can
exceed the reference face over repeated cycles. Results cannot be scaled into
portfolio returns or combined as if the same account supplied the capital.

The cycle buys a synthetic proxy, sells one future contract, buys that contract
back, then sells the remaining proxy. Initial proxy BTC units equal 10 divided
by the actual synthetic purchase index. The native inverse contract and proxy
do not guarantee an exactly neutral BTC delta; all resulting price effects are
in the reported cash flows and terminal marks. There is one live phase per
experiment, no concurrent rung or pair allocation, and no shorts before the
proxy acquisition is known. Acquisition here does not test portfolio-wide
lowest-APR selection or the 30–60% exposure rule.

| Parameter | Base scenario | Sensitivity |
| --- | --- | --- |
| Observation/fill → decision; decision → market | 500 ms each | 2 seconds each |
| Posting distance | 1% passive distance from latest observed future trade | Always posted |
| Tape participation | 10%, whole native contracts | 1% |
| Transaction fee | 1 bp on every proxy and futures fill | 5 bp |
| Proxy expense / liquidity surcharge | 0 / 0 | 0.25% annual expense + 0.50% annual surcharge |
| Futures tick / face | USD 2.50 / USD 10 | Fixed research assumptions |
| Ladder increment | Disabled for this threshold experiment | Lot/rung logic tested separately |

All numerical settings are research scenarios, not approved live defaults or
claims about historical broker fees. The 1% posting distance is broad, uses a
last-trade approximation because no order book is present, and does not change
the PRD-derived price. Marketable limits have zero passive distance. Commands
cancel/replace old quotes only on delayed arrival; completed order identities
cannot be revived by an in-flight amendment. Resting orders have no arbitrary
age expiry.

Futures fills require a later price strictly through the limit, opposite
aggressor direction, and sufficient participation volume. Fill at the limit.
A timestamp equal to arrival cannot fill. Notifications and commands each obey
their delay; same-timestamp tape is processed before new observations/commands.
One print is never reused inside an experiment. Independent parameter scenarios
replay the same raw tape separately; their volumes are not additive capacity.

Proxy execution is explicitly synthetic at the first trade-attached index
observation strictly after order arrival. It is not a recorded ETF trade and
has no real book/slippage model. A future sell limit uses proxy_APR + H; the
cover limit uses proxy_APR + L, with proxy_APR=e/(1-e)+surcharge. Expense decays
proxy units by (1-e)^(elapsed years); the surcharge is a declared continuous
cost approximation. Neither establishes actual margin-sale/rebuy cash flows.

Native short P&L in BTC is 10 × (1/exit_price − 1/entry_price). For this unit
comparison it is converted at the exit observation's index; there is no native
collateral wallet, interest, portfolio margin or collateral conversion fee.
Unclosed shorts use the last raw mark and index; unsold proxy is marked as
well. Exit fees are charged only if a fill actually occurs. There is no invented
end liquidation. Current contract conventions are documented by
[Deribit](https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures);
the replay's tick, fees and conversion choices are stated assumptions.

## Full base grid

Cycle counts and USD net marks below sum the two independent instrument probes
in each period. Each probe trades one USD 10 native contract at a time. These
are normalized execution comparisons, **not returns on USD 20 of funded capital**.
Net includes fees, proxy price changes, realized inverse cash flows and any
unfinished-position mark. All base validation/test runs retain an open short at
the end; terminal marks therefore materially affect comparisons.

| H | L | Gap (pp) | Training cycles | Validation cycles | Test cycles | Validation net USD | Test net USD |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2.00% | 1.00% | 1.00 | 4 | 0 | 0 | -0.1484 | -0.1261 |
| 2.50% | 2.25% | 0.25 | 687 | 0 | 3 | -0.0785 | -0.0885 |
| 2.75% | 2.25% | 0.50 | 300 | 0 | 3 | -0.0438 | -0.0305 |
| 2.75% | 2.50% | 0.25 | 979 | 2 | 4 | -0.1911 | -0.0954 |
| 3.00% | 2.50% | 0.50 | 456 | 2 | 4 | -0.1313 | -0.0294 |
| 3.00% | 2.75% | 0.25 | 1,516 | 10 | 6 | -0.4764 | -0.0597 |
| 3.25% | 2.25% | 1.00 | 93 | 0 | 3 | +0.0258 | +0.0846 |
| 3.25% | 2.75% | 0.50 | 532 | 10 | 6 | -0.3084 | +0.0226 |
| 3.50% | 2.50% | 1.00 | 104 | 2 | 4 | -0.0554 | +0.1025 |
| 3.50% | 3.25% | 0.25 | 788 | 169 | 17 | -3.8971 | -0.2577 |
| 3.75% | 2.75% | 1.00 | 68 | 10 | 6 | +0.0774 | +0.1816 |
| 3.75% | 3.25% | 0.50 | 174 | 149 | 17 | -2.4947 | -0.0537 |
| 4.25% | 3.25% | 1.00 | 12 | 63 | 17 | -0.6266 | +0.2928 |

## Sensitivity example and actual executed PRDs

The following shows H=3.75%, L=2.75% as one grid example, not a selected winner.
Every candidate was stressed; the JSON contains all 338 runs.

| Scenario | Validation cycles | Validation net USD | Test cycles | Test net USD |
| --- | ---: | ---: | ---: | ---: |
| base | 10 | +0.0774 | 6 | +0.1816 |
| always_posted | 10 | +0.0774 | 8 | +0.2857 |
| two_second_delays | 12 | +0.0457 | 8 | -0.0081 |
| five_bp_fees | 10 | -0.0969 | 6 | +0.0696 |
| proxy_cost | 47 | -0.8352 | 32 | +0.3068 |
| one_percent_participation | 5 | +0.0570 | 5 | +0.1773 |

For that base example, validation has 12 entries, all with actual executed PRD
below H, and 10 exits, all above L. Test has 8 entries (3 below H) and 6 exits
(5 above L). Limits remain valid strict-through fills: the contemporary index
differs from the earlier index used to calculate the order. This is why the
actual fill-based pair PRD and transaction ledger must remain authoritative.

The proxy-cost scenario changes both the order levels and holding costs, so
its result cannot be interpreted as a pure fee deduction from the base path.
Likewise, longer delays can create more fills while worsening economics; more
fills alone do not demonstrate better execution. Broad posting misses some
paths seen by always-posted limits, as anticipated.

## Current-leg ladder rule and tests

The research reference derives a pair ladder from current remaining lots. A
3% long and 6% short have current PRD 3%, regardless of a retired leg's gains.
Partial replacements update both old and destination summaries. Empty pairs
have null PRD; unknown anchors remain unknown. A pair-wide average cannot
qualify individually low-PRD lots. No separate transferred credit is stored.

The declared research reconstruction fills contiguous rungs from qualifying
lots in ascending executed PRD order, breaking ties by lot ID; quantities split
at rung boundaries. Equality at a target qualifies. Below-threshold inventory
remains owned and must consume portfolio risk capacity when the funded replay
is added. Pending order reservations and import seeding are not implemented by
this small lot-only reference.

16 deterministic tests pass: partial/long/short replacements, no cumulative
credit, quantity conservation, weighted/null PRD, unknown anchors, lower-rung
restoration, strict-through/equality/aggressor/volume conditions, two latency
legs, timestamp ties, no completed-order revival, persistent old quotes,
posting distance, native short P&L and unfinished marks.

The independent audit re-reads the hash-verified raw data and checks all 45,088
fills in 338 runs: source observation and rounded limit, both delays, no reused
print, strict-through direction/participation, posting band, proxy price, fees,
four-phase cycle order and independently reconstructed native/proxy cash and
terminal positions. It passes. This certifies the declared unit experiment,
not the missing portfolio mechanics.

## Remaining work before choosing production levels

1. Obtain eligible futures/futures raw windows and observations spanning the
   three-month retirement window and the strictly-before-60-day target. The
   full archive exists; the current local samples do not exercise those cases.
2. Build the cash-start native funded replay: shared exposure/leverage/collateral
   reservations, lowest-APR acquisition, partial fills, concurrent pair ladders,
   roll/netting ownership, late fills and restart reconciliation. Unit quantities
   here must be replaced by the agreed headroom-derived sizing.
3. Calibrate location and gap against incremental funded result versus the same
   baseline acquisition policy, retaining unmatched risk, funding/exit losses and
   fees. Test causal location refits and old-order price drift on new chronological
   periods; do not pick whichever of the examined test rows happens to look best.
4. Validate final candidates with ladder increments and expiry escalation, then
   reserve a genuinely new final period. No live parameter or app integration is
   approved by the current execution-only evidence.

## Artifacts and reproduction

- [Experiment code](research/btc_prd_execution_calibration.py)
- [Frozen configuration](research/btc-prd-calibration-config.json)
- [All results and input hashes](research/btc-prd-execution-calibration.json)
- [Every fill, compressed JSON lines](research/btc-prd-calibration-fills.jsonl.gz)
- [Independent audit code](research/validate_btc_prd_calibration.py)
- [Audit result and artifact hashes](research/btc-prd-calibration-validation.json)
- [Current-leg lot/rung reference](research/btc_prd_pair_lots.py)
- [Deterministic tests](research/test_btc_prd_calibration.py)

```bash
python -m unittest discover -s docs/research -p "test_btc_prd_calibration.py" -v
python docs/research/btc_prd_execution_calibration.py \
  --sep-dec /path/to/sep_dec_history \
  --dec-mar /path/to/dec_mar_verified_inputs --output docs/research
python docs/research/validate_btc_prd_calibration.py \
  --sep-dec /path/to/sep_dec_history \
  --dec-mar /path/to/dec_mar_verified_inputs --output docs/research
```

Python 3 and NumPy are required. No network, exchange downloads, credentials,
paid data or application services are required by these research scripts.
