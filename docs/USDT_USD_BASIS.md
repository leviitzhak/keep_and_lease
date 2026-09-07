# USDT/USD basis in the BTC research proxy

The active Binance BTC/USDT minute candles are used without FX conversion. The
engine assumes one USDT is one USD. This is an explicit provisional research
assumption, not a statement that the peg has always held. The downloaded BTC
window does not itself measure USDT/USD; no claim of peg stability during
June–September 2026 has been established by this import.

## Documented historical deviations

| Episode | Reported price | Approximate discount to USD |
| --- | --- | --- |
| October 2018 | $0.90 | 10% |
| 12 May 2022, during the Terra turmoil | $0.95 | 5% |

The October figure is reported in [Kraken's discussion of stablecoin depegging](https://www.kraken.com/learn/stablecoin-depegging),
which links the episode to reserve concerns and Bitfinex withdrawal issues.
The May figure and associated redemption pressure are documented in the
[OECD's *Lessons from the crypto winter*](https://www.oecd.org/content/dam/oecd/en/publications/reports/2022/12/lessons-from-the-crypto-winter_37bf4b9e/199edf4f-en.pdf).
These are reported episode prices, not reconstructed consolidated market lows
or persistent discounts across every exchange. Venue, quote pair, liquidity,
sampling interval and duration matter. A USDT/USDC discount also need not be
the same as a USDT/USD discount. USDT (Tether) is not UST (Terra).

Smaller but longer-lived deviations are also relevant: [Kaiko's 31 August 2023
study](https://www.kaiko.com/resources/defining-depegs-a-new-metric-for-stablecoin-stability)
found a slight USDT discount over nearly all of August, using a USDT threshold
of $0.998 and a volume-weighted measure based on hourly lows. That threshold is
not a reported monthly minimum, and a high severity score is not a percentage
price loss. This illustrates why daily average prices can hide intraday risk.

## Effect on the strategy

Let `q` be USD per USDT, `S` be BTC in USDT, `F` be the USD futures quote, and
`tau` be remaining maturity in years. Ignoring cross-venue frictions, correct
USD spot is `q*S`. The current proxy uses `S` instead:

```text
lease_proxy = r_USD - (F/S - 1)/tau
lease_FX_adjusted = r_USD - (F/(q*S) - 1)/tau
lease_proxy - lease_FX_adjusted = (F/S)*(1/q - 1)/tau
```

Thus USDT trading below $1 makes the unadjusted proxy overstate the implied
lease rate. Near spot/futures parity, a 0.1% discount causes approximately
`0.001 * 365 / 30 = 0.01217`, or **1.22 percentage points annualized** for a
30-day contract. A 1% discount produces roughly 12.2 points. These are
illustrative formula sensitivities, not measured results in the imported window.
Changing `q` also affects USD direct-holding returns and the conversion value of
inverse-futures BTC payoffs. Constant numerical denomination is not an FX hedge.

The 6 September execution audit reproduces the anomaly with **regular** futures
and identifies stale/no-trade execution as a substantial contributor; see
[BTC_EXECUTION_FIX_PROPOSAL.md](BTC_EXECUTION_FIX_PROPOSAL.md). This does not
measure or rule out USDT/USD deviations. The spot-linked stale-mark sensitivity
also keeps the parity assumption and must not be described as FX correction.

## Next research control

Add an independent contemporaneous USDT/USD feed and compare FX-adjusted with
parity-assumed runs. Use only an FX observation available at the decision time,
with an explicit maximum age; do not backfill missing FX from the future. A
genuine BTC/USD feed is another option. Either can be implemented as an adapter
that supplies the same engine-facing USD observation interface. Even with FX
correction, cross-exchange basis and candle-versus-executable-quote differences
remain. Also retain the separate existing caveat about idle BTC collateral in
the inverse-futures lease book (see TODO).


The approved observed-fill correction reduces the full zero-cost regular-futures
result to +43.7336%; a 1 bp fee per side makes it −39.8437%. Neither experiment
measures or removes the FX basis. The user's maturity-payoff equivalence supports
using inverse USD quotes as an explicit regular-futures **research proxy**, but
different terminal indices, pre-maturity BTC conversion, collateral and funding
can still prevent price equality. See the payoff derivation and CME data plan in
`BTC_EXECUTION_FIX_PROPOSAL.md`.
