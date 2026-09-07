import unittest

from maturity_scoring import (
    BoundaryAnchors,
    RelativeAdjustment,
    adjusted_score,
    allocate_scores,
    score_contracts,
    signed_distance,
)
from rate_change_attribution import (
    InstrumentAttribution,
    absolute_notional_weighted_maturity,
    build_rate_change_point,
    group_scatter_points,
)


class BoundaryAnchorTests(unittest.TestCase):
    def test_boundary_passes_through_both_anchors(self):
        boundary = BoundaryAnchors(30, 0.01, 365, 0.05)
        self.assertAlmostEqual(boundary.value(30), 0.01)
        self.assertAlmostEqual(boundary.value(365), 0.05)

    def test_rejects_non_increasing_maturities(self):
        with self.assertRaises(ValueError):
            BoundaryAnchors(365, 0.01, 30, 0.05)

    def test_slope_intercept_migration_preserves_line(self):
        old_slope = 0.0001
        old_intercept = 0.012
        boundary = BoundaryAnchors.from_slope_intercept(
            30, 730, old_slope, old_intercept)
        for maturity in (30, 180, 365, 730):
            self.assertAlmostEqual(
                boundary.value(maturity),
                old_intercept + old_slope * maturity,
            )


class RelativeScoringTests(unittest.TestCase):
    def setUp(self):
        self.boundary = BoundaryAnchors(30, 0.01, 365, 0.05)
        self.adjustment = RelativeAdjustment(
            strength=0.5, rate_scale=0.01, clip=2.0)

    def test_higher_long_rate_increases_adjustment(self):
        low = adjusted_score(1.0, 0.03, 180, self.boundary,
                             self.adjustment, "long")
        high = adjusted_score(1.0, 0.04, 180, self.boundary,
                              self.adjustment, "long")
        self.assertGreater(high, low)

    def test_more_negative_short_rate_increases_adjustment(self):
        mild = adjusted_score(1.0, -0.03, 180, self.boundary,
                              self.adjustment, "short")
        deep = adjusted_score(1.0, -0.04, 180, self.boundary,
                              self.adjustment, "short")
        self.assertGreater(deep, mild)

    def test_equal_distances_produce_equal_multipliers(self):
        maturity_a, maturity_b = 90, 300
        distance = 0.007
        rate_a = self.boundary.value(maturity_a) + distance
        rate_b = self.boundary.value(maturity_b) + distance
        score_a = adjusted_score(2.0, rate_a, maturity_a, self.boundary,
                                 self.adjustment, "long")
        score_b = adjusted_score(2.0, rate_b, maturity_b, self.boundary,
                                 self.adjustment, "long")
        self.assertAlmostEqual(score_a, score_b)

    def test_zero_strength_reproduces_base_score(self):
        adjustment = RelativeAdjustment(
            strength=0.0, rate_scale=0.01, clip=2.0)
        self.assertEqual(
            adjusted_score(1.7, 0.20, 365, self.boundary,
                           adjustment, "long"),
            170.0,
        )

    def test_extreme_adjustment_is_clipped_and_non_negative(self):
        self.assertEqual(self.adjustment.normalized(10.0), 2.0)
        self.assertEqual(self.adjustment.normalized(-10.0), -2.0)
        self.assertEqual(self.adjustment.multiplier(-10.0), 0.0)

    def test_softmax_accepts_negative_logits_and_preserves_target(self):
        weights = allocate_scores({"below": -2.0, "above": 1.0}, 0.75)
        self.assertGreater(weights["below"], 0.0)
        self.assertGreater(weights["above"], weights["below"])
        self.assertAlmostEqual(sum(weights.values()), 0.75)

    def test_equal_logits_split_the_target_equally(self):
        weights = allocate_scores({"A": 0.0, "B": 0.0}, 1.0)
        self.assertAlmostEqual(weights["A"], 0.5)
        self.assertAlmostEqual(weights["B"], 0.5)

    def test_below_line_eligible_contract_keeps_positive_weight(self):
        contracts = [
            {"symbol": "A", "days": 100, "lease": 0.001},
            {"symbol": "B", "days": 200, "lease": 0.002},
        ]
        weights, diagnostics = score_contracts(
            contracts, direction="long", eligibility_threshold=0.0,
            boundary=self.boundary, adjustment=self.adjustment, target=1.0)
        self.assertEqual(set(weights), {"A", "B"})
        self.assertGreater(weights["A"], 0.0)
        self.assertGreater(weights["B"], 0.0)
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertTrue(all(row["final_score"] < 0 for row in diagnostics))

    def test_short_distance_uses_negative_rate(self):
        maturity = 180
        expected = 0.04 - self.boundary.value(maturity)
        self.assertAlmostEqual(
            signed_distance(-0.04, maturity, self.boundary, "short"),
            expected,
        )

    def test_ineligible_contracts_never_receive_weight(self):
        contracts = [
            {"symbol": "A", "days": 100, "lease": 0.04},
            {"symbol": "B", "days": 200, "lease": -0.02},
        ]
        weights, diagnostics = score_contracts(
            contracts, direction="long", eligibility_threshold=0.0,
            boundary=self.boundary, adjustment=self.adjustment, target=0.6)
        self.assertIn("A", weights)
        self.assertNotIn("B", weights)
        self.assertAlmostEqual(sum(weights.values()), 0.6)
        row_b = next(row for row in diagnostics if row["symbol"] == "B")
        self.assertFalse(row_b["eligible"])
        self.assertEqual(row_b["target_weight"], 0.0)


class AttributionTests(unittest.TestCase):
    def test_absolute_notional_weighted_maturity(self):
        instruments = [
            InstrumentAttribution("A", 2.0, 30, 1.1, 1.0),
            InstrumentAttribution("B", -1.0, 120, 0.9, 1.0),
        ]
        self.assertAlmostEqual(
            absolute_notional_weighted_maturity(instruments), 60.0)

    def test_signed_holdings_drive_rate_change_pnl(self):
        instruments = [
            InstrumentAttribution("LONG", 2.0, 90, 1.02, 1.00),
            InstrumentAttribution("SHORT", -1.0, 180, 1.03, 1.00),
        ]
        point = build_rate_change_point(
            start_date="2026-01-02", end_date="2026-01-05",
            leg="mixed", commodity="silver", instruments=instruments,
            portfolio_value=10.0)
        self.assertAlmostEqual(point["rate_change_pnl"], 0.01)
        self.assertAlmostEqual(point["portfolio_relative_return"], 0.001)
        self.assertAlmostEqual(point["position_relative_return"], 0.01 / 3)

    def test_point_uses_start_maturity_and_start_instruments(self):
        held = [InstrumentAttribution("OLD", 1.0, 45, 1.01, 1.00)]
        point = build_rate_change_point(
            start_date="2026-01-02", end_date="2026-01-05",
            leg="long", commodity="gold", instruments=held,
            portfolio_value=1.0)
        self.assertEqual(point["weighted_maturity"], 45)
        self.assertEqual(point["instruments"][0]["symbol"], "OLD")
        self.assertNotIn("NEW", [x["symbol"] for x in point["instruments"]])

    def test_zero_position_is_excluded(self):
        point = build_rate_change_point(
            start_date="2026-01-02", end_date="2026-01-05",
            leg="long", commodity="silver", instruments=[],
            portfolio_value=1.0)
        self.assertTrue(point["excluded"])
        self.assertIsNotNone(point["exclusion_reason"])

    def test_scatter_groups_every_leg_commodity_pair(self):
        base = {
            "excluded": False,
            "weighted_maturity": 90,
            "position_relative_return": 0.01,
        }
        grouped = group_scatter_points([
            {**base, "leg": "long", "commodity": "silver"},
            {**base, "leg": "short", "commodity": "silver"},
            {**base, "leg": "treasury", "commodity": "cash"},
            {**base, "leg": "long", "commodity": "gold", "excluded": True},
        ])
        self.assertEqual(set(grouped), {
            "long::silver", "short::silver", "treasury::cash"})


if __name__ == "__main__":
    unittest.main()
