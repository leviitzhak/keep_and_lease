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

    def test_two_day_range_prunes_partitions_and_preserves_equal_time_order(self):
        import hashlib
        from datetime import datetime, timedelta
        root = self.root / "range"
        first = root / "days/2026-06-25"
        convert(self.raw, first, batch_rows=1)
        with zipfile.ZipFile(self.raw / "spot.zip", "w") as archive:
            archive.writestr("spot.csv", "4,103,0.1,10.3,1782432000000001,false,true\n")
        future = dict(timestamp=1782432000001, trade_seq=3, trade_id="3", price=104,
                      amount=10, direction="buy")
        with gzip.open(self.raw / "future.jsonl.gz", "wt") as stream:
            stream.write(json.dumps(future)+"\n")
        source = json.loads((self.raw / "manifest.json").read_text())
        source.update(start="2026-06-26T00:00:00+00:00", end="2026-06-27T00:00:00+00:00")
        source["spot"].update(rows=1, sha256=sha256(self.raw / "spot.zip"))
        source["futures"]["BTC-test"].update(rows=1, sha256=sha256(self.raw / "future.jsonl.gz"))
        (self.raw / "manifest.json").write_text(json.dumps(source))
        second = root / "days/2026-06-26"
        convert(self.raw, second, batch_rows=1)
        children = [ParquetTradeStore(first), ParquetTradeStore(second)]
        manifest = dict(schema_version=1, partitions=[], source_manifest=dict(
            start=children[0].source_manifest["start"], end=children[1].source_manifest["end"], futures={}),
            daily_datasets=[dict(start=c.source_manifest["start"], end=c.source_manifest["end"],
                                manifest_sha256=hashlib.sha256(c.manifest_bytes).hexdigest(),
                                local_path="days/"+c.source_manifest["start"][:10]) for c in children])
        (root / "manifest.json").write_text(json.dumps(manifest))
        store = ParquetTradeStore(root)
        self.assertEqual(list(store.trades()), [t for c in children for t in c.trades()])
        selected = ParquetTradeStore(root)
        self.assertEqual(list(selected.trades(start_us=1782432000000000, symbols={"SPOT"})),
                         list(children[1].trades(symbols={"SPOT"})))
        self.assertEqual(len(selected.accessed_partitions), 1)
        self.assertIn("market=spot", selected.accessed_partitions[0]["path"])
        # Re-reading warmup uses the same verified partition, not a second checksum scan.
        list(selected.trades(start_us=1782432000000000, symbols={"SPOT"}))
        self.assertEqual(len(selected.accessed_partitions), 1)


if __name__ == "__main__":
    unittest.main()

    def test_bounded_remote_cache_preserves_events_and_limits_range_requests(self):
        import io
        from trade_data_store import BlockCachedReader, partition_trades
        class Remote(io.BytesIO):
            def __init__(self,data):super().__init__(data);self.requests=0
            def size(self):return len(self.getbuffer())
            def read(self,n=-1):self.requests+=1;return super().read(n)
        out,store=self.converted()
        for part in store.manifest['partitions']:
            path=out/part['path']; remote=Remote(path.read_bytes())
            with BlockCachedReader(remote) as cached:
                expected=list(partition_trades(path))
                actual=list(partition_trades(cached))
                self.assertEqual(actual,expected)
                self.assertLessEqual(remote.requests,2)
        remote=Remote(bytes(range(256))*64)
        with BlockCachedReader(remote,block_size=1024,max_blocks=2) as cached:
            for offset in [0,1200,2400,3600,0,16380,17000]:
                cached.seek(offset)
                self.assertEqual(cached.read(100),remote.getvalue()[offset:offset+100])
                self.assertLessEqual(sum(map(len,cached.blocks.values())),2048)
            cached.seek(-5,2)
            self.assertEqual(cached.read(),remote.getvalue()[-5:])
            with self.assertRaises(ValueError):cached.seek(-1)
        self.assertFalse(remote.closed)
