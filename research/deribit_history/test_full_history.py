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
        self.assertEqual(len(calls),3)
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
if __name__=='__main__':unittest.main()
