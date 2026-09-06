# Continuous BTC minute import: validation and deployment gate

Validated locally on 6 September 2026. This change has not been deployed.

## Continuation: regular futures and deployment proposal

The requested test is now explicitly **regular futures**, using Deribit inverse
USD candle prices as a provisional regular-futures price proxy. The full GUI
reproduces **+3,640.5349891%** versus BTC holding **+32.8013623%**, with 129,599
one-minute intervals and zero missing returns. The earlier inverse result below
was also reproduced with the streamed audit path: **+3,637.3487166%**.

Stale/no-trade closes are a demonstrated contributor; the engine trades at
zero-volume candles whose underlying prices can be many minutes old. Delay and
causal synthetic-mark sensitivities reduce the anomaly but do not yield validated
economic returns. Read [the findings and proposed execution/output fix](BTC_EXECUTION_FIX_PROPOSAL.md)
for the measured controls, exact stale-price examples, remaining uncertainties,
and proposed CME regular-futures acquisition plan.

Complete audit-row streaming and reduced comparison-row retention are implemented
locally without changing strategy mathematics. The streamed regular audit peaks
at **652.9 MiB RSS**; the canonical GUI still peaks at **4,231.8 MiB** and returns
**821.97 MiB JSON**, exceeding both deployment limits. The full GUI profile took
273.58 seconds including repeated per-section output sizing. These are local
process measurements, not deployed worker acceptance tests; the worker's own
JSON encoding adds buffers. No resources or export UX have been changed.

Measured machine-readable reports are preserved in [validation/btc-minute](validation/btc-minute):
`regular.json`, `inverse.json`, `delayed.json`, `stale-mark-control.json`,
`combined-control.json`, and `gui-profile.json`. They record source window, mode,
interval counts, summaries, peak RSS and sensitivity settings. The regular and
inverse reports include bounded examples from the full audit stream; they are
not full ledger downloads. The harness can persist **every** complete row through
`--engine-only --audit-output /absolute/path/audit.jsonl.gz` when requested.

Reproduction:

```bash
python scripts/check-btc-minute-backtest.py --profile-output
python scripts/check-btc-minute-backtest.py --engine-only
python scripts/check-btc-minute-backtest.py --engine-only --contract-type inverse
python scripts/check-btc-minute-backtest.py --engine-only --reactivity next_day
python scripts/check-btc-minute-backtest.py --engine-only --stale-mark-control
python scripts/check-btc-minute-backtest.py --engine-only --stale-mark-control --reactivity next_day
```

`--days N` explicitly bounds a diagnostic window; it is never applied implicitly.
The optional stale-mark control changes only the freshly built research market
in memory, not the imported source files or production execution policy.

## Detailed validation caveats and their disposition

1. **The two roll-scoring failures existed on unchanged master.** Reproduced in
   an isolated export of `72ebc1c9479c142f109b0ef804f08502c479a19d`:
   `test_line_distance_changes_existing_score_relatively` expected `0.32`, but
   the current implementation returns `20.6`; and
   `test_zero_pure_maturity_strength_is_backward_compatible` expected `0.20`,
   but it returns `20.0`. These tests used the superseded multiplicative score.
   The documented SoftMax input is `base/rate_scale + signed adjustments`, hence
   `0.20/0.01 + 0.006/0.01 = 20.6`, and `0.20/0.01 = 20` with adjustments off.
   This continuation updates the test names/expectations to the current documented
   contract. **No scoring algorithm or allocation parameters were changed.**
2. **FastAPI dependencies were missing, not failing the backtest.** The previous
   environment could not import FastAPI for broader API discovery, so the prior
   32 Python tests did not validate HTTP jobs, caching, owner-scoped result access
   or durable worker behavior. Installed the pinned `requirements.txt` versions
   (`fastapi==0.116.1`, `httpx==0.28.1`, `uvicorn==0.35.0`). All **17 tests** in
   `tests.test_server_api` and `tests.test_cloud_jobs` now pass. Their cloud
   adapters are fakes: passing is not proof of a real GCP deployment or IAP access.
3. **Generated `public/` Python copies can be stale.** Several test modules prepend
   `public/` to `sys.path` or explicitly import a file there; others import root
   modules. Editing only root source and running discovery before asset preparation
   can exercise the old implementation, with import order also affecting reuse of
   `sys.modules`. Run **`npm run prepare:assets` after Python edits**, then run
   tests in a fresh Python process. Root files remain canonical; do not manually
   patch generated copies. Copies were regenerated for this continuation.
4. **Old fixture coverage assumptions also needed updating.** The portfolio
   coverage test still expected the 1,440-minute Kraken sample. Its expectations
   now match the active Binance 129,600-minute window. This is a data assertion
   update, not a calculation or sampling change.

Current targeted validation comprises 91 passing engine/data/payoff/streaming/API
tests, plus the 10 corrected roll-policy tests and the full active-market coverage
test, and 21 passing rendered-HTML tests. The streaming regression checks complete
ledger equality, projected comparison equality, inverse pending balances, both
reactivity modes, causal research controls and propagation of audit-sink failures.
The entire repository discovery/build/deployment suite has **not** been claimed
as passing. No local Sites preview was started and no private GCP verification
was performed, because the economic and output deployment gates remain open.

## Data and focused checks

- Binance source window: `[2026-06-06T00:00Z, 2026-09-04T00:00Z)`.
- 129,600 candles; all 129,599 adjacent timestamp differences are 60 seconds.
- Every downloaded ZIP matches Binance's published SHA-256. The deterministic
  normalized gzip is 2,797,394 bytes with SHA-256
  `1000e6465a027f05e3464230f6f1c766f28c39979f1970da4a5b747ef76cb7fa`.
- 32 focused Python tests passed (Binance ingestion, causal Treasury indices,
  provider-neutral intraday readers, BTC semantics, market-data store).
- 21 rendered-HTML tests passed, including the explicit USDT/USD caveat.
- Broader discovery initially hit stale generated public Python copies; those
  were regenerated. Two roll-scoring assertions also fail on unchanged master,
  independently reproduced in an isolated export of that commit. Local FastAPI
  dependencies are absent, so the complete API suite was not run.

## Historical full-period inverse GUI calculation

Reproduce with `python scripts/check-btc-minute-backtest.py --contract-type inverse`. It maps the saved
full-silver-long-gradual configuration to BTC-only, zero direct-holding expense,
inverse futures and a 60-second execution interval. No accounting or economic
parameters are fitted to the result.

The initial unindexed run completed with:

| Measurement | Result |
| --- | --- |
| First/last observable marks | 2026-06-06 00:01 to 2026-09-04 00:00 UTC |
| Return intervals | 129,599 |
| Missing futures-return intervals | 0 |
| Compounded strategy return | 3,637.3487166% |
| Direct-holding proxy return | 32.8013623% |
| Peak resident memory | 6,281.6 MiB |
| Serialized GUI result | 817.31 MiB |
| Runtime, including market build and result sizing | 741.18 seconds |

The return is **an anomalous research output, not a validated economic result**.
Possible contributors requiring audit include execution on stale/no-trade
Deribit candle closes, zero configured trading costs, cross-venue timing/basis,
the USDT/USD parity assumption, and the existing idle-BTC-collateral caveat.
None has yet been established as the cause or a complete explanation.

Treasury index optimization reduced observed market-build time from 138.9 to
27.5 seconds and total runtime from 741.18 to 267.37 seconds. The optimized
full run reproduced every summary figure above exactly, with the same 817.31
MiB result and 6,289.5 MiB peak memory. Causal lookup and accrual tests also match
the unindexed path exactly. The optimization does not address result size or
ledger memory retention.

## Deployment is gated

The existing Cloud Run worker has a 4 GiB memory limit and the configured result
limit is 256 MiB. This full-minute result exceeds both. No cloud limits were
increased and no preview replacement was triggered. Unreferenced content blobs
were transferred using the GitHub connector and hash-checked, but do not
constitute a published branch or deployed release.

Before activation on the deployed GUI, review the proposed single continuous
simulation with chunked/on-demand outputs, then validate causal execution and
rerun the full workload checks. Do not split calculations into independent date
windows that reset positions or change strategy history. The
full-resolution source data itself is small and complete; the blocker is the
calculation/output path rather than data availability.
