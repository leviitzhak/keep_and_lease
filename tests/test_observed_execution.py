import copy
import unittest
from datetime import datetime, timedelta
from dataclasses import replace

from backtest_silver_lease_strategy import Parameters, run_backtest
from observed_execution import ObservedExecution
from tests.test_streamed_backtest import StreamedBacktestTests


class ObservedExecutionTests(unittest.TestCase):
    def market(self):
        market = StreamedBacktestTests().market()
        for day, curve in market[3].items():
            curve[0].update(observed=True, spot_observed=True, source_kind="candle",
                available_at=day, observation_start=day-timedelta(minutes=1),
                last_observed_at=day, quote_age_seconds=0)
        return market

    def parameters(self, **kwargs):
        return replace(Parameters(min_days=1, futures_contract_type="regular",
            trading_calendar="all_days", execution_interval_seconds=60,
            enable_short_book=False, execution_model="observed", slv_expense=0), **kwargs)

    def test_no_fill_on_signal_bar_or_carried_candle_and_no_skipped_intervals(self):
        market = self.market()
        days = sorted(market[0])
        for day in days[2:5]:
            market[3][day][0].update(observed=False, volume=0, quote_age_seconds=180)
        for lag in ("same_day", "next_day"):
            rows, missing = run_backtest(*market, self.parameters(reactivity=lag))
            self.assertEqual(len(rows), len(days)-1)
            self.assertEqual(missing, [])
            self.assertEqual(rows[0]["execution_audit"]["fills"], [])
            held = None
            for row in rows:
                day = datetime.fromisoformat(row["date"])
                quantity = sum(h["quantity"] for h in row["holding_ledger"] if h["holding_type"] == "future")
                if day in days[2:5]:
                    self.assertEqual(row["execution_audit"]["fills"], [])
                    self.assertAlmostEqual(quantity, held)
                held = quantity
                for fill in row["execution_audit"]["fills"]:
                    self.assertGreater(fill["fill_time"], fill["signal_time"])
                    if fill["symbol"] != "BTC-USD":
                        self.assertGreaterEqual(fill["observation_start"], fill["signal_time"])
                        self.assertTrue(fill["observed"])

    def test_future_observations_cannot_change_prior_decisions_or_returns(self):
        market = self.market()
        later = copy.deepcopy(market)
        change_day = sorted(market[0])[5]
        later[0][change_day] *= 1.1
        later[1]["BTC-test"][change_day] *= 1.1
        later[3][change_day][0]["future"] *= 1.1
        before, _ = run_backtest(*market, self.parameters())
        after, _ = run_backtest(*later, self.parameters())
        for left, right in zip(before, after):
            if left["exit_date"] < change_day.isoformat():
                self.assertEqual(left, right)

    def test_costs_reconcile_nav_book_and_holding_ledger(self):
        p = self.parameters(trading_fee_bps=2, half_spread_bps=1, slippage_bps=1)
        rows, _ = run_backtest(*self.market(), p)
        free, _ = run_backtest(*self.market(), replace(p, trading_fee_bps=0, half_spread_bps=0, slippage_bps=0))
        self.assertLess(rows[-1]["ending_nav"], free[-1]["ending_nav"])
        self.assertGreater(sum(row["trading_cost_value"] for row in rows), 0)
        for row in rows:
            ledger = row["holding_ledger"]
            self.assertAlmostEqual(sum(h["start_value"] for h in ledger), row["starting_nav"])
            self.assertAlmostEqual(sum(h["end_value"] for h in ledger), row["ending_nav"])
            self.assertAlmostEqual(sum(h["pnl_value"] for h in ledger), row["ending_nav"]-row["starting_nav"])
            self.assertAlmostEqual(sum(h["internal_transfer_value"] for h in ledger), 0)
            for h in ledger:
                self.assertAlmostEqual(h["start_value"]+h["pnl_value"]+h["internal_transfer_value"], h["end_value"])

    def test_capacity_limits_fills_and_pending_inventory_is_not_rebalanced(self):
        market=self.market()
        for curve in market[3].values():
            curve[0]["volume"]=0.00001
        rows,_=run_backtest(*market,self.parameters(max_volume_participation=0.25))
        futures=[f for row in rows for f in row["execution_audit"]["fills"] if f["symbol"]!="BTC-USD"]
        self.assertTrue(futures)
        self.assertTrue(all(abs(f["quantity_change"]) <= 0.0000025+1e-15 for f in futures))
        self.assertTrue(any(p["reason"]=="partial fill" for row in rows for p in row["execution_audit"]["pending_orders"]))

    def test_bid_ask_and_missing_settlement(self):
        market=self.market()
        for curve in market[3].values():
            curve[0].update(source_kind="quote", bid=curve[0]["future"]-0.1,
                ask=curve[0]["future"]+0.1, bid_size=0.01, ask_size=0.01)
        rows,_=run_backtest(*market,self.parameters())
        fills=[f for row in rows for f in row["execution_audit"]["fills"] if f["symbol"]!="BTC-USD"]
        self.assertTrue(fills)
        self.assertTrue(all(f["price_cost_usd"] > 0 for f in fills))
        del market[1]["BTC-test"][sorted(market[0])[3]]
        with self.assertRaisesRegex(ValueError,"Missing"):
            run_backtest(*market,self.parameters())

    def test_unsupported_settlement_and_short_book_are_explicit(self):
        for p in (self.parameters(futures_contract_type="inverse"), self.parameters(enable_short_book=True)):
            with self.assertRaisesRegex(ValueError,"regular futures"):
                run_backtest(*self.market(),p)

    def test_legacy_model_cannot_silently_ignore_requested_trading_costs(self):
        with self.assertRaisesRegex(ValueError,"controls require observed"):
            run_backtest(*self.market(),self.parameters(execution_model="legacy_close",trading_fee_bps=1))


if __name__ == "__main__":
    unittest.main()
