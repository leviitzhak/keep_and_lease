# Single-bill full-depth search example

This standalone, USD-only research example has four decision steps at
`t=0,1,2,3` and terminal `T=4`. It is separate from the application and from
the earlier 44-input delayed Treasury model.

- [Auditable spreadsheet](Single_Bill_Full_Search_Horizons.xlsx): generated
  trades, the first trajectory, four complete search trees represented as
  path/step tables, all ten start/end pairs, losses and neural forward passes.
- [Detailed assumptions and reproduction](README.txt).
- [Simulation and training source](simulate.py), [numerical results](data.json),
  and [numerical checks](validation.json).
- [Workbook builder](build.mjs) and [workbook checks](workbook_validation.json).

Run with Python and NumPy:

```bash
python docs/research/single_bill_full_search/simulate.py
```

The fixed example uses `P(t)=95+0.5*t`, repeated one-unit aggressive buy/sell
prints, one-bill strategic actions and a four-bill inventory cap. There is no
borrowing, shorting, execution delay or fee. Orders fill conservatively at
their limit after a strictly through-limit print. The separate liquidation
label sells owned bills at successive eligible prints after the endpoint,
ignoring liquidation duration.

The first optimal trajectory buys one bill per step. It ends with USD 616 cash
and four USD-100 face-value bills. Long-term USD holdings are USD 1,016.
Sequential liquidation produces USD 1,009.50 and utility 0.0095.

Every legal continuation is searched to the requested endpoint. Along a retained
optimal continuation, every earlier state receives the same terminal USD
liquidation target. Exploratory states are labeled from their own best
continuation. Network-greedy/exploration tags describe agreement with the frozen
initial network; this exhaustive enumeration does not use epsilon sampling.

The 97-parameter network has four inputs, 16 tanh units and one scalar USD
output. It fits 61 unique state/horizon examples, including zero-horizon
boundaries, with equal total weight for each horizon. After 12,000 Adam updates,
in-sample liquidation-value RMSE is USD 0.3530969. This is a fitting diagnostic,
not evidence of generalization to other market paths.

The simulator's targets match an independent Bellman calculation and its
closing cashflows match independent arithmetic. The spreadsheet passed 286
numerical/recalculation checks and visual review of all nine sheets. Desktop
Excel was not available for application-level verification.

This directory contains executable documentation and research outputs. It is
not imported by the application, and changes under `docs/**` are excluded from
the deployment workflow.
