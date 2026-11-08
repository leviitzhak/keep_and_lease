# Two delay modes

The original corrected adversarial run and its sources are untouched. This copy
adds `KEEP_LEASE_DELAY_MODE=adversarial|stochastic` (default adversarial).

Adversarial mode retains the corrected max-action/min-successor-value algorithm:
pending total delays remain in original support and arrive strictly after now;
already realized physical and observed events remain fixed.

Stochastic mode uses four independent conditional pending-delay samples per
candidate action, common across actions, and maximizes mean successor value.
The pending simulator queue is not resampled during execution. New actual delays
use its configured distribution (1,2,3 with probabilities .6,.3,.1). Planning
rollouts use separate conditional pending schedules and random generators;
search picks a first action and the real simulator executes it independently.
All realized trajectory states and endpoints are labeled with terminal value.
Training still selects the maximum-return candidate rollout, so finite search
can be optimistic. Greedy common-scenario evaluation is the primary comparison.
The planner uses the simulator's realized physical state and pending-event
identities. This is not a fully observation-only belief-state implementation.

The change to independent execution is necessary in stochastic mode to avoid
selecting realized environmental luck. It means the comparison changes both the
local delay objective and the rollout execution rule; it cannot alone isolate
a pure minimization ablation. The evaluation crosses both checkpoints with both
local action selectors to separate training and controller effects further.

## Reproduction

From the workspace root:

    KEEP_LEASE_DELAY_MODE=stochastic PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 python progressive_horizons/two_mode_code/progressive.py --horizon 10 --rounds 2 --epochs 100 --rollouts 4 --workers 4 --output progressive_horizons/stochastic_h10_v2

H10 uses all 343 deduplicated original episode/start/end roots. Both modes use
seed17 initialization, the same root seeds, optimizer, 100 epochs per fitted
round, four candidate rollouts, full histories, all states, and validation-RMSE
checkpoint selection. One label is a Monte Carlo return, not an exact expected
return. A single training seed is insufficient for a general causal claim.

The discarded `stochastic_h10` target-generation attempt was stopped before
fitting because planning rollouts inherited execution RNG. Its targets must not
be reused. The corrected run uses `stochastic_h10_v2`, with source hashes.

From this code directory:

    PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 python -m unittest -v test_stochastic_delays test_pending_adversary test_curriculum

The common evaluation harness accepts repeated `--checkpoint label=path` and
writes checkpoint hashes, per-scenario returns/actions, means and standard
errors. It crosses both action-selection modes with each trained checkpoint.
Held-out seeds start at81000, with event-keyed uniforms shared across policies.
The deterministic comparison environment uses a frozen fresh-seed17 network as
its successor-value adversary; this is not a terminal-payoff worst-case oracle.

Larger horizons use `run_curriculum.py` with the same mode environment variable.
Its config records the mode and refuses mixing outputs. The prepared progression
is10,24,48,96,192,384,768,1024, gated on measured policy evidence. No H24 run or
convergence claim follows automatically from a lower regression loss. The
historical fixed-delay $1013.50 is not the corrected adversarial optimum.
