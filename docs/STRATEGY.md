# Strategy Specification

## Objective

Construct a portfolio that captures relative carry and lease-rate opportunities while controlling total exposure and allowing different maturities to be held on the long and short sides.

## Portfolio components

The portfolio may contain:

- a physical-backed commodity ETF;
- long commodity futures;
- short commodity futures;
- Treasury or cash instruments;
- a benchmark allocation used for comparison.

Long and short futures are separate books. They may both be active when different parts of the curve provide opposite opportunities.

## Signal and execution timing

1. Observe prices, rates, maturities, and eligibility on trading day `t`.
2. Compute target allocations using information available on day `t` only.
3. Execute the target change on trading day `t+1`.
4. Attribute day `t+1` return to the positions actually held during that day.

This one-day shift is mandatory to avoid look-ahead bias.

## Eligibility before ranking

Ranking never overrides economic eligibility.

### Long futures

A contract may enter the long candidate set only if its lease rate is above the configured long eligibility threshold. A maturity bonus cannot make an ineligible long contract tradable.

### Short futures

A contract may enter the short candidate set only if its lease rate is below the configured short eligibility threshold. A maturity bonus cannot make an ineligible short contract tradable.

The short book may select short-dated or long-dated contracts. Maturity is a preference, not a hard exclusion, after the eligibility gate is satisfied.

## Contract ranking

Eligible contracts receive:

1. a base economic score derived from lease rate or carry;
2. a relative maturity-line adjustment described in [SCORING.md](SCORING.md);
3. optional constraints such as minimum time to expiry, tradability, or missing-data rejection.

The final scores determine allocation weights within each book.

## Position sizing

Target exposure should be gradual rather than binary.

- No or minimal position near the neutral threshold.
- Increasing position as the signal moves farther from neutral.
- A configurable maximum gross or book-level allocation.
- Optional minimum holding period or turnover control.
- Long and short allocations normalized separately, then combined under total-risk constraints.

When several contracts are selected, weights should reflect their positive ranking strength after normalization. The proportions should remain interpretable and sum to the requested book exposure.

## ETF and Treasury transition

The default transition between Treasury/cash and the physical commodity ETF should be gradual around the ETF expense-ratio threshold, with a configurable transition band. The current intended default is approximately `±1 percentage point` around that threshold, subject to confirmation in implementation defaults.

## Rolling

Futures must be rolled before they cease to satisfy operational constraints. Rolling rules should:

- preserve the intended economic exposure;
- use only information known at the decision date;
- record the outgoing and incoming contracts;
- separate roll P&L from ordinary mark-to-market P&L where possible.

## Risk and accounting outputs

For each day, retain:

- target and executed positions;
- gross and net exposure;
- selected contracts and scores;
- ETF, futures, Treasury, financing, fees, and roll return components;
- benchmark return;
- cumulative return and drawdown.

## Invariants

- No future information enters a signal.
- Ineligible contracts receive zero target weight.
- Allocations respect configured caps.
- Long and short books can coexist without netting away contract-level intent.
- Every selected contract can be explained from its inputs, base score, adjustment, and final score.
