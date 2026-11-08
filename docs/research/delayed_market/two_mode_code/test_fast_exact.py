import copy, unittest
import numpy as np
import search
from fast_exact import FastPathSimulator, assert_same

class FastCloneTests(unittest.TestCase):
    def test_mature_branch_clone_parity(self):
        for horizon in [10,24]:
            for seed in [111,222,777]:
                s=FastPathSimulator(search.Config(horizon=horizon,tail_end=horizon+10,seed=seed));s.snapshot('before')
                rng=np.random.default_rng(seed)
                for t in range(horizon):
                    actions=search.feasible_actions(s.observation())
                    pristine=copy.deepcopy(s)
                    for a in actions:
                        slow=copy.deepcopy(s);slow.__class__=search.PathSimulator
                        for mode in ['first','random']:
                            c1,_=search.transition(s,a,mode,seed=919+t)
                            c2,_=search.transition(slow,a,mode,seed=919+t)
                            assert_same(c1,c2);assert_same(s,pristine)
                            r1=search.record(c1.observation(),horizon);r2=search.record(c2.observation(),horizon)
                            for k in r1:np.testing.assert_array_equal(r1[k],r2[k])
                    a=actions[int(rng.integers(len(actions)))];s,_=search.transition(s,a,'random',seed=918+t)

    def test_full_trajectory_parity(self):
        from network import Transformer
        from exploration import ExplorationSchedule
        for seed in [111,222]:
            fast=FastPathSimulator(search.Config(seed=seed));fast.snapshot('before')
            slow=copy.deepcopy(fast);slow.__class__=search.PathSimulator
            a=search.trajectory(fast,10,Transformer(),991,count=4,schedule=ExplorationSchedule())
            b=search.trajectory(slow,10,Transformer(),991,count=4,schedule=ExplorationSchedule())
            for k in ['value','rows','observations','legs']:self.assertEqual(a[k],b[k],k)
            assert_same(a['terminal'],b['terminal'])

if __name__=='__main__':unittest.main()
