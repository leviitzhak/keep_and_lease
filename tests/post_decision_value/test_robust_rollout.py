from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from research.post_decision_value.accounting import Cashflow, Goal, Instrument, Ledger, Position
from research.post_decision_value.checkpoint import pack
from research.post_decision_value.engine import Delays, Engine, Instruction, Order, Trade, admissible
from research.post_decision_value.liquidation import ClosingRule, horizon_support, liquidate
from research.post_decision_value.robust_rollout import CampaignBudget, Controller, TARGET_VERSION, collect_post_state, reduce_matrix, rollout
from research.post_decision_value.treasury_fixtures import accept_anchor, action_provider, finite_toy_optimum, fixture_engine, hold_reference, make_cases, scenario_set, DAY
from research.post_decision_value.treasury_model import TreasuryValue, encode, load_scalar, save_scalar, tensors
from research.post_decision_value.treasury_learning import collect_cases, validate_config


def config():
    return json.loads(Path('research/post_decision_value/treasury_learning_config.json').read_text())


class ZeroModel:
    def predict(self, fs):
        return np.zeros(len(fs))

    def fingerprint(self):
        return 'fixed-zero-test-controller'


class RobustTests(unittest.TestCase):
    def setUp(self):
        self.c = config()
        self.case = make_cases('train', self.c)[0]
        self.budget = CampaignBudget(self.c['limits'])

    def engine(self):
        return fixture_engine(self.case, self.c)

    def scenarios(self):
        return scenario_set(self.case, self.c['scenario_seeds'], self.c, 'test')

    def owned(self, quantity=25):
        e = self.engine()
        for ledger in (e.hidden.ledger, e.observable.ledger):
            ledger.fill(e.instruments['BILL'], quantity, self.case['price'])
        return e

    def test_plus_minus_actions_versus_random_outcomes_and_downward_correction(self):
        o = lambda v: dict(done=True, truncated=False, utility=v)
        self.assertEqual(reduce_matrix([[o(1)], [o(-1)]])['target'], 1)
        self.assertEqual(reduce_matrix([[o(1), o(-1)]])['target'], -1)
        self.assertLess(reduce_matrix([[o(1), o(-1)]])['target'], reduce_matrix([[o(1)]])['target'])
        self.assertEqual(reduce_matrix([[o(-2)], [o(-1)]])['target'], -1)

    def test_joint_outcome_not_independent_currency_minima(self):
        a = dict(done=True, truncated=False, utility=200., balances={'A':90, 'B':110})
        b = dict(done=True, truncated=False, utility=200., balances={'A':110, 'B':90})
        result = reduce_matrix([[a, b]])
        self.assertEqual(result['joint_outcome']['balances'], a['balances'])
        self.assertEqual(result['target'], 200.)

    def test_incomplete_adverse_replica_blocks_label_and_unequal_k_rejected(self):
        o = dict(done=True, truncated=False, utility=1.)
        self.assertFalse(reduce_matrix([[o, dict(done=False)]])['done'])
        with self.assertRaises(ValueError):
            reduce_matrix([[o], [o, o]])

    def test_sequential_partial_closing_and_independent_cash_accounting(self):
        e = self.owned(25); start = e.now
        tape = [Trade(start+1, 'BILL', 98, 10, 'buy', 'a', 100000, 'treasury'),
                Trade(start+2, 'BILL', 97, 15, 'buy', 'b', 100000, 'treasury')]
        result = liquidate(e, tape, start+100, ClosingRule(100, 10, 1))
        fee = self.case['fee_bps']/10000
        expected = 10000-25*self.case['price']*(1+fee)+(10*98+15*97)*(1-fee)
        self.assertTrue(result['done'])
        self.assertAlmostEqual(result['balances']['USD'], expected)
        self.assertEqual([r['quantity'] for r in result['trace']], [-10, -15])
        self.assertEqual(e.hidden.ledger.positions['BILL'].quantity, 25)

    def test_atomic_cancel_preserves_parent_and_no_pending_instruction_fills(self):
        e = self.engine()
        e.submit(Instruction('create', (Order('x', 'BILL', 25, self.case['price']),)))
        before = deepcopy(pack(e.__dict__))
        r = liquidate(e, self.scenarios()[0]['trades'], self.case['label_end'])
        self.assertEqual(r['utility'], 0)
        self.assertEqual(r['cancelled_pending'], ['request-0'])
        self.assertEqual(pack(e.__dict__), before)

    def test_strict_subsequent_and_scan_cap(self):
        e = self.owned()
        tr = Trade(e.now, 'BILL', 105, 100, 'buy', 'at-boundary', 100000, 'treasury')
        self.assertFalse(liquidate(e, [tr], e.now+100, ClosingRule(100, 1))['done'])
        tape = [replace(tr, time=e.now+i+1, side='sell', identifier=str(i)) for i in range(3)]
        r = liquidate(e, tape, e.now+100, ClosingRule(100, 1))
        self.assertEqual(r['reason'], 'closing_scan_cap')
        self.assertNotIn('utility', r)

    def test_duration_ignored_and_split_containment(self):
        e = self.owned()
        tr = Trade(e.now+1, 'BILL', 99, 100, 'buy', 'close', 100000, 'treasury')
        a = liquidate(e, [tr], e.now+1000, ClosingRule(1000, 5))
        b = liquidate(e, [replace(tr, time=e.now+999)], e.now+1000, ClosingRule(1000, 5))
        self.assertEqual(a['utility'], b['utility'])
        self.assertFalse(liquidate(e, [replace(tr, time=e.now+1001)], e.now+1000)['done'])

    def test_future_changes_label_not_features(self):
        e = self.owned(); f = encode(e.observe(), Instruction(), e.goal, e.instruments, 0)
        tr = Trade(e.now+1, 'BILL', 99, 100, 'buy', 'close', 100000, 'treasury')
        a = liquidate(e, [tr], e.now+100)
        b = liquidate(e, [replace(tr, price=95)], e.now+100)
        self.assertNotEqual(a['utility'], b['utility'])
        self.assertEqual(f, encode(e.observe(), Instruction(), e.goal, e.instruments, 0))

    def test_sale_and_redemption_never_double_counted(self):
        e = self.owned(); e.now = self.case['maturity']-10
        tr = Trade(e.now+1, 'BILL', 99, 100, 'buy', 'sale', 100000, 'treasury')
        sale = liquidate(e, [tr], e.now+100)
        redeem = liquidate(e, [], e.now+100)
        cash = e.hidden.ledger.balances['USD']
        self.assertAlmostEqual(sale['balances']['USD'], cash+25*99*(1-self.case['fee_bps']/10000))
        self.assertAlmostEqual(redeem['balances']['USD'], cash+2500)
        self.assertEqual(len(redeem['projected_receipts']), 1)

    def test_liabilities_are_paid_or_censored_never_forgiven(self):
        e = self.engine()
        e.hidden.ledger.credit_limit = 100
        e.hidden.ledger.borrow(100, e.now+10, 2)
        complete = liquidate(e, [], e.now+100)
        self.assertAlmostEqual(complete['balances']['USD'], 9998)
        self.assertFalse(liquidate(e, [], e.now+5)['done'])

    def test_failure_penalty_survives_closing(self):
        e = self.engine(); e.hidden.failures.append(dict(time=e.now, reason='earlier'))
        self.assertEqual(liquidate(e, [], e.now)['utility'], -1)

    def test_support_zero_horizon_censoring_and_base_only_exception(self):
        r = ClosingRule(100, 10)
        self.assertFalse(horizon_support(100, 0, 150, 150, r)[0])
        self.assertTrue(horizon_support(100, 0, 150, 150, r, base_only=True)[0])
        self.assertFalse(horizon_support(100, 51, 150, 500, r)[0])

    def test_native_linear_inverse_pnl_fees_no_automatic_btc_repurchase(self):
        for payoff, quantity in [('linear', .01), ('inverse', 1000)]:
            ins = Instrument('F', 10000, payoff=payoff, source_payoff=payoff, fee_bps=1, tick=1, lot=.001)
            l = Ledger(dict(BTC=1., USD=10000.)); l.fill(ins, quantity, 100000)
            e = Engine({'F':ins}, l, Goal(dict(BTC=1.,USD=10000.), 1, 10000, mode='weighted_growth'), delays=Delays(0,0,0,0,0,0))
            e.now=1
            tr = Trade(2, 'F', 101000, abs(quantity), 'buy', 'close', 100000, payoff)
            r = liquidate(e, [tr], 100)
            native = quantity*(101000-100000) if payoff=='linear' else quantity*(1/100000-1/101000)
            expected = l.balances[ins.currency]+native-ins.fee(quantity, 101000)
            self.assertAlmostEqual(r['balances'][ins.currency], expected)
            if payoff=='linear': self.assertEqual(r['balances']['BTC'], 1.)

    def test_explicit_funded_btc_repurchase_after_spot_funded_future(self):
        spot = Instrument('S', 100000, payoff='spot', source_payoff='spot', tick=1, lot=.001, fee_bps=0)
        fut = Instrument('F', 10000, payoff='linear', source_payoff='linear', tick=1, lot=.001, fee_bps=0)
        l = Ledger(dict(BTC=1., USD=10000.))
        l.fill(spot, -.05, 100000); l.fill(fut, .05, 99000)
        e = Engine({'S':spot, 'F':fut}, l, Goal(dict(BTC=1.,USD=10000.),1,10000,mode='weighted_growth'), delays=Delays(0,0,0,0,0,0))
        e.now=1; e.participation=1.
        closed = liquidate(e, [Trade(2,'F',100000,.05,'buy','close',100000,'linear')],100)
        self.assertEqual(closed['balances']['BTC'], .95)
        e.hidden.ledger.fill(fut, -.05, 100000)
        e.observable.ledger = e.hidden.ledger.clone()
        e.seed_market([Trade(0,'S',100000,1,'buy','spot',100000,'spot')], 3)
        buy = Instruction('create', (Order('repurchase','S',.05,100000),))
        self.assertTrue(admissible(e.observe(),buy,e.goal,e.instruments)[0])
        e.submit(buy); e.add_tape([Trade(4,'S',99999,.05,'sell','funded-buy',100000,'spot')]); e.advance(5)
        self.assertAlmostEqual(e.hidden.ledger.balances['BTC'],1.)
        self.assertAlmostEqual(e.hidden.ledger.balances['USD'],10050.)

    def test_multi_horizon_same_state_isolated_reproducible_and_boundary_no_model(self):
        e = accept_anchor(self.engine(), Instruction(), self.c)
        before = deepcopy(pack(e.__dict__))
        args = (e, [0,2000], self.scenarios(), [], [Controller(1),Controller(2,.5)],
                ZeroModel(), encode, action_provider(self.c), self.c)
        rows = collect_post_state(*args, self.budget, 'frozen')
        again = collect_post_state(*args, self.budget, 'frozen')
        self.assertEqual(rows, again)
        self.assertEqual(pack(e.__dict__), before)
        self.assertEqual(rows[0]['state_id'], rows[1]['state_id'])
        self.assertEqual(rows[0]['benchmark']['initial'], rows[1]['benchmark']['initial'])
        self.assertEqual(len(rows[0]['branches']), 1)
        self.assertEqual(len(rows[1]['branches']), 2)
        for branches in rows[1]['branches']:
            self.assertEqual(branches[0]['controller'], branches[1]['controller'])

    def test_physical_countdown_event_wakeups_and_no_strategy_tail(self):
        e = self.engine()
        r = rollout(e, 2*DAY, self.scenarios()[0], Controller(0), ZeroModel(), encode,
                    action_provider(self.c), self.c, self.budget)
        self.assertGreater(len(r['decisions']), 1)
        for d in r['decisions']:
            self.assertEqual(d['remaining_ms'], r['endpoint']-d['time'])
            self.assertLess(d['time'], r['endpoint'])
            self.assertNotIn('hidden', d['reasons'])

    def test_budget_stop_never_produces_label(self):
        limits = dict(self.c['limits'], decisions=1)
        r = rollout(self.engine(), 2*DAY, self.scenarios()[0], Controller(0), ZeroModel(),
                    encode, action_provider(self.c), self.c, CampaignBudget(limits))
        self.assertFalse(r['outcome']['done'])

    def test_independent_hold_reference_and_toy_oracle(self):
        for case in make_cases('train', self.c)[:4]:
            for q in ([0] if case['category']=='cash_constrained' else [0,5,25,60]):
                e = fixture_engine(case,self.c)
                a = Instruction() if not q else Instruction('create',(Order('x','BILL',q,case['price']),))
                accept_anchor(e,a,self.c)
                s = scenario_set(case,[1],self.c,'reference')[0]
                for h in self.c['horizons_ms']:
                    r = rollout(e,h,s,Controller(0),ZeroModel(),encode,action_provider(self.c),self.c,self.budget,hold=True)
                    expected = hold_reference(case,q,h)
                    self.assertTrue(r['outcome']['done'])
                    self.assertAlmostEqual(r['outcome']['utility'],expected['utility'],places=10)
            oracle=finite_toy_optimum(case,self.c['horizons_ms'][-1],self.c,self.budget)
            self.assertEqual(oracle['witness']['quantity'],60 if case['category']=='profitable' else 0)

    def test_splits_buffers_and_fresh_case_groups(self):
        groups=[make_cases(s,self.c) for s in ('train','validation','test')]
        for left,right in zip(groups,groups[1:]):
            self.assertLess(max(c['label_end'] for c in left),min(c['start'] for c in right))
        self.assertEqual(len({c['id'] for group in groups for c in group}),20)

    def test_scalar_checkpoint_exact_inference_legacy_rejection_and_label_checks(self):
        torch.set_num_threads(1); torch.manual_seed(1)
        m=TreasuryValue();e=self.engine();f=encode(e.observe(),Instruction(),e.goal,e.instruments,0)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'model.pt';save_scalar(path,m,None,{'target':TARGET_VERSION})
            restored,_,_=load_scalar(path,{'target':TARGET_VERSION})
            np.testing.assert_array_equal(m.predict([f]),restored.predict([f]))
            with self.assertRaises(ValueError):load_scalar(path,{'target':'legacy'})
        with self.assertRaises(ValueError):tensors([dict(done=False,target=None)])

    def test_collector_integration_independent_references_and_fresh_winner_audits(self):
        c=deepcopy(self.c);c['horizons_ms']=[0,2000];c['controllers']=[dict(seed=1,epsilon=0)]
        c['anchor_indices']=[]
        rows=collect_cases(make_cases('train',c)[:1],c,self.budget,ZeroModel())
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(r['done'])
            self.assertAlmostEqual(r['target'],r['independent_target'])
            audit_ids={a['scenario'] for a in r['winner_audit']}
            self.assertFalse(audit_ids & set(r['scenarios']))
            self.assertEqual(len(r['winner_audit']),1)

    def test_configuration_cannot_silently_change_oracle_domain_or_audit_seeds(self):
        validate_config(self.c)
        c=deepcopy(self.c);c['price_offsets']=[0,.01]
        with self.assertRaises(ValueError):validate_config(c)
        c=deepcopy(self.c);c['audit_seeds']=c['scenario_seeds'][:1]
        with self.assertRaises(ValueError):validate_config(c)

    def test_duplicate_closing_print_rejected(self):
        e=self.owned();t=Trade(e.now+1,'BILL',99,10,'buy','duplicate',100000,'treasury')
        with self.assertRaises(ValueError):liquidate(e,[t,t],e.now+100)

    def test_trace_distinguishes_hidden_arrivals_and_received_reports(self):
        e=self.engine();e.event_trace=[]
        e.submit(Instruction('create',(Order('x','BILL',5,self.case['price']),)))
        e.add_tape(self.scenarios()[0]['trades']);e.advance(e.now+2000)
        kinds={r['kind']:r['visibility'] for r in e.event_trace}
        self.assertEqual(kinds['message'],'hidden');self.assertEqual(kinds['report'],'received')

    def test_fitting_budget_counts_validation_and_checkpoint_time_on_interrupt(self):
        with patch('research.post_decision_value.robust_rollout.time.monotonic') as clock:
            clock.return_value=0.
            budget=CampaignBudget(self.c['limits'])
            with self.assertRaisesRegex(RuntimeError,'campaign_fit_cap'):
                with budget.fitting():
                    clock.return_value=121.
                    with self.assertRaisesRegex(RuntimeError,'campaign_fit_cap'):budget.fit_check()
            self.assertEqual(budget.fit_seconds,121.)
            self.assertIsNone(budget.fit_started)


if __name__ == '__main__':
    unittest.main()
