import hashlib
import io
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch
import zipfile

from tests.test_trade_range_recovery import RangeManifestTests
import btc_trade_backtest as replay

ROOT = Path(__file__).resolve().parents[1]


class BenchmarkChainTests(unittest.TestCase):
    def resolve(self, run, manifest=None):
        module = runpy.run_path(str(ROOT/'scripts/await-btc-trade-range.py'))
        value = manifest or RangeManifestTests().manifest()
        raw = json.dumps(value).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive: archive.writestr('manifest.json', raw)
        replies = [json.dumps(run).encode(), json.dumps({'artifacts':[
            {'id':1,'name':'btc-90day-manifest','expired':False,'size_in_bytes':len(output.getvalue())}]}).encode(), output.getvalue()]
        with patch.dict(module['resolve'].__globals__, api=lambda _: replies.pop(0)):
            actual = module['resolve'](123)
        return actual, hashlib.sha256(raw).hexdigest()

    def test_only_successful_ingestion_resolves_exact_manifest(self):
        run=dict(head_branch='agent/cloud-autonomous-access', path='.github/workflows/btc-trade-range.yml',status='completed', conclusion='success')
        self.assertEqual(*self.resolve(run))
        run['conclusion']='failure'
        with self.assertRaisesRegex(ValueError,'did not pass'): self.resolve(run)
        run['head_branch']='master'
        with self.assertRaisesRegex(ValueError,'Unexpected'): self.resolve(run)

    def test_wrong_range_does_not_start_benchmark(self):
        run=dict(head_branch='agent/cloud-autonomous-access', path='.github/workflows/btc-trade-range.yml',status='completed', conclusion='success')
        value=RangeManifestTests().manifest(1)
        with self.assertRaisesRegex(ValueError,'approved period'): self.resolve(run,value)

    def test_server_catalog_normalizes_timezone_bounds_for_gui(self):
        catalog=dict(id='range',start='2026-06-06T03:00:00+03:00',end='2026-09-04T00:00:00Z',
                     manifest_sha256='a'*64,uri='gs://keep-and-lease-market-data/btc/trades/ranges/'+'a'*64,
                     maximum_decisions=16_000_000)
        with patch.dict('os.environ',KEEP_AND_LEASE_TRADE_CATALOG=json.dumps(catalog)):
            actual=replay.catalog()
        self.assertEqual(actual['start'],'2026-06-06T00:00:00.000000')
        self.assertEqual(actual['end'],'2026-09-04T00:00:00.000000')
