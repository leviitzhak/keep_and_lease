# Delayed synthetic-market training

The corrected H10 experiment compares causal adversarial pending-delay selection
with stochastic simulator execution. Both runs use all 343 original deduplicated
start/end roots, identical seed-17 initial weights, two fitted rounds of 100 epochs,
four rollout candidates, full histories and every trajectory timestep.

- [Code and reproducible commands](two_mode_code/README.md)
- [Comparison and validation report](two_mode_evaluation/REPORT.md)
- [Paired statistics](two_mode_evaluation/summary.json)

Neither mode has demonstrated policy convergence. On 32 common scenarios,
adversarial mode averaged $1,010.89 and stochastic mode $1,010.43, against
$1,012.11 for the simple comparator. The mode difference is inconclusive.
Pending events may only choose original-support arrivals strictly after now;
already realized events stay fixed.

This is executable research documentation, independent of the application.
Large generated labels, root checkpoints and binary weights are not committed;
the code regenerates them. Paths in original experiment reports preserve their
workspace provenance. Run commands from this directory instead of the original
workspace, replacing `progressive_horizons/` with the local directory prefix.

The next work moves into a private `open-trading` repository: sampled-pair H24
training and a shared-network, simultaneous two-agent exchange simulator.
Those extensions are not claimed as completed in this archive.
