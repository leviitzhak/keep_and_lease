# Repository working conventions

## Preview deployment after changes

After implementing and validating application changes, deploy the resulting
feature-branch commit for preview unless the user explicitly asks not to deploy.
Documentation-only changes do not require a new runtime deployment.

The authoritative preview path is the GitHub Actions workflow **Deploy Google
Cloud workloads** (`.github/workflows/deploy-google-cloud.yml`). Push the feature
branch, manually dispatch that workflow for the exact branch, and keep
`allow_unauthenticated=false`.

This workflow updates the same private, IAP-protected Cloud Run service used by
production; it does not create an isolated preview service. Before dispatching,
state that the selected branch temporarily replaces the deployed revision. After
the run, verify the authenticated health check and that the deployed commit is the
feature branch's exact SHA, then report the workflow run and private preview URL.
Restore `master` by dispatching the same workflow on `master` when the preview is
finished or whenever the user requests restoration.

Do not use the retired Render preview workflow. See
`docs/GOOGLE_CLOUD_RUN_SETUP.md` for the deployment and access runbook.
