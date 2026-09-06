import csv
import gzip
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
from unittest.mock import patch

from backtest_silver_lease_strategy import (
    IndexedRateSeries, _select_intraday_spot_session, asof_rate,
    _rate_change_boundaries, accrued_yield_return)
from market_data_store import BinanceSpotCandleCsvProvider, IntradayMarketData

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "binance_refresh", ROOT / "scripts/refresh-binance-intraday-data.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class BinanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def write_archive(self, microseconds=True, skip=None):
        start = int(datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()) * 1000
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        scale = 1000 if microseconds else 1
        for minute in range(1440):
            if minute == skip:
                continue
            stamp = start + minute * 60000
            writer.writerow([stamp * scale, 100, 102, 99, 101, 4,
                             (stamp + 59999) * scale, 404, 2, 1, 101, 0])
        path = self.directory / "test.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("test.csv", buffer.getvalue())
        return path

    def test_epoch_units_and_exact_grid(self):
        for microseconds in (False, True):
            rows = list(refresh.minute_rows(
                [self.write_archive(microseconds)], date(2026, 6, 6), date(2026, 6, 7)))
            self.assertEqual(len(rows), 1440)
            self.assertEqual(rows[0][:2], ["2026-06-06T00:00Z", "BTC-USDT"])
            self.assertEqual(rows[-1][0], "2026-06-06T23:59Z")

    def test_missing_minutes_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing/duplicate"):
            list(refresh.minute_rows([self.write_archive(skip=21)],
                                     date(2026, 6, 6), date(2026, 6, 7)))

    def test_incomplete_tail_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete history"):
            list(refresh.minute_rows([self.write_archive()],
                                     date(2026, 6, 6), date(2026, 6, 8)))

    def test_duplicate_archive_rejected(self):
        path = self.write_archive()
        with self.assertRaisesRegex(ValueError, "Missing/duplicate"):
            list(refresh.minute_rows([path, path], date(2026, 6, 6), date(2026, 6, 7)))

    def test_checksum_mismatch_rejected(self):
        with patch.object(refresh, "fetch", side_effect=[b"a" * 64, b"incorrect"]):
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                refresh.archive("2026-06", "monthly", self.directory)

    def test_missing_monthly_archive_falls_back_to_ordered_days(self):
        def fake_archive(period, frequency, directory):
            if frequency == "monthly":
                raise urllib.error.HTTPError("test", 404, "missing", {}, None)
            return period, {"frequency": frequency}
        with patch.object(refresh, "archive", side_effect=fake_archive):
            downloaded = refresh.download(date(2026, 9, 1), date(2026, 9, 4), self.directory)
        self.assertEqual([day for day, _ in downloaded],
                         ["2026-09-01", "2026-09-02", "2026-09-03"])

    def test_permission_error_is_not_treated_as_missing_archive(self):
        with patch.object(refresh, "archive", side_effect=urllib.error.HTTPError(
                "test", 403, "forbidden", {}, None)):
            with self.assertRaises(urllib.error.HTTPError):
                refresh.download(date(2026, 9, 1), date(2026, 9, 4), self.directory)

    def test_futures_refresh_preserves_provider_config(self):
        spec = importlib.util.spec_from_file_location(
            "deribit_refresh", ROOT / "scripts/refresh-btc-intraday-data.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = self.directory / "config.json"
        original = '{"active_providers":{"spot":"binance_1m"}}'
        config.write_text(original)
        with patch.object(module, "CONFIG", config):
            module.write_config()
        self.assertEqual(config.read_text(), original)

    def test_proxy_provenance_and_no_lookahead(self):
        with gzip.open(self.directory / "spot.csv.gz", "wt") as stream:
            stream.write("timestamp,symbol,close,volume,trade_count\n"
                         "2026-06-06T00:00Z,BTC-USDT,101,4,2\n")
        market = IntradayMarketData(BinanceSpotCandleCsvProvider(self.directory))
        instant = datetime(2026, 6, 6, tzinfo=timezone.utc)
        snapshots = list(market.iter_snapshots([instant, instant + timedelta(minutes=1)]))
        self.assertEqual(snapshots[0].observations, {})
        observation = snapshots[1].observations["BTC-USD"]
        self.assertEqual(observation.reference_price, 101)
        self.assertEqual(observation.quote_currency, "USDT")
        self.assertEqual(observation.source_symbol, "BTC-USDT")
        self.assertEqual(observation.usd_conversion_rate_assumed, 1)
        self.assertIsNone(observation.bid_price)
        self.assertEqual(list(market.iter_observations(symbols={"OTHER"})), [])

    def test_continuous_manifest_does_not_select_one_day(self):
        (self.directory / "manifest.json").write_text(json.dumps({
            "coverage": {"continuous": True, "missing_minutes": 0}}))
        market = IntradayMarketData(BinanceSpotCandleCsvProvider(self.directory))
        observations = {datetime(2026, 6, 6): 100, datetime(2026, 9, 1): 110}
        self.assertEqual(_select_intraday_spot_session(market, observations), observations)

    def test_materialization_deterministic_and_failure_preserves_file(self):
        data = self.directory / "public/data"
        data.mkdir(parents=True)
        (data / "manifest.json").write_text("{}")
        source = self.write_archive()
        args = ([(source, {"sha256": "fixture"})], date(2026, 6, 6), date(2026, 6, 7))
        first = refresh.materialize(*args, root=self.directory)
        second = refresh.materialize(*args, root=self.directory)
        self.assertEqual(first["output"], second["output"])
        self.assertNotIn("btc_intraday_spot", json.loads((data / "manifest.json").read_text()))
        output = data / "btc/intraday/binance_1m/spot.csv.gz"
        before = output.read_bytes()
        self.write_archive(skip=2)
        with self.assertRaises(ValueError):
            refresh.materialize(*args, root=self.directory)
        self.assertEqual(output.read_bytes(), before)


class PackagedBinanceTests(unittest.TestCase):
    def test_complete_verified_packaged_window(self):
        directory = ROOT / "public/data/btc/intraday/binance_1m"
        manifest = json.loads((directory / "manifest.json").read_text())
        path = directory / "spot.csv.gz"
        self.assertEqual(refresh.sha256(path.read_bytes()), manifest["output"]["sha256"])
        self.assertEqual(manifest["coverage"]["bars"], 129600)
        market = IntradayMarketData(BinanceSpotCandleCsvProvider(directory))
        times = [o.effective_time for o in market.iter_observations()]
        self.assertEqual(len(times), 129600)
        self.assertEqual(times[0], datetime(2026, 6, 6, 0, 1, tzinfo=timezone.utc))
        self.assertEqual(times[-1], datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertEqual(Counter(b-a for a, b in zip(times, times[1:])),
                         {timedelta(minutes=1): 129599})
        self.assertEqual(_select_intraday_spot_session(market, dict.fromkeys(times, 1)),
                         dict.fromkeys(times, 1))


class IndexedRateTests(unittest.TestCase):
    def test_indexed_and_plain_lookups_and_accrual_agree(self):
        plain = {91: [(date(2026, 6, 4), .04), (date(2026, 6, 5), .05),
                      (date(2026, 6, 8), .03)]}
        indexed = IndexedRateSeries(plain)
        start = datetime(2026, 6, 4)
        for minute in range(0, 6*1440, 17):
            stamp = start + timedelta(minutes=minute)
            for query in (stamp, stamp.date()):
                self.assertEqual(asof_rate(indexed, 91, query), asof_rate(plain, 91, query))
        end = datetime(2026, 6, 10)
        self.assertEqual(_rate_change_boundaries(indexed, start, end, [91]),
                         _rate_change_boundaries(plain, start, end, [91]))
        self.assertEqual(accrued_yield_return(indexed, start, end, 91, [91]),
                         accrued_yield_return(plain, start, end, 91, [91]))
        self.assertEqual(asof_rate(indexed, 91, datetime(2026, 6, 5, 23, 59)), .04)
        self.assertEqual(asof_rate(indexed, 91, datetime(2026, 6, 6)), .05)

    def test_timestamped_marks_and_replaced_tenor(self):
        first = datetime(2026, 6, 6, 10)
        plain = {91: [(first, .04), (first + timedelta(minutes=30), .05)]}
        indexed = IndexedRateSeries(plain)
        for minute in range(-1, 40):
            stamp = first + timedelta(minutes=minute)
            self.assertEqual(asof_rate(indexed, 91, stamp), asof_rate(plain, 91, stamp))
        indexed[91] = [(first, .07)]
        self.assertEqual(asof_rate(indexed, 91, first), .07)


if __name__ == "__main__":
    unittest.main()
