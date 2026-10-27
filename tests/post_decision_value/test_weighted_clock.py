from copy import deepcopy
from dataclasses import asdict
import tempfile
import unittest
import torch

from research.post_decision_value.accounting import Instrument, Ledger, Goal
from research.post_decision_value.engine import Engine, Trade, Order, Instruction, Delays
from research.post_decision_value.decision_clock import DecisionSchedule
from research.post_decision_value.checkpoint import DirectoryCheckpoints, save_engine, restore_engine
from research.post_decision_value.model import ValueNetwork, features, labels, fit
from research.post_decision_value.pilot import continuation_identity, Budget, episode


def engine(delays=None):
    ins={'S':Instrument('S',10**15,payoff='spot',source_payoff='spot',tick=1,lot=.001,fee_bps=0)}
    goal=Goal({'BTC':1.,'USD':100000.},1000,1000,mode='weighted_growth')
    e=Engine(ins,Ledger(goal.initial.copy()),goal,1,delays or Delays(0,0,0,0,0,0),participation=1)
    e.seed_market([Trade(-1000,'S',100000,100,'buy','seed',100000,'spot')],0)
    return e


def collect(e,mode='event',trigger=None):
    schedule=DecisionSchedule(e,e.goal.horizon,mode=mode,cadence_ms=100,trigger=trigger or dict(min_gap_ms=20,max_wait_ms=300))
    times=[]
    for t,reasons in schedule:
        times.append((t,reasons));e.submit(Instruction());schedule.accept()
    e.advance(e.goal.horizon)
    return times


class WeightedTests(unittest.TestCase):
    def test_weighted_reward_penalizes_each_negative_even_zero_weight(self):
        g=Goal({'BTC':1.,'USD':100.},1,2,mode='weighted_growth',growth_weights={'BTC':.7,'USD':.3},loss_aversion=10)
        self.assertAlmostEqual(g.outcome({'BTC':1.1,'USD':120.})['utility'],.13)
        self.assertAlmostEqual(g.outcome({'BTC':1.1,'USD':99.})['utility'],-.03)
        self.assertAlmostEqual(g.outcome({'BTC':.99,'USD':99.})['utility'],-.2)
        g.growth_weights={'BTC':1.,'USD':0.}
        self.assertAlmostEqual(g.outcome({'BTC':1.,'USD':99.})['utility'],-.1)
        self.assertAlmostEqual(g.outcome({'BTC':1.1,'USD':100.},True)['utility'],-.9)

    def test_continuous_boundary_and_monotonicity(self):
        g=engine().goal
        for eps in (1e-3,1e-6,1e-9):
            center=g.outcome({'BTC':1.05,'USD':100000})['utility']
            low=g.outcome({'BTC':1.05,'USD':100000*(1-eps)})['utility']
            high=g.outcome({'BTC':1.05,'USD':100000*(1+eps)})['utility']
            self.assertLess(low,center);self.assertGreater(high,center)
            self.assertAlmostEqual(center-low,10*eps,places=10)
            self.assertAlmostEqual(high-center,.5*eps,places=10)

    def test_invalid_parameters_and_mixed_labels(self):
        for kw in [dict(loss_aversion=0),dict(loss_aversion=float('nan')),dict(growth_weights={'BTC':1.,'USD':1.})]:
            with self.assertRaises(ValueError):Goal({'BTC':1.,'USD':100.},1,2,mode='weighted_growth',**kw)
        e=engine();e.advance(1000);out=e.outcome();records=[dict(outcome=out,continuation='same')]
        other=deepcopy(records[0]);other['outcome']['objective_parameters']['loss_aversion']=20
        with self.assertRaisesRegex(ValueError,'Mixed objective parameters'):labels(records+[other])

    def test_new_features_labels_and_real_torch_fit(self):
        torch.set_num_threads(1);e=engine();f=features(e.observe(),e.goal,e.instruments)
        self.assertEqual(f['schema_version'],3);self.assertEqual(len(f['global_']),39)
        e.goal.loss_aversion=100;self.assertNotEqual(f,features(e.observe(),e.goal,e.instruments));e.advance(1000)
        records=[dict(features=features(e.observe(),e.goal,e.instruments),outcome=e.outcome(),continuation='hold')]
        m=ValueNetwork(feature_version=3);self.assertEqual(sum(p.numel() for p in m.parameters()),88901)
        _,_,info=fit(m,records,updates=2);self.assertEqual(info['updates'],2)
        self.assertEqual(len(m.predict([records[0]['features']])['objective']),1)

    def test_policy_identity_changes_with_weights_lambda_or_clock(self):
        config=dict(goal_mode='weighted_growth',growth_weights={'BTC':.5,'USD':.5},loss_aversion=10,feature_version=3)
        base=continuation_identity('hold',config)
        for k,v in [('growth_weights',{'BTC':.9,'USD':.1}),('loss_aversion',20),('decision_clock','event')]:
            self.assertNotEqual(base,continuation_identity('hold',{**config,k:v}))
        self.assertNotEqual(continuation_identity('hold',{**config,'cadence_ms':500}),continuation_identity('hold',{**config,'cadence_ms':1000}))


class ClockTests(unittest.TestCase):
    def test_quiet_tape_coalesces_decisions_but_processes_every_event(self):
        tape=[Trade(t,'S',100000,10,'buy',str(t),100000,'spot') for t in range(10,1000,10)]
        a,b=engine(),engine();a.add_tape(tape);b.add_tape(tape)
        event=collect(a);fixed=collect(b,'fixed')
        self.assertEqual([t for t,_ in event],[0,300,600,900]);self.assertEqual(len(fixed),10)
        self.assertEqual(a.hidden.processed,b.hidden.processed);self.assertEqual(a.outcome(),b.outcome())

    def test_future_and_hidden_arrival_never_wake_before_received_observation(self):
        e=engine(Delays(50,0,0,0,0,0))
        e.add_tape([Trade(10,'S',100100,10,'buy','changed',100000,'spot')])
        times=collect(e);self.assertEqual(times[1][0],60);self.assertIn('price_change',times[1][1])

    def test_cumulative_changes_and_debounce(self):
        e=engine();e.add_tape([Trade(t,'S',p,10,'buy',str(t),100000,'spot') for t,p in [(10,100015),(15,100030),(40,100035)]])
        times=collect(e);self.assertEqual(times[1][0],20);self.assertNotIn(40,[t for t,_ in times])

    def test_premium_trigger_can_fire_below_price_threshold(self):
        e=engine();e.instruments={'F':Instrument('F',10000,fee_bps=0)}
        e.observable.market={};e.observable.history=[]
        e.seed_market([Trade(-1000,'F',105000,100,'buy','seed-f',100000)],0)
        e.add_tape([Trade(100,'F',105000,100,'buy','premium-change',100010)])
        times=collect(e,trigger=dict(min_gap_ms=20,max_wait_ms=300,price_bps=2.,premium_bps=.5))
        self.assertEqual(times[1][0],100);self.assertEqual(times[1][1],['premium_change'])

    def test_fixed_clock_resume_does_not_repeat_accepted_tick(self):
        e=engine();s=DecisionSchedule(e,1000,cadence_ms=100,trigger=dict(min_gap_ms=20,max_wait_ms=300));it=iter(s)
        self.assertEqual(next(it)[0],0);e.submit(Instruction());s.accept()
        self.assertEqual([t for t,_ in collect(e,'fixed')],list(range(100,1000,100)))

    def test_report_and_partial_fill_changes_are_observed_only_after_delay(self):
        e=engine(Delays(0,0,0,100,0,0));schedule=DecisionSchedule(e,1000,mode='event',trigger=dict(min_gap_ms=20,max_wait_ms=300))
        times=[]
        e.add_tape([Trade(10,'S',100001,.001,'buy','fill',100000,'spot')])
        for t,reasons in schedule:
            times.append((t,reasons))
            e.submit(Instruction('create',(Order('sell','S',-.002,100000),)) if t==0 else Instruction())
            schedule.accept()
        self.assertNotIn(10,[t for t,_ in times]);self.assertEqual(times[1][0],100)
        self.assertIn('account_or_order_report',times[1][1])
        self.assertEqual(times[2][0],120)  # fill report at 110, debounced from ack decision
        self.assertIn('account_or_order_report',times[2][1])

    def test_known_cashflow_wakes_without_seeing_hidden_receipt(self):
        e=engine(Delays(0,0,0,100,0,0));ins=Instrument('T',250,payoff='treasury',source_payoff='treasury',cashflows=((250,100.),),fee_bps=0)
        e.instruments['T']=ins;e.hidden.ledger.fill(ins,1,99);e.observable.ledger.fill(ins,1,99)
        e._event(250,-1,'asset_cashflow','T')
        schedule=DecisionSchedule(e,1000,mode='event',trigger=dict(min_gap_ms=20,max_wait_ms=300));observed=[]
        for t,reasons in schedule:
            observed.append((t,reasons,e.observe().ledger.balances['USD']))
            e.submit(Instruction());schedule.accept()
        at=[r for r in observed if r[0]==250][0]
        self.assertIn('known_cashflow_or_deadline',at[1]);self.assertEqual(at[2],99901)
        self.assertEqual([r[2] for r in observed if r[0]==350],[100001])

    def test_clock_checkpoint_resumes_same_decisions_and_rejects_other_config(self):
        a=engine();a.add_tape([Trade(180,'S',100100,10,'buy','change',100000,'spot')])
        schedule=DecisionSchedule(a,1000,mode='event',trigger=dict(min_gap_ms=20,max_wait_ms=300))
        iterator=iter(schedule);self.assertEqual(next(iterator)[0],0);a.submit(Instruction());schedule.accept()
        with tempfile.TemporaryDirectory() as d:
            store=DirectoryCheckpoints(d);save_engine(store,0,a,{'clock':'v1'});b=restore_engine(store,{'clock':'v1'})
            with self.assertRaisesRegex(ValueError,'resume configuration'):DecisionSchedule(b,1000,mode='event')
            rest=[]
            for t,why in iterator:rest.append((t,why));a.submit(Instruction());schedule.accept()
            a.advance(1000);self.assertEqual(rest,collect(b));self.assertEqual(a.outcome(),b.outcome())

    def test_pilot_episode_uses_trigger_and_hard_runtime_budget(self):
        e=engine();block=dict(start=0,end=1000,id='fixture',split='test',seeds=[Trade(-1000,'S',100000,10,'buy','seed',100000,'spot')],tape=[])
        config=dict(initial_btc=1.,initial_usd=100000.,reference_btc=100000.,goal_mode='weighted_growth',delays=asdict(Delays(0,0,0,0,0,0)),
                    participation=1,event_cap=1000,candidate_budget=32,action_space='grid',action_domain={},search_evaluations=4,
                    search_rounds=1,cadence_ms=100,decision_clock='event',trigger=dict(min_gap_ms=20,max_wait_ms=300),
                    pilot_seconds=30,transition_cap=100)
        rows,r=episode(block,e.instruments,1,'hold',config,Budget(config),retain=True)
        self.assertEqual(len(rows),4);self.assertTrue(r['outcome']['done']);self.assertEqual(r['outcome']['objective'],'weighted_growth')
        config['transition_cap']=1;rows,r=episode(block,e.instruments,1,'hold',config,Budget(config),retain=True)
        self.assertEqual(rows,[]);self.assertFalse(r['outcome']['done'])
