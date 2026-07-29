import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public"))

from backtest_silver_lease_strategy import Parameters, positions_for_day
from silver_strategy_gui import parameters


class LegAndEntryModeTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"symbol": "negative", "lease": -0.10, "days": 30, "volume": 100},
            {"symbol": "positive", "lease": 0.02, "days": 90, "volume": 50},
        ]

    def test_negative_long_thresholds_are_valid_when_ordered(self):
        p = parameters({"positive_entry_rate": "-20", "positive_full_rate": "-10"})
        self.assertEqual(p.positive_entry_rate, -0.20)
        self.assertEqual(p.positive_full_rate, -0.10)

    def test_fixed_modes_jump_to_full_positions(self):
        p = Parameters(
            min_days=10, slv_entry_mode="fixed",
            long_futures_entry_mode="fixed", short_futures_entry_mode="fixed")
        position = positions_for_day(self.candidates, p)
        self.assertEqual(position["base_slv"], 1.0)
        self.assertAlmostEqual(sum(position["base_longs"].values()), p.max_long_future)
        self.assertAlmostEqual(sum(position["shorts"].values()),
                               p.max_short_fraction_of_slv)

    def test_fixed_modes_ignore_all_entry_conditions(self):
        p = Parameters(
            min_days=10, slv_entry_mode="fixed",
            long_futures_entry_mode="fixed", short_futures_entry_mode="fixed",
            slv_start_rate=-1.0, positive_entry_rate=1.0,
            negative_short_start_rate=-1.0)
        position = positions_for_day(self.candidates, p)
        self.assertEqual(position["base_slv"], 1.0)
        self.assertAlmostEqual(sum(position["base_longs"].values()),
                               p.max_long_future)
        self.assertAlmostEqual(sum(position["shorts"].values()),
                               p.max_short_fraction_of_slv)

    def test_slv_can_be_disabled_independently(self):
        position = positions_for_day(
            self.candidates, Parameters(min_days=10, enable_slv_leg=False))
        self.assertEqual(position["base_slv"], 0.0)
        self.assertEqual(position["base_treasury"], 1.0)

    def test_cash_and_long_futures_can_be_disabled_independently(self):
        position = positions_for_day(
            self.candidates,
            Parameters(min_days=10, enable_cash_long_futures_leg=False,
                       enable_short_book=False))
        self.assertEqual(position["base_treasury"], 0.0)
        self.assertEqual(position["base_longs"], {})
        self.assertGreater(position["base_slv"], 0.0)

    def test_short_book_is_zero_when_no_long_composition_exists(self):
        position = positions_for_day(
            self.candidates,
            Parameters(min_days=10, enable_slv_leg=False,
                       enable_cash_long_futures_leg=False))
        self.assertEqual(position["shorts"], {})
        self.assertEqual(position["long_extension"], 0.0)

    def test_allocation_thresholds_do_not_change_relative_long_contract_weights(self):
        candidates = [
            {"symbol": "near", "lease": 0.04, "days": 30, "volume": 100},
            {"symbol": "far", "lease": 0.03, "days": 395, "volume": 100},
        ]
        common = dict(
            min_days=10, long_contract_selection="weighted_lease_rate",
            long_maturity_line_intercept=0.0,
            long_maturity_line_slope_per_year=0.0)
        low = positions_for_day(
            candidates, Parameters(**common, positive_entry_rate=0.00,
                                   positive_full_rate=0.10))
        high = positions_for_day(
            candidates, Parameters(**common, positive_entry_rate=0.02,
                                   positive_full_rate=0.20))
        low_mix = {k: v / sum(low["base_longs"].values())
                   for k, v in low["base_longs"].items()}
        high_mix = {k: v / sum(high["base_longs"].values())
                    for k, v in high["base_longs"].items()}
        for symbol in low_mix:
            self.assertAlmostEqual(low_mix[symbol], high_mix[symbol])

    def test_maturity_line_rewards_contract_above_line(self):
        candidates = [
            {"symbol": "near", "lease": 0.021, "days": 30, "volume": 100},
            {"symbol": "far", "lease": 0.04, "days": 395, "volume": 100},
        ]
        position = positions_for_day(
            candidates, Parameters(
                min_days=10, long_contract_selection="weighted_lease_rate",
                long_maturity_line_intercept=0.02,
                long_maturity_line_slope_per_year=0.01))
        self.assertGreater(position["base_longs"]["far"],
                           position["base_longs"]["near"])


if __name__ == "__main__":
    unittest.main()
