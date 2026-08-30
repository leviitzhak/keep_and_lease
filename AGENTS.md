# Repository working conventions

## Canonical repository

Treat `https://github.com/leviitzhak/keep_and_lease` as the canonical repository.
Base application changes on the current GitHub `master` branch and push feature
branches to that GitHub repository. Do not push application changes only to the
ChatGPT Sites internal `git.chatgpt-team.site` repository.

Before transferring work from a ChatGPT Sites working copy, fetch GitHub and
compare histories. If the histories are unrelated or commits were rewritten,
recreate or cherry-pick only the intended patch onto a branch based on GitHub
`master`; never push an unrelated Sites history to GitHub.

ChatGPT Sites and GitHub are separate repositories and are not automatically
synchronized. Treat the Sites working copy and its local preview as optional
pre-push validation: validate there first when useful, then transfer the tested
patch onto a branch based on GitHub `master` and push it to GitHub. The local
Sites preview is not a deployment target. Automatically deploying a hosted Sites
preview from GitHub is possible future work; do not assume that automation exists
or implement it unless requested. When reporting a push, state the GitHub branch
and full commit SHA, and distinguish the Git remote, the local Sites preview, and
the deployed GCP preview URL.

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
