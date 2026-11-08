import unittest
from unittest.mock import patch
import numpy as np
from exploration import ExplorationSchedule
from search import PathSimulator,trajectory,rollout,step,full_state,transition,feasible_actions

class ExplorationTests(unittest.TestCase):
    def test_independent_switches_and_endpoint_rates(self):
        expected={'fixed':(.3,.3,.3,.3),'rounds':(.3,.3,.15,.15),'timeline':(.5,.1,.5,.1),'both':(.5,.1,.25,.05)}
        for mode,values in expected.items():
            s=ExplorationSchedule(mode=mode)
            np.testing.assert_allclose([s.probability(r,i,10) for r,i in [(0,0),(0,9),(1,0),(1,9)]],values)

    def test_single_step_uses_midpoint_and_floor(self):
        s=ExplorationSchedule()
        self.assertAlmostEqual(s.probability(0,0,1),.3)
        self.assertAlmostEqual(s.probability(1,0,1),.15)
        self.assertEqual(s.probability(20,0,1),.05)
        for steps in [2,3,10]:
            self.assertAlmostEqual(np.mean([s.probability(0,i,steps) for i in range(steps)]),.3)

    def test_replanning_resets_timeline_at_each_search_root(self):
        s=PathSimulator();s.snapshot('before');schedule=ExplorationSchedule()
        tr=trajectory(s,4,None,seed=8,count=3,schedule=schedule,round_index=1)
        for t,q in enumerate(tr['queries']):
            nsteps=4-t
            for j,r in enumerate(q['rollouts']):
                for i,n in enumerate(r['rows']):
                    self.assertEqual(n['rollout_start'],t)
                    self.assertEqual(n['rollout_step'],i)
                    self.assertEqual(n['scheduled_exploration'],schedule.probability(1,i,nsteps))
                    self.assertEqual(n['exploration_probability'],0 if j==0 else n['scheduled_exploration'])
                    if j==0:self.assertEqual(n['mode'],'greedy')
            self.assertEqual(full_state(q['next']),full_state(q['rollouts'][q['winner']]['first']))

    def test_absolute_time_does_not_set_timeline_progress(self):
        s=PathSimulator();s.snapshot('before')
        for _ in range(3):s,_=transition(s,feasible_actions(s.observation())[0])
        r=rollout(s,6,None,seed=8,schedule=ExplorationSchedule(),round_index=0)
        np.testing.assert_allclose([x['exploration_probability'] for x in r['rows']],[.5,.3,.1])

    def test_fixed_mode_reproduces_legacy_rollout(self):
        s=PathSimulator();s.snapshot('before');rng=np.random.default_rng(551);c=s.clone()
        actions=[]
        for _ in range(5):
            c,n=step(c,5,None,rng,exploration=.3);actions.append(n['action'])
        r=rollout(s,5,None,seed=551,schedule=ExplorationSchedule(mode='fixed'))
        self.assertEqual(actions,[n['action'] for n in r['rows']])
        self.assertEqual(full_state(c),full_state(r['terminal']))

    def test_probability_controls_mode_but_does_not_change_delay_law(self):
        s=PathSimulator();s.snapshot('before')
        config=ExplorationSchedule(mode='fixed',constant=1,floor=0)
        r=rollout(s,4,None,seed=12,schedule=config)
        self.assertTrue(all(n['mode']=='exploratory' for n in r['rows']))
        for ch in ('outbound','market','ack','fill'):
            self.assertEqual(getattr(s.config,ch).probabilities,(.6,.3,.1))
        r=rollout(s,4,None,seed=12,schedule=config,greedy=True)
        self.assertTrue(all(n['mode']=='greedy' and n['exploration_probability']==0 for n in r['rows']))

    def test_invalid_schedules_rejected(self):
        for kwargs in [dict(mode='unknown'),dict(first=-.1),dict(last=.8),dict(round_decay=2),dict(floor=.2),dict(first=float('nan'))]:
            with self.assertRaises(ValueError):ExplorationSchedule(**kwargs)
        s=ExplorationSchedule()
        for args in [(-1,0,10),(0,10,10),(0,0,0)]:
            with self.assertRaises(ValueError):s.probability(*args)

if __name__=='__main__':unittest.main(verbosity=2)
