# Current work

_Update this file whenever active development moves to another branch or pull
request. Other documents link here instead of duplicating a change-specific PR or
branch._

## Active change set

- Status: pure-maturity scoring multiplier implemented, verified, published, and
  deployed to the private Google Cloud preview; review and merge remain
- Integration: based on the deployed `master` revision; not yet merged
- Current implementation branch: [`agent/pure-maturity-multiplier`](https://github.com/leviitzhak/keep_and_lease/tree/agent/pure-maturity-multiplier)
  (published; not yet merged)
- Previous generalized application review: [PR #22 — Complete generalized multi-commodity implementation](https://github.com/leviitzhak/keep_and_lease/pull/22)
- Render services' configured source branch: [`agent/fixed-render-preview-deploys`](https://github.com/leviitzhak/keep_and_lease/tree/agent/fixed-render-preview-deploys). Deploy hooks override this default with the exact commit pushed to the current implementation branch.
- Application version: `1.3`
- First verified Cloud Run revision:
  `fc4400e9a18a4e68846f250b64efee7fc0429ad7`
- Current private Cloud Run deployment commit:
  `08b583696f52314b54e3be6bd6f1d39497b10a1c` (same application content as
  `a3d457516bda8b74a8b23db3f5bb2f491296ea10`; the extra commit only supplied the
  temporary private-deployment trigger)
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

## Explicitly deferred

- Cloud Run numerical/cancellation/replacement acceptance tests and capacity
  measurements remain deployment work. Direct Cloud Run IAP is the recommended
  next browser-access step. Anonymous access remains deferred until application
  authentication, ownership, quotas, and spending/abuse controls exist. The fixed
  Render services, deploy-hook secrets, and public URL variables are configured;
  only the optional Render-native health-check paths remain to be entered in the
  current services.
- Versioned Parquet/DuckDB/Arrow cloud inputs and cloud day inspection remain after
  the durable execution proof; the first worker image keeps the current input set.
