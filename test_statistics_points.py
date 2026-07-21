import importlib.util
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "public" / "silver_strategy_gui.py"
SPEC = importlib.util.spec_from_file_location("silver_strategy_gui", MODULE_PATH)
GUI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUI)


class StatisticsPointsTests(unittest.TestCase):
    def test_pairs_lease_with_same_contract_next_quote_return(self):
        first = date(2026, 1, 2)
        next_day = date(2026, 1, 5)
        contracts = {"SIH26": {first: 100.0, next_day: 102.0}}
        by_day = {
            first: [{"symbol": "SIH26", "days": 60, "lease": 0.03,
                     "premium": 0.01}],
            next_day: [{"symbol": "SIH26", "days": 57, "lease": 0.02,
                        "premium": 0.008}],
        }

        points = GUI.statistics_points(
            by_day, contracts, SimpleNamespace(min_days=10))

        self.assertEqual(points[0]["next_date"], "2026-01-05")
        self.assertEqual(points[0]["next_elapsed_days"], 3)
        self.assertAlmostEqual(points[0]["next_return_pct"], 2.0)
        self.assertIsNone(points[1]["next_return_pct"])
