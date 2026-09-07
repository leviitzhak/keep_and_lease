import json
from pathlib import Path
import unittest
from unittest.mock import patch

from backtest_audit import AuditCollection, MemoryAuditStore, read_chunk
import btc_trade_backtest as replay
from trade_replay import Trade

ROOT = Path(__file__).resolve().parents[1]


def payload():
    value = json.loads((ROOT / "strategies/research-btc-long-gradual-500ms.json").read_text())["parameters"]
    value["backtest_end"] = "2026-06-25T00:00:02"
    value["commodity_parameters"]["btc"].update(long_futures_entry_mode="fixed", execution_delay_seconds="0.001")
    return value


class FakeStore:
    def __init__(self):
        self.start = replay.us_time(replay.START)
        self.source_manifest = dict(start=replay.START, end=replay.END, futures={
            "F": dict(expiry="2026-09-25T08:00:00", seed={"timestamp": self.start//1000-1,
                      "price": 100, "amount": 10000, "direction": "buy", "trade_id": "seed"})})
        self.manifest = {"partitions": []}
        self.manifest_bytes = b"synthetic-fixture"
        self.events = [Trade(self.start+us, symbol, price, 10000, side, str(us))
                       for us, symbol, price, side in [
                           (100, "SPOT", 100, "buy"), (500000, "SPOT", 100, "sell"),
                           (501000, "SPOT", 100, "sell"), (502000, "SPOT", 100, "sell"),
                           (503000, "F", 100, "buy"), (1100000, "F", 101, "buy"),
                           (1500000, "SPOT", 102, "buy"), (2000000, "SPOT", 999, "buy")]]

    def trades(self, start_us=None, end_us=None, symbols=None):
        return iter(t for t in self.events if (start_us is None or t.us >= start_us)
                    and (end_us is None or t.us < end_us) and (symbols is None or t.symbol in symbols))


class BtcTradeBacktestTests(unittest.TestCase):
    def simulate(self, parameters=None, store=None):
        audit = AuditCollection(MemoryAuditStore())
        with patch.object(replay.strategy, "read_rates", return_value={}), patch.object(replay.strategy, "usd_rate", return_value=.05):
            result = replay.run(parameters or payload(), ROOT, audit, store=store or FakeStore())
        rows = {product: [row for entry in data["chunks"] for row in read_chunk(audit.store, entry)]
                for product, data in result["audit"]["datasets"].items()}
        return result, rows

    def test_fractional_clock_strict_delay_half_open_end_and_reconciliation(self):
        result, rows = self.simulate()
        start = FakeStore().start
        valuations = rows["btc_trade_valuations"]
        self.assertEqual([r["us"]-start for r in valuations], [500000, 1000000, 1500000, 2000000])
        events = rows["btc_trade_events"]
        fills = [r for r in events if r["kind"] == "fill"]
        self.assertGreater(len(fills), 0)
        self.assertEqual(fills[0]["us"]-start, 502000)
        orders = {r["order_id"]: r for r in events if r["kind"] == "order"}
        for fill in fills:
            self.assertGreater(fill["us"], orders[fill["order_id"]]["eligible_after_us"])
            self.assertLessEqual(abs(fill["signed_btc"]), .1 * fill["observed_btc"])
        self.assertEqual(result["trade_replay"]["decisions"], 3)
        self.assertEqual(result["trade_replay"]["market_events"], 7)
        self.assertEqual(result["series"][-1][2], 1.02)  # end-boundary print excluded
        self.assertLess(result["trade_replay"]["max_nav_reconstruction_error_usd"], 1e-7)
        self.assertTrue(all(r["kind"] != "order" or r["us"] < start+2000000 for r in events))

    def test_millisecond_clock_and_non_grid_final_boundary(self):
        p = payload()
        p.update(execution_interval_seconds=.001, backtest_end="2026-06-25T00:00:00.004500")
        result, rows = self.simulate(p)
        self.assertEqual([r["us"]-FakeStore().start for r in rows["btc_trade_valuations"]], [1000,2000,3000,4000,4500])
        self.assertEqual(result["trade_replay"]["decisions"], 4)

    def test_selected_window_starts_fresh_and_uses_prior_causal_marks(self):
        p = payload()
        p["backtest_start"] = "2026-06-25T00:00:01.200"
        result, rows = self.simulate(p)
        self.assertEqual(result["series"][0][1:3], [1.0,1.0])
        self.assertEqual(result["trade_replay"]["market_events"], 1)
        self.assertEqual(rows["btc_trade_valuations"][-1]["mark_us"]["F"], FakeStore().start+1100000)

    def test_stale_signal_cancels_pending_without_erasing_holdings(self):
        p = payload()
        p["commodity_parameters"]["btc"]["max_quote_age_seconds"] = .51
        store = FakeStore()
        store.events = [t for t in store.events if t.us != store.start+1100000]
        result, rows = self.simulate(p, store)
        self.assertGreater(result["trade_replay"]["no_fresh_curve_decisions"], 0)
        self.assertGreater(rows["btc_trade_valuations"][-1]["units"].get("F", 0), 0)

    def test_rejects_unsupported_frequency_period_and_settings(self):
        for update in [dict(execution_interval_seconds=0), dict(execution_interval_seconds=.0005),
                       dict(execution_interval_seconds=.0015), dict(execution_interval_seconds=float("nan")),
                       dict(backtest_start="2026-06-24"), dict(backtest_end="2026-06-27"),
                       dict(execution_interval_seconds=.001, backtest_end=replay.END),
                       dict(weight_silver=1), dict(weight_treasury=1), dict(reactivity="next_day")]:
            p = payload(); p.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                replay.validate(p)
        for update in [dict(futures_contract_type="inverse"), dict(enable_short_book="true"),
                       dict(half_spread_bps=1), dict(slv_expense=1), dict(max_volume_participation=0),
                       dict(execution_delay_seconds=.0001), dict(execution_model="legacy_close")]:
            p = payload(); p["commodity_parameters"]["btc"].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                replay.validate(p)

    def test_request_clock_overrides_nested_clock(self):
        p = payload(); p["commodity_parameters"]["btc"]["execution_interval_seconds"] = 60
        self.assertEqual(replay.validate(p)[0].execution_interval_seconds, .5)

    def test_cancellation_reaches_replay(self):
        audit = AuditCollection(MemoryAuditStore(), check_cancelled=lambda: (_ for _ in ()).throw(RuntimeError("cancelled")))
        with patch.object(replay.strategy, "read_rates", return_value={}), self.assertRaisesRegex(RuntimeError, "cancelled"):
            replay.run(payload(), ROOT, audit, store=FakeStore())

    def test_api_rejects_before_launch_and_exposes_coverage(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        from tests.test_server_api import FakeEngine
        with TestClient(create_app(FakeEngine())) as client:
            self.assertEqual(client.get("/api/v1/trade-data").json()["datasets"][0]["minimum_interval_seconds"], .001)
            p = payload(); p["backtest_end"] = "2026-07-01"
            self.assertEqual(client.post("/api/v1/backtests", json={"parameters": p}).status_code, 400)

    def test_job_result_audit_and_csv_lifecycle(self):
        import csv
        import io
        import time
        from fastapi.testclient import TestClient
        from server.app import create_app
        from tests.test_server_api import FakeEngine
        class Engine(FakeEngine):
            def run_backtest_with_audit(self, parameters, audit, progress):
                return replay.run(parameters, ROOT, audit, progress, store=FakeStore())
        with patch.object(replay.strategy, "read_rates", return_value={}), patch.object(replay.strategy, "usd_rate", return_value=.05), TestClient(create_app(Engine())) as client:
            created = client.post("/api/v1/backtests", json={"parameters": payload()}).json()
            for _ in range(100):
                state = client.get(created["status_url"]).json()
                if state["status"] in ("completed", "failed"):
                    break
                time.sleep(.01)
            self.assertEqual(state["status"], "completed", state)
            result = client.get(created["result_url"]).json()
            url = created["result_url"].removesuffix("/result")
            rows = list(csv.DictReader(io.StringIO(client.get(url+"/trade-valuations.csv").text)))
            self.assertEqual(len(rows), result["summary"]["observations"])
            self.assertEqual(rows[-1]["date"], result["summary"]["end"])
            raw = client.get(url+"/audit/btc_trade_valuations/0").json()["rows"][-1]
            self.assertEqual(json.loads(rows[-1]["units"]), raw["units"])
            archive = client.get(url+"/audit-download")
            self.assertEqual(archive.status_code, 200)
            self.assertTrue(archive.content.startswith(b"PK"))
