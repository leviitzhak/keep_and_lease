import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from research.post_decision_value.accounting import Goal, Instrument, Ledger
from research.post_decision_value.analytical import analytical
from research.post_decision_value.analytical_study import Budget, PRESETS, check_fills, inventory, plan, rank_presets, replay
from research.post_decision_value.data import utc_ms
from research.post_decision_value.engine import CandidateGenerator, Instruction, ObservableState, Order


class AnalyticalStudyTests(unittest.TestCase):
    def state(self, n=2):
        ins = {chr(65+i): Instrument(chr(65+i), 999999999) for i in range(n)}
        obs = ObservableState(10, Ledger({'BTC':1., 'USD':100000.}))
        obs.market = {s: dict(price=100000+i*2000, index=100000, received=1) for i,s in enumerate(ins)}
        return obs, Goal({'BTC':1., 'USD':100000.},1000,999999999), ins

    def test_candidate_counts_and_budget_bias(self):
        obs, goal, ins = self.state()
        accepted, audit = CandidateGenerator(budget=96).generate(obs,goal,ins)
        self.assertEqual(len(audit),50)
        self.assertEqual(sum(len(x['instruction']['orders'])==2 for x in audit),24)
        obs,goal,ins = self.state(3)
        _,audit = CandidateGenerator(budget=96).generate(obs,goal,ins)
        self.assertEqual(len(audit),96)
        self.assertEqual(sum(len(x['instruction']['orders'])==2 for x in audit),72)
        self.assertEqual(sum(len(x['instruction']['orders'])==1 for x in audit),22)

    def test_pending_orders_suppress_creates(self):
        obs,goal,ins = self.state()
        obs.uncertain={'old':[Order('old','A',.005,100000)]}
        _,audit=CandidateGenerator(budget=96).generate(obs,goal,ins)
        self.assertEqual(len(audit),4)
        self.assertEqual({r['instruction']['kind'] for r in audit},{'wait','cancel','amend','emergency'})

    def test_analytical_positive_basket_and_zero_ties(self):
        obs,goal,ins=self.state()
        pair=Instruction('create',(Order('a','A',.01,100000),Order('b','B',-.0099,102000)))
        self.assertEqual(analytical(obs,[Instruction(),pair],goal,ins),1)
        self.assertEqual(analytical(obs,[Instruction(),Instruction('cancel')],goal,ins),0)

    def test_selection_rejects_failure_even_if_profitable(self):
        rows=[dict(preset=p['name'],outcome=dict(done=True,failed=i==0,utility=10 if i==0 else .01)) for i,p in enumerate(PRESETS)]
        ranked=rank_presets(rows,PRESETS)
        self.assertEqual(ranked[0]['preset'],'small')
        self.assertFalse(ranked[-1]['eligible'])

    def test_fixed_split_dates_and_decision_bound(self):
        p=plan();s=p['splits']
        self.assertEqual([len(s[k]) for k in ('calibration','validation','test')],[54,18,18])
        self.assertEqual(s['test'][0],'2026-08-17')
        self.assertEqual(s['calibration']+s['validation']+s['test'],p['dates'])
        self.assertEqual(len(set(p['dates'])),90)
        worst=4*2*54*24+2*2*18*24+4*2*18*24+2*90*24
        self.assertEqual(worst,19872)
        self.assertLessEqual(worst,p['max_decisions'])

    def fixture(self, root):
        config=plan(); config['dates']=config['dates'][:2]
        start=utc_ms(config['dates'][0]+'T00:00:00Z'); expiry=start+365*86400000
        (root/'inputs').mkdir()
        (root/'specification.json').write_text(json.dumps(dict(symbols=['A','B'],expiry=[expiry,expiry+86400000])))
        seeds={s:dict(timestamp=start-5000,instrument_name=s,price=p,index_price=100000,amount=10000,direction='buy',trade_id=str(i+1),trade_seq=1) for i,(s,p) in enumerate([('A',100000),('B',102000)])}
        (root/'seeds.json').write_text(json.dumps(seeds))
        coverage=[];receipts=[]
        for d,day in enumerate(config['dates']):
            for i,s in enumerate(['A','B']):
                price=(99000-2000*d) if s=='A' else (104000+2000*d)
                row=dict(timestamp=start+d*86400000+60000,instrument_name=s,price=price,index_price=100000,amount=10000,direction='sell' if s=='A' else 'buy',trade_id=str(10+d*2+i),trade_seq=2+d)
                path=root/'inputs'/f'{day}-{s}.jsonl.gz'
                raw=gzip.compress((json.dumps(row)+'\n').encode());path.write_bytes(raw);digest=hashlib.sha256(raw).hexdigest()
                coverage.append(dict(path=path.name,sha256=digest,raw_rows=1,ordinary_rows=1))
                receipts.append(dict(key=f'fixture/{digest}',sha256=digest,bytes=len(raw)))
        (root/'input_coverage.json').write_text(json.dumps(coverage))
        (root/'source_receipts.json').write_text(json.dumps(receipts))
        return config

    def test_daily_chunks_preserve_positions_and_resume_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=self.fixture(root);budget=Budget(config)
            ins,manifest,seeds=inventory(root,config,budget)
            result=replay(root,root/'out',{'fixture':1},config,ins,manifest,seeds,budget,'test',config['dates'],PRESETS[0],11)
            daily=json.loads((root/'out'/'episodes'/result['name']/'daily.json').read_text())
            self.assertGreater(daily[0]['fills'],0)
            self.assertGreater(daily[1]['fills'],daily[0]['fills'])
            fills=json.loads(gzip.decompress((root/'out'/'episodes'/result['name']/'fills.json.gz').read_bytes()))
            ledger=Ledger(config['initial'].copy())
            for f in fills:ledger.fill(ins[f['symbol']],f['quantity'],f['price'])
            self.assertEqual(result['outcome']['holdings'],ledger.holdings(ins))
            reset_ledger=Ledger(config['initial'].copy())
            for f in fills:
                if f['time']>=utc_ms(config['dates'][1]+'T00:00:00Z'):
                    reset_ledger.fill(ins[f['symbol']],f['quantity'],f['price'])
            self.assertNotEqual(result['outcome']['holdings'],reset_ledger.holdings(ins))
            self.assertEqual(result['decisions'],48)
            self.assertEqual(result['outcome']['holding_status'],'contractual/projected')
            resumed=replay(root,root/'out',{'fixture':1},config,ins,manifest,seeds,Budget(config),'test',config['dates'],PRESETS[0],11)
            self.assertEqual(result,resumed)
            path=root/'out'/'episodes'/result['name']/'daily.json';path.write_text('[]')
            with self.assertRaisesRegex(ValueError,'artifact hash'):
                replay(root,root/'out',{'fixture':1},config,ins,manifest,seeds,Budget(config),'test',config['dates'],PRESETS[0],11)

    def test_strict_through_audit_rejects_touch(self):
        from research.post_decision_value.engine import Trade
        trade=Trade(1,'A',100000,10000,'sell','x',100000)
        fill=dict(symbol='A',source_id='x',time=1,source_price=100000,price=100000,quantity=.001)
        with self.assertRaisesRegex(ValueError,'strict-through'):
            check_fills([fill],{('A','x'):trade},{'A':Instrument('A',9999)},.1)


if __name__=='__main__':unittest.main()
