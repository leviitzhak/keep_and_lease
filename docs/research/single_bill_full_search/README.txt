Single-bill full-depth search and all-horizon training
Prepared 1 November 2026

This is a NEW reduced diagnostic for the requested four actual decision steps.
It is not the earlier four-history-observation Treasury checkpoint and does not
change or deploy the repository's production/research pipeline.

Open Single_Bill_Full_Search_Horizons.xlsx. The workbook has the six requested
sheets (trades, first trajectory, four searches), plus All pairs, Training,
and Network for the horizon and fit audit.

Experiment
Four decisions t=0,1,2,3 and terminal T=4. Initial capital USD 1000, no bills.
Midprice P(t)=95+0.5*t. Face value USD 100 at maturity t=10.
Each interval k repeats two one-unit aggressive prints:
  sell at k+0.25, price P(k+0.25)-0.25;
  buy at k+0.75, price P(k+0.75)+0.25.
The identical timing, sizes and offsets continue through interval 8, providing
enough subsequent prints to liquidate every supported terminal portfolio.
There is one deterministic market law, known to the planner, and no stochastic
market scenarios, execution jitter, fees, shorting or borrowing in this example.

Actions: wait, buy one bill if cash and the four-bill cap permit, or sell one
owned bill. A buy limit is P(t)+0.25; a sell limit is P(t)-0.25. A strictly
through-limit opposite-side print fills at the posted limit. Every admitted
order fills within its interval, so the next decision has no pending messages
or live orders. This is a deliberately simplified synchronous state schema.

Liquidation at endpoint t2 starts strictly AFTER t2. It sells at the first
eligible subsequent aggressive buy print, consumes at most one unit per print,
and continues until all bills are sold. These closing fills execute at the
print price, following the prior audit's separate subsequent-print label rule.
Liquidation duration is ignored. No strategic decisions run after t2. The
closing rule is fixed, not an adversarial selection of closing times/prices.
No bill redemption is added after a bill has been sold.

The long-term economic USD quantity is cash + face_value * bill_quantity.
This differs from both current liquidation and terminal liquidation.
Utility U(L)=max(L/1000-1,0)-10*max(1-L/1000,0).
Only USD is a commodity; BTC is absent.

Search and targets
At state time ti, search stops at min(t2,ti+depth_search). Depth=5 > T=4,
so every branch reaches its actual endpoint. All admissible continuations are
enumerated, and the highest terminal utility wins. Exact ties retain the first
depth-first path under action order wait, buy, sell. Only its first action is
executed before another full search. Network values do not supply leaf labels.

Greedy/exploration tags are relative to the FROZEN INITIAL network's ranking
of next-state values. A non-greedy enumerated action is tagged exploration.
There is no random epsilon coin toss and no pruning. Greedy labels thus describe
network agreement, not how the exhaustive search selects its final winner.
Each step also records all admissible wait/buy/sell network scores.

The first path is buy/buy/buy/buy. Its terminal portfolio has cash USD 616 and
four bills, or USD 1016 of long-term economic holdings. Subsequent prints at
4.75,5.75,6.75,7.75 sell at 97.625,98.125,98.625,99.125, totaling USD 393.50.
The liquidation target is USD 1009.50 and utility is 0.0095 (0.95%).

Every retained optimal suffix shares its terminal liquidation target. Each of
the ten pairs 0<=t1<t2<=4 starts from the first path's state at t1 and has its
own full search. All retained pair trajectories are shown in All pairs.
For off-path states, the target is re-searched from that state to its horizon.
Blindly assigning an explored path's worse terminal result to all its shared
states would instead learn the return of that continuation, not optimal value.

The training corpus contains 34 unique reachable states and 61 unique valid
(state,horizon) rows, including h=0 boundaries. Horizon counts h=0..4 are
34,16,7,3,1. A row has weight 1/(5*count_for_its_horizon), giving each horizon
equal total influence. Repeated states are deduplicated.

Network and fit
Four inputs: (cash-1000)/400, quantity/4, time/4, remaining_horizon/4.
One 16-unit tanh layer and one scalar output: 97 trainable parameters.
v predicts LIQUIDATION USD DIRECTLY:
v = 1000 * [1 + 0.01 * (hidden dot output_weights + output_bias)].
Price and maturity are determined by time for this one fixed tape.
Random initialization: NumPy default_rng seed 20261101.
Adam: 12000 full-batch updates, learning rate 0.003 through update 6000 and
0.0006 afterward, beta1=.9, beta2=.999, epsilon=1e-8. The optimizer minimizes
the horizon-balanced USD squared error divided by 10 squared.
All rows are trained on; this is an in-sample diagnostic, not a validation/test
estimate of generalization. Training all horizons supplies horizon information
but cannot by itself establish generalization to other market paths.

Reproduction
Files: simulate.py, data.json, validation.json, build.mjs,
workbook_validation.json, README.txt.
Run with Python and NumPy:
  python simulate.py
The script deterministically enumerates, verifies, trains, and rewrites data.json.
It needs no PyTorch or model download. This run used NumPy 2.3.5.

For the workbook, use the Codex artifact-tool JavaScript runtime. Place build.mjs
in a writable temporary directory whose node_modules symlink points to the
provided CODEX_PRIMARY_RUNTIME_NODE_MODULES. Set BILL_DIAG_ROOT to this package's
absolute directory and BILL_DIAG_OUTPUT to the desired absolute output directory.
Run build.mjs with CODEX_PRIMARY_RUNTIME_NODE. No other spreadsheet libraries
are used. This is a fixed four-step fixture; changing its domain requires
updating the simulator and workbook layout together.

The workbook contains live cashflow, liquidation, utility, loss and neural
forward-pass formulas. Enumerated paths, initial-network branch tags, weights,
and training labels are recorded experiment outputs. Editing spreadsheet cells
does not rerun search or training. Rerun the scripts to generate a new experiment.

Checks
All exact labels agree with an independent backward Bellman calculation.
All 34 liquidation states agree with independent closed-form cash arithmetic.
Selected path suffixes share their endpoint target. Trade identifiers are unique.
Analytic neural gradients agree with finite differences within 5.1e-11.
Workbook values, network passes and search totals match simulator results.
A reversible weight perturbation confirms neural formula recalculation.
Every tab was visually reviewed. No formula errors were found by artifact-tool.
Microsoft Excel desktop was not available for application-level verification.

Source context
Earlier Single_Bill_Audit_Reproduction.zip, and the research branch:
https://github.com/leviitzhak/keep_and_lease/tree/agent/btc-post-decision-value-v1
The earlier experiment had a different state schema, objective and time scale.
