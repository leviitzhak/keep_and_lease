"""Independent cash-flow and opportunity-cost cases for the paired selector."""
from dataclasses import dataclass, replace
import json
import math
import unittest

from paired_transfer_economics import (DAY_US, EconomicsConfig, IncrementalFeeSchedule, PositionSlice,
    QuoteSnapshot, evaluate_transfer, funded_quantity)


@dataclass(frozen=True)
class Fee:
    fee_bps: float = 0
    fixed: float = 0
    minimum: float = 0
    currency: str = "USD"

    def total_fee(self, quantity, notional):
        return 0 if quantity <= 0 else max(self.minimum, self.fixed + self.fee_bps * notional / 10000)


NOW = 0
SPOT = QuoteSnapshot("SPOT", 100, NOW, NOW)


def future(price=100, expiry_days=30, symbol="F", **kwargs):
    return QuoteSnapshot(symbol, price, NOW, NOW, int(expiry_days * DAY_US), **kwargs)


def config(**kwargs):
    return replace(EconomicsConfig(), max_transfer_fraction=1,
                   cash_reserve_fraction=0, price_limit_bps=0, uncertainty_bps=0,
                   **kwargs)


def decide(source=None, target=None, *, rate=0, fees=None, config_=None, **kwargs):
    return evaluate_transfer(NOW, source or PositionSlice(SPOT, 1), target or future(),
                             SPOT, cash_rate=rate, fees=fees,
                             config=config_ or config(), **kwargs)


class PairedEconomicsTests(unittest.TestCase):
    def test_zero_cost_flat_forward_is_keep(self):
        d = decide()
        self.assertFalse(d.accepted)
        self.assertAlmostEqual(d.edge_btc, 0, places=12)
        self.assertEqual(d.reason, "keep_net_gain_below_buffer")

    def test_equal_capital_funds_premium_and_commissions(self):
        fees = {"spot": Fee(fee_bps=10, fixed=1), "futures": Fee(fee_bps=20, fixed=2)}
        d = decide(target=future(105), fees=fees, config_=config(size_fractions=(1,)))
        proceeds = 100 - 1 - .1
        expected_quantity = (proceeds - 2) / (105 * 1.002)
        self.assertAlmostEqual(d.target_quantity_btc, expected_quantity)
        self.assertLess(d.target_quantity_btc, d.source_quantity_btc)
        self.assertAlmostEqual(d.diagnostics["target_cash_usd"], expected_quantity * 105)
        self.assertAlmostEqual(d.diagnostics["initial_capital_usd"], 100)
        self.assertFalse(d.accepted)

    def test_positive_carry_can_fail_total_cost_recovery(self):
        d = decide(target=future(99.99), fees={"spot": Fee(fee_bps=3), "futures": Fee(fee_bps=3)})
        self.assertFalse(d.accepted)
        self.assertLess(d.edge_btc, 0)

    def test_fixed_cost_size_grid_prefers_sufficiently_large_transfer(self):
        d = decide(target=future(98), fees={"futures": Fee(fixed=.4), "spot": Fee(fixed=.4)})
        self.assertTrue(d.accepted)
        self.assertAlmostEqual(d.source_quantity_btc, 1)
        small = [a for a in d.diagnostics["alternatives"] if a["source_fraction"] == .25]
        large = [a for a in d.diagnostics["alternatives"] if a["source_fraction"] == 1]
        self.assertTrue(all(a["reason"] == "keep_net_gain_below_buffer" for a in small))
        self.assertTrue(any(a["reason"] == "net_gain_exceeds_buffer" for a in large))

    def test_future_keep_uses_mark_and_actual_cash_not_historical_entry(self):
        source = PositionSlice(future(110), 1, 100, 10)
        d = decide(source, SPOT, config_=config(horizon_days=(1,), max_horizon_days=1))
        expected_keep_cash = 110 + ((100 + 10 * 29 / 30) - 110)
        self.assertAlmostEqual(d.keep_btc, expected_keep_cash / 100)
        self.assertAlmostEqual(d.swap_btc, 1.1)
        self.assertTrue(d.accepted)
        # Different accounting settlement bases with the same equity and zero
        # rate have the same forward economics; old entry costs are absent.
        settled = decide(replace(source, cash_usd=110, unsettled_pnl_usd=0), SPOT,
                         config_=config(horizon_days=(1,), max_horizon_days=1))
        self.assertAlmostEqual(d.edge_btc, settled.edge_btc)

    def test_cash_variation_timing_matches_daily_funded_cashflows(self):
        source = PositionSlice(future(110, expiry_days=2), 1, 105, 5)
        d = decide(source, SPOT, rate=.1,
                   config_=config(horizon_days=(2,), max_horizon_days=2, size_fractions=(1,)))
        # At day one F=105, so initial U=5 exactly offsets new mark loss -5.
        day_growth = math.exp(.1 / 365)
        expected = 105 * day_growth**2 - 5
        self.assertAlmostEqual(d.keep_btc, expected / 100, places=12)
        self.assertAlmostEqual(d.diagnostics["keep"]["interest_usd"],
                               105 * (day_growth**2 - 1), places=12)

    def test_roll_reuses_cash_without_spot_entry_commission(self):
        source = PositionSlice(future(100, symbol="OLD"), 1, 100)
        fees = {"spot": Fee(fixed=7), "futures": Fee(fixed=.1)}
        d = decide(source, future(95, symbol="NEW"), fees=fees,
                   config_=config(size_fractions=(1,), horizon_days=(1,), max_horizon_days=1))
        self.assertAlmostEqual(d.entry_cost_usd, .2)
        self.assertAlmostEqual(d.diagnostics["keep"]["exit_cost_usd"], 7.1)
        self.assertAlmostEqual(d.diagnostics["swap"]["exit_cost_usd"], 7.1)

    def test_horizon_capped_by_both_expiries_and_risk(self):
        source = PositionSlice(future(101, expiry_days=2, symbol="OLD"), 1, 101)
        d = decide(source, future(95, expiry_days=3, symbol="NEW"), horizon_limit_us=int(1.5 * DAY_US))
        self.assertLessEqual(d.horizon_us, 1.5 * DAY_US)
        self.assertTrue(all(a["horizon_us"] <= 1.5 * DAY_US for a in d.diagnostics["alternatives"]))
        denied = decide(horizon_limit_us=0)
        self.assertEqual(denied.reason, "no_feasible_horizon")

    def test_early_exit_retains_residual_basis(self):
        d = decide(target=future(90, expiry_days=30),
                   config_=config(horizon_days=(1,), max_horizon_days=1, size_fractions=(1,)))
        projected = 90 + 10 / 30
        self.assertAlmostEqual(d.diagnostics["swap"]["projected_future_price"], projected)
        self.assertAlmostEqual(d.swap_btc, (100 + (projected - 90)) / 100)
        self.assertLess(d.edge_btc, .01)

    def test_expiry_reference_and_delivery_schedule_not_future_exit_fee(self):
        fees = {"futures": Fee(fixed=1), "delivery": Fee(fixed=.25)}
        d = decide(target=future(90, expiry_days=1), fees=fees,
                   config_=config(horizon_days=(1,), settlement_basis_bps=-100, size_fractions=(1,)))
        self.assertEqual(d.diagnostics["swap"]["projected_future_price"], 99)
        self.assertAlmostEqual(d.entry_cost_usd, 1)
        self.assertAlmostEqual(d.diagnostics["swap"]["exit_cost_usd"], .25)
        self.assertAlmostEqual(d.swap_btc, (99 + 9 - .25) / 100)

    def test_future_keep_exit_cost_charged_exactly_once(self):
        source = PositionSlice(future(100), 1, 100)
        d = decide(source, SPOT, fees={"futures": Fee(fixed=2), "spot": Fee(fixed=1)},
                   config_=config(horizon_days=(1,), max_horizon_days=1, size_fractions=(1,)))
        self.assertAlmostEqual(d.keep_btc, .97)
        self.assertAlmostEqual(d.swap_btc, .97)
        self.assertAlmostEqual(d.edge_btc, 0)

    def test_cost_multiplier_does_not_charge_base_costs_twice(self):
        fees = {"spot": Fee(fee_bps=1), "futures": Fee(fee_bps=1)}
        one = decide(target=future(95), fees=fees,
                     config_=config(size_fractions=(1,), cost_buffer_multiplier=1))
        two = decide(target=future(95), fees=fees,
                     config_=config(size_fractions=(1,), cost_buffer_multiplier=2))
        self.assertAlmostEqual(one.edge_btc, two.edge_btc)
        self.assertAlmostEqual(one.required_edge_btc, 0)
        self.assertAlmostEqual(two.required_edge_btc,
                               two.diagnostics["incremental_future_cost_usd"] / 100)

    def test_increasing_fees_cannot_improve_same_size_forecast(self):
        cfg = config(size_fractions=(1,), horizon_days=(1,), max_horizon_days=1)
        low = decide(target=future(95), fees={"spot": Fee(fee_bps=1), "futures": Fee(fee_bps=1)}, config_=cfg)
        high = decide(target=future(95), fees={"spot": Fee(fee_bps=5), "futures": Fee(fee_bps=5)}, config_=cfg)
        self.assertLess(high.edge_btc, low.edge_btc)

    def test_rejects_unavailable_stale_future_and_missing_rates(self):
        for quote, expected in [
            (replace(future(), available_us=1), "quote_not_available"),
            (replace(future(), price=float("nan")), "unavailable_price"),
            (replace(future(), source_us=-2_000_000, available_us=-2_000_000), "stale_quote"),
            (replace(future(), expiry_us=None), "unavailable_future_expiry"),
            (replace(future(), size_btc=0), "unavailable_liquidity"),
        ]:
            with self.subTest(reason=expected):
                self.assertEqual(decide(target=quote).reason, expected)
        self.assertEqual(decide(rate=None).reason, "unavailable_cash_rate")

    def test_unfunded_keep_state_is_not_called_discretionary_opportunity(self):
        d = decide(PositionSlice(future(100), 1, 50), SPOT)
        self.assertFalse(d.accepted)
        self.assertEqual(d.reason, "forecast_funding_shortfall")

    def test_adverse_prices_and_reserve_funded_without_external_capital(self):
        cfg = replace(config(size_fractions=(1,)), price_limit_bps=10, cash_reserve_fraction=.01)
        d = decide(target=future(95), config_=cfg)
        cash = 99.9
        q = min(1, cash * .99 / (95 * 1.001))
        self.assertAlmostEqual(d.target_quantity_btc, q)
        self.assertAlmostEqual(d.diagnostics["target_cash_usd"], cash)
        self.assertGreaterEqual(cash, q * d.diagnostics["target_buy_limit"])
        self.assertAlmostEqual(d.diagnostics["cash_reserve_usd"], cash * .01)

    def test_ticket_minimum_makes_tiny_budget_untradable(self):
        q, fee = funded_quantity(4, 100, {"spot": Fee(minimum=5)}, "spot")
        self.assertEqual((q, fee), (0, 0))
        q, fee = funded_quantity(10, 100, {"spot": Fee(minimum=5)}, "spot")
        self.assertAlmostEqual(q, .05)
        self.assertEqual(fee, 5)

    def test_terminal_cash_below_conversion_minimum_remains_wealth(self):
        source = PositionSlice(future(1), 1, 1)
        # Source-to-spot transfer is impossible, so test its KEEP forecast through
        # a future roll whose entry does not need the unaffordable spot ticket.
        d = evaluate_transfer(NOW, source, future(.9, symbol="NEW"), SPOT, cash_rate=0,
            fees={"spot": Fee(minimum=200)}, config=config(size_fractions=(1,), horizon_days=(1,), max_horizon_days=1))
        self.assertGreater(d.keep_btc, 0)
        self.assertGreater(d.swap_btc, 0)
        self.assertAlmostEqual(d.keep_btc, (1 + 99 / 30) / 100)

    def test_backwardation_does_not_expand_commodity_quantity(self):
        d = decide(target=future(90), config_=config(size_fractions=(1,)))
        self.assertEqual(d.target_quantity_btc, 1)
        self.assertEqual(d.diagnostics["target_cash_usd"], 100)
        self.assertEqual(d.diagnostics["exposure_quantity_change_btc"], 0)

    def test_execution_costs_and_spot_expense_are_forecast_once(self):
        cfg = replace(config(size_fractions=(1,), horizon_days=(1,), max_horizon_days=1),
                      half_spread_bps=2, slippage_bps=3, proxy_expense_rate=.02)
        d = decide(target=future(90), config_=cfg)
        self.assertAlmostEqual(d.diagnostics["source_sale_limit"], 99.95)
        self.assertAlmostEqual(d.diagnostics["target_buy_limit"], 90 * 1.0005)
        self.assertAlmostEqual(d.keep_btc, math.exp(-.02 / 365))

    def test_horizon_search_can_choose_early_exit_over_costly_delivery(self):
        d = decide(target=future(90), fees={"delivery": Fee(fixed=20)},
                   config_=config(size_fractions=(1,)))
        self.assertTrue(d.accepted)
        self.assertEqual(d.horizon_us, 14 * DAY_US)
        delivery = [a for a in d.diagnostics["alternatives"] if a["horizon_us"] == 30 * DAY_US]
        self.assertTrue(all(a["reason"] == "keep_net_gain_below_buffer" for a in delivery))

    def test_horizon_restriction_can_remove_otherwise_profitable_cost_recovery(self):
        fees = {"spot": Fee(fixed=.3), "futures": Fee(fixed=.3), "delivery": Fee(fixed=.3)}
        target = future(98)
        long = decide(target=target, fees=fees, config_=config(size_fractions=(1,)))
        short = decide(target=target, fees=fees, config_=config(size_fractions=(1,)),
                       horizon_limit_us=DAY_US)
        self.assertTrue(long.accepted)
        self.assertFalse(short.accepted)
        self.assertTrue(all(a["horizon_us"] <= DAY_US for a in short.diagnostics["alternatives"]))

    def test_future_observation_perturbations_cannot_authorize_earlier_decision(self):
        for later_price in (1, 100, 1000000):
            unavailable = replace(future(later_price), source_us=1, available_us=2)
            d = decide(target=unavailable)
            self.assertFalse(d.accepted)
            self.assertEqual(d.reason, "quote_not_available")
            self.assertEqual(d.target_quantity_btc, 0)
            self.assertIsNone(d.horizon_us)

    def test_quote_arrival_order_is_irrelevant_after_both_available(self):
        cfg = config(size_fractions=(1,))
        first = QuoteSnapshot("SPOT", 100, -100, -50)
        second = replace(future(90), source_us=-70, available_us=-10)
        d1 = evaluate_transfer(NOW, PositionSlice(first, 1), second, first,
                              cash_rate=0, config=cfg)
        other_spot = replace(first, available_us=-1)
        other_future = replace(second, available_us=-20)
        d2 = evaluate_transfer(NOW, PositionSlice(other_spot, 1), other_future, other_spot,
                              cash_rate=0, config=cfg)
        self.assertTrue(d1.accepted and d2.accepted)
        self.assertAlmostEqual(d1.edge_btc, d2.edge_btc)

    def test_invalid_source_expiry_and_stale_spot_fail_without_liquidation(self):
        source = PositionSlice(replace(future(), expiry_us=NOW), 1, 100)
        self.assertEqual(decide(source, SPOT).reason, "unavailable_future_expiry")
        stale = replace(SPOT, source_us=-2_000_000, available_us=-2_000_000)
        d = evaluate_transfer(NOW, PositionSlice(future(), 1, 100), SPOT, stale,
                              cash_rate=0, config=config())
        self.assertEqual(d.reason, "stale_quote")
        self.assertEqual(d.source_quantity_btc, 0)

    def test_spread_costs_reduce_edge_without_borrowed_capital(self):
        edges = []
        for bps in (0, 1, 10, 100):
            cfg = replace(config(size_fractions=(1,), horizon_days=(1,), max_horizon_days=1),
                          half_spread_bps=bps)
            d = decide(target=future(95), config_=cfg)
            self.assertGreaterEqual(d.diagnostics["target_cash_usd"] + 1e-12,
                                    d.target_quantity_btc * d.diagnostics["target_buy_limit"])
            edges.append(d.edge_btc)
        self.assertEqual(edges, sorted(edges, reverse=True))

    def test_partial_entry_ticket_does_not_recharge_sunk_minimum(self):
        ticket = IncrementalFeeSchedule(Fee(fee_bps=10, fixed=2, minimum=5),
                                        cumulative_quantity=.2, cumulative_notional=20, already_paid=5)
        self.assertEqual(ticket.total_fee(.3, 30), 0)
        self.assertAlmostEqual(ticket.total_fee(100, 10000), 7.02)
        self.assertEqual(ticket.total_fee(0, 0), 0)

    def test_marginal_entry_override_cannot_discount_terminal_exit_ticket(self):
        full = Fee(fixed=2)
        source = PositionSlice(future(100, symbol="OLD"), 1, 100)
        d = decide(source, future(90, symbol="NEW"), fees={"futures": full},
                   config_=config(size_fractions=(1,), horizon_days=(1,), max_horizon_days=1),
                   entry_fees={"source": IncrementalFeeSchedule(full, .2, 20, 2),
                               "target": IncrementalFeeSchedule(full, .1, 9, 2)})
        self.assertEqual(d.entry_cost_usd, 0)
        self.assertEqual(d.diagnostics["keep"]["exit_cost_usd"], 2)
        self.assertEqual(d.diagnostics["swap"]["exit_cost_usd"], 2)

    def test_absurd_finite_rate_fails_before_overflow_or_nonfinite_audit(self):
        d = decide(rate=1e300)
        self.assertFalse(d.accepted)
        self.assertEqual(d.reason, "unsupported_cash_rate_magnitude")
        json.dumps(d.to_dict(), allow_nan=False)

    def test_depth_limit_rescales_grid_to_include_small_feasible_transfers(self):
        d = decide(target=future(90, size_btc=.001), config_=config())
        self.assertTrue(d.accepted)
        self.assertAlmostEqual(d.source_quantity_btc, .001)
        self.assertLessEqual(d.target_quantity_btc, .001)
        source = PositionSlice(replace(SPOT, size_btc=.0005), 1)
        d = decide(source, future(90, size_btc=.001), config_=config())
        self.assertAlmostEqual(d.source_quantity_btc, .0005)

    def test_pending_forecast_preserves_original_quantity_and_child_limits(self):
        cfg = config(size_fractions=(1,), horizon_days=(30,))
        dynamic = decide(target=future(95), config_=cfg)
        fixed = decide(target=future(95), config_=cfg, target_quantity_btc=.5,
                       execution_price_overrides={"source": 100, "target": 100},
                       comparison_horizon_us=30 * DAY_US)
        self.assertTrue(dynamic.accepted)
        self.assertFalse(fixed.accepted)
        self.assertEqual(fixed.target_quantity_btc, .5)
        self.assertEqual(fixed.diagnostics["target_buy_limit"], 100)
        self.assertEqual(fixed.diagnostics["target_quote"]["price"], 95)
        self.assertAlmostEqual(fixed.edge_btc, 0)
        self.assertEqual(fixed.horizon_us, 30 * DAY_US)

    def test_pending_instruction_cannot_replace_unfundable_ratio_with_smaller_trade(self):
        d = decide(target=future(95), config_=config(size_fractions=(1,)),
                   target_quantity_btc=1,
                   execution_price_overrides={"source": 90, "target": 95})
        self.assertFalse(d.accepted)
        self.assertEqual(d.reason, "fixed_target_exceeds_funding")
        self.assertEqual(d.target_quantity_btc, 0)

    def test_pending_horizon_is_exact_even_if_another_horizon_is_more_profitable(self):
        d = decide(target=future(90), config_=config(size_fractions=(1,)),
                   target_quantity_btc=1, comparison_horizon_us=3 * DAY_US)
        self.assertEqual(d.horizon_us, 3 * DAY_US)
        self.assertEqual(d.diagnostics["evaluated_horizons"], 1)
        self.assertAlmostEqual(d.edge_btc, .01)
        impossible = decide(target=future(90, expiry_days=2),
                            comparison_horizon_us=3 * DAY_US)
        self.assertFalse(impossible.accepted)
        self.assertEqual(impossible.reason, "no_feasible_horizon")

    def test_pending_fixed_ratio_uses_marginal_entry_but_new_terminal_ticket(self):
        full = Fee(fixed=2)
        paid = IncrementalFeeSchedule(full, .5, 50, 2)
        d = decide(target=future(90), fees={"spot": full, "futures": full},
                   config_=config(size_fractions=(1,), horizon_days=(1,), max_horizon_days=1),
                   target_quantity_btc=.5,
                   execution_price_overrides={"source": 100, "target": 91},
                   entry_fees={"source": paid, "target": paid},
                   comparison_horizon_us=DAY_US)
        self.assertEqual(d.entry_cost_usd, 0)
        self.assertEqual(d.target_quantity_btc, .5)
        self.assertEqual(d.diagnostics["swap"]["exit_cost_usd"], 4)

    def test_json_output_contains_no_nonfinite_values(self):
        d = decide(target=future(98))
        json.dumps(d.to_dict(), allow_nan=False)
        self.assertLess(len(json.dumps(d.to_dict())), 32767)

    def test_config_parses_and_validates_research_controls(self):
        cfg = EconomicsConfig.from_payload({"paired_horizon_days": "0.25, 1, 3", "paired_max_transfer_fraction": ".1"})
        self.assertEqual(cfg.horizon_days, (.25, 1, 3))
        self.assertEqual(cfg.max_transfer_fraction, .1)
        for update in [dict(uncertainty_bps=float("nan")), dict(cost_buffer_multiplier=.5),
                       dict(max_transfer_fraction=2), dict(cash_reserve_fraction=1),
                       dict(horizon_days=()), dict(settlement_interval_seconds=0),
                       dict(settlement_interval_seconds=1, max_horizon_days=30)]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                replace(EconomicsConfig(), **update)


if __name__ == "__main__":
    unittest.main()
