# Fixed Render preview deployment

This runbook creates one persistent preview GUI and one persistent preview
calculation API. GitHub Actions deploys the same commit to both services through
their deploy hooks and verifies the deployed revisions before publishing the
preview addresses.

This is deliberately a **shared fixed preview**, not a per-pull-request preview.
The latest deployment replaces the previous one. It avoids the paid
multi-service Preview Environment feature while retaining separate memory and
CPU allocations for the GUI and Python calculation service.

## Files and ownership

| File or setting | Purpose | Maintained where |
|---|---|---|
| `render.preview.yaml` | Recreates the two fixed services | Repository |
| `.github/workflows/deploy-fixed-render-preview.yml` | Deploys and verifies one commit on both services | Repository |
| Render deploy-hook URLs | Authorize deploy triggers | GitHub Actions secrets |
| Stable GUI and API URLs | Verification and workflow summary | GitHub Actions variables |
| `public/compute-config.json` | Baked GUI-to-API URL | Generated during each GUI build |

Never commit or paste a deploy-hook URL. Regenerate it in Render if it is
exposed.

## One-time Render setup

1. In Render, create a new Blueprint from
   `leviitzhak/keep_and_lease` and set the Blueprint spec path to
   `render.preview.yaml`.
2. Link the Blueprint to `agent/multi-commodity-preview` and create both
   declared services:
   - `keep-and-lease-preview`
   - `keep-and-lease-preview-api`
3. Confirm that both services have **Auto-Deploy Off**. The workflow is the only
   deploy trigger.
4. Copy each service's actual external URL. Render may add a suffix if a desired
   hostname is unavailable.
5. Confirm the GUI environment variable
   `KEEP_AND_LEASE_COMPUTE_API_URL` equals the API's `RENDER_EXTERNAL_URL`.
6. Confirm the API environment variable `KEEP_AND_LEASE_ALLOWED_ORIGINS` equals
   the GUI's `RENDER_EXTERNAL_URL`.
7. Open each service's Settings page and copy its secret deploy-hook URL.

If Render does not resolve a cross-service `RENDER_EXTERNAL_URL` reference during
the first Blueprint sync, enter the corresponding full `https://...onrender.com`
value manually, then use **Save, rebuild, and deploy**. The values remain stable
for this fixed preview.

## One-time GitHub setup

Open the repository's **Settings → Secrets and variables → Actions** page.

Create repository secrets:

- `RENDER_PREVIEW_API_DEPLOY_HOOK`
- `RENDER_PREVIEW_GUI_DEPLOY_HOOK`

Create repository variables using the actual Render external URLs, without a
trailing slash:

- `PREVIEW_API_URL`
- `PREVIEW_GUI_URL`

The URLs are not credentials. The deploy hooks are credentials and must remain
secrets.

## Deployment trigger

The workflow runs automatically after a push to
`agent/multi-commodity-preview`. It can also be run manually from the GitHub
Actions page. A manual run deploys the commit selected for that workflow run.

The workflow appends the triggering commit SHA to both secret hook URLs as the
`ref` parameter. It then polls:

- `${PREVIEW_API_URL}/api/v1/health`, whose `engine_commit` comes from
  `RENDER_GIT_COMMIT`;
- `${PREVIEW_GUI_URL}/build-info.json`, whose `commit` is generated during the
  GUI build.

It succeeds only when both services report the exact triggering commit. It also
requires `${PREVIEW_GUI_URL}/compute-config.json` to point to
`PREVIEW_API_URL`. The workflow summary publishes the GUI URL, API health URL,
and a strict `?engine=server` URL.

Deploy-hook requests can return `202 Accepted` when another deployment is in
progress. The workflow does not assume that hook acceptance means readiness;
the commit polling is the authoritative completion check.

## Verification and diagnosis

After a successful workflow run:

1. Open `${PREVIEW_GUI_URL}/?engine=server`.
2. Initialization must show **Server calculation ready**. Strict mode must not
   silently select Pyodide.
3. Open `${PREVIEW_GUI_URL}/compute-config.json`; `apiBaseUrl` must equal
   `PREVIEW_API_URL`.
4. Open `${PREVIEW_API_URL}/api/v1/health`; `engine_commit` must equal the GUI's
   displayed commit.
5. Run a small backtest, then repeat with `?engine=pyodide` to confirm that the
   preserved browser path still initializes.

Common failures:

| Symptom | Likely cause |
|---|---|
| GUI reports the GUI host as the calculation server | Empty or missing generated `compute-config.json`; rebuild the GUI with the API URL configured |
| API health returns 404 | The request is reaching the Node GUI service rather than the API service |
| Workflow times out with an old commit | Render build failed, a newer deployment replaced it, or a service is still starting |
| API health succeeds but browser requests fail | `KEEP_AND_LEASE_ALLOWED_ORIGINS` does not equal the fixed GUI origin |
| Hook returns 401 | Hook was regenerated or the GitHub secret is incorrect |
| Hook returns 404 for `ref` | The requested commit is unavailable in the linked repository |

## Rebuild from another thread or workspace

No local workspace state is required. To resume:

1. Read `docs/CURRENT_WORK.md` and this runbook.
2. Inspect the latest run of **Deploy fixed Render preview** in GitHub Actions.
3. Check the four GitHub secret/variable names above; secret values cannot and
   should not be read back.
4. Compare the API health `engine_commit`, GUI `build-info.json` commit, and the
   intended GitHub commit.
5. If a hook might be compromised, regenerate it in Render and replace only the
   corresponding GitHub secret.
6. Recreate both services from `render.preview.yaml` if necessary, replace the
   two public URL variables, and regenerate both hooks.

The application remains operable through the v12 Pyodide fallback if the fixed
API is sleeping or unavailable. Use `?engine=server` when validating deployment
so fallback cannot hide a server configuration failure.
