import hashlib
import io
import json
import unittest
import zipfile
from datetime import datetime
from unittest.mock import patch
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
from backtest_audit import AuditCollection, MemoryAuditStore
from replay_checkpoints import encode
from server.app import create_app
from server.benchmarks import BenchmarkService, MANIFEST, parameters
from server.replay_exports import replay_workbook, selected_rows, workbook
from tests.test_server_api import FakeEngine


def fixture():
    store = MemoryAuditStore()
    collection = AuditCollection(store, provenance={'trade_data': {'manifest_sha256': MANIFEST}})
    writer = collection.writer('btc_trade_valuations')
    writer.row_limit = 1
    for date, nav in [('2026-09-03T22:00:00.000000', 100000), ('2026-09-03T23:30:00.000000', 110000), ('2026-09-04T00:00:00.000000', 120000)]:
        us = int((datetime.fromisoformat(date)-datetime(1970,1,1)).total_seconds()*1e6)
        writer.emit(dict(date=date, us=us, nav_usd=nav, cash_usd=50000, units={'SPOT': 1}, targets={'SPOT': 1},
                         starting_nav=1, ending_nav=nav/100000, direct_nav=1.1, futures_notional_usd=0,
                         fees_usd=0, return_fraction=nav/100000-1, reconstruction_error_usd=0,
                         mark_us={'SPOT': us}, mark_ids={'SPOT': '12345678901234567890'}))
    collection.writer('btc_trade_events').emit(dict(date='2026-09-03T23:45:00.000000', kind='fill', symbol='SPOT', price=65000, signed_btc=.1))
    manifest = collection.finish()
    p = parameters('sequence')
    digest = hashlib.sha256(json.dumps({k:v for k,v in p.items() if k!='trade_ordering'},sort_keys=True).encode()).hexdigest()
    report = dict(days=90, ordering='sequence', interval_seconds=.5, manifest_sha256=MANIFEST,
                  strategy_parameters_sha256=digest, fingerprint='unchanged-engine',
                  summary=dict(start='2026-06-06T00:00:00.000000', end='2026-09-04T00:00:00.000000', ending_nav=1.2, observations=3),
                  replay=dict(plot_sample_every=1, capital_usd=100000, assumptions=['Zero-cost research baseline']))
    tick = int((datetime(2026,9,3,23)-datetime(1970,1,1)).total_seconds()*1e6)
    checkpoint = dict(identity='unchanged-engine', source_cursor_exclusive_us=tick,
                      state={'series': [['2026-06-06T00:00:00.000000',1,1,0,100000,0,0,0]]})
    class Service(BenchmarkService):
        def __init__(self): pass
        def read(self, name, limit=0):
            return json.dumps(report).encode() if name.endswith('benchmark-report.json') else encode(checkpoint)
        def audit_store(self, policy): return store
    return Service(), store, manifest, report, checkpoint


class BenchmarkGuiTests(unittest.TestCase):
    def test_chart_recovery_reads_only_tail_and_reconciles_final_nav(self):
        service, store, manifest, _, _ = fixture()
        original = store.get
        seen = []
        store.get = lambda name: (seen.append(name), original(name))[1]
        result, _ = service.load('sequence')
        self.assertEqual([r[1] for r in result['series']], [1,1.1,1.2])
        self.assertEqual(result['series'][-1][4], 70000)
        self.assertNotIn(manifest['datasets']['btc_trade_valuations']['chunks'][0]['object'], seen)
        with self.assertRaises(KeyError): service.load('unpublished')

    def test_report_or_checkpoint_mismatch_is_rejected(self):
        service, _, _, _, checkpoint = fixture()
        checkpoint['identity'] = 'different-engine'
        with self.assertRaisesRegex(ValueError, 'checkpoint differs'): service.load('sequence')

    def test_period_workbook_has_exact_rows_formulas_and_saved_parameters(self):
        service, store, manifest, _, _ = fixture()
        result, _ = service.load('sequence')
        data = b''.join(replay_workbook(store,manifest,result,'2026-09-03T23:00:00.000000','2026-09-04T00:00:00.000000'))
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIsNone(z.testzip())
            ns = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            valuations = ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
            self.assertEqual(len(valuations.findall('m:sheetData/m:row',ns)),3)
            self.assertEqual(valuations.find(".//m:c[@r='D2']/m:f",ns).text,'B2-C2')
            self.assertEqual(float(valuations.find(".//m:c[@r='D2']/m:v",ns).text),60000)
            self.assertIn(b'12345678901234567890',z.read('xl/worksheets/sheet2.xml'))
            self.assertIn(b'65000',z.read('xl/worksheets/sheet3.xml'))
            self.assertIn(b'trade_initial_capital_usd',z.read('xl/worksheets/sheet4.xml'))
            for n in z.namelist(): ET.fromstring(z.read(n))

    def test_split_sheets_keep_all_rows_and_safe_text(self):
        with patch('server.replay_exports.MAX_SHEET_ROWS',3):
            data=b''.join(workbook([('Data',['Value'],[[v] for v in ['=1+1',2,3,4,5]])]))
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('xl/worksheets/sheet3.xml',z.namelist())
            self.assertIn(b't="inlineStr"',z.read('xl/worksheets/sheet1.xml'))
            self.assertIn(b'=1+1',z.read('xl/worksheets/sheet1.xml'))
            self.assertIn(b'<v>5</v>',z.read('xl/worksheets/sheet3.xml'))

    def test_export_bounds_and_chunk_integrity(self):
        _, store, manifest, _, _ = fixture()
        entries=manifest['datasets']['btc_trade_valuations']['chunks']
        store.objects[entries[0]['object']]=b'corrupt outside selected period'
        self.assertEqual(len(list(selected_rows(store,manifest,'btc_trade_valuations','2026-09-03T23:00:00.000000','2026-09-04T00:00:00.000000'))),2)
        store.objects[entries[1]['object']]=b'corrupt selected period'
        with self.assertRaisesRegex(ValueError,'checksum'):
            list(selected_rows(store,manifest,'btc_trade_valuations','2026-09-03T23:00:00.000000','2026-09-04T00:00:00.000000'))

    def test_routes_expose_only_published_fixtures_and_validate_dates(self):
        service, _, _, _, _ = fixture()
        client=TestClient(create_app(FakeEngine(),benchmark_service=service))
        self.assertEqual(len(client.get('/api/v1/benchmarks').json()['jobs']),2)
        self.assertEqual(client.get('/api/v1/benchmarks/sequence/result').status_code,200)
        self.assertEqual(client.get('/api/v1/benchmarks/private-job/result').status_code,404)
        self.assertEqual(client.get('/api/v1/backtests/sequence/result').status_code,404)
        base='/api/v1/benchmarks/sequence/spreadsheet'
        self.assertEqual(client.get(base,params={'start':'bad','end':'bad'}).status_code,400)
        self.assertEqual(client.get(base,params={'start':'2026-06-05','end':'2026-06-06'}).status_code,400)
        response=client.get(base,params={'start':'2026-09-03T23:00:00Z','end':'2026-09-04T00:00:00Z'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.content[:2],b'PK')


if __name__=='__main__': unittest.main()
