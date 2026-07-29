# GUI specification additions

## Saved strategies

The parameter panel supports named strategy presets. Saving without a name uses
an automatic suggestion derived from the enabled assets and the current date.
A saved preset includes portfolio proportions, rebalancing, Treasury settings,
and the independent leg settings for every commodity. Presets can be loaded or
deleted.

## Per-commodity leg parameters

Silver, gold, and S&P 500 each retain an independent copy of contract
selection, replicating-fund, long-futures, and short-futures parameters.
Treasury controls remain portfolio-level. Entry thresholds determine total
book size; maturity scoring only allocates that size across eligible contracts.

## Inspected-day portfolio

Day inspection presents the hierarchy:

1. commodity or standalone Treasury sleeve;
2. replicating-fund, Treasury/cash, long-futures, and short-futures legs;
3. individual futures contracts, including side, portfolio weight, price,
   remaining maturity, and lease rate.

## Parameter explanations and validation

Every strategy parameter has an adjacent information control. Clicking or
tapping it expands a short explanation of the parameter's role, units, and
effect without changing the parameter. Numeric controls use steps consistent
with their shipped defaults. Invalid or temporarily incomplete numeric input
is not persisted or submitted; the interface highlights the field instead of
sending an invalid value to the calculation engine.

## Plot rendering and point inspection

Common portfolio plots are rebuilt from the filtered portfolio series without
reusing canvas identifiers from a prior render. They must remain populated for
full history, a calendar year, and a custom date range.

Every general-statistics scatter supports nearest-point inspection by mouse
hover, click, or mobile tap. Details include date, contract or tenor, maturity,
the plotted values, and next-observation details where applicable. Treasury
maturity statistics plot the observed Treasury **yield**, not a price or a
generic rate label.
