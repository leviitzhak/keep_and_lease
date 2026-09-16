"""Exchange-time deadlines, full-tranche hedges and bounded funded restoration."""
import json
import unittest

from paired_transfer import PairedConfig, PairedTransferAccount
from trade_replay import Trade

DAY = 86400 * 1_000_000


def trade(us, symbol="SPOT", price=100, quantity=.01, side="buy"):
    return Trade(us, symbol, price, quantity, side, f"{symbol}:{us}", True)


class EmpiricalDeadlineExecutionTests(unittest.TestCase):
    def account(self, **settings):
        params = dict(repricing_mode="empirical", waiting_seconds=1, max_unpaired_btc=.01,
                      max_quote_age_seconds=60, max_quote_skew_seconds=60)
        params.update(settings)
        audit = []
        account = PairedTransferAccount(1000, config=PairedConfig(**params),
                                        expiries={"F": 30*DAY}, sink=audit.append)
        account.marks["F"] = trade(0, "F", 98)
        account.initialize_spot(trade(0))
        account.rate = .04
        return account, audit

    def submit(self, account, us=1, q=.01, target_q=.01):
        return account.start_transfer(us, dict(accepted=True, source_symbol="SPOT", target_symbol="F",
            source_quantity_btc=q, target_quantity_btc=target_q, cash_rate=.04, horizon_us=30*DAY,
            diagnostics=dict(source_sale_limit=99.9, target_buy_limit=99,
                             execution_budget_bps=100, execution_joint_success_probability=.95)))

    def test_partial_source_accumulates_before_one_hedge_and_all_source_acknowledgements(self):
        account, _ = self.account(response_delay_seconds=.1, decision_delay_seconds=.1,
                                   order_delay_seconds=.1)
        self.submit(account)
        account.on_trade(trade(200_002, quantity=.004, side="sell"))
        account.on_trade(trade(200_003, quantity=.006, side="sell"))
        pair = account.pairs[account.active_pair_id]
        self.assertAlmostEqual(pair.source_filled_btc, .01)
        self.assertFalse(account.orders["F"].active)
        account.on_trade(trade(250_000, "F", 98))
        self.assertEqual(account.units.get("F", 0), 0)
        account.accrue(500_003)
        self.assertTrue(account.orders["F"].active)
        account.on_trade(trade(500_004, "F", 98, .004))
        account.on_trade(trade(500_005, "F", 98, .006))
        self.assertAlmostEqual(account.units["F"], .01)
        account.accrue(600_005)
        self.assertIsNone(account.active_pair_id)
        self.assertEqual(account.summary()["empirical_execution"]["completed_by_deadline"], 1)

    def test_deadline_origin_is_decision_start_and_deadline_print_cannot_fill(self):
        account, audit = self.account(decision_delay_seconds=.2, order_delay_seconds=.3)
        self.submit(account)
        account.accrue(500_001)
        pair = account.pairs[account.active_pair_id]
        self.assertEqual(pair.submitted_us, 200_001)
        self.assertEqual(pair.deadline_us, 1_000_001)
        account.on_trade(trade(1_000_001, side="sell"))
        self.assertEqual(account.fill_count, 0)
        self.assertIsNone(account.active_pair_id)
        result = next(row for row in audit if row["kind"] == "empirical_instruction_result")
        self.assertEqual(result["us"], 1_000_001)
        self.assertFalse(result["completed_by_deadline"])
        self.assertEqual(account.summary()["empirical_execution"]["unfilled_at_deadline"], 1)

    def test_standing_source_limit_is_frozen_and_does_not_require_new_quote_freshness(self):
        account, _ = self.account(max_quote_age_seconds=.001)
        self.submit(account)
        floor = account.orders["SPOT"].limit_price
        account.on_trade(trade(10_000, "F", 105))
        self.assertEqual(account.orders["SPOT"].limit_price, floor)
        account.on_trade(trade(20_000, side="sell"))
        self.assertAlmostEqual(account.units["SPOT"], 9.99)
        self.assertEqual(account.orders["F"].limit_price, 99)

    def test_actual_source_proceeds_bound_hedge_and_no_price_improvement_widens_budget(self):
        account, _ = self.account()
        self.submit(account)
        account.on_trade(trade(2, price=105, side="sell"))
        self.assertEqual(account.orders["F"].limit_price, 99)
        account.on_trade(trade(3, "F", 100))
        self.assertEqual(account.fill_count, 1)
        account.on_trade(trade(4, "F", 99))
        self.assertEqual(account.fill_count, 2)
        self.assertGreaterEqual(account.funding_equity, account.collateral)

    def test_deadline_partial_source_restores_spot_in_finite_funded_attempt(self):
        account, audit = self.account()
        self.submit(account)
        account.on_trade(trade(2, side="sell", quantity=.004))
        account.on_trade(trade(3, "F", 98))
        self.assertEqual(account.units.get("F", 0), 0, "Incomplete source tranche cannot hedge")
        account.accrue(1_000_001)
        self.assertIsNone(account.active_pair_id)
        self.assertIsNotNone(account.cash_recovery)
        prior_quantity = account.units["SPOT"]
        account.on_trade(trade(1_000_002, quantity=.004))
        self.assertGreater(account.units["SPOT"], prior_quantity)
        self.assertIsNone(account.cash_recovery)
        summary = account.summary()["empirical_execution"]
        self.assertEqual(summary["partial_at_deadline"], 1)
        self.assertAlmostEqual(summary["archived_unmatched_source_btc"], .004)
        self.assertGreater(summary["cash_restored_btc"], 0)
        self.assertGreaterEqual(account.cash, 0)
        self.assertAlmostEqual(account.reconstruction_error(), 0, places=8)
        self.assertEqual([row["us"] for row in audit], sorted(row["us"] for row in audit))

    def test_no_liquidity_restoration_expires_and_cash_stays_visible(self):
        account, _ = self.account()
        self.submit(account)
        account.on_trade(trade(2, side="sell"))
        account.accrue(1_000_001)
        self.assertIsNotNone(account.cash_recovery)
        account.accrue(2_000_001)
        self.assertIsNone(account.cash_recovery)
        summary = account.summary()["empirical_execution"]
        self.assertEqual(summary["restoration_deadline_failed"], 1)
        self.assertGreater(summary["restoration_residual_cash_usd"], 0)
        self.assertGreater(summary["residual_cash_usd"], 0)
        self.assertIsNone(account.active_pair_id)
        self.assertEqual(account.ledger.reservations, {})

    def test_hedge_partial_fill_preserves_request_ratio_and_failed_exposure_history(self):
        account, _ = self.account()
        pair = self.submit(account)
        account.on_trade(trade(2, side="sell"))
        account.on_trade(trade(3, "F", 98, .004))
        account.accrue(1_000_001)
        self.assertEqual(pair.source_quantity_btc, .01)
        self.assertEqual(pair.target_quantity_btc, .01)
        self.assertAlmostEqual(pair.unpaired_btc, .006)
        self.assertAlmostEqual(account.units["F"], .004)
        self.assertLessEqual(account.cash_recovery["budget_usd"], .6+1e-10)
        self.assertGreaterEqual(account.funding_equity, account.collateral)

    def test_final_exchange_fill_before_deadline_succeeds_even_when_ack_is_late(self):
        account, _ = self.account(response_delay_seconds=.1)
        self.submit(account)
        account.on_trade(trade(2, side="sell"))
        account.on_trade(trade(950_000, "F", 98))
        account.accrue(1_000_001)
        self.assertEqual(account.summary()["empirical_execution"]["completed_by_deadline"], 1)
        self.assertIsNone(account.cash_recovery)
        account.accrue(1_100_000)
        self.assertAlmostEqual(account.known_units["F"], account.units["F"])

    def test_end_window_censor_is_separate_from_deadline_failure_and_predictions(self):
        account, _ = self.account()
        self.submit(account)
        account.on_trade(trade(2, side="sell", quantity=.004))
        account.cancel(500_000, "end_of_window")
        summary = account.summary()["empirical_execution"]
        self.assertEqual(summary["end_window_censored"], 1)
        self.assertEqual(summary["deadline_failed"], 0)
        self.assertIsNone(summary["completion_probability"])
        self.assertIsNone(summary["predicted_completion_probability_mean"])
        self.assertIsNone(account.cash_recovery)
        self.assertGreater(account.cash, 0)

    def test_restart_preserves_exchange_deadline_and_bounded_restoration(self):
        account, audit = self.account(decision_delay_seconds=.1, order_delay_seconds=.1)
        self.submit(account)
        account.on_trade(trade(300_000, side="sell"))
        restored_audit = []
        restored = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())), sink=restored_audit.append)
        audit.clear()
        for item in (account, restored):
            item.accrue(1_000_001)
            item.accrue(1_200_001)
            item.on_trade(trade(1_200_002))
        self.assertEqual(account.snapshot(), restored.snapshot())
        self.assertEqual(audit, restored_audit)
        self.assertAlmostEqual(account.reconstruction_error(), 0, places=8)

    def test_expiry_risk_exit_is_bounded_even_when_held_future_exceeds_tranche_cap(self):
        account, _ = self.account()
        for start in (1, 10):
            self.submit(account, us=start)
            account.on_trade(trade(start+1, side="sell"))
            account.on_trade(trade(start+2, "F", 98))
        self.assertAlmostEqual(account.units["F"], .02)
        account.expiries["F"] = DAY
        pair = account.decide(20, rate_snapshot={"allows_new_transfers": False})
        self.assertIsNotNone(pair)
        self.assertEqual(pair.source_symbol, "F")
        self.assertEqual(pair.target_symbol, "SPOT")
        self.assertLessEqual(pair.source_quantity_btc, account.config.max_unpaired_btc)
        self.assertEqual(pair.reason, "forced_expiry_exit")
        self.assertNotIn("execution_joint_success_probability", pair.decision["diagnostics"])

    def test_impossible_submission_deadline_rejects_and_pending_end_window_is_censored(self):
        blocked, _ = self.account(decision_delay_seconds=.5, order_delay_seconds=.5)
        self.assertIsNone(self.submit(blocked))
        self.assertIsNone(blocked.active_pair_id)
        self.assertEqual(blocked.last_reason, "decision_and_transport_exhaust_execution_deadline")
        pending, audit = self.account(decision_delay_seconds=.5)
        self.submit(pending)
        pending.cancel(100_000, "end_of_window")
        summary = pending.summary()["empirical_execution"]
        self.assertEqual(summary["instructions"], 1)
        self.assertEqual(summary["end_window_censored"], 1)
        self.assertEqual(summary["deadline_failed"], 0)
        self.assertFalse(pending.pending_initial_decision)
        self.assertTrue(any(row["kind"] == "empirical_instruction_result" for row in audit))

    def test_oversized_whole_instruction_and_invalid_parameters_fail_closed(self):
        account, _ = self.account()
        self.assertIsNone(self.submit(account, q=.1, target_q=.1))
        self.assertEqual(account.last_reason, "empirical_instruction_exceeds_tranche_cap")
        for settings in ({"execution_confidence": 1}, {"execution_min_samples": 0},
                         {"execution_min_samples": 1.5}, {"waiting_seconds": 61},
                         {"execution_size_grid_btc": "0.001,-1"}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                PairedConfig(**settings)


if __name__ == "__main__":
    unittest.main()
