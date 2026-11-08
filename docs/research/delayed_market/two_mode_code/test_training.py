import unittest,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from network import Transformer,batch,predict
from search import *

class TrainingTests(unittest.TestCase):
    def test_nontrivial_max_min_retains_the_minimizing_child(self):
        # Regression fixture: choosing a maximum child or an average would pick
        # WAIT; max-min must pick BUY and retain its lower-valued child.
        s=PathSimulator();s.snapshot('before');aa=feasible_actions(s.observation())[:2]
        def branches(root,a):
            values=[1005.,1000.] if a.kind=='WAIT' else [1003.,1002.]
            result=[]
            for value in values:
                c,post=transition(root,a);c.reported_cash=round(value*32);result.append((c,post))
            return result
        with patch('search.feasible_actions',return_value=aa),patch('search.enumerate_successors',side_effect=branches):
            child,r=step(s,3,None,np.random.default_rng(0),True,exhaustive=True)
        self.assertEqual(r['action_index'],1);self.assertEqual(r['selected_delay_index'],1)
        self.assertEqual(r['minimum'],1002.);self.assertEqual(child.reported_cash/32,1002.)

    def test_exhaustive_delays_and_compression_agree(self):
        s=PathSimulator();s.snapshot('before');m=Transformer(d=8,heads=2,ff=16)
        for t in range(4):
            fast,a=step(s,6,m,np.random.default_rng(3),True)
            slow,b=step(s,6,m,np.random.default_rng(3),True,exhaustive=True)
            self.assertEqual(a['action'],b['action']);self.assertAlmostEqual(a['next_value'],b['next_value'],places=5)
            self.assertEqual(key(fast.observation()),key(slow.observation()))
            self.assertEqual([(z['event'],z['delay']) for z in fast.delay_draws],[(z['event'],z['delay']) for z in slow.delay_draws])
            s,_=step(s,6,m,np.random.default_rng(30+t),exploration=1)

    def test_root_delay_tree_is_complete_and_hidden(self):
        s=PathSimulator();s.snapshot('before');a=feasible_actions(s.observation())[-1]
        cc=enumerate_successors(s,a)
        # outbound=1: 2 market reports and an ack => 27; outbound=2/3 => 9 each.
        self.assertEqual(len(cc),45);self.assertEqual(len({key(c.observation()) for c,p in cc}),1)
        self.assertEqual({c.delay_draws[len(s.delay_draws)]['delay'] for c,p in cc},{1,2,3})
        self.assertEqual({c.active_order_id is None for c,p in cc},{False,True})

    def test_random_exploration_uses_random_actions_and_delays(self):
        s=PathSimulator();s.snapshot('before');actions=set();delays=set()
        for seed in range(60):
            c,r=step(s,10,None,np.random.default_rng(seed),exploration=1)
            self.assertEqual(r['mode'],'exploratory');self.assertIsNone(r['minimum']);actions.add(r['action'])
            delays.update(x['delay'] for x in r['new_delays'])
        self.assertGreater(len(actions),5);self.assertEqual(delays,{1,2,3})

    def test_inherited_delay_assignments_never_resampled(self):
        s=PathSimulator();s.snapshot('before');a=feasible_actions(s.observation())[-1]
        s,_=transition(s,a,'enumerate',(3,2,3));old=copy.deepcopy(s.delay_draws)
        event=next(e for e in s.queue if e[3]=='command');self.assertEqual(event[0],12)
        c,r=step(s,10,None,np.random.default_rng(5),True)
        self.assertEqual(c.delay_draws[:len(old)],old);self.assertIn(event,c.queue)

    def test_winning_first_transition_is_copied_whole(self):
        s=PathSimulator();s.snapshot('before');q=search(s,4,None,count=4,seed=4,audit=True)
        self.assertEqual(q['value'],max(r['value'] for r in q['rollouts']))
        self.assertEqual(full_state(q['next']),full_state(q['rollouts'][q['winner']]['first']))
        for r in q['rollouts']:
            self.assertEqual(len(r['rows']),4);self.assertEqual(r['value'],liquidation(r['terminal'],4))

    def test_replanning_keeps_only_winning_first_step(self):
        s=PathSimulator();s.snapshot('before');tr=trajectory(s,4,None,seed=8,count=3)
        for i,q in enumerate(tr['queries']):
            self.assertEqual(key(tr['observations'][i+1]),key(q['next'].observation()))
            self.assertEqual(tr['rows'][i]['best_rollout_value'],max(r['value'] for r in q['rollouts']))
        self.assertEqual(tr['value'],liquidation(tr['terminal'],4))

    def test_network_receives_only_delivered_history(self):
        s=PathSimulator();o=s.snapshot('before');r=record(o,10)
        c=s.clone();c.exchange_cash-=500;c.exchange_bills=2
        np.testing.assert_array_equal(record(c.observation(),10)['tokens'],r['tokens'])
        self.assertNotIn('pending_events',o);self.assertNotIn('delay_assignments',o)

    def test_last_step_still_uses_network_value(self):
        s=PathSimulator();s.snapshot('before')
        with patch('search.predict',lambda model,rr:np.full(len(rr),1234.5)):
            c,r=step(s,1,None,np.random.default_rng(1),True)
        self.assertEqual(r['minimum'],1234.5);self.assertNotEqual(liquidation(c,1),1234.5)

    def test_liquidation_uses_true_inventory_and_future_prints(self):
        s=PathSimulator();s.exchange_bills=5;s.exchange_cash=16000
        v,ll=liquidation(s,10,True);self.assertEqual([z['quantity'] for z in ll],[2,2,1])
        self.assertTrue(all(z['time']>10 for z in ll));self.assertEqual(v,500+sum(z['proceeds'] for z in ll))

    def test_transformer_gradient_finite_difference(self):
        m=Transformer(d=8,heads=2,ff=16,dtype=np.float64);rng=np.random.default_rng(42)
        x=rng.normal(0,.2,(2,4,60));mask=np.array([[0,1,1,1],[1,1,1,1]],bool);c=rng.normal(size=(2,3));y=np.array([.1,-.2])
        v,p=m.forward(x,mask,c,True);loss=((v-y)**2).mean();loss.backward();errors=[]
        for name,a in m.p.items():
            idx=tuple(rng.integers(z) for z in a.shape);old=a[idx];eps=1e-5
            a[idx]=old+eps;hi=np.mean((m.forward(x,mask,c)-y)**2)
            a[idx]=old-eps;lo=np.mean((m.forward(x,mask,c)-y)**2);a[idx]=old
            e=abs((hi-lo)/(2*eps)-p[name].grad[idx]);errors.append(e);self.assertLess(e,2e-7,name)
        self.__class__.max_gradient_error=max(errors)

    def test_causal_attention(self):
        m=Transformer(d=8,heads=2,ff=16);rng=np.random.default_rng(3)
        x=rng.normal(size=(1,6,60)).astype(np.float32);mask=np.ones((1,6),bool);c=np.ones((1,3),np.float32)
        a=m.forward(x,mask,c,read_index=2);x[:,3:]+=100;b=m.forward(x,mask,c,read_index=2)
        np.testing.assert_allclose(a,b,atol=1e-7)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(TrainingTests);names=[x.id().split('.')[-1] for x in suite]
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    (Path(__file__).parent/'validation.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),tests_run=result.testsRun,tests=names,max_gradient_error=getattr(TrainingTests,'max_gradient_error',None),errors=[(str(t),e) for t,e in result.failures+result.errors]),indent=2))
    raise SystemExit(not result.wasSuccessful())
