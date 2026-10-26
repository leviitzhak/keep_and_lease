# Analytical policy: complete cached 90-day study

This is a separate analytical calibration experiment, not neural training. The
unchanged full-fill contractual scorer was extracted to `analytical.py` so this
runner does not require PyTorch. The original neural pilot and its configuration
are unchanged. No exchange, data purchase, download, deployment or infrastructure
operation is performed.

## Frozen protocol (before replay)

All dates below are UTC, full 24-hour days, with exclusive midnight endpoints.

| Set | Inclusive dates | Days | Use |
|---|---|---:|---|
| Calibration | 2026-06-06–2026-07-29 | 54 | Rank four predefined grids; retain two |
| Validation | 2026-07-30–2026-08-16 | 18 | Choose one of the retained grids |
| Test | 2026-08-17–2026-09-03 | 18 | Frozen selected grid vs original grid and hold |

The complete local export has 180 raw daily files for BTC-25DEC26 and BTC-26MAR27.
All hashes, byte sizes and row counts are checked against existing GCS receipts.
This is the complete **cached two-contract dataset**, not the separate multi-year
Deribit archive of 540 contracts. Multi-year metadata is locally available, but
its raw tapes are not in this export, and observed settlement bridges are not
available to this adapter. Existing unrelated full-history studies are not
results of this policy.

Each split starts with 1 BTC and USD 100,000 and causal prior market observations.
Positions, cash, pending instructions and orders persist across all days within
that split; no daily portfolio reset. Portfolios reset only at the boundaries
between calibration, validation and test, preventing labels/positions crossing
the holdout boundary. Seeds 11 and 29 use counter-keyed common latency scenarios.
All trades are replayed. Decisions occur hourly, independently of trade arrivals;
this is a deliberately different cadence from the two-minute neural smoke test.

The four grids are the Cartesian product of:

- quantities `{0.005, 0.01}` or `{0.0025, 0.005}` BTC;
- offsets `{-50, 0, +50}` or `{-10, 0, +10}` bp from the last received trade.

Both pair directions and leg ratios 1 and 0.99 remain fixed. All other assumptions
remain fixed: 10% trade participation, 1 bp hypothetical futures fee, initial
holding floors of 90%, 0.02 BTC asynchronous cap, finite dated-funding stress,
seeded observation/computation/delivery/report delays, strict-through prints and
lot/tick rounding. No fees or risk constraints are tuned for a better score.

Rank each grid by the **mean terminal trajectory utility across the two seeds**:
`min(BTC growth, USD growth) - 1 * path_failure`. Reject grids with any incomplete
or failed calibration/validation path. Exact ties follow declared grid order.
Validation selects one of the best two calibration grids. Write the frozen
selection before test replay. Test evaluates selected, original and hold with
identical initial states and seeds, plus selected at 10x delays. A separate
continuous 90-day replay uses only the untuned original policy and is descriptive.
The archive was used in earlier research; this is a holdout from this calibration,
not a claim that these market dates have never been inspected.

The analytical score fills all newly proposed/amended remaining quantities at
their limits in a hypothetical ledger and chooses the largest increase in joint
contractual utility. It does not model fill probability, expected waiting time,
or future opportunities. Wait/cancel have zero hypothetical gain; first-max ties
favor waiting. Consequently an unattractive order can remain resting. These are
properties to measure, not silently fix while comparing against the original.

## Candidate counts used by the neural pilot

For `n` eligible observed instruments, no outstanding uncertain orders and default
grids: `2 + 12*n + 24*C(n,2)` proposals before the budget/risk filters. The 2 are
wait and emergency-cancel; 12 per instrument are 2 sizes x 2 directions x 3 prices;
24 per unordered pair are 2 sizes x 2 directions x 2 ratios x 3 opposing offsets.
Thus two instruments produce **50**, not 96. Three produce 110 before the pilot
budget truncates them to 96. The hard constructor limit is 128.

Generation order is wait, cancel/amend when relevant, lexicographically ordered
pairs, directional trades, then the reserved emergency action. Truncation happens
**before** risk filtering and does not backfill rejected proposals. It therefore
biases a larger universe toward earlier pairs; this is not an exhaustive or
balanced large-universe search. A pair's price offsets are linked/opposite, not
independently enumerated. Native inverse sizes are converted from BTC quantity
at the proposed price and rounded.

If `k` uncertain order IDs exist, new creates are suppressed: at most `k+3`
proposals remain (wait, cancel-all, one reprice per ID, emergency-cancel-all).
Pending amendments can have several possible versions; risk admission checks
all fill/no-fill subsets of at most six versions. Initial floors, asynchronous
exposure, dated funding, instrument expiry and native lot/tick constraints then
filter the list. Each accepted action produces an immediate observable
post-decision state containing pending intent and reservations, without assuming
execution. The neural scalar head ranks those states. Historical pilot counts
were 4, 5 or 50 proposed, and 3–50 admitted.

## Bounds, audit and reproduction

The old pilot's limits are unchanged. This full-period analysis has a separate
streamed input envelope: <=100,000 rows / 8 MB compressed per day, <=600,000 unique
rows / 12 MB total; <=1,200,000 events per continuous trajectory; <=20,000 decisions
and <=3,600 seconds across the study; no optimizer updates. At most 19,872
decisions are planned. This reads the already cached 9.1 MB, not a bulk download.

```bash
python -m unittest tests.post_decision_value.test_analytical_study \
  tests.post_decision_value.test_accounting tests.test_funded_ledger \
  tests.test_paired_transfer_economics tests.test_paired_execution_study -v
python -m research.post_decision_value.analytical_study \
  --input /workspace/scratch/0daf5da3421c/dec_mar_inputs \
  --output docs/research/post_decision_value/analytical-90day-v1
```

Use `--resume` to reuse complete, hash-verified episodes; an interrupted episode
is replayed. The output persists configuration, source identities and GCS URIs,
calibration shortlist and frozen selection, every candidate/decision, every fill,
daily portfolio snapshots, native final engine checkpoints using the existing
DirectoryCheckpoints codec, summaries and an artifact SHA-256 index. Every fill
is checked against its raw source, aggressor direction, strict limit crossing,
native lot and shared print capacity. No independently unobserved settlement,
spot execution or order-book depth is generated.

BTC/USD results are contractual/projected until actual supported settlement.
Two latency seeds share one market path: report their range, not an IID confidence
interval or annualized statistical claim. Selection performance is always shown
against holding, including when holding wins.
