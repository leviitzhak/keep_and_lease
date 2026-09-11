# Shared daily / replay plots — verified preview

## Revisions and rollout

The work continues from `agent/todo-batch-completion` at
`4674d0601ea3a180d740e89b78bd05e9ac4ce93b` on `agent/shared-run-plots` (PR #46).
The application revision is `8f83983f4493db490f9941130dde86402d1f181d`.
Documentation-only follow-ups do not alter the deployed application revision.
No branch was merged into `master` and no stable deployment was performed.

The first combined implementation (`62d03527a8f71a297def7f1de69d2de48360b553`)
passed preview workflow `34620772208`. A subsequent UI correction releases old
canvas bitmaps/registry entries, preserves chart-specific inspection handlers,
and removes legacy fixed-height clipping. The correction went through the same
integration checks and a second, serialized preview deployment, rather than
racing another branch against the single shared preview.

Final preview workflow `34621268667` completed successfully on September 11,
2026. Private preview:
<https://keep-and-lease-preview-web-vfk2j2rgoq-zf.a.run.app/?engine=server>.

## Automated integration

Workflow `34621160549` passed 130 Python regression tests, all 72 JavaScript tests,
the production build/artifact validation, browser-smoke script syntax, and
canonical/public HTML and JavaScript mirror checks. Its artifact
`shared-plots-validation-34621160549` (ID `10272262070`) includes the logs and
`SOURCE_COMMIT.txt` identifying the application revision above.

Local actual-source Chromium checks included the application's CSS and histogram
wrapper, all 16 daily/replay-by-family combinations, desktop/mobile rendering,
hover, complete chart height, and release of disconnected chart references.
There were no page errors. These synthetic fixtures are additional regression
checks, not substitutes for the authenticated deployed tests.

A separate before/after synthetic numerical comparison found exact equality of
replay summaries, all full replay event/valuation audit rows, original daily and
replay chart fields, and the daily summary. The new state/result fields are
additive diagnostics; trading decisions, fills and accounting were not changed.

## Deployed checks

Evidence artifact: `deployment-smoke-preview-34621268667`, ID `10273088885`.
The downloaded `gui-report.json` and `extension/extension.json` both identify
`8f83983f4493db490f9941130dde86402d1f181d` as the deployed revision.

The authenticated GUI checks passed:

- A fresh, non-cached silver/gold/S&P 500/Treasury run with 4,836 observations,
  all three commodity lease charts, and shared daily holdings/turnover plots.
- A 500 ms replay with 600 valuations and ending NAV `1.0002382504874086`,
  matching the existing local/GCS financial expectation. Shared book and market
  plots, desktop hover, mobile rendering, and all eight plot families passed.
  The all-family loop also checked clipping and retained disconnected canvases.
- A 1 ms replay with 998 observations and ending NAV `1.0000001621471633`.
- Saved-result reopening, a 600-row CSV, audit access, both published 90-day
  benchmark views, shared historical book plots, and selected-period XLSX export.
  Historical missing turnover remains unavailable rather than fabricated.
- A checkpoint extension from `2026-06-25T01:00:01.000000` to
  `2026-06-25T01:00:03.000000`, resuming after the hourly checkpoint at
  `01:00:00` and verifying that the parent result was unchanged.

The final GUI report has `pageErrors: []` and `error: null`. Raw network evidence
includes the intentional invalid-date HTTP 400 probe and browser `ERR_ABORTED`
attachment navigations; downloaded CSV/XLSX responses were independently validated
by the smoke script. They are not missing exports.

The optional full BTC-minute acceptance step was skipped. No fresh full-period
90-day Cloud Run job was run for this release.

## The 90-day milestone

The research computations for `[2026-06-06, 2026-09-04)` at 500 ms under both
sequence and timestamp ordering, including their paired comparison, are done.
Workflow `34363722260` is successful. Their published GUI results/audits/exports
remain available. The TODO now marks that computational milestone complete and
separately tracks a fresh full-period GUI/Cloud Run operational acceptance run.
This plotting work did not rerun the complete 90-day computation.

## Boundaries

The common catalog has 30 definitions in eight families, rendered one commodity
and family at a time. Missing historical diagnostics remain unavailable and
inactive keep/short books remain not applicable. Daily money values are per
initial capital of 1; replay money values use configured USD capital. Sampled
returns, leg contributions and drawdown curves are not substitutes for exact
full-frequency risk statistics. Full-series filtering means the retained series,
not recovery of observations discarded by sampling.

Specialised full-universe curve-attribution/research plots and exact
full-frequency annual/leg statistics remain outstanding where their source
inputs are not retained. The inherited line-axis/tooltip numeric formatting can
round very small changes; adaptive precision is a usability follow-up. Underlying
stored result values are not rounded by the adapter. Existing checkpoint
engine/data identity restrictions remain in force for resume and extension.
