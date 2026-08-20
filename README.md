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

## Durable Google Cloud execution

The Google Cloud path replaces the process-local queue with Firestore metadata,
one Cloud Run Job per calculation, and immutable gzip results in Cloud Storage.
Separate web/worker images, Cloud Run v2 Terraform, and the manual keyless GitHub
deployment workflow are implemented. The foundation is provisioned; follow
[`docs/GOOGLE_CLOUD_RUN_SETUP.md`](docs/GOOGLE_CLOUD_RUN_SETUP.md) for the first
private workload deployment and acceptance test.

## Fixed Render preview

The repository includes `render.preview.yaml` and a GitHub Actions workflow for
deploying one commit to a persistent GUI/API preview pair. Follow
[`docs/RENDER_FIXED_PREVIEW.md`](docs/RENDER_FIXED_PREVIEW.md) to provision the
services, store their deploy hooks, configure their stable URLs, verify commit
provenance, or rebuild the preview from another workspace.

The provisioned preview tracks deployments triggered from
[`agent/multi-commodity-preview`](https://github.com/leviitzhak/keep_and_lease/tree/agent/multi-commodity-preview):

- GUI: <https://keep-and-lease-fixed-preview.onrender.com>
- API health and running commit: <https://keep-and-lease-fixed-preview-api.onrender.com/api/v1/health>
- GUI build metadata: <https://keep-and-lease-fixed-preview.onrender.com/build-info.json>
