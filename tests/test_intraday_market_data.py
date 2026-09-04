import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from market_data_store import load_intraday_market


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


class IntradayMarketDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        intraday = self.root / "data" / "btc" / "intraday"
        (intraday / "deribit_1m" / "futures").mkdir(parents=True)
        (intraday / "tardis_quotes").mkdir()
        (intraday / "config.json").write_text(json.dumps({
            "active_provider": "deribit_1m",
            "providers": {
                "deribit_1m": {
                    "format": "deribit_candles",
                    "path": "deribit_1m",
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


if __name__ == "__main__":
    unittest.main()
