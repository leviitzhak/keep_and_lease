# Current work

_Update this file whenever active development moves to another branch or pull
request. Other documents link here instead of duplicating a change-specific PR or
branch._

## Active change set

- Preview-verified on `agent/gui-subsecond-execution` in [PR #39](https://github.com/leviitzhak/keep_and_lease/pull/39): integrated the uploaded June 25
  trade dataset with the GUI and durable worker. Supports positive millisecond
  clocks, bounded UTC periods, actual capital/participation, streamed audit and
  CSV exports. See [BTC_SUBSECOND_GUI.md](BTC_SUBSECOND_GUI.md). Local execution
  and regression checks pass (50 Python, 36 JavaScript/HTML, production build);
  GCP preview deployment and rendered GUI acceptance passed at
  `ef0000cb294c622d8e8d40973b8c2cb1ca065042` in
  [workflow 34149398811](https://github.com/leviitzhak/keep_and_lease/actions/runs/34149398811).
  Both 500 ms and 1 ms clocks, GCS/local financial equivalence, full CSV,
  audit access, hover and the multi-commodity baseline passed.
  No merge into master has been performed.


- Previously merged: the one-day raw-trade research replay, Parquet/GCS storage
  pilot, selectable UTC backtest periods and connection-recovery changes were
  preview-verified and merged into `master` in
  [PR #38](https://github.com/leviitzhak/keep_and_lease/pull/38), merge commit
  `608aa6027e77474445c69ad221f33e3f98e953b6`. See
  [BTC_TRADE_PILOT.md](BTC_TRADE_PILOT.md) and
  [BTC_TRADE_STORAGE.md](BTC_TRADE_STORAGE.md). That merged revision used minute data in the GUI.
  The owner granted the operator bucket create/read access. The bounded GCS
  upload/replay passed for all 5,739,608 events and both complete audit hashes,
  with an 8 MiB remote-read cache per open partition. The measured capacity
  replay took 145.35 seconds from GCS versus 87.34 seconds locally. The ordered
  preparation plan for 90-day execution is in `BTC_TRADE_STORAGE.md`;
  multi-day trade-worker/GUI integration remains outstanding.
  Explicit UTC backtest start/end controls now restrict strategy computation;
  see [BACKTEST_PERIOD.md](BACKTEST_PERIOD.md).
  The latest follow-up fixes interrupted server-job polling and disables the
  unavailable Cloud Run browser fallback; see [BTC_CONNECTION_RECOVERY.md](BTC_CONNECTION_RECOVERY.md).
  The original user connection failure has no job ID/HTTP status, so its
  underlying cause remains unconfirmed.
  The merge intentionally used `[skip ci]` at the user's request, so no stable
  deployment ran. Documentation-only pushes are now excluded from the deployment
  workflow; mixed application/documentation changes continue to deploy.

- Previous change status: the approved regular BTC execution and on-demand audit
  redesign was validated in private preview and merged in PR #37. Full 60-second execution retains 129,599
  intervals: +43.7336% at zero costs versus +32.8014% direct holding; an illustrative
  1 bp fee per side changes the strategy result to −39.8437%. The original silver
  strategy and all three BTC presets are preserved in `strategies/`.
  The full worker path measures 3,186.3 MiB RAM and 63.54 MiB initial JSON under
  the unchanged 4 GiB / 256 MiB limits. Complete ledgers are stored as immutable
  audit chunks. See [the findings and implementation](BTC_EXECUTION_FIX_PROPOSAL.md)
  and [validation/caveats](BTC_MINUTE_VALIDATION.md).
  The user approved merging this change into master, with the follow-up
  visualization, progress/cancellation and order-book research tasks in `TODO.md`.
- Previous branch: `agent/btc-binance-minute-data`
- Completed review and deployment evidence: [merged PR #37](https://github.com/leviitzhak/keep_and_lease/pull/37).
- Previous generalized application review: [PR #22 — Complete generalized multi-commodity implementation](https://github.com/leviitzhak/keep_and_lease/pull/22)
- Render services' configured source branch: [`agent/fixed-render-preview-deploys`](https://github.com/leviitzhak/keep_and_lease/tree/agent/fixed-render-preview-deploys). Deploy hooks override this default with the exact commit pushed to the current implementation branch.
- Application version: `1.3`
- First verified Cloud Run revision:
  `fc4400e9a18a4e68846f250b64efee7fc0429ad7`
- Last documented private stable commit verified by the private operator:
  `08b583696f52314b54e3be6bd6f1d39497b10a1c` (same application content as
  `a3d457516bda8b74a8b23db3f5bb2f491296ea10`)
- First successful autonomous private health/GUI run:
  [Cloud agent operator #2](https://github.com/leviitzhak/keep_and_lease/actions/runs/32643381753)
- Cloud Run URL: <https://keep-and-lease-web-vfk2j2rgoq-zf.a.run.app>. Anonymous
  requests return `403 Forbidden`; use the authenticated Cloud SDK proxy until
  selected-user browser authentication is implemented.
- Private GCP preview URL:
  <https://keep-and-lease-preview-web-vfk2j2rgoq-zf.a.run.app>. Normal
  feature-branch deployments run an authenticated GUI and multi-commodity smoke
  test; the keyless cloud-agent operator can independently select this target and
  enforce its exact deployed SHA.
- For the separate Render preview, read `Version … · commit …` in the [preview GUI](https://keep-and-lease-fixed-preview.onrender.com), or compare [`build-info.json`](https://keep-and-lease-fixed-preview.onrender.com/build-info.json) with the API [`engine_commit`](https://keep-and-lease-fixed-preview-api.onrender.com/api/v1/health).

## Scope being completed

- Generalized multi-commodity strategy and independent cash/Treasury sleeve.
- Independent shorter-long/longer-short pure-maturity scoring multiplier.
- One canonical scoring pipeline and removal of the duplicate legacy formula path.
- Multi-commodity GUI, plots, statistics, decomposition, inspected-day audit, and
  parameter persistence.
- Detailed browser initialization diagnostics and startup improvements.
- A versioned server-side CPython job API, Docker image, browser adapter, and
  explicit Pyodide fallback using the same calculation modules and result shape.
- Repeatable AWS infrastructure foundation, setup runbook, preview idle shutdown,
  and a managed-container scale-out alternative.
- A provisioned fixed two-service Render preview and deploy-hook workflow that
  deploys and verifies the same commit on the GUI and computation API. The first
  complete synchronized deployment was validated on 2026-08-18.
- A provisioned Google Cloud foundation plus implemented durable Firestore/GCS job
  persistence, scale-to-zero web service, one-shot 4 GiB calculation Job, separate
  containers, workload Terraform, and GitHub OIDC deployment workflow.
- A branch-restricted, keyless GitHub OIDC operator that can collect non-secret
  health/build evidence, render the private GUI, and run sanitized fixed-fixture
  API smoke tests against stable or preview without exposing a Google credential
  to Codex.
- BTC-only intraday execution/rebalancing at whole multiples of the detected
  one-minute market resolution, using causal latest-observable Treasury accrual.
- A documented direct Cloud Run IAP migration that keeps the existing
  internet-reachable `run.app` URL, allowlists approved Google users and machine
  identities, preserves the keyless operator, and keeps anonymous access disabled.
- Cross-session restoration of the latest completed durable backtest, complete
  rate-change plots, explicit empty-plot states, and canonical loading of the
  three GUI-selectable materialized markets.

## Explicitly deferred

- Complete the one-time no-organization External OAuth setup, manually add approved
  humans plus the operator and deployment identities in the Google Cloud IAP
  policy, set the two `GCP_IAP_*` repository variables, apply the foundation delta,
  deploy direct IAP, and verify allowed, denied, operator, and deployment paths
  before removing direct operator invocation. Anonymous access remains disabled.
- Cloud Run numerical/cancellation/replacement acceptance tests and capacity
  measurements remain deployment work. The fixed Render services, deploy-hook
  secrets, and public URL variables are configured; only the optional
  Render-native health-check paths remain to be entered in the current services.
- Versioned Parquet/DuckDB/Arrow cloud inputs and cloud day inspection remain after
  the durable execution proof; the first worker image keeps the current input set.
