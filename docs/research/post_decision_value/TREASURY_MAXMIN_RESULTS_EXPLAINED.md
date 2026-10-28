# Treasury max–min results, explained in plain English

28 October 2026. A companion to [TREASURY_MAXMIN_RESULTS.md](TREASURY_MAXMIN_RESULTS.md), which is preserved unchanged. This explains the same saved experiment and its five figures; it does not report a new training run.

**The small learning exercise worked. The next, more realistic exercise got stuck repeatedly placing and cancelling an order, so the experiment stopped before learning from those rollouts or taking its final test.**

That is why the report can say both “the diagnostic passed” and “learning is not accepted.” They refer to different steps. We have a model that learned a small set of simple examples, plus working experiment machinery. We do not yet have evidence that the model can reliably run the repeated decision-making strategy.

## 1. What were we asking the model to learn?

Imagine a very small market with one made-up Treasury bill. Each unit pays **$100 after 28 days**. The account starts with **$10,000 and 1 BTC**. BTC stays unchanged in these Treasury examples; the bill purchases and proceeds affect the dollar balance.

At the initial decision, the allowed choices are to wait or submit a purchase for **5, 25 or 60 units**, provided there is enough available cash. Total bill inventory is capped at **60 units**. During repeated decisions, the controller can also cancel an outstanding order. Submitting an order does not mean it has filled: messages travel, trades happen, and reports arrive later.

The model gives each candidate **post-state** a score. A post-state means “what the account and pending instructions would look like just after choosing this action,” without pretending the order has already traded. The controller uses those scores to choose what to do.

There were two learning tasks:

| Task | Everyday version | What happened |
| --- | --- | --- |
| Simple diagnostic | “If I submit this purchase and then hold until maturity, what is the result? If I already own the bill and stop now, what is the result?” | Learned well enough to pass the small diagnostic. |
| Repeated-policy learning | “If I make this choice and then keep making decisions as new information arrives, what conservative result should I expect?” | Collection got stuck before a refit could happen. |

The distinction matters: learning the first task does not automatically teach the model how to value every pending order, cancellation or shorter time horizon in the second task.

### What “utility” means in every figure

**Utility is the experiment's custom score. It is not dollars, a quoted yield, an annualized return or a portfolio return percentage.** Higher is better.

The general objective rewards positive BTC and USD growth with weight 0.5 each, penalizes negative growth with a factor of 10, and subtracts 1 for a failed path. In these examples BTC is unchanged. For a complete, nonfailed Treasury outcome, the score therefore simplifies to:

`USD growth = (final dollars − 10,000) / 10,000`

`Utility = 0.5 × max(USD growth, 0) − 10 × max(−USD growth, 0)`

For example, gaining $100 is 1% USD growth and gives utility **+0.005**. Losing $100 gives utility **−0.10**. The loss receives a much larger penalty than the reward for an equal gain. Keeping the original balances gives **0**.

This also means an error of 0.001 utility is not automatically a 0.1% return error. The conversion depends on which part of the scoring rule applies. An unfinished simulation has **no utility label**; it is not assigned zero or quietly treated as a successful outcome.

### What “max–min” means here

The intended rollout target asks: **“Of the controllers we tried, which has the best worst result across the scenarios we tried?”** A controller is a rule for choosing the next action from information received so far.

Here, **J = 2** means two controllers: one always picks the highest model score; the other explores with probability **35%**. **K = 2** means two future execution-delay scenarios per controller. Each controller is run through each complete scenario. We take its lower utility, then choose the controller with the higher of those two lower values: `max_j min_k`.

For illustration only, if one controller scores 0.006 and 0.002, its worst result is 0.002. If another scores 0.004 and 0.003, its worst is 0.003, so max–min prefers the second controller. Those example numbers are not experiment results.

The worst result must come from one coherent simulated path. We cannot take the worst dollar balance from one path and the worst BTC balance from another and call that a real outcome. The controller also cannot peek at future messages or change its past decision after seeing which scenario was chosen.

“Worst” is limited to these sampled scenarios. Both use the **same synthetic trades and prices**; only future message/report delays change. This is not a worst case over future market prices. Already scheduled hidden events are preserved when states are copied, and a separate random seed is reserved to audit the selected controller.

## 2. What the synthetic examples look like

There are four kinds of case:

| Case | What it means | Correct initial hold decision |
| --- | --- | --- |
| Profitable | The $100 maturity payment exceeds the purchase price plus fees. | Buy 60 units, the allowed maximum. |
| Overpriced | Buying costs more than the eventual $100 payment, even before adding fees. | Wait. |
| Fee-erased | The bill looks slightly cheap, but its purchase fee is larger than the apparent discount. | Wait. |
| Cash-constrained | The price can look attractive, but almost all dollars are pledged; only $1 is available. | Wait, because none of the purchase sizes can be funded. |

The last row is partly a test of the funding guard. Unaffordable orders are rejected before model ranking, so getting that case right does not show that the network independently learned the funding rule.

There are **8 training cases** and **4 validation cases**. Training examples change the weights; validation examples measure performance on separate development cases. The planned final test has **8 cases**, with its generator settings fixed in advance. Its trading tapes and outcomes were not evaluated.

The splits occupy separate chronological blocks, with room for the closing buffers. The years attached to those blocks are synthetic coordinates, not claims that these were historical Treasury observations.

### Figure 1 — the data and the answers used for the diagnostic

![Three panels showing synthetic hold outcomes and immediate-closing outcomes by price and quantity](treasury-maxmin-v1-plots/data-surfaces.png)

These are the **training reference answers**, calculated from the simulated cashflows and checked independently. They are not network predictions.

**Left panel: “Generated hold-through-maturity data.”** The horizontal axis is the posted purchase price in dollars per bill. The vertical axis is the number of units: 0, 5, 25 or 60. Each dot is one allowed choice in one training case, and its color is the resulting utility if the purchase is left to fill and then held to maturity. Nearby dots can overlap.

The dots around $96.87 and $97.99 have positive hold value, especially at 60 units. Dots above $100 have negative value. The cases just below $100 also lose money because of their fees. At quantity zero the reference value is zero. Low-price cash-constrained cases have only a zero-quantity dot, because buying is not allowed.

**Middle panel: “28-day hold labels.”** This presents the same hold answers as a grid. Columns are quantities, and rows are the eight cases sorted by price. Each cell answers: “What score results from this quantity in this case if held until maturity?” The displayed 28-day horizon includes a small two-second endpoint margin after maturity.

The price labels do not show fees or cash restrictions, so use this key when reading the rows:

| Training case price | Case type | Purchase fee |
| --- | --- | --- |
| $96.51 | Cash-constrained | 0% |
| $96.71 | Cash-constrained | 0% |
| $96.87 | Profitable | 0.05% |
| $97.99 | Profitable | 0.10% |
| $99.89 | Fee-erased | 0.60% |
| $99.92 | Fee-erased | 0.60% |
| $100.64 | Overpriced | 0.10% |
| $100.86 | Overpriced | 0.10% |

White cells in the first two rows mean **inadmissible purchases**, not missing successful trades or zero utility. Each quantity-zero cell is genuinely zero.

**Right panel: “H=0 owned-inventory closing labels.”** This asks a different question: “I already bought and own this quantity. If I stop making strategic decisions now and close the position under the closing rule, what is my total outcome relative to the original account?” Here `H=0` means no more time for strategy decisions. It does not erase the purchase cost or mean that settlement takes no time.

Before maturity, the fixture provides closing trades at **$0.20 below the entry price**. Selling early therefore loses the spread and applicable purchase/sale fees. That is why nonzero positions in this panel have negative values, including bills that would have been profitable to hold to maturity. The high-fee cases near $99.90 are particularly expensive to buy and then sell.

**Read each colorbar separately.** Red means a higher score within that panel and blue means a lower score. In the right panel the highest value is zero, so red there can mean “no gain or loss,” not profit. The right panel also has a different numerical color range from the other two.

For a concrete saved example, **60 units at $96.87 with a 0.05% purchase fee** cost $5,815.1061. They pay $6,000 at maturity, leaving $10,184.8939 in the account. The USD gain is about 1.849%, and utility is **0.009244695**. Closing that already-owned position early instead gives utility **−0.0178062**, because the exit price is lower and selling has a fee too.

The useful lesson from this figure is that “good to hold until maturity” and “good to buy and immediately sell” are different questions. The model needs to distinguish them.

## 3. How well did the small diagnostic learn?

The diagnostic contains **52 complete training labels** and **26 complete validation labels**. A label is one known answer for one case, quantity and horizon; it is not a separate market history. In training, six unrestricted cases each contribute four quantities and two tasks, while two cash-constrained cases contribute only quantity zero and two tasks: `6 × 4 × 2 + 2 × 1 × 2 = 52`. Validation has the corresponding `3 × 4 × 2 + 1 × 1 × 2 = 26`.

| Measurement | Training | Validation | What it tells us |
| --- | ---: | ---: | --- |
| Cases / complete labels | 8 / 52 | 4 / 26 | How small this exercise is. Labels within a case are related examples. |
| Correct initial hold action and quantity | 8/8 | 4/4 | The chosen option was correct in every case: 60 units for profitable cases; wait for the other categories. |
| Utility MAE | 0.000231721 | 0.000565977 | Average absolute difference between prediction and the reference answer. Lower is better. |
| Maximum utility error | 0.001572084 | 0.002769321 | The single largest absolute prediction error within that split. Lower is better. |
| Normalized scalar MSE | 0.000355261 | 0.002414108 | Average squared error after dividing errors by the training label scale. Large misses count more heavily. Lower is better. |

The frozen diagnostic maximum-error threshold was **0.003**. Both splits stayed below it and all initial hold choices were correct, so both diagnostic checks passed. This is encouraging evidence about the particular examples tested. Four validation cases are not enough to establish a dependable trading policy, especially for states absent from this diagnostic.

### Figure 2 — the two learning curves

![Training and validation error during the 500-update diagnostic](treasury-maxmin-v1-plots/learning.png)

Both panels use **optimizer updates** on the horizontal axis. One update means the training algorithm has adjusted the model's weights once. It is not a market event, an elapsed trading day or a new independent case. The fit made **500 updates**; the saved curve has a measurement every 25 updates, so it contains **20 plotted checkpoints**, beginning at update 25.

The same two lines appear in both panels:

| Line | What it measures |
| --- | --- |
| Solid blue, `diagnosis train` | Error on the 52 diagnostic labels used to fit the model. |
| Dashed orange, `diagnosis validation` | Error on the 26 separate validation labels. These labels do not drive the weight updates. |

**Left panel: normalized scalar MSE.** Each prediction error is divided by the training label standard deviation, approximately **0.0198423**, then squared and averaged. The vertical axis is logarithmic: moving from 0.1 to 0.01 is a tenfold improvement, as is moving from 0.01 to 0.001. Equal vertical distances therefore represent ratios, not equal absolute decreases.

The blue line drops from about **0.232** at update 25 to **0.000355** at update 500. The orange line drops from about **0.305** to **0.002414**. Both improve; the model remains more accurate on the examples it trained on.

**Right panel: utility MAE.** This is the average size of the errors in the original utility units, without squaring or normalization. Its vertical axis is ordinary linear scale. Training MAE goes from about **0.00747** to **0.000232**, and validation MAE from **0.00851** to **0.000566**. Most of the visible improvement happens early, followed by smaller gains.

The validation curve does not turn upward over the recorded checkpoints. That supports “the small diagnostic improved.” It does not establish performance on the pending/cancel states encountered later. There is **no final-test curve and no rollout-refit curve**, because neither stage ran.

### What changed from the earlier failed model?

The old input representation could feed the network a history age of about **38,880 minutes**, roughly 27 days, as a large raw number. The previously archived model also had **89.7% of its final Tanh activations saturated**: many outputs of that activation were near its flat extremes, where changes in the input have little effect.

The new diagnostic changed several things together:

- Time features use bounded relative scales instead of very large raw ages.
- Feature and label means/scales are calculated from training data only. Validation and final-test outcomes do not set those scales.
- A small feed-forward network, with **two layers of 48 hidden units**, uses SiLU activations. It has **3,409 trainable parameters**.
- It predicts one scalar utility, so there are no competing auxiliary prediction losses in this diagnostic.

This combination worked on the small exercise. Because all these changes were made together, the experiment does not identify which one caused the improvement.

The saved records also include training-health measurements. The recorded gradient norm falls from about **0.474** to **0.000873**; that measures the size of the gradient before clipping, not profitability. The largest absolute activation in the recorded first hidden layer rises from about **1.48** to **2.55**. These are useful debugging readings. They are not additional curves in the displayed figure, and the SiLU saturation field is unset rather than a measured “0% saturation.”

## 4. Where are the prediction errors?

### Figure 3 — predictions versus known answers

![Validation prediction scatter and the ten largest signed validation errors](treasury-maxmin-v1-plots/reference-errors.png)

**Left panel: “Validation predictions.”** Each blue dot is one of the **26 validation labels**, although some overlap. The horizontal coordinate is the independent diagnostic answer; the vertical coordinate is the network prediction. Both coordinates are in utility units.

The black diagonal is the **perfect-prediction line**, `prediction = reference`. A dot on it is exactly right. A dot above it is too optimistic; a dot below it is too pessimistic. Closeness to the diagonal shows that the model reproduces these simple hold/closing values fairly well. This is not a chart of realized trading returns.

**Right panel: “Largest validation errors.”** The ten orange bars show the labels with the largest absolute errors. The horizontal value is signed: `prediction − reference`. A bar to the right of zero means overestimation; a bar to the left means underestimation. The longest bar is about **+0.002769**, consistent with the maximum-error table. Bar length measures the size of the mistake, not the size of a position.

The vertical labels use the compact format **`case number / horizon`**. For example, `1 / 28 d` means a hold-to-maturity example from validation case 1. `0 d` means an immediate-closing example. The case key is:

| Validation case number | Type | Posted price |
| --- | --- | ---: |
| 0 | Profitable | $97.39 |
| 1 | Overpriced | $101.03 |
| 2 | Fee-erased | $99.94 |
| 3 | Cash-constrained | $98.48 |

The same label can appear more than once because the chart omits the quantity: different quantities in the same case and horizon have different errors. The bars are ranked by absolute error, with the largest at the top; they are not a time sequence.

These references match the **diagnostic hold/boundary task**. Comparing the diagnostic network to a different rollout objective would answer the wrong calibration question.

## 5. Why did the repeated simulation get stuck?

After the diagnostic, the experiment tried to gather examples of the model making repeated decisions. At a **two-day horizon**, it encountered pending-order and cancellation states that had not been validated by the simple hold/boundary exercise.

The saved trace shows the following pattern: place an order, receive an order report, choose to cancel, receive a cancellation report, place an order again, and repeat. Reports are legitimate new information, so the event clock correctly wakes the controller to reconsider its action.

The model gave the selected create post-state a score around **0.00920** and the selected cancel post-state a score around **0.01005**. These are predictions in different successive states. We should not read them as two options evaluated in one identical state, or add their difference up as repeated earnings.

### Figure 4 — the cancel/repost loop

![First 100 decisions from the longest incomplete rollout, showing alternating create and cancel instructions](treasury-maxmin-v1-plots/collection-churn.png)

Both panels share a horizontal axis of **simulated seconds since the first displayed decision**. The image zooms in on only the **first 100 decisions**, spanning roughly ten seconds. Those seconds are simulated market time, not the CPU time spent running the program.

**Top panel: the blue zigzag line.** Each dot is the predicted utility of the action selected at that moment. The lower points, around **0.00920**, correspond to creates. The higher points, around **0.01005**, correspond to cancels. The connecting line makes the alternating pattern easy to see; it is not account equity, a market price or accumulated profit.

**Bottom panel: the action dots.** Blue dots on `create` mean an order was submitted. Orange dots on `cancel` mean cancellation was requested. The `wait` row is empty in this excerpt. The vertical positions are category labels, not numerical utility levels. A create dot does not establish that a purchase filled.

The full saved branch contains **14,999 decisions: 7,500 creates and 7,499 cancels**. There were **14,998 account/order-report trigger occurrences**, so reports drove almost all of the loop. The branch hit its **30,000-event replay ceiling**. Across the shared campaign, the experiment used all **20,000 allowed decisions**.

This happened with the **zero-exploration controller** too. Random exploration is therefore not enough to explain the failure. The evidence is consistent with poor value calibration for these intermediate states; it does not isolate a single architectural cause or prove that one particular fix will solve it.

The run stopped under its original limits. No extra waiting rule, oracle-selected action, larger budget or retry was inserted to force a better result. The important finding is that a model can fit simple examples well and still behave badly when its own choices determine the states it visits.

## 6. What labels were actually collected?

| Saved collection | Complete | Incomplete | Unsupported | Total |
| --- | ---: | ---: | ---: | ---: |
| Training, first collection | 28 | 55 | 1 | 84 |
| Validation, first collection | 13 | 26 | 0 | 39 |

These counts describe **candidate-state/horizon records**, not numbers of trades or optimizer updates. A record may require several controller/scenario replays before it has a valid max–min label.

**Complete** means the required calculation finished. **Incomplete** means at least one required replay did not finish, so the record has no valid target. **Unsupported** means the requested horizon is outside the allowed window for that state, so it should not be simulated as if supported.

### Figure 5 — which horizons have usable labels?

![Training support map with complete zero-horizon labels, incomplete positive-horizon labels and one unsupported horizon](treasury-maxmin-v1-plots/horizon-support.png)

The horizontal axis has three requested horizons: **0 days**, **2 days**, and approximately **28 days**. The last is actually **28 days plus two seconds**, rounded in the tick label. Each row is a different saved candidate post-state, either from an initial action or from a sampled point on an outer trajectory. The row numbers are just row indices, not dates, prices or utility levels.

The colorbar is categorical:

| Color | Meaning | What we can do with it |
| --- | --- | --- |
| Green/teal | Complete | Use the finished label for the task it actually represents. |
| Orange | Incomplete | Retain the failure record; do not invent a target. |
| Gray | Unsupported | Exclude that state/horizon combination as outside the permitted window. |

The entire zero-day column is green. The positive-horizon columns are orange apart from one gray cell. **All complete collected records are boundary labels.** They do not demonstrate that the model learned a conservative value for a future period of repeated decisions.

The gray cell is a useful detail: an outer-trajectory state occurs slightly after the initial starting time. Adding a fresh full 28-days-plus-two-seconds horizon from that later state would go past the fixed decision deadline. The collector correctly marks it unsupported. It does not quietly move the deadline later.

This image shows **training** collection only. The validation counts are in the table above. Also, these zero-horizon collection records should not be confused with the earlier diagnostic's already-owned-inventory examples: both are boundary calculations, but their starting states can differ.

The campaign required complete supported records before refitting. Because that condition failed, it performed **zero rollout refits**, no second collection/refit cycle, and **zero fresh final-test evaluations**. The diagnostic curve remains the only learning curve.

The retained model is explicitly marked **`diagnostic-hold-boundary-v1`**. The intended rollout target, **`sampled-maxmin-sequential-close-v1`**, was not fitted. A later metadata correction clarified that distinction without changing model weights, optimizer state or random-generator state. Before/after hashes were kept so this clarification is auditable.

## 7. What did the software checks and independent references establish?

The delivered checkout reports **236 passing software tests**: **153 post-decision tests**, including **25 new semantic/integration checks**, plus **83 existing funded-ledger, transfer-economics and execution regression tests**. The 25 new checks are included in 153, not added on top of 236.

These tests check implementation behavior: accounting, cancellations, partial closes, obligations, fees, event timing, budgets and related mechanics. Passing them is useful evidence that the machinery follows its rules. It does not certify profitable strategy behavior.

The main implementation changes mean the following:

| Component | Plain-language purpose |
| --- | --- |
| `liquidation.py` | Work out what remains when strategy decisions stop, using a copied account so the original state is not altered. |
| `robust_rollout.py` | Copy a post-state and its clocks, run matched complete scenarios for each frozen controller, calculate max–min, audit the winner and enforce shared budgets. |
| `treasury_fixtures.py` | Generate the small bill examples, enforce cash/quantity restrictions and provide independent reference arithmetic. |
| `treasury_model.py` | Provide the small Treasury-specific scalar network and its training-only normalization. Existing Transformer checkpoints keep their original meaning. |
| `treasury_learning.py` | Run the frozen experiment stages, stop on failures or caps, and allow a final test only after the preceding stages succeed. Later code paths exist even though this campaign never reached them. |
| `treasury_plots.py` / `treasury_artifacts.py` | Draw figures from saved evidence and package the source, records and checkpoints so they can be checked and restored. Event traces distinguish hidden arrivals/trades from information actually received by the controller. |

### How closing is valued

Under this experiment's closing convention, the calculator cancels outstanding and in-flight instructions atomically, releases reserved funds, then uses subsequent suitable trades in chronological order to close positions. It uses those trade prices, the instrument's lot sizes, the declared participation limit and fees. Partial closes can span several trades. Dated obligations and Treasury redemption are accounted for once, and the code does not silently buy BTC to repair a balance.

The two-day closing buffer supplies a bounded amount of extra data to resolve the account. If closing cannot be completed, there is no complete utility label. Closing duration is ignored in the current strategic horizon and score; this is not a study of how fast positions can be liquidated.

These are explicit simulation assumptions. Atomic terminal cancellation and the declared print-based liquidity convention should not be read as measured real-market guarantees. Future trades can be used offline to calculate labels, but the controller only sees received information when choosing an action. Treasury payments remain contractual projections.

### The three kinds of reference

**Independent hold/closing arithmetic** recalculates the simple answers from purchase costs, fees, exit proceeds and redemption. It does not ask the neural network what the result should be. This is the reference behind the diagnostic data and prediction-error figures.

**The signed-fill audit** reconstructs the account using actual saved simulated fills: buys spend cash, sells receive cash, and fees and redemption are applied separately. It then recalculates the same joint max–min statistic for complete records. This checks the realized controller's accounting; it does not replace its decisions with hindsight-optimal actions.

**The finite toy oracle** is a small exhaustive reference solver. It considers two fixed-price purchase opportunities, quantities 0/5/25/60, the 60-unit cap, the same fees and cash restrictions, one bill and its $100 maturity payment. The second choice can depend on fills already reported, not future information. Under these restricted constant-price assumptions, intermediate purchase/cancel behavior cannot beat the enumerated zero/60-unit endpoints.

The oracle implementation was tested, but the campaign stopped before its planned policy/oracle comparison: the resource report records **zero campaign oracle-controller enumerations**. There is therefore no measured model-to-oracle performance gap, final-test policy-comparison plot or final-test account-trajectory plot in this result. The oracle is not a general optimum for changing prices, arbitrary sells, multiple assets or long uncertainty trees.

## 8. Which stages finished?

| Stage | What it was supposed to do | Actual result |
| --- | --- | --- |
| 0 — Freeze | Write down settings, seeds, split boundaries, pass criteria and resource limits before fitting. | Done. Source and fixture hashes identify what was used. |
| 1 — Labels | Check that outcome labels agree with independent accounting. | Done for the diagnostic, with software checks for closing and account mechanics. |
| 2 — Diagnosis | See whether the model can learn the easy hold/boundary controls. | Passed on training and validation. |
| 3 — Collector | Gather repeated-decision outcomes for max–min learning. | Code implemented/tested; campaign collection retained incomplete records and hit its caps. |
| 4 — References | Audit cashflows and compare against the restricted exact reference. | Reference code implemented/tested; campaign policy/oracle comparison was blocked. |
| 5 — Bounded learning cycle | Collect, refit, recollect, refit, then run one fresh final test. | Stopped during first collection. No rollout refit or final test. |
| 6 — Publication | Preserve enough evidence to inspect and reproduce the result. | Configs, source, samples, checkpoints, traces, figures and a verified archive were retained. |

## 9. How much work did this run use?

| Recorded quantity | Value | How to read it |
| --- | ---: | --- |
| Elapsed campaign time | 88.33 seconds | Time on the wall clock for the bounded campaign. The overall cap was 240 seconds. |
| CPU time | 88.32 seconds | Processor time consumed; close to elapsed time in this single-thread run. |
| Optimizer updates | 500 | All belonged to the diagnostic. The planned aggregate maximum was 1,200. |
| Timed optimizer-update work | 0.301 seconds | A narrow timer, not the complete training phase. |
| Decisions | 20,000 | The shared decision budget was exhausted. |
| Exchange/report/closing events | 43,312 | Cumulative events across branches. This can exceed the 30,000-event limit for any one replay. Events and decisions are different counters. |
| Distinct input rows | 372 | Small synthetic input data, not 372 independent market experiments. The input-row cap was 100,000. |
| Compressed input bytes | 5,416 | The measured compressed input size, not the size of all checkpoints, traces or the archive. The cap was 8,000,000 bytes. |
| Peak memory | About 1.16 GiB | Peak process resident memory, including the runtime and libraries. |
| Campaign oracle enumerations | 0 | The comparison stage was not reached; its maximum budget was 4,096. |

The run used ChatGPT's Linux workspace, an **AMD EPYC 9V74 CPU**, one Torch/BLAS thread, **Python 3.12.14**, **Torch 2.14.1+cpu** and **NumPy 2.3.5**. It did not run on the user's Windows machine or GCP.

The **0.301-second** figure needs particular care. The executed version timed optimizer-update work without separately timing all normalization, validation and checkpoint writing. The full fitting-phase duration was not recorded. The entire campaign took only 88.33 seconds, so fitting was necessarily below the 120-second fitting cap, but we cannot recover a precise complete fitting time from that narrow timer.

The final source corrected the timer to include the full fitting phase, including interrupted fits. That correction was unit-tested without another training run. Software tests, plotting and packaging are separate work; the 88.33 seconds is not the total time spent developing and publishing the project.

## 10. What was saved, and what does reproduction prove?

The [machine-readable report](treasury-maxmin-v1-report.json) contains the final status and counters. The [download/checksum receipt](treasury-maxmin-v1-artifacts.json) identifies the published archive and the checks performed. The [complete bundle](treasury-maxmin-v1.tar.gz) contains the frozen settings, executed source snapshot, diagnostic data, collected records, model checkpoints, learning measurements, traces, figures and verification code.

A checksum is a fingerprint of file bytes. The published archive was downloaded from an immutable commit, its SHA-256 and size were checked, every manifest entry was verified, and the archive was safely restored. Its standalone verification reproduced **four saved predictions** and independently recalculated **52 reference values**. That demonstrates that the saved result can be recovered; it is not a new test of trading performance.

The archive belongs to artifact commit **`cd7839d46ed0a7004546d7d6a6a36844dc959b73`**. It contains the **235-test publication snapshot**. The subsequent fitting-timer regression brings the final delivered checkout to **236 passing tests**. These numbers refer to successive snapshots, so they are not a conflicting count of one test run.

For exact commands and the executed source SHA-256, use the [original report's reproduction section](TREASURY_MAXMIN_RESULTS.md#resources-and-reproduction). The commands serve different purposes:

| Operation | What it does |
| --- | --- |
| Software test commands | Check implementation behavior. Their pass count is not a learning result. |
| `verify` or standalone `verify_inference.py` | Check retained examples and predictions from the saved artifacts. |
| `plots` | Recreate figures from saved evidence. |
| `restore` | Verify and extract the archived bundle into a new location. |
| `run` | Start a new bounded campaign in a new output directory. This is new experimental work, not simply opening the existing result. |

The configuration defines the training/evaluation contract. There is no separate command intended to silently rerun an allegedly untouched final test. This explanatory rewrite only reads the existing evidence and reuses the original figures.

## 11. What can we conclude, and what remains to do?

We can conclude that the revised small model learned the initial purchase-and-hold choices and immediate-closing values in the diagnostic, and that the saved artifacts make this inspectable. We also have a concrete failure trace: repeated decisions can produce a create/cancel loop and exhaust the campaign budget.

We cannot conclude that repeated max–min learning succeeded, that the final policy beat cash holding or the oracle, or that the approach is profitable on historical or live Treasury markets. The fresh test was not evaluated. The study used a single synthetic bill, projected contractual payments and delay uncertainty on a fixed trade tape. It did not establish real liquidity/depth, price-risk robustness or performance across assets.

The proposed next bounded learning step is to cover **short horizons and pending, confirmed and cancellation post-states** before attempting repeated collection again. A follow-up needs to show that values become better calibrated while preserving the event semantics and fixed objective; merely suppressing the visible churn would answer a different question.

That follow-up was not performed in this campaign. The policy counts down to fixed deadlines; rolling horizons and choosing horizons by a value-per-time score remain separate experiments. The local explorer and broader market simulator also remained deferred in the original report. This result is research evidence, with no deployment or live trading.
