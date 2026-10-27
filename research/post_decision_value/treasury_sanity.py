"""Bounded synthetic Treasury learning gate, using the production value/engine path.

One initial instruction followed by the SAME hold-to-maturity continuation for
every action. Calendar-length maturities are jumped over by exact event replay;
this is not a historical or years-long streaming training benchmark.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import time

import numpy as np
import torch

from .accounting import Goal, Instrument, Ledger
from .engine import Delays, Engine, Instruction, Order, Trade, admissible
from .model import ValueNetwork, action_features, batch, fit, labels, load_model, save_model
from .pilot import code_identity, write_json

DAY = 86400000
CONTINUATION = 'treasury-sanity-v1:hold-after-initial-instruction:weighted-0.5-0.5-lambda10'
DELAYS = Delays(20, 10, 30, 50, .25, .25)


def scenarios(split, count):
    """Independent seeded fixtures; calendar splits do not turn these into history."""
    rng = random.Random({'train': 1701, 'validation': 1901, 'test': 2001}[split])
    cases = []
    for n in range(count):
        year = (2016 + n % 3) if split == 'train' else 2019 if split == 'validation' else 2020
        start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000) + 10000
        category = ('profitable', 'overpriced', 'fee_erased', 'cash_constrained')[n % 4]
        price = round(rng.uniform(96., 99.6), 2)
        fee = rng.choice((0., 5., 15.))
        if category == 'overpriced': price = round(rng.uniform(100.1, 102.), 2)
        if category == 'fee_erased':
            price = round(rng.uniform(99.85, 99.98), 2)
            fee = rng.choice((30., 50., 75.))
        days = rng.choice((28, 91, 182, 364))
        cases.append(dict(id=f'{split}-{n:04d}', split=split, category=category,
                          start=start, maturity=start + days * DAY, end=start + days * DAY + 2000,
                          days=days, price=price, fee_bps=fee, usd=rng.choice((8000., 10000., 12000.)),
                          quantities=[5., 25., 60.], seed=rng.randrange(1000000)))
    return cases


def engine(case):
    ins = Instrument('BILL', case['maturity'], payoff='treasury', source_payoff='treasury',
                     tick=.01, lot=1., fee_bps=case['fee_bps'],
                     cashflows=((case['maturity'], 100.),), listed_at=case['start']-DAY)
    initial = dict(BTC=1., USD=case['usd'])
    ledger = Ledger(initial.copy())
    if case['category'] == 'cash_constrained': ledger.pledge('USD', case['usd']-1.)
    goal = Goal(initial, case['end'], case['end'], mode='weighted_growth')
    e = Engine({'BILL': ins}, ledger, goal, case['seed'], DELAYS, participation=1., event_cap=100)
    e.seed_market([Trade(case['start']-1000, 'BILL', case['price'], 1000., 'buy',
                        'seed', 100000., 'treasury')], case['start'])
    return e


def collect(cases):
    rows, audits = [], []
    for case in cases:
        e = engine(case)
        actions = [Instruction()] + [Instruction('create', (Order('bill', 'BILL', q, case['price'],
                                                                 created=case['start']),)) for q in case['quantities']]
        for action in actions:
            ok, reason = admissible(e.observe(), action, e.goal, e.instruments)
            audits.append(dict(case=case['id'], action=action.payload(), accepted=ok, reason=reason))
            if not ok: continue
            replay = engine(case)
            # Build the post-state BEFORE the future tape is attached or executed.
            f = action_features(replay.observe(), action, replay.goal, replay.instruments)
            replay.submit(action)
            replay.add_tape([Trade(case['start']+1000, 'BILL', case['price']-.01, 1000.,
                                   'sell', 'synthetic-cross', 100000., 'treasury')])
            replay.advance(case['end'])
            outcome = replay.outcome()
            if not outcome['done'] or outcome['failed']: raise AssertionError('Incomplete/failed fixture')
            quantity = sum(o.quantity for o in action.orders)
            expected = case['usd'] + quantity * (100. - case['price'] * (1. + case['fee_bps']/10000))
            if abs(outcome['balances']['USD']-expected) > 1e-8: raise AssertionError('Treasury conservation')
            if replay.hidden.ledger.positions: raise AssertionError('Matured inventory remains')
            rows.append(dict(case=case['id'], category=case['category'], quantity=quantity,
                             features=f, instruction=action.payload(), continuation=CONTINUATION,
                             outcome=outcome, fills=replay.hidden.fills, events=replay.hidden.processed))
    return rows, audits


def metrics(model, rows):
    """Full-set objective, on TRAINING normalization, distinct from minibatch loss."""
    y, _ = labels(rows)
    total = 0.
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), 64):
            rs = rows[start:start+64]
            t = torch.tensor(y[start:start+64])
            z = model(batch([r['features'] for r in rs]))
            normalized = (t[:, :3]-model.label_mean)/model.label_scale
            loss = ((z[:, :3]-normalized)**2).mean() + .05*torch.nn.functional.binary_cross_entropy_with_logits(z[:, 3:], t[:, 3:])
            total += float(loss) * len(rs)
    pred = model.predict([r['features'] for r in rows])['objective']
    groups = {}
    for n, r in enumerate(rows): groups.setdefault(r['case'], []).append(n)
    choices = []
    for case, indices in groups.items():
        selected = max(indices, key=lambda i: float(pred[i]))
        best = max(indices, key=lambda i: rows[i]['outcome']['utility'])
        realized = rows[selected]['outcome']['utility']
        optimal = rows[best]['outcome']['utility']
        choices.append(dict(case=case, category=rows[selected]['category'], quantity=rows[selected]['quantity'],
                            predicted_utility=float(pred[selected]), utility=realized,
                            oracle_quantity=rows[best]['quantity'], oracle_utility=optimal,
                            regret=max(0., optimal-realized), correct=optimal-realized<1e-9,
                            growth=rows[selected]['outcome']['growth'], fills=rows[selected]['fills'],
                            candidates=[dict(quantity=rows[i]['quantity'], predicted=float(pred[i]),
                                             actual=rows[i]['outcome']['utility']) for i in indices]))
    summary = {}
    for category in ('all', 'profitable', 'overpriced', 'fee_erased', 'cash_constrained'):
        cs = [c for c in choices if category=='all' or c['category']==category]
        if cs:
            summary[category] = dict(cases=len(cs), correct=sum(c['correct'] for c in cs),
                mean_utility=float(np.mean([c['utility'] for c in cs])),
                mean_oracle_utility=float(np.mean([c['oracle_utility'] for c in cs])),
                mean_regret=float(np.mean([c['regret'] for c in cs])),
                bought=sum(c['quantity']>0 for c in cs),
                mean_usd_growth=float(np.mean([c['growth']['USD'] for c in cs])))
    return dict(loss=total/len(rows), objective_mae=float(np.mean(np.abs(pred-y[:, 0]))),
                summary=summary, choices=choices)


def run(output, updates=1200):
    if not 100 <= updates <= 1200 or updates % 100: raise ValueError('100..1200 updates, in blocks of 100')
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); cpu = time.process_time()
    torch.set_num_threads(1); torch.manual_seed(23)
    config = dict(source_kind='synthetic_fixture', counts=dict(train=128, validation=48, test=64),
                  updates=updates, wall_cap_seconds=240, training_cap_seconds=120, threads=1,
                  objective='weighted_growth', weights=dict(BTC=.5, USD=.5), loss_aversion=10.,
                  architecture=dict(width=64, layers=2, heads=4, feature_version=3),
                  continuation=CONTINUATION, delays=asdict(DELAYS),
                  acceptance=dict(profitable_accuracy=.95, loss_case_accuracy=1., max_mean_regret=.0001),
                  selection='minimum validation full-set normalized regression+BCE loss; no test inspection',
                  split_dates=dict(train='synthetic starts January 1, 2016/2017/2018',
                                   validation='synthetic starts January 1, 2019', test='synthetic starts January 1, 2020'))
    cases = {s: scenarios(s, n) for s, n in config['counts'].items()}
    identity = code_identity()
    identity.update(source_kind='synthetic_fixture',
                    config_sha256=hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                    fixtures_sha256=hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest())
    write_json(output/'configuration.json', config); write_json(output/'identity.json', identity)
    write_json(output/'fixtures.json', cases)
    # Do not collect or evaluate test outcomes until the checkpoint is frozen.
    datasets = {}
    for split in ('train', 'validation'):
        rows, audit = collect(cases[split]); datasets[split] = rows
        write_json(output/f'{split}-samples.json.gz', rows); write_json(output/f'{split}-admission.json.gz', audit)
    model = ValueNetwork(**config['architecture'])
    opt = rng = None; best_loss = float('inf'); best_step = None; training_seconds = 0.; curve = []; minibatch_losses = []
    for step in range(100, updates+1, 100):
        if time.monotonic()-started > 240 or training_seconds >= 120: raise RuntimeError('Smoke resource cap')
        opt, rng, info = fit(model, datasets['train'], updates=100, seed=23, optimizer=opt, rng=rng,
                             normalize=step==100, wall_seconds=120-training_seconds)
        training_seconds += info['seconds']; minibatch_losses.extend(info['losses'])
        if info['updates'] != 100: raise RuntimeError('Incomplete fit block')
        train = metrics(model, datasets['train']); validation = metrics(model, datasets['validation'])
        point = dict(updates=step, train_loss=train['loss'], validation_loss=validation['loss'],
                     train_summary=train['summary'], validation_summary=validation['summary'])
        curve.append(point)
        if validation['loss'] < best_loss:
            best_loss = validation['loss']; best_step = step
            save_model(output/'best-model.pt', model, opt, rng, identity)
        write_json(output/'learning-curve.json', curve); write_json(output/'minibatch-losses.json', minibatch_losses)
        print(json.dumps(dict(updates=step, train_loss=train['loss'], validation_loss=validation['loss'],
                              validation_correct=validation['summary']['all']['correct'])), flush=True)
    save_model(output/'last-model.pt', model, opt, rng, identity)
    model, _, _ = load_model(output/'best-model.pt', identity)
    rows, audit = collect(cases['test']); datasets['test'] = rows
    write_json(output/'test-samples.json.gz', rows); write_json(output/'test-admission.json.gz', audit)
    evaluation = metrics(model, rows); write_json(output/'test-evaluation.json', evaluation)
    s = evaluation['summary']; gates = dict(
        profitable=s['profitable']['correct']/s['profitable']['cases'] >= .95,
        overpriced=s['overpriced']['correct']==s['overpriced']['cases'],
        fees=s['fee_erased']['correct']==s['fee_erased']['cases'],
        constrained=s['cash_constrained']['correct']==s['cash_constrained']['cases'],
        regret=s['all']['mean_regret']<=.0001)
    report = dict(identity=identity, source_kind='synthetic_fixture', passed=all(gates.values()), gates=gates,
                  parameters=sum(p.numel() for p in model.parameters()), selected_updates=best_step,
                  samples={s:len(rs) for s,rs in datasets.items()}, test=evaluation['summary'],
                  test_loss=evaluation['loss'], test_objective_mae=evaluation['objective_mae'],
                  hold_baseline_utility=0., oracle='best funded initial order followed by hold; fixture benchmark, not learned',
                  resources=dict(wall_seconds=time.monotonic()-started, cpu_seconds=time.process_time()-cpu,
                                 training_seconds=training_seconds, updates=len(minibatch_losses), threads=1,
                                 replay_events=sum(r['events'] for rs in datasets.values() for r in rs)),
                  limitations=['Synthetic deterministic execution paths with stochastic message/report delays; no historical return inference.',
                               '28/91/182/364 actual calendar-day maturities, sparse event jumps, one initial decision; not annual streaming throughput.',
                               'All heads use the same hold continuation. Complete replay outcomes only; no analytical target substituted.',
                               'Constraint filtering enforces cash safety; cash-constrained choices alone do not prove learned constraint reasoning.',
                               'Contractual Treasury payments are projected, not externally observed settlements.',
                               'Test loss evaluated once after validation checkpoint selection; test cases cannot remain untouched after this report.'])
    write_json(output/'report.json', report)
    print(json.dumps({k:report[k] for k in ('passed','gates','selected_updates','test','resources')}), flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True); p.add_argument('--updates', type=int, default=1200)
    a = p.parse_args(); run(a.output, a.updates)
