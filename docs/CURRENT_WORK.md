# Current work

_Update this file whenever active development moves to another branch or pull
request. Other documents link here instead of duplicating a change-specific PR or
branch._

## Active change set

- Status: keyless cloud-agent GUI/API access activated and verified end-to-end
- Integration: unmerged; production deployment remains on `master`
- Current implementation branch: [`agent/cloud-autonomous-access`](https://github.com/leviitzhak/keep_and_lease/tree/agent/cloud-autonomous-access)
- Previous generalized application review: [PR #22 — Complete generalized multi-commodity implementation](https://github.com/leviitzhak/keep_and_lease/pull/22)
- Render services' configured source branch: [`agent/fixed-render-preview-deploys`](https://github.com/leviitzhak/keep_and_lease/tree/agent/fixed-render-preview-deploys). Deploy hooks override this default with the exact commit pushed to the current implementation branch.
- Application version: `1.3`
- First verified Cloud Run revision:
  `fc4400e9a18a4e68846f250b64efee7fc0429ad7`
- Current production deployment commit verified by the private operator:
  `08b583696f52314b54e3be6bd6f1d39497b10a1c`
- First successful autonomous private health/GUI run:
  [Cloud agent operator #2](https://github.com/leviitzhak/keep_and_lease/actions/runs/32643381753)
- Exact deployed revision: read `Version … · commit …` in the [preview GUI](https://keep-and-lease-fixed-preview.onrender.com), or compare [`build-info.json`](https://keep-and-lease-fixed-preview.onrender.com/build-info.json) with the API [`engine_commit`](https://keep-and-lease-fixed-preview-api.onrender.com/api/v1/health).

## Scope being completed

- Generalized multi-commodity strategy and independent cash/Treasury sleeve.
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

## Explicitly deferred

- The pure shorter-long/longer-short maturity multiplier is planned for a later
  change set.
- Investigate the initial private GUI's two HTTP 404 console messages and
  `portfolio_series` null-reference page error. The page still renders with HTTP
  200 and reports the server engine ready; the operator artifact preserves the
  diagnostic without exposing credentials.
- Cloud Run numerical/cancellation/replacement acceptance tests and capacity
  measurements remain deployment work. Direct Cloud Run IAP is the recommended
  next browser-access step. Anonymous access remains deferred until application
  authentication, ownership, quotas, and spending/abuse controls exist. The fixed
  Render services, deploy-hook secrets, and public URL variables are configured;
  only the optional Render-native health-check paths remain to be entered in the
  current services.
- Versioned Parquet/DuckDB/Arrow cloud inputs and cloud day inspection remain after
  the durable execution proof; the first worker image keeps the current input set.
