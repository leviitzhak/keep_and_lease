import copy
import json
import unittest

from paired_transfer import PairedConfig, PairedTransferAccount
from rolling_lease_execution import RollingPriceWindow, YEAR_US
from tests.test_paired_transfer import trade
from tests.test_paired_backtest_integration import scenario, run_case


class RollingLeaseTests(unittest.TestCase):
    def account(self, price=90, **settings):
        settings = dict(selection_mode="amortized_rank", repricing_mode="rolling_worst",
            max_transfer_fraction=1, max_delta_btc=.2, max_unpaired_btc=.1,
            max_quote_age_seconds=100, max_quote_skew_seconds=100,
            lease_window_seconds=5, lease_execution_delta_bps=10,
            expected_hedge_slippage_bps=1, **settings)
        rows = []
        account = PairedTransferAccount(1000, config=PairedConfig(**settings),
            sink=rows.append, expiries={"F": YEAR_US})
        account.marks["F"] = trade(0, "F", price)
        account.initialize_spot(trade(0))
        account.rate = .04
        return account, rows

    def test_both_limit_anchors_and_spot_leg_inversion(self):
        account, _ = self.account()
        account.observed_marks["G"] = trade(0, "G", 120)
        context = dict(spot_reference_price=100, factors={"SPOT": 1, "F": .95, "G": 1.1},
                       expected_hedge_slippage_bps=10, limit_anchor="spot")
        self.assertEqual(account._rolling_limits(context, "F", "G"), (95, 110.00000000000001))
        floor, cap = account._rolling_limits(context, "SPOT", "F")
        self.assertAlmostEqual(floor, 90/.95)
        self.assertEqual(cap, 95)
        floor, cap = account._rolling_limits(context, "F", "SPOT")
        self.assertEqual(floor, 95)
        self.assertAlmostEqual(cap, 90/.95)
        context["limit_anchor"] = "relative_price"
        floor, cap = account._rolling_limits(context, "F", "G")
        self.assertAlmostEqual(floor, 120*1.001*.95/1.1)
        self.assertAlmostEqual(cap, 90*.999*1.1/.95)
        self.assertNotAlmostEqual(floor, 95)
        parsed = PairedConfig.from_payload(dict(paired_selection_mode="amortized_rank",
            paired_repricing_mode="rolling_worst", paired_limit_anchor="spot"))
        self.assertEqual(parsed.limit_anchor, "spot")
        with self.assertRaisesRegex(ValueError, "limit_anchor"):
            PairedConfig(limit_anchor="unknown")

    def test_spot_anchor_replay_and_restart_preserve_choice(self):
        account, _ = self.account(limit_anchor="spot")
        account.decide(1)
        restored = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())))
        self.assertEqual(restored.config.limit_anchor, "spot")
        for a in (account, restored):
            a.on_trade(trade(2, btc=.1, side="sell"))
            a.on_trade(trade(3, "F", 90, .1))
        self.assertEqual(account.snapshot(), restored.snapshot())
        self.assertGreater(account.fill_count, 0)
        p, store, coverage = scenario()
        p.update(paired_selection_mode="amortized_rank", paired_repricing_mode="rolling_worst",
                 paired_limit_anchor="spot", paired_max_delta_btc=.2)
        result, rows, _ = run_case(p, store, coverage)
        self.assertEqual(result["trade_replay"]["paired_transfer"]["limit_anchor"], "spot")
        self.assertGreater(result["trade_replay"]["paired_transfer"]["completed"], 0)
        self.assertEqual(result["trade_replay"]["collateral_breach_count"], 0)
        self.assertLess(result["trade_replay"]["max_nav_reconstruction_error_usd"], 1e-7)

    def test_bounds_all_pairs_expiration_and_snapshot(self):
        window = RollingPriceWindow(2)
        for symbol, price, us in (("SPOT", 100, 0), ("F", 90, 1),
                                  ("SPOT", 102, 2), ("F", 95, 3)):
            window.observe(symbol, price, us, us)
        bound = window.bounds("F", 3, YEAR_US+3, .04)
        self.assertAlmostEqual(bound["min_lease"], .04-(95/100-1))
        self.assertAlmostEqual(bound["max_lease"], .04-(90/102-1))
        restored = RollingPriceWindow.restore(2, json.loads(json.dumps(window.snapshot())))
        self.assertEqual(bound, restored.bounds("F", 3, YEAR_US+3, .04))
        self.assertIsNone(window.bounds("F", 2_000_004, YEAR_US, .04))

    def test_delayed_data_does_not_enter_window_early(self):
        account, _ = self.account(futures_feed_delay_seconds=1)
        self.assertIsNone(account._rolling_context(500_000, "SPOT", "F"))
        account.accrue(1_000_000)
        self.assertIsNotNone(account._rolling_context(1_000_000, "SPOT", "F"))
        account.on_trade(trade(2_000_000, "F", 120))
        context = account._rolling_context(2_000_000, "SPOT", "F")
        self.assertEqual(context["rates"]["F"]["future_extrema"]["max"]["price"], 90)
        account.accrue(3_000_000)
        self.assertEqual(account._rolling_context(3_000_000, "SPOT", "F")["rates"]["F"]["future_extrema"]["max"]["price"], 120)

    def test_full_btc_has_no_target_first_funding_and_market_crosses_old_cap(self):
        account, rows = self.account()
        pair = account.decide(1)
        self.assertIsNotNone(pair)
        account.on_trade(trade(2, "F", 90, .1))
        self.assertEqual(account.fill_count, 0)
        account.on_trade(trade(3, btc=.1, side="sell"))
        old_cap = account.orders["F"].limit_price
        self.assertTrue(account.orders["F"].market_order)
        account.on_trade(trade(4, "F", old_cap+1, .1))
        self.assertEqual(account.fill_count, 2)
        row = next(r for r in rows if r["kind"] == "lease_execution")
        self.assertGreater(row["adverse_lease_slippage"], 0)
        self.assertLess(abs(account.reconstruction_error()), 1e-9)
        self.assertGreaterEqual(account.free_collateral, -1e-9)

    def test_target_first_uses_only_existing_cash_then_market_source(self):
        account, rows = self.account()
        account.ledger.execute_fill("SPOT", -.2, 100, "cash-buffer")
        account.known_units = dict(account.units)
        pair = account.decide(1)
        account.on_trade(trade(2, "F", 90, .1))
        self.assertEqual(pair.source_filled_btc, 0)
        self.assertAlmostEqual(pair.unpaired_btc, .1)
        self.assertTrue(account.orders["SPOT"].market_order)
        account.on_trade(trade(3, price=99, btc=.1, side="sell"))
        self.assertAlmostEqual(pair.unpaired_btc, 0)
        execution = next(r for r in rows if r["kind"] == "lease_execution")
        self.assertEqual(execution["first_role"], "target")
        self.assertAlmostEqual(execution["source_fill_price"], 99)
        self.assertAlmostEqual(account.reconstruction_error(), 0)

    def test_market_hedge_waits_for_ack_decision_transport_and_survives_restart(self):
        account, rows = self.account(response_delay_seconds=.1, decision_delay_seconds=.1,
                                     order_delay_seconds=.1)
        account.decide(1)
        account.accrue(200_002)
        account.on_trade(trade(200_003, btc=.1, side="sell"))
        self.assertFalse(account.orders["F"].market_order)
        account.on_trade(trade(400_000, "F", 91, .1))
        self.assertEqual(account.fill_count, 1)
        restored = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())))
        for a in (account, restored):
            a.on_trade(trade(500_003, "F", 91, .05))  # exact arrival cannot fill
            self.assertEqual(a.fill_count, 1)
            a.on_trade(trade(500_004, "F", 91, .05))
            a.on_trade(trade(600_005, "F", 91, .05))
            a.accrue(800_006)
        self.assertEqual(account.snapshot(), restored.snapshot())
        execution = [r for r in rows if r["kind"] == "lease_execution"]
        self.assertEqual(len(execution), 2)
        self.assertEqual(execution[0]["hit_order_revision"], execution[1]["hit_order_revision"])
        self.assertEqual(execution[0]["set_lease"], execution[1]["set_lease"])

    def test_reverse_and_roll_use_exit_sign_and_reconcile(self):
        for roll in (False, True):
            with self.subTest(roll=roll):
                account, rows = self.account(price=110)
                account.ledger.execute_fill("SPOT", -2, 100, "setup-sale")
                account.ledger.execute_fill("F", 1, 110, "setup-future")
                account.known_units = dict(account.units)
                if roll:
                    account.expiries["G"] = YEAR_US
                    account.on_trade(trade(1, "G", 80))
                pair = account.decide(2)
                self.assertEqual(pair.source_symbol, "F")
                self.assertEqual(pair.target_symbol, "G" if roll else "SPOT")
                account.on_trade(trade(3, "F", 110, .1, "sell"))
                account.on_trade(trade(4, pair.target_symbol, 80 if roll else 100, .1))
                results = [r for r in rows if r["kind"] == "lease_execution"]
                exit_row = next(r for r in results if r["symbol"] == "F")
                self.assertGreater(exit_row["execution_delta"], 0)
                if roll:
                    self.assertLess(next(r for r in results if r["symbol"] == "G")["execution_delta"], 0)
                self.assertLess(abs(account.reconstruction_error()), 1e-8)

    def test_delta_and_expected_slippage_can_reject_transfer(self):
        account, _ = self.account(price=103.9)
        self.assertIsNone(account.decide(1))  # 10 bps annual delta uses up 10 bps gross
        account, _ = self.account(price=103.8)
        self.assertIsNotNone(account.decide(1))
        account, _ = self.account(price=103.8)
        account.config.expected_hedge_slippage_bps = 100
        self.assertIsNone(account.decide(1))

    def test_current_hit_print_cannot_reprice_its_own_order(self):
        account, rows = self.account()
        account.decide(1)
        before = copy.deepcopy(account.orders["SPOT"].lease_context)
        revision = account.orders["SPOT"].revision
        account.on_trade(trade(2, price=101, btc=.1, side="sell"))
        first = next(r for r in rows if r["kind"] == "fill")
        self.assertEqual(first["order_revision"], revision)
        self.assertEqual(first["lease_context"], before)

    def test_target_first_timeout_keeps_source_market_recovery_and_partial_metrics(self):
        account, rows = self.account(max_legging_seconds=.1)
        account.ledger.execute_fill("SPOT", -.2, 100, "cash-buffer")
        account.known_units = dict(account.units)
        pair = account.decide(1)
        account.on_trade(trade(2, "F", 90, .1))
        account.accrue(100_003)
        self.assertEqual(pair.status, "timed_out")
        self.assertTrue(account.orders["SPOT"].active)
        account.on_trade(trade(100_004, price=99, btc=.05, side="sell"))
        account.cancel(100_005, "end_of_window")
        result = [r for r in rows if r["kind"] == "paired_transfer_result"][-1]
        self.assertAlmostEqual(result["unpaired_btc"], .05)
        self.assertAlmostEqual(result["matched_source_btc"], .05)
        self.assertAlmostEqual(result["source_vwap"], 99)
        self.assertAlmostEqual(result["target_vwap"], 90)

    def test_small_source_print_cannot_strand_fixed_hedge_fee(self):
        account, _ = self.account(futures_fixed_fee_usd=.5)
        account.decide(1)
        self.assertIsNotNone(account.active_pair_id)
        account.on_trade(trade(2, btc=.00001, side="sell"))
        self.assertEqual(account.fill_count, 0)

    def test_mode_and_cost_validation(self):
        for values in (dict(lease_window_seconds=0), dict(lease_execution_delta_bps=-1),
                       dict(expected_hedge_slippage_bps=10000), dict(expected_hedge_slippage_bps=float("nan"))):
            with self.subTest(values=values), self.assertRaises(ValueError):
                PairedConfig(selection_mode="amortized_rank", repricing_mode="rolling_worst", **values)
        with self.assertRaisesRegex(ValueError, "requires amortized_rank"):
            PairedConfig(repricing_mode="rolling_worst")

    def test_real_replay_records_limits_and_matched_comparisons(self):
        p, store, coverage = scenario()
        p.update(paired_selection_mode="amortized_rank", paired_repricing_mode="rolling_worst",
                 paired_max_delta_btc=.2)
        result, rows, _ = run_case(p, store, coverage)
        json.dumps(result, allow_nan=False)
        self.assertGreater(result["trade_replay"]["paired_transfer"]["completed"], 0)
        self.assertEqual(result["trade_replay"]["collateral_breach_count"], 0)
        self.assertLess(result["trade_replay"]["max_nav_reconstruction_error_usd"], 1e-7)
        kinds = {r["kind"] for r in rows["btc_trade_events"]}
        self.assertIn("lease_execution", kinds)
        self.assertIn("lease_limit_state", kinds)
        from tests.test_paired_exports import exported
        sheets = exported(rows["btc_trade_events"])
        self.assertTrue(sheets["Lease executions"])
        self.assertTrue(sheets["Lease limits"])
        actual = next(r for r in rows["btc_trade_events"] if r["kind"] == "lease_execution")
        saved = sheets["Lease executions"][0]
        self.assertEqual(saved["hit_order_revision"], actual["hit_order_revision"])
        self.assertEqual(saved["set_lease"], actual["set_lease"])
        self.assertEqual(saved["executed_lease"], actual["executed_lease"])
        from tests.test_paired_audit_checker import CHECKER
        from types import SimpleNamespace
        import sqlite3
        checks = CHECKER.Checks()
        with sqlite3.connect(":memory:") as db:
            audit = CHECKER.Audit(SimpleNamespace(capital=100000, fee_bps=0, participation=1,
                max_unpaired_btc=1, interval_seconds=.5), SimpleNamespace(checks=checks), db)
            for row in rows["btc_trade_events"]:
                audit.event(row)
        self.assertFalse(checks.failures, checks.report())


if __name__ == "__main__":
    unittest.main()
