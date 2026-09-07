import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "public"
sys.path.insert(0, str(ROOT))
from backtest_silver_lease_strategy import build_market


class ContractQuoteScalingTests(unittest.TestCase):
    def test_contract_scale_does_not_change_on_march_18_1980(self):
        _, contracts, _, _ = build_market(ROOT)
        self.assertAlmostEqual(contracts["SI80Z"][date(1980, 3, 18)], 30.27)
        self.assertAlmostEqual(contracts["SI80Z"][date(1980, 3, 19)], 29.27)
        self.assertAlmostEqual(contracts["SI81U"][date(1980, 3, 18)], 32.70)
        self.assertAlmostEqual(contracts["SI81U"][date(1980, 3, 19)], 31.70)


if __name__ == "__main__":
    unittest.main()
