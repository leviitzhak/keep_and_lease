import unittest

from funded_ledger import FeeSchedule
from paired_amortized_strategy import (
    evaluate_amortized_transfer, keep_amortized_return,
    rank_amortized_decisions, solve_amortized_price_limit,
)
from paired_transfer_economics import (
    EconomicsConfig, PositionSlice, QuoteSnapshot, YEAR_US,
)


class AmortizedRankingTest(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000
        self.spot = QuoteSnapshot("SPOT", 100.0, self.now, self.now)
        self.good = QuoteSnapshot("GOOD", 95.0, self.now, self.now,
                                  self.now + YEAR_US)
        self.bad = QuoteSnapshot("BAD", 110.0, self.now, self.now,
                                 self.now + YEAR_US)
        self.fees = {
            "spot": FeeSchedule(fee_bps=10),
            "futures": FeeSchedule(fee_bps=5),
            "delivery": FeeSchedule(),
        }
        self.config = EconomicsConfig(max_transfer_fraction=1,
            max_delta_btc=.2, min_improvement_bps=5)

    def test_direct_holding_is_default_and_delta_caps_transfer(self):
        config = EconomicsConfig(max_transfer_fraction=1, max_delta_btc=.2,
            min_improvement_bps=5, proxy_expense_rate=.01)
        decision = evaluate_amortized_transfer(self.now,
            PositionSlice(self.spot, 1.0), self.good, self.spot,
            cash_rate=.04, fees=self.fees, config=config)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.source_quantity_btc, .2)
        self.assertEqual(decision.diagnostics["source_keep"]["amortized_rate"], -.01)
        self.assertTrue(decision.diagnostics["no_discrete_holding_horizons"])

    def test_costs_can_reject_an_apparently_positive_lease(self):
        expensive = {"spot": FeeSchedule(fee_bps=300),
                     "futures": FeeSchedule(fee_bps=300),
                     "delivery": FeeSchedule(fee_bps=300)}
        target = QuoteSnapshot("THIN", 99.0, self.now, self.now,
                               self.now + YEAR_US // 10)
        decision = evaluate_amortized_transfer(self.now,
            PositionSlice(self.spot, 1.0), target, self.spot,
            cash_rate=.04, fees=expensive, config=self.config)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "amortized_improvement_below_buffer")

    def test_keep_future_does_not_recharge_sunk_entry(self):
        kept = keep_amortized_return(self.now, PositionSlice(self.good, .5),
            self.spot, cash_rate=.04, fees=self.fees, config=self.config)
        self.assertTrue(kept["entry_cost_is_sunk"])
        expected_future_cost = self.fees["spot"].total_fee(.5, 50)
        self.assertAlmostEqual(kept["remaining_cost_usd"], expected_future_cost)

    def test_rank_is_worst_keep_then_best_candidate(self):
        spot_source = PositionSlice(self.spot, 1.0)
        first = evaluate_amortized_transfer(self.now, spot_source, self.good,
            self.spot, cash_rate=.04, fees=self.fees, config=self.config)
        second = evaluate_amortized_transfer(self.now, spot_source, self.bad,
            self.spot, cash_rate=.04, fees=self.fees, config=self.config)
        ranked = rank_amortized_decisions([second.to_dict(), first.to_dict()])
        self.assertEqual(ranked[0]["target_symbol"], "GOOD")

    def test_adaptive_bound_is_last_accepted_price(self):
        source = PositionSlice(self.spot, .2)
        cap, decision = solve_amortized_price_limit(self.now, source, self.good,
            self.spot, price_role="target", counterpart_price=100,
            cash_rate=.04, fees=self.fees,
            config=EconomicsConfig(max_transfer_fraction=1, max_delta_btc=.2,
                                   min_improvement_bps=5))
        self.assertIsNotNone(cap)
        self.assertTrue(decision.accepted)
        rejected = evaluate_amortized_transfer(self.now, source, self.good,
            self.spot, cash_rate=.04, fees=self.fees,
            config=EconomicsConfig(max_transfer_fraction=1, max_delta_btc=.2,
                                   min_improvement_bps=5),
            source_price=100, target_price=cap * (1 + 1e-8))
        self.assertFalse(rejected.accepted)


if __name__ == "__main__":
    unittest.main()
