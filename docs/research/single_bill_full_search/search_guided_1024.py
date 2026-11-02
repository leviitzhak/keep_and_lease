"""Post-hoc diagnosis: add one exact-search-selected path to 16 random paths.

Same model, seeds and optimizer schedule; reused holdouts. This is not an
untouched confirmation experiment. All horizons of each retained state train.
"""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from timeline_1024 import CONFIG, ScaledMarket, LazyLabels, evaluation_pools, fit
from longer_timelines import rollout

HERE = Path(__file__).resolve().parent


def selected_path(env):
    s = env.initial; states = [s]; count = 0
    while s.t < env.T:
        ns = [env.step(s, a) for a in env.actions_q(s.q)]
        s = ns[int(np.argmax([env.exact(n, env.T) for n in ns]))]
        states.append(s); count += len(ns)
    return states, count


def main():
    started = time.perf_counter(); deadline = started+300
    env = ScaledMarket(1024); pools = evaluation_pools(env)
    val = pools['validation'].probe(90001, 2); test = pools['test'].probe(90002, 2)
    short_test = pools['test'].short_probe()
    guided, edges = selected_path(env)
    output = dict(purpose='Post-hoc search-selected data augmentation; holdouts reused',
                  random_trajectories=16, added_search_selected_trajectories=1,
                  guided_candidate_transitions=edges, protocol=CONFIG.copy(), runs=[],
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  imported_source_sha256=hashlib.sha256((HERE/'timeline_1024.py').read_bytes()).hexdigest())
    for seed in CONFIG['seeds']:
        rng = np.random.default_rng(seed^12345); states = set()
        for _ in range(16): states.update(s for s in rollout(env, rng) if env.split(s) == 'train')
        before = len(states)
        states.update(s for s in guided if env.split(s) == 'train')
        train = LazyLabels(env, states)
        run = dict(seed=seed, trajectories=17, training_transitions=17*1024,
                   added_training_states=len(states)-before, training_states=len(states),
                   eligible_training_labels=train.label_count,
                   **fit(env, train, val, test, short_test, seed, deadline))
        output['runs'].append(run); output['wall_seconds'] = time.perf_counter()-started
        (HERE/'results_1024/search_guided.json').write_text(json.dumps(output, separators=(',', ':'), allow_nan=False))
        print(json.dumps(dict(seed=seed, test_rmse=run['test']['rmse_usd'],
                              short_rmse=run['short_horizon_test']['rmse_usd'],
                              regret=run['policy']['full_horizon_regret_usd'],
                              confirmed=run['confirmed'], elapsed=output['wall_seconds'])), flush=True)


if __name__ == '__main__': main()
