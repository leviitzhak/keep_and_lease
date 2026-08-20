import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public"))

from silver_strategy_gui import parameters


class ScoringParameterTests(unittest.TestCase):
    def test_two_anchor_gui_boundary_reaches_engine(self):
        p = parameters({
            "long_line_maturity_1": "30",
            "long_line_rate_1": "1",
            "long_line_maturity_2": "395",
            "long_line_rate_2": "3",
            "short_line_maturity_1": "30",
            "short_line_rate_1": "2",
            "short_line_maturity_2": "395",
            "short_line_rate_2": "5",
            "long_score_rate_scale": "2",
            "short_score_rate_scale": "4",
        })
        self.assertAlmostEqual(p.long_maturity_line_slope_per_year, 0.02)
        self.assertAlmostEqual(p.short_maturity_line_slope_per_year, 0.03)
        self.assertAlmostEqual(p.long_score_rate_scale, 0.02)
        self.assertAlmostEqual(p.short_score_rate_scale, 0.04)

    def test_legacy_intercept_slope_payload_remains_supported(self):
        p = parameters({
            "long_maturity_line_intercept": "2",
            "long_maturity_line_slope_per_year": "1.5",
        })
        self.assertAlmostEqual(p.long_maturity_line_intercept, 0.02)
        self.assertAlmostEqual(p.long_maturity_line_slope_per_year, 0.015)

    def test_pure_maturity_controls_reach_engine(self):
        p = parameters({
            "long_pure_maturity_strength": "0.4",
            "short_pure_maturity_strength": "0.7",
            "pure_maturity_scale_days": "180",
            "pure_maturity_clip": "2",
        })
        self.assertEqual(p.long_pure_maturity_strength, 0.4)
        self.assertEqual(p.short_pure_maturity_strength, 0.7)
        self.assertEqual(p.pure_maturity_scale_days, 180)
        self.assertEqual(p.pure_maturity_clip, 2)


if __name__ == "__main__":
    unittest.main()
