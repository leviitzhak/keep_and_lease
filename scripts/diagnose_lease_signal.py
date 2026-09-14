#!/usr/bin/env python3
"""Owner-run, read-only lease-signal reconstruction from saved decision audits.

No strategy/account replay, remote writes, exchange requests or deployments.
Preserves every decision and every contract calculation; never infers the signal
from the average lease rate of filled holdings. See docs/LEASE_SIGNAL_DIAGNOSTIC.md.
"""
from __future__ import annotations
import argparse
import ast
import base64
import bisect
import collections
import csv
import datetime as dt
import gzip
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import textwrap
from dataclasses import asdict

from diagnose_run_costs import Reader, MIB, DAY_US, us, iso, result_json

HOUR_US = 3_600_000_000
MARKET = 'gs://keep-and-lease-market-data/'
SOURCE_FILES = ('btc_trade_backtest.py', 'trade_replay.py', 'backtest_audit.py',
    'trade_data_store.py', 'trade_ordering.py', 'backtest_silver_lease_strategy.py',
    'maturity_scoring.py', 'silver_strategy_gui.py', 'market_data_store.py',
    'rate_change_attribution.py', 'observed_execution.py', 'replay_checkpoints.py')
RATE_FILES = ('DTB3.csv', 'DTB6.csv', 'DGS1.csv', 'DGS2.csv', 'DGS3.csv', 'DGS5.csv')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


class CloudInputs:
    """Read fixed project bucket objects, pin generations, and retain receipts."""
    def __init__(self, run_id, budget, output):
        self.run = Reader(run_id, budget)
        self.budget, self.bytes_read = budget, 0
        self.out = Path(output)
        self.receipts = {}

    def fetch(self, uri, destination, *, cap=64*MIB, expected=None):
        if not (uri.startswith(self.run.root) or uri.startswith(MARKET)):
            raise ValueError('Input is outside the selected run and market-data bucket')
        if any(x in uri for x in ('..', '#', '?', '\\')):
            raise ValueError('Unsafe input object path')
        metadata = json.loads(Reader._command(
            ['storage', 'objects', 'describe', uri, '--raw', '--format=json']))
        size, generation = int(metadata['size']), str(metadata['generation'])
        if size > cap or self.bytes_read + self.run.bytes_read + size > self.budget:
            raise ValueError('Input read budget exceeded; explicitly raise --max-read-mib')
        dest = Path(destination); dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            Reader._command(['storage', 'cat', uri+'#'+generation], stream)
        digest = hashlib.sha256()
        with dest.open('rb') as stream:
            for block in iter(lambda: stream.read(MIB), b''):
                digest.update(block)
        if dest.stat().st_size != size or (expected and digest.hexdigest() != expected):
            raise ValueError('Input object checksum/size mismatch')
        self.bytes_read += size
        self.receipts[uri] = dict(generation=generation, bytes=size, sha256=digest.hexdigest())
        return dest

    def run_bytes(self, name):
        dest = self.out/'inputs'/name
        if dest.exists():
            return dest.read_bytes()
        self.run.budget = self.budget-self.bytes_read
        data = self.run.get(name)
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
        return data

    def chunk(self, entry):
        # Reuse the existing checked decoder, with its generation-pinned download
        # cached locally. Each chunk is fully exhausted even at period boundaries.
        self.run_bytes('audit/'+entry['object'])
        local = Reader('local', self.budget, self.out/'inputs')
        yield from local.chunk(entry)


def snapshot_engine(repo, commit, out):
    if not re.fullmatch('[0-9a-f]{40}', commit or ''):
        raise ValueError('Saved engine commit is absent; do not substitute the current engine')
    out = Path(out); out.mkdir()
    hashes = {}
    for name in SOURCE_FILES + RATE_FILES:
        p = subprocess.run(['git', '-C', str(repo), 'show', commit+':'+name],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if p.returncode:
            raise ValueError(f'Original engine input missing: {name}. Fetch the recorded commit {commit}; no current-source fallback is used.')
        (out/name).write_bytes(p.stdout); hashes[name] = sha(p.stdout)
    return hashes


def traced_selector(strategy):
    """Capture original function locals without rewriting its numerical logic."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(strategy.positions_for_day)))
    fn = tree.body[0]; fn.name = '_diagnostic_select'
    # Nested select_long must retain its ordinary return values.
    class Returns(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            return node
        def visit_Return(self, node):
            return ast.copy_location(ast.Return(ast.Tuple([
                node.value or ast.Constant(None), ast.Call(ast.Name('locals', ast.Load()), [], [])
            ], ast.Load())), node)
    fn.body = [Returns().visit(node) for node in fn.body]
    ast.fix_missing_locations(tree)
    scope = dict(vars(strategy)); exec(compile(tree, '<original-selector-trace>', 'exec'), scope)
    return scope[fn.name]


class Rates:
    """Original engine maturity interpolation, with exact observable tenor rows."""
    def __init__(self, strategy, root):
        self.s, self.series = strategy, strategy.read_rates(Path(root))
        self.rows = {}
        for tenor, name in strategy.TENORS:
            items = self.series[tenor]
            self.rows[tenor] = (name, items, [us(strategy._rate_available_at(
                obs, dt.datetime(2000,1,1)).isoformat()) for obs, rate in items])
    def at(self, tick, maturity):
        day = dt.datetime(1970,1,1) + dt.timedelta(microseconds=tick)
        rate = self.s.usd_rate(self.series, day, maturity)
        components = []
        for tenor, r, weight in self.s.usd_rate_components(self.series, day, maturity):
            name, items, times = self.rows[tenor]
            i = bisect.bisect_right(times, tick)-1
            if i < 0 or not math.isclose(r, items[i][1], abs_tol=1e-15):
                raise ValueError('Treasury component does not reconcile to original as-of row')
            components.append(dict(series=name, tenor_days=tenor,
                observation=items[i][0].isoformat(), available_at_utc=iso(times[i]),
                yield_fraction=r, interpolation_weight=weight))
        return rate, components


def lease_parts(old, new):
    """Exact sequential attribution: yield, future, spot, then maturity clock."""
    if old is None or min(old['maturity_days'], new['maturity_days']) <= 0:
        return {}
    f0, s0, d0 = old['future_price'], old['spot_price'], old['maturity_days']
    f1, s1, d1 = new['future_price'], new['spot_price'], new['maturity_days']
    parts = dict(yield_change_bps=(new['usd_rate_fraction']-old['usd_rate_fraction'])*10000,
        futures_move_bps=-(f1-f0)/s0*365/d0*10000,
        spot_move_bps=-f1*(1/s1-1/s0)*365/d0*10000,
        maturity_clock_bps=-(f1/s1-1)*365*(1/d1-1/d0)*10000)
    parts['change_attribution_error_bps'] = ((new['lease_fraction']-old['lease_fraction'])*10000-sum(parts.values()))
    return parts


def initialize_db(path, checkpoint):
    db = sqlite3.connect(path)
    db.execute('PRAGMA cache_size=-16384')
    db.execute('CREATE TABLE valuations(t INTEGER PRIMARY KEY, row TEXT NOT NULL)')
    db.execute('CREATE TABLE refs(symbol TEXT,id TEXT,raw_us INTEGER,effective_us INTEGER,PRIMARY KEY(symbol,id))')
    db.execute('CREATE TABLE marks(symbol TEXT,id TEXT,raw_us INTEGER,price TEXT,btc REAL,executable INTEGER,source TEXT,source_sequence INTEGER,PRIMARY KEY(symbol,id))')
    for symbol, m in checkpoint['account']['marks'].items():
        raw_time = m.get('reported_us') if m.get('reported_us') is not None else m['us']
        db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?,?,?)', (symbol,str(m['identifier']),
            raw_time,repr(m['price']),m['btc'],int(m['executable']),'checkpoint',m.get('sequence')))
    return db


def stage_valuations(db, inputs, entries, checkpoint, end):
    start = checkpoint['state']['previous_tick']
    selected = [e for e in entries if us(e['end']) > start and us(e['start']) < end]
    if not selected:
        raise ValueError('No full-resolution valuation audit in the requested interval')
    previous = start; count = 0
    for n, entry in enumerate(selected, 1):
        for row in inputs.chunk(entry):
            t = int(row['us'])
            if not start < t < end:
                continue
            if t <= previous:
                raise ValueError('Duplicate or reversed valuation timestamp')
            previous = t; count += 1
            db.execute('INSERT INTO valuations VALUES(?,?)',(t,json.dumps(row,separators=(',',':'))))
            reported = row.get('reported_mark_us')
            if reported is None:
                raise ValueError('Reported mark timestamps missing: cannot locate source days without guessing')
            for symbol, identifier in row['mark_ids'].items():
                raw_time, effective = int(reported[symbol]), int(row['mark_us'][symbol])
                if effective > t or raw_time > effective:
                    raise ValueError('Noncausal mark timestamp in saved valuation')
                db.execute('INSERT OR IGNORE INTO refs VALUES(?,?,?,?)',
                           (symbol,str(identifier),raw_time,effective))
        db.commit()
        if n % 10 == 0 or n == len(selected):
            print(f'Valuation chunks verified: {n}/{len(selected)}', file=sys.stderr,flush=True)
    return count


def resolve_marks(db, manifest, manifest_uri, inputs, output):
    """Join recorded IDs, not a new ordering simulation, to immutable raw records."""
    import pyarrow.parquet as pq
    missing = list(db.execute('SELECT r.symbol,r.id,r.raw_us FROM refs r LEFT JOIN marks m USING(symbol,id) WHERE m.id IS NULL'))
    dates = collections.defaultdict(dict)
    for symbol, identifier, raw_time in missing:
        dates[iso(raw_time)[:10]][(symbol,identifier)] = raw_time
    days = manifest.get('daily_datasets')
    if days:
        by_date = {d['start'][:10]:d for d in days}
    else:
        by_date = {manifest['source_manifest']['start'][:10]:None}
    for date, needed in sorted(dates.items()):
        if date not in by_date:
            raise ValueError(f'Referenced marks on {date} absent from the pinned dataset')
        day = by_date[date]
        root = MARKET+'btc/trades/v1/'+day['manifest_sha256'] if day else manifest_uri
        child = manifest
        if day:
            file = inputs.fetch(root+'/manifest.json', Path(output)/'inputs'/('market-'+date+'.json'), expected=day['manifest_sha256'])
            child = json.loads(file.read_bytes())
            if child['source_manifest']['start'] != day['start'] or child['source_manifest']['end'] != day['end']:
                raise ValueError('Daily market coverage differs from range manifest')
        for part in child['partitions']:
            relative = part['path']
            if Path(relative).is_absolute() or '..' in Path(relative).parts:
                raise ValueError('Unsafe market partition path')
            spot_part = '/market=spot/' in '/'+relative
            wanted = {k:v for k,v in needed.items() if (k[0]=='SPOT')==spot_part and part['first_us']<=v<=part['last_us']}
            if not wanted:
                continue
            print(f'Resolving recorded {date} {"spot" if spot_part else "futures"} marks ({len(wanted):,} references)',file=sys.stderr,flush=True)
            path = inputs.fetch(root+'/'+relative, Path(output)/'inputs'/('partition-'+sha((root+'/'+relative).encode())+'.parquet'),
                                cap=512*MIB, expected=part['sha256'])
            columns = ['timestamp_us','symbol','trade_id','price','native_quantity','quantity_currency','flags','source_sequence']
            with pq.ParquetFile(path, pre_buffer=False) as file:
                for batch in file.iter_batches(batch_size=8192,columns=columns,use_threads=False):
                    lists = [c.to_pylist() for c in batch.columns]
                    for timestamp,symbol,identifier,price,quantity,currency,flags,sequence in zip(*lists):
                        key = symbol,str(identifier)
                        if key not in wanted:
                            continue
                        if timestamp != wanted[key] or float(price)<=0 or currency not in ('BTC','USD'):
                            raise ValueError('Recorded mark identity/time does not match source input')
                        btc = float(quantity) if currency=='BTC' else float(quantity)/float(price)
                        values = (symbol,str(identifier),timestamp,str(price),btc,int(flags==0),root+'/'+relative,sequence)
                        prior = db.execute('SELECT * FROM marks WHERE symbol=? AND id=?',key).fetchone()
                        if prior is not None and prior != values:
                            raise ValueError('Conflicting source records for the same mark ID')
                        if prior is None:
                            db.execute('INSERT INTO marks VALUES(?,?,?,?,?,?,?,?)',values)
            db.commit(); path.unlink()  # matched original values and receipts remain in SQLite/CSVs
    unresolved = db.execute('SELECT count(*) FROM refs r LEFT JOIN marks m USING(symbol,id) WHERE m.id IS NULL').fetchone()[0]
    if unresolved:
        raise ValueError(f'{unresolved} recorded marks unresolved; no prices are interpolated or invented')


class Signal:
    def __init__(self, strategy, gui, rates, payload, checkpoint, manifest, lookup):
        merged = gui.product_payload(payload,'btc')
        merged['execution_interval_seconds'] = payload.get('execution_interval_seconds',0)
        for k in ('bond_mode','treasury_allocation_mode','treasury_asset','reactivity'):
            if k in payload: merged[k] = payload[k]
        self.p = gui.parameters(merged)
        if self.p.enable_short_book or self.p.futures_contract_type!='regular':
            raise ValueError('Diagnostic supports the saved long-only regular BTC replay, not inverse/short books')
        self.s,self.rates,self.choose,self.lookup = strategy,rates,traced_selector(strategy),lookup
        self.previous_t = int(checkpoint['state']['previous_tick'])
        self.previous_allocation = checkpoint['state']['previous_allocation']
        self.expiries = {s:us(v['expiry']) for s,v in manifest['source_manifest']['futures'].items()}
        self.prior = {}; self.previous_signal = None; self.previous_fee = checkpoint['account']['fees']
        self.last_marks = {}
        self.previous_observation = None

    def mark(self, symbol, identifier):
        key = symbol,str(identifier)
        if symbol not in self.last_marks or self.last_marks[symbol][0] != key:
            self.last_marks[symbol] = (key,self.lookup(key))
        return self.last_marks[symbol][1]

    def step(self, row):
        p = self.p; t = int(row['us']); nav = float(row['nav_usd'])
        marks = {s:self.mark(s,i) for s,i in row['mark_ids'].items()}
        spot = float(marks['SPOT']['price']); spot_time = int(row['mark_us']['SPOT'])
        if marks['SPOT']['raw_us']!=int(row['reported_mark_us']['SPOT']):
            raise ValueError('Spot mark timestamp differs from the saved source reference')
        candidates, details = [],[]
        for symbol,expiry in self.expiries.items():
            if symbol not in marks: continue
            m = marks[symbol]; future = float(m['price']); days = (expiry-t)/DAY_US
            age = (t-int(row['mark_us'][symbol]))/1e6
            if int(m['raw_us']) != int(row['reported_mark_us'][symbol]):
                raise ValueError('Mark timestamp differs from stored reported time')
            rate,components = self.rates.at(t,days)
            premium = future/spot-1
            lease = rate-premium*365/days if rate is not None and days>0 else None
            reason = ('expired' if days<=0 else 'excluded_trade_type' if not m['executable'] else
                      'stale_future' if age>p.max_quote_age_seconds else 'no_usd_rate' if rate is None else
                      'below_min_days' if days<p.min_days else 'eligible')
            d = dict(time_utc=iso(t),symbol=symbol,expiry_utc=iso(expiry),maturity_days=days,
                spot_price=spot,spot_source_decimal=marks['SPOT']['price'],spot_trade_id=str(row['mark_ids']['SPOT']),
                spot_effective_time_utc=iso(spot_time),spot_reported_time_utc=iso(marks['SPOT']['raw_us']),
                spot_age_seconds=(t-spot_time)/1e6,spot_source=marks['SPOT']['source'],
                future_price=future,future_source_decimal=m['price'],future_trade_id=str(row['mark_ids'][symbol]),
                future_effective_time_utc=iso(int(row['mark_us'][symbol])),future_reported_time_utc=iso(m['raw_us']),
                future_age_seconds=age,effective_time_gap_seconds=(spot_time-int(row['mark_us'][symbol]))/1e6,
                source_sequence=m['source_sequence'],future_source=m['source'],eligibility=reason,
                premium_fraction=premium,annualized_premium_fraction=premium*365/days if days>0 else None,
                usd_rate_fraction=rate,rate_components=components,lease_fraction=lease,
                lease_pct=lease*100 if lease is not None else None,
                lease_bps_per_day=lease*10000/365 if lease is not None else None)
            if lease is not None and self.prior.get(symbol,{}).get('lease_fraction') is not None:
                d.update(lease_parts(self.prior[symbol],d))
            details.append(d)
            if reason in ('eligible','below_min_days'):
                candidates.append(dict(symbol=symbol,days=days,future=future,spot=spot,premium=premium,
                                       rate=rate,lease=lease,volume=m['btc']))
        previous = {'base_longs':{s:q*float(marks[s]['price'])/nav for s,q in row['units'].items() if s!='SPOT' and q>0},'shorts':{}}
        if self.previous_allocation is not None: previous['base_treasury']=self.previous_allocation
        desired,trace = self.choose(candidates,p,previous,elapsed_days=(t-self.previous_t)/DAY_US)
        selection = trace.get('selected_positive')
        chosen = next((d for d in details if selection and d['symbol']==selection['symbol']),None)
        active = desired is not None and t-spot_time<=p.max_quote_age_seconds*1e6
        computed = None
        if active:
            computed = {s:w*nav/float(marks[s]['price']) for s,w in desired['base_longs'].items()}
            computed['SPOT']=desired['slv']*nav/spot
        recorded = row['targets']
        mismatch = (computed is None)!=(recorded is None); max_error=0.0
        if computed is not None and recorded is not None:
            for symbol in set(computed)|set(recorded):
                a,b=float(computed.get(symbol,0)),float(recorded.get(symbol,0))
                max_error=max(max_error,abs(a-b))
                mismatch |= not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-10)
        raw_weight = self.s.clamp(p.max_futures_treasury_fraction*trace.get('positive_strength',0.0)) if p.enable_cash_long_futures_leg else 0.0
        applied = desired['base_treasury'] if active else None
        actual_spot = row['units'].get('SPOT',0.0)*spot/nav
        actual_future = sum(abs(q)*float(marks[s]['price']) for s,q in row['units'].items() if s!='SPOT')/nav
        allocation_candidates = trace.get('allocation_long_candidates',[])
        threshold = trace.get('long_score_threshold')
        for d in details:
            d['selected_allocation_driver'] = bool(chosen and chosen['symbol']==d['symbol'])
            d['passes_positive_entry_gate'] = d['lease_fraction']>p.positive_entry_rate if d['lease_fraction'] is not None else None
            d['entry_threshold_fraction'] = p.positive_entry_rate
            d['full_allocation_threshold_fraction'] = p.positive_full_rate
            c = next((c for c in candidates if c['symbol']==d['symbol']),None)
            rank_candidates=trace.get('long_candidates',[])
            rank_floor=min((c['lease'] for c in rank_candidates),default=None)
            d['selection_logit']=None
            if c and rank_floor is not None and any(x['symbol']==c['symbol'] for x in rank_candidates) and p.long_contract_selection!='shortest_maturity':
                d['selection_logit']=self.s.maturity_line_adjusted_score(max(1e-9,c['lease']-rank_floor),c,p,'long')
            d['pre_sticky_allocation_logit'] = (self.s.maturity_line_adjusted_score(d['lease_fraction']-threshold,c,p,'long')
                if c and threshold is not None and any(x['symbol']==c['symbol'] for x in allocation_candidates) else None)
            d['allocation_score_base_threshold_fraction']=threshold
            d['score_calculation']=self.s.score_diagnostic(c,p,'long',threshold) if c and threshold is not None else None
            d['target_notional_weight'] = desired['base_longs'].get(d['symbol'],0.0) if desired else None
        obs = dict(time_utc=iso(t),signal_contract=chosen['symbol'] if chosen else None,
            signal_lease_pct=chosen['lease_pct'] if chosen else None,
            best_eligible_lease_pct=max((100*c['lease'] for c in trace.get('eligible',[])),default=None),
            diagnostic_weighted_lease_pct=desired['signal']*100 if desired and desired['signal'] is not None else None,
            driver_future_price=chosen['future_price'] if chosen else None,spot_price=spot,
            driver_maturity_days=chosen['maturity_days'] if chosen else None,
            driver_future_age_seconds=chosen['future_age_seconds'] if chosen else None,
            spot_age_seconds=(t-spot_time)/1e6,entry_threshold_pct=p.positive_entry_rate*100,
            full_threshold_pct=p.positive_full_rate*100,max_futures_weight_pct=p.max_futures_treasury_fraction*100,
            raw_futures_weight_pct=raw_weight*100 if desired else None,
            previous_futures_weight_pct=self.previous_allocation*100 if self.previous_allocation is not None else None,
            target_futures_weight_pct=applied*100 if applied is not None else None,
            target_spot_weight_pct=(1-applied)*100 if applied is not None else None,
            actual_spot_weight_pct=actual_spot*100,actual_futures_weight_pct=actual_future*100,
            cash_weight_pct=float(row['cash_usd'])/nav*100,
            nav_usd=nav,fee_counter_usd=float(row['fees_usd']),
            fees_since_previous_valuation_usd=float(row['fees_usd'])-self.previous_fee,
            target_spot_btc=recorded.get('SPOT',0) if recorded is not None else None,
            actual_spot_btc=row['units'].get('SPOT',0),
            allocation_gate='submitted' if active else 'stale_spot' if desired else 'no_eligible_curve',
            target_matches_saved=not mismatch,max_target_quantity_error_btc=max_error,
            half_life_days=p.long_allocation_half_life_days,elapsed_seconds=(t-self.previous_t)/1e6,
            signal_contract_changed=bool(self.previous_signal and chosen and self.previous_signal['symbol']!=chosen['symbol']),
            spot_mark_changed=bool(self.previous_observation and str(row['mark_ids']['SPOT'])!=self.previous_observation['spot_id']),
            eligible_contracts='|'.join(c['symbol'] for c in trace.get('eligible',[])),
            eligible_contract_set_changed=bool(self.previous_observation and {c['symbol'] for c in trace.get('eligible',[])}!=self.previous_observation['eligible']))
        if chosen:
            for k in ('yield_change_bps','futures_move_bps','spot_move_bps','maturity_clock_bps','change_attribution_error_bps'):
                obs[k]=chosen.get(k)
            old_same = self.prior.get(chosen['symbol'])
            obs['contract_selection_effect_bps'] = ((old_same['lease_fraction']-self.previous_signal['lease_fraction'])*10000
                if old_same and old_same['lease_fraction'] is not None and self.previous_signal else None)
            obs['driver_future_mark_changed'] = bool(old_same and old_same['future_trade_id']!=chosen['future_trade_id'])
        else:
            for k in ('yield_change_bps','futures_move_bps','spot_move_bps','maturity_clock_bps','change_attribution_error_bps','contract_selection_effect_bps'):
                obs[k]=None
            obs['driver_future_mark_changed']=None
        if active: self.previous_allocation=desired['base_treasury']
        self.previous_fee=float(row['fees_usd']); self.previous_t=t
        self.previous_signal=chosen; self.prior={d['symbol']:d for d in details}
        self.previous_observation={'spot_id':str(row['mark_ids']['SPOT']),'eligible':{c['symbol'] for c in trace.get('eligible',[])}}
        return obs,details


def quantiles(values):
    values = sorted(v for v in values if v is not None)
    if not values: return None
    return dict(zip(('min','p05','median','p95','max'),
        (values[int((len(values)-1)*q)] for q in (0,.05,.5,.95,1))))


def summarize(rows):
    jumps=[]; previous=None; hours=collections.defaultdict(list); causes=collections.Counter()
    gaps=[]
    for r in rows:
        hours[r['time_utc'][:13]].append(r)
        if previous:
            a,b = r['target_futures_weight_pct'],previous['target_futures_weight_pct']
            if a is not None and b is not None:
                delta=a-b
                if abs(delta)>=5:
                    if r['eligible_contract_set_changed']: cause='eligible_contract_set_changed'
                    elif r['signal_contract_changed']: cause='selected_contract_changed'
                    elif r['spot_mark_changed'] and not r['driver_future_mark_changed']: cause='spot_updated_driver_future_unchanged'
                    elif r['driver_future_mark_changed'] and not r['spot_mark_changed']: cause='driver_future_updated_spot_unchanged'
                    elif r['driver_future_mark_changed'] and r['spot_mark_changed']: cause='both_prices_updated'
                    else: cause='eligibility_clock_or_other_state'
                    causes[cause]+=1
                    jumps.append(dict(time_utc=r['time_utc'],allocation_change_percentage_points=delta,
                        signal_before_pct=previous['signal_lease_pct'],signal_after_pct=r['signal_lease_pct'],
                        contract_before=previous['signal_contract'],contract_after=r['signal_contract'],classification=cause,
                        future_age_seconds=r['driver_future_age_seconds'],spot_age_seconds=r['spot_age_seconds']))
        if r['allocation_gate']!='submitted': gaps.append(r['time_utc'])
        previous=r
    hourly=[]
    for hour, items in sorted(hours.items()):
        hourly.append(dict(hour_utc=hour+':00:00Z',decisions=len(items),
            lease_pct=quantiles(r['signal_lease_pct'] for r in items),
            target_futures_weight_pct=quantiles(r['target_futures_weight_pct'] for r in items),
            actual_futures_weight_pct=quantiles(r['actual_futures_weight_pct'] for r in items),
            fees_in_preceding_valuation_intervals_usd=sum(r['fees_since_previous_valuation_usd'] for r in items)))
    return dict(decisions=len(rows),signal_lease_pct=quantiles(r['signal_lease_pct'] for r in rows),
        target_futures_weight_pct=quantiles(r['target_futures_weight_pct'] for r in rows),
        actual_futures_weight_pct=quantiles(r['actual_futures_weight_pct'] for r in rows),
        driver_future_age_seconds=quantiles(r['driver_future_age_seconds'] for r in rows),
        target_mismatches=sum(not r['target_matches_saved'] for r in rows),
        max_target_quantity_error_btc=max((r['max_target_quantity_error_btc'] for r in rows),default=0),
        no_submission_decisions=len(gaps),large_allocation_changes_at_least_5pp=len(jumps),
        large_change_classifications=dict(causes),
        largest_allocation_changes=sorted(jumps,key=lambda r:abs(r['allocation_change_percentage_points']),reverse=True)[:100],
        hourly=hourly)


HTML = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lease signal and allocation audit</title><style>
body{font:16px system-ui;margin:24px;max-width:1300px}canvas{width:100%;height:280px;border:1px solid #aaa}
label{display:inline-block;margin:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{margin:28px 0}input{font:inherit}
</style><h1>Recorded-decision lease signal</h1><p id="status">Loading locally embedded data…</p>
<p>All decision rows are retained. At wide zoom, min/max envelopes preserve spikes; narrow the UTC range to inspect individual decisions.
No external requests are made. This is the rate used by the model, not a simultaneous executable quote or proof of profitable switching.</p>
<label>From UTC <input type="datetime-local" id="start" step="0.001"></label><label>To UTC <input type="datetime-local" id="end" step="0.001"></label><button id="reset">Full day</button>
<article><h2>Allocation-driving lease rate (% annualized)</h2><canvas id="signal"></canvas><p>Signal and configured entry/full-allocation thresholds. Gaps mean no selected allocation-driving contract.</p></article>
<article><h2>Futures allocation (%)</h2><canvas id="allocation"></canvas><p>Raw target, smoothed target, and actually held futures exposure. A target is not a fill.</p></article>
<article><h2>Cumulative fees since the first displayed observation (USD)</h2><canvas id="fees"></canvas><p>Fees in each valuation precede the new target submitted at that same decision.</p></article>
<pre id="hover"></pre><script>
(async()=>{try{
const compressed=Uint8Array.from(atob('__DATA__'),c=>c.charCodeAt(0));
const text=await new Response(new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
const data=JSON.parse(text), rows=data.rows, $=id=>document.getElementById(id);
let selected=rows; const local=t=>new Date(t).toISOString().slice(0,23);
function reset(){$('start').value=local(rows[0][0]);$('end').value=local(rows[rows.length-1][0]);draw()}
const colors=['#2257a5','#b3442e','#168157'];
function chart(id,series,reference=[]){const c=$(id),w=c.clientWidth,h=280,dpr=devicePixelRatio||1;c.width=w*dpr;c.height=h*dpr;const x=c.getContext('2d');x.scale(dpr,dpr);const left=66,right=w-12,top=18,bottom=h-32;
let low=Infinity,high=-Infinity;for(const r of selected)for(const [,fn]of series){const v=fn(r);if(v!==null&&Number.isFinite(v)){low=Math.min(low,v);high=Math.max(high,v)}}for(const v of reference){low=Math.min(low,v);high=Math.max(high,v)}
if(!Number.isFinite(low)){x.fillText('No applicable data in this window',left,40);return}if(low===high){low-=1e-4;high+=1e-4}
const X=t=>left+(t-selected[0][0])/(selected[selected.length-1][0]-selected[0][0]||1)*(right-left),Y=v=>bottom-(v-low)/(high-low)*(bottom-top);
x.fillStyle='#111';x.font='12px system-ui';for(let i=0;i<5;i++){const v=low+(high-low)*i/4;x.fillText(v.toFixed(4),2,Y(v));}x.fillText(new Date(selected[0][0]).toISOString().slice(11,23),left,h-9);x.fillText(new Date(selected[selected.length-1][0]).toISOString().slice(11,23),Math.max(left,right-105),h-9);
for(const v of reference){x.strokeStyle='#888';x.setLineDash([5,5]);x.beginPath();x.moveTo(left,Y(v));x.lineTo(right,Y(v));x.stroke()}x.setLineDash([]);
series.forEach(([name,fn],index)=>{x.strokeStyle=colors[index%3];x.fillStyle=colors[index%3];x.fillText(name,left+index*180,12);
if(selected.length>(right-left)*3){const buckets=new Map;for(const r of selected){let v=fn(r);if(v===null||!Number.isFinite(v))continue;const k=Math.round(X(r[0]));const a=buckets.get(k)||[v,v];a[0]=Math.min(a[0],v);a[1]=Math.max(a[1],v);buckets.set(k,a)}x.beginPath();for(const[k,[a,b]]of buckets){x.moveTo(k,Y(a));x.lineTo(k,Y(b)+(a===b?.6:0));}x.stroke();}
else{x.beginPath();let on=false;for(const r of selected){const v=fn(r);if(v===null||!Number.isFinite(v)){on=false;continue}if(on)x.lineTo(X(r[0]),Y(v));else x.moveTo(X(r[0]),Y(v));on=true}x.stroke()}});
c.onpointermove=e=>{const t=selected[0][0]+Math.max(0,Math.min(1,(e.clientX-c.getBoundingClientRect().left-left)/(right-left)))*(selected[selected.length-1][0]-selected[0][0]);let lo=0,hi=selected.length-1;while(lo<hi){let m=(lo+hi)>>1;if(selected[m][0]<t)lo=m+1;else hi=m}let r=selected[lo];$('hover').textContent=JSON.stringify(Object.fromEntries(data.fields.map((f,i)=>[f,i===0?new Date(r[i]).toISOString():r[i]])),null,2)};
}
function draw(){const lo=Date.parse($('start').value+'Z'),hi=Date.parse($('end').value+'Z');selected=rows.filter(r=>r[0]>=lo&&r[0]<=hi);if(!selected.length)return;
chart('signal',[['Signal',r=>r[1]]],[data.entry,data.full]);chart('allocation',[['Raw target',r=>r[2]],['Smoothed target',r=>r[3]],['Actual futures',r=>r[4]]]);const base=rows[0][5];chart('fees',[['Cumulative increase',r=>r[5]-base]]);}
$('status').textContent=data.status+' · '+rows.length.toLocaleString()+' decision rows · original engine '+data.commit;
$('start').onchange=$('end').onchange=draw;$('reset').onclick=reset;addEventListener('resize',draw);reset();
}catch(e){document.getElementById('status').textContent='Cannot render: '+e.message+'; use the full CSV exports.'}})();
</script></html>'''


def write_view(out, rows, report, p):
    fields=['time_utc','signal_lease_pct','raw_futures_weight_pct','target_futures_weight_pct',
        'actual_futures_weight_pct','fee_counter_usd','signal_contract','spot_price','driver_future_price',
        'driver_future_age_seconds','spot_age_seconds','actual_spot_weight_pct','target_spot_weight_pct','target_matches_saved']
    data=dict(fields=fields,rows=[[us(r['time_utc'])/1000]+[r[k] for k in fields[1:]] for r in rows],
        entry=p.positive_entry_rate*100,full=p.positive_full_rate*100,status=report['status'],commit=report['engine_commit'])
    encoded=base64.b64encode(gzip.compress(json.dumps(data,allow_nan=False,separators=(',',':')).encode())).decode()
    (Path(out)/'evolution.html').write_text(HTML.replace('__DATA__',encoded))


def run(args):
    out=Path(args.output).expanduser().resolve()
    if out.exists(): raise ValueError('Use a new output directory; existing results are never replaced')
    if not re.fullmatch('[0-9a-f]{32}',args.run_id): raise ValueError('Invalid saved-run ID')
    if not 1<=args.days<=7 or args.max_read_mib<=0: raise ValueError('Choose 1–7 days and a positive read budget')
    try: import pyarrow.parquet
    except ImportError: raise ValueError('Install pyarrow in your Python environment before running this diagnostic') from None
    out.mkdir(parents=True)
    write_json(out/'status.json',{'status':'IN_PROGRESS_NOT_VALIDATED'})
    inputs=CloudInputs(args.run_id,args.max_read_mib*MIB,out)
    result=result_json(inputs.run_bytes('result.json.gz'))
    manifest=json.loads(inputs.run_bytes('audit/manifest.json'))
    if result.get('result_kind')!='btc_trade_replay': raise ValueError('This is not a trade replay result')
    provenance=manifest['provenance']; engine_commit=provenance.get('engine_commit')
    payload=provenance.get('parameters',result.get('parameters'))
    if not isinstance(payload,dict): raise ValueError('Original run parameters missing')
    start,end=us(result['summary']['start']),us(result['summary']['end'])
    lo=us(args.day+'T00:00:00Z') if args.day else ((start+DAY_US-1)//DAY_US)*DAY_US
    hi=lo+args.days*DAY_US
    if lo<start or hi>end: raise ValueError('Select complete UTC days inside the saved run')
    interval=int(round(float(result['trade_replay']['interval_seconds'])*1e6))
    if interval<=0 or HOUR_US%interval: raise ValueError('An exact hourly-aligned decision clock is required')
    checkpoint_time=lo-HOUR_US
    if checkpoint_time<=start: raise ValueError('This extraction needs the checkpoint one hour before the selected day')
    checkpoint_file=inputs.fetch(inputs.run.root+f'checkpoints/{checkpoint_time:020d}.json.gz',out/'inputs'/'checkpoint.json.gz',cap=16*MIB)
    source=out/'original_engine'
    source_hashes=snapshot_engine(Path(args.repo),engine_commit,source)
    sys.path.insert(0,str(source))
    strategy=importlib.import_module('backtest_silver_lease_strategy')
    gui=importlib.import_module('silver_strategy_gui')
    cpmod=importlib.import_module('replay_checkpoints')
    checkpoint=cpmod.decode(checkpoint_file.read_bytes())
    if checkpoint['state']['previous_tick']!=checkpoint_time: raise ValueError('Unexpected checkpoint boundary')
    trade=provenance.get('trade_data') or result['trade_replay']
    uri=trade['dataset_uri'].rstrip('/')
    if not re.fullmatch(r'gs://keep-and-lease-market-data/btc/trades/(ranges|v1)/[0-9a-f]{64}',uri):
        raise ValueError('Unsupported immutable market dataset URI')
    market_file=inputs.fetch(uri+'/manifest.json',out/'inputs'/'market-manifest.json',expected=trade['manifest_sha256'])
    market_bytes=market_file.read_bytes(); market=json.loads(market_bytes)
    if cpmod.fingerprint(payload,market_bytes,source)!=checkpoint['identity']:
        raise ValueError('Original engine/rates/parameters/market bytes do not match checkpoint identity; no approximate reconstruction is certified')
    write_json(out/'parameters.json',payload)
    db=initialize_db(out/'observations.sqlite',checkpoint)
    try:
        count=stage_valuations(db,inputs,manifest['datasets']['btc_trade_valuations']['chunks'],checkpoint,hi)
        if count!=(hi-checkpoint_time)//interval-1: raise ValueError('Missing or extra decision audit rows')
        expected=checkpoint_time+interval
        for t, in db.execute('SELECT t FROM valuations ORDER BY t'):
            if t!=expected: raise ValueError('A decision tick is missing or off-grid')
            expected+=interval
        resolve_marks(db,market,uri,inputs,out)
        def lookup(key):
            record=db.execute('SELECT * FROM marks WHERE symbol=? AND id=?',key).fetchone()
            if record is None: raise ValueError('A required price record is unresolved')
            return dict(zip(('symbol','id','raw_us','price','btc','executable','source','source_sequence'),record))
        engine=Signal(strategy,gui,Rates(strategy,source),payload,checkpoint,market,lookup)
        write_json(out/'effective_parameters.json',asdict(engine.p))
        rows=[]; warmup_mismatches=0; writers={}; streams=[]; calculation_count=0
        try:
            for i,(t,stored) in enumerate(db.execute('SELECT t,row FROM valuations ORDER BY t'),1):
                obs,details=engine.step(json.loads(stored))
                if t<lo:
                    warmup_mismatches+=not obs['target_matches_saved'];continue
                rows.append(obs)
                for name,records in [('decisions', [obs]),('lease-calculations',details)]:
                    for record in records:
                        if name not in writers:
                            stream=gzip.open(out/(name+'.csv.gz'),'wt',newline='');streams.append(stream)
                            fields=sorted(set(record)|({'yield_change_bps','futures_move_bps','spot_move_bps','maturity_clock_bps','change_attribution_error_bps'} if name=='lease-calculations' else set()))
                            writers[name]=csv.DictWriter(stream,fieldnames=fields);writers[name].writeheader()
                        writers[name].writerow({k:json.dumps(v,separators=(',',':'),allow_nan=False) if isinstance(v,(list,dict)) else v for k,v in record.items()})
                        if name=='lease-calculations': calculation_count+=1
                if i%10000==0: print(f'Reconstructed {i:,}/{count:,} stored decisions',file=sys.stderr,flush=True)
        finally:
            for stream in streams: stream.close()
        stats=summarize(rows)
        failed=stats['target_mismatches']>0 or warmup_mismatches>0
        report=dict(run_id=args.run_id,mode='read-only recorded-state signal reconstruction; no financial replay',
            selected_period=dict(start=iso(lo),end_exclusive=iso(hi)),engine_commit=engine_commit,
            checkpoint_time_utc=iso(checkpoint_time),checkpoint_identity_verified=True,
            status='TARGET_RECONSTRUCTION_MISMATCH' if failed else 'MATCHED_SAVED_TARGETS_AT_EVERY_DECISION',
            calculations=calculation_count,warmup_target_mismatches=warmup_mismatches,statistics=stats,
            effective_parameters=asdict(engine.p),original_source_sha256=source_hashes,
            input_receipts={**inputs.receipts,**inputs.run.receipts},
            bytes_read=inputs.bytes_read+inputs.run.bytes_read,
            notes=['All selected decision ticks and contract calculations are exported without downsampling.',
              'Prices join exact saved mark IDs, with reported and effective timestamps retained; no time interpolation.',
              'Stored past holdings seed each decision; the original pinned allocation function is re-evaluated, not the execution engine.',
              'Target equality establishes implementation reproducibility, not executable same-time carry or economic justification.',
              'Yield/future/spot/maturity change attribution uses a stated sequential order; attribution is not unique.',
              'Daily-scaled lease is an annualized-rate diagnostic divided by 365, not a prediction of next-day realised return.',
              'Fees since previous valuation belong to (previous_tick,tick]; new targets are submitted at tick.',
              'Raw prices are USDT-parity spot and USD futures proxy as in the original run; no new FX conversion.'])
        write_json(out/'summary.json',report)
        write_view(out,rows,report,engine.p)
        write_json(out/'status.json',{'status':report['status']})
        print(report['status']);print(f'Output directory: {out}');print(f'Decisions: {len(rows):,}; contract calculations: {calculation_count:,}')
        return 2 if failed else 0
    finally: db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id',required=True)
    p.add_argument('--day',help='UTC day YYYY-MM-DD; default first complete day')
    p.add_argument('--days',type=int,default=1)
    p.add_argument('--output',required=True,help='New local output directory')
    p.add_argument('--repo',default=str(Path(__file__).resolve().parents[1]),help='Local Git checkout containing original engine history')
    p.add_argument('--max-read-mib',type=int,default=2048)
    args=p.parse_args()
    try: return run(args)
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as exc:
        print(f'Diagnostic not certified: {exc}',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
