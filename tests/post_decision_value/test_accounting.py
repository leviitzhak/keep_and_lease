import unittest
from copy import deepcopy
from research.post_decision_value.accounting import Instrument,Ledger,Goal

class AccountingTests(unittest.TestCase):
    def test_fast_clone_matches_deepcopy_and_isolates_all_mutable_state(self):
        from dataclasses import asdict
        from research.post_decision_value.accounting import Cashflow
        p=Ledger({'BTC':2.,'USD':100000.},credit_limit=2000)
        p.fill(self.linear,.1,100000);p.fill(self.inverse,-1000,100000)
        p.borrow(1000,1500,10);p.pledge('USD',100)
        p.flows.append(Cashflow('coupon',500,'USD',5,'treasury'));p.settled_ids.append('old')
        a,b=p.clone(),deepcopy(p)
        self.assertEqual(asdict(a),asdict(b))
        for price in (50000,100000,200000):
            self.assertEqual(a.funding_headroom(self.ins,price,2000),b.funding_headroom(self.ins,price,2000))
        a.balances['USD']+=1;a.positions['L'].basis+=1;a.flows[0].amount-=1
        a.collateral['USD']+=1;a.fees['USD']+=1;a.settled_ids.append('new')
        self.assertEqual(asdict(p),asdict(b))
    def setUp(self):
        self.linear=Instrument('L',1000,fee_bps=0)
        self.inverse=Instrument('I',2000,'inverse',lot=10,fee_bps=0)
        self.ins={'L':self.linear,'I':self.inverse}
    def test_funded_long_not_double_counted(self):
        p=Ledger({'BTC':0.,'USD':100000.});p.fill(self.linear,1,100000)
        self.assertEqual(p.holdings(self.ins),{'BTC':1.,'USD':0.})
    def test_linear_repeated_variation(self):
        p=Ledger({'BTC':1.,'USD':100000.});p.fill(self.linear,.1,100000)
        before=p.holdings(self.ins)
        p.variation(self.linear,110000);p.variation(self.linear,90000);p.variation(self.linear,120000)
        self.assertEqual(before,p.holdings(self.ins));self.assertAlmostEqual(p.balances['USD'],102000)
        p.fill(self.linear,-.1,120000);self.assertEqual(p.positions,{})
        self.assertAlmostEqual(p.balances['USD'],102000)
    def test_inverse_repeated_settlement_identity(self):
        p=Ledger({'BTC':2.,'USD':100000.});p.fill(self.inverse,10000,100000)
        before=p.holdings(self.ins)
        for price in (120000,80000,110000):p.variation(self.inverse,price)
        self.assertAlmostEqual(p.holdings(self.ins)['BTC'],before['BTC'])
        p.fill(self.inverse,-10000,110000)
        self.assertAlmostEqual(p.balances['BTC'],2+10000*(1/100000-1/110000))
    def test_short_and_sign_flip(self):
        p=Ledger({'BTC':1.,'USD':100000.});p.fill(self.linear,-.1,100000);p.fill(self.linear,.2,90000)
        self.assertAlmostEqual(p.balances['USD'],101000)
        self.assertAlmostEqual(p.positions['L'].quantity,.1);self.assertEqual(p.positions['L'].basis,90000)
    def test_inverse_harmonic_basis(self):
        p=Ledger({'BTC':1.,'USD':100000.});p.fill(self.inverse,100,100);p.fill(self.inverse,100,200)
        self.assertAlmostEqual(p.positions['I'].basis,200/1.5)
    def test_borrow_and_collateral_never_create_wealth(self):
        p=Ledger({'BTC':1.,'USD':100000.},credit_limit=10000)
        before=p.holdings(self.ins);p.pledge('USD',1000);self.assertEqual(before,p.holdings(self.ins))
        p.borrow(1000,500);self.assertEqual(before,p.holdings(self.ins))
        p.borrow(1000,500,10);self.assertEqual(p.holdings(self.ins)['USD'],99990)
        with self.assertRaises(ValueError):p.borrow(9000,500)
    def test_treasury_receipts_counted_once(self):
        p=Ledger({'BTC':1.,'USD':100000.})
        with self.assertRaises(ValueError):p.buy_treasury('t',990,[(500,10),(1000,1010)])
        p.buy_treasury('t',990,[(500,10),(1000,1010)],enabled=True)
        self.assertEqual(p.holdings(self.ins)['USD'],100030)
        p.resolve_cashflows(500);p.resolve_cashflows(1000);p.resolve_cashflows(1000)
        self.assertEqual(p.balances['USD'],100030);self.assertEqual(len(p.settled_ids),2)
    def test_bridges_and_basis_risk(self):
        for ins in (self.linear,self.inverse):
            p=Ledger({'BTC':1.,'USD':100000.});q=.1 if ins.payoff=='linear' else 10000
            p.fill(ins,q,100000);before=p.holdings(self.ins)
            with self.assertRaises(ValueError):p.bridge(ins,120000,120000,observed=False)
            p.bridge(ins,120000,120000,observed=True)
            for c in before:self.assertAlmostEqual(before[c],p.holdings(self.ins)[c])
        p=Ledger({'BTC':1.,'USD':100000.});p.fill(self.linear,.1,100000);p.bridge(self.linear,120000,121000,observed=True)
        self.assertAlmostEqual(p.balances['USD'],89900)
    def test_cross_expiry_net_exposure_is_not_funding(self):
        a=Instrument('a',1000,fee_bps=0);b=Instrument('b',2000,fee_bps=0)
        p=Ledger({'BTC':1.,'USD':100.});p.fill(a,1,1000);p.fill(b,-1,1010)
        self.assertEqual(p.holdings({'a':a,'b':b})['USD'],110.)
        self.assertLess(p.funding_headroom({'a':a,'b':b},1000,2000),0)
    def test_resolution_must_cover_claims(self):
        p=Ledger({'BTC':1.,'USD':100000.});p.fill(self.linear,.1,100000)
        self.assertLess(p.funding_headroom(self.ins,100000,999),0)
    def test_floor_boundary_initial_not_high_water(self):
        g=Goal({'BTC':1.,'USD':100000.},100,1000)
        self.assertEqual(g.headroom({'BTC':.9,'USD':90000}),{'BTC':0.,'USD':0.})
        self.assertLess(g.headroom({'BTC':.899,'USD':90000})['BTC'],0)
    def test_zero_initial_and_btc_goal(self):
        with self.assertRaises(ValueError):Goal({'BTC':1.,'USD':0.},100,1000)
        g=Goal({'BTC':1.,'USD':0.},100,1000,absolute_floors={'USD':0},scales={'USD':1000},mode='btc')
        self.assertEqual(g.outcome({'BTC':1.01,'USD':0})['growth']['USD'],0)
    def test_target_necessary_wealth(self):
        g=Goal({'BTC':1.,'USD':100000.},100,1000,mode='target',tolerance=0.)
        self.assertEqual(g.required_target_value(),225000)
        self.assertFalse(g.composition(g.initial)[0])
        self.assertTrue(g.composition({'BTC':1.35,'USD':90000})[0])
    def test_expected_utility_not_utility_of_mean(self):
        g=Goal({'BTC':1.,'USD':100.},100,1000)
        a=g.outcome({'BTC':1.04,'USD':100.})['utility'];b=g.outcome({'BTC':1.,'USD':104.})['utility']
        self.assertEqual((a+b)/2,0.)
        self.assertAlmostEqual(g.outcome({'BTC':1.02,'USD':102.})['utility'],.02)
    def test_fee_once(self):
        ins=Instrument('F',1000,fee_bps=10)
        p=Ledger({'BTC':1.,'USD':100000.});p.fill(ins,.1,100000);p.variation(ins,110000)
        self.assertEqual(p.fees['USD'],10.)
        self.assertEqual(p.holdings({'F':ins})['USD'],89990.)
    def test_short_inverse_bridge_and_full_cross_expiry_bridge(self):
        p=Ledger({'BTC':2.,'USD':100000.});p.fill(self.inverse,-10000,100000)
        before=p.holdings(self.ins);p.bridge(self.inverse,80000,80000,observed=True)
        for c in before:self.assertAlmostEqual(p.balances[c],before[c])
        a=Instrument('a',1000,fee_bps=0);b=Instrument('b',2000,fee_bps=0);ins={'a':a,'b':b}
        p=Ledger({'BTC':1.,'USD':100000.});p.fill(a,.1,100000);p.fill(b,-.1,101000)
        before=p.holdings(ins);self.assertGreaterEqual(p.funding_headroom(ins,100000,2000),0)
        p.bridge(a,120000,120000,observed=True)
        self.assertAlmostEqual(p.balances['BTC'],1.1);self.assertAlmostEqual(p.balances['USD'],90000)
        p.bridge(b,80000,80000,observed=True)
        for c in before:self.assertAlmostEqual(p.balances[c],before[c])
    def test_per_commodity_floors_and_invalid_zero_basket(self):
        g=Goal({'BTC':1.,'USD':100000.},100,1000,drawdown={'BTC':.05,'USD':.2})
        self.assertEqual(g.floor('BTC'),.95);self.assertEqual(g.floor('USD'),80000)
        with self.assertRaises(ValueError):Goal({'BTC':0.,'USD':0.},100,1000,absolute_floors={'BTC':0,'USD':0},scales={'BTC':1,'USD':1})
