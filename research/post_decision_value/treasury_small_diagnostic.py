"""Small single-BILL hold/boundary diagnostic with four received history steps.

This is a separate feature/checkpoint schema, not a repeated-policy or max-min
learner. Observation truncation never skips simulation events or redemption.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re

import numpy as np
import torch
from torch import nn

from .engine import Instruction, Trade
from .liquidation import ClosingRule, liquidate
from .robust_rollout import CampaignBudget, Controller, digest, rollout
from .treasury_fixtures import (DAY, accept_anchor, action_provider, fixture_engine,
                               hold_reference, make_cases, scenario_set)
from .treasury_model import (DIAGNOSTIC_VERSION, FEATURE_NAMES as BASE_NAMES,
                             TreasuryValue, encode as base_encode, error, fit_scalar)

FEATURE_VERSION = 'treasury-four-received-history-v1'
CHECKPOINT_VERSION = 'treasury-small-history-checkpoint-v1'
LABEL_IDENTITY = 'single-bill-four-history-hold-boundary-v1'
HISTORY_STEPS = 4
HISTORY_FIELDS = ('relative_price', 'amount', 'side', 'age', 'receipt_delay', 'valid')
FEATURE_NAMES = BASE_NAMES + tuple(f'history_{i}_{name}' for i in range(HISTORY_STEPS)
                                  for name in HISTORY_FIELDS)
DEFAULT_CONFIG = Path(__file__).with_name('treasury_small_diagnostic_config.json')


def write_json(path, value):
    path = Path(path)
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode()
    if path.suffix == '.gz':
        raw = gzip.compress(raw, mtime=0)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(raw)
    temporary.replace(path)


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def validate_config(config):
    if config['schema'] != 'treasury-small-history-diagnostic-v1':
        raise ValueError('Unknown diagnostic schema')
    if config['history_steps'] != HISTORY_STEPS or config['history_spacing_ms'] != 1000:
        raise ValueError('This feature schema fixes four one-second received seed steps')
    if config['objective'] != dict(BTC=.5, USD=.5, **{'lambda': 10}, failure_penalty=1, drawdown=.1):
        raise ValueError('Frozen diagnostic objective changed')
    if config['quantities'] != [5, 25, 60] or config['price_offsets'] != [0] or config['inventory_cap'] != 60:
        raise ValueError('Changed action domain needs a new reference version')
    if config['architecture'] != {'width': 24}:
        raise ValueError('This diagnostic fixes a width-24 architecture')
    if not 0 < config['diagnosis_updates'] <= config['limits']['updates'] <= 500:
        raise ValueError('Optimizer schedule exceeds the small diagnostic cap')
    if set(config['splits']) != {'train', 'validation', 'test'}:
        raise ValueError('Require train, validation and test splits')
    if len({c['seed'] for c in config['splits'].values()}) != 3:
        raise ValueError('Split generator seeds must be distinct')
    if any(c['count'] < 4 or c['count'] % 4 for c in config['splits'].values()):
        raise ValueError('Balanced four-category fixture groups required')
    if sum(c['count'] for c in config['splits'].values()) > 16:
        raise ValueError('Small diagnostic permits at most 16 cases')
    d = config['delays']
    if (d['decision'] + d['delivery'] + d['report']) * (1+d['jitter']) * (1+d['congestion']) >= 1000:
        raise ValueError('Delay law outside hold-reference support')


def seed_trades(case):
    """Nuisance past variation, independent of outcome; initial limit unchanged.

    The generic fixed-price action provider uses the first history price. Both
    endpoints therefore remain the declared purchase price; middle observations
    have small unrelated tick offsets. No future tape is consulted.
    """
    rng = random.Random(case['seed'] ^ 0x4B17)
    offsets = [0., rng.choice([-.03, -.02, -.01, .01, .02, .03]),
               rng.choice([-.03, -.02, -.01, .01, .02, .03]), 0.]
    return [Trade(case['start'] - (HISTORY_STEPS-i)*1000, 'BILL',
                  round(case['price']+offset, 2), float(rng.randrange(100, 1001)),
                  rng.choice(['buy', 'sell']), f'history-{i}', 100000., 'treasury')
            for i, offset in enumerate(offsets)]


def short_fixture(case, config):
    engine = fixture_engine(case, config)
    engine.observable.history.clear()
    engine.observable.market.clear()
    engine.seed_market(seed_trades(case), case['start'])
    return engine


def received_history(obs):
    if any(row['received'] > obs.time or row['time'] > row['received'] for row in obs.history):
        raise ValueError('History includes unavailable or invalid future information')
    if any(row['symbol'] != 'BILL' for row in obs.history):
        raise ValueError('Only BILL history is supported')
    return sorted(obs.history, key=lambda r: (r['received'], r['time'], r['identifier']))[-HISTORY_STEPS:]


def encode(obs, action, goal, instruments, horizon):
    values = base_encode(obs, action, goal, instruments, horizon)
    history = received_history(obs)
    values += [0.] * ((HISTORY_STEPS-len(history))*len(HISTORY_FIELDS))
    for row in history:
        values.extend([(row['price']-100)/5, row['amount']/1000,
                       1. if row['side']=='buy' else -1.,
                       min(2., (obs.time-row['received'])/(28*DAY)),
                       (row['received']-row['time'])/1000, 1.])
    return values


class SmallHistoryValue(TreasuryValue):
    """Separate checkpoint format; inherits only scalar operations, not weights."""
    def __init__(self, width=24):
        nn.Module.__init__(self)
        self.width = width
        self.net = nn.Sequential(nn.Linear(len(FEATURE_NAMES), width), nn.SiLU(),
                                 nn.Linear(width, width), nn.SiLU(), nn.Linear(width, 1))
        self.register_buffer('x_mean', torch.zeros(len(FEATURE_NAMES)))
        self.register_buffer('x_scale', torch.ones(len(FEATURE_NAMES)))
        self.register_buffer('y_mean', torch.tensor(0.))
        self.register_buffer('y_scale', torch.tensor(1.))
        self.identity = {}
        self.target_version = DIAGNOSTIC_VERSION
        self.label_identity = LABEL_IDENTITY


def save_model(path, model, optimizer, identity):
    torch.save(dict(schema=CHECKPOINT_VERSION, feature_version=FEATURE_VERSION,
                    target_version=model.target_version, label_identity=model.label_identity,
                    width=model.width, history_steps=HISTORY_STEPS, feature_names=FEATURE_NAMES,
                    state=model.state_dict(), optimizer=optimizer.state_dict() if optimizer else None,
                    torch_rng=torch.get_rng_state(), identity=identity), path)


def load_model(path, identity=None):
    saved = torch.load(path, map_location='cpu', weights_only=True)
    if (saved['schema'] != CHECKPOINT_VERSION or saved['feature_version'] != FEATURE_VERSION
            or saved['target_version'] != DIAGNOSTIC_VERSION or saved['label_identity'] != LABEL_IDENTITY
            or saved['history_steps'] != HISTORY_STEPS or tuple(saved['feature_names']) != FEATURE_NAMES):
        raise ValueError('Incompatible short-history diagnostic checkpoint')
    if identity is not None and saved['identity'] != identity:
        raise ValueError('Checkpoint source/config identity mismatch')
    model = SmallHistoryValue(saved['width'])
    model.load_state_dict(saved['state'])
    model.identity = saved['identity']
    return model


def collect(cases, config, budget):
    """Full existing simulator cashflows, independent hold/boundary arithmetic."""
    rows = []
    actions = action_provider(config)
    for case in cases:
        budget.check()
        base = short_fixture(case, config)
        budget.input(dict(trades=seed_trades(case)))
        candidates, admission = actions(base.observe(), base.goal, base.instruments)
        scenario = scenario_set(case, [311], config, 'small-diagnostic')[0]
        for action in candidates:
            if action.kind not in ('wait', 'create'):
                continue
            quantity = sum(o.quantity for o in action.orders)
            parent = accept_anchor(deepcopy(base), action, config)
            horizon = case['decision_end']-parent.now
            observation = parent.observe()
            features = encode(observation, Instruction(), parent.goal, parent.instruments, horizon)
            result = rollout(parent, horizon, scenario, Controller(0), None, encode, actions,
                             config, budget, hold=True)
            reference = hold_reference(case, quantity, horizon)
            pair = [('hold', horizon, observation, features, reference, result['outcome'],
                     {k:v for k,v in result.items() if k not in ('engine', 'anchors')})]
            owned = deepcopy(parent)
            owned.add_tape(scenario['trades'])
            owned.advance(case['start']+DAY+1000)
            budget.event(owned.hidden.processed)
            observation = owned.observe()
            features = encode(observation, Instruction(), owned.goal, owned.instruments, 0)
            boundary = liquidate(owned, scenario['trades'], scenario['label_end'],
                                 ClosingRule(**config['closing']), budget)
            pair.append(('boundary', 0, observation, features,
                         hold_reference(case, quantity, 0, inventory=True), boundary, boundary))
            for kind, horizon, observation, features, reference, outcome, replay in pair:
                balance_error = max(abs(outcome['balances'][c]-reference['balances'][c]) for c in ('BTC', 'USD')) if outcome['done'] else None
                utility_error = abs(outcome['utility']-reference['utility']) if outcome['done'] else None
                if not outcome['done'] or balance_error > config['acceptance']['accounting_atol'] or utility_error > config['acceptance']['accounting_atol']:
                    raise AssertionError('Independent diagnostic cashflow/reference mismatch')
                rows.append(dict(case=case['id'], split=case['split'], category=case['category'],
                                 quantity=quantity, kind=kind, horizon_ms=horizon, features=features,
                                 observation_time=observation.time, history=received_history(observation),
                                 available_history_steps=len(observation.history), history_steps=len(received_history(observation)),
                                 done=True, target=outcome['utility'], target_version=DIAGNOSTIC_VERSION,
                                 identity=LABEL_IDENTITY, reference=reference, replay=replay,
                                 admission=admission, accounting_balance_error=balance_error,
                                 accounting_utility_error=utility_error))
    return rows


def assess(model, rows, config):
    predictions = model.predict([r['features'] for r in rows])
    choices = []
    for case in sorted({r['case'] for r in rows}):
        indices = [i for i, row in enumerate(rows) if row['case']==case and row['kind']=='hold']
        best = max(float(predictions[i]) for i in indices)
        selected = next(i for i in indices if float(predictions[i]) >= best-config['tie_margin'])
        optimal = max(rows[i]['target'] for i in indices)
        row = rows[selected]
        choices.append(dict(case=case, category=row['category'], quantity=row['quantity'],
                            predicted_utility=float(predictions[selected]), utility=row['target'],
                            optimal=optimal, regret=max(0., optimal-row['target']),
                            correct=abs(row['target']-optimal)<=config['acceptance']['quantity_atol']))
    errors = error(model, rows)
    return dict(passed=all(c['correct'] for c in choices) and errors['max_error']<=config['acceptance']['diagnosis_max_error'],
                cases=len(choices), labels=len(rows), correct_cases=sum(c['correct'] for c in choices),
                choices=choices, errors=errors)


def source_identity(source_commit):
    if not re.fullmatch(r'[0-9a-f]{40}', source_commit):
        raise ValueError('--source-commit must be the pinned upstream full SHA')
    root = Path(__file__).resolve().parents[2]
    files = sorted(Path(__file__).parent.glob('*.py'))
    files += [root/'trade_ordering.py', root/'replay_checkpoints.py']
    hashes = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files if p.exists()}
    return dict(source_commit=source_commit, source_commit_meaning='upstream baseline plus recorded local source hashes',
                source_files=hashes, source_sha256=digest(hashes), simulator='post-decision-v1',
                feature_version=FEATURE_VERSION, checkpoint_version=CHECKPOINT_VERSION,
                target_version=DIAGNOSTIC_VERSION)


def verify(output):
    output = Path(output)
    identity = read(output/'identity.json')
    if digest(read(output/'configuration.json')) != identity['configuration_sha256']:
        raise ValueError('Configuration hash mismatch')
    model = load_model(output/'selected-model.pt', identity)
    selection = read(output/'frozen-selection.json')
    if selection['identity'] != identity or model.fingerprint() != selection['model_sha256']:
        raise ValueError('Checkpoint differs from frozen validation selection')
    fixtures = read(output/'fixtures.json')
    if digest(fixtures) != identity['fixtures_sha256']:
        raise ValueError('Frozen fixture specification hash mismatch')
    examples = read(output/'inference-examples.json')
    np.testing.assert_allclose(model.predict(examples['features']), examples['predictions'], rtol=0, atol=1e-8)
    cases = {c['id']:c for cs in fixtures.values() for c in cs}
    checked = 0
    for path in output.glob('rows-*.json.gz'):
        for row in read(path):
            reference = hold_reference(cases[row['case']], row['quantity'], row['horizon_ms'], inventory=row['kind']=='boundary')
            if abs(reference['utility']-row['target']) > 1e-8:
                raise ValueError('Independent saved target mismatch')
            if any(h['received']>row['observation_time'] for h in row['history']) or row['history_steps']>HISTORY_STEPS:
                raise ValueError('Saved history is not bounded and causal')
            checked += 1
    return dict(verified=True, checkpoint_model_sha256=model.fingerprint(), examples=len(examples['features']),
                independently_rechecked_labels=checked)


def run(output, config_path=DEFAULT_CONFIG, source_commit=None):
    config = read(config_path)
    validate_config(config)
    identity = source_identity(source_commit)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(config['seed'])
    budget = CampaignBudget(config['limits'])
    cases = {split:make_cases(split, config) for split in ('train', 'validation', 'test')}
    splits = [cases[s] for s in ('train', 'validation', 'test')]
    if any(max(c['label_end'] for c in left) >= min(c['start'] for c in right)
           for left, right in zip(splits, splits[1:])):
        raise ValueError('Split buffers overlap')
    identity.update(configuration_sha256=digest(config), fixtures_sha256=digest(cases))
    write_json(output/'configuration.json', config)
    write_json(output/'identity.json', identity)
    write_json(output/'fixtures.json', cases)
    write_json(output/'environment.json', dict(platform=platform.platform(), python=platform.python_version(),
               torch=str(torch.__version__), numpy=np.__version__, cpu=platform.processor(), device='cpu',
               threads=torch.get_num_threads(), thread_environment={k:os.environ.get(k) for k in
               ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')}))
    model = SmallHistoryValue(**config['architecture'])
    report = dict(schema=config['schema'], source_kind='synthetic_fixture', scope=config['scope'],
                  passed=False, test_evaluations=0, identity=identity,
                  parameters=sum(p.numel() for p in model.parameters()), history_steps=HISTORY_STEPS,
                  history_fields=list(HISTORY_FIELDS), input_features=len(FEATURE_NAMES), feature_names=list(FEATURE_NAMES),
                  selection=config['selection'], status='running')
    write_json(output/'report.json', report)
    rows_by_split = {}
    curve = []
    optimizer = None
    try:
        for split in ('train', 'validation'):
            rows_by_split[split] = collect(cases[split], config, budget)
            write_json(output/f'rows-{split}.json.gz', rows_by_split[split])
        def checkpoint(current, opt, point):
            curve.append(point)
            write_json(output/'learning-curve.json', curve)
            save_model(output/'last-model.pt', current, opt, identity)
        optimizer, _, best = fit_scalar(model, rows_by_split['train'], rows_by_split['validation'],
                                       config['diagnosis_updates'], budget, callback=checkpoint)
        report['training_endpoint'] = {split:assess(model, rows, config) for split, rows in rows_by_split.items()}
        model.load_state_dict(best['state'])
        optimizer.load_state_dict(best['optimizer'])
        torch.set_rng_state(best['torch_rng'])
        save_model(output/'selected-model.pt', model, optimizer, identity)
        report['selected_updates'] = best['updates']
        report['splits'] = {split:assess(model, rows, config) for split, rows in rows_by_split.items()}
        write_json(output/'frozen-selection.json', dict(model_sha256=model.fingerprint(), identity=identity,
                   selected_updates=best['updates'], test_evaluations=0, selection=config['selection']))
        if all(report['splits'][s]['passed'] for s in ('train', 'validation')):
            # The test's tape and outcomes are first constructed AFTER selection.
            rows_by_split['test'] = collect(cases['test'], config, budget)
            write_json(output/'rows-test.json.gz', rows_by_split['test'])
            report['test_evaluations'] = 1
            report['splits']['test'] = assess(model, rows_by_split['test'], config)
            report['passed'] = all(s['passed'] for s in report['splits'].values())
            report['status'] = 'complete_pass' if report['passed'] else 'complete_failed_diagnostic_acceptance'
        else:
            report['status'] = 'blocked_by_development_gate'
            report['reason'] = 'Selected training or validation controls failed; no retry and fresh test remains untouched.'
        predictions = []
        for split, rows in rows_by_split.items():
            for row, prediction in zip(rows, model.predict([r['features'] for r in rows])):
                predictions.append({k:row[k] for k in ('case','split','category','kind','quantity','target','history_steps')} |
                                   dict(prediction=float(prediction)))
        write_json(output/'predictions.json', predictions)
        report['normalization'] = dict(x_mean=model.x_mean.tolist(), x_scale=model.x_scale.tolist(),
                                       y_mean=float(model.y_mean), y_scale=float(model.y_scale), fitted_on='train only')
        all_rows = [r for rows in rows_by_split.values() for r in rows]
        report['history_counts'] = sorted({r['history_steps'] for r in all_rows})
        report['max_accounting_balance_error'] = max(r['accounting_balance_error'] for r in all_rows)
        report['max_accounting_utility_error'] = max(r['accounting_utility_error'] for r in all_rows)
        examples = rows_by_split['train'][:8]
        fs = [r['features'] for r in examples]
        restored = load_model(output/'selected-model.pt', identity)
        np.testing.assert_array_equal(model.predict(fs), restored.predict(fs))
        write_json(output/'inference-examples.json', dict(features=fs, predictions=restored.predict(fs).tolist()))
        report['restoration'] = verify(output)
    except (RuntimeError, AssertionError) as exc:
        report['status'] = 'failed_or_capped'
        report['reason'] = str(exc)
        save_model(output/'interrupted-model.pt', model, optimizer, identity)
    finally:
        report['resources'] = budget.summary()
        report['checkpoint_target_version'] = DIAGNOSTIC_VERSION
        report['checkpoint_label_identity'] = LABEL_IDENTITY
        write_json(output/'learning-curve.json', curve)
        write_json(output/'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'verify'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--source-commit')
    args = parser.parse_args()
    result = run(args.output, args.config, args.source_commit) if args.command=='run' else verify(args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
