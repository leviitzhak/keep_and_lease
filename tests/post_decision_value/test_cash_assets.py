from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import json
import random
import tempfile
import unittest

import numpy as np
import torch

from research.post_decision_value.accounting import Instrument, Ledger, Goal, Position
from research.post_decision_value.action_search import ActionDomain, SparseGridDomain
from research.post_decision_value.cash_data import load_cash_bundle, attach_cash_blocks
from research.post_decision_value.checkpoint import DirectoryCheckpoints, save_engine, restore_engine
from research.post_decision_value.engine import Engine, Trade, Order, Instruction, Delays, post_decision, admissible
from research.post_decision_value.model import ValueNetwork, features, action_features, labels, fit, save_model, load_model


def instruments():
    return {'S':Instrument('S',10**15,payoff='spot',source_payoff='spot',tick=1,lot=.001,fee_bps=0),
            'P':Instrument('P',10**15,payoff='proxy',source_payoff='proxy',tick=.01,lot=1,fee_bps=0,underlying_per_unit=.01),
            'T':Instrument('T',1000,payoff='treasury',source_payoff='treasury',tick=.01,lot=1,fee_bps=0,cashflows=((900,5.),(1000,100.))),
            'F':Instrument('F',1100,tick=1,lot=.001,fee_bps=0)}


def replay(*,proxy=False,report=0):
    ins=instruments();ledger=Ledger({'BTC':1.,'USD':100000.})
    if proxy:ledger.balances['BTC']=.99;ledger.positions['P']=Position(1.,1000.)
    goal=Goal({'BTC':1.,'USD':100000.},1300,1300,mode='gated_max')
    e=Engine(ins,ledger,goal,11,Delays(0,0,0,report,0,0),participation=1)
    e.seed_market([Trade(0,s,p,100000,'buy','seed-'+s,100000.,i.source_payoff) for s,i in ins.items()
                   for p in [dict(S=100000.,P=1000.,T=100.,F=104000.)[s]]],1)
    return e


def carry(proxy=False):
    e=replay(proxy=proxy);s='P' if proxy else 'S';q=-1. if proxy else -.01
    action=Instruction('create',(Order('spot',s,q,1000. if proxy else 100000.,'carry'),
                                 Order('future','F',.01,104000.,'carry'),Order('bill','T',10.,100.)))
    e.submit(action)
    e.add_tape([Trade(10,s,1001. if proxy else 100001.,10,'buy','sell-btc',100000.,e.instruments[s].source_payoff),
                Trade(20,'F',103999.,100000,'sell','buy-future',100000.),
                Trade(30,'T',99.,100,'sell','buy-bill',100000.,'treasury')])
    # Entirely synthetic observed settlement/bridge fixture, never historical evidence.
    e._event(1100,1,'settlement',('F',120000.,120000.,True))
    e.advance(1300)
    return e


class CashAccountingTests(unittest.TestCase):
    def test_cash_purchases_debit_full_cost_and_no_double_count(self):
        ins=instruments();l=Ledger({'BTC':1.,'USD':100000.})
        l.fill(ins['S'],.01,100000.);self.assertAlmostEqual(l.balances['USD'],99000.)
        self.assertNotIn('S',l.positions);self.assertAlmostEqual(l.holdings(ins)['BTC'],1.01)
        l.fill(ins['P'],1,1000.);l.fill(ins['T'],10,100.)
        self.assertAlmostEqual(l.holdings(ins)['BTC'],1.02)
        self.assertAlmostEqual(l.holdings(ins)['USD'],98050.)
        self.assertAlmostEqual(l.marked_wealth(ins,{'P':1000,'T':100},100000)['USD'],200000.)
        self.assertEqual([(r['date'],r['amount']) for r in l.schedule(ins)],[(900,50.),(1000,1000.)])

    def test_cash_assets_cannot_be_short_or_bought_with_unsettled_claims(self):
        ins=instruments();l=Ledger({'BTC':.01,'USD':100.});l.pledge('BTC',.01);l.pledge('USD',100.)
        for symbol,q,p in [('S',-.001,100000),('P',-1,1000),('T',-1,100),('T',1,100)]:
            with self.assertRaises(ValueError):l.fill(ins[symbol],q,p)
        l=Ledger({'BTC':1.,'USD':1000.});l.fill(ins['T'],10,100.)
        self.assertEqual(l.balances['USD'],0.)
        with self.assertRaises(ValueError):l.fill(ins['P'],1,1000.)
        l.fill(ins['F'],.001,104000.)
        self.assertLess(l.funding_headroom(ins,100000.,1300),0.)

    def test_coupons_follow_owned_units_no_duplicate_principal(self):
        ins=instruments();l=Ledger({'BTC':1.,'USD':100000.});l.fill(ins['T'],10,100.)
        l.fill(ins['T'],-4,101.)
        before=l.holdings(ins)['USD'];self.assertEqual(l.pay_asset(ins['T'],900),30.)
        self.assertEqual(l.holdings(ins)['USD'],before);self.assertEqual(l.pay_asset(ins['T'],900),0.)
        l.fill(ins['T'],2,100.)  # Ex-coupon buyers cannot receive past cash.
        self.assertEqual(l.pay_asset(ins['T'],1000),800.)
        self.assertNotIn('T',l.positions);self.assertEqual(l.schedule(ins),[])
        self.assertEqual(l.pay_asset(ins['T'],1000),0.)

    def test_spot_and_proxy_carry_expiry_conservation(self):
        for proxy in (False,True):
            e=carry(proxy);o=e.outcome()
            self.assertTrue(o['done']);self.assertFalse(o['failed']);self.assertEqual(o['fills'],3)
            self.assertAlmostEqual(o['balances']['BTC'],1.)
            self.assertAlmostEqual(o['balances']['USD'],100010.)
            self.assertAlmostEqual(o['utility'],.0001)
            self.assertEqual(o['holding_status'],'contractual/projected')
            self.assertEqual(len(o['projected_receipts']),2)
            self.assertFalse(e.hidden.ledger.positions)

    def test_surplus_carry_can_be_allocated_to_extra_btc(self):
        from research.post_decision_value.cash_smoke import carry_replay
        result=carry_replay(False,True);o=result['outcome']
        self.assertTrue(o['done']);self.assertFalse(o['failed'])
        self.assertAlmostEqual(o['balances']['BTC'],1.000096)
        self.assertAlmostEqual(o['balances']['USD'],100000.016)
        self.assertAlmostEqual(o['utility'],.000096)

    def test_delayed_payment_and_resume_preserve_ownership(self):
        e=replay(report=100)
        e.submit(Instruction('create',(Order('t','T',10,100),)))
        e.add_tape([Trade(20,'T',99,100,'sell','fill',100000.,'treasury')]);e.advance(950)
        self.assertEqual(e.hidden.ledger.balances['USD'],99050.)
        self.assertEqual(e.observe().ledger.balances['USD'],99000.)
        with tempfile.TemporaryDirectory() as d:
            store=DirectoryCheckpoints(d);save_engine(store,950,e,{'fixture':'cash'})
            restored=restore_engine(store,{'fixture':'cash'})
            e.advance(1300);restored.advance(1300)
            self.assertEqual(e.outcome(),restored.outcome())
            self.assertEqual(e.observable.ledger,e.hidden.ledger)

    def test_coupon_is_ex_coupon_and_expired_orders_report_cancellation(self):
        e=replay(report=100);e.advance(850)
        e.submit(Instruction('create',(Order('t','T',1,100),)))
        e.add_tape([Trade(900,'T',99,10,'sell','same-coupon',100000.,'treasury')])
        e.advance(950);self.assertEqual(e.hidden.ledger.balances['USD'],99900.)
        e.advance(1000);self.assertEqual(e.hidden.ledger.balances['USD'],100000.)
        e.advance(1200);self.assertEqual(e.observable.ledger,e.hidden.ledger)
        e=replay(report=100);e.submit(Instruction('create',(Order('unfilled','T',1,99),)));e.advance(1150)
        self.assertNotIn('unfilled',e.observable.uncertain)

    def test_pending_sales_reserve_native_inventory_and_are_not_hidden_fills(self):
        e=replay(proxy=True,report=100);obs=e.observe()
        a=Instruction('create',(Order('p','P',-1,1000),))
        x=post_decision(obs,a,e.instruments)
        self.assertEqual(x.reserved_assets,{'P':1.});self.assertEqual(x.ledger,obs.ledger)
        self.assertEqual(obs.pending,[])
        duplicate=Instruction('create',(Order('p2','P',-1,1000),))
        self.assertFalse(admissible(x,duplicate,e.goal,e.instruments)[0])
        e.submit(a);before=features(e.observe(),e.goal,e.instruments)
        e.add_tape([Trade(10,'P',1001,2,'buy','hidden-fill',100000.,'proxy')])
        e.advance(10);after=e.observe();after.time=obs.time;after.history=obs.history;after.market=obs.market
        self.assertEqual(before,features(after,e.goal,e.instruments))

    def test_native_cash_grid_and_listing_guard(self):
        e=replay();d=ActionDomain(min_btc=.001,max_btc=.02,min_usd=100,max_usd=2000)
        self.assertEqual(d.quantity_lots(e.instruments['S'],100000),(1,20))
        self.assertEqual(d.quantity_lots(e.instruments['P'],1000),(1,2))
        self.assertEqual(d.quantity_lots(e.instruments['T'],100),(1,20))
        grid=SparseGridDomain().prepare(random.Random(7),e.observe(),e.goal,e.instruments)
        self.assertEqual(set(grid.prices),set(e.instruments))
        ins=Instrument('later',2000,payoff='treasury',source_payoff='treasury',cashflows=((2000,100.),),listed_at=500)
        self.assertFalse(ins.tradable(499,2000));self.assertTrue(ins.tradable(500,2000))


class CashObjectiveLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)

    def test_gate_boundary_and_neutral_futures_pair(self):
        goal=Goal({'BTC':1.,'USD':100000.},1,2,mode='gated_max')
        for b,u,score in [(1.05,99999.9,-.000001),(1.05,100000.,.05),(1.,101000.,.01),(.99,110000.,-.01),(1.02,103000.,.03)]:
            self.assertAlmostEqual(goal.outcome({'BTC':b,'USD':u})['utility'],score)
        ins={'A':Instrument('A',1,fee_bps=0),'B':Instrument('B',2,fee_bps=0)}
        l=Ledger(goal.initial.copy());l.fill(ins['A'],.01,100000);l.fill(ins['B'],-.01,105000)
        h=l.holdings(ins);self.assertAlmostEqual(h['BTC'],1.)
        self.assertAlmostEqual(goal.outcome(h)['utility'],.0005)
        self.assertEqual(Goal(goal.initial,1,2).outcome(h)['utility'],0.)

    def test_expected_utility_is_not_utility_of_expected_holdings(self):
        goal=Goal({'BTC':1.,'USD':100000.},1,2,mode='gated_max')
        outcomes=[goal.outcome({'BTC':1.1,'USD':99000}),goal.outcome({'BTC':1.1,'USD':101000})]
        expected=sum(o['utility'] for o in outcomes)/2
        self.assertAlmostEqual(expected,.045)
        self.assertAlmostEqual(goal.outcome({'BTC':1.1,'USD':100000})['utility'],.1)

    def test_v2_features_training_checkpoint_and_objective_separation(self):
        e=replay();choices=[Instruction(),Instruction('create',(Order('t','T',10,100),)),
                            Instruction('create',(Order('t','T',5,100),))]
        records=[]
        for a in choices:
            x=replay();f=action_features(x.observe(),a,x.goal,x.instruments);x.submit(a)
            x.add_tape([Trade(20,'T',99,100,'sell','fill',100000.,'treasury')]);x.advance(1300)
            records.append(dict(features=f,outcome=x.outcome(),continuation='wait-after-initial-v2'))
        self.assertEqual(len(f['global_']),35);self.assertTrue(all(len(i)==28 for i in f['items']))
        self.assertNotEqual(records[1]['features'],records[2]['features'])
        y,_=labels(records);self.assertAlmostEqual(float(y[1,0]),.0005)
        torch.manual_seed(3);model=ValueNetwork(feature_version=2)
        self.assertEqual(sum(p.numel() for p in model.parameters()),88645)
        opt,rng,info=fit(model,records,updates=30,seed=2)
        self.assertLess(info['last_loss'],info['first_loss'])
        with tempfile.TemporaryDirectory() as d:
            save_model(d+'/m.pt',model,opt,rng,{'schema':2});restored,opt2,rng2=load_model(d+'/m.pt',{'schema':2})
            np.testing.assert_array_equal(model.predict([f])['objective'],restored.predict([f])['objective'])
            fit(model,records,updates=2,optimizer=opt,rng=rng,normalize=False)
            fit(restored,records,updates=2,optimizer=opt2,rng=rng2,normalize=False)
            for k,v in model.state_dict().items():self.assertTrue(torch.equal(v,restored.state_dict()[k]),k)
        with self.assertRaisesRegex(ValueError,'retraining'):ValueNetwork().predict([f])
        mixed=deepcopy(records);mixed[0]['outcome']['objective']='basket'
        with self.assertRaisesRegex(ValueError,'Mixed trajectory'):labels(mixed)


class CashSourceTests(unittest.TestCase):
    def bundle(self,root,kind='synthetic_fixture',executable=True,currency='USD'):
        from pathlib import Path
        p=Path(root);row=asdict(Trade(0,'S',100000.,1.,'buy','s0',100000.,'spot',executable))
        body=gzip.compress((json.dumps(row)+'\n').encode(),mtime=0);(p/'tape.jsonl.gz').write_bytes(body)
        m=dict(schema_version=1,currency=currency,instruments=[asdict(instruments()['S'])],objects=[dict(
            file='tape.jsonl.gz',kind=kind,source_uri='fixture://cash-v1',bytes=len(body),sha256=hashlib.sha256(body).hexdigest())])
        (p/'manifest.json').write_text(json.dumps(m));return p

    def test_cash_source_hash_units_currency_and_indicative_guard(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.bundle(d);ins,tape,m=load_cash_bundle(p);self.assertEqual(m['rows'],1)
            b=[dict(start=20000,end=21000,seeds=[],tape=[])];attach_cash_blocks(b,ins,tape)
            self.assertEqual(b[0]['seeds'],tape)
            self.bundle(d,kind='indicative_quote',executable=True)
            with self.assertRaisesRegex(ValueError,'Indicative'):load_cash_bundle(p)
            self.bundle(d,kind='indicative_quote',executable=False);ins,tape,_=load_cash_bundle(p)
            self.assertFalse(tape[0].executable)
            self.bundle(d,currency='USDT')
            with self.assertRaisesRegex(ValueError,'USD cash'):load_cash_bundle(p)
            self.bundle(d)
            rows=json.loads(gzip.decompress((p/'tape.jsonl.gz').read_bytes()));rows['source_time']=-1
            body=gzip.compress((json.dumps(rows)+'\n').encode(),mtime=0);(p/'tape.jsonl.gz').write_bytes(body)
            manifest=json.loads((p/'manifest.json').read_text());manifest['objects'][0].update(bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
            (p/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'retroactive'):load_cash_bundle(p)
            self.bundle(d);(p/'tape.jsonl.gz').write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):load_cash_bundle(p)
