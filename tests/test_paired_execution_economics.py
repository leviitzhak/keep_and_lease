"""Independent cash-flow cases for empirical execution admission and sizing."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from funded_ledger import FeeSchedule
from paired_transfer_economics import (
    DAY_US, EconomicsConfig, PositionSlice, QuoteSnapshot,
    evaluate_transfer, evaluate_transfer_with_execution,
)


NOW = 1_000_000
SPOT = QuoteSnapshot("SPOT", 100, NOW, NOW)
FUTURE = QuoteSnapshot("F", 95, NOW, NOW, NOW + DAY_US)


def cfg(**kwargs):
    return replace(EconomicsConfig(), horizon_days=(1,), max_horizon_days=1,
                   max_transfer_fraction=1, size_fractions=(1,),
                   cash_reserve_fraction=0, price_limit_bps=0, uncertainty_bps=0,
                   **kwargs)


def outcome(weight=1, source=1, target=1, **kwargs):
    return dict(weight=weight, source_fill_fraction=source, target_fill_fraction=target,
                source_vwap_ratio=1 if source else None,
                target_vwap_ratio=1 if target else None,
                source_fill_delay_seconds=1 if source else None,
                target_fill_delay_seconds=2 if target else None,
                max_adverse_budget_bps=0, deadline_spot_ratio=1,
                censored=False, **kwargs)


class Model:
    def __init__(self, rows=None, **kwargs):
        self.rows = rows or [outcome()]
        self.extra = kwargs
        self.calls = []

    def forecast(self, symbol, expiry_us, now_us, quantity, wait_seconds, confidence, min_samples):
        self.calls.append((quantity, wait_seconds, confidence, min_samples))
        result = dict(available=True, samples=100, completion_probability=.95,
                    all_outcome_probability=.95, budget_bps=100,
                    label_cutoff_us=NOW-1, model_id="test-causal", scope="exact_contract",
                    outcomes=[dict(row, requested_source_btc=quantity) for row in self.rows])
        return {**result, **self.extra}


def decide(model=None, **kwargs):
    return evaluate_transfer_with_execution(NOW, PositionSlice(SPOT, 1), FUTURE, SPOT,
        cash_rate=0, execution_model=model or Model(), config=kwargs.pop("config", cfg()),
        candidate_quantities_btc=kwargs.pop("candidate_quantities_btc", (1,)), **kwargs)


class EmpiricalExecutionEconomicsTests(unittest.TestCase):
    def test_expected_and_conservative_edges_are_distinct_and_no_fills_equal_keep(self):
        d = decide(Model([outcome(.95), outcome(.05, source=0, target=0)]))
        self.assertTrue(d.accepted)
        self.assertAlmostEqual(d.keep_btc, 1)
        self.assertAlmostEqual(d.swap_btc, .95 * 1.05 + .05)
        self.assertAlmostEqual(d.edge_btc, .0475)
        self.assertAlmostEqual(d.diagnostics["conservative_budget_edge_btc"], .0305)
        self.assertEqual(d.diagnostics["execution_model"]["label_cutoff_us"], NOW-1)

    def test_sold_but_unhedged_scenario_pays_restoration_cost_instead_of_keep(self):
        d = decide(Model([outcome(.95), outcome(.05, source=1, target=0)]))
        failed_wealth = 100 / 101
        self.assertAlmostEqual(d.swap_btc, .95 * 1.05 + .05 * failed_wealth)
        self.assertLess(d.edge_btc, .0475)
        self.assertAlmostEqual(d.diagnostics["expected_restored_spot_btc"], .05 * failed_wealth)

    def test_partial_source_tranche_is_restored_without_starting_hedge(self):
        d = decide(Model([outcome(.95), outcome(.05, source=.5, target=.5)]))
        failed_wealth = .5 + 50 / 101
        self.assertAlmostEqual(d.swap_btc, .95 * 1.05 + .05 * failed_wealth)
        self.assertAlmostEqual(d.diagnostics["expected_target_filled_btc"], .95)
        self.assertAlmostEqual(d.diagnostics["expected_source_filled_btc"], .975)

    def test_budget_is_reserved_before_ratio_and_never_deducted_from_cash_reserve(self):
        target = replace(FUTURE, price=100)
        settings = replace(cfg(), cash_reserve_fraction=.01)
        d = evaluate_transfer_with_execution(NOW, PositionSlice(SPOT, 1), target, SPOT,
            cash_rate=.2, execution_model=Model(), config=settings,
            candidate_quantities_btc=(1,))
        self.assertAlmostEqual(d.target_quantity_btc, 99 * .99 / 101)
        self.assertAlmostEqual(d.diagnostics["cash_reserve_usd"], .99)
        self.assertLess(d.target_quantity_btc, .99)

    def test_empirical_budget_changes_entry_only_not_future_exit_or_conversion(self):
        d = decide()
        baseline = evaluate_transfer(NOW, PositionSlice(SPOT, 1), FUTURE, SPOT,
            cash_rate=0, config=cfg(),
            execution_price_overrides={"source": 99, "target": 95.95})
        self.assertAlmostEqual(d.diagnostics["conservative_budget_swap_btc"], baseline.swap_btc)
        self.assertEqual(d.diagnostics["execution_budget_applied_to"], "entry_only")
        self.assertEqual(d.diagnostics["swap"]["exit_cost_usd"], 0)

    def test_model_price_adjustments_are_not_charged_twice(self):
        row = outcome()
        row.update(source_vwap_ratio=.999, target_vwap_ratio=1.001, max_adverse_budget_bps=10)
        d = decide(Model([row]), config=replace(cfg(), half_spread_bps=4, slippage_bps=6))
        self.assertEqual(d.diagnostics["source_sale_limit"], 99)
        self.assertAlmostEqual(d.diagnostics["target_buy_limit"], 95.95)
        # Entry cash=99.9; entry future=95.095. At expiry the cash is104.805,
        # converted at100.1 because the existing terminal spread still applies.
        self.assertAlmostEqual(d.swap_btc, 104.805 / 100.1)

    def test_known_deadline_nofill_is_keep_even_after_historical_spot_fell(self):
        nofill = outcome(.05, source=0, target=0)
        nofill.update(censored=True, censor_reason="waiting_deadline",
                      max_adverse_budget_bps=None, deadline_spot_ratio=.8)
        d = decide(Model([outcome(.95), nofill]))
        self.assertAlmostEqual(d.swap_btc, .95 * 1.05 + .05)
        self.assertEqual(d.diagnostics["execution_tail_fallback_probability"], 0)

    def test_unknown_tail_cannot_profit_from_fictitious_spot_roundtrip(self):
        tail = outcome(.05, source=0, target=0)
        tail.update(censored=True, censor_reason="data_end", deadline_spot_ratio=.8)
        d = decide(Model([outcome(.95), tail]))
        self.assertLessEqual(d.swap_btc, .95 * 1.05 + .05)
        self.assertEqual(d.diagnostics["execution_tail_fallback_probability"], .05)

    def test_smaller_funded_hedge_does_not_inherit_cheaper_full_quantity_vwap(self):
        target = replace(FUTURE, price=99.9)
        row = outcome()
        # A late cheap print lowers the historical whole-ticket VWAP, while the
        # smaller funded prefix may pay the worst price of99.9 throughout.
        row.update(target_vwap_ratio=.75, worst_future_adverse_bps=0)
        d = evaluate_transfer_with_execution(NOW, PositionSlice(SPOT, 1), target, SPOT,
            cash_rate=.2, execution_model=Model([row], budget_bps=0),
            config=replace(cfg(), cash_reserve_fraction=.01),
            candidate_quantities_btc=(1,))
        self.assertTrue(d.accepted)
        self.assertAlmostEqual(d.target_quantity_btc, 99/99.9)
        self.assertLess(d.swap_btc, 1.01)
        self.assertEqual(d.diagnostics["execution_target_prefix_bound_probability"], 1)

    def test_failed_conservative_gate_skips_every_empirical_scenario_honestly(self):
        target = replace(FUTURE, price=105)
        with patch("paired_transfer_economics._execution_outcome_forecast") as forecast:
            d = evaluate_transfer_with_execution(NOW, PositionSlice(SPOT, 1), target, SPOT,
                cash_rate=0, execution_model=Model(), config=cfg(), candidate_quantities_btc=(1,))
        forecast.assert_not_called()
        self.assertFalse(d.accepted)
        self.assertIsNone(d.diagnostics["expected_edge_btc"])
        self.assertIsNone(d.diagnostics["expected_swap_btc"])
        self.assertEqual(d.diagnostics["execution_expected_evaluation"], "skipped_conservative_rejection")
        self.assertEqual(d.edge_btc, d.diagnostics["conservative_budget_edge_btc"])
        self.assertEqual(d.swap_btc, d.diagnostics["conservative_budget_swap_btc"])

    def test_unmeasured_restoration_liquidity_cannot_create_cheap_repurchase_profit(self):
        failed = outcome(.05, source=1, target=0)
        failed.update(deadline_spot_ratio=.8)
        d = decide(Model([outcome(.95), failed]))
        self.assertLessEqual(d.swap_btc, .95 * 1.05 + .05)
        self.assertEqual(d.diagnostics["expected_restored_spot_btc"], 0)

    def test_nonproportional_entry_fees_fail_closed_for_uncalibrated_ticket_paths(self):
        d = decide(fees={"spot": FeeSchedule(minimum=.1)})
        self.assertFalse(d.accepted)
        self.assertEqual(d.reason, "empirical_nonproportional_fees_unsupported")

    def test_expected_fees_include_both_source_and_restore_tickets(self):
        fees = {"spot": FeeSchedule(fee_bps=10), "futures": FeeSchedule(fee_bps=10)}
        d = decide(Model([outcome(.95), outcome(.05, source=1, target=0)]), fees=fees)
        # Complete: source .1 and future .095. Failure: source .1, then
        # restoration spends 99.9 inclusive of proportional commission.
        restore_quantity = 99.9 / (101 * 1.001)
        expected_fees = .95 * (.1 + .095) + .05 * (.1 + restore_quantity * 101 * .001)
        self.assertAlmostEqual(d.diagnostics["expected_entry_and_restore_fees_usd"], expected_fees)

    def test_only_calibrated_grid_sizes_below_allocation_limit_are_considered(self):
        model = Model()
        d = decide(model, config=replace(cfg(), max_transfer_fraction=.025),
                   candidate_quantities_btc=(.0001, .001, .01, .1))
        self.assertEqual([call[0] for call in model.calls], [.0001, .001, .01])
        self.assertAlmostEqual(d.source_quantity_btc, .01)
        self.assertAlmostEqual(d.source_fraction, .01)
        self.assertAlmostEqual(d.diagnostics["residual_source_quantity_btc"], .99)

    def test_model_label_cutoff_must_precede_decision_and_confidence_counts_misses(self):
        class Altered(Model):
            def __init__(self, overrides):
                super().__init__()
                self.overrides = overrides

            def forecast(self, *args):
                return {**super().forecast(*args), **self.overrides}

        future = decide(Altered({"label_cutoff_us": NOW}))
        self.assertFalse(future.accepted)
        self.assertEqual(future.reason, "execution_model_not_causal")
        misses = decide(Altered({"completion_probability": 1, "all_outcome_probability": .94}))
        self.assertFalse(misses.accepted)
        self.assertEqual(misses.reason, "execution_joint_confidence_unattainable")

    def test_outside_budget_tail_is_not_assumed_filled_at_an_unauthorized_price(self):
        tail = outcome(.05)
        tail.update(max_adverse_budget_bps=300, target_vwap_ratio=1.03)
        d = decide(Model([outcome(.95), tail]))
        self.assertAlmostEqual(d.diagnostics["execution_tail_fallback_probability"], .05)
        self.assertAlmostEqual(d.diagnostics["expected_target_filled_btc"], .95)
        self.assertAlmostEqual(d.swap_btc, .95 * 1.05 + .05 * 99 / 101)

    def test_partial_hedge_keeps_futures_and_restores_only_unmatched_source(self):
        d = decide(Model([outcome(.95), outcome(.05, source=1, target=.5)]))
        # Failed branch: restore .5 source with its $50, keep half a future.
        # $50 funds the future; its expiry P&L is $2.50.
        branch = 50 / 101 + .525
        self.assertAlmostEqual(d.swap_btc, .95 * 1.05 + .05 * branch)
        self.assertAlmostEqual(d.diagnostics["expected_target_filled_btc"], .975)

    def test_nofill_mixture_cannot_hide_fixed_costs_or_manufacture_profitable_decision(self):
        d = decide(Model([outcome(.95, source=0, target=0), outcome(.05, source=1, target=0)]))
        self.assertFalse(d.accepted)
        self.assertEqual(d.reason, "empirical_expected_gain_below_buffer")
        self.assertLess(d.edge_btc, 0)

    def test_unsupported_routes_and_too_short_horizon_fail_closed(self):
        reverse = evaluate_transfer_with_execution(NOW, PositionSlice(FUTURE, 1, 100),
            SPOT, SPOT, cash_rate=0, execution_model=Model(), config=cfg())
        self.assertEqual(reverse.reason, "empirical_execution_route_unsupported")
        short = decide(horizon_limit_us=NOW + 10_000_000)
        self.assertFalse(short.accepted)
        self.assertEqual(short.reason, "no_feasible_execution_horizon")


if __name__ == "__main__":
    unittest.main()
