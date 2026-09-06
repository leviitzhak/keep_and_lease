# Continuous BTC minute import: validation and deployment gate

Validated locally on 6 September 2026. This change has not been deployed.

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

## Full-period canonical GUI calculation

Reproduce with `python scripts/check-btc-minute-backtest.py`. It maps the saved
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

Before activation on the deployed GUI, choose a bounded-result approach (for
example date-windowed calculations plus chunked/on-demand export ledgers), then
validate the suspicious performance and rerun the full workload checks. The
full-resolution source data itself is small and complete; the blocker is the
calculation/output path rather than data availability.
