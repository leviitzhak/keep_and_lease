# BTC-only backtest data and execution status

Evidence checked September 9, 2026. Dates below are UTC. An exclusive end of
September 4 includes all of September 3.

## Available inputs

| Input | Coverage / resolution | Location | What is established |
| --- | --- | --- | --- |
| Daily BTC spot and futures | Common curve/spot dates January 6, 2017–September 2, 2026; daily | Repository `public/data/btc/spot.csv`, `futures/`, `coverage.json`; copied into deployed assets | Manifest records 3,527 common dates with no missing calendar dates, 462 contracts with candles. Available maturity count varies; this is not tick history. |
| Binance BTC/USDT spot candles | June 6–September 3, 2026; 1 minute | Repository `public/data/btc/intraday/binance_1m/spot.csv.gz` and manifest | 129,600 bars, zero missing minutes, archive/output checksums. USDT is used as a USD proxy; no historical FX conversion. Close becomes observable at the next minute boundary. |
| Deribit futures candles | Same 90-day requested window; 1 minute | Repository `public/data/btc/intraday/deribit_1m/futures/` and manifest | 93 contracts, 1,202,419 rows, including 840,526 zero-volume synthetic rows. Synthetic marks may support valuation but are not observed executions. Each contract has its own lifetime and coverage. |
| Kraken BTC/USD midpoint candles | July 1, August 1, September 1, 2026 only; 1 minute | Repository `public/data/btc/intraday/kraken_1m/spot.csv.gz` and manifest | Three free Tardis sample sessions, 4,320 bars with no within-session missing minutes. Not a continuous three-month dataset. |
| Trade replay pilot | June 25, 2026; event timestamps | GCS `btc/trades/v1/9c05efc03118699303e7a55e14205bed29783683a85c165f99319dd3fabc055d` | Verified raw/Parquet/cloud equivalence and deployed GUI examples at 500 ms and 1 ms clocks. |
| Full trade replay range | June 6–September 3, 2026; Binance spot aggregate trades and Deribit futures trades | GCS immutable daily datasets and range below | All 90 daily raw/cloud comparisons passed. Full 90-day strategy result is not yet complete. |
| Treasury yields | Shared daily rate CSVs `DTB3`, `DTB6`, `DGS1`, `DGS2`, `DGS3`, `DGS5` | Repository root and deployed engine data | Replay carries the latest observable yield and accrues between observations; no future interpolation. Rate bytes participate in checkpoint identity. |

The trade range is:

`gs://keep-and-lease-market-data/btc/trades/ranges/52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912`

The final path component is the SHA-256 of `manifest.json`. It references 90
immutable daily manifests under `gs://keep-and-lease-market-data/btc/trades/v1/`.
Original raw inputs, source manifests, endpoint responses and anomaly ledgers
are content-addressed under `gs://keep-and-lease-market-data/btc/raw/sha256/`.
Large trade histories are not embedded in the application images.

Research benchmark audits/checkpoints live under
`gs://keep-and-lease-market-data/jobs/<validation-id>/`. GUI backtest results,
audits and checkpoints use `gs://keep-and-lease-results/jobs/<job-id>/`.
GitHub artifacts contain compact reports and receipts with finite retention;
they are not the canonical market-data store.

## Checks completed, and their limits

- [Recovery 34267650300](https://github.com/leviitzhak/keep_and_lease/actions/runs/34267650300)
  published the full immutable range after 90 daily verification gates. August
  26 and 28 were recovered from already-uploaded GCS objects, not redownloaded
  from exchanges: 4,323,107 and 4,862,726 events respectively were reverified.
- Raw checksums, Parquet event identity, uploaded bytes, contiguous daily range
  coverage and immutable manifest hashes pass. These establish fidelity to the
  collected history, not a proof that an exchange never omitted a trade.
- Deribit sequence/timestamp disagreements and extra endpoint records are
  retained in versioned evidence. Sequence order with delayed backwards times
  and original timestamp order are two explicit research assumptions. Missing
  sequence gaps/conflicting versions within the inspected envelope still fail.
  The causes of observed discrepancies remain unresolved.
- Trade replay uses the regular USD futures proxy, not native inverse BTC
  collateral/settlement accounting. Trade prints do not reconstruct historical
  bid/ask depth or queue position; the participation/latency model remains an
  assumption. Post-expiry prints cannot fill orders.
- [Preview 34267612174](https://github.com/leviitzhak/keep_and_lease/actions/runs/34267612174)
  passed pilot GUI, financial equivalence, CSV/audit, hover and fractional-window
  checks. It is not full 90-day Cloud Run acceptance.

## Measured staged replay results

[Run 34267691181](https://github.com/leviitzhak/keep_and_lease/actions/runs/34267691181)
used the same saved 500 ms strategy and starts June 6. Times include ordering
preparation and apply to GitHub runners, not measured Cloud Run performance.

| Days | Sequence time | Timestamp time | Sequence / timestamp peak process RAM | Compressed audit per policy |
| --- | --- | --- | --- | --- |
| 1 | 17m 27s | 7m 22s | 616.8 / 204.4 MiB | 90,675,546 bytes |
| 7 | 48m 08s | 43m 32s | 627.2 / 231.3 MiB | 562,323,989 bytes |
| 30 | 2h 55m 01s | 2h 55m 24s | 644.0 / 344.2 MiB | 2,368,272,316 bytes |
| 90 | Incomplete | Not started in original job | No completed report | Partial durable audit/checkpoints retained |

All three completed paired stages passed resource gates. Reported aggregate
financial/fill comparisons had zero differences; this does not establish that
both policies agree in July/August discrepancy windows outside the first 30 days.
Sequence preparation indexes futures across the pinned range even for short
selected periods. Process RSS excludes some filesystem usage; Cloud Run memory
also includes temporary files. The current gate adds twice ordering-database
size and requires the total below 3.5 GiB.

The 90-day job hit GitHub's six-hour job limit on September 9 around 09:09 UTC.
Its last logged durable sequence checkpoint was August 21 at 13:00 UTC, about
76.5 of 90 data days. There is no reported integrity or memory failure. The
second policy had not started. An extrapolation suggests roughly seven hours
per policy, but full measured results and Cloud Run acceptance remain pending.

## Infrastructure implemented for continuation

- Versioned preview/stable Terraform profiles are explicitly passed by the
  deployment workflow. Preview selects the verified 90-day catalog, 16 million
  decision ceiling, 1 vCPU / 4 GiB and a 24-hour worker timeout. Stable keeps
  its pilot and 30-minute timeout. These are per-execution resource settings,
  not a global limit on simultaneous jobs.
- Worker CPU/memory are parameters; timeout validation allows up to seven days
  for future measured workloads. The web service remains asynchronous and its
  HTTP timeout is independent of replay duration. Automatic task retries remain
  disabled; existing owner-scoped resume prevents overlapping executions.
- Benchmark policies run independently. Each gets four sequential segments,
  yielding after about three hours at a durable hourly checkpoint. Completed
  reports are persisted in GCS and reused by later segments. A final comparison
  requires both complete reports; an exhausted segment budget fails explicitly
  while retaining checkpoints. Timings on a resumed report cover its final
  attempt, not total runtime; segment continuation artifacts preserve timings.
- The dedicated long-recovery workflow reuses the original run's checkpoint IDs
  and unchanged engine fingerprint, so the sequence policy continues from its
  August checkpoint. It does not rerun the completed 1/7/30-day gates.

## Extending a period without replaying its whole history

`replay_extension.extend_checkpoint` forks a validated checkpoint and its audit
prefix into a new destination. The parent result stays immutable. It verifies
engine, rate files, parameters and market manifest; only the requested end may
change. It copies audited history and resumes calculation after the last saved
checkpoint, redoing at most the unsaved tail (normally less than one data hour).
Cash, positions, pending fills, accrual and cumulative performance continue.
Charts may be resampled; full financial audit rows are retained.

`scripts/extend-btc-backtest.py` exposes this for CLI outputs containing
`parameters.json`, `audit/` and `checkpoints/`, such as local benchmark outputs.
A regression compares an extended run's financial summary and every event and
valuation row to an uninterrupted run, including pending orders across midnight.

The current extension contract requires the same immutable market manifest.
Extending within the pinned 90 days works; accepting a new, longer manifest needs
explicit append-only prefix validation (same historical daily hashes and causal
seed/ordering metadata). The GUI Extend action and cloud job lineage API remain
future work. The current reader/catalog still cap data ranges at 90 days and
16 million decisions: configurable worker duration alone does not remove those
engine bounds. Longer history requires extending these bounded manifests and
validating audit-index/ordering-cache limits, not merely increasing a timeout.
