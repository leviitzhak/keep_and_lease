# Keep and Lease web GUI

This repository contains the hosted browser version of the Keep & Lease strategy
GUI. Its default calculation adapter uses the versioned server-side CPython API
when configured and automatically retains the existing Pyodide Web Worker as a
browser fallback. Both paths call the same Python modules and return the same
result object.

## Requirements

- Node.js 22.13 or newer
- npm

## Run locally

From the repository root:

```bash
npm ci
npm run dev
```

The development command copies market data and Python sources from the
repository root and the Pyodide runtime from `node_modules` into generated
public assets.

## Build

```bash
npm run build
```

The same asset-preparation step runs automatically before a production build.
The hosting manifest connects this checkout to the deployed ChatGPT Site at
<https://keep-and-lease.itzhakb.chatgpt.site>.

## Source layout

- `app/page.tsx` embeds the strategy interface.
- `public/silver_strategy_gui.html` contains the controls and charts.
- `public/backtest-worker-v12.js` initializes Pyodide 0.29.4 / Python 3.13 and
  executes the existing Python strategy.
- `public/backtest-worker-v13.js` preserves the worker protocol while routing
  calculations to the server API, with v12 as the fallback.
- `server/` implements the queued `/api/v1` computation API.
- `scripts/prepare-assets.mjs` prepares generated runtime and data assets.

## Run the computation API locally

```bash
python -m pip install -r requirements.txt
python server_main.py
```

Set `KEEP_AND_LEASE_COMPUTE_API_URL=http://localhost:8000` before building the
GUI. Add `?engine=pyodide` to the GUI URL to explicitly use the preserved browser
engine, or `?engine=server` to require the API without fallback.

## Active deployment: Google Cloud

**Google Cloud Run is the current and authoritative deployment path.** The stable
working version and the separate feature-branch preview should use the Google
Cloud infrastructure and `.github/workflows/deploy-google-cloud.yml`; do not
create or use Render services for current deployments or previews.

The Google Cloud path replaces the process-local queue with Firestore metadata,
one Cloud Run Job per calculation, and immutable gzip results in Cloud Storage.
Separate web/worker images, Cloud Run v2 Terraform, and the keyless GitHub
deployment workflow are implemented. The foundation is provisioned; follow
[`docs/GOOGLE_CLOUD_RUN_SETUP.md`](docs/GOOGLE_CLOUD_RUN_SETUP.md) for deployment,
preview/access operations, and remaining acceptance tests.

The Sites checkout may be used for a local agent preview only. Before starting
one, synchronize it with the intended GitHub branch and commit, then verify the
checkout's `HEAD` equals that commit. A Sites preview is never a deployment
source and must not substitute for the GitHub-to-Cloud-Run preview workflow.

## Render (legacy / retired)

The repository still contains historical Render configuration and documentation
for provenance and possible cleanup. **The Render deployment workflow has been
discarded and is not an active deployment target.** Render URLs, deploy hooks,
`render.preview.yaml`, and Render-specific workflows must not be treated as the
current preview or production procedure.

See the Google Cloud documentation above for all new deployment and preview work.


## Commodity-leg allocation semantics

Each configured commodity proportion is the **full long commodity leg**. Within that leg, the replicating fund and the Treasury-collateralized long-futures replication are complementary: if `a(r)` is the futures+Treasuries share, the replicating-fund share is `1 - a(r)`. The parameter `max_futures_treasury_fraction` caps `a(r)`, so `1 - max_futures_treasury_fraction` is the minimum replicating-fund share. The replicating fund is structurally mandatory; legacy JSON containing `enable_slv_leg=false` is accepted but the value is ignored.

The short parameter `max_short_fraction_of_long_leg` is measured against the full long commodity leg, not against only the fund or only the futures portion. A short position is paired with an equal-sized extension of the complete long commodity implementation.

## Book return decomposition

The lease book is the base long commodity implementation: replicating fund plus Treasury-collateralized long futures. The keep book is the incremental matched long extension plus short futures. The GUI reports independently compounded returns for both books and, within the lease book, for the replicating fund and the futures-plus-Treasury implementation.

Independent curves are useful counterfactuals, but they do not multiply to the strategy NAV because the daily strategy return is initially an additive sum of book contributions. For an exact product decomposition, daily additive contributions `c_i` with `R = sum(c_i)` are converted to log contributions

`g_i = c_i * log(1 + R) / R`, using the continuous limit `g_i = c_i` when `R = 0`.

Then `1 + R = product(exp(g_i))`. Compounding each elementary factor `exp(g_i) - 1` through time gives an order-independent attribution whose factors multiply exactly to the parent NAV. The same transformation is applied first to lease versus keep and then inside the lease book to fund versus futures-plus-Treasury.
