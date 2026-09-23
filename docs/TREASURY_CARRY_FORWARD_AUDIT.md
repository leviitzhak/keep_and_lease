# Treasury carry-forward audit: exact retained vintage and generated values

Verified 2026-09-15 from the six exact rate CSVs in the retained preliminary
study package. Their SHA-256 hashes match the original diagnostic provenance.
This is an explanation of existing behavior, not a refresh of historical yields
or a claim that these were the actual later market rates.

The opt-in cost-aware paired policy implemented on 2026-09-16 now uses a
separate refreshed snapshot, normalized 91-day investment yield, rate-age gate
and a later modeled publication delay. Those changes do not rewrite this retained
vintage or its results. See
[COST_AWARE_FUNDED_TRANSFERS.md](COST_AWARE_FUNDED_TRANSFERS.md#versioned-treasury-inputs).

## Last observations

| Series | Code tenor (days) | Last observation | Raw rate (%) |
|---|---:|---|---:|
| DTB3 | 91 | 2026-07-14 | 3.71 |
| DTB6 | 182 | 2026-07-14 | 3.79 |
| DGS1 | 365 | 2026-07-14 | 4.02 |
| DGS2 | 730 | 2026-07-14 | 4.18 |
| DGS3 | 1095 | 2026-07-14 | 4.23 |
| DGS5 | 1825 | 2026-07-14 | 4.31 |

`read_rates` divides those percentages by 100. `asof_rate` keeps the last
available observation; no later rows or linearly extrapolated future yields are
created. `_rate_available_at` treats date-only observations as available at the
NEXT UTC midnight for intraday queries. Thus the July 14 vector applies from
2026-07-15T00:00:00Z onward in replay/study timestamps. During July 14 intraday,
the July 13 vector is still used: 3.76, 3.87, 4.12, 4.26, 4.30, 4.37 percent.
Date-only daily-close queries may use a row on its observation date instead.

The six TENOR NODES are flat through subsequent calendar time, but the curve is
not flat across maturity. `usd_rate` linearly interpolates between tenors, clamps
D<=91 days to 3.71%, and clamps D>=1825 days to 4.31%. For 91<=D<=182:

```
r(D) = 0.0371 + (D-91)/91 * (0.0379-0.0371)
```

A fixed-expiry bond can therefore move down the frozen maturity curve as D
shrinks even without new yield observations. The clamp is not observed 1-day
or 3-day Treasury data. Later calendar-date carry-forward also is not evidence
that the real market yield stopped changing.

## Existing BTC trade replay: cash accrual, not an actual bond-price history

`btc_trade_backtest.py` passes the shortest 91-day rate to TapeAccount, regardless
of the individual futures maturity. The replay therefore accrues its cash at
3.71% after that availability boundary, while the LEASE SIGNAL still uses each
future's maturity-matched interpolated rate. A matched-maturity GUI parameter
must not be read as evidence of an actual maturity-matched security in this path.

`TapeAccount.accrue` updates at chronological trade/decision/rate/expiry events:

```
interest = cash_before * r * elapsed_seconds / (365*86400)
cash_after = cash_before + interest
index_after = index_before * (1 + r*elapsed_seconds/(365*86400))
```

Each interval uses simple interest on the then-current balance; successive
intervals COMPOUND. At constant r and very short steps the factor approaches
exp(r*elapsed_days/365), not 1+r*total_days/365. Actual cash also changes with
spot trades, fees and immediate futures mark P&L. No security ID, bond face or
observed Treasury price series is generated for this replay cash balance.

## Synthetic matched-maturity bond in the preliminary holding study

This is a DIFFERENT construction: fixed Treasury face L, initial value A and
same expiry as the future. It uses the retained curve numbers as annual-effective
yields for the synthetic zero-coupon price (not a corrected real bill convention):

```
P(t,T) per 100 face = 100 * (1+r_t(D_t))^(-D_t/365)
B_h / A = (1+r_0)^(D_0/365) / (1+r_h)^(D_h/365)
```

No maturity interest is paid early: liquidation uses the remaining-maturity
synthetic price. At D=0 the bond pays its face. With identical r throughout the
relevant maturity segment, B_h/A=(1+r)^(h/365), which is not exactly linear.
At one FIXED remaining tenor the generated price stays unchanged while that
curve is frozen; a FIXED EXPIRY moves toward par as its remaining tenor shrinks.

Illustrative generated values, not observed securities, after July 15:

| Remaining days | Curve yield (%) | Synthetic price per $100 face |
|---:|---:|---:|
| 1 | 3.710000 | 99.990020 |
| 3 | 3.710000 | 99.970063 |
| 10 | 3.710000 | 99.900246 |
| 30 | 3.710000 | 99.701037 |
| 91 | 3.710000 | 99.095898 |
| 120 | 3.735495 | 98.801514 |
| 182 | 3.790000 | 98.162221 |
| 201 | 3.813880 | 97.959911 |
| 365 | 4.020000 | 96.135359 |

Same initial $100 invested, flat 3.71%, no fees or cash flows:

| Elapsed days | Replay-style accrual, regular 0.5-s steps | Synthetic fixed 30-day bond |
|---:|---:|---:|
| 0 | 100.000000 | 100.000000 |
| 1 | 100.010165 | 100.009981 |
| 10 | 100.101696 | 100.099854 |
| 30 | 100.305397 | 100.299860 |

The actual replay adds trade-event boundaries to the 0.5-s decision grid; its
exact index is the product over those real intervals, not this illustrative
regular-grid example. A $100 FACE 30-day bond starts at $99.701037 and reaches
$100, unlike a bond position with $100 INITIAL MARKET VALUE.

Legacy daily/candle code also has separate `bond_return(mode='accrual')` and
synthetic mark-price modes; do not conflate those with the tape account or the
fixed-lot event study. In accrual mode it multiplies simple segment returns;
mark-price mode uses successive synthetic discount prices.

## Conventions and implementation gate

DTB3/DTB6 are discount-basis bill benchmarks; DGS1/2/3/5 are constant-maturity
investment-basis benchmarks, not zero yields or actual same-expiry prices.
The retained reader only divides by 100: it does not harmonize those conventions.
The study's use of these numbers in an annual-effective discount formula and
the replay's simple-accrual rule must remain labeled approximations. Refresh and
normalize inputs in a new version before new strategy acceptance, expose data
age and compare results without overwriting the old calculation trail.

Sources: `backtest_silver_lease_strategy.py` read_rates/asof_rate/usd_rate,
_rate_available_at, accrued_yield_return/bond_return; `btc_trade_backtest.py`
rate assignment; `trade_replay.py` TapeAccount.accrue/on_trade. Code inspected
at 173eb302a17b4129982f2a81a697c8f0fb82654d. The study's unchanged
`analyse_events.py` and METHODOLOGY.md retain the fixed-face growth formula.

Rate-file SHA-256:

```
DTB3 b4b08495bf58f09548c73e00190d454f577e4cf6dcf4acc7bda965a73e73e29b
DTB6 473f42077b9c17b937d4176f3e68657b2f3cbd36f3e5e8426dfebc5038ba9023
DGS1 a31932d5fb868927ffa8f4718be88d49052123a3d40851be1ab479ecdaa88874
DGS2 1225a0684f290a6b57e34f4f9df02a1650e05ffc846e35595198f92bc56fc854
DGS3 2cad75b1db4a442c852808c5380436095731c277a32853e333b76b9c23dd1b9f
DGS5 4eff5750675a518ac9e60b489129ca38616120aef20ba22f4d35388644189f8f
```

Verification: all six retained hashes/last observations matched; original as-of
functions returned the same last vector at July 15, August 1 and September 4;
next-midnight availability, maturity interpolation, synthetic prices and source
cash-accrual recurrence were checked. This does not certify a live backtest or
correct the known quote-basis and frozen-data limitations.

Definition references (not replacements for the retained source data):
https://fred.stlouisfed.org/series/DTB3
https://fred.stlouisfed.org/series/DGS1
