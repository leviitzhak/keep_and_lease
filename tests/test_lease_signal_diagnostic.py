"""Synthetic source, arithmetic, selection, and exact-mark reconstruction checks."""
import ast
import base64
import copy
import datetime as dt
import gzip
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import diagnose_lease_signal as d
import backtest_silver_lease_strategy as strategy
import silver_strategy_gui as gui


class FixedRates:
    def __init__(self, rate=.04): self.rate=rate
    def at(self,tick,maturity):
        return self.rate,[{'series':'fixture','tenor_days':91,'yield_fraction':self.rate,'interpolation_weight':1}]


def setup_signal(**overrides):
    t=d.us('2026-06-07T00:00:00Z')
    payload=dict(commodity_parameters={'btc':dict(futures_contract_type='regular',enable_short_book=False,
        slv_expense=0,positive_entry_rate=0,positive_full_rate=15,max_futures_treasury_fraction=100,
        min_days=10,long_contract_selection='weighted_lease_rate',roll_only_if_better=False,
        max_quote_age_seconds=60)},execution_interval_seconds=.5)
    payload['commodity_parameters']['btc'].update(overrides)
    cp={'state':dict(previous_tick=t-500000,previous_allocation=.25),'account':{'fees':0}}
    m={'source_manifest':{'futures':{'A':{'expiry':d.iso(t+12*d.DAY_US)},'B':{'expiry':d.iso(t+30*d.DAY_US)}}}}
    marks={}
    for s,price in [('SPOT',100),('A',99.8),('B',100.2)]:
        marks[(s,s+'0')]=dict(price=str(price),raw_us=t,btc=1,executable=True,source='fixture',source_sequence=1)
    engine=d.Signal(strategy,gui,FixedRates(),payload,cp,m,marks.__getitem__)
    row=dict(us=t,nav_usd=1000,cash_usd=100,units={'SPOT':9,'A':.3,'B':.7},
        mark_ids={s:s+'0' for s in ('SPOT','A','B')},mark_us={s:t for s in ('SPOT','A','B')},
        reported_mark_us={s:t for s in ('SPOT','A','B')},targets=None,fees_usd=0)
    return engine,row,marks,payload,cp,m


def expected_targets(engine,row):
    t=row['us'];marks={s:engine.lookup((s,str(i))) for s,i in row['mark_ids'].items()}
    spot=float(marks['SPOT']['price']);nav=row['nav_usd'];candidates=[]
    for s,expiry in engine.expiries.items():
        if s not in marks: continue
        mark=marks[s];days=(expiry-t)/d.DAY_US
        if not mark['executable'] or days<=0 or t-row['mark_us'][s]>engine.p.max_quote_age_seconds*1e6: continue
        r,_=engine.rates.at(t,days);f=float(mark['price']);premium=f/spot-1
        candidates.append(dict(symbol=s,days=days,future=f,spot=spot,premium=premium,rate=r,lease=r-premium*365/days,volume=mark['btc']))
    prev={'base_longs':{s:q*float(marks[s]['price'])/nav for s,q in row['units'].items() if s!='SPOT' and q>0},'shorts':{}}
    if engine.previous_allocation is not None:prev['base_treasury']=engine.previous_allocation
    des=strategy.positions_for_day(candidates,engine.p,prev,elapsed_days=(t-engine.previous_t)/d.DAY_US)
    if des is None or t-row['mark_us']['SPOT']>engine.p.max_quote_age_seconds*1e6:return None
    return {**{s:w*nav/float(marks[s]['price']) for s,w in des['base_longs'].items()},'SPOT':des['slv']*nav/spot}


class SelectionTests(unittest.TestCase):
    def test_instrumented_return_does_not_change_original_function(self):
        traced=d.traced_selector(strategy)
        p=gui.parameters({'enable_short_book':False})
        contracts=[dict(symbol=s,days=days,lease=lease,volume=vol,rate=.04,premium=.001,future=100,spot=100)
                   for s,days,lease,vol in [('A',12,.03,1),('B',100,.05,2),('C',9,.09,3)]]
        for mode in ('shortest_maturity','highest_lease_rate','weighted_lease_rate'):
            for allocation in ('fixed','gradual'):
                for smoothing in (0,.01):
                    pp=replace(p,long_contract_selection=mode,long_futures_entry_mode=allocation,long_allocation_half_life_days=smoothing)
                    for cs in (contracts,[],[dict(c,lease=-.1) for c in contracts]):
                        before=copy.deepcopy(cs);prev={'base_longs':{'A':.3},'base_treasury':.3}
                        real=strategy.positions_for_day(copy.deepcopy(cs),pp,prev,elapsed_days=.5/86400)
                        got,trace=traced(copy.deepcopy(cs),pp,prev,elapsed_days=.5/86400)
                        self.assertEqual(got,real);self.assertEqual(cs,before)
                        if got:self.assertIn('positive_strength',trace)

    def test_every_target_and_formula_preserved(self):
        engine,row,marks,*_=setup_signal()
        row['targets']=expected_targets(engine,row);original=copy.deepcopy(row)
        obs,details=engine.step(row)
        self.assertTrue(obs['target_matches_saved']);self.assertEqual(row,original)
        chosen=next(x for x in details if x['selected_allocation_driver'])
        self.assertEqual(obs['signal_contract'],chosen['symbol'])
        for x in details:
            self.assertAlmostEqual(x['lease_fraction'],x['usd_rate_fraction']-(x['future_price']/x['spot_price']-1)*365/x['maturity_days'])
            self.assertIn('score_calculation',x)
        self.assertAlmostEqual(obs['target_futures_weight_pct'],100*chosen['lease_fraction']/.15)
        self.assertNotEqual(obs['diagnostic_weighted_lease_pct'],obs['signal_lease_pct'])

    def test_report_detects_changed_target(self):
        e,r,*_=setup_signal();r['targets']=expected_targets(e,r);r['targets']['SPOT']+=.01
        obs,_=e.step(r);self.assertFalse(obs['target_matches_saved']);self.assertGreater(obs['max_target_quantity_error_btc'],.009)

    def test_smoothing_uses_prior_target_not_current_inventory(self):
        e,r,*_=setup_signal(long_allocation_half_life_days=.001)
        r['targets']=expected_targets(e,r);obs,_=e.step(r)
        self.assertTrue(obs['target_matches_saved'])
        self.assertAlmostEqual(obs['target_futures_weight_pct'],25+(1-2**(-.5/86400/.001))*(obs['raw_futures_weight_pct']-25))
        self.assertGreater(abs(obs['raw_futures_weight_pct']-obs['target_futures_weight_pct']),1)

    def test_stale_curve_keeps_previous_allocation_state(self):
        e,r,*_=setup_signal();r['us']+=61_000_000;r['targets']=None
        obs,details=e.step(r);self.assertEqual(obs['allocation_gate'],'no_eligible_curve');self.assertTrue(obs['target_matches_saved'])
        self.assertEqual(e.previous_allocation,.25);self.assertIsNone(obs['target_futures_weight_pct'])
        self.assertTrue(all(x['eligibility']=='stale_future' for x in details))

    def test_stale_spot_and_excluded_futures_do_not_create_orders(self):
        e,r,marks,*_=setup_signal()
        r['mark_us']['SPOT']-=61_000_000;r['reported_mark_us']['SPOT']-=61_000_000;marks['SPOT','SPOT0']['raw_us']-=61_000_000
        obs,_=e.step(r);self.assertEqual(obs['allocation_gate'],'stale_spot');self.assertTrue(obs['target_matches_saved'])
        e,r,marks,*_=setup_signal()
        for s in ('A','B'):marks[s,s+'0']['executable']=False
        obs,details=e.step(r);self.assertTrue(obs['target_matches_saved']);self.assertTrue(all(x['eligibility']=='excluded_trade_type' for x in details))

    def test_fixed_allocation_does_not_follow_rate_level(self):
        e,r,*_=setup_signal(long_futures_entry_mode='fixed')
        r['targets']=expected_targets(e,r);obs,_=e.step(r)
        self.assertEqual(obs['target_futures_weight_pct'],100);self.assertTrue(obs['target_matches_saved'])

    def test_new_spot_mark_can_move_signal_with_unchanged_future(self):
        e,r,marks,*_=setup_signal();r['targets']=expected_targets(e,r);before,_=e.step(r)
        r=copy.deepcopy(r);r['us']+=500000
        marks['SPOT','new']=dict(marks['SPOT','SPOT0'],price='100.1',raw_us=r['us'])
        r['mark_ids']['SPOT']='new';r['mark_us']['SPOT']=r['us'];r['reported_mark_us']['SPOT']=r['us']
        r['targets']=expected_targets(e,r);after,details=e.step(r)
        self.assertTrue(after['target_matches_saved']);self.assertTrue(after['spot_mark_changed'])
        self.assertFalse(after['driver_future_mark_changed']);self.assertGreater(after['spot_move_bps'],0)
        self.assertGreater(after['target_futures_weight_pct'],before['target_futures_weight_pct'])


class InputsTests(unittest.TestCase):
    def test_rate_details_are_causal_and_maturity_interpolated(self):
        with tempfile.TemporaryDirectory() as td:
            for tenor,name in strategy.TENORS:
                Path(td,name+'.csv').write_text('observation_date,'+name+'\n2026-06-05,4\n2026-06-07,20\n')
            rates=d.Rates(strategy,td)
            rate,parts=rates.at(d.us('2026-06-07T22:00:00Z'),120)
            self.assertAlmostEqual(rate,.04);self.assertEqual(len(parts),2)
            self.assertTrue(all(p['observation']=='2026-06-05' for p in parts))
            self.assertAlmostEqual(sum(p['interpolation_weight'] for p in parts),1)
            self.assertAlmostEqual(rates.at(d.us('2026-06-08T00:00:00Z'),120)[0],.2)

    def test_change_decomposition_sums_exactly(self):
        old=dict(future_price=100.2,spot_price=100,maturity_days=12,usd_rate_fraction=.04)
        new=dict(future_price=100.1,spot_price=100.4,maturity_days=11.99,usd_rate_fraction=.045)
        for r in (old,new):r['lease_fraction']=r['usd_rate_fraction']-(r['future_price']/r['spot_price']-1)*365/r['maturity_days']
        parts=d.lease_parts(old,new);self.assertLess(abs(parts['change_attribution_error_bps']),1e-10)

    def test_wrong_spot_identity_is_rejected(self):
        e,r,*_=setup_signal();r['reported_mark_us']['SPOT']+=1
        with self.assertRaisesRegex(ValueError,'Spot mark'):e.step(r)

    def test_audit_input_stage_preserves_original_rows_and_exact_references(self):
        e,r,marks,payload,cp,m=setup_signal()
        cp['account']['marks']={s:dict(identifier=s+'0',us=r['us']-1,reported_us=r['us']-1,price=float(x['price']),btc=1,executable=True,sequence=1) for (s,i),x in marks.items()}
        r['targets']=expected_targets(e,r)
        class I:
            def chunk(self,entry):yield r
        entry=dict(start=d.iso(r['us']),end=d.iso(r['us']))
        with tempfile.TemporaryDirectory() as td:
            db=d.initialize_db(Path(td)/'db',cp)
            self.assertEqual(d.stage_valuations(db,I(),[entry],cp,r['us']+1),1)
            self.assertEqual(json.loads(db.execute('SELECT row FROM valuations').fetchone()[0]),r)
            self.assertEqual(db.execute('SELECT count(*) FROM refs').fetchone()[0],3)
            db.close()

    def test_unresolved_day_is_not_silently_substituted(self):
        if importlib.util.find_spec('pyarrow') is None:self.skipTest('pyarrow not installed; real Parquet check runs in CI')
        e,r,marks,payload,cp,m=setup_signal();cp['account']['marks']={}
        with tempfile.TemporaryDirectory() as td:
            db=d.initialize_db(Path(td)/'db',cp);db.execute('INSERT INTO refs VALUES(?,?,?,?)',('SPOT','x',r['us'],r['us']))
            m['source_manifest']['start']='2026-06-06T00:00:00Z';m['partitions']=[]
            with self.assertRaisesRegex(ValueError,'absent'):d.resolve_marks(db,m,'',None,td)
            db.close()

    def test_matching_real_parquet_ids_and_decimal_prices(self):
        if importlib.util.find_spec('pyarrow') is None:self.skipTest('pyarrow not installed; real Parquet check runs in CI')
        import pyarrow as pa
        import pyarrow.parquet as pq
        e,r,marks,payload,cp,m=setup_signal();cp['account']['marks']={}
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);db=d.initialize_db(td/'db',cp);t=r['us']
            db.execute('INSERT INTO refs VALUES(?,?,?,?)',('SPOT','wanted',t,t))
            source=td/'source.parquet'
            pq.write_table(pa.table({'timestamp_us':[t,t+1],'symbol':['SPOT','SPOT'],'trade_id':['wanted','ignored'],
                'price':[Decimal('100.123456789012'),Decimal('101')],'native_quantity':[Decimal('1'),Decimal('1')],
                'quantity_currency':['BTC','BTC'],'flags':[0,0],'source_sequence':[1,2]}),source)
            class I:
                def fetch(self,uri,destination,**kw):
                    self_outer.assertEqual(kw['expected'],d.sha(source.read_bytes()));Path(destination).parent.mkdir(exist_ok=True,parents=True)
                    Path(destination).write_bytes(source.read_bytes());return Path(destination)
            self_outer=self
            m['source_manifest']['start']='2026-06-07T00:00:00Z'
            m['partitions']=[dict(path='venue=binance/market=spot/date=2026-06-07/part-000.parquet',first_us=t,last_us=t+1,sha256=d.sha(source.read_bytes()))]
            d.resolve_marks(db,m,d.MARKET+'btc/trades/v1/'+'a'*64,I(),td)
            found=db.execute('SELECT price,raw_us FROM marks').fetchone();self.assertEqual(found,('100.123456789012',t));db.close()

    def test_html_retains_all_rows_not_only_minute_samples(self):
        e,r,*_=setup_signal();r['targets']=expected_targets(e,r);obs,_=e.step(r)
        with tempfile.TemporaryDirectory() as td:
            d.write_view(td,[obs],{'status':'fixture','engine_commit':'a'*40},e.p)
            text=Path(td,'evolution.html').read_text();encoded=text.split("atob('")[1].split("')")[0]
            data=json.loads(gzip.decompress(base64.b64decode(encoded)))
            self.assertEqual(len(data['rows']),1);self.assertEqual(data['rows'][0][1],obs['signal_lease_pct'])
            self.assertNotIn('__DATA__',text)

    def test_full_cli_export_uses_original_state_and_preserves_all_day_rows(self):
        if importlib.util.find_spec('pyarrow') is None:self.skipTest('pyarrow not installed; full pipeline check runs in CI')
        from types import SimpleNamespace
        import replay_checkpoints as cpmod
        e,r,marks,payload,cp,m=setup_signal(max_quote_age_seconds=86400)
        lo=r['us'];seed=lo-d.HOUR_US;payload['execution_interval_seconds']=3600
        cp['state']['previous_tick']=seed
        cp['account']['marks']={s:dict(identifier=s+'0',us=seed,reported_us=seed,price=float(x['price']),btc=1,executable=True,sequence=1) for (s,i),x in marks.items()}
        for v in marks.values():v['raw_us']=seed
        m['source_manifest']['start']='2026-06-06T00:00:00Z';m['partitions']=[]
        market_bytes=json.dumps(m).encode()
        cp['identity']=cpmod.fingerprint(payload,market_bytes,ROOT)
        engine=d.Signal(strategy,gui,d.Rates(strategy,ROOT),payload,cp,m,marks.__getitem__)
        rows=[]
        for h in range(24):
            row=copy.deepcopy(r);row['us']=lo+h*d.HOUR_US
            row['mark_us']={s:seed for s in row['mark_ids']};row['reported_mark_us']=dict(row['mark_us'])
            row['targets']=expected_targets(engine,row);engine.step(row);rows.append(row)
        result=dict(result_kind='btc_trade_replay',summary=dict(start='2026-06-06T00:00:00Z',end='2026-06-09T00:00:00Z'),parameters=payload,
            trade_replay=dict(interval_seconds=3600,dataset_uri=d.MARKET+'btc/trades/v1/'+'a'*64,manifest_sha256=d.sha(market_bytes)))
        audit=dict(provenance=dict(engine_commit='a'*40,parameters=payload),datasets={'btc_trade_valuations':{'chunks':[dict(start=d.iso(lo),end=d.iso(lo+23*d.HOUR_US))]}})
        class Inputs:
            def __init__(self,*args):
                self.run=SimpleNamespace(root='gs://keep-and-lease-results/jobs/'+'b'*32+'/',bytes_read=0,receipts={})
                self.bytes_read=0;self.receipts={}
            def run_bytes(self,name):return gzip.compress(json.dumps(result).encode()) if name=='result.json.gz' else json.dumps(audit).encode()
            def fetch(self,uri,dest,**kw):
                data=cpmod.encode(cp) if '/checkpoints/' in uri else market_bytes
                if kw.get('expected'):self_outer.assertEqual(kw['expected'],d.sha(data))
                Path(dest).parent.mkdir(parents=True,exist_ok=True);Path(dest).write_bytes(data);return Path(dest)
            def chunk(self,entry):yield from rows
        def snapshot(repo,commit,out):
            out.mkdir();result={}
            for name in d.SOURCE_FILES+d.RATE_FILES:
                data=(ROOT/name).read_bytes();(out/name).write_bytes(data);result[name]=d.sha(data)
            return result
        self_outer=self
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'report'
            args=SimpleNamespace(output=str(out),run_id='b'*32,day='2026-06-07',days=1,max_read_mib=2048,repo=ROOT)
            with patch.object(d,'CloudInputs',Inputs),patch.object(d,'snapshot_engine',snapshot):
                self.assertEqual(d.run(args),0)
            report=json.loads((out/'summary.json').read_text());self.assertEqual(report['statistics']['decisions'],24)
            self.assertTrue(report['checkpoint_identity_verified']);self.assertEqual(report['statistics']['target_mismatches'],0)
            import csv
            with gzip.open(out/'decisions.csv.gz','rt') as stream:exported=list(csv.DictReader(stream))
            self.assertEqual(len(exported),24)
            with gzip.open(out/'lease-calculations.csv.gz','rt') as stream:calcs=list(csv.DictReader(stream))
            self.assertEqual(len(calcs),48);self.assertTrue(all('rate_components' in x for x in calcs))

    def test_output_must_be_new(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'never replaced'):
                d.run(SimpleNamespace(output=td))


if __name__=='__main__':unittest.main()
