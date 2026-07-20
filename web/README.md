# Keep and Lease web GUI

This directory contains the hosted browser version of the silver lease strategy
GUI. It runs the repository's existing Python backtest in a Web Worker using
Pyodide, so changing parameters and rerunning the strategy does not require a
separate Python server.

## Requirements

- Node.js 22.13 or newer
- npm

## Run locally

From this `web` directory:

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
- `public/backtest-worker-v9.js` initializes Pyodide 0.29.4 / Python 3.13 and
  executes the existing Python strategy.
- `scripts/prepare-assets.mjs` prepares generated runtime and data assets.
