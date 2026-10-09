import copy
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("download", Path(__file__).with_name("download_1oz_mbo.py"))
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)


class FakeStore:
    def __init__(self):
        self.saved = []
        self.objects = {}
        self.fail_after_upload = False

    def checkpoint(self, state):
        if self.fail_after_upload and self.objects:
            raise IOError("Checkpoint unavailable")
        self.saved.append(copy.deepcopy(state))

    def verify(self, row):
        assert row["object"] in self.objects

    def recover(self, name, row):
        recovered = self.objects.get(row["attempt_id"])
        if recovered:
            row.update(recovered)
            return True
        return False

    def raw(self, name, row, path):
        row.update(status="done", object=row["attempt_id"], sha256=download.digest(path),
                   size=path.stat().st_size)
        self.objects[row["attempt_id"]] = copy.deepcopy(row)


class DownloadTests(unittest.TestCase):
    def state(self):
        return {"config": copy.deepcopy(download.CONFIG), "streams": {}, "reserved_estimated_usd": 0.0}

    def test_daily_partitions_cover_exact_window_without_gaps(self):
        import pandas as pd
        rows = download.partitions()[1:]
        self.assertEqual(len(rows), 92)
        self.assertEqual(pd.Timestamp(rows[0]["request"]["start"]), pd.Timestamp("2026-07-09", tz="UTC"))
        self.assertEqual(pd.Timestamp(rows[-1]["request"]["end"]), pd.Timestamp("2026-10-09", tz="UTC"))
        self.assertTrue(all(a["request"]["end"] == b["request"]["start"] for a, b in zip(rows, rows[1:])))
        self.assertTrue(all(row["request"]["schema"] == "mbo" for row in rows))

    def test_purchase_requires_durable_reservation_and_completed_resume_skips_vendor(self):
        store, state = FakeStore(), self.state()
        item = download.partitions()[1]
        calls = []
        def stream(**request):
            self.assertEqual(store.saved[-1]["streams"][item["name"]]["status"], "inflight")
            self.assertAlmostEqual(store.saved[-1]["reserved_estimated_usd"], 0.01)
            calls.append(request)
            Path(request["path"]).write_bytes(b"valid DBN")
        client = SimpleNamespace(timeseries=SimpleNamespace(get_range=stream))
        with tempfile.TemporaryDirectory() as work:
            download.acquire(item, 0.01, client, store, state, Path(work), lambda *a: None)
            download.acquire(item, 0.01, client, store, state, Path(work), lambda *a: None)
        self.assertEqual(len(calls), 1)

    def test_raw_upload_survives_lost_completion_checkpoint_without_repurchase(self):
        store, state = FakeStore(), self.state()
        item = download.partitions()[1]
        calls = []
        def stream(**request):
            calls.append(request)
            Path(request["path"]).write_bytes(b"valid DBN")
        client = SimpleNamespace(timeseries=SimpleNamespace(get_range=stream))
        store.fail_after_upload = True
        with tempfile.TemporaryDirectory() as work:
            with self.assertRaises(IOError):
                download.acquire(item, 0.01, client, store, state, Path(work), lambda *a: None)
            durable = copy.deepcopy(store.saved[-1])
            store.fail_after_upload = False
            download.acquire(item, 0.01, client, store, durable, Path(work), lambda *a: None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(durable["streams"][item["name"]]["status"], "done")

    def test_budget_rejection_precedes_vendor_call(self):
        state, store = self.state(), FakeStore()
        state["reserved_estimated_usd"] = 0.249
        def forbidden(**request):
            self.fail("Vendor must not be called above the cap")
        with tempfile.TemporaryDirectory() as work, self.assertRaises(ValueError):
            download.acquire(download.partitions()[1], 0.002,
                SimpleNamespace(timeseries=SimpleNamespace(get_range=forbidden)),
                store, state, Path(work), lambda *a: None)
        self.assertEqual(store.saved, [])

    def test_actual_expiries_and_three_month_cutoff(self):
        import pandas as pd
        rows = []
        for symbol in download.SYMBOLS:
            month = pd.Timestamp(year=2020 + int(symbol[-1]),
                month="FGHJKMNQUVXZ".index(symbol[-2]) + 1, day=1, tz="UTC")
            rows.append({"raw_symbol": symbol, "expiration": month - pd.Timedelta(days=3),
                         "instrument_class": "F"})
        frame = pd.DataFrame(rows)
        self.assertEqual(set(download.validate_expiries(frame)), set(download.SYMBOLS))
        frame.loc[0, "expiration"] = pd.Timestamp("2027-01-08", tz="UTC")
        with self.assertRaises(ValueError):
            download.validate_expiries(frame)

    def test_request_cannot_expand_contracts_or_raise_budget(self):
        request = {"schema_version": 1, "request_id": "test", "action": "download", "study": download.STUDY}
        download.validate_request(request)
        for field in ("symbols", "max_cost", "url"):
            with self.assertRaises(ValueError):
                download.validate_request({**request, field: "override"})


if __name__ == "__main__":
    unittest.main()
