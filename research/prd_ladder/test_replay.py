import unittest
from replay import Replay,YEAR,split

class ModelTests(unittest.TestCase):
    def make(self):
        seeds={s:dict(instrument_name=s,timestamp=-1,trade_id=str(i),price=1000.,index_price=1000.,mark_price=1000.) for i,s in enumerate(['N','F'])}
        return Replay(['N','F'],[YEAR,2*YEAR],seeds,0,100000,async_cap_btc=.1)
    def row(self,t=600,leg=0,price=990,amount=100,direction='sell'):
        return dict(timestamp=t,instrument_name=['N','F'][leg],price=price,amount=amount,direction=direction,
                    index_price=1000.,mark_price=price,trade_id=str(t),trade_seq=t)
    def quote(self,price=1000,qty=10,total=10):
        return dict(limit=price,qty=qty,total=total,observed=0,activation=500,index=1000.,reference_age_ms=1,generation=0)
    def test_split_conservation_and_monotone(self):
        prev=[0]*6
        for n in range(1000):
            x=split(n);self.assertEqual(sum(x),n);self.assertLessEqual(max(x)-min(x),1)
            self.assertTrue(all(a>=b for a,b in zip(x,prev)));prev=x
    def test_strict_touch_and_arrival_excluded(self):
        r=self.make();v=r.tasks[1];q=self.quote()
        with self.assertRaises(AssertionError):r.fill(v,0,q,1,self.row(price=1000))
        r=self.make();v=r.tasks[1]
        with self.assertRaises(AssertionError):r.fill(v,0,self.quote(),1,self.row(t=500))
    def test_partial_pair_closing_reserves_exact_native_contracts(self):
        r=self.make();v=r.tasks[1];r.fill(v,0,self.quote(),3,self.row())
        self.assertEqual(r.permission(v,0),0);self.assertEqual(r.permission(v,1),3)
        q=self.quote(price=1030,qty=3);q.update(observed=600,activation=1100)
        r.fill(v,1,q,2,self.row(t=1200,leg=1,price=1040,direction='buy'))
        c=r.cells[0];self.assertEqual(c['opened'],2)
        self.assertEqual(sum(r.tasks[x].total for x in c['close_ids']),2)
        self.assertEqual(r.permission(v,1),1)
        self.assertNotIn(2,r.tasks) # mirrored order cannot reserve a second cell
    def test_inverse_pnl_exact_contract_roundtrip(self):
        r=self.make();v=r.tasks[1];r.fill(v,0,self.quote(),10,self.row())
        q=self.quote(price=1030);q.update(observed=600,activation=1100)
        r.fill(v,1,q,10,self.row(t=1200,leg=1,price=1040,direction='buy'))
        c=r.cells[0]
        for tid in list(c['close_ids']):
            z=r.tasks[tid];n=z.total
            q=self.quote(price=1010,qty=n,total=n);q.update(observed=1200,activation=1700)
            r.fill(z,0,q,n,self.row(t=1800,price=1020,direction='buy'))
            q=self.quote(price=1020,qty=n,total=n);q.update(observed=1800,activation=2300)
            r.fill(z,1,q,n,self.row(t=2400,leg=1,price=1010,direction='sell'))
        expected=100*(1/1000-1/1010-1/1030+1/1020)
        self.assertAlmostEqual(r.cash,expected,14);self.assertEqual(r.pos,[0,0])
        self.assertEqual(len(r.cycles),1);self.assertEqual(r.cells[0]['direction'],0)
    def test_print_shared_across_levels(self):
        r=self.make();r.queue.clear()
        for tid in [1,3]:
            v=r.tasks[tid];v.active[0]=self.quote()
        r.run([self.row(amount=30)])
        self.assertEqual(sum(f['contracts'] for f in r.fills),3)
    def test_self_cross_rejected_at_arrival(self):
        r=self.make();r.queue.clear()
        # Buy near and reversed sell near would cross; preserve the resting buy.
        r.tasks[1].active[0]=self.quote(price=1000)
        q=self.quote(price=995)
        r.queue.append((500,999,2,0,q));r.arrivals(600)
        self.assertNotIn(0,r.tasks[2].active)
        self.assertEqual(r.counts['self_cross_quote_rejections'],1)
    def test_default_async_chunk_cap(self):
        r=self.make();r.async_cap_btc=.02;r.queue.clear()
        for v in r.tasks.values():v.requested.clear()
        r.snapshot(0);r.arrivals(600)
        for v in r.tasks.values():
            for q in v.active.values():self.assertLessEqual(q['qty']*10/q['limit'],.02+1e-12)
        v=r.tasks[1]
        with self.assertRaises(AssertionError):r.fill(v,0,self.quote(),3,self.row())
    def test_matched_apr_is_actual_and_excludes_unmatched(self):
        r=self.make();v=r.tasks[1];r.fill(v,0,self.quote(),3,self.row())
        self.assertEqual(len(r.matched),0);self.assertEqual(r.prd_stats['sold'][0],0)
        q=self.quote(price=1030,qty=3);q.update(observed=600,activation=1100)
        r.fill(v,1,q,2,self.row(t=1200,leg=1,price=1040,direction='buy'))
        self.assertEqual(len(r.matched),1);m=r.matched[0]
        self.assertEqual(m['contracts'],2);self.assertAlmostEqual(m['near_apr_pp'],0)
        self.assertAlmostEqual(m['actual_prd_pp'],(1.03-1)/((2*YEAR-1200)/YEAR)*100)
        self.assertEqual(m['spread_side'],'sold');self.assertEqual(r.prd_stats['sold'][0],2)

if __name__=='__main__':unittest.main()
