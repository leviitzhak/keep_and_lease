# Keep & Lease — Project State

_Last updated: 2026-09-07_

## Purpose

Build an interactive research and backtesting application for strategies that allocate among commodity ETFs, commodity futures across maturities, and Treasury/cash instruments. The application should expose all economically meaningful parameters in a GUI and make the daily decisions auditable.

## Current scope

- Optional bounded BTC trade replay: June 25 uploaded data, millisecond decision
  clocks, GCS worker audit, charts and full valuation CSV. See
  [BTC_SUBSECOND_GUI.md](BTC_SUBSECOND_GUI.md) and `CURRENT_WORK.md` for preview status.

- Commodities: silver, gold, S&P 500, and BTC through the same registered-market
  framework, with other data-backed commodities remaining extensible.
- Cash/Treasuries: treated as another investable curve, using interest rates rather than lease rates.
- Instruments: physical-backed ETFs, futures at several maturities, and Treasury/cash positions.
- Outputs: interval positions, returns, cumulative returns, diagnostics, contract-level
  inspection and scatter plots. Complete minute ledgers are stored in immutable
  audit chunks with on-demand GUI detail, full archive and XLSX downloads.
- BTC acceptance: the saved full-long gradual regular strategy preserves all
  129,599 intervals. Local full worker RSS / initial JSON are 3,186.3 / 63.54 MiB.
  Zero-cost return is +43.73%; a 1 bp fee/side yields −39.84%, demonstrating cost
  sensitivity. See `BTC_MINUTE_VALIDATION.md`; no profitability claim is established.

## Core design decisions

1. Legacy daily signals execute at the same close and earn the next interval.
   Observed regular long-only BTC uses later genuine observations for fills and
   retains actual quantities while orders await execution; stale closes only value
   inventory. Both models are explicitly selectable for research.
2. Long and short futures books may coexist at different maturities.
3. A long futures contract remains eligible only when its lease rate satisfies the long-side eligibility rule.
4. A short futures contract remains eligible only when its lease rate satisfies the short-side eligibility rule; a maturity bonus must not make an otherwise ineligible contract tradable.
5. Contract ranking combines an existing economic score with a relative maturity/curve adjustment.
6. The maturity adjustment is based on a linear boundary in `(maturity, lease rate)` space.
7. Treasury contract analysis uses the same plots and ranking concepts, replacing lease rate with interest rate.
8. Contract tables belong in the inspected-day view, not as hard-coded data in general statistics.
9. General statistics should provide comparable scatter plots for every commodity.

## Canonical documents

- [STRATEGY.md](STRATEGY.md): portfolio construction and trading rules.
- [SCORING.md](SCORING.md): score definitions and maturity-line adjustment.
- [PARAMETERS.md](PARAMETERS.md): GUI/configuration parameters.
- [GUI_SPECIFICATION.md](GUI_SPECIFICATION.md): application behavior and visual requirements.
- [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md): timing, accounting, and simulation assumptions.
- [DATA_SOURCES.md](DATA_SOURCES.md): required market data and derived quantities.
- [TODO.md](TODO.md): prioritized implementation work.
- [CHANGELOG.md](CHANGELOG.md): durable design decisions.
- [ROADMAP.md](ROADMAP.md): staged development plan.
- [DEPLOYMENT_ARCHITECTURE.md](DEPLOYMENT_ARCHITECTURE.md): current implementation pointer, planned server-computation API, and hosting design.
- [CURRENT_WORK.md](CURRENT_WORK.md): single updatable pointer to the active unmerged change set.

## Current implementation state

1. Registered commodity markets run as independent sleeves through the same engine.
2. Global settings can be overridden independently for every commodity.
3. A generic aggregator combines commodity sleeves and an independent cash/Treasury sleeve under the selected rebalancing schedule.
4. `maturity_scoring.py` is the single formula implementation used by trading and inspected-day diagnostics.
5. The GUI includes synchronized inspection, score audits, per-commodity and Treasury scatters, hierarchical decomposition, statistics, and versioned parameter sets.
6. Unavailable or corrupt market archives are isolated and reported only if the user selects the affected commodity.
7. The optional pure-maturity multiplier independently favors shorter long and
   longer short contracts; zero strength preserves the previous scoring.
8. A queued `/api/v1` CPython service now calls the same canonical Python engine,
   while the GUI's v13 adapter preserves the v12 Pyodide worker as an explicit or
   automatic fallback.
9. The fixed Render GUI and API services are provisioned. The GitHub deploy-hook
   workflow, repository secrets, and public URL variables are configured and have
   verified a synchronized deployment from one exact commit. Render-native health
   check paths remain to be entered on the two existing services.
10. The Google Cloud foundation is provisioned. Durable Firestore jobs, immutable
    compressed GCS results, a scale-to-zero Cloud Run web service, one-shot
    calculation Job, containers, Terraform, and OIDC deployment workflow are
    implemented and deployed. The `agent/pure-maturity-multiplier` revision was
    temporarily exposed for GUI inspection, then returned to private Cloud Run IAM
    access on 2026-08-21; unauthenticated requests now return `403`. The authenticated
    health check and private operator GUI path work; bounded calculation,
    cancellation, and replacement acceptance tests remain. Direct IAP Terraform,
    manual human/machine allowlist instructions, and dual-mode keyless workflow
    audiences are implemented; one-time OAuth activation, manual policy setup, and
    acceptance verification remain.
    Anonymous calculation access remains disabled.
11. BTC-only strategies accept execution/rebalancing frequencies at whole
    multiples of the detected intraday market-data resolution. Intraday Treasury
    valuation accrues at the latest observable yield without future backfill or
    interpolation.
    The default BTC spot feed is continuous Binance BTC/USDT minute candles
    over 6 June–3 September 2026, explicitly used as a USD proxy at assumed
    USDT/USD parity. Kraken sample days and interchangeable tick adapters remain
    available; historical FX correction is still a research follow-up.
12. The local Sites preview is intentionally outside the normal validation path
    while its compatibility gaps remain unfixed. Feature branches deploy to the
    private GCP preview, whose built-in smoke test and bounded keyless operator can
    verify the exact deployed SHA and rendered GUI.

## Active review and planned architecture

- [CURRENT_WORK.md](CURRENT_WORK.md) is the maintained pointer to the current
  implementation and completion scope.
- The exact preview revision is the version and commit displayed by the deployed GUI.
- The first server-computation implementation sends the existing parameter JSON
  to a CPython job runner and returns the unchanged result JSON. Deployment and
  equivalence benchmarking remain before it becomes the accepted production path.
  See [DEPLOYMENT_ARCHITECTURE.md](DEPLOYMENT_ARCHITECTURE.md).
- The two-host AWS prototype now has a plan-first setup runbook and Terraform foundation in [AWS_SETUP.md](AWS_SETUP.md); it must not be treated as production-ready until the listed application, authentication, role-splitting, and deployment tasks are complete.
- [RENDER_FIXED_PREVIEW.md](RENDER_FIXED_PREVIEW.md) is the reproducible setup,
  verification, failure-recovery, and rebuild runbook for the shared two-service
  Render preview.
- The live fixed preview is <https://keep-and-lease-fixed-preview.onrender.com>;
  the API reports its running revision at
  <https://keep-and-lease-fixed-preview-api.onrender.com/api/v1/health>.

## Source-of-truth policy

This file records the current high-level state. Detailed formulas and behavior belong in the linked documents. When a design decision changes, update the relevant detailed document and add a dated entry to `CHANGELOG.md`.
