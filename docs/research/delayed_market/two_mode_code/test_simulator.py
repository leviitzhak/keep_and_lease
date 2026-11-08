"""Behavioral tests for delayed observation, ordering, history and causality."""
from dataclasses import replace
from pathlib import Path
import copy,json,unittest,random
import numpy as np
from simulator import Config,DelayLaw,Simulator,Action,HistoryValueNetwork,encode,feasible_actions,run_episode,diagnostic_policy

ZERO=DelayLaw((0,),(1.,))
ONE=DelayLaw((1,),(1.,))
THREE=DelayLaw((3,),(1.,))

def buy(sim,n):
    return next(a for a in feasible_actions(sim.observation()) if a.kind=='CREATE' and a.quantity==n)

class Observations(unittest.TestCase):
    def test_market_is_invisible_until_received(self):
        s=Simulator(Config(warmup_steps=0,market=THREE),intervals=[0])
        s.advance_to(3);self.assertIsNone(s.observation()['current']['latest_market'])
        self.assertEqual(feasible_actions(s.observation()),[Action()])
        s.advance_to(3.25);self.assertEqual(s.observation()['current']['latest_market']['source_tick'],1)
    def test_order_create_is_hidden_until_acknowledged(self):
        s=Simulator(Config(market=ZERO,ack=THREE,fill=THREE),{'outbound':[1]})
        s.submit(buy(s,4));s.advance_to(1)
        self.assertIsNotNone(s.active_order_id)
        self.assertEqual(s.observation()['current']['current_order']['status'],'SENT')
        self.assertIsNotNone(s.observation()['current']['pending_create'])
    def test_fill_changes_exchange_before_reported_portfolio(self):
        s=Simulator(Config(market=ZERO,ack=ONE,fill=THREE),{'outbound':[1]})
        a=buy(s,4);s.submit(a);s.advance_to(1.25)
        self.assertEqual(s.exchange_bills,2);self.assertEqual(s.reported_bills,0)
        self.assertEqual(s.reported_cash,32000);self.assertEqual(s.exchange_cash,32000-2*a.limit_ticks)
        s.advance_to(4.25);self.assertEqual(s.reported_bills,2)
    def test_fill_before_ack_promotes_known_order(self):
        s=Simulator(Config(market=ZERO,ack=THREE,fill=ONE),{'outbound':[1]})
        s.submit(buy(s,4));s.advance_to(2.25)
        self.assertIsNone(s.pending_create);self.assertEqual(s.reported_bills,2)
        self.assertEqual(s.observation()['current']['current_order']['status'],'PARTIAL')
        s.advance_to(4)
        self.assertEqual(s.reported_bills,4)
        self.assertFalse([p for p in s.private_history if p['kind']=='create_ack'][0]['applied'])
    def test_cumulative_reports_out_of_order_do_not_double_count(self):
        s=Simulator(Config(market=ZERO,ack=THREE),{'outbound':[1],'fill':[3,1]})
        a=buy(s,4);s.submit(a);s.advance_to(3.25)
        self.assertEqual(s.reported_bills,4)
        self.assertEqual(s.reported_cash,32000-4*a.limit_ticks)
        s.advance_to(4.25)
        self.assertEqual(s.reported_bills,4)
        stale=[p for p in s.private_history if p['kind']=='fill' and p['cumulative_filled']==2][0]
        self.assertFalse(stale['applied'])
    def test_duplicate_private_report_is_idempotent(self):
        s=Simulator(Config(market=ZERO,ack=ONE,fill=ONE),{'outbound':[1]})
        s.submit(buy(s,2));s.advance_to(3)
        before=(s.reported_cash,s.reported_bills)
        p=copy.deepcopy(s.private_history[-1]);s._receive_private(p)
        self.assertEqual((s.reported_cash,s.reported_bills),before)
        self.assertFalse(s.private_history[-1]['applied'])
    def test_cancel_race_accounts_for_unreported_fills(self):
        s=Simulator(Config(market=ZERO,ack=ONE,fill=THREE),{'outbound':[1,2]})
        a=buy(s,10);s.submit(a);s.advance_to(2);s.submit(Action('CANCEL'));s.advance_to(4)
        self.assertEqual(s.exchange_bills,6);self.assertIsNone(s.active_order_id)
        self.assertIsNotNone(s.pending_cancel)
        s.advance_to(5);self.assertIsNone(s.pending_cancel)
        self.assertEqual(s.reported_bills,6);self.assertEqual(s.reported_cash,32000-6*a.limit_ticks)
        s.advance_to(7);self.assertEqual(s.reported_bills,6)
        self.assertEqual(s.observation()['current']['reserved_cash'],0)
    def test_late_market_packet_kept_without_rewinding_latest(self):
        s=Simulator(Config(warmup_steps=0),{'market':[3,1]},intervals=[0])
        s.advance_to(1.75);self.assertEqual(s.latest_market['source_tick'],3)
        s.advance_to(3.25);self.assertEqual(s.latest_market['source_tick'],3)
        self.assertEqual(len(s.market_history),2);self.assertFalse(s.market_history[-1]['advances_latest'])
    def test_clones_preserve_existing_scheduled_messages(self):
        s=Simulator(Config(market=ZERO),{'outbound':[3]});s.submit(buy(s,2))
        c=s.clone();c.set_future_delays('outbound',[1])
        self.assertEqual(s.queue,c.queue)
        s.advance_to(2);c.advance_to(2);self.assertEqual(s.observation(),c.observation())
        self.assertIsNone(s.active_order_id);self.assertIsNone(c.active_order_id)
    def test_hidden_truth_and_unreceived_packets_do_not_change_network_input(self):
        s=Simulator(Config(market=ZERO,ack=THREE,fill=THREE),{'outbound':[1]})
        s.snapshot('before');s.submit(buy(s,4));s.snapshot('after');s.advance_to(1);s.snapshot('before')
        before=s.observation();c=s.clone()
        c.exchange_cash-=111;c.exchange_bills+=1
        # Alter a not-yet-delivered payload and delivery time, not any receipt.
        for i,e in enumerate(c.queue):
            if e[3]=='private':
                e=list(e);e[0]+=4;e[4]=dict(e[4],cumulative_filled=3);c.queue[i]=tuple(e);break
        after=c.observation()
        self.assertEqual(before,after)
        x=encode(before,10);self.assertTrue(np.array_equal(x,encode(after,10)))
        net=HistoryValueNetwork(len(x));self.assertEqual(net.predict(before,10),net.predict(after,10))
        self.assertEqual(feasible_actions(before),feasible_actions(after))
    def test_different_received_history_is_encoded_even_with_same_current_state(self):
        s=Simulator(Config(market=ZERO));s.snapshot('before');a=s.observation();b=copy.deepcopy(a)
        b['market_history'][0]['price_ticks']+=4
        self.assertEqual(a['current'],b['current']);self.assertFalse(np.array_equal(encode(a,10),encode(b,10)))
    def test_history_padding_has_explicit_zero_masks(self):
        s=Simulator();s.snapshot('before');obs=s.observation();x=encode(obs,10)
        self.assertEqual(x.size,1589)
        state=x[3:3+22*27].reshape(22,27)
        self.assertEqual(state[0,0],1);self.assertTrue(np.all(state[1:]==0))
    def test_invalid_future_message_in_encoder_is_rejected(self):
        s=Simulator();s.snapshot('before');obs=s.observation();obs['market_history'][0]['receive_tick']=99
        with self.assertRaises(AssertionError):encode(obs,10)
    def test_history_is_not_silently_truncated(self):
        s=Simulator();s.snapshot('before');obs=s.observation();obs['state_history']*=30
        with self.assertRaises(ValueError):encode(obs,10)
    def test_zero_delay_channels_reconcile_immediately(self):
        s=Simulator(Config(outbound=ZERO,market=ZERO,ack=ZERO,fill=ZERO));s.submit(buy(s,4))
        self.assertIsNone(s.pending_create);self.assertEqual(s.observation()['current']['current_order']['status'],'ACTIVE')
        s.advance_to(.25)
        self.assertEqual(s.exchange_cash,s.reported_cash);self.assertEqual(s.exchange_bills,s.reported_bills)
        self.assertEqual(s.reported_bills,2)
    def test_buy_reservation_protects_cash_and_inventory_before_ack(self):
        s=Simulator(Config(market=ZERO,ack=THREE,fill=THREE),{'outbound':[1]});a=buy(s,10);s.submit(a);s.advance_to(1.5)
        v=s.observation()['current']
        self.assertEqual(v['cap_available'],0);self.assertEqual(v['reserved_cash'],10*a.limit_ticks/32)
        self.assertEqual(feasible_actions(s.observation()),[Action()])
    def test_strict_touch_does_not_fill(self):
        # A received reference makes a buy limit 95.46875. Test print equal to it.
        s=Simulator(Config(market=ZERO,ack=ONE,fill=ONE),{'outbound':[1]});a=buy(s,2);s.submit(a);s.advance_to(1)
        tr=dict(trade_id='touch',source_tick=s.clock,price_ticks=a.limit_ticks,mid_ticks=a.limit_ticks+8,size=2,aggressor=-1)
        s._trade(tr);self.assertEqual(s.exchange_bills,0)
    def test_cap_100_is_configurable_without_imaginary_funding(self):
        s=Simulator(Config(cap=100,market=ZERO));self.assertEqual(max(a.quantity for a in feasible_actions(s.observation())),10)
        s=Simulator(Config(cap=100,initial_cash_ticks=320000,market=ZERO));self.assertEqual(max(a.quantity for a in feasible_actions(s.observation())),100)
    def test_actions_are_priced_from_received_market_data(self):
        s=Simulator(Config(market=THREE));s.advance_to(1);o=s.observation();a=buy(s,1)
        self.assertEqual(a.limit_ticks,o['current']['latest_market']['mid_ticks']+16)
        self.assertNotEqual(a.limit_ticks,s.config.initial_mid_ticks+s.clock+16)
    def test_delay_law_frequency(self):
        law=DelayLaw();rng=random.Random(44);draws=[law.draw(rng) for _ in range(20000)]
        for d,p in zip(law.values,law.probabilities):self.assertLess(abs(draws.count(d)/len(draws)-p),.015)
    def test_full_episode_prefixes_are_causal(self):
        s,decisions,x=run_episode()
        self.assertEqual(x.shape,(21,1589));self.assertEqual(len(s.state_history),21)
        for v in s.state_history:
            if v['latest_market']:self.assertLessEqual(v['latest_market']['receive_tick']/4,v['time'])
            for o in v['known_orders'].values():
                if o['last_receive_tick'] is not None:self.assertLessEqual(o['last_receive_tick']/4,v['time'])
    def test_many_random_delay_paths_reconcile_after_reports(self):
        for seed in range(100):
            s,ds,x=run_episode(Config(seed=seed))
            s.advance_to(24)
            self.assertEqual(s.reported_cash,s.exchange_cash);self.assertEqual(s.reported_bills,s.exchange_bills)
            actual=[e for e in s.audit if e['kind']=='fill_at_exchange']
            self.assertAlmostEqual(s.exchange_cash/32,1000-sum(e['signed_qty']*e['price'] for e in actual))
            self.assertEqual(s.exchange_bills,sum(e['signed_qty'] for e in actual))
    def test_received_history_cannot_be_mutated_by_policy(self):
        s=Simulator();o=s.observation();o['current']['reported_cash']=1;o['market_history'].clear()
        self.assertEqual(s.reported_cash,32000);self.assertGreater(len(s.market_history),0)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Observations)
    names=[t.id().split('.')[-1] for t in suite]
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests_run=result.testsRun,passed=result.wasSuccessful(),test_names=names,
                failures=[(str(t),msg) for t,msg in result.failures+result.errors],random_delay_episodes=100,
                training_run=False,network_input_size=1589)
    (Path(__file__).resolve().parent/'validation.json').write_text(json.dumps(report,indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
