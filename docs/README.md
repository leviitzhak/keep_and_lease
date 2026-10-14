# Keep & Lease Documentation

The GUI displays an application version and deployed commit. Versions follow
the branch lineage: the main line is `1`, a branch from it is `1.1`, and a
branch from `1.1` is `1.1.1`. Commits within a branch do not change its version.

Start with [PROJECT_STATE.md](PROJECT_STATE.md).

## Documents

- [Project state](PROJECT_STATE.md) — current scope, decisions, and priorities.
- [Current work](CURRENT_WORK.md) — updatable pointer to the active unmerged branch, PR, and completion scope.
- [Strategy](STRATEGY.md) — portfolio construction and trading rules.
- [Scoring](SCORING.md) — contract ranking formulas.
- [Parameters](PARAMETERS.md) — configuration reference.
- [BTC PRD exposure-band plan](BTC_PRD_EXPOSURE_BAND_PLAN.md) — proposed multi-pair opening/closing strategy, exposure/leverage accounting and decisions required before implementation.
- [BTC PRD raw-data preflight](BTC_PRD_BAND_DATA_PREFLIGHT.md) — verified input coverage, maturity eligibility and a preliminary delayed strict-through quote screen; not a portfolio backtest.
- [BTC PRD execution calibration](BTC_PRD_EXECUTION_CALIBRATION.md) — first chronological threshold grid, strict-through unit experiments, execution audit and current-leg ladder tests; not funded portfolio optimization.
- [BTC PRD extended calibration](BTC_PRD_EXTENDED_CALIBRATION.md) — proxy cost reconciliation, separate realized/unrealized results, fee rebates, 1 ms comparisons and longer-history method.
- [Adaptive PRD and competing-market research](BTC_PRD_ADAPTIVE_MARKET_RESEARCH.md) — proposed live location/gap updates, held-inventory transitions, competing-agent simulator feasibility and verified trade-workload sizing.
- [Offline BTC PRD testing](BTC_PRD_OFFLINE_TESTING.md) — cache preparation, exact replay commands, measured runtime and local environment sizing.
- [BTC maturity-separation history](BTC_MATURITY_SEPARATION_HISTORY.md) — full saved catalog, daily minima, monthly tables and exact windows passing 25%; metadata feasibility, not execution results.
- [Empirical BTC lease execution](EMPIRICAL_LEASE_EXECUTION.md) — waiting-time/slippage calibration, funded execution budgets and the separate ten-day evaluation.
- [GUI specification](GUI_SPECIFICATION.md) — views and interaction.
- [Backtest engine](BACKTEST_ENGINE.md) — timing and accounting.
- [Data sources](DATA_SOURCES.md) — required inputs and derived fields.
- [TODO](TODO.md) — prioritized implementation work.
- [Changelog](CHANGELOG.md) — dated design decisions.
- [Roadmap](ROADMAP.md) — staged development plan.
- [Deployment and calculation architecture](DEPLOYMENT_ARCHITECTURE.md) — current-change pointer, server-computation migration, and production/preview hosting.
- [AWS setup](AWS_SETUP.md) — repeatable account provisioning, deployment prerequisites, idle shutdown, security, and operations.
- [Google Cloud Run setup](GOOGLE_CLOUD_RUN_SETUP.md) — provisioned foundation,
  implemented scale-to-zero web service and durable calculation Job, deployment,
  security boundaries, acceptance work, and analytical-data migration.
- [Cloud-agent access](CLOUD_AGENT_ACCESS.md) — keyless, branch-restricted private
  GUI/API diagnostics through GitHub OIDC.
 
## Working convention

Use these files as shared context across project chats. Durable changes should be reflected in the relevant specification and recorded in the design changelog. Unconfirmed values should remain marked as pending rather than being silently converted into defaults.
