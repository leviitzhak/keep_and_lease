import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public"))

from backtest_silver_lease_strategy import Parameters, positions_for_day


class ShortBookToggleTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"symbol": "near", "lease": -0.10, "days": 30, "volume": 100},
            {"symbol": "far", "lease": 0.02, "days": 90, "volume": 50},
        ]

    def test_disabled_short_book_has_no_short_or_matched_extension(self):
        position = positions_for_day(
            self.candidates, Parameters(min_days=10, enable_short_book=False))
        self.assertEqual(position["shorts"], {})
        self.assertEqual(position["long_extension"], 0.0)
        self.assertEqual(position["extension_ratio"], 0.0)
        self.assertEqual(position["slv"], position["base_slv"])
        self.assertEqual(position["treasury"], position["base_treasury"])
        self.assertEqual(position["longs"], position["base_longs"])

    def test_short_book_remains_enabled_by_default(self):
        position = positions_for_day(self.candidates, Parameters(min_days=10))
        self.assertGreater(sum(position["shorts"].values()), 0.0)
        self.assertAlmostEqual(
            position["long_extension"], sum(position["shorts"].values()))


if __name__ == "__main__":
    unittest.main()
