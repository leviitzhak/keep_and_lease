# Repository working conventions

## Preview deployment after changes

Every push to a non-`master` branch automatically deploys that exact commit to
the shared preview target. Every push to `master` automatically deploys that exact
commit to stable. Because the workflow intentionally covers every branch push,
documentation-only pushes also redeploy their corresponding target.

The authoritative preview path is the GitHub Actions workflow **Deploy Google
Cloud workloads** (`.github/workflows/deploy-google-cloud.yml`). Push any
non-`master` branch; the push automatically deploys that exact commit to the
preview target with private access. Manual dispatch remains available for reruns,
with `deployment_target=preview` and `allow_unauthenticated=false`.

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
