import unittest,copy
from unittest.mock import patch
import numpy as np
import search,stochastic_delays as sd
from fast_exact import FastPathSimulator,assert_same
from network import Transformer

class StochasticTests(unittest.TestCase):
 def state(self):
  s=FastPathSimulator(search.Config(seed=111));s.snapshot('before')
  return search.transition(s,search.Action(),'random')[0]
 def test_execution_preserves_pending_assignments_and_rng(self):
  s=self.state();before=copy.deepcopy(s)
  with patch('search.feasible_actions',return_value=[search.Action()]):
   a,row=sd.step(s,10,Transformer(),np.random.default_rng(5),True)
  expected,_=search.transition(s,search.Action(),'random')
  assert_same(a,expected);assert_same(s,before)
  self.assertEqual(row['pending_reselections'],[])
 def test_action_selection_uses_mean_not_minimum(self):
  s=self.state();actions=search.feasible_actions(s.observation())[:2]
  # First action has larger mean but smaller minimum.
  with patch('search.feasible_actions',return_value=actions),patch.object(sd,'predict',return_value=np.array([0,10,10,10,6,6,6,6])):
   child,row=sd.step(s,10,None,np.random.default_rng(4),True)
  self.assertEqual(row['action_index'],0);self.assertEqual(row['expected_action_values'],[7.5,6.])
 def test_planning_seed_cannot_choose_execution_delays(self):
  s=self.state();out=[]
  for seed in [1,2,3]:
   with patch('search.feasible_actions',return_value=[search.Action()]):
    c,row=sd.step(s,10,None,np.random.default_rng(seed),True)
   out.append(c)
  for c in out[1:]:assert_same(c,out[0])
 def test_exploration_uses_simulator_law(self):
  s=self.state()
  with patch('search.feasible_actions',return_value=[search.Action()]):
   c,row=sd.step(s,10,None,np.random.default_rng(3),exploration=1)
  expected,_=search.transition(s,search.Action(),'random');assert_same(c,expected)

if __name__=='__main__':unittest.main()

class PlanningIsolationTests(unittest.TestCase):
 def test_rollout_search_does_not_use_execution_rng(self):
  import random
  s=FastPathSimulator(search.Config(seed=111));s.snapshot('before');other=s.clone()
  other.rng={ch:random.Random(999999) for ch in search.CHANNELS}
  original=search.step
  try:
   search.step=sd.step
   a=sd.rollout_search(s,2,Transformer(),count=2,seed=42)
   b=sd.rollout_search(other,2,Transformer(),count=2,seed=42)
   self.assertEqual([r['value'] for r in a['rollouts']],[r['value'] for r in b['rollouts']])
   self.assertEqual(a['winner'],b['winner'])
  finally:search.step=original
