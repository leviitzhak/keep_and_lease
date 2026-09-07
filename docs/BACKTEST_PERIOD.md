# Selecting a backtest period

The strategy form has **Backtest period → Start (UTC) / End (UTC)** above the
commodity weights. The API/saved JSON names are `backtest_start` and
`backtest_end`. Both are optional ISO dates or timestamps; blank uses the
available edge. Timezone offsets are normalized to UTC and naive timestamps are
UTC, regardless of the browser's local timezone. An end must be later than a
start. Invalid or too-short/no-overlap windows fail explicitly.

The boundaries include available observations at start and end. The final
observation is a valuation boundary, not an extra return interval. For a full
UTC day use `2026-06-25T00:00:00` through `2026-06-26T00:00:00`: the minute feed
has 1,440 holding intervals in that window. Date-only `2026-06-26` means midnight
at the beginning of that day. Holidays, missing marks, selected frequency and
reactivity can move the actual first/last usable interval inward; the result's
`backtest_period` records requested and actual boundaries and the GUI displays
the actual period next to the observation diagnostics.

A selected window starts a **fresh portfolio**, including fresh strategy
allocation/smoothing state. It does not continue positions accumulated before
its start, and it is not a slice of a previously compounded NAV. Execution and
comparison calculations are restricted before simulation. All intervals within
the chosen execution clock remain present. Plots/export controls continue to
select a view within the completed result; changing them alone does not rerun
the strategy.

Original contract prices and pre-window Treasury observations remain available
for causal as-of lookups; no future Treasury value is used to initialize the
window. The worker still loads the bundled market histories at cold start, and
contextual Treasury-rate diagnostics retain their existing history. This change
reduces simulated work and ledgers, not all input-loading costs. Blank bounds
retain previous accounting/results. Saved/downloaded parameter sets include the
bounds; loading an older preset without them clears the range.

CLI example:

```sh
python scripts/check-btc-minute-backtest.py --start 2026-06-25T00:00:00 --end 2026-06-26T00:00:00 --report work/btc-selected-period.json
```

The GCP preview workflow checks both the full BTC preset and a fresh one-day
GUI-selected run with 1,440 intervals, matching audit coverage and initial NAV 1.
Exact-revision evidence and timing are recorded in PR #38. The GCS trade pilot
is still the distinct one-second research runner described in
[BTC_TRADE_STORAGE.md](BTC_TRADE_STORAGE.md); the GUI uses minute candles.


Local validation: 34 focused Python tests and 35 JavaScript/HTML checks passed,
plus the production build/artifact check. The selected one-day BTC run completed
in 38.59 seconds including 33.9 seconds of cold BTC market loading, retained all
1,440 intervals and no missing returns, and used 1,190.5 MiB peak RSS. This local
measurement used inline ledgers; the production worker uses audit chunks.
Strategy return was −1.92409125%, versus −2.10221391% direct holding. These are
minute-candle proxy results, distinct from the one-second trade replay.

The browser acceptance compares selected boundaries as UTC instants, since native
datetime fields can omit zero seconds when serializing their values.
