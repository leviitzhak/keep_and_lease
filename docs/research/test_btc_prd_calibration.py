"""Deterministic accounting and causal execution acceptance cases for research."""
import unittest
from btc_prd_execution_calibration import Experiment, Trade, DAY, YEAR, FACE
from btc_prd_pair_lots import Lot, weighted_prd, remove, replace_leg, ladder


class PairLotTests(unittest.TestCase):
    def test_short_replacement_uses_current_legs_not_completed_leg_credit(self):
        old = [Lot('entry', .2, .03, .05)]
        remaining, new = replace_leg(old, .2, 'short', .06, 'roll')
        self.assertEqual(remaining, [])
        self.assertIsNone(weighted_prd(remaining))
        self.assertAlmostEqual(weighted_prd(new), .03)
        # Buyback APR .04 is historical exit data, never changes current PRD.
        self.assertEqual(ladder(new,.035,.005,.1)['counted_quantity'], 0)
        self.assertAlmostEqual(old[0].prd,.02)  # immutable original

    def test_partial_long_roll_updates_both_pair_summaries(self):
        lots = [Lot('a', .1, .03, .05), Lot('b', .2, .02, .06)]
        remaining,new = replace_leg(lots,.15,'long',.01,'roll')
        self.assertAlmostEqual(sum(x.quantity for x in remaining),.15)
        self.assertAlmostEqual(weighted_prd(remaining),.04)
        self.assertAlmostEqual(weighted_prd(new),(.1*.04+.05*.05)/.15)
        self.assertAlmostEqual(sum(x.quantity for x in new),.15)

    def test_current_fill_rungs_and_closure_restore_lower_level(self):
        lots=[Lot('a',.1,0,.021),Lot('b',.1,0,.031)]
        before=ladder(lots,.02,.005,.1)
        self.assertAlmostEqual(before['next_threshold'],.03)
        remaining,_=remove(lots,.1)
        after=ladder(remaining,.02,.005,.1)
        self.assertAlmostEqual(after['next_threshold'],.025)
        self.assertAlmostEqual(after['counted_quantity'],.1)

    def test_quantity_cannot_qualify_from_aggregate_average(self):
        lots=[Lot('low',.1,0,.01),Lot('high',.1,0,.07)]
        result=ladder(lots,.02,.005,.1)
        self.assertAlmostEqual(weighted_prd(lots),.04)
        self.assertAlmostEqual(result['counted_quantity'],.1)
        self.assertAlmostEqual(result['unqualified_quantity'],.1)

    def test_fill_at_threshold_counts_and_unknown_never_invents_prd(self):
        lots=[Lot('a',.1,.03,.05),Lot('unknown',.1,None,.06)]
        self.assertIsNone(weighted_prd(lots))
        result=ladder(lots,.02,.005,.1)
        self.assertAlmostEqual(result['counted_quantity'],.1)
        self.assertAlmostEqual(result['owned_quantity'],.2)

    def test_repeated_replace_does_not_multiply_inventory(self):
        lots=[Lot('a',.2,.03,.05)]
        _,lots=replace_leg(lots,.2,'short',.06,'one')
        _,lots=replace_leg(lots,.2,'long',.02,'two')
        self.assertAlmostEqual(sum(x.quantity for x in lots),.2)
        self.assertAlmostEqual(weighted_prd(lots),.04)
        with self.assertRaises(ValueError): remove(lots,.3)


class ExecutionTests(unittest.TestCase):
    def row(self,t,p=10000.,s=10000.,direction='buy',amount=100.):
        return Trade(t,p,s,p,amount,direction,str(t))

    def engine(self,**kwargs):
        return Experiment(YEAR,0,DAY,.02,.01,**kwargs)

    def active(self,e,phase,limit,arrival=1000):
        e.phase=phase
        e.active=dict(key=(0,phase),limit=limit,arrival=arrival,decision=500,observed=0)

    def test_strict_through_and_opposite_aggressor_and_volume(self):
        e=self.engine()
        self.active(e,1,10200.)
        for r in [self.row(1001,10200.),self.row(1002,10202.5,direction='sell'),
                  self.row(1003,10202.5,amount=10.)]:
            e.fill(r)
            self.assertFalse(e.fills)
        e.fill(self.row(1004,10202.5))
        self.assertEqual(len(e.fills),1)
        self.assertEqual(e.fills[0]['price'],10200.)

    def test_buy_equality_rejected_fill_at_limit(self):
        e=self.engine()
        e.entry=10200.
        self.active(e,2,10100.)
        e.fill(self.row(1001,10100.,direction='sell'))
        self.assertFalse(e.fills)
        e.fill(self.row(1002,10097.5,direction='sell'))
        self.assertEqual(e.fills[0]['price'],10100.)
        expected=FACE*(1/10100.-1/10200.)*10000.-FACE/10100.*10000.*.0001
        self.assertAlmostEqual(e.cash,expected)

    def test_arrival_tie_and_no_retroactive_fill(self):
        e=self.engine()
        self.active(e,1,10200.)
        e.fill(self.row(1000,10300.))
        self.assertFalse(e.fills)
        e.fill(self.row(1001,10300.))
        self.assertEqual(len(e.fills),1)

    def test_two_latency_legs_and_postarrival_proxy_index(self):
        e=self.engine(band=None)
        e.run([self.row(0),self.row(1000,s=11000.),self.row(1001,s=12000.),
               self.row(1500,p=13000.,s=12000.),self.row(2001,p=13000.,s=12000.),
               self.row(2002,p=13000.,s=12000.)])
        buy=e.fills[0]
        self.assertEqual((buy['observed'],buy['decision'],buy['arrival'],buy['t']),
                         (0,500,1000,1001))
        self.assertEqual(buy['price'],12000.)
        short=e.fills[1]
        self.assertGreater(short['t'],buy['t']+1000)
        for f in e.fills:
            self.assertEqual(f['decision']-f['observed'],500)
            self.assertEqual(f['arrival']-f['decision'],500)
            self.assertGreater(f['t'],f['arrival'])

    def test_zero_delay_does_not_react_within_equal_timestamp_batch(self):
        e=self.engine(delay=0)
        e.run([self.row(0),self.row(0),self.row(1),self.row(1,p=11000.),
               self.row(2,p=11000.)])
        self.assertEqual([x['phase'] for x in e.fills],[0,1])
        self.assertEqual([x['t'] for x in e.fills],[1,2])

    def test_filled_identity_cannot_be_reopened_by_delayed_amendment(self):
        e=self.engine()
        self.active(e,1,10200.)
        old=dict(e.active,arrival=1003)
        e.enqueue(1003,'command',old)
        e.fill(self.row(1002,10300.))
        e.process(1004)
        self.assertIsNone(e.active)
        self.assertEqual(e.counts['obsolete_completed_order_commands'],1)

    def test_old_order_persists_without_arbitrary_age_expiry(self):
        e=self.engine()
        self.active(e,1,10200.)
        e.fill(self.row(12*3600000,10300.))
        self.assertEqual(len(e.fills),1)

    def test_passive_band_includes_marketable_limits(self):
        e=self.engine(band=.01)
        e.decision(500,self.row(0,p=11000.),(0,1))
        self.assertIsNotNone(e.queue[0][3]['limit'])
        e2=self.engine(band=.01)
        e2.decision(500,self.row(0,p=9000.),(0,1))
        self.assertIsNone(e2.queue[0][3]['limit'])

    def test_unfinished_proxy_and_short_are_marked_not_discarded(self):
        e=self.engine()
        result=e.run([self.row(0),self.row(1001),self.row(2002,p=10300.),
                      self.row(3003,p=10400.,s=10100.)])
        self.assertEqual(result['completed_cycles'],0)
        self.assertEqual(result['remaining_short_face'],10)
        self.assertGreater(result['remaining_proxy_btc'],0)
        self.assertAlmostEqual(result['net_marked_usd_per_10_face'],
                               result['unfinished_net_marked_usd'])

    def test_opening_boundary_and_retirement_test_is_not_faked(self):
        e=self.engine()
        self.active(e,1,10200.)
        e.fill(self.row(e.cutoff,10300.))
        self.assertFalse(e.fills)



class ExtendedAccountingTests(unittest.TestCase):
    def test_one_year_proxy_expense_is_charged_once(self):
        e=Experiment(3*YEAR,0,YEAR,.02,.01,proxy_expense=.02,fee_bp=0)
        e.proxy=e.proxy_original=.001;e.proxy_cost=10;e.proxy_bought=0
        e.cash=e.cycle_cash=-10;e.phase=1
        result=e.run([Trade(0,10000,10000,10000,100,'buy','a')])
        self.assertAlmostEqual(e.proxy_apr,.02/.98)
        self.assertAlmostEqual(result['net_marked_usd_per_10_face'],-.2)
        self.assertAlmostEqual(result['unrealized_proxy_expense_effect_usd'],-.2)
        self.assertAlmostEqual(result['unfinished_cycle_realized_net_usd'],0)

    def test_fee_only_repricing_matches_a_fresh_replay_and_no_proxy_rebate(self):
        from btc_prd_full_history import fee_sensitivity,audit_fills
        rows=[Trade(t,p,10000,p,100,d,str(t)) for t,p,d in
              [(0,10000,'buy'),(1001,10000,'buy'),(2002,10300,'buy'),
               (3003,10000,'sell'),(4004,10000,'sell'),(5005,10000,'buy'),(6006,10300,'buy')]]
        a=Experiment(YEAR,0,DAY,.02,.01,band=None);base=a.run(rows)
        self.assertGreater(base['completed_cycles'],0)
        audit_fills(a,rows,base)
        b=Experiment(YEAR,0,DAY,.02,.01,future_fee_bp=-1,proxy_fee_bp=0,band=None);fresh=b.run(rows)
        derived=fee_sensitivity(base,a.fills,-1,0)
        for key in ('net_marked_usd_per_10_face','completed_cycle_realized_net_usd',
                    'unfinished_cycle_realized_net_usd','unrealized_mark_net_usd'):
            self.assertAlmostEqual(fresh[key],derived[key])
        self.assertTrue(all(f['fee_usd']==0 for f in b.fills if f['phase'] in (0,3)))
        self.assertTrue(all(f['fee_usd']<0 for f in b.fills if f['phase'] in (1,2)))

    def test_closed_future_in_unfinished_cycle_is_realized(self):
        rows=[Trade(t,p,10000,p,100,d,str(t)) for t,p,d in
              [(0,10000,'buy'),(1001,10000,'buy'),(2002,10300,'buy'),(3003,10000,'sell')]]
        e=Experiment(YEAR,0,DAY,.02,.01,band=None);r=e.run(rows)
        self.assertEqual(r['unfinished_phase'],3)
        self.assertGreater(r['unfinished_cycle_future_realized_usd'],0)
        self.assertEqual(r['unrealized_future_usd'],0)
        self.assertAlmostEqual(r['net_marked_usd_per_10_face'],r['completed_cycle_realized_net_usd']+
                               r['unfinished_cycle_realized_net_usd']+r['unrealized_mark_net_usd'])

    def test_one_ms_remains_two_distinct_latency_legs(self):
        rows=[Trade(t,11000,10000,11000,100,'buy',str(t)) for t in range(10)]
        e=Experiment(YEAR,0,DAY,.02,.01,delay=1);e.run(rows)
        self.assertGreater(len(e.fills),0)
        for f in e.fills:
            self.assertEqual(f['decision']-f['observed'],1)
            self.assertEqual(f['arrival']-f['decision'],1)
            self.assertGreater(f['t'],f['arrival'])


class HistoricalTapeTests(unittest.TestCase):
    def test_missing_marks_retained_but_invalid_index_and_backdated_print_excluded(self):
        import tempfile,json,gzip,hashlib
        from pathlib import Path
        from btc_prd_full_history import Archive,load_contract,JOB,PREFIX
        with tempfile.TemporaryDirectory() as tmp:
            a=Archive(tmp,offline=True)
            raw=[dict(timestamp=t,price=100,index_price=index,mark_price=None,
                      amount=10,direction='buy',instrument_name='BTC-TEST',trade_seq=i,trade_id=str(i))
                 for i,(t,index) in enumerate([(1000,100),(999,100),(1500,0),(2000,100)],1)]
            b=gzip.compress(b''.join((json.dumps(x)+'\n').encode() for x in raw),mtime=0)
            key=PREFIX+'/objects/example/trades.jsonl.gz';path=Path(tmp)/key;path.parent.mkdir(parents=True);path.write_bytes(b)
            receipt=dict(status='COMPLETE',instrument='BTC-TEST',first_seq=1,last_seq=4,rows=4,
                         min_timestamp=999,max_timestamp=2000,
                         objects=[dict(key=key,bytes=len(b),sha256=hashlib.sha256(b).hexdigest())])
            path=Path(tmp)/f'{JOB}/receipts/BTC-TEST/000000000001-000000000004.json'
            path.parent.mkdir(parents=True);path.write_text(json.dumps(receipt))
            rows,counts,_=load_contract(a,dict(instrument='BTC-TEST',first_available_seq=1,last_available_seq=4),5000)
            self.assertEqual([r.id for r in rows],['1','4'])
            self.assertEqual([r.mark for r in rows],[100,100])
            self.assertEqual(counts['backdated_excluded'],1)
            self.assertEqual(counts['invalid_numeric_excluded'],1)
            self.assertEqual(counts['mark_missing_or_invalid_trade_price_fallback'],2)

if __name__ == "__main__":
    unittest.main()
