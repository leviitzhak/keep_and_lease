# Unified data, subsecond cost, and order replays

**Historical phase report.** The later [completed union and full action search](FULL_ACTIONS_AND_UNION.md)
supersedes the pending-merge, missing-Torch and action-domain status below. Its
new CPU measurements apply to expanded neural search; the frozen legacy replay
results and their provenance here remain unchanged.

Research only, 2026-10-26. No deployment, orders, purchases, new market-data downloads,
cloud workers, neural retraining, or large replay were started.

## What was completed

- Added a bounded offline union builder accepting both daily native exports and
  receipt-described native sequence chunks. It verifies hashes, bytes, native
  sequence/identity, deduplicates overlaps, preserves both origins, and rejects
  conflicting records atomically. Inter-object gaps remain explicit.
- Added a causal `Trade` adapter: sequence-prefix maximum timestamp is the
  earliest availability time; backdated prints cannot execute orders retroactively.
  An incomplete prefix requires a verified prefix anchor. Internal gaps block
  strict replay; the raw union still preserves them.
- Built a local union of all 180 available daily files: **486,203 unique records**,
  **9,121,523 compressed input bytes**, no internal sequence gaps. Separately,
  importing the same historical object twice deduplicated 21,228 input rows to
  10,614 records with both source references. This is a historical-object
  deduplication test, not verification against the unavailable multi-year copy.
- Re-executed three four-hour historical prefixes. Every regenerated action,
  candidate audit and fill matched the published 90-day study exactly.
- Measured 2,880 decisions in four short historical CPU benchmark runs.

**The entire multi-year union has not been materialized or raw-reconciled.**
`unified-v1.json` says `full_archive_union_complete: false`. No missing period
has been fabricated or interpolated. The existing published study is unchanged;
its legacy timestamp-ordering policy differs from the new strict causal adapter.
Do not silently mix results produced under these two policies.

## Source overlap and the remaining work

| Source | Verified scope here | Coverage |
|---|---|---|
| Daily Dec26/Mar27 export | All 180 raw hashes, sizes, identities and sequences | 2026-06-06 through 2026-09-03 |
| Frozen multi-year archive | Ten exported metadata hashes and exact completed receipt-key coverage | Approximately 2017-01-06 through 2026-10-09; individual instrument snapshots differ |
| Multi-year raw chunks | Not locally available or freshly read | 12,322 receipt-named chunks; 120,105,433 advertised native sequences |

The archive catalog has 540 instruments, 509 with trades and 31 empty; 11 have
unavailable prefixes. Those are source limitations, not continuous zero-trade
observations. The daily export's two instruments and sequence bounds lie within
this larger archive. The correct operation is a **union keyed by venue,
instrument, and native trade ID**, with a unique per-instrument sequence check.
This implementation is Deribit-only, so venue is implicit and cannot be mixed.
Do not simply append the 90 days: that would double count overlapping prints.

The current session has the multi-year plan and completion metadata, not the
raw receipts/objects. The existing `deribit-maturity-inputs` operator exports
metadata only. Its eight-shard full-history replay runs a different strategy;
launching it would not reconcile or evaluate this implementation. There is no
GCS read connector in this session. A bounded read-only worker using the existing
keyless operator identity is the next access path; do not copy credentials here.

Remaining steps, in order:

1. Pin the frozen plan and instrument catalog, retaining each snapshot cutoff,
   listing/expiry, native payoff, contract size and tick/lot provenance. Current
   catalog fees/margins are not historical fee/margin schedules.
2. Export a small overlap receipt/object sample through that operator. Verify
   compressed SHA256/size, sequence bounds/counts and execution-relevant fields
   against the daily export. Preserve both origins; quarantine any disagreement.
3. Reconcile the remaining receipt/object references in bounded, resumable
   batches **in the existing storage location**. A logical dataset manifest can
   reference immutable objects rather than copying all raw data. Add partition
   indexes and checkpoints, then audit aggregate counts, duplicates, anomalies,
   timestamp reversals and unavailable prefixes. No bulk download is necessary.
4. Adapt the study runner to this indexed reader: active contract membership,
   causal seeds across chunks, dynamic expiries, explicit gap/invalid-record
   handling, bounded historical instrument shortlist, and chronological
   calibration/validation/test windows with non-overlapping outcome tails.
5. Verify settlement/bridge evidence separately before claiming through-expiry
   results or realized final holdings.

`unified.py` is a **bounded local foundation**, not the full archive worker. Its
CLI enforces 600k input rows, 12 MB compressed total, 100k rows/8 MB per object,
and 180 seconds. The full archive needs the partitioned worker above, not larger
unattended limits. The temporary SQLite cache is reproducible from pinned sources
and is not committed. The manifest/report and implementation are durable in git.

### Why the previous reader was narrow

There is no incompatible native trade format: both contain Deribit native JSON
records. The old loader expects `specification.json`, four pilot metadata files,
and one `YYYY-MM-DD-SYMBOL.jsonl.gz` for every configured instrument/day. Its
pilot split helper explicitly requires two instrument seeds. The multi-year
archive instead has per-instrument 10,000-sequence chunks and receipt-addressed
objects, changing listings, empty contracts, anomalies, and timestamp reversals.
The original bounds and assumptions were appropriate to its small pilot. Merely
pointing that loader at the larger directory cannot make it consume the archive.

### Settlement and bridge evidence

Trade unification does **not** require settlement data. Through-expiry accounting
and a claim of realized commodity balances do require it:

- Exact contract expiry, payoff, settlement currency and official delivery price;
  daily settlement history and cash availability when funding feasibility depends
  on it; historically applicable fees, margin and settlement-session behavior.
- Actual spot conversion evidence for the delivery-equivalent bridge: time,
  executable instrument, price/volume or quotes, fees, latency and available cash.
  BTCUSDT spot also needs USD/USDT conversion evidence or an explicit assumption.
- Provenance for every resulting cash flow. A last futures trade or its associated
  index snapshot is not an observed official final settlement price.

Deribit documents daily 08:00 UTC realization without closing the contract, and
final cash settlement with no physical delivery. Its delivery-price endpoint
supplies historical official prices, but has not been queried/downloaded here:
[settlement rules](https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement),
[delivery-price API](https://docs.deribit.com/api-reference/market-data/public-get_delivery_prices).
Today's documentation is not proof that all rules/fees held throughout the archive.

For a hypothetical linear long of `q` BTC at `K`, settlement P&L is
`q*(S_settlement-K)` USD. Buying `q` BTC is a **separate spot execution**; a short
uses the opposite bridge. For native inverse signed notional `N` USD, P&L is
`N*(1/K-1/S_settlement)` BTC, and the delivery-equivalent bridge trades
`N/S_settlement` BTC. Actual bridge price, timing and fees matter.

The current study uses inverse-source trades with hypothetical linear accounting,
so all its execution results are counterfactual. Its held positions are contractual,
not realized settlement balances. The multi-year snapshot ends in October 2026:
**it still does not reach Dec26 or Mar27 expiry**. Older contracts must supply
through-expiry learning episodes, with verified settlement evidence.

## Analytical policy and exact grids

The analytical baseline used in these runs is greedy: among feasible candidates,
pretend every proposed remaining quantity fills at its posted limit, compute the
change in `min(BTC fractional growth, USD fractional growth)` after fees, and
choose the first maximum. Wait wins zero ties. Risk admission separately checks
holding floors, funding and partial-fill combinations. The scoring rule has no
estimated fill probability, waiting cost, future premium forecast or learned value.
Simulation still fills legs independently with delayed messages and reports.

| Preset | Alternative base sizes, BTC | Alternative offsets, basis points |
|---|---|---|
| original | 0.005, 0.010 | -50, 0, +50 |
| small | 0.0025, 0.005 | -50, 0, +50 |
| tight | 0.005, 0.010 | -10, 0, +10 |
| small_tight | 0.0025, 0.005 | -10, 0, +10 |

The pair of sizes is a menu of two choices, **not one size per leg**. The triplet
is a menu of three offsets, **not three simultaneous posted quotes**. One basis
point is 0.01%; 50 bp is 0.5%.

For each unordered eligible pair `(A,B)`, the generator combines a base size `q`,
sign `s` in `{+1,-1}`, second-leg ratio `r` in `{1,0.99}`, and offset `d`:

- `quantity_A = s*q`, `quantity_B = -s*q*r`, rounded down in absolute native lots.
- `limit_A = last_received_trade_A*(1+d)`;
  `limit_B = last_received_trade_B*(1-d)`.
- Buy limits round down and sell limits round up to the price tick. Offsets are
  linked across the pair, not independently crossed. A negative offset is below
  the reference, not necessarily passive for a sell.
- Singles choose one symbol, `q`, sign and `d` independently.

The linear adapter lot is 0.0001 BTC: `0.010*0.99 = 0.0099`, but
`0.005*0.99 = 0.00495` rounds to **0.0049** (2% imbalance), and
`0.0025*0.99` rounds to **0.0024** (4%). The 0.99 factor always applies to the
lexicographically second symbol; every unequal orientation is not enumerated.
For native inverse orders the desired BTC quantity is converted to USD notional
at the posted limit before native rounding.

An example actually selected on June 6: choose `q=.01`, `s=+1`, `r=.99`,
`d=-.005`. Received references were 62,325 and 62,872.5 USD/BTC. The posted pair
is **buy .0100 Dec26 at 62,012.5; sell .0099 Mar27 at 63,187.5** after tick rounding.

### Instrument selection and action count

The recent study supplied **only Dec26 and Mar27**; it did not search 540 archive
contracts. In general, the generator lexicographically sorts supplied instruments
that have an observed market record and satisfy `now < expiry <= resolution`.
It enumerates all unordered pairs, then singles. It has no liquidity ranking.

With two sizes and three offsets, and no uncertain orders, the unfiltered count
is `2 + 12*n + 24*n*(n-1)/2`: wait/emergency, singles, and pairs. Two instruments
produce **50** proposals. Three produce 110, truncated to the configured **96**
before risk filtering. Pairs precede singles, creating lexicographic/truncation
bias. A larger-universe study needs a balanced shortlist based only on received
information. The neural feature encoder also has a 32-item limit including order
and cashflow tokens; the whole archive catalog cannot be inserted as one state.

While orders remain uncertain/working, new creations are suppressed: consider
wait, cancel-all, one amendment per uncertain order, and emergency cancel.
Amendments use the last received trade with zero offset and the known remaining
quantity; they do not search the original grid again. One/two uncertain order IDs
usually give four/five proposals. Risk filtering can reduce these further.
The neural network ranks the accepted immediate post-decision states with one
shared continuation-policy objective head.

Calibration remains the published protocol: June 6–July 29 (54 days), validation
July 30–August 16 (18), held-out August 17–September 3 (18); two matched seeds.
Calibration rejects any failing preset and ranks safe mean joint utility;
validation selects before the test is opened. Only `small_tight` qualified and
it waited throughout. These subsecond benchmarks do not recalibrate that policy.

## Measured subsecond cost

CPU: Intel Xeon Platinum 8573C, Python 3.12.14, one replay process, container quota
8 CPUs/8 GiB; benchmark peak RSS 29.1 MiB. Four runs replayed the same first
120 historical seconds. Total elapsed 143.7 s. All trades retained their exact
recorded times; there were no invented quotes between them.

| Interval | Decisions / 90 days | Sample state | Mean per decision | 90-day serial wall projection |
|---|---:|---|---:|---:|
| 500 ms | 15,552,000 | original, mostly 5 candidates | 17.22 ms | 74.5 h / 3.1 days |
| 500 ms | 15,552,000 | small_tight, 50 candidates | 107.20 ms | 463.3 h / 19.3 days |
| 100 ms | 77,760,000 | original, mostly 5 candidates | 13.09 ms | 283.0 h / 11.8 days |
| 100 ms | 77,760,000 | small_tight, 50 candidates | 80.71 ms | 1,743.7 h / 72.7 days |

These are early-window extrapolations, **not measured 90-day runs or guarantees**.
The short windows had no fills and small ledgers. Different complexity, CPU load,
more instruments and accumulated cashflows can change cost substantially. Mean
costs differ between intervals because these are separate measurements, not a
claim that faster cadence makes individual decisions cheaper. Candidate/risk
checks consumed roughly 77–95% of total wall time. Benchmarks ran alongside
bounded local work; CPU and wall times are separately recorded in the JSON.

Neural inference was **not measured**: Torch is not installed in this runtime.
Any additional 10 ms per decision for feature building plus a batched network
forward would add 43.2 h at 500 ms, or 216 h at 100 ms, per 90-day trajectory.
Multiply collection/replay cost by actual seeds, starts, policies and improvement
rounds; do not multiply by every candidate unless collecting branched rollouts.
Independent trajectories parallelize, but one sequential trajectory does not
become eight times faster merely by renting eight cores.

The existing 87,877-parameter network fits comfortably on CPU. A practical
engineering target is 8–16 CPU cores, 32–64 GiB RAM and SSD-backed streaming
storage; a 16–24 GiB GPU is optional for batched fitting, not a fix for Python
candidate/admission cost. These are sizing assumptions, not a benchmarked purchase
recommendation. Before months-long subsecond collection, profile and optimize
candidate evaluation and shared immutable features, batch neural inference, and
retain exact event causality. Skipping empty clock ticks is only equivalent if
all policy inputs/feasibility remain equivalent; order age and time-to-expiry
can change without a new trade.

At full 64-event history, a compact float32 training sample uses approximately
2.5–5 KB depending on item count. Saving one sample every 500 ms for 90 days is
roughly 40–80 GB before indexing/metadata; every 100 ms is about 200–400 GB.
Naive Python/JSON storage is larger. Stream/shard or sample decision states;
reusing each market-history block avoids much duplication. Network context is
64 received events, not all months of ticks: the long outcome horizon changes
label collection rather than requiring months-long backpropagation.

For scale only, the earlier 320-update CPU fit took 9.756 s at batch size 32.
Linear extrapolation to 15.55 million samples would be about 4.1 h per epoch,
or 20.6 h for 77.76 million, **before large-dataset I/O and with no guarantee the
small-pilot throughput transfers**. Current fitting is capped at 2,000 updates
and 1,200 s, so these are planning figures, not authorized jobs.

The local 486k-row SQLite cache is about 339 MiB. At the same verbose layout,
120 million rows would be roughly 82 GiB before temporary indexes and additional
provenance. Prefer immutable compressed partitions and an index. The separate
spot archive already advertises approximately 77 GB compressed, unparsed; its
storage and decoding costs are not included in the futures benchmark.

## Replay examples

Open [the event step-through](replays-v1.html), [the plot](replays-v1.png), or
[the exact journals](replays-v1.json). All use seed 11 and **hourly study decisions**;
the separate 100/500 ms runs are runtime probes, not these policy illustrations.

| Excerpt (UTC) | Policy | Decisions | Fill fragments | Holdings at excerpt end, contractual |
|---|---|---:|---:|---|
| June 6, 00:00–04:00 | original calibration | 4 | 8 | 1.0101 BTC; 99,378.19398 USD |
| August 17, 00:00–04:00 | original held-out | 4 | 8 | 1.0001 BTC; 100,000.53998 USD |
| August 17, 00:00–04:00 | selected small_tight | 4 | 0 | 1 BTC; 100,000 USD |

June 6 details:

| UTC | Event |
|---|---|
| 00:00:00.000 | Submit buy .0100 Dec26 @ 62,012.5 and sell .0099 Mar27 @ 63,187.5 |
| 00:00:00.138 | Creation reaches simulated exchange |
| 00:00:00.278 | Policy receives acknowledgement |
| 00:04:11.092 | Mar sell fills .0099 @ 63,187.5; opposing source print 63,272.5, ID 432723868 |
| 00:04:11.282 | Policy receives that fill report |
| 01:00:00.000 | Amend remaining Dec buy .0100 to 62,597.5 |
| 01:11:57.477 | Dec buy fills .0080 @ 62,597.5 |
| 01:12:42.759 | Remaining .0020 fills at the same limit |

Fills occur at posted limits when an opposing native print strictly crosses them,
subject to the 10% shared participation cap after native amount conversion and
lot rounding. A source print is evidence for this hypothetical fill rule, not
proof that our unplaced order would have filled on the real exchange. The earlier
leg can fill alone; the chart and journals preserve this exposure and delayed
observability. Excerpt-end holdings are not complete-horizon performance labels.

## Reproduction and checks

From the repository root; use the existing cached exports, no network:

```bash
python -m unittest tests.post_decision_value.test_unified \
  tests.post_decision_value.test_analytical_study \
  tests.post_decision_value.test_accounting tests.test_funded_ledger \
  tests.test_paired_transfer_economics tests.test_paired_execution_study -v

python -m research.post_decision_value.unified \
  --daily-root /path/to/dec_mar_inputs \
  --metadata-root /path/to/btc-maturity-inputs \
  --archive-cache /path/to/existing-gcs-key-cache \
  --database /path/to/new-unified.sqlite --report /path/to/unified.json

# Extract the committed analytical-90day-v1.tar.gz to obtain its episodes folder.
python -m research.post_decision_value.replay_examples \
  --root /path/to/dec_mar_inputs --study /path/to/analytical-final \
  --output docs/research/post_decision_value/replays-v1.json
python docs/research/post_decision_value/render_replays.py

python -m research.post_decision_value.cadence_benchmark \
  --root /path/to/dec_mar_inputs --output /path/to/cadence-benchmark.json
```

117 relevant tests passed, including eight new deduplication, conflict, provenance,
causal backdating, missing-prefix, gap, anomaly and bound checks. Three independent
historical re-executions matched saved decisions/candidate audits/fills, with raw
strict-through and shared-volume checks. The plot was rendered and visually
inspected; the offline viewer JavaScript was syntax and interaction checked.
Full neural/feature test discovery was attempted but two modules could not import
because Torch is absent. No neural code changed; this is not a new neural test pass.

Durable artifacts: this report; `unified-v1.json`; `historical-dedup-check.json`;
`cadence-benchmark-v1.json`; `replays-v1.{json,html,png}`; `unified-tests.txt`;
the renderer and three research modules. The large temporary SQLite is intentionally
excluded from git and can be rebuilt from the pinned source references.
