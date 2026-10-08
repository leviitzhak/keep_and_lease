import unittest
from policies import PolicyReplay,YEAR

class PolicyTests(unittest.TestCase):
    def make(self,**kw):
        seeds={s:dict(instrument_name=s,timestamp=-1,trade_id=str(i),price=100000.,index_price=100000.,mark_price=100000.) for i,s in enumerate(['N','F'])}
        r=PolicyReplay(['N','F'],[YEAR,2*YEAR],seeds,0,100000,opposite_aggressor=False,**kw)
        r.queue.clear();r.timers.clear();return r
    def quote(self,price=100000,qty=100,total=1000,side=1):
        return dict(limit=price,qty=qty,total=total,observed=0,activation=500,index=100000.,
            reference_age_ms=1,generation=0,fill_watermark=0,index_age_ms=1,phase='target',side=side)
    def row(self,t=600,leg=0,price=99000,amount=100,direction='sell'):
        return dict(timestamp=t,instrument_name=['N','F'][leg],price=price,amount=amount,direction=direction,
            index_price=100000.,mark_price=price,trade_id=str(t),trade_seq=t)
    def lead(self,r,n=20):
        v=r.tasks[1];q=self.quote();v.active[0]=q
        r.fill(v,0,q,n,self.row());return v,q
    def test_leading_remainder_remains_fillable_until_cancel(self):
        r=self.make();v,q=self.lead(r)
        r.execute_print(self.row(t=900,amount=100))
        self.assertEqual(v.fills,[30,0]);self.assertEqual(v.episode['start_ms'],600)
        self.assertFalse(r.fills[0]['cancel_pending']);self.assertTrue(r.fills[1]['cancel_pending'])
        r.timer_event(1100,'cancel',(v.id,v.cancel_token))
        r.execute_print(self.row(t=1200,amount=100))
        self.assertEqual(v.fills,[30,0])
    def test_ack_includes_late_counterleg_and_sizes_exact_remainder(self):
        r=self.make();v,q=self.lead(r,n=20)
        far=self.quote(price=104000,qty=20,side=-1);v.active[1]=far
        r.fill(v,1,far,6,self.row(t=700,leg=1,price=105000,direction='buy'))
        r.fill(v,1,far,2,self.row(t=1000,leg=1,price=105000,direction='buy'))
        r.timer_event(1100,'cancel',(v.id,v.cancel_token));r.timer_event(1600,'ack',(v.id,v.cancel_token))
        rec=r.cancellations[0];self.assertEqual(rec['residual_contracts_at_ack'],12)
        self.assertEqual(rec['late_fill_contracts'],8)
        r.snapshot(1600)
        self.assertEqual(next(x[4]['qty'] for x in r.queue if x[2]==v.id and x[3]==1),12)
    def test_undo_open_conserves_inventory_and_pnl(self):
        r=self.make();v,q=self.lead(r,n=20)
        r.timer_event(1100,'cancel',(v.id,v.cancel_token));r.timer_event(1600,'ack',(v.id,v.cancel_token))
        undo=self.quote(price=99000,qty=20,side=-1);undo.update(observed=1600,activation=2100,phase='rescue',rescue_action='undo')
        r.fill(v,0,undo,20,self.row(t=2200,price=99025,direction='buy'),undo=True,price=99000)
        self.assertEqual(v.fills,[0,0]);self.assertEqual(r.pos,[0,0])
        expected=200*(1/100000-1/99000)
        self.assertAlmostEqual(r.cash,expected,14);self.assertAlmostEqual(r.realized,expected,14)
        self.assertEqual(r.cells[0]['opened'],0);self.assertEqual(len(r.matched),0)
    def test_undo_close_restores_inventory_without_new_pair(self):
        r=self.make();v,q=self.lead(r,n=20)
        far=self.quote(price=104000,qty=20,side=-1)
        r.fill(v,1,far,20,self.row(t=800,leg=1,price=105000,direction='buy'))
        z=r.tasks[r.cells[0]['close_ids'][0]];n=z.total
        cq=self.quote(price=101000,qty=n,side=-1)
        r.fill(z,0,cq,n,self.row(t=900,price=102000,direction='buy'))
        uq=self.quote(price=101100,qty=n,side=1);uq.update(phase='rescue',rescue_action='undo')
        r.fill(z,0,uq,n,self.row(t=1000,price=101000),undo=True,price=101100)
        self.assertEqual(z.fills,[0,0]);self.assertEqual(r.pos,[20,-20]);self.assertEqual(r.cells[0]['closed'],0)
        self.assertEqual(sum(r.tasks[x].total for x in r.cells[0]['close_ids']),20)
    def test_executed_anchor_does_not_expire(self):
        r=self.make(fresh_seconds=5);v,q=self.lead(r)
        r.index_time=10000
        self.assertTrue(r.fresh(v,10000));self.assertFalse(r.fresh(v,16000))
        other=r.tasks[3];self.assertFalse(r.fresh(other,10000))
    def test_relaxation_makes_lagging_limit_more_aggressive(self):
        for direction in [1,-1]:
            for kind in ['open','close']:
                for lead in [0,1]:
                    r=self.make(relax=True);v=r.tasks[1];v.kind=kind;v.direction=direction
                    r.cells[0]['direction']=direction;v.total=100
                    v.fills[lead]=10;v.anchor_apr=.05
                    r.episode_start(v,1000);r.index_time=6000
                    lag=1-lead;base=r.base_limit(v,lag,6000)[0]
                    r.snapshot(6000);q=next(x[4] for x in r.queue if x[2]==v.id and x[3]==lag)
                    self.assertGreater(v.side(lag)*(q['limit']-base),0)
                    self.assertEqual(q['concession_bp'],5)
    def test_timers_cancel_without_a_new_trade(self):
        r=self.make(fresh_seconds=5);v,q=self.lead(r)
        # Run no further market prints; cancellation and acknowledgment must run.
        r.run([])
        self.assertEqual(r.cancellations[0]['status'],'reconciled')
        self.assertEqual(r.cancellations[0]['ack_ms'],1600)
    def test_inflight_edit_deducts_intervening_fills(self):
        r=self.make();v,q=self.lead(r,n=20)
        later=self.quote(qty=30);later.update(observed=100,activation=600)
        r.queue.append((600,1,v.id,0,later));r.arrivals(700)
        self.assertEqual(v.active[0]['qty'],10)

if __name__=='__main__':unittest.main()
