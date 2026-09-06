# Continuous BTC minute import: validation and deployment gate

Validated locally on 6 September 2026. This change has not been deployed.

## Approved implementation and full-window acceptance

The preserved test now uses `strategies/full-btc-long-gradual-1m-regular.json`:
100% BTC, regular USD futures accounting, full silver long gradual allocation
parameters, no direct-holding expense, no short book, 60-second execution. It
uses Deribit inverse USD quotes as an explicit regular-futures research price
proxy and Binance BTC/USDT at assumed parity. The original silver preset remains
unchanged. Legacy execution and a 1 bp fee sensitivity have separate saved presets.

| Run | Strategy | Direct holding | Intervals / missing |
| --- | ---: | ---: | ---: |
| Legacy regular close | +3,640.5349891% | +32.8013623% | 129,599 / 0 |
| Observed later fills, zero costs | +43.7335811% | +32.8013623% | 129,599 / 0 |
| Observed later fills, 1 bp fee/side | −39.8436771% | +32.8013623% | 129,599 / 0 |

There are zero zero-volume futures fills under observed execution. Actual
quantities remain held while orders await a genuine observation. The change
addresses an established stale-price/same-close execution artifact, but the
remaining performance is **research-only**: later candle closes are not executable
quotes, costs are illustrative, and contemporaneous USDT/USD has not been measured.
See [the implementation and investigation](BTC_EXECUTION_FIX_PROPOSAL.md).

The full deployed-engine path loads silver, gold, S&P 500 and BTC, computes the
requested BTC result plus comparison statistics, writes complete audit chunks,
and uses the exact worker incremental encoder. Local measured peak RSS is
**3,186.3 MiB** and initial result JSON **63.54 MiB**, within the unchanged
4,096 / 256 MiB limits. Runtime is 311.79 seconds. GCS uploads were replaced by
bounded local writes for this measurement; live Cloud Run/GCS acceptance is a
separate authenticated deployment check. The BTC audit has 285 compressed chunks
and portfolio attribution 181; both preserve all 129,599 rows.

Reports in [validation/btc-minute](validation/btc-minute) preserve the historical
`regular`, `inverse`, `delayed`, `stale-mark-control`, `combined-control`, and
`gui-profile` measurements, plus the new `observed`, `observed-worker`, and
`observed-fee-1bp` reports. These compact reports contain measured summaries;
complete audit ledgers are available through the immutable job audit download.

```bash
# Uses a NEW directory: audit objects are immutable.
python scripts/check-btc-minute-backtest.py --server-engine --chunk-output /tmp/btc-audit-new --report /tmp/btc-observed.json
python scripts/check-btc-minute-backtest.py --engine-only --fee-bps 1
# Explicit historical reproduction:
python scripts/check-btc-minute-backtest.py --engine-only --execution-model legacy_close
python scripts/check-btc-minute-backtest.py --engine-only --execution-model legacy_close --contract-type inverse
python scripts/check-btc-minute-backtest.py --engine-only --execution-model legacy_close --reactivity next_day
python scripts/check-btc-minute-backtest.py --engine-only --execution-model legacy_close --stale-mark-control
```

`--days N` is an explicit diagnostic restriction and is never applied implicitly.
`--audit-output` streams full engine JSONL gzip; `--chunk-output` produces the
manifest and original chunks. Stale-mark controls are synthetic sensitivities,
never a production feed correction or a claim about executable returns.

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
   patch generated copies. Copies were regenerated for this continuation. Asset preparation also synchronizes
   the tracked public HTML with the canonical root GUI to prevent the served page
   from lagging the tested code.
4. **Old fixture coverage assumptions also needed updating.** The portfolio
   coverage test still expected the 1,440-minute Kraken sample. Its expectations
   now match the active Binance 129,600-minute window. This is a data assertion
   update, not a calculation or sampling change.

The full repository Python discovery completed **142 tests with no failures and
3 explicit skips** (685.46 seconds): the opt-in full 1969 workbook regression,
and two legacy gold/oil portfolio tests because oil is outside the enabled market
set. This does not establish coverage for disabled commodities or the skipped
1969 golden workbook. Focused follow-up checks cover later audit/API/UI changes.
The normal build and artifact validation also completed. A focused follow-up of
59 execution, audit, API and cloud-workflow tests passed after the full discovery. The original 21 HTML
checks and six workbook tests pass, including streaming workbook equivalence,
minute timestamp preservation, and cost reconciliation.

New execution/audit tests cover later-only fills, no-trade inventory retention,
causality under future-price perturbation, partial volume fills, bid/ask costs,
missing-settlement errors, complete ledger/chunk reconstruction, NAV continuity,
checksums, partial failures/cancellation, ownership checks and streamed downloads.
The Cloud Run deployment workflow additionally checks this feature branch's full
BTC preset, exact SHA, resource limits, first/last audit chunks, detailed plots,
and a one-day workbook in the authenticated GUI. Those real-cloud results must
be read from the workflow; fake adapters and local tests are not substitutes.
A full 129,599-interval XLSX stress test completed in 372.79 seconds: 427,540,700
bytes, 1,711.9 MiB peak RSS in Node with a 1 GiB JS heap ceiling. All 285 check
worksheets report OK, and their interval counts sum to 129,599. This runs the
actual GUI export function and workbook module against stored audit chunks;
it is not a live Chromium measurement. A metadata-only ZIP entry avoids retaining
finished compressor buffers. See `validation/btc-minute/workbook-profile.json`.
No local Sites preview was started.

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

Reproduce with `python scripts/check-btc-minute-backtest.py --execution-model legacy_close --contract-type inverse`. It maps the saved
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


### First preview acceptance correction

The first published revision (`d774093086f4aacdb0e2f1566dad6b20fba6df3d`)
built and passed private health checks, but its multi-commodity GUI smoke timed
out before submission. The new participation input had minimum 0.001, step 1 and
default 100, which violates HTML step validity. It now accepts any percentage
from 0 through 100. The browser smoke reports invalid form controls immediately,
and an HTML regression verifies every numeric default against its bounds/step.
This correction changes form validity only, not execution or measured returns.
