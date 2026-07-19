import unittest
from datetime import date

from backtest_silver_lease_strategy import Parameters, positions_for_day, run_backtest


class StandaloneLegReturnTests(unittest.TestCase):
    def setUp(self):
        self.days = [date(2020, 1, day) for day in range(1, 6)]
        self.spot = dict(zip(self.days, [100, 110, 121, 133.1, 146.41]))
        self.contracts = {
            "near": dict(zip(self.days, [100, 102, 104.04, 106.1208, 108.243216])),
            "far": dict(zip(self.days, [100, 99, 98.01, 97.0299, 96.059601])),
        }
        self.rates = {tenor: [(self.days[0], 0.0)] for tenor in
                      (91, 182, 365, 730, 1095, 1825)}
        candidates = [
            {"symbol": "near", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.0, "volume": 10},
            {"symbol": "far", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.0, "volume": 5},
        ]
        self.by_day = {day: [dict(item) for item in candidates]
                       for day in self.days}

    def test_leg_contracts_are_selected_even_when_thresholds_disable_trades(self):
        position = positions_for_day(self.by_day[self.days[0]], Parameters(min_days=1))
        self.assertEqual({}, position["longs"])
        self.assertEqual({}, position["shorts"])
        self.assertEqual({"near": 1.0}, position["long_leg"])
        self.assertEqual(1.0, sum(position["short_leg"].values()))

    def test_leg_returns_ignore_zero_portfolio_weights(self):
        rows, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1, slv_start_rate=-0.20,
                       slv_full_rate=-0.30, slv_expense=0))
        self.assertTrue(all(row["slv_weight_pct"] == 0 for row in rows))
        self.assertTrue(all(row["long_futures_notional_pct"] == 0 for row in rows))
        self.assertTrue(all(row["short_futures_notional_pct"] == 0 for row in rows))
        self.assertAlmostEqual(10.0, rows[0]["slv_daily_return_pct"])
        self.assertAlmostEqual(2.0, rows[0]["long_futures_daily_return_pct"])
        self.assertIsNotNone(rows[0]["short_futures_daily_return_pct"])

    def test_short_leg_uses_strategy_maturities_when_short_is_nonzero(self):
        candidates = [
            {"symbol": "negative", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.10, "volume": 10},
            {"symbol": "positive", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.10, "volume": 5},
        ]
        position = positions_for_day(candidates, Parameters(min_days=1))
        self.assertGreater(sum(position["shorts"].values()), 0)
        self.assertEqual(position["shorts"], position["short_leg"])
        self.assertEqual({"negative"}, set(position["short_leg"]))


if __name__ == "__main__":
    unittest.main()
