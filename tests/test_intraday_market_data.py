import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtest_silver_lease_strategy import TENORS, build_intraday_btc_market
from market_data_store import load_intraday_market


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


class IntradayMarketDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        intraday = self.root / "data" / "btc" / "intraday"
        (intraday / "deribit_1m" / "futures").mkdir(parents=True)
        (intraday / "kraken_1m").mkdir()
        (intraday / "tardis_quotes").mkdir()
        (intraday / "config.json").write_text(json.dumps({
            "active_provider": "deribit_1m",
            "active_providers": {
                "spot": "kraken_1m",
                "futures": "deribit_1m",
            },
            "providers": {
                "deribit_1m": {
                    "format": "deribit_candles",
                    "path": "deribit_1m",
                },
                "kraken_1m": {
                    "format": "kraken_spot_candles",
                    "path": "kraken_1m",
                },
                "tardis_quotes": {
                    "format": "tardis_quotes",
                    "path": "tardis_quotes",
                },
            },
        }), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def write_candles(self):
        path = (self.root / "data" / "btc" / "intraday" /
                "deribit_1m" / "futures" / "BTC-25SEP26.csv.gz")
        with gzip.open(path, "wt", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("timestamp", "open", "high", "low", "close", "volume"))
            writer.writerow(("2026-09-01T00:00Z", 100, 102, 99, 101, 2))
            writer.writerow(("2026-09-01T00:01Z", 101, 103, 100, 102, 0))

    def write_tardis_quotes(self):
        path = (self.root / "data" / "btc" / "intraday" /
                "tardis_quotes" / "quotes.csv")
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow((
                "exchange", "symbol", "timestamp", "local_timestamp",
                "ask_amount", "ask_price", "bid_price", "bid_amount"))
            writer.writerow((
                "deribit", "BTC-25SEP26", 1788220800000000,
                1788220800000100, 4, 102, 100, 3))

    def write_kraken_candles(self):
        path = (self.root / "data" / "btc" / "intraday" /
                "kraken_1m" / "spot.csv.gz")
        with gzip.open(path, "wt", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow((
                "timestamp", "symbol", "open", "high", "low", "close",
                "quote_count"))
            writer.writerow((
                "2026-09-01T00:00Z", "BTC-USD", 99, 102, 98, 101, 17))

    def test_deribit_candles_are_normalized_and_flag_filled_minutes(self):
        self.write_candles()
        observations = list(load_intraday_market(self.root).iter_observations())

        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0].timestamp,
                         datetime(2026, 9, 1, tzinfo=UTC))
        self.assertEqual(observations[0].available_at,
                         datetime(2026, 9, 1, 0, 1, tzinfo=UTC))
        self.assertEqual(observations[0].reference_price, 101)
        self.assertTrue(observations[0].observed)
        self.assertFalse(observations[1].observed)
        self.assertEqual(observations[1].execution_price("buy"), 102)

    def test_tardis_quotes_use_same_boundary_and_expose_executable_sides(self):
        self.write_tardis_quotes()
        observation = next(load_intraday_market(
            self.root, provider="tardis_quotes").iter_observations())

        self.assertEqual(observation.timestamp,
                         datetime(2026, 9, 1, tzinfo=UTC))
        self.assertEqual(observation.reference_price, 101)
        self.assertEqual(observation.execution_price("buy"), 102)
        self.assertEqual(observation.execution_price("sell"), 100)

    def test_spot_role_loads_kraken_minute_close_at_end_of_bar(self):
        self.write_kraken_candles()
        observation = next(load_intraday_market(
            self.root, role="spot").iter_observations())

        self.assertEqual(observation.symbol, "BTC-USD")
        self.assertEqual(observation.timestamp,
                         datetime(2026, 9, 1, tzinfo=UTC))
        self.assertEqual(observation.effective_time,
                         datetime(2026, 9, 1, 0, 1, tzinfo=UTC))
        self.assertEqual(observation.reference_price, 101)
        self.assertEqual(observation.source, "kraken")
        self.assertTrue(observation.observed)

    def test_tardis_normalizes_kraken_xbt_alias_for_provider_swaps(self):
        path = (self.root / "data" / "btc" / "intraday" /
                "tardis_quotes" / "kraken.csv")
        path.write_text(
            "exchange,symbol,timestamp,local_timestamp,ask_amount,ask_price,"
            "bid_price,bid_amount\n"
            "kraken,XBT/USD,1788220800000000,1788220800000100,4,102,100,3\n",
            encoding="utf-8",
        )

        observation = next(load_intraday_market(
            self.root, provider="tardis_quotes").iter_observations())

        self.assertEqual(observation.symbol, "BTC-USD")
        self.assertEqual(observation.source, "kraken")

    def test_asof_snapshot_never_uses_a_future_candle(self):
        self.write_candles()
        schedule = [
            datetime(2026, 9, 1, 0, 0, 30, tzinfo=UTC),
            datetime(2026, 9, 1, 0, 1, 30, tzinfo=UTC),
            datetime(2026, 9, 1, 0, 2, tzinfo=UTC),
        ]

        snapshots = list(load_intraday_market(self.root).iter_snapshots(schedule))

        self.assertEqual(snapshots[0].observations, {})
        self.assertEqual(
            snapshots[1].reference_prices()["BTC-25SEP26"], 101)
        self.assertEqual(
            snapshots[2].reference_prices()["BTC-25SEP26"], 102)

    def test_snapshot_can_reject_stale_observations(self):
        self.write_candles()
        snapshots = list(load_intraday_market(self.root).iter_snapshots(
            [datetime(2026, 9, 1, 0, 2, 31, tzinfo=UTC)],
            max_age=timedelta(seconds=30),
        ))

        self.assertEqual(snapshots[0].observations, {})

    def test_schedule_must_be_strictly_increasing(self):
        self.write_candles()
        instant = datetime(2026, 9, 1, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            list(load_intraday_market(self.root).iter_snapshots(
                [instant, instant]))

    def test_btc_market_joins_independent_spot_and_futures_roles(self):
        self.write_kraken_candles()
        self.write_candles()
        manifest = (self.root / "data" / "btc" / "intraday" /
                    "deribit_1m" / "manifest.json")
        manifest.write_text(json.dumps({
            "contracts": {
                "BTC-25SEP26": {
                    "expiration_timestamp": "2026-09-25T08:00Z",
                },
            },
        }), encoding="utf-8")
        for _, name in TENORS:
            (self.root / f"{name}.csv").write_text(
                f"observation_date,{name}\n2026-08-31,5.0\n",
                encoding="utf-8",
            )

        spot, contracts, _, curves = build_intraday_btc_market(self.root)
        instant = datetime(2026, 9, 1, 0, 1)

        self.assertEqual(spot, {instant: 101})
        self.assertEqual(contracts["BTC-25SEP26"][instant], 101)
        self.assertEqual(curves[instant][0]["rate"], 0.05)
        self.assertGreater(curves[instant][0]["days"], 24)

    def test_btc_market_accepts_tardis_futures_without_engine_changes(self):
        self.write_kraken_candles()
        self.write_tardis_quotes()
        config_path = (self.root / "data" / "btc" / "intraday" /
                       "config.json")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["active_providers"]["futures"] = "tardis_quotes"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest = (self.root / "data" / "btc" / "intraday" /
                    "deribit_1m" / "manifest.json")
        manifest.write_text(json.dumps({
            "contracts": {
                "BTC-25SEP26": {
                    "expiration_timestamp": "2026-09-25T08:00Z",
                },
            },
        }), encoding="utf-8")
        for _, name in TENORS:
            (self.root / f"{name}.csv").write_text(
                f"observation_date,{name}\n2026-08-31,5.0\n",
                encoding="utf-8",
            )

        spot, contracts, _, curves = build_intraday_btc_market(self.root)
        instant = datetime(2026, 9, 1, 0, 1)

        self.assertEqual(spot, {instant: 101})
        self.assertEqual(contracts["BTC-25SEP26"][instant], 101)
        self.assertGreater(curves[instant][0]["days"], 24)

    def test_checked_deribit_archive_has_selected_coverage(self):
        directory = ROOT / "public" / "data" / "btc" / "intraday" / "deribit_1m"
        manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["resolution"], "1m")
        self.assertEqual(manifest["from_timestamp"], "2026-06-06T00:00Z")
        self.assertEqual(
            manifest["to_timestamp_exclusive"], "2026-09-04T00:00Z")
        self.assertEqual(manifest["coverage"]["contract_count"], 93)
        self.assertGreater(manifest["coverage"]["rows"], 1_200_000)
        self.assertEqual(
            len(list((directory / "futures").glob("*.csv.gz"))), 93)

    def test_checked_kraken_archive_has_three_complete_sample_days(self):
        directory = ROOT / "public" / "data" / "btc" / "intraday" / "kraken_1m"
        manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["resolution"], "1m")
        self.assertEqual(manifest["symbol"], "BTC-USD")
        self.assertEqual(manifest["coverage"]["bars"], 4320)
        self.assertEqual(manifest["coverage"]["session_count"], 3)
        self.assertEqual(manifest["coverage"]["missing_minutes"], 0)
        self.assertTrue((directory / "spot.csv.gz").is_file())


if __name__ == "__main__":
    unittest.main()
