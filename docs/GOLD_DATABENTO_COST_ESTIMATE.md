# Gold futures three-month cost estimate

The owner requested a cost estimate before the three-month Databento gold data
download on 9 October 2026. A request-only push on the existing operator branch
with `study: gold-three-month-cost-only-v1` and `action: estimate` runs free
Databento metadata and symbology calls, with the existing OIDC service account
and Secret Manager secret. It never submits batch jobs or streams market data.
The existing September two-contract estimate/screen path remains available.

The fixed requested window is 9 July–9 October 2026 UTC; quote the available
portion if the dataset ends earlier. Compare 1OZ (the prior gold analysis),
MGC and GC separately for trades, MBP-1, MBO and BBO-1m. The three tick schemas
are alternatives; prices must not be summed unless each is purchased.

Candidate outright contracts are Jan 2027 onward for GC/MGC, and Feb 2027
onward for 1OZ, which terminates in the preceding month. Free symbology filters
contracts actually present during the window, then retains contracts with
another eligible contract month at most three months away. All eligible
bimonthly chains have two-month gaps. Exact vendor expiration timestamps and
listing coverage must be checked against definitions before any acquisition;
this estimate does not purchase definitions. No continuous series or spreads
are included. No ETF, spot or other underlying data is included.

The request supplies an RSA public key; only encrypted diagnostic evidence
is uploaded as an artifact. Free cost metadata and sanitized failure status
are also available in the workflow log so the quote remains readable when
artifact transfer is unavailable. No secrets or licensed market records are
printed. Estimates are not an invoice, account credit balance or storage cost.

Installing this operator-only addition uses `[skip ci]`, followed by a
request-only push. Neither push deploys the application. A cost estimate does
not authorize a paid download; report the quote before acquisition.
