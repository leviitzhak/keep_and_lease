import io
import importlib.util
import runpy
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

try:
    from google.api_core.exceptions import PreconditionFailed
    from google.cloud import storage
except ImportError:
    PreconditionFailed = None
from tests import test_trade_data_store as fixtures


@unittest.skipUnless(PreconditionFailed and importlib.util.find_spec("pyarrow"),
                     "Optional requirements-trade-data.txt not installed")
class UploadTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.TradeDataStoreTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.raw, self.out = fixture.raw, fixture.converted()[0]
        self.objects, self.writes = {}, []
        outer = self

        class Blob:
            def __init__(self, name):
                self.name = name

            def upload_from_filename(self, path, **kwargs):
                outer.assertEqual(kwargs, {"if_generation_match": 0, "checksum": "crc32c"})
                if self.name in outer.objects:
                    raise PreconditionFailed("exists")
                outer.objects[self.name] = Path(path).read_bytes()
                outer.writes.append(self.name)

            def reload(self):
                pass

            def open(self, *args, **kwargs):
                return io.BytesIO(outer.objects[self.name])

        class Bucket:
            def blob(self, name, **kwargs):
                return Blob(name)

        self.bucket = Bucket()
        self.main = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/upload-btc-trade-parquet.py"))["main"]

    def invoke(self):
        with patch("sys.argv", ["upload", "--data", str(self.raw), "--parquet", str(self.out), "--execute"]), \
                patch("google.cloud.storage.Client") as client, redirect_stdout(io.StringIO()):
            client.return_value.bucket.return_value = self.bucket
            self.main()

    def test_create_only_manifest_last_and_idempotent_retry(self):
        self.invoke()
        self.assertTrue(self.writes[-1].startswith("btc/trades/v1/"))
        self.assertTrue(self.writes[-1].endswith("/manifest.json"))
        count = len(self.writes)
        self.invoke()
        self.assertEqual(len(self.writes), count)
        self.assertTrue(any(key.startswith("btc/raw/sha256/") for key in self.objects))

    def test_conflicting_object_stops_publication(self):
        self.invoke()
        manifest = self.writes[-1]
        del self.objects[manifest]
        self.objects[self.writes[0]] = b"wrong bytes"
        with self.assertRaisesRegex(ValueError, "Existing cloud object differs"):
            self.invoke()
        self.assertNotIn(manifest, self.objects)


if __name__ == "__main__":
    unittest.main()
