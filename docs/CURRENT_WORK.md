# Current work

_Update this file whenever active development moves to another branch or pull
request. Other documents link here instead of duplicating a change-specific PR or
branch._

## Active change set

- Status: GUI stabilization is implemented on top of the market-data SQLite/IAP
  branch; separate stable/preview Cloud Run targets are being deployed and verified
- Active branch: `agent/gui-stabilization`
- Previous generalized application review: [PR #22 — Complete generalized multi-commodity implementation](https://github.com/leviitzhak/keep_and_lease/pull/22)
- Render services' configured source branch: [`agent/fixed-render-preview-deploys`](https://github.com/leviitzhak/keep_and_lease/tree/agent/fixed-render-preview-deploys). Deploy hooks override this default with the exact commit pushed to the current implementation branch.
- Application version: `1.3`
- First verified Cloud Run revision:
  `fc4400e9a18a4e68846f250b64efee7fc0429ad7`
- Current private Cloud Run deployment commit verified by the private operator:
  `08b583696f52314b54e3be6bd6f1d39497b10a1c` (same application content as
  `a3d457516bda8b74a8b23db3f5bb2f491296ea10`)
- First successful autonomous private health/GUI run:
  [Cloud agent operator #2](https://github.com/leviitzhak/keep_and_lease/actions/runs/32643381753)
- Cloud Run URL: <https://keep-and-lease-web-vfk2j2rgoq-zf.a.run.app>. Anonymous
  requests return `403 Forbidden`; use the authenticated Cloud SDK proxy until
  selected-user browser authentication is implemented.
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
  API smoke tests without exposing a Google credential to Codex.
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
