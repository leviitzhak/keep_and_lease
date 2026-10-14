# Retained BTC full-history research operator

This bounded read-only workflow replays the completed October 9 archive. It does
not trade, download from the exchange, change IAM, modify the archive, or deploy
an application. Installation commits use `[skip ci]`; only a subsequent fixed
request triggers the analysis. Eight independent shards run on ordinary Actions
runners, with a 120-minute limit and 30-day result-artifact retention.

Each eligible contract trains quote locations on its first third of entry-eligible
calendar history, then runs the frozen gap/location grid on the remaining tape.
It compares equal 1 ms, 500 ms and 2-second delay legs, always-posted quotes, proxy
cost, zero fees and conditional futures-only maker rebates. Every fill is audited
against its raw print and source observation. Signed fees never credit the proxy
with a futures-maker rebate. Fees cannot change sizing in these unfunded unit
probes, so fee-only cases reuse the identical fills and recompute all cash totals.

Open positions at the end are marked and exposed, not declared closed. This does
not implement the funded exposure bands, multi-pair ladders, rolls, portfolio
margin, expiry liquidation or restart reconciliation. Historical tick sizes use
the contract metadata snapshot; no historical tick-change schedule is available.
Source objects are hash checked and cached for an offline rerun using the same
CLI with `--offline`. Read `docs/research/btc_prd_full_history.py` on the research
branch for the maintained source and the resulting study documentation there.

Early 2017 trades lack exchange marks. Valid trade and index observations remain
usable for execution; when a mark is absent or nonpositive, valuation uses the
last trade price as an explicitly counted fallback. No mark is synthesized for
order execution, and fallback valuations are not exchange margin marks.
