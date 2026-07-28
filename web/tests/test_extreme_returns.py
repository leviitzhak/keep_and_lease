import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "public"
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("silver_strategy_gui", ROOT / "silver_strategy_gui.py")
GUI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUI)


class ExtremeReturnStatisticsTests(unittest.TestCase):
    def test_counts_strictly_above_one_percent_and_lists_ten_highest(self):
        values = [1.0, -2.0, *range(2, 14)]
        rows = [{"date": f"2020-01-{i:02d}", "interval_return_pct": value,
                 "nav": 1 + i / 100,
                 "silver_price_return_contribution_pct": value,
                 "lease_carry_contribution_pct": 0,
                 "lease_rate_change_contribution_pct": 0,
                 "rolling_contribution_pct": 0,
                 "treasury_return_contribution_pct": 0,
                 "slv_expense_contribution_pct": 0,
                 "other_return_contribution_pct": 0}
                for i, value in enumerate(values, 1)]
        result = GUI.extreme_return_statistics(rows)
        self.assertEqual(result["count"], 12)
        self.assertEqual(len(result["highest"]), 10)
        self.assertEqual(result["highest"][0]["return_pct"], 13)
        self.assertEqual(result["highest"][-1]["return_pct"], 4)
        self.assertEqual(len(result["lowest"]), 10)
        self.assertEqual(result["lowest"][0]["return_pct"], -2)
        self.assertAlmostEqual(result["highest"][0]["reconciled_pct"], 13)


if __name__ == "__main__":
    unittest.main()
