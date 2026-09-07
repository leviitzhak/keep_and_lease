import gzip
import importlib.util
import json
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

from trade_data_store import ParquetTradeStore, convert, sha256, spot_records, write_partition


@unittest.skipUnless(importlib.util.find_spec("pyarrow"), "Optional requirements-trade-data.txt not installed")
class TradeDataStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        with zipfile.ZipFile(self.raw / "spot.zip", "w") as archive:
            archive.writestr("spot.csv", "1,100.00000001,0.1,10,1782345600000001,false,true\n"
                             "2,101,0.2,20.2,1782345600001000,true,true\n"
                             "3,102,0.3,30.6,1782345601000000,false,true\n")
        rows = [dict(timestamp=1782345600001, trade_seq=i, trade_id=str(i), price=100,
                     amount=10, direction="buy", **({"combo_id": "combo"} if i == 2 else {}))
                for i in (1, 2)]
        with gzip.open(self.raw / "future.jsonl.gz", "wt") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        source = dict(start="2026-06-25T00:00:00+00:00", end="2026-06-26T00:00:00+00:00",
                      spot=dict(path="spot.zip", rows=3, sha256=sha256(self.raw / "spot.zip")),
                      futures={"BTC-test": dict(path="future.jsonl.gz", rows=2,
                                               sha256=sha256(self.raw / "future.jsonl.gz"))})
        (self.raw / "manifest.json").write_text(json.dumps(source))

    def converted(self):
        out = self.root / "normalized"
        convert(self.raw, out, batch_rows=1)
        return out, ParquetTradeStore(out)

    def test_exact_decimal_native_units_flags_and_equal_timestamp_order(self):
        out, store = self.converted()
        events = list(store.trades(batch_rows=1))
        self.assertEqual([(t.us, t.symbol, t.identifier) for t in events], [
            (1782345600000001, "SPOT", "1"), (1782345600001000, "BTC-test", "1"),
            (1782345600001000, "BTC-test", "2"), (1782345600001000, "SPOT", "2"),
            (1782345601000000, "SPOT", "3")])
        self.assertEqual(events[0].price, 100.00000001)
        self.assertEqual(events[1].btc, .1)
        self.assertFalse(events[2].executable)
        import pyarrow.parquet as pq
        spot = next(x for x in store.manifest["partitions"] if "binance" in x["path"])
        value = pq.ParquetFile(out / spot["path"]).read_row_group(0, columns=["price"])[0][0].as_py()
        self.assertEqual(value, Decimal("100.00000001"))

    def test_half_open_time_range_and_symbol_filter_across_row_groups(self):
        _, store = self.converted()
        events = list(store.trades(start_us=1782345600001000, end_us=1782345601000000,
                                   symbols={"SPOT"}, batch_rows=1))
        self.assertEqual([t.identifier for t in events], ["2"])

    def test_rejects_corruption_before_replay(self):
        out, store = self.converted()
        path = out / store.manifest["partitions"][0]["path"]
        with path.open("ab") as stream:
            stream.write(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            list(store.trades())

    def test_refuses_overwrite_and_source_checksum_mismatch(self):
        out, _ = self.converted()
        with self.assertRaisesRegex(ValueError, "immutable"):
            convert(self.raw, out)
        with (self.raw / "spot.zip").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "Source checksum"):
            convert(self.raw, self.root / "other")
        self.assertFalse((self.root / "other" / "manifest.json").exists())

    def test_duplicate_or_missing_sequence_is_not_silently_normalized(self):
        rows = list(spot_records(self.raw / "spot.zip"))
        with self.assertRaisesRegex(ValueError, "sequence gap"):
            write_partition([rows[0], rows[2]], self.root / "gap.parquet", expected_rows=2)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            write_partition([rows[0], rows[0]], self.root / "duplicate.parquet", expected_rows=2)


if __name__ == "__main__":
    unittest.main()
