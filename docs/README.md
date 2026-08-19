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
- [GUI specification](GUI_SPECIFICATION.md) — views and interaction.
- [Backtest engine](BACKTEST_ENGINE.md) — timing and accounting.
- [Data sources](DATA_SOURCES.md) — required inputs and derived fields.
- [TODO](TODO.md) — prioritized implementation work.
- [Changelog](CHANGELOG.md) — dated design decisions.
- [Roadmap](ROADMAP.md) — staged development plan.
- [Deployment and calculation architecture](DEPLOYMENT_ARCHITECTURE.md) — current-change pointer, server-computation migration, and production/preview hosting.
- [AWS setup](AWS_SETUP.md) — repeatable account provisioning, deployment prerequisites, idle shutdown, security, and operations.
- [Google Cloud Run setup](GOOGLE_CLOUD_RUN_SETUP.md) — proposed scale-to-zero web service, durable calculation Jobs, analytical data storage, security, costs, and migration.
 
## Working convention

Use these files as shared context across project chats. Durable changes should be reflected in the relevant specification and recorded in the design changelog. Unconfirmed values should remain marked as pending rather than being silently converted into defaults.
