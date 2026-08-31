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
development, GUI/API testing, and result-analysis environment. The local Sites
preview is not a deployment target. When reporting a push, state the GitHub
branch and full commit SHA, and distinguish the local Sites preview from the
deployed GCP preview URL.

### Required development and deployment sequence

1. Implement new GUI/API features in the Sites working copy.
2. Before any GCP preview deployment, run the local Sites preview and inspect or
   test the changes there, including strategy results and analysis when needed.
3. If the preview needs changes, modify and retest the Sites working copy
   locally. Do not push merely to preserve an intermediate workspace version,
   and do not use GCP preview deployments as the normal source-iteration loop.
4. Keep the tested version local until the user explicitly decides to preserve
   and deploy that workspace version. Only after that decision, transfer the
   tested patch onto a feature branch based on GitHub `master` and push it to
   GitHub. That push automatically deploys the GCP **preview** site.
5. Verify the GCP preview represents the pushed GitHub SHA. After explicit
   approval, merge the feature branch into GitHub `master`; that merge
   automatically deploys the GCP **stable** site.

Do not treat a Sites preview as a substitute for either GCP deployment, and do
not treat a GCP deployment as a substitute for the local Sites review stage.
Do not push, deploy, or merge an intermediate version unless the user has made
the corresponding decision. Do not implement Sites-from-GitHub deployment
automation unless requested.

### Required Sites checkout freshness check

Before editing application code in a ChatGPT Sites working copy, identify the
intended GitHub branch and commit, fetch GitHub, and verify that the Sites
checkout is based on that exact revision. If it is behind or based on a different
history, first transfer/rebase the intended patch onto a branch based on the
current GitHub revision; do not begin a new implementation on stale Sites code.
Preserve any existing uncommitted user work while doing so. Before starting a
local Sites preview, repeat the check and report the GitHub branch and SHA that
the preview represents.

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
