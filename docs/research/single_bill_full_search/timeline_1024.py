"""Bounded 1024-step, all-horizon experiment; historical runners stay unchanged.

Exact shared-state Bellman search, lazy horizon-balanced labels, the original
97-parameter network and Adam schedule. No analytic shortcut enters the net.
"""
from pathlib import Path
import argparse
import hashlib
import json
import time
import numpy as np
from longer_timelines import Market, State, Net, rollout

HERE = Path(__file__).resolve().parent
CONFIG = dict(T=1024, seeds=[20261101, 20261102, 20261103],
              trajectory_budgets=[1, 4, 16, 64], updates=60000,
              batch_size=256, checkpoint_every=500, threshold=.3531,
              evaluation_trajectories=512, evaluation_states=512,
              evaluation_rows_per_horizon=2, train_probe_rows_per_horizon=4,
              wall_seconds=600)


class ScaledMarket(Market):
    def __init__(self, T):
        if T not in (4, 8, 16, 32, 64, 128, 1024):
            raise ValueError('Timeline outside the validated bounded domain')
        self.T = T; self.scale = 4*T; self.slope = 2/T; self.cap = 4
        self.initial = State(0, 1000*self.scale, 0)
        # Marked wealth changes by q_next*slope - .25*abs(action).
        # Therefore cash >= 1000 - .25*T - 4*97, for EVERY legal path.
        self.cash_lower_bound = 1000 - .25*T - 4*97
        assert self.cash_lower_bound > 97.25
        assert 97+self.slope*3.75+.25 < 100
        started = time.perf_counter()
        self.W = np.full((T+1, T+1, 5), np.nan)
        ends = np.arange(T+1)
        for q in range(5):
            self.W[ends, ends, q] = self.close_increment(ends, q)
        # Same Bellman recurrence as Market, vectorized across endpoints.
        for t in range(T-1, -1, -1):
            nxt = self.W[t+1:, t+1, :]
            best = nxt.copy()
            best[:, :4] = np.maximum(best[:, :4], self.cash_delta(t, 1)+nxt[:, 1:])
            best[:, 1:] = np.maximum(best[:, 1:], self.cash_delta(t, -1)+nxt[:, :4])
            self.W[t+1:, t, :] = best
        self.oracle_edges = 13*T*(T+1)//2
        self.boundaries = 5*(T+1)
        self.oracle_seconds = time.perf_counter()-started


class LazyLabels:
    """Every valid horizon remains eligible without materializing every pair."""
    def __init__(self, env, states):
        self.env = env; self.states = sorted(states)
        self.rows = np.array([(s.t, s.cash_ticks, s.q) for s in self.states], dtype=np.int64)
        self.counts = np.searchsorted(self.rows[:, 0], env.T-np.arange(env.T+1), side='right')
        self.label_count = int(self.counts.sum())

    def make(self, ids, hs):
        t, ticks, q = self.rows[ids].T
        cash = ticks/self.env.scale
        x = np.column_stack(((cash-1000)/400, q/4, t/self.env.T, hs/self.env.T))
        y = cash+self.env.W[t+hs, t, q]
        return dict(x=x, y=y, h=hs, ids=ids)

    def sample(self, rng, count):
        assert np.all(self.counts > 0)  # The initial training state covers all h.
        hs = rng.integers(self.env.T+1, size=count)
        ids = rng.integers(self.counts[hs])
        return self.make(ids, hs)

    def probe(self, seed, per_horizon):
        rng = np.random.default_rng(seed); ids = []; hs = []
        for h, count in enumerate(self.counts):
            take = min(per_horizon, count)
            ids.extend(rng.choice(count, take, replace=False).tolist())
            hs.extend([h]*take)
        return self.make(np.array(ids, dtype=int), np.array(hs, dtype=int))

    def short_probe(self):
        ids = []; hs = []
        for h in range(4):
            ids.extend(range(self.counts[h])); hs.extend([h]*self.counts[h])
        return self.make(np.array(ids), np.array(hs))


def measure(net, data):
    diff = net.predict(data['x'])-data['y']
    return dict(rmse_usd=float(np.sqrt(np.mean(diff**2))),
                max_abs_usd=float(np.max(abs(diff))), rows=len(diff))


def evaluation_pools(env):
    rng = np.random.default_rng(70001+env.T)
    pools = {'validation': set(), 'test': set()}
    for _ in range(CONFIG['evaluation_trajectories']):
        for s in rollout(env, rng):
            which = env.split(s)
            if which in pools: pools[which].add(s)
    result = {}
    for i, (which, states) in enumerate(pools.items()):
        states = sorted(states)
        choose = np.random.default_rng(80001+env.T+i)
        ids = choose.choice(len(states), min(len(states), CONFIG['evaluation_states']), replace=False)
        result[which] = LazyLabels(env, [states[j] for j in sorted(ids)])
    assert set(result['validation'].states).isdisjoint(result['test'].states)
    return result


def evaluate_policy(net, env):
    # Full length plus fixed diagnostic horizons; not all 1024 policy rollouts.
    horizons = [1, 2, 3, 4, 8, 16, 64, 256, 512, env.T]
    outcomes = []; transitions = 0
    for end in horizons:
        s = env.initial; actions = []
        while s.t < end:
            aa = env.actions_q(s.q); ns = [env.step(s, a) for a in aa]
            values = net.predict(np.array([env.features(n, end) for n in ns]))
            k = int(np.argmax(values)); s = ns[k]; actions.append(aa[k]); transitions += len(aa)
        regret = env.exact(env.initial, end)-env.close(s)
        assert regret > -1e-8
        outcomes.append(dict(horizon=end, regret_usd=regret, liquidation=env.close(s),
                             buys=actions.count(1), sells=actions.count(-1),
                             final_quantity=s.q, actions=actions))
    return dict(horizons=outcomes, candidate_transitions=transitions,
                full_horizon_regret_usd=outcomes[-1]['regret_usd'])


def fit(env, train, val, test, short_test, seed, deadline):
    net = Net(seed); rng = np.random.default_rng(seed^991)
    probe = train.probe(seed^7781, CONFIG['train_probe_rows_per_horizon'])
    moments = [np.zeros_like(p) for p in net.p]; squares = [p.copy() for p in moments]
    curve = []; best = float('inf'); best_params = None; best_step = 0
    consecutive = 0; sustained = None; first = None
    started = time.perf_counter()

    def checkpoint(step):
        nonlocal best, best_params, best_step, consecutive, sustained, first
        tm = measure(net, probe); vm = measure(net, val)
        curve.append(dict(update=step, train_probe=tm, validation=vm))
        if vm['rmse_usd'] < best:
            best = vm['rmse_usd']; best_params = net.copy_params(); best_step = step
        if vm['rmse_usd'] <= CONFIG['threshold']:
            consecutive += 1
            if first is None: first = step
            if consecutive >= 3 and sustained is None: sustained = step
        else: consecutive = 0

    checkpoint(0)
    for step in range(1, CONFIG['updates']+1):
        if step % 500 == 0 and time.perf_counter() > deadline:
            raise TimeoutError('1024-step experiment exceeded declared wall budget')
        batch = train.sample(rng, CONFIG['batch_size'])
        x = batch['x']; target = (batch['y']-1000)/10
        pred, z = net.forward(x); d = 2*(pred-target)/len(x)
        dz = d[:, None]*net.p[2][None, :]*(1-z*z)
        grads = [x.T@dz, dz.sum(0), z.T@d, np.array([d.sum()])]
        rate = .003 if step <= 6000 else .0006
        for k, g in enumerate(grads):
            moments[k] = .9*moments[k]+.1*g
            squares[k] = .999*squares[k]+.001*g*g
            net.p[k] -= rate*(moments[k]/(1-.9**step))/(np.sqrt(squares[k]/(1-.999**step))+1e-8)
        if step % CONFIG['checkpoint_every'] == 0: checkpoint(step)
    net.p = best_params
    result = dict(best_update=best_step, first_validation_threshold_update=first,
                  sustained_validation_threshold_update=sustained, curve=curve,
                  train_probe=measure(net, probe), validation=measure(net, val),
                  test=measure(net, test), short_horizon_test=measure(net, short_test),
                  policy=evaluate_policy(net, env), fit_seconds=time.perf_counter()-started,
                  optimizer_label_queries=CONFIG['updates']*CONFIG['batch_size'],
                  selected_parameters={k:p.tolist() for k,p in zip(['W','b','w','c'], net.p)})
    result['confirmed'] = bool(sustained is not None and result['test']['rmse_usd'] <= CONFIG['threshold'])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE/'results_1024')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter(); deadline = started+CONFIG['wall_seconds']
    env = ScaledMarket(CONFIG['T']); pools = evaluation_pools(env)
    val = pools['validation'].probe(90001, CONFIG['evaluation_rows_per_horizon'])
    test = pools['test'].probe(90002, CONFIG['evaluation_rows_per_horizon'])
    short_test = pools['test'].short_probe()
    result = dict(protocol=CONFIG.copy(), status='running', runs=[],
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  imported_source_sha256=hashlib.sha256((HERE/'longer_timelines.py').read_bytes()).hexdigest(),
                  market=dict(T=env.T, slope=env.slope, maturity=2.5*env.T,
                      cash_lower_bound=env.cash_lower_bound, optimal_root_liquidation=env.exact(env.initial, env.T),
                      oracle_edges=env.oracle_edges, oracle_boundaries=env.boundaries,
                      oracle_seconds=env.oracle_seconds, oracle_array_bytes=env.W.nbytes,
                      complete_root_paths=str(env.path_count())),
                  evaluation=dict(distinct_rollouts=CONFIG['evaluation_trajectories'],
                      transitions=CONFIG['evaluation_trajectories']*env.T,
                      validation_states=len(pools['validation'].states), test_states=len(pools['test'].states),
                      validation_rows=len(val['y']), test_rows=len(test['y']), short_test_rows=len(short_test['y'])))

    def save():
        result['wall_seconds'] = time.perf_counter()-started
        tmp = args.output/'study.tmp'
        tmp.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False))
        tmp.replace(args.output/'study.json')

    save()
    print(json.dumps(dict(ready=True, market=result['market'], evaluation=result['evaluation'])), flush=True)
    try:
        for seed in CONFIG['seeds']:
            rng = np.random.default_rng(seed^12345); states = set(); generated = 0
            for budget in CONFIG['trajectory_budgets']:
                while generated < budget:
                    states.update(s for s in rollout(env, rng) if env.split(s) == 'train'); generated += 1
                train = LazyLabels(env, states)
                assert all(env.split(s) == 'train' for s in train.states)
                run = dict(seed=seed, trajectories=budget, training_transitions=budget*env.T,
                           training_states=len(states), eligible_training_labels=train.label_count,
                           **fit(env, train, val, test, short_test, seed, deadline))
                result['runs'].append(run); save()
                print(json.dumps({k:run[k] for k in ['seed','trajectories','training_states','eligible_training_labels','best_update','confirmed']}|
                                 dict(test_rmse=run['test']['rmse_usd'],short_rmse=run['short_horizon_test']['rmse_usd'],
                                      regret=run['policy']['full_horizon_regret_usd'],elapsed=result['wall_seconds'])), flush=True)
        result['status'] = 'completed'
    except TimeoutError as exc:
        result['status'] = 'budget_exhausted'; result['reason'] = str(exc)
    save()
    print(json.dumps(dict(status=result['status'], runs=len(result['runs']), wall_seconds=result['wall_seconds'])), flush=True)


if __name__ == '__main__': main()
