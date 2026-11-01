"""Independent cashflow/search checks, runnable with unittest."""
import unittest
import numpy as np
from longer_timelines import Market, State, Net, dataset, rollout, verify_original

class SearchTests(unittest.TestCase):
    def test_matches_all_original_labels(self):
        self.assertEqual(verify_original()['original_labels'],61)

    def test_eight_step_exhaustive_search(self):
        env=Market(8)
        # Explicit paths, no affine cash reduction or shared search states.
        values=[]
        def visit(t,cash,q):
            if t==8:
                for j in range(q):cash+=95+env.slope*(t+j+.75)+.25
                values.append(cash);return
            visit(t+1,cash,q)
            if q<4:visit(t+1,cash-(95+env.slope*t+.25),q+1)
            if q>0:visit(t+1,cash+(95+env.slope*t-.25),q-1)
        visit(0,1000.,0)
        self.assertEqual(len(values),env.path_count())
        self.assertAlmostEqual(max(values),env.exact(env.initial,8),places=10)

    def test_subsequent_print_closing(self):
        for T in [4,8,16,32,64,128]:
            env=Market(T)
            for t in [0,T//2,T]:
                for q in range(5):
                    s=State(t,round(678.25*env.scale),q)
                    independent=s.cash_ticks/env.scale
                    times=[]
                    for k in range(t,T+5):
                        if len(times)<q:
                            event=k+.75;independent+=95+2*event/T+.25;times.append(event)
                    self.assertEqual(len(times),q)
                    self.assertTrue(all(time>t for time in times))
                    self.assertAlmostEqual(env.close(s),independent,places=10)

    def test_all_horizons_and_state_split(self):
        env=Market(16);rng=np.random.default_rng(17);states=set()
        for _ in range(16):states.update(rollout(env,rng))
        subsets={which:{s for s in states if env.split(s)==which} for which in ['train','validation','test']}
        self.assertTrue(subsets['train'].isdisjoint(subsets['validation']))
        self.assertTrue(subsets['train'].isdisjoint(subsets['test']))
        data=dataset(env,subsets['train'])
        for s in subsets['train']:
            self.assertEqual({end for ss,end in data['records'] if ss==s},set(range(s.t,17)))

    def test_affine_cash_and_budget_accounting(self):
        for T in [8,16,32,64]:
            env=Market(T)
            self.assertEqual(env.oracle_edges,13*T*(T+1)//2)
            self.assertEqual(env.boundaries,5*(T+1))
            for q in range(5):
                low=State(T//2,600*env.scale,q);high=State(T//2,700*env.scale,q)
                self.assertAlmostEqual(env.exact(high,T)-env.exact(low,T),100.)

    def test_network_parameter_count_and_initialization(self):
        n=Net(20261101);m=Net(20261101)
        self.assertEqual(sum(p.size for p in n.p),97)
        for a,b in zip(n.p,m.p):np.testing.assert_array_equal(a,b)

    def test_optimal_buy_first_formula_all_horizons(self):
        for T in [8,16,32,64]:
            env=Market(T)
            for end in range(T+1):
                for t in range(end+1):
                    for q in range(5):
                        buys=min(end-t,4-q);final_q=q+buys
                        paid=buys*(95+env.slope*t+.25)+env.slope*buys*(buys-1)/2
                        proceeds=final_q*(95+env.slope*(end+.75)+.25)+env.slope*final_q*(final_q-1)/2
                        self.assertAlmostEqual(env.W[end,t,q],proceeds-paid,places=10)

if __name__=='__main__':unittest.main()
