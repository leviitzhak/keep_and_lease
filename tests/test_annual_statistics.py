import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "public" / "silver_strategy_gui.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("silver_strategy_gui", MODULE_PATH)
GUI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUI)


class AnnualStatisticsTests(unittest.TestCase):
    def test_compounds_returns_and_averages_available_lease_by_year(self):
        rows = [
            {"date": "2020-01-02", "interval_return_pct": 10,
             "slv_daily_return_pct": 5, "long_weighted_lease_rate_pct": 2,
             "long_futures_daily_return_pct": 10,
             "short_futures_daily_return_pct": -5,
             "short_weighted_lease_rate_pct": -3,
             "long_futures_trade_details": [
                 {"action": "entry", "price": 20, "size_pct": 10}],
             "short_futures_trade_details": [
                 {"action": "entry", "price": 22, "size_pct": 5}]},
            {"date": "2020-01-03", "interval_return_pct": -10,
             "slv_daily_return_pct": 5, "long_weighted_lease_rate_pct": 4,
             "long_futures_daily_return_pct": -5,
             "short_futures_daily_return_pct": 10,
             "short_weighted_lease_rate_pct": None,
             "long_futures_trade_details": [
                 {"action": "entry", "price": 30, "size_pct": 30},
                 {"action": "exit", "price": 25, "size_pct": 8}],
             "short_futures_trade_details": [
                 {"action": "exit", "price": 21, "size_pct": 4}]},
            {"date": "2021-01-04", "interval_return_pct": 1,
             "slv_daily_return_pct": -2, "long_weighted_lease_rate_pct": None,
             "long_futures_daily_return_pct": 3,
             "short_futures_daily_return_pct": 4,
             "short_weighted_lease_rate_pct": -1},
        ]

        result = GUI.annual_statistics(rows)

        self.assertEqual([row["year"] for row in result], ["2020", "2021"])
        self.assertAlmostEqual(result[0]["mean_long_lease_rate_pct"], 3)
        self.assertAlmostEqual(result[0]["mean_short_lease_rate_pct"], -3)
        self.assertAlmostEqual(result[0]["strategy_return_pct"], -1)
        self.assertAlmostEqual(result[0]["silver_return_pct"], 10.25)
        self.assertAlmostEqual(result[0]["long_buy_vwap"], 27.5)
        self.assertAlmostEqual(result[0]["long_sale_vwap"], 25)
        self.assertAlmostEqual(result[0]["short_sale_vwap"], 22)
        self.assertAlmostEqual(result[0]["short_buy_vwap"], 21)
        self.assertAlmostEqual(result[0]["long_rolling_return_pct"], 4.5)
        self.assertAlmostEqual(result[0]["short_rolling_return_pct"], 4.5)
        self.assertAlmostEqual(result[0]["long_vwap_ratio_pct"], 100 * (25 / 27.5 - 1))
        self.assertAlmostEqual(result[0]["short_vwap_ratio_pct"], 100 * (22 / 21 - 1))
        self.assertIsNone(result[1]["mean_long_lease_rate_pct"])


if __name__ == "__main__":
    unittest.main()
