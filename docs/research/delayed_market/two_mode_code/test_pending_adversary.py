import unittest,copy,itertools
from pathlib import Path
import numpy as np
import search,pending_adversary as pa
from fast_exact import FastPathSimulator,assert_same
from network import Transformer,predict

class PendingAdversaryTests(unittest.TestCase):
 def state(self):
  s=FastPathSimulator(search.Config(seed=111));s.snapshot('before');s,_=search.transition(s,search.Action(),'first');return s
 def test_pending_market_changes_next_history(self):
  s=self.state();group,choices=pa.successors(s,search.Action());self.assertEqual(len(choices),2)
  self.assertEqual([x['support'] for x in choices],[[1,2,3],[1,2,3]])
  self.assertEqual(len(group),4);self.assertEqual(len({search.key(x[0].observation()) for x in group}),4)
  # The previous algorithm enumerates nine NEW delays but freezes pending ones.
  self.assertEqual(len({search.key(c.observation()) for c,p in search.enumerate_successors(s,search.Action())}),1)
 def test_adversarial_minimum_not_first_pending_assignment(self):
  s=self.state();model=Transformer();group,_=pa.successors(s,search.Action());values=predict(model,[search.record(x[0].observation(),10) for x in group])
  self.assertLess(float(values.min()),float(values[0])-.01);self.assertNotEqual(int(np.argmin(values)),0)
 def test_grouping_matches_all_joint_pending_and_new_delays(self):
  s=self.state();model=Transformer()
  fast,rf=pa.step(s,10,model,np.random.default_rng(0),force_greedy=True,audit=True)
  slow,rs=pa.step(s,10,model,np.random.default_rng(0),force_greedy=True,audit=True,exhaustive=True)
  self.assertEqual(rf['action'],rs['action']);self.assertEqual(rf['minimum'],rs['minimum']);self.assertEqual(fast.observation(),slow.observation())
  self.assertEqual([(e[0],e[1],e[2],e[3],e[4]) for e in sorted(fast.queue)],[(e[0],e[1],e[2],e[3],e[4]) for e in sorted(slow.queue)])
  self.assertEqual([(r['event'],r['delay']) for r in fast.delay_draws],[(r['event'],r['delay']) for r in slow.delay_draws])
 def test_conditioning_allows_only_original_future_times(self):
  s=FastPathSimulator(search.Config());s.snapshot('before');action=search.feasible_actions(s.observation())[1]
  s,_=search.transition(s,action,'enumerate',(3,2,3));original=copy.deepcopy(s)
  choices=pa.pending_choices(s,False);outbound=next(x for x in choices if x['channel']=='outbound');self.assertEqual(outbound['support'],[2,3])
  for delays in itertools.product(*(x['support'] for x in choices)):
   c,audit=pa.assign_pending(s,choices,delays,'test')
   self.assertEqual(c.observation(),s.observation());self.assertEqual(c.exchange_orders,s.exchange_orders);self.assertEqual(c.exchange_cash,s.exchange_cash);self.assertEqual(c.exchange_bills,s.exchange_bills)
   for row in audit:
    self.assertGreater(row['chosen_arrival_time'],1);self.assertIn(row['chosen_delay'],[1,2,3]);self.assertEqual(row['chosen_arrival_time'],row['source_time']+row['chosen_delay'])
   assert_same(s,original)
 def test_already_delivered_and_completed_events_are_fixed(self):
  s=FastPathSimulator(search.Config());s.snapshot('before');buy=next(a for a in search.feasible_actions(s.observation()) if a.kind=='CREATE' and a.quantity==2)
  s,_=search.transition(s,buy,'first')
  for _ in range(3):s,_=search.transition(s,search.Action(),'first')
  self.assertGreater(s.reported_bills,0);history=copy.deepcopy(s.observation());orders=copy.deepcopy(s.exchange_orders);cash=s.exchange_cash;draws=copy.deepcopy(s.delay_draws)
  choices=pa.pending_choices(s,False);indices={x['draw_index'] for x in choices}
  for delays in itertools.product(*(x['options'] for x in choices)):
   c,audit=pa.assign_pending(s,choices,delays,'test');self.assertEqual(c.observation(),history);self.assertEqual(c.exchange_orders,orders);self.assertEqual(c.exchange_cash,cash)
   for i,r in enumerate(draws):
    if i not in indices:self.assertEqual(c.delay_draws[i],r)
 def test_exploratory_reselection_also_respects_history(self):
  s=self.state();original=copy.deepcopy(s)
  for seed in range(20):
   c,audit=pa.conditioned_random_pending(s,np.random.default_rng(seed));self.assertEqual(c.observation(),s.observation());assert_same(s,original)
 def test_every_retained_timestep_and_endpoint_available(self):
  import progressive
  from exploration import ExplorationSchedule
  s=FastPathSimulator(search.Config());s.snapshot('before')
  tr=progressive.lean_trajectory(s,3,Transformer(),881,2,ExplorationSchedule(),0)
  self.assertEqual([o['current']['time'] for o in tr['observations']],[0,1,2,3]);self.assertEqual(len(tr['rows']),3)

if __name__=='__main__':unittest.main()
