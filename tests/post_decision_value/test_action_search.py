import math,random,unittest
from dataclasses import asdict
import numpy as np
import torch
from research.post_decision_value.action_search import ActionDomain,ValueActionSearch
from research.post_decision_value.accounting import Instrument,Ledger,Goal
from research.post_decision_value.engine import ObservableState,Order,Instruction,Engine,Delays,Trade,admissible,post_decision
from research.post_decision_value.model import ValueNetwork,features,action_features,batch

class FullActionTests(unittest.TestCase):
    def state(self,n=2):
        instruments={chr(65+i):Instrument(chr(65+i),10000,tick=1,lot=.001,fee_bps=0) for i in range(n)}
        obs=ObservableState(1,Ledger({'BTC':1.,'USD':100000.}))
        obs.market={s:dict(price=100.,index=100.,received=0,time=0) for s in instruments}
        goal=Goal({'BTC':1.,'USD':100000.},1000,10000,reference={'BTC':100.,'USD':1.})
        return obs,goal,instruments
    def test_entire_native_single_order_lattice_has_support(self):
        obs,goal,ins=self.state();domain=ActionDomain(.001,.003,100,max_new_orders=1);rng=random.Random(3)
        observed=set()
        for _ in range(5000):
            action=domain.sample(rng,obs,goal,ins);self.assertTrue(domain.contains(obs,action,ins))
            o=action.orders[0];observed.add((o.symbol,round(o.quantity,3),o.limit))
        expected={(s,sign*q/1000,p) for s in ins for sign in (-1,1) for q in (1,2,3) for p in (99,100,101)}
        self.assertEqual(observed,expected);self.assertEqual(domain.single_order_count(obs,goal,ins),36)
    def test_native_inverse_quantity_bounds(self):
        obs,goal,_=self.state();ins={'A':Instrument('A',10000,'inverse',tick=1,lot=1,fee_bps=0)}
        domain=ActionDomain(.01,.05,100,max_new_orders=1);rng=random.Random(4)
        for _ in range(200):
            a=domain.sample(rng,obs,goal,ins);self.assertTrue(domain.contains(obs,a,ins))
            q=abs(a.orders[0].quantity/a.orders[0].limit);self.assertGreaterEqual(q,.01-1e-12);self.assertLessEqual(q,.05+1e-12)
    def test_new_postings_allowed_with_working_orders(self):
        obs,goal,ins=self.state();obs.uncertain={'old':[Order('old','A',.001,100)]}
        search=ValueActionSearch(ActionDomain(.001,.003,100,2),evaluations=64)
        action,info=search.choose(obs,goal,ins,lambda actions:[10. if a.kind=='create' else 0. for a in actions],rng=random.Random(8))
        self.assertEqual(action.kind,'create');self.assertTrue(admissible(obs,action,goal,ins)[0])
        kinds={r['instruction']['kind'] for r in info['proposals']};self.assertTrue({'create','amend','cancel','batch'}<=kinds)
        amendments=[r['instruction']['orders'] for r in info['proposals'] if r['instruction']['kind']=='amend']
        self.assertTrue(any(o['limit']!=100 for orders in amendments for o in orders))
        self.assertTrue(any(abs(o['quantity'])!=.001 for orders in amendments for o in orders))
    def test_independent_pair_sizes_prices_and_both_orientations(self):
        obs,goal,ins=self.state();domain=ActionDomain(.001,.005,200,2);rng=random.Random(9);found=False
        for _ in range(500):
            a=domain.sample(rng,obs,goal,ins)
            if len(a.orders)==2:
                x,y=a.orders
                if abs(x.quantity)!=abs(y.quantity) and x.limit+y.limit!=200:found=True
        self.assertTrue(found)
    def test_scalar_argmax_and_seeded_exploration(self):
        obs,goal,ins=self.state();search=ValueActionSearch(ActionDomain(.001,.003,100,2),evaluations=64)
        def score(actions):return [sum(o.quantity for o in a.orders) for a in actions]
        a,info=search.choose(obs,goal,ins,score,rng=random.Random(5))
        scored=[r['instruction'] for r in info['proposals'] if r['accepted']]
        self.assertAlmostEqual(sum(o.quantity for o in a.orders),max(sum(o['quantity'] for o in x['orders']) for x in scored))
        a,x=search.choose(obs,goal,ins,score,rng=random.Random(7),epsilon=1.)
        b,y=search.choose(obs,goal,ins,score,rng=random.Random(7),epsilon=1.)
        self.assertEqual(a,b);self.assertEqual(x,y);self.assertTrue(x['explored']);self.assertTrue(admissible(obs,a,goal,ins)[0])
    def test_batch_does_not_resurrect_unreported_filled_order(self):
        obs,goal,ins=self.state();e=Engine(ins,obs.ledger,goal,11,Delays(0,0,100,200,0,0),participation=1)
        e.seed_market([Trade(0,s,100,1000,'buy',s,100) for s in ins],1)
        e.submit(Instruction('create',(Order('old','A',.001,100),)))
        e.add_tape([Trade(120,'A',99,1000,'sell','fill',100)])
        e.advance(130);self.assertNotIn('old',e.hidden.orders);self.assertIn('old',e.observable.uncertain)
        action=Instruction('batch',(Order('old','A',.002,99),Order('new','B',-.001,101)),('old',))
        before=e.observe();post=post_decision(before,action,ins)
        self.assertEqual(len(post.uncertain['old']),2);self.assertNotIn('new',before.uncertain)
        e.submit(action);e.advance(240)
        self.assertNotIn('old',e.hidden.orders);self.assertIn('new',e.hidden.orders)
        e.advance(500);self.assertNotIn('old',e.observable.uncertain);self.assertIn('new',e.observable.confirmed)
    def test_batch_unknown_targets_and_duplicate_ids_rejected(self):
        obs,goal,ins=self.state();obs.uncertain={'old':[Order('old','A',.001,100)]}
        self.assertFalse(admissible(obs,Instruction('batch',targets=('missing',)),goal,ins)[0])
        self.assertFalse(admissible(obs,Instruction('batch',(Order('old','A',.002,100),)),goal,ins)[0])
    def test_more_than_32_items_and_actual_orders_enter_network(self):
        obs,goal,ins=self.state(40)
        action=Instruction('batch',(Order('new','A',.003,101),))
        f=features(post_decision(obs,action,ins),goal,ins)
        self.assertEqual(len(f['items']),41)
        model=ValueNetwork();pred=model.predict([f]);self.assertEqual(pred['objective'].shape,(1,))
        changed=features(post_decision(obs,Instruction('batch',(Order('new','A',.002,99),)),ins),goal,ins)
        self.assertNotEqual(f['items'],changed['items'])
        self.assertEqual(len(f['global_']),34);self.assertEqual(len(f['items'][0]),20)
    def test_invalid_domain_scores_and_version_budget(self):
        with self.assertRaises(ValueError):ActionDomain(max_btc=math.inf)
        obs,goal,ins=self.state();search=ValueActionSearch(evaluations=8)
        with self.assertRaisesRegex(ValueError,'Finite scalar'):search.choose(obs,goal,ins,lambda a:[float('nan')]*len(a))
        obs.uncertain={str(i):[Order(str(i),'A',.001,100)] for i in range(6)}
        self.assertFalse(admissible(obs,Instruction('create',(Order('new','A',.001,100),)),goal,ins)[0])

    def test_fast_features_equal_detached_post_state_and_leave_input_unchanged(self):
        obs,goal,ins=self.state();before=asdict(obs);rng=random.Random(12)
        for _ in range(30):
            action=ActionDomain(.001,.003,100).sample(rng,obs,goal,ins)
            self.assertEqual(action_features(obs,action,goal,ins),features(post_decision(obs,action,ins),goal,ins))
        self.assertEqual(asdict(obs),before)

    def test_shared_history_matches_full_forward_and_invalidates_after_weights_change(self):
        obs,goal,ins=self.state();torch.manual_seed(3);model=ValueNetwork();model.eval()
        f=features(obs,goal,ins);g=features(obs,goal,ins);g['history']=[[.2]*8,[.3]*8]
        fs=[f,g,f,g];cache={}
        with torch.no_grad():expected=model(batch(fs))[:,:3].numpy()
        predicted=model.predict(fs,history_cache=cache)
        np.testing.assert_allclose(predicted['objective'],expected[:,0],rtol=1e-5,atol=1e-6)
        self.assertEqual(len(cache),2)
        self.assertEqual(model.predict(fs,history_cache=cache)['objective'].tolist(),predicted['objective'].tolist())
        with torch.no_grad():model.hist.bias.add_(.5);changed=model(batch(fs))[:,:3].numpy()
        actual=model.predict(fs,history_cache=cache)
        np.testing.assert_allclose(actual['objective'],changed[:,0],rtol=1e-5,atol=1e-6)
        self.assertEqual(len(cache),4)

    def test_continuation_identity_includes_search_domain_and_model_weights(self):
        from research.post_decision_value.pilot import continuation_identity
        config=dict(action_space='full',action_domain=asdict(ActionDomain()),search_evaluations=128)
        a=continuation_identity('exploratory_v1',config)
        config['search_evaluations']=256
        self.assertNotEqual(a,continuation_identity('exploratory_v1',config))
        model=ValueNetwork();a=continuation_identity('collect_greedy_v1_eps015',config,model)
        with torch.no_grad():model.readout[-1].bias.add_(1.)
        self.assertNotEqual(a,continuation_identity('collect_greedy_v1_eps015',config,model))

if __name__=='__main__':unittest.main()
