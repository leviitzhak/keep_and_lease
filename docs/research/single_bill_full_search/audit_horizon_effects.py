"""Post-hoc error and target-geometry audit; no training or parameter selection."""
from pathlib import Path
import json
import numpy as np
from longer_timelines import Market, Net, evaluation_set
from timeline_1024 import ScaledMarket, LazyLabels

HERE = Path(__file__).resolve().parent


def restore(run):
    net = Net(0)
    net.p = [np.array(run['selected_parameters'][k]) for k in ['W','b','w','c']]
    return net


def slices(net, x, y, h):
    diff = net.predict(x)-y
    result = {}
    for label, mask in [('all', np.ones(len(h), dtype=bool)), ('h0_3', h < 4), ('h4_plus', h >= 4)]:
        result[label] = dict(rows=int(mask.sum()), rmse_usd=float(np.sqrt(np.mean(diff[mask]**2))))
    return result


def main():
    old = json.loads((HERE/'longer_results/followup.json').read_text())
    result = dict(purpose='Post-hoc diagnostics; the experiments do not isolate a single cause', prior=[])
    for r in old['runs']:
        env = Market(r['T']); data = evaluation_set(env, 'test'); net = restore(r)
        result['prior'].append(dict(T=env.T, short_horizon_training_mass=4/(env.T+1),
            saturated_extension_max_error_usd=max(abs(q*95.25+4*env.slope*h+env.slope*(9-(4-q)*(3-q)/2)-env.W[h,0,q]) for h in range(4) for q in range(5)),
            heldout=slices(net, data['x'], data['y'], data['h'])))
    study = json.loads((HERE/'results_1024/study.json').read_text()); env = ScaledMarket(1024)
    next_states = [env.step(env.initial, a) for a in [0, 1]]
    exact_next = [env.exact(s, env.T) for s in next_states]
    result['1024_root_action_gap_usd'] = exact_next[1]-exact_next[0]
    s = env.initial; optimal_states = [s]
    for _ in range(env.T):
        s = env.step(s, 1 if s.q < 4 else 0); optimal_states.append(s)
    labels = LazyLabels(env, optimal_states)
    # Full-horizon values along the independent optimal buy-first trajectory.
    ids = np.arange(len(labels.states)); hs = env.T-labels.rows[:, 0]
    data = labels.make(ids, hs)
    result['1024_optimal_path'] = []
    all_runs = [('random', r) for r in study['runs']]
    guided_file = HERE/'results_1024/search_guided.json'
    if guided_file.exists():
        all_runs += [('search_augmented', r) for r in json.loads(guided_file.read_text())['runs']]
    for kind, r in all_runs:
        net = restore(r); diff = net.predict(data['x'])-data['y']
        result['1024_optimal_path'].append(dict(kind=kind, seed=r['seed'], trajectories=r['trajectories'],
            rmse_usd=float(np.sqrt(np.mean(diff**2))), max_abs_usd=float(np.max(abs(diff))),
            root_value_error_usd=float(diff[0]),
            predicted_root_buy_minus_wait_usd=float(np.diff(net.predict(np.array([env.features(s,env.T) for s in next_states])))[0]),
            policy_regret_usd=r['policy']['full_horizon_regret_usd']))
    (HERE/'results_1024/horizon_audit.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
