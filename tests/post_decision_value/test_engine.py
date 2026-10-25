from copy import deepcopy
import tempfile
import unittest
from research.post_decision_value.accounting import Instrument,Ledger,Goal
from research.post_decision_value.engine import *
from research.post_decision_value.model import features
from research.post_decision_value.checkpoint import DirectoryCheckpoints,save_engine,restore_engine
from research.post_decision_value.data import validate_splits

class EngineTests(unittest.TestCase):
    def make(self,delivery=10,report=20,payoff='linear',event_cap=10000):
        ins=Instrument('F',10000,payoff,lot=.001 if payoff=='linear' else 10,fee_bps=0)
        goal=Goal({'BTC':1.,'USD':100000.},1000,10000,reference={'BTC':100000.,'USD':1.})
        e=Engine({'F':ins},Ledger(goal.initial.copy()),goal,42,Delays(0,0,delivery,report,0,0),participation=1,event_cap=event_cap)
        e.seed_market([Trade(0,'F',100000,10000,'buy','seed',100000)],1)
        return e
    def action(self,e,qty=.01,price=100000):
        return Instruction('create',(Order('o','F',qty,price,created=e.now),))
    def trade(self,t,price=99000,amount=990,side='sell',id=None):
        return Trade(t,'F',price,amount,side,str(id or t),100000)
    def test_no_fill_before_arrival_and_strict_through(self):
        e=self.make();e.submit(self.action(e));e.add_tape([self.trade(5),self.trade(12,100000),self.trade(13,99000,side='buy'),self.trade(14)])
        e.advance(20);self.assertEqual(len(e.hidden.fills),1)
        self.assertEqual(e.hidden.fills[0]['time'],14);self.assertEqual(e.hidden.fills[0]['price'],100000)
    def test_source_capacity_partial_and_conservation(self):
        e=self.make(delivery=0);a=Instruction('create',(Order('a','F',.008,100000),Order('b','F',.008,100000)))
        e.submit(a);e.add_tape([self.trade(10,amount=990)]);e.advance(11)
        self.assertAlmostEqual(sum(abs(f['quantity']) for f in e.hidden.fills),.01)
        self.assertAlmostEqual(e.hidden.orders['b'].quantity,.006)
    def test_live_unacknowledged_and_filled_unreported(self):
        e=self.make();e.submit(self.action(e));e.add_tape([self.trade(12)])
        e.advance(11);self.assertIn('o',e.hidden.orders);self.assertNotIn('o',e.observable.confirmed)
        self.assertTrue(e.observable.pending);e.advance(13)
        self.assertTrue(e.hidden.ledger.positions);self.assertFalse(e.observable.ledger.positions)
        self.assertTrue(e.observable.uncertain);e.advance(50)
        self.assertAlmostEqual(e.observable.ledger.positions['F'].quantity,.01)
        self.assertFalse(e.observable.uncertain);self.assertEqual(e.observable.reserved['USD'],0.)
    def test_cancel_race_and_release_after_report(self):
        e=self.make(delivery=10,report=20);e.submit(self.action(e));e.advance(32)
        e.submit(Instruction('cancel',targets=('o',)));e.add_tape([self.trade(40)])
        e.advance(43);self.assertEqual(len(e.hidden.fills),1);self.assertTrue(e.observable.uncertain)
        e.advance(70);self.assertFalse(e.observable.uncertain);self.assertEqual(e.observable.reserved['USD'],0.)
    def test_cancel_before_print(self):
        e=self.make();e.submit(self.action(e));e.advance(32);e.submit(Instruction('cancel',targets=('o',)))
        e.add_tape([self.trade(43)]);e.advance(80);self.assertFalse(e.hidden.fills)
    def test_amend_not_effective_at_submission(self):
        e=self.make();e.submit(self.action(e));e.advance(32)
        e.submit(Instruction('amend',(Order('o','F',.01,98000,created=32),),('o',)))
        e.add_tape([self.trade(40),self.trade(50)])
        e.advance(90);self.assertEqual(len(e.hidden.fills),1);self.assertEqual(e.hidden.fills[0]['price'],100000)
    def test_hidden_future_and_latency_do_not_change_features(self):
        e=self.make();e.submit(self.action(e));x=features(e.observe(),e.goal,e.instruments)
        e.hidden.queue=[(t+900,p,s,k,d) for t,p,s,k,d in e.hidden.queue]
        e.hidden.ledger.balances['USD']=1;e.add_tape([self.trade(999,150000)])
        self.assertEqual(x,features(e.observe(),e.goal,e.instruments))
    def test_pure_post_state_does_not_fill_or_cancel(self):
        e=self.make();a=self.action(e);x=post_decision(e.observe(),a,e.instruments)
        self.assertFalse(x.ledger.positions);self.assertTrue(x.pending);self.assertFalse(e.observable.pending)
        y=post_decision(x,Instruction('cancel',targets=('o',)),e.instruments)
        self.assertIn('o',y.uncertain);self.assertEqual(y.reserved,x.reserved)
    def test_seeded_replay_and_resume(self):
        e=self.make();e.delays=Delays(3,2,10,20,.5,.5)
        e.submit(self.action(e));e.add_tape([self.trade(t,amount=200) for t in range(50,200,10)]);e.advance(70)
        with tempfile.TemporaryDirectory() as d:
            store=DirectoryCheckpoints(d);save_engine(store,70,e,{'source':'a'})
            other=restore_engine(store,{'source':'a'})
            with self.assertRaises(ValueError):restore_engine(store,{'source':'b'})
            e.advance(1000);other.advance(1000)
            self.assertEqual(e.outcome(),other.outcome());self.assertEqual(e.hidden.fills,other.hidden.fills)
    def test_async_and_floor_masks_use_partial_subsets(self):
        e=self.make();a=self.action(e,qty=.101)
        self.assertFalse(admissible(e.observe(),a,e.goal,e.instruments)[0])
        a=Instruction('create',(Order('o','F',.03,100000,'g'),Order('p','F',-.03,100000,'g')))
        self.assertEqual(admissible(e.observe(),a,e.goal,e.instruments)[1],'asynchronous_cap')
    def test_candidate_prices_rounded_and_budgeted(self):
        e=self.make();actions,audit=CandidateGenerator(budget=12).generate(e.observe(),e.goal,e.instruments)
        self.assertLessEqual(len(audit),12);self.assertTrue(any(a.kind=='wait' for a in actions))
        for a in actions:
            for o in a.orders:self.assertAlmostEqual(o.limit/2.5,round(o.limit/2.5))
    def test_runtime_truncation_has_no_terminal_label(self):
        e=self.make(event_cap=3);e.add_tape([self.trade(10),self.trade(20)]);e.advance(1000)
        self.assertFalse(e.outcome()['done']);self.assertNotIn('holdings',e.outcome())
    def test_inverse_native_bounded_fixture(self):
        e=self.make(payoff='inverse');e.submit(self.action(e,qty=100));e.add_tape([self.trade(20,amount=100)])
        e.advance(1000);self.assertEqual(e.outcome()['fills'],1)
        self.assertAlmostEqual(e.outcome()['holdings']['BTC'],1.001)
        self.assertEqual(e.outcome()['holdings']['USD'],99900)
    def test_missing_settlement_is_not_realized(self):
        e=self.make();e.submit(self.action(e));e.add_tape([self.trade(20)]);e.advance(10001)
        self.assertTrue(e.truncated);self.assertFalse(e.outcome()['done'])
    def test_observed_expiry_bridge_and_delayed_report(self):
        e=self.make();e.goal.horizon=10050;e.goal.resolution=10050
        e.submit(self.action(e));e.add_tape([self.trade(20)])
        e._event(10000,1,'settlement',('F',120000,120000,True));e.advance(10050)
        self.assertFalse(e.hidden.ledger.positions);self.assertFalse(e.observable.ledger.positions)
        self.assertEqual(e.outcome()['holding_status'],'realized')
    def test_split_purges_full_label_tail(self):
        blocks=[dict(id='a',start=0,end=5,label_end=12,split='train'),dict(id='b',start=10,end=20,label_end=20,split='test')]
        with self.assertRaises(ValueError):validate_splits(blocks)
        blocks[1]['start']=13;validate_splits(blocks)
    def test_fixed_horizon_and_no_independent_maxima(self):
        e=self.make();x=e.observe();x.time=100
        self.assertAlmostEqual(features(x,e.goal,e.instruments)['global_'][1],900/86400000)
        x.time=200;self.assertAlmostEqual(features(x,e.goal,e.instruments)['global_'][1],800/86400000)
