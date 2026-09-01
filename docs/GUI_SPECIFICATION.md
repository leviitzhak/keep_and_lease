# GUI specification additions

## Saved strategies

The parameter panel supports named strategy presets. Saving without a name uses
an automatic suggestion derived from the enabled assets and the current date.
A saved preset includes portfolio proportions, rebalancing, Treasury settings,
and the independent leg settings for every commodity. Presets can be loaded or
deleted. The currently loaded or saved name is displayed next to the preset
controls. Editing a strategy value marks the form as an unsaved current strategy
instead of leaving a stale preset name visible. Legacy presets containing only
`min_days` are migrated to the independent long and short expiry floors.

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

Commodity frozen-curve rate-change and Treasury yield-change scatters are part of
the required result set. Calendar-year and custom-range filtering applies to their
point collections as well as to the main time series. A plot with no finite points
must state that no observations are available rather than appearing silently blank.

Each commodity sleeve also exposes a commodity-quoted decomposition. It plots
the replicating-fund and futures-plus-Treasury lease legs, their lease-book sum,
the keep book, their daily commodity-quoted returns and compounded indexes, the
underlying price index, and NAV beside its exact reconstruction. Daily return
histograms remain available. The superseded standalone-compounded and
multiplicative-contribution plot families are intentionally hidden.

Every decomposition time series participates in the same nearest-date inspection
as the other result charts. A separate scatter compares the daily-horizon lease
signal with the corresponding commodity-quoted lease-book daily return; selecting
a point synchronizes inspected-day attribution. Strategy-versus-direct-hold plots
start both paths at one and compare the strategy with the same initial quantity of
the underlying commodity.

The portfolio contribution chart shows the aggregate asset contribution and the
replicating-fund, futures-plus-Treasury, and keep-book legs for each commodity.
Transaction costs are already embedded in those net leg values and are exposed as
a separate diagnostic, not added a second time to the plotted total.

For every observation, the decomposition is required to satisfy, up to floating
point tolerance,

```text
NAV(t) = P(t) / P(0) * product_s<=t(1 + r_lease(s) + r_keep(s)).
```

## Session restoration

On startup, the server-first GUI requests the latest completed durable backtest,
downloads its canonical result from the existing result endpoint, restores the run
parameters, and rebuilds all summaries, tables, and plots without recalculation.
This is server-side Firestore/GCS persistence, so refresh, close/reopen, and another
device using the same approved Google identity see that identity's latest completed
run. Another allowlisted identity cannot list, poll, download, or cancel it. Browser
storage remains responsible only for lightweight unsaved parameter edits, named
presets, plot range, and chart order.

## Portfolio spreadsheet export

The period selector controls both plots and spreadsheet export. After a result is
run or restored, the GUI can download an Excel workbook for the active full-history,
calendar-year, or custom date interval. The workbook contains an overview with the
initial portfolio composition, the combined portfolio NAV and returns, and a long
component table with each commodity sleeve's daily effective portfolio weight, leg
weight, component value, and weighted price or price index. Component values are
explicitly labelled as values within a commodity sleeve initialized to one; futures
prices are weighted averages of the contracts held in the corresponding leg.
