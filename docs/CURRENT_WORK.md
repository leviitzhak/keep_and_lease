# Current unmerged work

_Update this file whenever active development moves to another branch or pull
request. Other documents link here instead of duplicating a change-specific PR or
branch._

## Active change set

- Status: in review and planned for completion before merge
- Pull request: [PR #22 — Complete generalized multi-commodity implementation](https://github.com/leviitzhak/keep_and_lease/pull/22)
- Current implementation and fixed-preview trigger branch: [`agent/multi-commodity-preview`](https://github.com/leviitzhak/keep_and_lease/tree/agent/multi-commodity-preview)
- Render services' configured source branch: [`agent/fixed-render-preview-deploys`](https://github.com/leviitzhak/keep_and_lease/tree/agent/fixed-render-preview-deploys). Deploy hooks override this default with the exact commit pushed to the current implementation branch.
- Application version: `1.2`
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

## Explicitly deferred

- The pure shorter-long/longer-short maturity multiplier is planned for a later
  branch after this change set is merged.
- Durable cross-restart job storage, authentication, production deployment, and
  capacity measurements remain deployment work. The fixed Render services,
  deploy-hook secrets, and public URL variables are configured; only the optional
  Render-native health-check paths remain to be entered in the current services.
