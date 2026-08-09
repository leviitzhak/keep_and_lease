# Current unmerged work

_Update this file whenever active development moves to another branch or pull
request. Other documents link here instead of duplicating a change-specific PR or
branch._

## Active change set

- Status: in review and planned for completion before merge
- Pull request: [PR #22 — Complete generalized multi-commodity implementation](https://github.com/leviitzhak/keep_and_lease/pull/22)
- Moving branch: [`agent/multi-commodity-preview`](https://github.com/leviitzhak/keep_and_lease/tree/agent/multi-commodity-preview)
- Application version: `1.1`
- Exact deployed revision: read `Version … · commit …` in the preview GUI

## Scope being completed

- Generalized multi-commodity strategy and independent cash/Treasury sleeve.
- One canonical scoring pipeline and removal of the duplicate legacy formula path.
- Multi-commodity GUI, plots, statistics, decomposition, inspected-day audit, and
  parameter persistence.
- Detailed browser initialization diagnostics and startup improvements.
- Documentation and design for moving backtest computation from Pyodide in the
  browser to a server-side Python job API.
- Repeatable AWS infrastructure foundation, setup runbook, preview idle shutdown,
  and a managed-container scale-out alternative.

## Explicitly deferred

- The pure shorter-long/longer-short maturity multiplier is planned for a later
  branch after this change set is merged.
