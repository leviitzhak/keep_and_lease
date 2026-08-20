import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public"))

from backtest_silver_lease_strategy import (Parameters, _sticky_contract_book,
                                             maturity_line_adjusted_score,
                                             maturity_line_score)


class RollPolicyTests(unittest.TestCase):
    def setUp(self):
        self.p = Parameters(min_days=10)
        self.contracts = {
            "held": {"lease": 0.02, "days": 40},
            "candidate": {"lease": 0.01, "days": 80},
        }

    def test_long_keeps_held_contract_when_candidate_lease_is_lower(self):
        result = _sticky_contract_book(
            {"candidate": 0.4}, {"held": 0.3}, self.contracts,
            set(self.contracts), "long", self.p)
        self.assertEqual(result, {"held": 0.4})

    def test_short_rolls_when_candidate_lease_is_lower(self):
        result = _sticky_contract_book(
            {"candidate": 0.4}, {"held": 0.3}, self.contracts,
            set(self.contracts), "short", self.p)
        self.assertEqual(result, {"candidate": 0.4})

    def test_minimum_days_forces_roll_even_without_better_lease(self):
        self.contracts["held"]["days"] = 10
        result = _sticky_contract_book(
            {"candidate": 0.4}, {"held": 0.3}, self.contracts,
            set(self.contracts), "long", self.p)
        self.assertEqual(result, {"candidate": 0.4})

    def test_forced_roll_can_be_disabled(self):
        self.p.force_roll_at_min_days = False
        self.contracts["held"]["days"] = 5
        result = _sticky_contract_book(
            {"candidate": 0.4}, {"held": 0.3}, self.contracts,
            {"candidate"}, "long", self.p)
        self.assertEqual(result, {"held": 0.4})

    def test_long_maturity_line_score_is_signed_distance(self):
        p = Parameters(min_days=10, long_maturity_line_intercept=0.02,
                       long_maturity_line_slope_per_year=0.01)
        self.assertAlmostEqual(
            maturity_line_score({"lease": 0.04, "days": 365}, p, "long"),
            0.01)
        self.assertAlmostEqual(
            maturity_line_score({"lease": 0.02, "days": 365}, p, "long"),
            -0.01)

    def test_short_maturity_line_uses_absolute_lease(self):
        p = Parameters(min_days=10, short_maturity_line_intercept=0.02,
                       short_maturity_line_slope_per_year=0.01)
        self.assertAlmostEqual(
            maturity_line_score({"lease": -0.04, "days": 365}, p, "short"),
            0.01)
        self.assertAlmostEqual(
            maturity_line_score({"lease": -0.02, "days": 365}, p, "short"),
            -0.01)

    def test_line_distance_changes_existing_score_relatively(self):
        long_p = Parameters(
            min_days=10, long_maturity_line_intercept=0.02,
            long_maturity_line_slope_per_year=0.01)
        short_p = Parameters(
            min_days=10, short_maturity_line_intercept=0.02,
            short_maturity_line_slope_per_year=0.01)
        self.assertAlmostEqual(
            maturity_line_adjusted_score(
                0.20, {"lease": 0.036, "days": 365}, long_p, "long"),
            0.32)
        self.assertAlmostEqual(
            maturity_line_adjusted_score(
                0.20, {"lease": -0.036, "days": 365}, short_p, "short"),
            0.32)

    def test_pure_maturity_prefers_shorter_longs(self):
        p = Parameters(
            min_days=10, long_relative_strength=0,
            long_pure_maturity_strength=0.5,
            pure_maturity_scale_days=365)
        short = maturity_line_adjusted_score(
            0.20, {"lease": 0.04, "days": 90}, p, "long")
        long = maturity_line_adjusted_score(
            0.20, {"lease": 0.04, "days": 365}, p, "long")
        self.assertGreater(short, long)

    def test_pure_maturity_prefers_longer_shorts(self):
        p = Parameters(
            min_days=10, short_relative_strength=0,
            short_pure_maturity_strength=0.5,
            pure_maturity_scale_days=365)
        short = maturity_line_adjusted_score(
            0.20, {"lease": -0.04, "days": 90}, p, "short")
        long = maturity_line_adjusted_score(
            0.20, {"lease": -0.04, "days": 365}, p, "short")
        self.assertGreater(long, short)

    def test_zero_pure_maturity_strength_is_backward_compatible(self):
        p = Parameters(min_days=10, long_relative_strength=0)
        self.assertAlmostEqual(
            maturity_line_adjusted_score(
                0.20, {"lease": 0.04, "days": 365}, p, "long"),
            0.20)


if __name__ == "__main__":
    unittest.main()
