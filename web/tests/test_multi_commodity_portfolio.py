import json
import sys
import unittest
from pathlib import Path


PUBLIC = Path(__file__).resolve().parents[1] / "public"
sys.path.insert(0, str(PUBLIC))

import silver_strategy_gui as gui
from backtest_silver_lease_strategy import (
    Parameters, TENORS, treasury_position_return)


class MultiCommodityPortfolioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.markets = gui.build_markets(PUBLIC)
        gui.MARKETS = cls.markets
        gui.MARKET = cls.markets["silver"]

    def test_all_downloaded_markets_have_curves(self):
        self.assertEqual(
            set(self.markets),
            {"silver", "gold", "oil", "wheat", "corn", "soybeans", "sp500"},
        )
        for market in self.markets.values():
            self.assertTrue(market[0])
            self.assertTrue(market[1])
            self.assertTrue(market[3])

    def test_gold_and_oil_use_independent_spot_series(self):
        for key in ("gold", "oil"):
            spot, contracts, _, _ = self.markets[key]
            day = next(iter(sorted(spot)))
            live = [prices[day] for prices in contracts.values() if day in prices]
            self.assertTrue(live)
            self.assertFalse(all(abs(value - spot[day]) < 1e-12 for value in live))

    def test_legacy_silver_only_result_is_json_serializable(self):
        result = gui.result({
            "weight_silver": 100,
            "portfolio_rebalancing": "daily",
            "min_days": 30,
            "enable_short_book": "false",
        })
        encoded = json.dumps(result, allow_nan=False)
        self.assertIn('"commodity_sleeves"', encoded)

    def test_daily_portfolio_contributions_reconcile(self):
        result = gui.result({
            "weight_silver": 40,
            "weight_gold": 35,
            "weight_oil": 25,
            "portfolio_rebalancing": "daily",
            "min_days": 30,
            "enable_short_book": "false",
        })
        contribution_start = 7
        for row in result["series"]:
            self.assertAlmostEqual(
                row[1], sum(row[contribution_start:]), places=11)

    def test_rebalancing_choice_changes_path(self):
        sleeves = {
            "a": {"_full_rows": [
                {"date": "2000-01-03", "interval_return_pct": 10,
                 "slv_daily_return_pct": 10},
                {"date": "2000-01-04", "interval_return_pct": 10,
                 "slv_daily_return_pct": 10},
            ]},
            "b": {"_full_rows": [
                {"date": "2000-01-03", "interval_return_pct": 0,
                 "slv_daily_return_pct": 0},
                {"date": "2000-01-04", "interval_return_pct": 0,
                 "slv_daily_return_pct": 0},
            ]},
        }
        _, daily, _ = gui.aggregate_portfolio(
            sleeves, {"a": 0.5, "b": 0.5}, "daily")
        _, drifting, _ = gui.aggregate_portfolio(
            sleeves, {"a": 0.5, "b": 0.5}, "none")
        self.assertNotAlmostEqual(daily[-1][3], drifting[-1][3], places=8)

    def test_hierarchical_daily_attribution_reconciles(self):
        result = gui.result({
            "weight_silver": 40,
            "weight_gold": 35,
            "weight_oil": 25,
            "portfolio_rebalancing": "monthly",
            "min_days": 30,
            "enable_short_book": "false",
        })
        for day in result["daily_attribution"]:
            self.assertAlmostEqual(
                day["portfolio_return_pct"], day["reconciled_pct"], places=11)
            for asset in day["assets"].values():
                self.assertAlmostEqual(
                    asset["contribution_pct"],
                    sum(asset["components"].values()), places=11)

    def test_treasury_proportion_is_normalized_with_commodities(self):
        weights = gui.portfolio_allocations({
            "weight_silver": 60,
            "weight_gold": 20,
            "weight_treasury": 20,
        })
        self.assertEqual(weights, {
            "silver": 0.6, "gold": 0.2, "treasury": 0.2,
        })

    def test_treasury_daily_contribution_reconciles(self):
        result = gui.result({
            "weight_silver": 50,
            "weight_gold": 25,
            "weight_treasury": 25,
            "portfolio_rebalancing": "daily",
            "min_days": 30,
            "enable_short_book": "false",
        })
        treasury_index = result["fields"].index("treasury_contribution_pct")
        self.assertGreaterEqual(treasury_index, 7)
        for row in result["series"]:
            self.assertAlmostEqual(
                row[1], sum(row[7:]), places=11)

    def test_rate_weighted_treasury_uses_yield_proportions(self):
        from datetime import date
        day = date(2000, 1, 3)
        next_day = date(2000, 1, 4)
        rates = {
            tenor: [(day, rate), (next_day, rate)]
            for (tenor, _), rate in zip(
                TENORS, [0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
        }
        p = Parameters(
            min_days=10, bond_mode="accrual",
            treasury_allocation_mode="rate_weighted_maturities")
        actual = treasury_position_return(rates, day, next_day, 1, p)
        expected = sum(rate * rate for rate in
                       [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]) / sum(
                           [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]) / 365
        self.assertAlmostEqual(actual, expected, places=14)


if __name__ == "__main__":
    unittest.main()
