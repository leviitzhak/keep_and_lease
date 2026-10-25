# Post-decision value v1 — final historical pilot

**Research implementation runs end to end; the learned policy does not outperform hold.** The final model is not accepted for trading or application promotion. Hold remains the reference fallback.

Source commit: `6b6865daf8b0691b934706229d8c281ca6dda507`. This is a counterfactual USD-linear experiment using native Deribit inverse trade prints. Figures describe net contractual commodity holdings, not realized expiry profits.

## Data and experiment

- Verified 16 daily objects: 45,756 raw rows and 923,128 compressed bytes, with native USD amounts, aggressor side, hashes, receipt sizes and row-count reconciliation.
- Instruments: BTC-25DEC26 and BTC-26MAR27; exact expiries and source URIs are in `pilot-v1/data-manifest.json`.
- Eight one-hour market blocks, 01:00–02:00 UTC: June 6–9 training, June 10–11 validation, June 12–13 held out. All seeds for a day remain in one split.
- Initial holdings: 1 BTC and $100,000; 90% floors. Two common delay seeds, two-minute decisions, 96 candidate budget, 10% print participation; hypothetical 1 bp trading fee.
- 480 complete training labels, two collect/fit stages, 320 optimizer updates. Both learned policies were frozen before validation; validation selected value_v2 among the two learned candidates.
- Both learned validation scores were negative. The final held-out comparison is evidence about the learner, not authorization to replace the baseline.

## Held-out comparison

The table averages two seeds on each of two independent market days. The joint score is the average of each trajectory’s minimum BTC/USD growth; it is not the minimum of the averaged growth vector.

| Policy / latency | BTC growth | USD growth | Joint score | Fills across four episodes | Fees across four episodes | Breaches |
|---|---:|---:|---:|---:|---:|---:|
| hold / 1× | 0.0000% | 0.0000% | 0.0000% | 0 | $0.000000 | 0 |
| analytical / 1× | 0.0000% | 0.0000% | 0.0000% | 0 | $0.000000 | 0 |
| value_v2 / 1× | -2.0950% | 1.3596% | -2.0950% | 22 | $0.543907 | 0 |
| value_v2 / 10× | -1.8450% | 1.1975% | -1.8450% | 21 | $0.479040 | 0 |

| Day / policy, standard latency | BTC growth | USD growth | Joint score | Mean marked USD wealth | Mean marked BTC wealth |
|---|---:|---:|---:|---:|---:|
| 2026-06-12 / hold | 0.0000% | 0.0000% | 0.0000% | $163,354.9400 | 2.57840888 |
| 2026-06-12 / analytical | 0.0000% | 0.0000% | 0.0000% | $163,354.9400 | 2.57840888 |
| 2026-06-12 / value_v2 | -0.1900% | 0.1227% | -0.1900% | $163,354.8755 | 2.57840786 |
| 2026-06-13 / hold | 0.0000% | 0.0000% | 0.0000% | $163,776.5500 | 2.56797444 |
| 2026-06-13 / analytical | 0.0000% | 0.0000% | 0.0000% | $163,776.5500 | 2.56797444 |
| 2026-06-13 / value_v2 | -4.0000% | 2.5966% | -4.0000% | $163,771.3198 | 2.56789243 |

Standard-latency value_v2 block mean scores range from -4.0000% to -0.1900%. With only two independent days, neither a reliable profitability claim nor a precise confidence interval is justified.

Minimum value_v2 floor headroom: 0.060000 BTC and $10,000.00. All actual tested path and funding checks passed. The test policy's paired asynchronous exposure was zero because its filled test instructions were directional; training did exercise paired execution and reached the 0.02 BTC limit.

Fixed-continuation score MAE averages 4.8778% across four calibration episodes. Terminal-holdings RMSE averages 0.049465 BTC and $3,113.07. Calibration is poor; synthetic dominance-test success does not establish historical forecast quality.

## Validation and resources

- **43 new tests passed**, including accounting, causality, trade-volume conservation, delayed reports, amendment/cancellation races, emergency admission, per-commodity floors, target transition, chronological label support, causal attention, scalar/commodity head independence and exact optimizer/engine resume.
- **83 existing regression tests passed** for the funded ledger, transfer economics and execution study.
- Independent historical audit passed: 16 source files, 48 audited episodes, 274 fills, 480 complete labels and eight matched baseline scenario groups. Four separate fixed-continuation calibration episodes are reported separately.
- Completed-pilot resume returns the same report after code/data/config verification. Both tensor-only model checkpoints were loaded and their continuation identities checked.
- Final pilot: 1,560 decisions, 28,257 exchange/report events, 320 optimizer updates, 9.76 training seconds, 48.81 total seconds, one CPU thread.
- An earlier smoke run before final API hardening and explicit causal summaries is retained as `pilot-initial-summary/`; it is not the final result. Both historical runs together used 640 optimizer updates and under 100 seconds. No test dates or trading hyperparameters were tuned to improve the final score.

## Spot archive status and material limits

The existing [spot acquisition run](https://github.com/leviitzhak/keep_and_lease/actions/runs/39736701767) completed on October 22 with `COMPLETE_WITH_SOURCE_GAPS`: 3,251 newly verified raw daily archives, 223 unavailable early days, zero pending days, and the existing 90-day range reused. New verified dates span August 17, 2017 through October 9, 2026, excluding the reused range. The operator summary says `parsed: false`. Its 77,413,288,976 raw bytes were not downloaded or reparsed in this task. The sanitized completed-job summary is saved in `spot-archive-status.json`.

The archive uses Binance BTCUSDT **individual trades**, not merely minute candles. Historical spot trading is still disabled here: the local pilot uses a validated futures export, and this task did not build a replay-ready spot adapter or verify USDT/USD conversion. Existing fine-grained data availability is not an invented execution model.

Other limits: hypothetical linear fees/margin/lots on inverse-source prices; finite funding stress scenarios; no observed book depth or queue position; FIFO allocation of capped print volume; no historical settlement/bridge tail; unknown future conversion costs excluded from contractual equivalents but stressed for funding. Treasury and inverse settlement paths are deterministic accounting fixtures, not independently validated historical trading studies. Target-composition configuration/constraints are implemented and tested; target-composition training is not evaluated in this pilot.

Outstanding positions, pending messages and live orders at the endpoint are included in the detailed reports. A completed decision horizon is not a live-account shutdown or a realized settlement test. Floor feasibility outside the finite stress set remains unproven. Failed and truncated trajectories are retained distinctly; truncated paths never receive terminal regression labels.

## Artifacts and reproduction

All final configurations, source references, original input metadata, chronological splits, trajectory features/labels, candidate and fill audits, model/optimizer/RNG checkpoints, calibration, test logs and reports are in `pilot-v1/`. `artifact-index.json` pins their SHA-256 identities. Raw source files remain at the existing GCS object URIs recorded in the manifest; no GCS data was overwritten or newly acquired.

Copy the four saved `input-metadata/` files into a local export directory and restore only the 16 hash-addressed source objects listed in `data-manifest.json` into its `inputs/` subdirectory using the existing authorized storage access. The acquisition code and all other daily objects are unnecessary for this bounded reproduction.

```bash
python -m unittest discover -s tests/post_decision_value -v
python -m unittest tests.test_funded_ledger tests.test_paired_transfer_economics tests.test_paired_execution_study -v
python -m research.post_decision_value.pilot --input /path/to/export --output /path/to/new-run
python -m research.post_decision_value.audit --input /path/to/export --run /path/to/new-run
python -m research.post_decision_value.pilot --input /path/to/export --output /path/to/new-run --resume
```

Installation, accounting conventions and safe push behavior are documented in [POST_DECISION_VALUE_V1.md](../../POST_DECISION_VALUE_V1.md). The research branch is excluded from deployment. No application deployment, master merge, live order, data purchase, infrastructure provisioning or bulk download occurred.

Exact session reproduction command (the existing cached export must still be present):

```bash
cd /workspace/scratch/54b859a43021/keep_and_lease
python -m research.post_decision_value.pilot --input /workspace/scratch/0daf5da3421c/dec_mar_inputs --output /workspace/scratch/54b859a43021/pdv-v1-reproduction
```
