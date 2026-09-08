import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import deribit_trade_ingest as ingest
from trade_ordering import OrderedTradeStore, sorted_raw_futures
from trade_replay import Trade, TapeAccount


def row(seq, ts):
    return dict(trade_seq=seq,trade_id=str(seq),timestamp=ts,price=100.,amount=100.,direction='buy',instrument_name='F')


class IngestionTests(unittest.TestCase):
    def download(self, records, missing_tail=False, mutate=False):
        def api(method, **p):
            if method.endswith('_and_time'):
                selected=[r for r in records if p.get('start_timestamp',-1)<=r['timestamp']<=p['end_timestamp']]
                if missing_tail and 'start_timestamp' in p: selected=[r for r in selected if r['trade_seq']!=5]
                selected=sorted(selected,key=lambda r:r['timestamp'],reverse=p['sorting']=='desc')[:p['count']]
            else:
                selected=[r for r in records if p['start_seq']<=r['trade_seq']<=p['end_seq']]
                if mutate: selected=[{**r,'price':101.} for r in selected]
            return dict(trades=selected,has_more=False)
        with tempfile.TemporaryDirectory() as root, patch.object(ingest,'PAGE',3):
            meta=ingest.download_future(api,'F',dict(expiration_timestamp='2026-06-26T08:00:00Z'),1000,2000,root)
            with gzip.open(Path(root)/meta['path'],'rt') as f: raw=[json.loads(x) for x in f]
            with gzip.open(Path(root)/meta['evidence_files'][1]['path'],'rt') as f: anomalies=[json.loads(x) for x in f]
            return meta,raw,anomalies

    def test_reversal_after_outside_window_does_not_stop_pagination(self):
        records=[row(1,900),row(2,1001),row(3,2001),row(4,1999),row(5,2002),row(6,2003),row(7,2004),row(8,2005)]
        meta,raw,anomalies=self.download(records)
        self.assertEqual([r['trade_seq'] for r in raw],[2,4])
        self.assertEqual(meta['discrepancy']['counts']['timestamp_reversal'],1)
        self.assertEqual(meta['discrepancy']['max_reversal_ms'],2)
        self.assertTrue(all(a['anomaly_id'] and a['status']=='unresolved' for a in anomalies))

    def test_sequence_endpoint_extra_is_preserved_and_reported(self):
        meta,raw,anomalies=self.download([row(i,900+i*100) for i in range(1,9)],True)
        self.assertIn(5,[r['trade_seq'] for r in raw])
        self.assertIn('sequence_endpoint_only',[a['kind'] for a in anomalies])

    def test_gaps_and_conflicting_versions_remain_errors(self):
        with self.assertRaisesRegex(ValueError,'gap'):
            self.download([row(1,900),row(2,1100),row(4,1300),row(5,2100)])
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            self.download([row(1,900),row(2,1100),row(3,1200)],mutate=True)

    def test_disk_sort_retains_values_and_validates_sequence_before_ordering(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'raw.gz'
            with gzip.open(path,'wt') as f:
                for r in [row(1,1002),row(2,1001),row(3,1002)]: f.write(json.dumps(r)+'\n')
            actual=[json.loads(x) for x in sorted_raw_futures(path)]
            self.assertEqual([r['trade_seq'] for r in actual],[2,1,3])
            self.assertEqual(sum(r['amount'] for r in actual),300)


class MemorySource:
    source_manifest=dict(start='2026-06-25',end='2026-06-27',futures={'F':dict(expiry='2026-09-25')})
    check_cancelled=staticmethod(lambda:None)
    def __init__(self, events):self.events=events
    def trades(self,start_us=None,end_us=None,symbols=None,batch_rows=8192):
        return iter(t for t in sorted(self.events,key=lambda t:(t.us,t.symbol,t.sequence or 0))
                    if (start_us is None or t.us>=start_us) and (end_us is None or t.us<end_us)
                    and (symbols is None or t.symbol in symbols))


class OrderingTests(unittest.TestCase):
    def test_sequence_timeline_crosses_midnight_and_selected_window(self):
        midnight=86400_000_000
        events=[Trade(midnight+2,'F',100,1,'buy','1',True,midnight+2,1),
                Trade(midnight-2,'F',101,1,'buy','2',True,midnight-2,2),
                Trade(midnight+3,'SPOT',100,1,'buy','s',True,midnight+3,1)]
        store=OrderedTradeStore(MemorySource(events),'sequence')
        try:
            self.assertEqual(list(store.trades(end_us=midnight)),[])
            actual=list(store.trades(start_us=midnight))
            self.assertEqual([e.identifier for e in actual],['1','2','s'])
            self.assertEqual([e.us for e in actual],[midnight+2,midnight+2,midnight+3])
            self.assertEqual(actual[1].reported_us,midnight-2)
            self.assertEqual(store.window_report(midnight,midnight+10)['max_delay_us'],4)
            comparison=OrderedTradeStore(MemorySource(events),'timestamp')
            self.assertEqual(next(comparison.trades()).identifier,'2')
        finally:store.close()

    def test_duplicate_sequence_is_not_silently_deduplicated(self):
        import sqlite3
        events=[Trade(1,'F',100,1,'buy','1',True,1,1),Trade(2,'F',101,1,'buy','2',True,2,1)]
        store=OrderedTradeStore(MemorySource(events),'sequence')
        try:
            with self.assertRaises(sqlite3.IntegrityError):list(store.trades())
        finally:store.close()

    def test_same_effective_timestamp_cannot_fill_a_new_order(self):
        account=TapeAccount(1000,1,0)
        account.initialize_spot(Trade(1,'SPOT',100,1,'buy','s'))
        first=Trade(10,'F',100,1,'buy','1',True,10,1)
        account.on_trade(first)
        account.submit_targets(10,{'SPOT':0,'F':1})
        account.on_trade(Trade(10,'F',101,1,'buy','2',True,9,2))
        self.assertEqual(account.fill_count,0)
        account.on_trade(Trade(11,'SPOT',100,10,'sell','s2'))
        account.on_trade(Trade(12,'F',101,1,'buy','3',True,12,3))
        self.assertGreater(account.fill_count,0)


class ReceiptRecoveryTests(unittest.TestCase):
    def test_restores_exact_receipt_and_rejects_wrong_run(self):
        import io,runpy,zipfile
        module=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/restore-btc-receipts.py'))
        data=io.BytesIO();digest='a'*64
        receipt=json.dumps(dict(uri='gs://keep-and-lease-market-data/btc/trades/v1/'+digest,manifest_sha256=digest)).encode()
        with zipfile.ZipFile(data,'w') as z:z.writestr('receipts/2026-06-06.json',receipt)
        run=dict(head_branch='agent/cloud-autonomous-access',path='.github/workflows/btc-trade-range.yml',status='completed')
        artifacts=dict(total_count=1,artifacts=[dict(name='btc-day-2026-06-06',expired=False,size_in_bytes=len(data.getvalue()),id=1)])
        responses=[json.dumps(run).encode(),json.dumps(artifacts).encode(),data.getvalue()]
        with tempfile.TemporaryDirectory() as root,patch.dict(module['restore'].__globals__,api=lambda _:responses.pop(0)):
            self.assertEqual(module['restore']([123],root),['2026-06-06'])
            self.assertEqual((Path(root)/'receipts/2026-06-06.json').read_bytes(),receipt)
        run['head_branch']='master'
        with tempfile.TemporaryDirectory() as root,patch.dict(module['restore'].__globals__,api=lambda _:json.dumps(run).encode()):
            with self.assertRaisesRegex(ValueError,'bounded operator'):module['restore']([123],root)

    def test_recovery_with_backwards_timestamps_keeps_identical_audit(self):
        from tests.test_trade_range_recovery import RecoveryTests
        class ReversedRecovery(RecoveryTests):
            def scenario(self):
                from dataclasses import replace
                p,store,coverage=super().scenario()
                # Input sequence identity is preserved by FakeStore before sorting.
                store.events[23]=replace(store.events[23],us=store.events[21].us-50_000)
                return p,store,coverage
        ReversedRecovery().test_day_boundary_recovery_preserves_every_financial_and_audit_row()
