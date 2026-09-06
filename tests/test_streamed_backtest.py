"""Streaming changes retention only, including full audit and inverse balances."""
import copy
import importlib.util
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import silver_strategy_gui as gui
from backtest_silver_lease_strategy import Parameters, run_backtest


class StreamedBacktestTests(unittest.TestCase):
    def market(self):
        start = datetime(2026, 6, 8)
        times = [start + timedelta(minutes=i) for i in range(8)]
        spot = dict(zip(times, [100, 101, 99, 103, 104, 102, 103, 105]))
        contracts = {"BTC-test": {d: s * 0.99 for d, s in spot.items()}}
        rates = {t: [(start - timedelta(days=1), 0.03)]
                 for t in (91, 182, 365, 730, 1095, 1825)}
        curves = {d: [{"symbol": "BTC-test", "future": s * 0.99,
                       "spot": s, "days": 30, "rate": 0.03,
                       "premium": -0.01, "lease": 0.15, "volume": 10}]
                  for d, s in spot.items()}
        return spot, contracts, rates, curves

    def test_full_audit_stream_and_projected_rows_equal_legacy(self):
        for kind in ("regular", "inverse"):
            for lag in ("same_day", "next_day"):
                with self.subTest(kind=kind, lag=lag):
                    p = Parameters(min_days=1, futures_contract_type=kind,
                                   inverse_min_conversion_btc=1,
                                   reactivity=lag, trading_calendar="all_days",
                                   execution_interval_seconds=60, enable_short_book=False)
                    expected, missing = run_backtest(*self.market(), p)
                    audit = []
                    projected, actual_missing = run_backtest(
                        *self.market(), p, row_sink=audit.append,
                        retain_fields=("nav", "date"))
                    self.assertEqual(audit, expected)
                    self.assertTrue(all(row["holding_ledger"] for row in audit))
                    self.assertEqual(projected, [{k: r[k] for k in ("nav", "date")}
                                                 for r in expected])
                    self.assertEqual(missing, actual_missing)
                    collected = []
                    rows, _ = run_backtest(*self.market(), p,
                                          row_sink=collected.append, retain_fields=())
                    self.assertEqual(rows, [])
                    self.assertEqual(collected, expected)

    def test_sink_failure_propagates(self):
        def fail(row):
            raise OSError("audit destination unavailable")
        with self.assertRaisesRegex(OSError, "audit destination"):
            run_backtest(*self.market(), Parameters(min_days=1),
                         row_sink=fail, retain_fields=())

    def test_gui_comparison_summaries_are_unchanged(self):
        payload = {"min_days": 1, "execution_interval_seconds": 60,
                   "commodity_parameters": {"btc": {"futures_contract_type": "regular"}}}
        actual = gui.sleeve_result(payload, self.market(), "btc")
        def legacy(*args, **kwargs):
            kwargs.pop("retain_fields", None)
            return run_backtest(*args, **kwargs)
        with patch.object(gui, "run_backtest", side_effect=legacy):
            expected = gui.sleeve_result(payload, self.market(), "btc")
        self.assertEqual(actual, expected)

    def test_research_stale_control_uses_only_past_observed_basis(self):
        path = Path(__file__).resolve().parents[1] / "scripts/check-btc-minute-backtest.py"
        spec = importlib.util.spec_from_file_location("btc_check", path)
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        market = self.market()
        dates = sorted(market[0])
        for d in dates[1:4]:
            market[3][d][0]["volume"] = 0
            market[3][d][0]["future"] = market[1]["BTC-test"][d] = 99
        other = copy.deepcopy(market)
        other[3][dates[5]][0]["future"] = 1000
        other[1]["BTC-test"][dates[5]] = 1000
        check.spot_linked_stale_control(market)
        check.spot_linked_stale_control(other)
        for d in dates[:5]:
            self.assertEqual(market[3][d], other[3][d])
        self.assertAlmostEqual(market[1]["BTC-test"][dates[2]], 0.99 * market[0][dates[2]])
        payload = check.btc_payload()
        self.assertEqual(payload["commodity_parameters"]["btc"]["futures_contract_type"], "regular")


if __name__ == "__main__":
    unittest.main()
