import json
import math
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

    def test_available_downloaded_markets_have_curves(self):
        self.assertEqual(set(self.markets), {"silver", "gold", "sp500"})
        for market in self.markets.values():
            self.assertTrue(market[0])
            self.assertTrue(market[1])
            self.assertTrue(market[3])
        self.assertEqual(
            set(gui.PRODUCTS) - set(self.markets),
            set(gui.MARKET_LOAD_ERRORS),
        )
        self.assertTrue(all(
            "not enabled in this deployment" in gui.MARKET_LOAD_ERRORS[key]
            for key in ("oil", "wheat", "corn", "soybeans")
        ))

    def test_gold_and_oil_use_independent_spot_series(self):
        for key in ("gold", "oil"):
            if key not in self.markets:
                continue
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
        self.assertIn("direct_unrebalanced_compounded_return_pct",
                      result["portfolio_fields"])

    def test_daily_portfolio_contributions_reconcile(self):
        if not {"gold", "oil"}.issubset(self.markets):
            self.skipTest("gold and oil archives are unavailable")
        result = gui.result({
            "weight_silver": 40,
            "weight_gold": 35,
            "weight_oil": 25,
            "portfolio_rebalancing": "daily",
            "min_days": 30,
            "enable_short_book": "false",
        })
        contribution_indices = [
            result["fields"].index(f"{key}_contribution_pct")
            for key in result["portfolio"]["weights"]]
        for row in result["series"]:
            self.assertAlmostEqual(
                row[1], sum(row[i] for i in contribution_indices), places=11)

    def test_rebalancing_choice_changes_path(self):
        sleeves = {
            "a": {"_full_rows": [
                {"date": "2000-01-03", "exit_date": "2000-01-04", "interval_return_pct": 10,
                 "slv_daily_return_pct": 10},
                {"date": "2000-01-04", "exit_date": "2000-01-05", "interval_return_pct": 10,
                 "slv_daily_return_pct": 10},
            ]},
            "b": {"_full_rows": [
                {"date": "2000-01-03", "exit_date": "2000-01-04", "interval_return_pct": 0,
                 "slv_daily_return_pct": 0},
                {"date": "2000-01-04", "exit_date": "2000-01-05", "interval_return_pct": 0,
                 "slv_daily_return_pct": 0},
            ]},
        }
        fields, daily, _ = gui.aggregate_portfolio(
            sleeves, {"a": 0.5, "b": 0.5}, "daily")
        _, drifting, _ = gui.aggregate_portfolio(
            sleeves, {"a": 0.5, "b": 0.5}, "none")
        self.assertEqual(daily[0][fields.index("start_date")], "2000-01-03")
        self.assertEqual(daily[0][fields.index("date")], "2000-01-04")
        self.assertNotAlmostEqual(
            daily[-1][fields.index("compounded_return_pct")],
            drifting[-1][fields.index("compounded_return_pct")], places=8)
        self.assertNotAlmostEqual(
            daily[-1][fields.index("direct_compounded_return_pct")],
            daily[-1][fields.index(
                "direct_unrebalanced_compounded_return_pct")], places=8)
        strategy_nav = 1 + daily[-1][fields.index(
            "compounded_return_pct")] / 100
        factor_navs = [
            1 + daily[-1][fields.index(
                f"{key}_attributed_factor_compounded_return_pct")] / 100
            for key in ("a", "b")]
        self.assertAlmostEqual(strategy_nav, math.prod(factor_navs))

    def test_hierarchical_daily_attribution_reconciles(self):
        if not {"gold", "oil"}.issubset(self.markets):
            self.skipTest("gold and oil archives are unavailable")
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
        if "gold" not in self.markets:
            self.skipTest("gold archive is unavailable")
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
        contribution_indices = [
            result["fields"].index(f"{key}_contribution_pct")
            for key in result["portfolio"]["weights"]]
        for row in result["series"]:
            self.assertAlmostEqual(
                row[1], sum(row[i] for i in contribution_indices), places=11)

    def test_treasury_can_run_as_standalone_portfolio(self):
        result = gui.result({
            "weight_silver": 0,
            "weight_treasury": 100,
            "min_days": 30,
        })
        self.assertEqual(result["portfolio"]["weights"], {"treasury": 1.0})
        self.assertEqual(result["commodity_sleeves"], {})
        treasury_index = result["fields"].index("treasury_contribution_pct")
        for row in result["series"]:
            self.assertAlmostEqual(row[1], row[treasury_index], places=11)

    def test_product_specific_parameters_override_global_values(self):
        payload = gui.product_payload({
            "positive_entry_rate": 1,
            "commodity_parameters": {
                "gold": {"positive_entry_rate": 3},
            },
            "gold__max_futures_treasury_fraction": 25,
        }, "gold")
        self.assertEqual(payload["positive_entry_rate"], 3)
        self.assertEqual(payload["max_futures_treasury_fraction"], 25)

    def test_unavailable_market_has_actionable_error(self):
        unavailable = next(
            (key for key in gui.PRODUCTS if key not in self.markets), None)
        if unavailable is None:
            self.skipTest("all market archives are available")
        with self.assertRaisesRegex(
                ValueError, "Set those proportions to zero"):
            gui.result({
                "weight_silver": 0,
                f"weight_{unavailable}": 100,
            })

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
