import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


if __name__ == "__main__":
    unittest.main()
