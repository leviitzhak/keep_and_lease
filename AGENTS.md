# Repository working conventions

## Preview deployment after changes

After implementing and validating application changes, deploy the resulting
feature-branch commit for preview unless the user explicitly asks not to deploy.
Documentation-only changes do not require a new runtime deployment.

The authoritative preview path is the GitHub Actions workflow **Deploy Google
Cloud workloads** (`.github/workflows/deploy-google-cloud.yml`). Push the feature
branch, manually dispatch that workflow for the exact branch with
`deployment_target=preview`, and keep `allow_unauthenticated=false`.

The preview target is a separate private, IAP-protected Cloud Run service and
calculation Job, with separate Firestore job/cache collections. It must never
replace the stable working service. After the run, verify the authenticated health
check and that the deployed commit is the feature branch's exact SHA, then report
the workflow run and private preview URL.

The stable working target deploys automatically from `master`. A manual stable
deployment must use `deployment_target=stable` and is rejected unless the selected
ref is `master`.

Do not use the retired Render preview workflow. See
`docs/GOOGLE_CLOUD_RUN_SETUP.md` for the deployment and access runbook.
