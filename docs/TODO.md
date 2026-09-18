# TODO

This checklist reflects the current Google Cloud / GCS implementation and the remaining research, product, data, and engineering work. Completed items are retained when they document important implemented behavior.

The September 11 small batch completes four items and partially improves full-audit
progress. Scope and validation are recorded in `TODO_SMALL_BATCH_VALIDATION.md`;
remaining items below are not implicitly completed by that batch.

## cost-aware strategy

- the direct/proxy holding is the starting point and the default position
- the lease rate of every instrument is either updated by a time-weighted moving average of the spot and the future prices, or implied from sufficiently close obeservations of both prices. we also discount it for a conservative estimate of the possible lease rate that can be executed (the choice and values may be implied by a data analysis, and evaluating what can be executed from what can be observed).
  
- each available instrument is given an 'amortized return' in the following way : we take into account its lease rate, and its expected entry and exit costs, using expiry as the exit date (to get the maximum possible amortization). an extra exit costs of the alternative to exit should also be accounted for. this creates an updated lease rate (diminished by the amortized costs in the remaining lifetime)

- the direct proxy holding can considered a candidate instrument with no expiry and and a negative lease rate of the expense ratio. this negative lease rate can be considered as the amortized-cost lease rate (since the holding period is not constrained) (that allows the exit of other instruments which updated amortized-cost lease rate became negative).

- we do normalize the possible amortized returns (including lease and costs) to a daily or annual return for comparison

- every instrument where a position is taken is also given a 'keep amortized return' (also normalized in the same way), where the entry cost is not accounted for in the costs

(- no need to check predetermined discrete holding horizons)

then the allocation is as follows (it is not anymore according to the allocation rules defined by the entry rates and the rates curves) :

- define a maximum delta change for any position change
- sort the possible new positions by their amortized lease rates from best to worst in descending order  
- sort the existing positions in descending order from their worst keep values to their best keep values
- check if there is a possible transfer from the worst existing position to best new possible position that will increase from the 'keep amortized return' of the existing position to the new 'amortized return' of the possible new position, by a sufficient amount (allowing some slippage in the executed lease rate). the transfer is limited by the maximum delta change, and by the existing position.
- if the existing position size is less than the maximum delta change, consider the next worst exisitng position, reducing available transfer amount by the already accounted for amount of the previous existing position.

- given an observed lease rate and possible transfer, the execution should be as follows : 
	- keep continuously observing both worst existing instrument and best possible instrument 
   	- update continuously a limit order of the worst existing instrument from the best possible instrument quote and the observed/desired lease rate
   	- optionally, increase the lease rate used for the limit order by the fees of the transaction, instead of counting them as in the amortized lease rate.
   	- limit the quantity of this limit order by the observed quantity in the order book of the best possible instrument (such when the limit order is hit we know we can, in theory and if we are fast enough, execute a market order on the best possible instrument - at least we are more conservative, even if we don't expect instant execution)
   	-  when the limit order is hit, execute a market order (or maybe a limit order sufficiently expected to be filled) on the opposite direction of the existing instrument.
   	-  do the exact same thing, with the possible instrument being the limit order, being updated from quotes of the existing instrument,  
	

## Next implementation — cost-aware, funded paired-transfer strategy

This is the single next development workstream, to be implemented in a new
thread/feature branch after the documentation merge. See
[NEXT_STRATEGY_IMPLEMENTATION.md](NEXT_STRATEGY_IMPLEMENTATION.md) for the
ordered implementation handoff and links to the complete specifications.
Documented plans and preliminary studies are not implemented strategy features.

- [x] Document the common strategy specification, including the **same transfer
  instruction** for `spot <-> (cash/Treasuries + futures)`, expected net BTC
  wealth versus KEEPING the current funded position, and full-period acceptance.
- [ ] Audit/refresh Treasury coverage and normalize yield conventions before new
  acceptance runs. Preserve the old July 14 carry-forward vintage/results and
  expose rate age; model real security holdings or explicitly labeled proxies.
- [ ] Implement separate spot/futures feed-availability delays, distinct from
  processing, order-entry and fill-response delays. Either observation order
  is allowed once both observations are available; never use future knowledge.
- [ ] Require causal, closely timed observations and size-aware executable prices.
  Reserve liquidity without double use; do not call past trade size quote depth.
- [ ] Implement durable paired incremental transfers, both directions and direct
  futures rolls, coupling child fills, cash/Treasury movements and collateral.
  Bound prefunding, unpaired exposure and legging time; retain partial failures.
- [ ] Separate held inventory from stale/missing signal eligibility. Missing new
  prices do not alone trigger liquidation or a compensating spot transaction.
- [ ] Implement venue-aware futures mark-to-market, variation settlement and
  funding in backtests, replacing the replay's immediate-P&L-to-cash shortcut
  rather than counting P&L twice. Separate marks, unsettled P&L and settled cash;
  model Treasury sales/financing, haircuts and settlement/payment calendars.
- [ ] Add optional product-specific fixed commissions and minimum ticket charges,
  alongside proportional/per-contract fees, spread, impact, delivery and funding
  costs. Define fee scope across partial fills/replacements; zero preserves the
  old behavior. Only actual fee-bearing transactions incur commissions.
- [ ] support proxy expense for trade replay
- [ ] Evaluate feasible transfer quantities and holding horizons using expected
  incremental NET BTC wealth against keeping the CURRENT position, with a
  cost-recovery safety margin/no-trade region. Reuse holdings; do not re-charge
  sunk costs or require arbitrary long holds instead of an economic comparison.
- [ ] Implement discretionary exits that crystallize acceptable net gains OR
  enable a sufficiently better forward net opportunity; compare executable pair
  limits and preserve mandatory expiry/collateral/risk overrides.
- [ ] Model expiry-reference basis, delivery fees and pre-expiry close choices;
  do not equate official settlement with an unrelated spot price or physical BTC.
- [ ] Report observed versus executed matched-fill lease rates, predicted versus
  realized BTC returns, cost/quantity/horizon breakdowns and KEEP alternatives.
  Retain unsuccessful/unmatched instructions and the full calculation provenance.
- [ ] Validate accounting, fixed fees, causal latency, funding stress, partial
  fills, liquidation, restart and zero-cost compatibility; then compare bounded
  same-opening-state runs and the full 90 days with chronological holdout dates.
  Keep all earlier strategies and results immutable. Leverage support must be
  explicit and separately tested, not silently enabled by this accounting work.

## Higher priority

- [x] Complete authenticated GCS publication/read validation for the tested
  Parquet trade pilot. All 5,739,608 events, both financial summaries and both
  complete audit hashes matched from GCS; see `BTC_TRADE_STORAGE.md`.

- [x] Prevent automatic GCP deployments for documentation-only pushes. The
  deployment workflow ignores `docs/**` and Markdown-only changes while mixed
  application/documentation commits continue to deploy.

- [x] Synchronize horizontal scrolling across related plot panes so long
  intraday/subsecond charts stay aligned during inspection.

- [x] Complete the 90-day BTC subsecond research backtest for
  `[2026-06-06, 2026-09-04)` at 500 ms under both sequence and timestamp
  ordering, including the paired comparison. Workflow `34363722260` completed
  both policies; published results, audits and selected-period XLSX exports
  are accessible in the GUI. This computational milestone is done.

- [ ] Separate operational acceptance: run a fresh, full 90-day job through
  the GUI/Cloud Run worker path and verify its lifecycle/resource behavior.
  This is not a claim that the completed research backtests are unfinished. The implementation already includes resumable daily
  ingestion and selected-partition range reads, continuous checkpoints, durable
  resume, discrepancy evidence, sequence/timestamp ordering scenarios,
  failed-day recovery, paired 90-day benchmarks, saved GUI results, and
  asynchronous selected-period XLSX exports. Do not reset holdings, pending
  fills, smoothing, or Treasury accrual at storage/day boundaries. See
  `BTC_90_DAY_EXECUTION.md`.

- [ ] analyse strategy : btc min 90d fees 2bps flg

- [ ] examine the following strategy : 
              - enter long a future when the lease rate is high
			  - keep it until maturity (and get the title on the commodity)
              - whenever there is a negative lease rate and a positive lease rate, and we have either a long position or titles on the commodity, short the future with the negative lease rate (up to the amount allowed by the existing position or the titles on the commodity), and take the equivalent long position on the future with the positive lease rate. 


- [x] Extend a completed backtest to a longer period from the GUI, reusing its
  durable checkpoint and verified prefix when the immutable engine/data/rates
  are compatible. Moving the start earlier remains a fresh-run operation. The
  deployed preview acceptance passed on commit
  `c1121291a554bb99fb83ec979c65d8d12f624a98` in workflow `34599205892`,
  including parent immutability and child resume from the hourly checkpoint.

- [x] Explain the purpose and origin of `agent/cloud-autonomous-access`.
- [x] Push and verify `agent/btc-90day-subsecond` in the GCP preview.
- [x] Integrate the uploaded BTC trade-research pilot with the GUI and worker for
  second/subsecond execution. See `BTC_SUBSECOND_GUI.md`.
- [x] Show saved server backtests with durable progress, cancellation,
  checkpoint resume, selectable results, and background/parallel cloud
  submission. Full-period Cloud Run acceptance remains pending.
- [x] Keep full 90-day BTC minute computation within existing worker limits using
  immutable audit chunks and on-demand detail/export. All 129,599 intervals are
  retained; local full worker measurement is 3,186.3 MiB RAM / 63.54 MiB initial
  JSON. The approved export UX preserves full ledgers in numbered XLSX parts.
- [x] Separate regular long-only BTC execution from stale candle valuation.
  Preserve genuine observation age, actual quantities, delayed fills, partial
  size limits and explicit trading costs. No zero-volume futures fills remain.
  Candle execution remains an explicit research assumption, not quote validation.
- [x] Add an authenticated deployment gate for the exact feature SHA and full
  BTC resource/audit/export acceptance in the authoritative private GCP preview.

- [x] Share the applicable daily/candle and trade-replay plot catalog in both
  directions: performance, exposures/collateral, activity, market/rates/legs,
  held-contract scatters, books/distributions and reconstruction. New runs retain
  diagnostic fields; historical missing fields and inactive books are explicit.
  See `SHARED_RUN_PLOTS.md` for units, timestamps and sampling limits.
- [ ] Extend specialised daily curve-attribution/research comparisons and exact
  full-frequency annual/leg statistics to replay when their underlying diagnostic
  inputs are retained or explicitly loaded; do not infer these from plot samples.
- [x] Allow user-selectable replay plot density for intraday/subsecond runs without
  changing the underlying decision/execution frequency.
- [x] Before long trade-replay backtests start, show the planned number of decision
  ticks and chart-sample cap, and report progress against the decision total.
- [ ] Before long exports start, estimate output work/size where robustly possible;
  prefer measured rows/chunks/bytes over a misleading time ETA.
- [x] Add a plot of volume traded by the strategy based on actual simulated fills,
  not market-wide volume.
- [ ] Display hover information for futures in the spot + futures-price plot,
  including implied lease rate.
- [x] Add progress and cancellation for selected-period BTC replay spreadsheet
  generation/export.
- [x] Add progress when loading detailed plots (selected chunks received/total,
  with cancellation and no partial replacement of existing charts).
- [ ] Complete progress for full-audit generation/download across run types.
  Ordinary daily/minute results now show preparation status, received bytes and
  cancellation, with percentage only when the response length is known. Large
  trade-replay archives still use native browser downloads; in-app progress for
  that path remains pending rather than buffering a multi-GB archive in RAM.
- [ ] Later, if suitable data becomes available, investigate historical bid/ask
  quotes and additional order-book depth for executable prices, available size,
  partial fills, participation constraints and slippage.
- [x] Report statistics for the collateralization ratio of futures positions and
  flag any breach of the required minimum collateralization.
- [x] In replay/export valuation data, add **Target futures notional USD** and
  **Free collateral USD = Cash/Treasury USD - absolute actual futures notional
  USD**. The current trade replay is long-only, so gross and net futures notional
  coincide; this makes delayed/partial execution distinguishable from an
  accounting mismatch.

## BTC data / execution research

- [ ] Obtain individual CME BTC/MBT regular-futures quote/trade history and exact
  expiry metadata through an entitled source. Until then, label Deribit inverse
  USD quotes used with linear P&L as a regular-futures **research price proxy**.
  CME DataMine is a documented acquisition route; no full-window purchase has
  been made. See `BTC_EXECUTION_FIX_PROPOSAL.md`.
- [ ] Add contemporaneous USDT/USD conversion or a genuine continuous BTC/USD
  feed and compare with the Binance parity-assumed proxy. Quantify peg and
  cross-venue basis separately before interpreting short-maturity lease signals
  as economic carry. See `USDT_USD_BASIS.md`.
- [ ] Do not activate the lease book for BTC inverse futures when their required
  BTC collateral is itself held idle and earns no yield; that construction does
  not satisfy the strategy's fully collateralized futures-plus-yielding-Treasury
  principle.
- [x] Enable BTC as a strategy commodity after the Deribit/Yahoo coverage audit:
  native-payoff conversion throughout return/attribution, regular/inverse mode,
  conversion fee, minimum accumulated-BTC conversion threshold, seven-day
  calendar alignment, weekend Treasury accrual, and direct-BTC holding labels.
- [x] BTC-only execution/rebalancing accepts any whole multiple of the detected
  common market-data resolution. Intraday Treasury valuation carries the latest
  observable yield forward and switches only when a new mark becomes available,
  without future observations or interpolation.

## Implemented core behavior

- [x] Stream complete finalized engine audit rows without retaining the full
  history; stream alternative comparisons into summary accumulators while
  reusing the selected main calculation. Complete audit chunks, owner-scoped APIs
  and on-demand GUI details are implemented without state resets at storage boundaries.
- [x] Eligibility gates are applied before maturity scoring.
- [x] Long and short linear maturity/rate boundaries are available.
- [x] Boundary distance is normalized, clipped, and applied as a relative score multiplier.
- [x] Short-side signed distance follows `-lease_rate - line`.
- [x] Per-commodity leg parameters and saved browser strategy presets are available.
- [x] Day inspection shows portfolio composition by commodity, leg and contract.
- [x] Common plots, calendar-year filtering, synchronized date inspection, and
  explicit plot diagnostics are implemented.
- [x] Commodity and Treasury maturity scatters are available; Treasury plots use yield.
- [x] Scatter points support hover/click on desktop and tap inspection on mobile.
- [x] Daily hierarchical return attribution reconciles to total return.
- [x] Annual statistics, headline drawdowns, and extreme-return inspection are present.
- [x] Silver, gold, Treasury, and S&P 500 data are organized as plain CSV with a
  coverage and hash manifest.
- [x] Restore the latest completed Firestore/GCS result and its parameters on GUI
  startup, without recalculation or obsolete state-route requests.
- [x] Display every commodity and Treasury rate-change scatter, filter its points
  with the selected plot period, and show an explicit empty-data state.
- [x] Load the default GUI markets from the canonical materialized/SQLite path
  without probing damaged optional legacy archives.
- [x] Generate a spreadsheet for a user-selected date interval containing
  portfolio composition, component values and component prices.
- [x] Replace per-commodity standalone-compounded and multiplicative-contribution
  displays with the commodity-quoted lease/keep decomposition: unextended
  futures+Treasuries, replicating/direct holding, lease book, keep book, daily
  returns, compounded indexes, underlying price evolution, distributions and NAV
  reconstruction diagnostics.
- [x] Investigate the NAV-reconstruction difference first appearing on
  03.01.1985 for `strategy full silver long gradual`.
- [x] Add schema-versioned current and named strategy presets, including server
  persistence where available and JSON import/export.
- [x] Use the root Python engine as the canonical implementation and copy it into
  `public/` only through `scripts/prepare-assets.mjs`; maturity scoring has one
  implementation in `maturity_scoring.py`.
- [x] Add inspected-day score audit with eligibility, boundary value, signed
  distance, base score, relative multiplier, final score and target weight.
- [x] Verify the one-trading-day execution shift end to end with regression tests.
- [x] Replace residual lease/basis-change attribution with observed-versus-frozen
  curve valuation for every held contract.
- [x] Add attribution-versus-maturity scatter plots for each commodity and
  Treasury yield changes.
- [x] Add no-look-ahead tests that perturb future observations.
- [x] Add the separate pure-maturity multiplier favoring shorter long positions
  and longer short positions, with a zero-strength backward-compatible default.
- [x] Keep durable replay checkpoints strict-JSON compliant even when internal
  accumulators use an infinity sentinel; infinities are tagged for checkpoint
  storage/restore and NaN remains a hard error.

## Wanted additions

- [ ] make sure fees can be applied to the legacy runs (with daily executions)
- [ ] Investigate and explain the performance of the full-silver long gradual strategy (appears in the strategies folderm, with daily execution frequency), adding fees for the transactions.
- [ ] Support separate minimum-days-before-expiry parameters for long and short
  futures positions.
- [ ] Define the extended book independently from the lease book:
  - every long future held by the extended book must mature earlier than every
    short future it holds;
  - extended-book long maturities need not match lease-book long maturities; and
  - choose the extension from the eligible shorter-maturity subset using the
    same construction logic and replicating/direct-holding versus
    Treasuries+long-futures trade-off as the lease book.
Transaction-cost implementation (including explicit fees and simulated bid-ask
spread costs) is grouped in the next-workstream checklist above.
- [ ] Add a scatter plot of lease rates scaled to a daily horizon versus the
  corresponding daily return quoted in the commodity.

## Small fixes / usability

- [ ] improve readability of parameters settings by either merging common legacy and trade replay parameters, or by displaying simulatanesouly all the parametrs of only one of them
- [ ] parameters settings specific to a commodity (for example btc) should appear in the specific commidities parameters section, when the parameters of the commodity is selected.
- [x] Make the saved-backtest list configurable: keep only user-selected runs in
  the default saved view across sessions, with an explicit option to show all.
- [ ] Where sensible, unify trade-replay period/export controls with the
  corresponding controls used for legacy/daily runs.
- [x] Extend streamed `trade-valuations.csv` output with target futures notional,
  free collateral, collateralization ratio and cumulative turnover. Preserve
  backward compatibility and leave historical benchmark fields blank when the
  immutable source does not contain enough information to derive them.
- [x] Make the HTML source default for `trade_initial_capital_usd` $100,000 and
  remove the runtime `$1 -> $100,000` upgrade heuristic so a deliberately saved
  $1 strategy remains $1. Update the stale help copy to describe participation
  against configured capital while retaining the research-capacity caveat.
- [ ] Refresh `BTC_SUBSECOND_GUI.md` for the current configurable chart density,
  accepted published paired benchmarks and deployed GUI/API checkpoint extension;
  keep fresh full-period Cloud Run acceptance documented as a separate pending gate.
- [x] Use thinner bins in displayed return-distribution histograms (60–160 bins,
  shared drawing/hover rules; missing values excluded).
- [x] Show hover information on return-distribution graphs with the bin interval,
  observation count and frequency.
- [x] Populate the GUI **Saved strategy** dropdown from strategy files in the
  repository `strategies` folder.
- [ ] Add full inspection interactivity to the new log-return decomposition graphs.
- [ ] Extend the portfolio contribution-by-asset plot to show individual leg
  values within each commodity sleeve.
- [ ] In each commodity strategy-versus-direct-hold plot, compare against a
  direct holding of the same initial commodity quantity.
- [ ] Update the **Maturity-line allocation formulas** section with the current
  signed-score and SoftMax allocation formula.
- [ ] Keep the displayed name of the currently loaded/saved parameter set
  synchronized with parameter-field values.

## Priority 2 — data

- [ ] Obtain modern individual-contract histories for gold, silver, and S&P 500.
  Current cross-maturity archives stop in 2002; continuous benchmarks through
  2026 cannot replace a maturity curve.
- [ ] start downloading one or two years of history of full btc raw data, instead of currently 90days.
- [ ] check where full subsecond raw data for other commodities can be found.
- [ ] Add automated data refresh and structural quality checks to CI.
- [ ] Migrate remaining large calculation-ready historical inputs to durable
  versioned object storage where appropriate while preserving reproducible
  manifests; GCS is the selected cloud object-storage architecture.
- [ ] Verify ETF distributions and total-return benchmark treatment.

## Priority 3 — research and usability

- [ ] Add scenario comparison between saved strategies.
- [ ] Add sensitivity surfaces, walk-forward/out-of-sample evaluation, and
  transaction-cost/liquidity stress tests.
- [ ] Validate coexistence of short-term long and long-term short books across commodities.
- [ ] Complete previous/next trading-day controls wherever inspection still
  requires date entry.

## Engineering

- [x] Define and implement the versioned browser-parameters/server-result API
  described in `DEPLOYMENT_ARCHITECTURE.md`.
- [x] Add asynchronous backtest execution with durable cloud progress,
  queued/running cancellation, result limits, caching and provenance.
- [ ] Measure warm/cold duration, peak memory and result size for representative
  daily, minute, one-second and subsecond cloud runs and use those measurements
  to tune GCP worker profiles.
- [ ] **Lower-priority speed improvement:** precompute/version compact
  per-commodity/per-contract quote-availability indexes and a reusable
  jointly-priceable compounding-calendar cache keyed by active commodities,
  contract-selection-relevant parameters, market-data version and date range.
- [x] Implement the Google Cloud durable Firestore job/cache repository,
  immutable result/audit storage, Cloud Run Job launcher/cancellation, worker
  heartbeat/stale-lease reconciliation, separate web/worker images, workload
  Terraform, and keyless immutable-digest deployment workflow.
- [x] Apply the Google Cloud foundation IAM delta and deploy private Cloud Run
  workloads with authenticated health checks.
- [x] Let the bounded keyless cloud-agent operator select private stable/preview
  GUI, enforce an optional exact deployed SHA, and keep request-only checks from
  triggering competing preview deployments.
- [ ] Complete bounded numerical, cancellation, cache-reuse and
  container-replacement acceptance tests in `GOOGLE_CLOUD_RUN_SETUP.md`.
- [x] Implement direct Cloud Run IAP, private human/machine allowlist
  instructions, and dual-mode keyless deployment/operator token audiences.
- [ ] Complete remaining IAP activation/allowlist/repository-variable work and
  verify the full acceptance matrix while anonymous Cloud Run invocation remains disabled.
- [ ] Move remaining calculation-ready cloud inputs out of worker images into
  versioned GCS Parquet/DuckDB/Arrow-style objects and restore durable cloud day inspection.
- [ ] Add GitHub Actions checks for Python tests, the production build, rendered
  tests and artifact validation.
- [ ] Prefer GitHub's ID-based `noreply` identity for future GitHub API/web and
  command-line commits; leave existing public history unchanged absent a separate
  history-rewrite decision.
- [ ] **Repository cleanup:** identify and remove discarded workflows, obsolete
  generated worker versions, duplicated deployment artifacts, abandoned preview
  paths and dead feature/code paths after confirming the canonical GCP/GCS build,
  deployment and computation paths. Preserve anything still needed for migration,
  reproducibility or historical documentation.
- [ ] Keep `CHANGELOG.md`, parameter documentation, data manifests and this
  checklist current with every durable behavior change.

## Explicitly delayed — persistent ChatGPT Sites and fallback computation

These items are intentionally deferred while GCP/Cloud Run + GCS remains the
canonical deployment and calculation architecture. Do not let them block normal
GCP feature work or releases.

- [ ] Make the persistent ChatGPT Sites deployment able to run a backtest and
  return its results reliably.
- [ ] Make the persistent Site operate smoothly and remain verifiable by the
  working agent: synchronize packaged runtime assets with deployed code, support
  reliable owner-authenticated access, and add an end-to-end smoke test that runs
  a strategy and verifies plots and spreadsheet download.
- [ ] Fix the maturity-allocation heatmap preview on the persistent Sites deployment.
- [ ] Revisit the browser/Pyodide fallback computation path only if it remains a
  desired supported architecture. If retained, add full-data CPython-versus-
  Pyodide equivalence fixtures and define exactly when automatic fallback is
  permitted; otherwise remove the fallback path during repository cleanup.
- [x] Historical/local work aligned the local ChatGPT Sites GUI/API preview with
  the Google Cloud versioned server-calculation method and strict server mode.
  Publishing persistent Sites against private IAP still requires separate
  authenticated integration and is deferred.

## September 9–10: long-run infrastructure and evidence

See `BTC_BACKTEST_DATA_STATUS.md` and `BTC_90_DAY_EXECUTION.md` for the data
inventory and measured staged results. Implemented infrastructure includes
explicit preview/stable Terraform profiles, a long-running preview worker,
verified 90-day catalog, configurable CPU/memory, bounded continuation segments,
recovery from durable checkpoints, compatible GUI/API checkpoint extension,
paired 90-day benchmark evidence, saved-result GUI integration, selected-period
replay XLSX exports with progress/cancellation, selectable replay chart density,
explicit execution/collateral diagnostics, and strict-JSON checkpoint sentinel
handling.

Remaining long-run work is fresh full-period Cloud Run acceptance, append-only
validation for newly ingested history, and lifting reader/catalog bounds beyond
90 days after resource checks.
