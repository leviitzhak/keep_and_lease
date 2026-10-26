import math,random,unittest
from dataclasses import asdict
from research.post_decision_value.action_search import SparseGridDomain,ValueActionSearch,sparse_levels
from research.post_decision_value.accounting import Instrument,Ledger,Goal
from research.post_decision_value.engine import ObservableState,Order
from research.post_decision_value.pilot import continuation_identity,episode,Budget
from research.post_decision_value.engine import Delays,Trade


class SparseGridTests(unittest.TestCase):
    def state(self):
        ins={s:Instrument(s,10000,tick=1,lot=.001,fee_bps=0) for s in ('A','B')}
        obs=ObservableState(1,Ledger({'BTC':1.,'USD':100000.}))
        obs.market={s:dict(price=100.,index=100.,received=0,time=0) for s in ins}
        return obs,Goal(obs.ledger.balances.copy(),1000,10000,reference={'BTC':100.,'USD':1.}),ins

    def test_endpoints_and_bounded_size_even_for_huge_lattice(self):
        levels=sparse_levels(1,10**12,2,random.Random(3))
        self.assertIn(1,levels);self.assertIn(10**12,levels);self.assertLessEqual(len(levels),5)
        self.assertEqual(sparse_levels(4,4,2,random.Random(3)),(4,))
        self.assertEqual(sparse_levels(5,4,2,random.Random(3)),())

    def test_all_price_size_endpoints_both_sides_in_search(self):
        obs,goal,ins=self.state();domain=SparseGridDomain(.001,.003,200,2,random_points=2)
        a,info=ValueActionSearch(domain,32).choose(obs,goal,ins,lambda actions:[sum(o.quantity for o in x.orders) for x in actions],rng=random.Random(7))
        observed={(o['symbol'],round(o['quantity'],3),o['limit']) for x in info['proposals'] if x['instruction']['kind']=='create' and len(x['instruction']['orders'])==1 for o in x['instruction']['orders']}
        expected={(s,sign*q,p) for s in ins for sign in (-1,1) for q in (.001,.003) for p in (98.,102.)}
        self.assertTrue(expected<=observed);self.assertEqual(info['boundary_proposals_not_attempted'],0)
        self.assertEqual(info['attempts'],32);self.assertEqual(len(info['price_grid']),2)
        self.assertTrue(domain.contains(obs,a,ins))

    def test_seeded_grid_changes_interiors_and_native_inverse_lots(self):
        obs,goal,_=self.state();ins={'A':Instrument('A',10000,'inverse',tick=.01,lot=.01,fee_bps=0)}
        domain=SparseGridDomain(.001,.003,200,2)
        a=domain.prepare(random.Random(1),obs,goal,ins);b=domain.prepare(random.Random(2),obs,goal,ins)
        self.assertNotEqual(a.prices,b.prices)
        rng=random.Random(2)
        for _ in range(50):self.assertTrue(domain.contains(obs,a.sample(rng,obs,goal,ins),ins))

    def test_amendment_extremes_and_budget_reporting(self):
        obs,goal,ins=self.state();obs.uncertain={'old':[Order('old','A',.001,100)]}
        search=ValueActionSearch(SparseGridDomain(.001,.003,200),32)
        _,info=search.choose(obs,goal,ins,lambda a:[0.]*len(a),rng=random.Random(5))
        limits={o['limit'] for r in info['proposals'] if r['instruction']['kind']=='amend' for o in r['instruction']['orders']}
        self.assertTrue({98.,102.}<=limits)
        _,small=ValueActionSearch(search.domain,4).choose(obs,goal,ins,lambda a:[0.]*len(a),rng=random.Random(5))
        self.assertGreater(small['boundary_proposals_not_attempted'],0)

    def test_policy_identity_includes_grid_and_effort(self):
        config=dict(action_space='grid',action_domain=asdict(SparseGridDomain())|{},search_evaluations=32,grid_random_points=2)
        a=continuation_identity('exploratory_v1',config)
        config['grid_random_points']=3;self.assertNotEqual(a,continuation_identity('exploratory_v1',config))
        config['search_rounds']=2;self.assertNotEqual(a,continuation_identity('exploratory_v1',config))

    def test_grid_runs_in_closed_loop_and_retains_search_audit(self):
        _,_,ins=self.state()
        block=dict(id='fixture',split='train',start=1,end=4,seeds=[Trade(0,s,100,1000,'buy',s,100) for s in ins],tape=[])
        config=dict(initial_btc=1.,initial_usd=100000.,reference_btc=100.,delays=asdict(Delays(0,0,0,0,0,0)),participation=.1,event_cap=100,
                    candidate_budget=96,action_space='grid',action_domain=dict(min_btc=.001,max_btc=.003,price_band_bps=200.,max_new_orders=2),
                    search_evaluations=32,cadence_ms=1,pilot_seconds=30,transition_cap=10)
        records,result=episode(block,ins,11,'hold',config,Budget(config),retain=True)
        self.assertEqual(len(records),3);self.assertTrue(result['outcome']['done'])
        self.assertTrue(all(x['instruction']['kind']=='wait' for x in records))


class CarryAccountingTests(unittest.TestCase):
    def ledger(self,q):
        ins=Instrument('F',1000,fee_bps=0);p=Ledger({'BTC':1.,'USD':100000.})
        # Economic construction only: not a claim of atomic spot/futures fills.
        p.balances['BTC']-=1;p.balances['USD']+=100000
        p.buy_treasury('bill',100000,[(999,105000)],enabled=True);p.fill(ins,q,104000)
        return p,ins

    def test_same_btc_size_keeps_cash_surplus_after_variation_and_bridge(self):
        for final_spot in (70000,120000):
            p,ins=self.ledger(1.)
            for mark in (110000,85000,101000):p.variation(ins,mark)
            p.resolve_cashflows(999);p.bridge(ins,final_spot,final_spot,observed=True)
            self.assertAlmostEqual(p.balances['BTC'],1.)
            self.assertAlmostEqual(p.balances['USD'],101000.)
            # Spending only carry surplus buys more BTC; initial cash stays held.
            extra=(p.balances['USD']-100000)/final_spot
            self.assertAlmostEqual(1+extra,1+1000/final_spot)

    def test_larger_prefunded_futures_size_locks_more_btc_under_ideal_bridge(self):
        for final_spot in (70000,120000):
            p,ins=self.ledger(105000/104000)
            p.variation(ins,80000);p.resolve_cashflows(999)
            p.bridge(ins,final_spot,final_spot,observed=True)
            self.assertAlmostEqual(p.balances['BTC'],105000/104000)
            self.assertAlmostEqual(p.balances['USD'],100000.)

    def test_basis_gap_and_fees_reduce_surplus_and_selling_first_breaches_floor(self):
        p,ins=self.ledger(1.);p.resolve_cashflows(999);p.bridge(ins,100000,100500,observed=True,fee_bps=10)
        self.assertAlmostEqual(p.balances['USD'],100399.5)
        goal=Goal({'BTC':1.,'USD':100000.},100,1000)
        self.assertLess(goal.headroom({'BTC':0.,'USD':200000.})['BTC'],0)

    def test_neutral_futures_pair_gains_cash_but_joint_min_can_be_zero(self):
        a=Instrument('A',1000,fee_bps=0);b=Instrument('B',2000,fee_bps=0);ins={'A':a,'B':b}
        p=Ledger({'BTC':1.,'USD':100000.});p.fill(a,.1,100000);p.fill(b,-.1,101000)
        self.assertAlmostEqual(p.holdings(ins)['BTC'],1.)
        self.assertAlmostEqual(p.holdings(ins)['USD'],100100.)
        self.assertEqual(Goal({'BTC':1.,'USD':100000.},100,2000).outcome(p.holdings(ins))['utility'],0.)


if __name__=='__main__':unittest.main()
