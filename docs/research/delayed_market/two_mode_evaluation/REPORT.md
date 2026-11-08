# H10 two-mode comparison

Both modes completed two rounds of 100 epochs, with four rollout candidates, identical seed 17 initial weights and all 343 identical start/end roots. Full history and every trajectory state/endpoint were retained.

| Trained network | Action selector | Mean on 32 common stochastic scenarios | Frozen initial-network adversary |
|---|---|---:|---:|
| Adversarial | Minimum successor value | $1,010.8906 | $1,012.1250 |
| Adversarial | Mean successor value | $1,011.0352 | $1,013.5000 |
| Stochastic | Minimum successor value | $1,010.4766 | $1,011.5000 |
| Stochastic | Mean successor value | $1,010.4297 | $1,011.5000 |
| Simple buy/cancel comparator | Received-information rule | $1,012.1133 | $1,014.0000 |

Stochastic mode did not improve performance in this run. With each mode’s own selector, its paired mean return was $0.4609 below adversarial mode. Both remain below the comparator. H24 and longer horizons were not launched; convergence is not established.

The fixed adversary uses one frozen initial network, not either trained checkpoint and not an exact terminal-payoff minimizer. The stochastic evaluations use 32 held-out, event-keyed seeds 81000–81031, sharing uniforms for matching event identities. Raw files retain per-scenario actions, returns and checkpoint hashes. The uncertainty estimates in summary.json describe these 32 scenario differences; they do not include training-seed variability.

The local selector cross-check also does not support a large minimization penalty: switching the adversarial-trained network to mean selection raised its mean by only $0.1445. These results come from one training seed and one rising-price fixture, so they do not settle the general hypothesis.

## Checkpoint-selection evidence

The separate diagnostic reproduced the first adversarial fit exactly (identical weights, maximum array difference 0). Validation-MSE selection chose epoch 8, returning $1,011.50. Epoch 28 returned $1,013.50 under the frozen selected-checkpoint adversary despite worse validation RMSE. This is evidence that prediction-error checkpoint selection can miss better policies. Epoch 28 is a diagnostic finding, not a newly selected held-out winner. A subsequent experiment should use separate validation scenarios for policy-based checkpoint selection before touching fresh test scenarios.

## Semantics and validation

Adversarial mode retains causal pending-delay reselection from original support, with arrivals strictly after now and completed events fixed. Stochastic mode uses four conditional planning samples per action and independent real simulator execution. The network receives reported history; the planner still uses simulator physical state and pending-event identities. This is not a fully observation-only belief-state policy. The stochastic rollout winner selects an action, not the realized delay path. Training still has finite-rollout maximization optimism.

14 focused tests passed. All343 root states, their RNG states and initial network arrays matched between runs. Each round had 1,583 raw trajectory-state labels and 343 endpoints; only existing cross-split duplicate filtering removed labels. Final checkpoints are finite and the saved source manifest matched the source used during training.

The first stochastic target-only attempt was stopped before fitting after finding inherited planning/execution RNG. Its directory is marked INVALIDATED.txt; no targets from it were reused. The completed corrected run is stochastic_h10_v2. The broad unchanged clone-parity test was interrupted; it is not counted among the 14 passing focused tests.

## Files and reproduction

- ../two_mode_code/README.md: modes, commands and limitations.
- ../stochastic_h10_v2/results.json: completed stochastic run.
- ../corrected_h10/results.json: completed adversarial run.
- adversarial_round2.json and stochastic_round2.json: matched evaluation paths.
- summary.json: paired differences and checks.

No repository was created or published. No training or evaluation job launched by this comparison remains pending.
