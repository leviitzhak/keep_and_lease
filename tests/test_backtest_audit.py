import gzip
import hashlib
import json
import time
import io
import zipfile
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backtest_audit import AuditCollection, MemoryAuditStore, load_manifest, read_chunk, project_row, archive_chunks
from server.app import create_app
from server.cloud import GcsResultStore
from tests.test_cloud_jobs import FakeStorageClient, FakeRepository, FakeEngine, FakeResultStore
from server.worker import WorkerRunner
from server.job_models import Job
from tests.test_observed_execution import ObservedExecutionTests
import silver_strategy_gui as gui


class AuditEngine(FakeEngine):
    loaded = True
    def capabilities(self):
        return {}
    def run_backtest_with_audit(self, parameters, audit, progress=None):
        writer=audit.writer("btc")
        writer.emit({"date":"2026-06-01T00:01:00", "exit_date":"2026-06-01T00:02:00",
                     "starting_nav":1, "ending_nav":1.01, "audit_value":parameters})
        if parameters.get("fail"):
            writer.flush()
            raise ValueError("failed after partial upload")
        return {"audit":audit.finish()}


class BacktestAuditTests(unittest.TestCase):
    def test_source_identity_includes_intraday_bytes_and_is_layout_independent(self):
        from market_data_store import source_manifest_hash
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            checkout=root/"checkout";deployed=root/"deployed"
            left=checkout/"public/data/btc/intraday/config.json"
            right=deployed/"data/btc/intraday/config.json"
            for path in (left,right):
                path.parent.mkdir(parents=True);path.write_text('{"spot":"binance"}')
            first=source_manifest_hash(checkout)
            self.assertEqual(first,source_manifest_hash(deployed))
            (deployed/"data/market.sqlite3").write_bytes(b"generated cache")
            self.assertEqual(first,source_manifest_hash(deployed))
            right.write_text('{"spot":"kraken"}')
            self.assertNotEqual(first,source_manifest_hash(deployed))

    def test_full_engine_rows_reassemble_exactly_across_chunks(self):
        fixture=ObservedExecutionTests()
        payload={"min_days":1,"execution_interval_seconds":60,
                 "enable_short_book":"false", "futures_contract_type":"regular",
                 "execution_model":"observed", "commodity_parameters":{"btc":{"futures_contract_type":"regular"}}}
        expected=gui.sleeve_result(payload,fixture.market(),"btc")
        store=MemoryAuditStore();collection=AuditCollection(store)
        # Small test ceiling forces a boundary after almost every engine row.
        with patch("backtest_audit.MAX_CHUNK_BYTES",20000):
            actual=gui.sleeve_result(payload,fixture.market(),"btc",collection)
            manifest=collection.finish()
        entries=manifest["datasets"]["btc"]["chunks"]
        self.assertGreater(len(entries),1)
        rows=[row for entry in entries for row in read_chunk(store,entry)]
        self.assertEqual([project_row(r,"btc","spreadsheet") for r in rows],expected["spreadsheet_rows"])
        self.assertEqual([p for r in rows for p in project_row(r,"btc","rate_change")],expected["rate_change_attribution_points"])
        self.assertEqual(actual["summary"],expected["summary"])
        self.assertEqual(actual["selection_comparison"],expected["selection_comparison"])
        for left,right in zip(entries,entries[1:]):
            self.assertEqual(left["closing_nav"],right["opening_nav"])
            self.assertEqual(left["end"],right["start"])
        self.assertEqual(load_manifest(store),manifest)
        self.assertEqual(manifest["datasets"]["btc"]["rows"],len(rows))
        with zipfile.ZipFile(io.BytesIO(b"".join(archive_chunks(store,manifest)))) as archive:
            self.assertEqual(json.loads(archive.read("manifest.json")),manifest)
            for entry in entries:
                self.assertEqual(archive.read(entry["object"]),store.objects[entry["object"]])
        with self.assertRaisesRegex(ValueError,"immutable"):
            collection.finish()
        entry=entries[0]
        store.objects[entry["object"]]+=b"corruption"
        with self.assertRaisesRegex(ValueError,"checksum"):
            list(read_chunk(store,entry))

    def test_cancellation_prevents_manifest_publication(self):
        store=MemoryAuditStore();collection=AuditCollection(store)
        collection.writer("btc").emit({"date":"2026-06-01", "exit_date":"2026-06-02"})
        def cancelled():
            raise RuntimeError("cancelled")
        collection.check_cancelled=cancelled
        with self.assertRaisesRegex(RuntimeError,"cancelled"):
            collection.finish()
        self.assertNotIn("manifest.json",store.objects)

    def test_owner_access_partial_jobs_projections_and_download(self):
        client=TestClient(create_app(AuditEngine()))
        owner={"x-goog-authenticated-user-id":"accounts.google.com:owner"}
        other={"x-goog-authenticated-user-id":"accounts.google.com:other"}
        for fail in (False,True):
            job=client.post("/api/v1/backtests",headers=owner,json={"parameters":{"fail":fail}}).json()
            for _ in range(100):
                state=client.get(job["status_url"],headers=owner).json()
                if state["status"] in ("completed","failed"):break
                time.sleep(.01)
            base=job["status_url"]
            for suffix in ("/audit","/audit/btc/0","/audit-download/btc","/audit-download"):
                self.assertEqual(client.get(base+suffix,headers=other).status_code,404)
                self.assertEqual(client.get(base+suffix,headers=owner).status_code,409 if fail else 200)
            if fail:continue
            chunk=client.get(base+"/audit/btc/0",headers=owner).json()
            archive=client.get(base+"/audit-download/btc",headers=owner)
            self.assertEqual(json.loads(gzip.decompress(archive.content)),chunk["rows"][0])
            self.assertEqual(client.get(base+"/audit/btc/-1",headers=owner).status_code,404)
            self.assertEqual(client.get(base+"/audit/secret/0",headers=owner).status_code,404)
            self.assertEqual(client.get(base+"/audit/btc/0?section=bad",headers=owner).status_code,400)

    def test_gcs_incremental_json_checksums_limits_and_strict_values(self):
        client=FakeStorageClient();store=GcsResultStore(client,"results")
        value={"unicode":"₿","data":[{"a":i} for i in range(100)]}
        expected=json.dumps(value,allow_nan=False,separators=(",",":")).encode()
        stored=store.write_json("a"*32,value,{},10000)
        blob=client.value.objects["jobs/"+"a"*32+"/result.json.gz"]
        self.assertEqual(gzip.decompress(blob.payload),expected)
        self.assertEqual(stored.result_checksum_sha256,hashlib.sha256(expected).hexdigest())
        self.assertEqual(blob.kwargs["if_generation_match"],0)
        self.assertEqual(blob.kwargs["checksum"],"crc32c")
        with self.assertRaisesRegex(ValueError,"server limit"):
            store.write_json("b"*32,value,{},1)
        with self.assertRaises(ValueError):
            store.write_json("c"*32,{"bad":float("nan")},{},10000)
        self.assertEqual(len(client.value.objects),1)

    def test_worker_uses_audit_path_and_does_not_complete_partial_failure(self):
        class Store(FakeResultStore):
            def __init__(self):
                super().__init__();self.audit=MemoryAuditStore()
            def audit_store(self,*args):
                return self.audit
        for fail in (False,True):
            repository=FakeRepository(Job("a"*32,{"fail":fail},"hash"))
            store=Store()
            code=WorkerRunner(repository,store,AuditEngine()).run("a"*32)
            self.assertEqual(code,1 if fail else 0)
            self.assertEqual("manifest.json" in store.audit.objects,not fail)
            self.assertEqual(repository.completed is not None,not fail)


if __name__ == "__main__":
    unittest.main()
