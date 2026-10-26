"""Full cached 90-day analytical calibration, with fixed chronological holdouts.

No neural dependency, downloads, deployment, or exchange connections. Daily
chunks retain one continuous engine per split. Original pilot limits are intact;
this separately bounded study reads <=100k rows / 8 MB per chunk, <=600k unique
rows / 12 MB total, <=20k decisions and <=3600 seconds across all trajectories.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import date, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time

from .accounting import Goal, Ledger
from .analytical import analytical
from .checkpoint import DirectoryCheckpoints, save_engine
from .data import load_archive, sha, utc_ms
from .engine import CandidateGenerator, Delays, Engine

DAY = 86400000
PRESETS = [
    dict(name='original', quantities=[.005, .01], offsets=[-.005, 0., .005]),
    dict(name='small', quantities=[.0025, .005], offsets=[-.005, 0., .005]),
    dict(name='tight', quantities=[.005, .01], offsets=[-.001, 0., .001]),
    dict(name='small_tight', quantities=[.0025, .005], offsets=[-.001, 0., .001]),
]


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()
    if path.suffix == '.gz':
        raw = gzip.compress(raw, mtime=0)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(raw)
    tmp.replace(path)


def plan():
    dates = [(date(2026, 6, 6) + timedelta(days=i)).isoformat() for i in range(90)]
    return dict(schema_version=1, dates=dates,
                splits=dict(calibration=dates[:54], validation=dates[54:72], test=dates[72:]),
                presets=PRESETS, seeds=[11, 29], cadence_ms=3600000,
                initial=dict(BTC=1., USD=100000.), participation=.1,
                candidate_budget=96, delays=asdict(Delays()),
                max_decisions=20000, max_seconds=3600, max_rows=600000,
                max_source_bytes=12000000, max_episode_events=1200000,
                selection='Top two safe calibration mean terminal utilities; validation chooses one; preset order breaks ties.',
                objective='min(BTC growth, USD growth) minus 1 for any path failure',
                portfolio='Continuous within each split, fresh identical initial portfolio at split boundaries.',
                full_period='Untuned original only; descriptive, not an additional holdout.',
                test='Frozen selected vs original vs hold; selected also at 10x all delays.',
                scope='All cached Dec26/Mar27 raw trades; not the separate multi-year 540-instrument archive.',
                settlement='Contractual/projected holdings; no observed settlement evidence; no spot execution.')


def fingerprint(config):
    digest = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob('*.py')):
        digest.update(p.name.encode()); digest.update(p.read_bytes())
    for name in ('trade_ordering.py', 'replay_checkpoints.py'):
        digest.update(Path(name).read_bytes())
    return dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                source_sha256=digest.hexdigest(),
                config_sha256=hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest())


class Budget:
    def __init__(self, config):
        self.started = time.monotonic()
        self.config = config
        self.decisions = self.events = 0

    def check(self, decision=False):
        if time.monotonic() - self.started >= self.config['max_seconds']:
            raise RuntimeError('study_wall_cap')
        if decision and self.decisions >= self.config['max_decisions']:
            raise RuntimeError('study_decision_cap')


def inventory(root, config, budget):
    """Verify each raw source; preserve seeds available before each split boundary."""
    files, daily, seeds_by_date, latest = [], {}, {}, {}
    byte_count = row_count = 0
    for day in config['dates']:
        budget.check()
        ins, trades, seeds, manifest = load_archive(root, [day])
        start = utc_ms(day + 'T00:00:00Z')
        if not latest:
            latest = {s.symbol: s for s in seeds}
        seeds_by_date[day] = list(latest.values())
        if set(latest) != set(ins) or any(t.time >= start for t in latest.values()):
            raise ValueError('Missing causal boundary seeds')
        if any(not start <= t.time < start + DAY for t in trades):
            raise ValueError('Source date partition mismatch')
        if len({(t.symbol, t.identifier) for t in trades}) != len(trades):
            raise ValueError('Duplicate source trades')
        for t in trades:
            if t.time <= start + DAY - 1000:
                latest[t.symbol] = t
        files.extend(manifest['files'])
        daily[day] = dict(rows=manifest['raw_rows'], bytes=manifest['bytes_read'])
        byte_count += manifest['bytes_read']; row_count += manifest['raw_rows']
        if byte_count > config['max_source_bytes'] or row_count > config['max_rows']:
            raise ValueError('Study source cap')
    manifest.update(files=files, daily=daily, bytes_read=byte_count, raw_rows=row_count,
                    coverage_claim='All 180 cached daily Dec26/Mar27 objects, 2026-06-06 through 2026-09-03; not the multi-year archive.')
    return ins, manifest, seeds_by_date


def check_fills(fills, source, instruments, participation):
    usage = {}
    for f in fills:
        tr = source[(f['symbol'], f['source_id'])]
        ins = instruments[f['symbol']]
        if not tr.executable or tr.time != f['time'] or tr.price != f['source_price']:
            raise ValueError('Fill provenance mismatch')
        through = (f['quantity'] > 0 and tr.side == 'sell' and tr.price < f['price']) or (f['quantity'] < 0 and tr.side == 'buy' and tr.price > f['price'])
        if not through or abs(ins.round_quantity(f['quantity']) - f['quantity']) > 1e-9:
            raise ValueError('Invalid strict-through/native fill')
        key = (tr.symbol, tr.identifier)
        usage[key] = usage.get(key, 0.) + abs(f['quantity'])
        if usage[key] > ins.print_capacity(tr.amount, tr.price) * participation + 1e-9:
            raise ValueError('Shared print volume exceeded')


def rank_presets(results, presets):
    ranked = []
    for preset in presets:
        rows = [r for r in results if r['preset'] == preset['name']]
        safe = bool(rows) and all(r['outcome']['done'] and not r['outcome']['failed'] for r in rows)
        score = statistics.mean(r['outcome']['utility'] for r in rows) if safe else None
        ranked.append(dict(preset=preset['name'], eligible=safe, score=score))
    # Sort is stable: preserve declared preset order for ties.
    return sorted(ranked, key=lambda r: (not r['eligible'], -(r['score'] if r['score'] is not None else 0)))


def replay(root, output, identity, config, instruments, manifest, seeds_by_date,
           budget, split, dates, preset, seed, multiplier=1., hold=False):
    name = f'{split}-{preset["name"]}-s{seed}-d{multiplier:g}' + ('-hold' if hold else '')
    folder = output / 'episodes' / name
    result_path = folder / 'result.json'
    if result_path.exists():
        result = json.loads(result_path.read_text())
        if result['identity'] != identity:
            raise ValueError('Episode identity mismatch')
        for filename, digest in result['artifacts'].items():
            if sha(folder / filename) != digest:
                raise ValueError('Episode artifact hash mismatch')
        budget.decisions += result['decisions']; budget.events += result['events']
        return result
    folder.mkdir(parents=True, exist_ok=True)
    start, end = utc_ms(dates[0] + 'T00:00:00Z'), utc_ms(dates[-1] + 'T00:00:00Z') + DAY
    goal = Goal(config['initial'], end, max(i.expiry for i in instruments.values()))
    delays = Delays(**{k: round(v * multiplier) if k in ('observation', 'decision', 'delivery', 'report') else v for k, v in config['delays'].items()})
    engine = Engine(instruments, Ledger(config['initial'].copy()), goal, seed, delays,
                    participation=config['participation'], event_cap=config['max_episode_events'])
    engine.seed_market(seeds_by_date[dates[0]], start)
    generator = CandidateGenerator(budget=config['candidate_budget'], quantities=preset['quantities'], offsets=preset['offsets'])
    decisions = 0; daily = []; counts = Counter(); accepted_counts = Counter(); actions = Counter()
    started = time.monotonic()
    audit_tmp = folder / 'decisions.jsonl.gz.tmp'
    with gzip.open(audit_tmp, 'wt') as audit:
        for day in dates:
            budget.check()
            _, trades, _, day_manifest = load_archive(root, [day])
            expected = [f for f in manifest['files'] if f['file'].startswith(day)]
            if day_manifest['files'] != expected:
                raise ValueError('Source changed after freeze')
            engine.add_tape(trades)
            before_fills = len(engine.hidden.fills)
            day_start = utc_ms(day + 'T00:00:00Z')
            for t in range(day_start, day_start + DAY, config['cadence_ms']):
                budget.check(decision=True)
                engine.advance(t)
                if engine.truncated:
                    raise RuntimeError('Replay truncated: no complete terminal label')
                obs = engine.observe()
                candidates, proposals = generator.generate(obs, goal, instruments)
                selected = next((i for i, a in enumerate(candidates) if a.kind == 'wait'), 0) if hold else analytical(obs, candidates, goal, instruments)
                action = candidates[selected]
                engine.submit(action)
                counts[len(proposals)] += 1; accepted_counts[len(candidates)] += 1; actions[action.kind] += 1
                audit.write(json.dumps(dict(time=t, chosen=action.payload(), candidates=proposals), separators=(',', ':')) + '\n')
                decisions += 1; budget.decisions += 1
            engine.advance(day_start + DAY - 1)
            if engine.truncated:
                raise RuntimeError('Replay truncated at day end')
            check_fills(engine.hidden.fills[before_fills:], {(t.symbol, t.identifier): t for t in trades}, instruments, config['participation'])
            holdings = engine.hidden.ledger.holdings(instruments)
            daily.append(dict(date=day, holdings=holdings, **goal.outcome(holdings, bool(engine.hidden.failures)),
                              fills=len(engine.hidden.fills), fees=engine.hidden.ledger.fees.copy(),
                              live_orders=len(engine.hidden.orders), pending=len(engine.observable.pending),
                              positions={k: asdict(v) for k, v in engine.hidden.ledger.positions.items()},
                              accepted_decisions=decisions))
    engine.advance(end)
    outcome = engine.outcome()
    if not outcome['done'] or outcome['truncated']:
        raise RuntimeError('Incomplete episode')
    if any(v < -1e-8 for v in outcome['min_floor_headroom'].values()) and not outcome['failed']:
        raise ValueError('Unreported floor failure')
    audit_tmp.replace(folder / 'decisions.jsonl.gz')
    write(folder / 'daily.json', daily)
    write(folder / 'fills.json.gz', engine.hidden.fills)
    checkpoint_store = DirectoryCheckpoints(folder / 'checkpoint')
    save_engine(checkpoint_store, end, engine, identity)
    artifacts = {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob('*')) if p.is_file() and p != result_path}
    result = dict(identity=identity, name=name, split=split, preset=preset['name'], seed=seed,
                  delay_multiplier=multiplier, hold=hold, start=start, end=end, goal=asdict(goal),
                  decisions=decisions, events=engine.hidden.processed, seconds=time.monotonic()-started,
                  outcome=outcome, proposed_count_histogram={str(k):v for k,v in counts.items()}, accepted_count_histogram={str(k):v for k,v in accepted_counts.items()},
                  selected_action_counts=dict(actions), artifacts=artifacts,
                  fill_audit='PASS: hash-verified raw print, strict-through side, lot rounding, shared print capacity')
    budget.events += engine.hidden.processed
    write(result_path, result)
    print(json.dumps(dict(episode=name, utility=outcome['utility'], growth=outcome['growth'], fills=outcome['fills'], failed=outcome['failed'], seconds=result['seconds'])), flush=True)
    return result


def summarize(results):
    groups = {}
    for row in results:
        key = (row['split'], row['preset'], row['hold'], row['delay_multiplier'])
        groups.setdefault(key, []).append(row)
    summary = []
    for (split, preset, hold, delay), rows in groups.items():
        outcomes = [r['outcome'] for r in rows]
        summary.append(dict(split=split, preset=preset, hold=hold, delay_multiplier=delay, seeds=len(rows),
                            mean_utility=statistics.mean(o['utility'] for o in outcomes),
                            growth={c: statistics.mean(o['growth'][c] for o in outcomes) for c in ('BTC', 'USD')},
                            score_range=[min(o['utility'] for o in outcomes), max(o['utility'] for o in outcomes)],
                            total_fills=sum(o['fills'] for o in outcomes),
                            mean_fees_usd=statistics.mean(o['fees']['USD'] for o in outcomes),
                            failures=sum(o['failed'] for o in outcomes),
                            min_floor_headroom={c: min(o['min_floor_headroom'][c] for o in outcomes) for c in ('BTC', 'USD')}))
    return summary


def run(root, output, resume=False):
    config = plan(); output = Path(output)
    identity = fingerprint(config)
    if (output / 'identity.json').exists():
        if not resume:
            raise ValueError('Existing run is immutable: --resume or new output')
        prior = json.loads((output / 'identity.json').read_text())
        if any(prior[k] != identity[k] for k in ('source_sha256', 'config_sha256')):
            raise ValueError('Resume source/config mismatch')
        identity = prior
    else:
        write(output / 'configuration.json', config)
        write(output / 'identity.json', identity)
    budget = Budget(config)
    instruments, manifest, seeds_by_date = inventory(root, config, budget)
    if (output / 'data-manifest.json').exists() and json.loads((output / 'data-manifest.json').read_text()) != manifest:
        raise ValueError('Resume data mismatch')
    write(output / 'data-manifest.json', manifest)
    for name in ('specification.json', 'input_coverage.json', 'source_receipts.json', 'seeds.json'):
        write(output / 'input-metadata' / name, json.loads((Path(root) / name).read_text()))
    results = []
    def evaluate(split, dates, preset, multiplier=1., hold=False):
        for seed in config['seeds']:
            results.append(replay(root, output, identity, config, instruments, manifest, seeds_by_date,
                                  budget, split, dates, preset, seed, multiplier, hold))
    for preset in config['presets']:
        evaluate('calibration', config['splits']['calibration'], preset)
    ranking = rank_presets(results, config['presets'])
    shortlist = [next(p for p in PRESETS if p['name'] == r['preset']) for r in ranking if r['eligible']][:2]
    write(output / 'calibration-selection.json', dict(ranking=ranking, shortlist=shortlist))
    if not shortlist:
        raise RuntimeError('No safe calibration preset; test withheld')
    for preset in shortlist:
        evaluate('validation', config['splits']['validation'], preset)
    validation = rank_presets([r for r in results if r['split'] == 'validation'], shortlist)
    if not validation[0]['eligible']:
        raise RuntimeError('No safe validation preset; test withheld')
    selected = next(p for p in shortlist if p['name'] == validation[0]['preset'])
    # Written before any test replay. No test feedback enters either selection.
    write(output / 'frozen-selection.json', dict(selected=selected, validation=validation,
                                               source_sha256=identity['source_sha256']))
    for preset in [selected] + ([PRESETS[0]] if selected['name'] != 'original' else []):
        evaluate('test', config['splits']['test'], preset)
    evaluate('test', config['splits']['test'], PRESETS[0], hold=True)
    evaluate('test', config['splits']['test'], selected, multiplier=10.)
    # The untuned original can be evaluated continuously on all 90 days without
    # applying a configuration selected using later information to earlier dates.
    evaluate('full_period_original', config['dates'], PRESETS[0])
    report = dict(identity=identity, selected=selected, calibration=ranking, validation=validation,
                  resources=dict(decisions=budget.decisions, events=budget.events, seconds=time.monotonic()-budget.started),
                  summary=summarize(results), episodes=[r['name'] for r in results],
                  limitations=['Counterfactual linear futures on inverse-source prints; no quote depth/spot execution.',
                               'Contractual/projected endpoints, no realized expiry bridges.',
                               'Hourly decisions; no claim of reproducing the two-minute neural pilot cadence.',
                               'Two latency seeds on one market path are not independent market samples; no IID confidence interval.',
                               'Test dates excluded from this calibration, but this archive has been used by earlier research.',
                               'Fixed four-point grid and two instruments; not a multi-year universe study.',
                               'Analytical score assumes every new/amended order fills; zero ties prefer waiting, including over cancellation.'])
    write(output / 'report.json', report)
    write(output / 'artifact-index.json', {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'artifact-index.json'})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    try:
        report = run(args.input, args.output, args.resume)
        print(json.dumps(dict(selected=report['selected'], resources=report['resources'])), flush=True)
    except Exception as e:
        write(Path(args.output) / 'failure.json', dict(done=False, reason=str(e), type=type(e).__name__))
        raise


if __name__ == '__main__':
    main()
