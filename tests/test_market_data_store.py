import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from market_data_store import (
    build_database, read_cached_asset, read_contract_csvs, read_spot_csv)


ROOT = Path(__file__).resolve().parents[1]


class MarketDataStoreTests(unittest.TestCase):
    def test_database_contains_all_materialized_curve_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            database = build_database(ROOT, Path(directory) / "market.sqlite3")
            with sqlite3.connect(database) as connection:
                assets = dict(connection.execute(
                    "SELECT asset, count(DISTINCT symbol) FROM future GROUP BY asset"))
            self.assertGreaterEqual(assets["silver"], 270)
            self.assertGreaterEqual(assets["gold"], 210)
            self.assertGreaterEqual(assets["sp500"], 80)
            self.assertGreaterEqual(assets["btc"], 450)

    def test_cached_gold_is_read_without_legacy_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "data" / "market.sqlite3"
            target.parent.mkdir()
            build_database(ROOT, target)
            spot, contracts, volumes = read_cached_asset(root, "gold")
            self.assertTrue(spot)
            self.assertGreaterEqual(len(contracts), 210)
            self.assertTrue(volumes)

    def test_cached_btc_keeps_deribit_contract_names_and_daily_spot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "data" / "market.sqlite3"
            target.parent.mkdir()
            build_database(ROOT, target)
            spot, contracts, volumes = read_cached_asset(root, "btc")
            self.assertGreaterEqual(len(spot), 3500)
            self.assertGreaterEqual(len(contracts), 450)
            self.assertTrue(all(symbol.startswith("BTC-") for symbol in contracts))
            self.assertTrue(volumes)

    def test_csv_readers_preserve_intraday_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "data" / "btc"
            futures = asset / "futures"
            futures.mkdir(parents=True)
            (asset / "spot.csv").write_text(
                "timestamp,close\n2026-01-05T10:15:00Z,90000\n",
                encoding="utf-8",
            )
            (futures / "BTC-30JAN26.csv").write_text(
                "timestamp,open,high,low,close,volume\n"
                "2026-01-05T10:15:00Z,90100,90100,90100,90100,2\n",
                encoding="utf-8",
            )
            timestamp = datetime(2026, 1, 5, 10, 15)
            self.assertEqual(read_spot_csv(root, "btc"), {timestamp: 90000})
            contracts, volumes = read_contract_csvs(root, "btc", "BTC")
            self.assertEqual(contracts["BTC-30JAN26"][timestamp], 90100)
            self.assertEqual(volumes[("BTC-30JAN26", timestamp)], 2)

    def test_unreadable_cache_has_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "data" / "market.sqlite3"
            target.parent.mkdir()
            target.write_text("not a sqlite database", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SQLite cache is unreadable"):
                read_cached_asset(root, "gold")


if __name__ == "__main__":
    unittest.main()
