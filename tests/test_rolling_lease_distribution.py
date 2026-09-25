import json
import random
import statistics
import unittest

from paired_transfer import PairedConfig, PairedTransferAccount
from rolling_lease_distribution import RollingLeaseDistributionWindow
from rolling_lease_execution import YEAR_US
from tests.test_paired_transfer import trade
from tests.test_paired_backtest_integration import scenario, run_case
from tests import test_rolling_lease_execution as legacy


class DistributionWindowTests(unittest.TestCase):
    def test_transformed_median_and_all_target_choices(self):
        window = RollingLeaseDistributionWindow(5)
        for symbol, prices in (("SPOT", [80, 100]), ("F", [90, 120])):
            for i, price in enumerate(prices):
                window.observe(symbol, price, i, i)
        lease = lambda f, s: .04-(f/s-1)
        for alpha in (0, .37, 1):
            for combine in ("min", "max", "mean"):
                b = window.distributions("F", 2, YEAR_US+2, .04, 100, 120, alpha, combine)
                a, c = [lease(120, s) for s in (80, 100)], [lease(f, 100) for f in (90, 120)]
                targets = []
                for values, key in ((a, "spot_history_leases"), (c, "future_history_leases")):
                    expected = statistics.median(values)+alpha*(max(values)-statistics.median(values))
                    self.assertAlmostEqual(b[key]["minimum"], min(values))
                    self.assertAlmostEqual(b[key]["median"], statistics.median(values))
                    self.assertAlmostEqual(b[key]["maximum"], max(values))
                    self.assertAlmostEqual(b[key]["target"], expected)
                    targets.append(expected)
                expected = {"min": min(targets), "max": max(targets), "mean": statistics.mean(targets)}[combine]
                self.assertAlmostEqual(b["target_lease"], expected)
        self.assertNotAlmostEqual(b["spot_history_leases"]["median"], lease(120, 90))

    def test_duplicates_expiry_boundaries_and_restart_match_brute_force(self):
        rng = random.Random(811)
        window = RollingLeaseDistributionWindow(.005)
        tape = []
        for i in range(200):
            us, price = i*100, rng.choice([90, 100, 100, 110, 120])
            tape.append((us, price))
            window.observe("SPOT", price, us, us)
            values = [p for t, p in tape if t >= us-5000]
            stats = window.statistics("SPOT", us)
            self.assertEqual(stats["count"], len(values))
            self.assertEqual(stats["median"], statistics.median(values))
            self.assertEqual(stats["median_reciprocal"], statistics.median([1/p for p in values]))
            if i == 100:
                window = RollingLeaseDistributionWindow.restore(.005, json.loads(json.dumps(window.snapshot())))
        self.assertIsNone(window.statistics("SPOT", 25001))

    def test_rate_and_remaining_maturity_are_current_not_historical(self):
        window = RollingLeaseDistributionWindow(10)
        window.observe("SPOT", 100, 0, 0)
        window.observe("F", 90, 0, 0)
        self.assertAlmostEqual(window.distributions("F", 1, YEAR_US//2+1, .03, 100, 90, .5, "mean")["target_lease"], .23)
        self.assertIsNone(window.distributions("F", 1, 1, .03, 100, 90, .5, "mean"))

    def test_payload_validation_and_legacy_defaults(self):
        cfg = PairedConfig.from_payload(dict(paired_selection_mode="amortized_rank",
            paired_repricing_mode="rolling_distribution", paired_lease_target_alpha="0.7", paired_lease_target_combine="max"))
        self.assertEqual((cfg.lease_target_alpha, cfg.lease_target_combine), (.7, "max"))
        for kwargs in ({"lease_target_alpha": 1.1}, {"lease_target_alpha": -1},
                       {"lease_target_alpha": float("nan")}, {"lease_target_combine": "median"},
                       {"repricing_mode": "rolling_distribution"}):
            with self.assertRaises(ValueError):
                PairedConfig(**kwargs)
        self.assertEqual(PairedConfig().repricing_mode, "fixed")


class DistributionExecutionTests(unittest.TestCase):
    def test_repeated_bootstrap_does_not_double_count_seed_trades(self):
        config=PairedConfig(selection_mode="amortized_rank",repricing_mode="rolling_distribution")
        account=PairedTransferAccount(1000,config=config,expiries={"F":YEAR_US})
        account.marks["F"]=trade(0,"F",90)
        account.initialize_spot(trade(1))
        account.bootstrap_observations()
        self.assertEqual(account.lease_window.statistics("F",1)["count"],1)
        self.assertEqual(account.lease_window.statistics("SPOT",1)["count"],1)

    def account(self, price=90, **settings):
        account, rows = legacy.RollingLeaseTests().account(price, **settings)
        account.config.repricing_mode = "rolling_distribution"
        account.lease_window = RollingLeaseDistributionWindow(account.config.lease_window_seconds)
        for symbol, mark in account.observed_marks.items():
            account.lease_window.observe(symbol, mark.price, account._source_us(mark), account.observed_available_us[symbol])
        return account, rows

    def test_partial_market_hedge_crosses_old_cap_after_delays_and_restart(self):
        account, rows = self.account(response_delay_seconds=.1, decision_delay_seconds=.1,
                                     order_delay_seconds=.1)
        account.decide(1)
        account.accrue(200002)
        account.on_trade(trade(200003, price=101, btc=.1, side="sell"))
        self.assertEqual(account.fill_count, 1)
        cap = account.orders["F"].limit_price
        account.on_trade(trade(400000, "F", cap+1, .1))
        self.assertEqual(account.fill_count, 1)
        restored = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())))
        for a in (account, restored):
            a.on_trade(trade(500003, "F", cap+1, .05))
            self.assertEqual(a.fill_count, 1)
            a.on_trade(trade(500004, "F", cap+1, .05))
            a.on_trade(trade(600005, "F", cap+1, .2))
            a.accrue(800006)
        self.assertEqual(account.snapshot(), restored.snapshot())
        executions = [r for r in rows if r["kind"] == "lease_execution"]
        self.assertEqual(len(executions), 2)
        self.assertEqual(executions[0]["hit_order_revision"], executions[1]["hit_order_revision"])
        self.assertLess(abs(account.reconstruction_error()), 1e-8)
        self.assertGreaterEqual(account.free_collateral, -1e-8)

    def test_target_first_requires_existing_funding(self):
        account, rows = self.account()
        pair = account.decide(1)
        account.on_trade(trade(2, "F", 89, .1))
        self.assertEqual(account.fill_count, 0)
        account.ledger.execute_fill("SPOT", -.2, 100, "cash-buffer")
        account.known_units = dict(account.units)
        account.on_trade(trade(3, "F", 89, .1))
        self.assertGreater(pair.target_filled_btc, 0)
        self.assertTrue(account.orders["SPOT"].market_order)
        account.on_trade(trade(4, price=99, btc=.2, side="sell"))
        self.assertAlmostEqual(pair.unpaired_btc, 0)
        self.assertEqual(next(r for r in rows if r["kind"] == "lease_execution")["first_role"], "target")

    def test_separate_targets_are_used_on_entry_exit_and_not_adjusted_again(self):
        account, _ = self.account()
        account.on_trade(trade(1, "F", 95))
        account.on_trade(trade(2, price=102))
        for combine in ("min", "max", "mean"):
            account.config.lease_target_combine = combine
            for source, target in (("SPOT", "F"), ("F", "SPOT")):
                context = account._rolling_context(3, source, target)
                rate = context["rates"]["F"]
                self.assertEqual(rate["execution_delta"], 0)
                self.assertEqual(rate["target_combine"], combine)
                self.assertAlmostEqual(context["factors"]["F"], 1+(.04-rate["target_lease"])*rate["years"])
                self.assertEqual(rate["current_spot_price"], 102)
                self.assertEqual(rate["current_future_price"], 95)

    def test_delayed_current_and_history_are_causal(self):
        account, _ = self.account(futures_feed_delay_seconds=1)
        self.assertIsNone(account._rolling_context(500000, "SPOT", "F"))
        account.accrue(1000000)
        account.on_trade(trade(2000000, "F", 120))
        before = account._rolling_context(2000000, "SPOT", "F")["rates"]["F"]
        self.assertEqual(before["current_future_price"], 90)
        self.assertEqual(before["future_history"]["maximum"], 90)
        account.accrue(3000000)
        after = account._rolling_context(3000000, "SPOT", "F")["rates"]["F"]
        self.assertEqual(after["current_future_price"], 120)
        self.assertEqual(after["future_history"]["maximum"], 120)

    def test_runner_costs_funding_audit_and_both_anchors(self):
        for anchor in ("relative_price", "spot"):
            p, store, coverage = scenario()
            p.update(paired_selection_mode="amortized_rank", paired_repricing_mode="rolling_distribution",
                     paired_limit_anchor=anchor, paired_max_delta_btc=.2,
                     paired_lease_target_alpha=.5, paired_lease_target_combine="mean",
                     paired_expected_hedge_slippage_bps=0)
            result, rows, _ = run_case(p, store, coverage)
            summary = result["trade_replay"]["paired_transfer"]
            self.assertEqual(summary["repricing_mode"], "rolling_distribution")
            self.assertEqual(summary["lease_target_combine"], "mean")
            self.assertGreater(summary["completed"], 0)
            self.assertEqual(result["trade_replay"]["collateral_breach_count"], 0)
            self.assertLess(result["trade_replay"]["max_nav_reconstruction_error_usd"], 1e-7)
            executions = [r for r in rows["btc_trade_events"] if r["kind"] == "lease_execution"]
            self.assertTrue(executions)
            for row in executions:
                rates = row["lease_context"]["rates"][row["symbol"]]
                self.assertIn("spot_history_leases", rates)
                self.assertIn("future_history_leases", rates)


if __name__ == "__main__":
    unittest.main()
