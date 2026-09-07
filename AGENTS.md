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
synchronized. The local Sites preview currently has known compatibility gaps
that are intentionally left unfixed. Do not start or use the local Sites preview
as part of the normal development, validation, or deployment workflow unless the
user explicitly asks to work on that compatibility. The deployed GCP preview is
the authoritative GUI/API preview. When reporting a push, state the GitHub branch
and full commit SHA and identify the deployed GCP preview URL.

### Required development and deployment sequence

1. Implement the change on a feature branch based on the current GitHub `master`
   and run relevant local checks that do not require a Sites preview.
2. Do not run the local Sites preview before deployment. Once a coherent change
   is ready to preview, push the feature branch to GitHub unless the user has
   requested local-only work or no deployment. The push automatically deploys
   that exact commit to the GCP **preview** target.
3. Record the pushed branch and full commit SHA. When practical and not
   resource-consuming, wait for **Deploy Google Cloud workloads** to reach a
   terminal state rather than leaving the deployment unchecked.
4. After a successful deployment, test the deployed GUI at the private preview
   URL reported by the workflow. Verify the displayed commit is the pushed SHA,
   the server engine is ready, and a representative strategy completes. The
   workflow's authenticated rendered-GUI and multi-commodity smoke test provides
   the baseline check; perform an additional interactive check when authenticated
   access is available and doing so is inexpensive. If waiting or deployed-GUI
   access is unavailable, report the unverified step explicitly.
5. If the preview needs changes, modify the feature branch and repeat the push,
   deployment wait, and deployed-GUI test. After explicit approval, merge the
   feature branch into GitHub `master`; that merge automatically deploys the GCP
   **stable** target.

Do not push or deploy an incomplete intermediate state merely to preserve it, and
do not merge a feature branch before preview approval. Do not publish a Sites
version as a substitute for the GCP preview and do not spend time repairing local
Sites compatibility unless requested.

### Required Sites checkout freshness check

Before editing application code in a ChatGPT Sites working copy, identify the
intended GitHub branch and commit, fetch GitHub, and verify that the Sites
checkout is based on that exact revision. If it is behind or based on a different
history, first transfer/rebase the intended patch onto a branch based on the
current GitHub revision; do not begin a new implementation on stale Sites code.
Preserve any existing uncommitted user work while doing so. This checkout
freshness check does not authorize or require starting a local Sites preview.

## Documentation updates are required for implementation changes

Whenever implementing a change or addition, update the relevant documentation in
the same patch. Documentation is part of the implementation's definition of done,
not a separate follow-up task.

Review and update every document affected by the change, including, as
applicable:

- user-facing behavior, configuration, parameters, formulas, and data sources;
- architecture, API, deployment, and operational runbooks;
- current implementation and project-state documents; and
- TODO entries whose scope or status changed.

Documentation must describe the code and deployment state that actually exists.
Do not leave obsolete behavior documented or completed work listed as pending.


## Documentation updates are required for implementation changes

Whenever implementing a change or addition, update the relevant documentation in
the same patch. Documentation is part of the implementation's definition of done,
not a separate follow-up task.

Review and update every document affected by the change, including, as
applicable:

- user-facing behavior, configuration, parameters, formulas, and data sources;
- architecture, API, deployment, and operational runbooks;
- current implementation and project-state documents; and
- TODO entries whose scope or status changed.

Documentation must describe the code and deployment state that actually exists.
Do not leave obsolete behavior documented or completed work listed as pending.

## Preview deployment after changes

Every push containing application, deployment, infrastructure, or data changes
to a non-`master` branch automatically deploys that exact commit to the shared
preview target. The corresponding pushes to `master` deploy to stable. A push
changing only `docs/**`, Markdown files, or `.cloud-agent/requests/**` is ignored
by the deployment workflow. A mixed commit still deploys. The diagnostic request
exception prevents an operator check from replacing or racing the preview
revision it is intended to inspect.

The authoritative preview path is the GitHub Actions workflow **Deploy Google
Cloud workloads** (`.github/workflows/deploy-google-cloud.yml`). Push any
non-`master` branch; the push automatically deploys that exact commit to the
preview target with private access. Manual dispatch remains available for reruns,
with `deployment_target=preview` and `allow_unauthenticated=false`.

The preview target is a separate private, IAP-protected Cloud Run service and
calculation Job, with separate Firestore job/cache collections. It must never
replace the stable working service. When practical, follow the workflow until it
finishes and use its authenticated health, rendered-GUI, and strategy smoke-test
results to validate the deployment. Then test the workflow-reported private
preview URL directly when authenticated access is available, verify that it shows
the feature branch's exact SHA, and report the workflow run and preview URL.

For an independent working-agent check of the private deployed GUI, use the
keyless **Cloud agent operator** described in `docs/CLOUD_AGENT_ACCESS.md`. Submit
only a bounded request on the permanent `agent/cloud-autonomous-access` branch,
set `target` to `preview`, and set `expected_commit` to the full deployed SHA.
Read the workflow result and sanitized GUI evidence through the GitHub connector.
The operator branch must first contain the current operator workflow, and the GCP
foundation/IAP policies must grant its dedicated service account access to the
preview service. Never copy an identity token or Google credential into the
workspace, repository, workflow artifact, or chat.

The stable working target deploys automatically from `master`. A manual stable
deployment must use `deployment_target=stable` and is rejected unless the selected
ref is `master`.

Do not use the retired Render preview workflow. See
`docs/GOOGLE_CLOUD_RUN_SETUP.md` for the deployment and access runbook.

## Stable deployment verification

After a user-approved merge into `master`, stable deployment does not need to be
verified again: the preview has normally already been verified. Do not routinely
wait for the stable deployment workflow or repeat stable health/GUI checks unless
the user explicitly requests stable verification. This exception applies to the
stable target; the preview verification requirements above remain in effect.
Existing automated stable deployment checks may still run without agent follow-up.
