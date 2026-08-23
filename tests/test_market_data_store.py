import sqlite3
import tempfile
import unittest
from pathlib import Path

from market_data_store import build_database, read_cached_asset


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


if __name__ == "__main__":
    unittest.main()
