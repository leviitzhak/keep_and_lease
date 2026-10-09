import unittest
from unittest.mock import patch
import download_full_history as d

def row(n):
    return dict(instrument_name='BTC-25DEC26', trade_seq=n, trade_id=str(n), price=100, amount=10, timestamp=1000+n)

class FullHistoryTest(unittest.TestCase):
    def test_historical_parameter_required(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"result":{"trades":[]}}'
        with patch.object(d.urllib.request,'urlopen',return_value=Response()) as opened, patch.object(d.time,'sleep'):
            d.api('get_last_trades_by_instrument',instrument_name='BTC-25DEC26',count=1)
        self.assertIn('include_old=true',opened.call_args.args[0])
    def test_gap_is_fatal(self):
        with self.assertRaises(ValueError):
            d.checked_rows({'trades':[row(1),row(3)]}, 'BTC-25DEC26', 1, 3)
    def test_reversal_preserved(self):
        rows=[row(1),row(2)]
        rows[1]['timestamp']=900
        self.assertEqual(d.checked_rows({'trades':rows}, 'BTC-25DEC26', 1, 2),rows)
    def test_wrong_instrument(self):
        with self.assertRaises(ValueError):
            d.checked_rows({'trades':[row(1)]}, 'BTC-25SEP26', 1, 1)
    def test_all_chunks_partitioned_once(self):
        p={'instruments':[{'instrument':'BTC-25DEC26','first_available_seq':1,'last_available_seq':23005}]}
        all_tasks=[t for s in range(d.SHARDS) for t in d.tasks(p,s)]
        ranges=sorted((t[1],t[2]) for t in all_tasks)
        self.assertEqual(ranges,[(1,10000),(10001,20000),(20001,23005)])
    def test_resume_skips_api(self):
        with patch.object(d,'verify_receipt',return_value={'rows':2}), patch.object(d,'api') as api:
            out=d.download_chunk(None,{'job_id':'btc-full-20261009-test'},'BTC-25DEC26',1,2,'x')
        self.assertTrue(out[2])
        api.assert_not_called()
    def test_receipt_written_after_objects(self):
        calls=[]
        def save(bucket,key,data):
            calls.append(key)
            return {'key':key,'sha256':d.digest(data),'bytes':len(data)}
        with patch.object(d,'verify_receipt',return_value=None), patch.object(d,'api',return_value={'trades':[row(1),row(2)]}), patch.object(d,'create_bytes',side_effect=save):
            d.download_chunk(None,{'job_id':'btc-full-20261009-test'},'BTC-25DEC26',1,2,'x')
        self.assertEqual(len(calls),4)
        self.assertIn('/receipts/',calls[-1])
    def test_failed_upload_no_receipt(self):
        calls=[]
        def save(bucket,key,data):
            calls.append(key)
            raise OSError('upload interrupted')
        with patch.object(d,'verify_receipt',return_value=None), patch.object(d,'api',return_value={'trades':[row(1)]}), patch.object(d,'create_bytes',side_effect=save):
            with self.assertRaises(OSError):
                d.download_chunk(None,{'job_id':'btc-full-20261009-test'},'BTC-25DEC26',1,1,'x')
        self.assertFalse(any('/receipts/' in k for k in calls))
    def test_corruption_rejected(self):
        obj={'key':'raw','sha256':d.digest(b'good'),'bytes':4}
        receipt={'status':'COMPLETE','instrument':'BTC-25DEC26','first_seq':1,'last_seq':1,'rows':1,'objects':[obj]}
        class Blob:
            def download_as_bytes(self,**kwargs):return b'evil'
        class Bucket:
            def blob(self,key):return Blob()
        with patch.object(d,'get_json',return_value=receipt):
            with self.assertRaises(ValueError):
                d.verify_receipt(Bucket(),'receipt','BTC-25DEC26',1,1)
    def test_shifted_overlap_and_end_extras(self):
        def fetch(method, **params):
            q=params['start_seq']
            return {'trades':[row(n) for n in range(max(1,q-5),max(1,q-5)+20)]}
        with patch.object(d,'api',side_effect=fetch):
            rows=d.collect_chunk('BTC-25DEC26',30,59,[])
        self.assertEqual([r['trade_seq'] for r in rows],list(range(30,60)))
    def test_seek_forward_when_shift_exceeds_page(self):
        def fetch(method,**params):
            q=params['start_seq']
            return {'trades':[row(n) for n in range(max(1,q-50),max(1,q-50)+10)]}
        with patch.object(d,'api',side_effect=fetch):
            rows=d.collect_chunk('BTC-25DEC26',100,119,[])
        self.assertEqual([r['trade_seq'] for r in rows],list(range(100,120)))
    def test_genuine_gap_not_waived(self):
        with patch.object(d,'api',return_value={'trades':[row(1),row(3)]}):
            with self.assertRaisesRegex(ValueError,'Unresolved sequence gap'):
                d.collect_chunk('BTC-25DEC26',1,3,[])
    def test_identical_duplicates_are_deduplicated(self):
        with patch.object(d,'api',return_value={'trades':[row(1),row(1),row(2)]}):
            self.assertEqual(len(d.collect_chunk('BTC-25DEC26',1,2,[])),2)
    def test_conflicting_duplicates_fail(self):
        other=row(1);other['price']=200
        with self.assertRaisesRegex(ValueError,'Conflicting sequence'):
            d.page_rows({'trades':[row(1),other]},'BTC-25DEC26')
    def test_zero_amount_preserved_and_flagged(self):
        r=row(1);r['amount']=0.0
        with patch.object(d,'api',return_value={'trades':[r]}):
            rows=d.collect_chunk('BTC-25DEC26',1,1,[])
        self.assertEqual(rows,[r])
        self.assertEqual(d.numeric_flags(rows[0]),['zero_amount'])
    def test_missing_numeric_preserved_and_flagged(self):
        r=row(1);r['price']=None
        self.assertEqual(d.page_rows({'trades':[r]},'BTC-25DEC26'),[r])
        self.assertEqual(d.numeric_flags(r),['invalid_price'])
    def test_timeout_reduces_actual_request_and_keeps_evidence(self):
        import io
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"result":{"trades":[]}}'
        err=d.urllib.error.HTTPError('https://history.deribit.com',400,'bad',{},io.BytesIO(b'{"error":{"code":13888,"message":"timed_out"}}'))
        evidence=[]
        with patch.object(d.urllib.request,'urlopen',side_effect=[err,Response()]) as opened, patch.object(d.time,'sleep'):
            d.api('get_last_trades_by_instrument',evidence=evidence,instrument_name='BTC-25DEC26',count=1000)
        self.assertIn('count=500',opened.call_args.args[0])
        self.assertEqual(evidence[0]['http_status'],400)
        self.assertEqual(evidence[1]['parameters']['count'],500)
    def test_failure_evidence_written_without_receipt(self):
        writes=[]
        def fetch(method,evidence,**params):
            evidence.append({'parameters':params,'response':{'trades':[row(1),row(3)]}})
            return {'trades':[row(1),row(3)]}
        def save(bucket,key,data):
            writes.append(key);return {'key':key}
        with patch.object(d,'verify_receipt',return_value=None),patch.object(d,'api',side_effect=fetch),patch.object(d,'create_bytes',side_effect=save):
            with self.assertRaisesRegex(ValueError,'Unresolved sequence gap'):
                d.download_chunk(None,{'job_id':'btc-full-20261009-test'},'BTC-25DEC26',1,3,'x')
        self.assertEqual(len(writes),1)
        self.assertIn('/failure-evidence/',writes[0])

class BoundaryPlanTest(unittest.TestCase):
    def test_expired_tail_extended_active_tail_frozen_and_resume(self):
        saved={}
        r={'job_id':'btc-full-20261009-test'}
        original={'instruments':[
            {'instrument':'BTC-29SEP17','metadata':{'expiration_timestamp':1000},'snapshot_at':'2026-10-09T00:00:00+00:00','first_available_seq':1,'last_available_seq':2},
            {'instrument':'BTC-25DEC26','metadata':{'expiration_timestamp':9999999999999},'snapshot_at':'2026-10-09T00:00:00+00:00','first_available_seq':1,'last_available_seq':2}]}
        rows=[dict(row(n),instrument_name='BTC-29SEP17') for n in (2,3)]
        def save(bucket,key,data):
            if key.endswith('.json'):saved[key]=d.json.loads(data)
            return {'key':key,'sha256':d.digest(data),'bytes':len(data)}
        with patch.object(d,'get_json',side_effect=lambda bucket,key:saved.get(key)),patch.object(d,'create_bytes',side_effect=save),patch.object(d,'api',return_value={'trades':rows}) as api:
            result=d.reconcile_plan(None,r,original)
            again=d.reconcile_plan(None,r,original)
        self.assertEqual([x['last_available_seq'] for x in result['instruments']],[3,2])
        self.assertEqual(original['instruments'][0]['last_available_seq'],2)
        self.assertEqual(again,result)
        self.assertEqual(api.call_count,1)

if __name__=='__main__':unittest.main()
