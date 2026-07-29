# PR #15 anchored-scoring preview

The production GUI remains unchanged while the new scoring behavior is reviewed.
This branch includes an isolated preview server that runs the existing silver
backtest with the active maturity score function replaced by the canonical PR
#15 implementation.

## Deploy an automatic mobile preview

[Deploy this branch to Render](https://render.com/deploy?repo=https://github.com/leviitzhak/keep_and_lease/tree/agent/implement-doc-plans)

The one-time Render setup creates a public HTTPS `onrender.com` URL. After that,
every commit pushed to `agent/implement-doc-plans` automatically rebuilds and
redeploys the preview. The deployment runs the PR #15 regression tests before
starting the web service.

The included `render.yaml` also enables automatic pull-request service previews
for future pull requests opened against the branch linked to the Render service.
Render deletes those temporary PR previews when their pull requests are closed.

## Run locally

```bash
python pr15_preview_server.py --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` (or the forwarded preview URL for port 8000).

## What this preview changes

- two maturity/rate anchor points for each of the long and short boundaries;
- derived linear boundary values at every maturity;
- canonical signed long and short distances;
- stable rate-scale normalization;
- symmetric clipping;
- configurable relative adjustment strength;
- non-negative final scores;
- the resulting contract allocation is passed into the existing backtest.

## What is not yet shown

The preview does not yet render the new frozen-curve rate-change attribution
scatter series. The reusable attribution module and tests are present, but the
production engine still needs explicit observed-versus-frozen end valuations for
each held instrument before those points can be generated without approximation.

## Suggested review

1. Run the defaults and record the ending NAV and weighted-maturity paths.
2. Set relative strength to zero; maturity allocation should revert to the base
   lease-edge score while entry eligibility and total notional stay unchanged.
3. Increase the second long anchor rate; longer long contracts should become less
   favored unless their lease rate rises sufficiently.
4. Increase the second short absolute-rate anchor; longer short contracts should
   become less favored unless their lease is sufficiently more negative.
5. Reduce the rate scale or increase strength to magnify the adjustment; clipping
   should keep the multiplier bounded.
