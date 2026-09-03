import math
import unittest
from datetime import date

from backtest_silver_lease_strategy import (
    Parameters, multiplicative_log_contributions, positions_for_day,
    run_backtest, usd_rate)
from silver_strategy_gui import futures_diagnostics


class StandaloneLegReturnTests(unittest.TestCase):
    def test_multiplicative_attribution_reconstructs_daily_return(self):
        logs = multiplicative_log_contributions(
            0.03, {"lease": 0.02, "keep": 0.01})
        self.assertAlmostEqual(
            1.03, math.exp(logs["lease"]) * math.exp(logs["keep"]))
        reversed_logs = multiplicative_log_contributions(
            0.03, {"keep": 0.01, "lease": 0.02})
        self.assertEqual(logs.keys(), reversed_logs.keys())
        for key in logs:
            self.assertAlmostEqual(logs[key], reversed_logs[key])

    def test_multiplicative_attribution_handles_zero_net_return(self):
        logs = multiplicative_log_contributions(
            0.0, {"lease": 0.01, "keep": -0.01})
        self.assertAlmostEqual(1.0, math.prod(math.exp(x) for x in logs.values()))

    def test_reported_compounded_factors_reconstruct_parent_navs(self):
        candidates = [
            {"symbol": "near", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.05, "volume": 10},
            {"symbol": "far", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.10, "volume": 5},
        ]
        by_day = {day: [dict(item) for item in candidates]
                  for day in self.days}
        rows, _ = run_backtest(
            self.spot, self.contracts, self.rates, by_day,
            Parameters(min_days=1, slv_expense=0))
        last = rows[-1]
        strategy = 1 + last["compounded_return_pct"] / 100
        lease_factor = 1 + last[
            "lease_book_attributed_factor_compounded_return_pct"] / 100
        keep_factor = 1 + last[
            "keep_book_attributed_factor_compounded_return_pct"] / 100
        self.assertAlmostEqual(strategy, lease_factor * keep_factor)
        lease_nav = 1 + last["lease_book_compounded_return_pct"] / 100
        fund_factor = 1 + last[
            "lease_fund_attributed_factor_compounded_return_pct"] / 100
        futures_factor = 1 + last[
            "lease_futures_treasury_attributed_factor_compounded_return_pct"] / 100
        self.assertAlmostEqual(lease_nav, fund_factor * futures_factor)
        for row in rows:
            self.assertAlmostEqual(
                row["nav"], row["lease_book_value"] + row["keep_book_value"])
            self.assertAlmostEqual(
                row["lease_book_value"],
                row["replicating_leg_value"] + row["futures_treasury_value"])
        self.assertEqual(rows[0]["exit_date"], self.days[1].isoformat())

    def test_holding_ledger_reconstructs_both_books(self):
        candidates = [
            {"symbol": "near", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.08, "volume": 10},
            {"symbol": "far", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.10, "volume": 5},
        ]
        by_day = {day: [dict(item) for item in candidates]
                  for day in self.days}
        rows, _ = run_backtest(
            self.spot, self.contracts, self.rates, by_day,
            Parameters(min_days=1, slv_expense=0.01))
        self.assertTrue(rows)
        for row in rows:
            ledger = row["holding_ledger"]
            self.assertTrue(any(item["holding_type"] == "cash" for item in ledger))
            for item in ledger:
                self.assertAlmostEqual(
                    item["end_value"], item["start_value"] +
                    item["pnl_value"] + item["internal_transfer_value"])
                if item["holding_type"] == "future":
                    self.assertEqual(0.0, item["start_value"])
                    self.assertEqual(0.0, item["end_value"])
                    self.assertIsNotNone(item["quantity"])
                if item["holding_type"] == "direct":
                    elapsed = (date.fromisoformat(row["exit_date"]) -
                               date.fromisoformat(row["date"])).days
                    expected_expense = (
                        item["start_value"] * 0.01 * elapsed / 365)
                    expected_pnl = item["start_value"] * (
                        item["exit_price"] / item["price"] - 1 -
                        0.01 * elapsed / 365)
                    self.assertAlmostEqual(expected_expense,
                                           item["expense_value"])
                    self.assertAlmostEqual(expected_pnl, item["pnl_value"])
                    self.assertAlmostEqual(
                        item["gross_pnl_value"] - item["expense_value"],
                        item["pnl_value"])
                    self.assertAlmostEqual(
                        item["quantity"] - item["units_expensed"],
                        item["end_quantity"])
                    self.assertAlmostEqual(
                        item["end_quantity"] * item["exit_price"],
                        item["end_value"])
                    self.assertEqual(0.0, item["internal_transfer_value"])
            for book in ("lease", "keep"):
                holdings = [item for item in ledger if item["book"] == book]
                start = sum(item["start_value"] for item in holdings)
                end = sum(item["end_value"] for item in holdings)
                pnl = sum(item["pnl_value"] for item in holdings)
                internal = sum(item["internal_transfer_value"] for item in holdings)
                self.assertAlmostEqual(row[f"{book}_book_start_value"], start)
                self.assertAlmostEqual(row[f"{book}_book_end_value"], end)
                self.assertAlmostEqual(end, start + pnl)
                self.assertAlmostEqual(0.0, internal)

    def setUp(self):
        self.days = [date(2020, 1, day) for day in range(1, 6)]
        self.spot = dict(zip(self.days, [100, 110, 121, 133.1, 146.41]))
        self.contracts = {
            "near": dict(zip(self.days, [100, 102, 104.04, 106.1208, 108.243216])),
            "far": dict(zip(self.days, [100, 99, 98.01, 97.0299, 96.059601])),
        }
        self.rates = {tenor: [(self.days[0], 0.0)] for tenor in
                      (91, 182, 365, 730, 1095, 1825)}
        candidates = [
            {"symbol": "near", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.0, "volume": 10},
            {"symbol": "far", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.0, "volume": 5},
        ]
        self.by_day = {day: [dict(item) for item in candidates]
                       for day in self.days}

    def test_leg_contracts_are_selected_even_when_thresholds_disable_trades(self):
        position = positions_for_day(self.by_day[self.days[0]], Parameters(min_days=1))
        self.assertEqual({}, position["longs"])
        self.assertEqual({}, position["shorts"])
        self.assertEqual({"near": 1.0}, position["long_leg"])
        self.assertAlmostEqual(1.0, sum(position["short_leg"].values()))

    def test_diagnostic_leg_returns_are_independent_of_portfolio_weights(self):
        rows, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1, enable_slv_leg=False,
                       enable_cash_long_futures_leg=False,
                       enable_short_book=False, slv_expense=0))
        self.assertTrue(all(row["slv_weight_pct"] == 100 for row in rows))
        self.assertTrue(all(row["long_futures_notional_pct"] == 0 for row in rows))
        self.assertTrue(all(row["short_futures_notional_pct"] == 0 for row in rows))
        self.assertAlmostEqual(10.0, rows[0]["slv_daily_return_pct"])
        self.assertAlmostEqual(2.0, rows[0]["long_futures_daily_return_pct"])
        self.assertIsNotNone(rows[0]["short_futures_daily_return_pct"])
        self.assertEqual(0.0, rows[0]["long_weighted_lease_rate_pct"])
        self.assertEqual(0.0, rows[0]["short_weighted_lease_rate_pct"])
        self.assertEqual(0.0, rows[0]["long_weighted_forward_premium_pct"])
        self.assertEqual(0.0, rows[0]["short_weighted_forward_premium_pct"])

    def test_short_leg_uses_strategy_maturities_when_short_is_nonzero(self):
        candidates = [
            {"symbol": "negative", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.10, "volume": 10},
            {"symbol": "positive", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.10, "volume": 5},
        ]
        position = positions_for_day(candidates, Parameters(min_days=1))
        self.assertGreater(sum(position["shorts"].values()), 0)
        self.assertEqual(position["shorts"], position["short_leg"])
        self.assertEqual({"negative"}, set(position["short_leg"]))

    def test_sleeves_are_proportional_to_available_signal_strength(self):
        candidates = [
            {"symbol": "positive", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.075, "volume": 10},
            {"symbol": "negative", "days": 90, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.0775, "volume": 10},
        ]
        position = positions_for_day(candidates, Parameters(min_days=1))
        self.assertAlmostEqual(1.0, position["base_treasury"] + position["base_slv"])
        self.assertGreater(position["treasury"], position["base_treasury"])
        self.assertGreater(
            position["treasury"] + position["slv"],
            position["base_treasury"] + position["base_slv"])
        self.assertEqual("long_and_short", position["mode"])

    def test_only_available_sleeve_receives_capital(self):
        positive = [{"symbol": "positive", "days": 30, "future": 100,
                     "spot": 100, "rate": 0, "premium": 0,
                     "lease": 0.075, "volume": 10}]
        negative = [{"symbol": "negative", "days": 30, "future": 100,
                     "spot": 100, "rate": 0, "premium": 0,
                     "lease": -0.0775, "volume": 10}]
        positive_position = positions_for_day(positive, Parameters(min_days=1))
        self.assertAlmostEqual(
            1.0,
            positive_position["base_slv"] +
            positive_position["base_treasury"],
        )
        self.assertAlmostEqual(0.25, positive_position["base_treasury"])
        self.assertEqual(1.0, positions_for_day(negative, Parameters(min_days=1))["base_slv"])

    def test_long_can_select_highest_lease_rate_instead_of_shortest_maturity(self):
        candidates = [
            {"symbol": "near", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.03, "volume": 10},
            {"symbol": "far", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.08, "volume": 5},
        ]
        default = positions_for_day(candidates, Parameters(min_days=1))
        highest = positions_for_day(
            candidates,
            Parameters(min_days=1, long_contract_selection="highest_lease_rate"))
        self.assertEqual({"near"}, set(default["longs"]))
        self.assertEqual({"far"}, set(highest["longs"]))
        self.assertEqual({"far": 1.0}, highest["long_leg"])

    def test_highest_lease_selection_still_enforces_entry_threshold(self):
        candidates = [
            {"symbol": "near", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.02, "volume": 10},
            {"symbol": "far", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.04, "volume": 5},
        ]
        position = positions_for_day(
            candidates,
            Parameters(min_days=1, positive_entry_rate=0.05,
                       long_contract_selection="highest_lease_rate"))
        self.assertEqual({}, position["longs"])

    def test_long_can_use_all_maturities_weighted_by_lease_edge(self):
        candidates = [
            {"symbol": "low", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.03, "volume": 10},
            {"symbol": "high", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.09, "volume": 5},
        ]
        position = positions_for_day(
            candidates,
            Parameters(min_days=1, positive_entry_rate=0.01,
                       long_contract_selection="weighted_lease_rate",
                       long_relative_strength=0))
        self.assertEqual({"low", "high"}, set(position["longs"]))
        self.assertAlmostEqual(
            math.exp((0.09 - 0.03) / 0.01),
            position["longs"]["high"] / position["longs"]["low"])

    def test_weighted_long_score_favors_shorter_maturity(self):
        candidates = [
            {"symbol": "near", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.05, "volume": 10},
            {"symbol": "far", "days": 395, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": 0.05, "volume": 5},
        ]
        position = positions_for_day(
            candidates,
            Parameters(min_days=1, long_contract_selection="weighted_lease_rate",
                       long_maturity_line_slope_per_year=0.04,
                       long_relative_strength=1))
        self.assertGreater(position["longs"]["near"], position["longs"]["far"])

    def test_short_can_select_only_lowest_lease_rate(self):
        candidates = [
            {"symbol": "low", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.10, "volume": 10},
            {"symbol": "higher", "days": 300, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.05, "volume": 5},
        ]
        position = positions_for_day(
            candidates,
            Parameters(min_days=1, short_contract_selection="lowest_lease_rate"))
        self.assertEqual({"low"}, set(position["shorts"]))

    def test_weighted_short_uses_all_eligible_maturities_without_a_share_cap(self):
        candidates = [
            {"symbol": "strong", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.10, "volume": 10},
            {"symbol": "weak", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.01, "volume": 5},
        ]
        position = positions_for_day(candidates, Parameters(min_days=1))
        self.assertEqual({"strong", "weak"}, set(position["shorts"]))
        total = sum(position["shorts"].values())
        self.assertGreater(position["shorts"]["strong"] / total, 0.5)

    def test_weighted_short_is_proportional_to_lease_edge_from_entry(self):
        candidates = [
            {"symbol": "strong", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.095, "volume": 10},
            {"symbol": "weak", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.035, "volume": 5},
        ]
        position = positions_for_day(
            candidates,
            Parameters(min_days=1, negative_short_start_rate=-0.005,
                       short_relative_strength=0))
        self.assertAlmostEqual(
            math.exp((0.095 - 0.035) / 0.01),
            position["shorts"]["strong"] / position["shorts"]["weak"])

    def test_weighted_short_score_favors_longer_maturity(self):
        candidates = [
            {"symbol": "near", "days": 30, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.05, "volume": 10},
            {"symbol": "far", "days": 395, "future": 100, "spot": 100,
             "rate": 0, "premium": 0, "lease": -0.05, "volume": 5},
        ]
        position = positions_for_day(
            candidates,
            Parameters(min_days=1, short_maturity_line_slope_per_year=-0.04,
                       short_relative_strength=1, score_rate_scale=0.1))
        self.assertGreater(position["shorts"]["far"], position["shorts"]["near"])

    def test_weekends_are_not_position_or_return_dates(self):
        friday = date(2020, 1, 3)
        saturday = date(2020, 1, 4)
        monday = date(2020, 1, 6)
        tuesday = date(2020, 1, 7)
        days = [friday, saturday, monday, tuesday]
        spot = {day: 100 + index for index, day in enumerate(days)}
        contracts = {"near": {day: 100 for day in days}}
        rates = {tenor: [(friday, 0.0)] for tenor in
                 (91, 182, 365, 730, 1095, 1825)}
        candidate = {"symbol": "near", "days": 30, "future": 100,
                     "spot": 100, "rate": 0, "premium": 0,
                     "lease": 0, "volume": 10}
        by_day = {day: [dict(candidate)] for day in days}
        rows, _ = run_backtest(spot, contracts, rates, by_day, Parameters(min_days=1))
        self.assertEqual(
            [friday.isoformat(), monday.isoformat()],
            [row["date"] for row in rows])
        self.assertEqual(friday.isoformat(), rows[0]["signal_date"])
        self.assertEqual(friday.isoformat(), rows[0]["execution_date"])

    def test_reactivity_selects_same_or_next_available_execution_day(self):
        same_day, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1, reactivity="same_day"))
        next_day, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1, reactivity="next_day"))
        self.assertEqual(self.days[0].isoformat(), same_day[0]["signal_date"])
        self.assertEqual(self.days[0].isoformat(), same_day[0]["execution_date"])
        self.assertEqual(self.days[0].isoformat(), next_day[0]["signal_date"])
        self.assertEqual(self.days[1].isoformat(), next_day[0]["execution_date"])
        self.assertEqual(len(same_day) - 1, len(next_day))

    def test_future_quote_perturbation_cannot_change_earlier_decisions(self):
        baseline, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1))
        changed_contracts = {
            symbol: dict(prices) for symbol, prices in self.contracts.items()}
        changed_contracts["near"][self.days[-1]] *= 10
        changed_by_day = {
            day: [dict(item) for item in candidates]
            for day, candidates in self.by_day.items()}
        changed_by_day[self.days[-1]][0]["future"] *= 10
        changed, _ = run_backtest(
            self.spot, changed_contracts, self.rates, changed_by_day,
            Parameters(min_days=1))
        decision_fields = ("signal_date", "execution_date", "mode",
                           "long_symbols", "short_symbols")
        for before, after in zip(baseline[:-1], changed[:-1]):
            self.assertEqual(
                tuple(before[field] for field in decision_fields),
                tuple(after[field] for field in decision_fields))

    def test_missing_leg_returns_are_reported_with_dates_and_symbol(self):
        del self.contracts["near"][self.days[2]]
        rows, missing = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1, positive_entry_rate=-0.01))
        self.assertTrue(missing)
        self.assertEqual("near", missing[0]["symbol"])
        self.assertEqual(self.days[2].isoformat(), missing[0]["exit_date"])
        self.assertNotEqual(len(self.days) - 2, len(rows))

    def test_futures_diagnostics_summarize_eligible_contracts(self):
        rows = [{"date": self.days[0].isoformat()}]
        self.by_day[self.days[0]] = [
            {"symbol": "low", "days": 30, "future": 101, "premium": 0.01,
             "lease": -0.05},
            {"symbol": "high", "days": 60, "future": 103, "premium": 0.03,
             "lease": 0.04},
            {"symbol": "too_short", "days": 5, "future": 90, "premium": -0.10,
             "lease": -0.50},
        ]
        diagnostics = futures_diagnostics(rows, self.by_day, Parameters(min_days=10))
        self.assertEqual(2, diagnostics[0]["available"])
        self.assertEqual(30, diagnostics[0]["shortest_maturity_days"])
        self.assertEqual(60, diagnostics[0]["longest_maturity_days"])
        self.assertEqual("low", diagnostics[0]["lowest_lease"]["symbol"])
        self.assertEqual("high", diagnostics[0]["highest_lease"]["symbol"])
        self.assertAlmostEqual(1.0, diagnostics[0]["lowest_premium_pct"])
        self.assertAlmostEqual(3.0, diagnostics[0]["highest_premium_pct"])

    def test_output_includes_eligible_futures_maturity_range(self):
        rows, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=100, slv_expense=0))
        self.assertEqual(300, rows[0]["available_futures_min_maturity_days"])
        self.assertEqual(300, rows[0]["available_futures_max_maturity_days"])

    def test_output_maturities_match_plotted_forward_and_lease_series(self):
        rows, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1, slv_expense=0))
        self.assertEqual(30, rows[0]["long_forward_maturity_days"])
        self.assertGreater(rows[0]["short_forward_maturity_days"], 30)
        self.assertLess(rows[0]["short_forward_maturity_days"], 300)

    def test_market_diagnostics_use_the_displayed_output_date(self):
        self.by_day[self.days[0]][0]["lease"] = -0.05
        self.by_day[self.days[2]][0]["lease"] = 0.08
        self.by_day[self.days[2]][0]["days"] = 28
        rows, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1, slv_expense=0))
        self.assertEqual(self.days[0].isoformat(), rows[0]["date"])
        self.assertAlmostEqual(-5.0, rows[0]["long_weighted_lease_rate_pct"])
        self.assertEqual(30, rows[0]["available_futures_min_maturity_days"])

    def test_rate_change_attribution_is_contract_level_and_reconciled(self):
        rows, _ = run_backtest(
            self.spot, self.contracts, self.rates, self.by_day,
            Parameters(min_days=1, positive_entry_rate=-0.01, slv_expense=0))
        points = rows[0]["rate_change_attribution_points"]
        self.assertEqual({"long", "short"}, {point["leg"] for point in points})
        self.assertTrue(any(point["instruments"] for point in points))
        components = sum(rows[0][name] for name in (
            "silver_price_return_contribution_pct",
            "slv_expense_contribution_pct",
            "treasury_return_contribution_pct",
            "lease_carry_contribution_pct",
            "lease_rate_change_contribution_pct",
            "rolling_contribution_pct",
            "other_return_contribution_pct",
        ))
        self.assertAlmostEqual(rows[0]["interval_return_pct"], components)

    def test_usd_rate_interpolates_missing_observation_dates(self):
        series = {tenor: [(date(2020, 1, 1), 0.01), (date(2020, 1, 11), 0.03)]
                  for tenor in (91, 182, 365, 730, 1095, 1825)}
        self.assertAlmostEqual(0.02, usd_rate(series, date(2020, 1, 6), 365))


if __name__ == "__main__":
    unittest.main()
