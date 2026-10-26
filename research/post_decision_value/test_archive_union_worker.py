import gzip,json,tempfile,unittest
from pathlib import Path
from research.post_decision_value.archive_union_worker import merge,encode,digest,PREFIX

class ArchiveUnionTests(unittest.TestCase):
    def fixture(self):
        objects={}
        def put(k,b):objects[k]=b;return dict(key=k,sha256=digest(b),bytes=len(b))
        def row(i):return dict(instrument_name='BTC-X',trade_id=str(i),trade_seq=i,timestamp=100+i,price=100.,amount=10.,index_price=99.,direction='buy')
        def raw(rs):return gzip.compress(b''.join(encode(r) for r in rs),mtime=0)
        keys=[]
        for lo,hi in ((1,2),(3,3)):
            obj=put('btc/raw/'+str(lo)+'/trades.jsonl.gz',raw([row(i) for i in range(lo,hi+1)]))
            key=f'{PREFIX}/receipts/BTC-X/{lo:012d}-{hi:012d}.json';keys.append(key)
            put(key,encode(dict(status='COMPLETE',instrument='BTC-X',first_seq=lo,last_seq=hi,rows=hi-lo+1,objects=[obj])))
        metadata=[]
        metadata.append(put(PREFIX+'/manifest.json',encode(dict(status='COMPLETE_AVAILABLE_HISTORY',prefix_unavailable=[]))))
        metadata.append(put(PREFIX+'/plan-reconciled-v2.json',encode(dict(job_id='fixture',chunk_size=2,instruments=[dict(instrument='BTC-X',first_available_seq=1,last_available_seq=3)]))))
        metadata.append(put(PREFIX+'/completed/shard-0.json',encode(dict(status='COMPLETE',failures=[],pending=False,receipt_keys=keys))))
        day=put('btc/raw/daily',raw([row(2)]));day.update(rows=1,symbol='BTC-X',first_seq=2,last_seq=2)
        inputs=dict(archive_job='fixture',metadata=metadata,daily_objects=[day],expected_daily_rows=1)
        def get(key,sha,size):
            b=objects[key]
            if sha is not None and digest(b)!=sha:raise ValueError('Source hash mismatch')
            if size is not None and len(b)!=size:raise ValueError('Source size mismatch')
            return b
        return inputs,objects,get
    def test_subset_union_references_archive_once(self):
        inputs,objects,get=self.fixture()
        with tempfile.TemporaryDirectory() as d:
            m=merge(inputs,get,d)
            self.assertEqual(m['status'],'COMPLETE_LOGICAL_UNION');self.assertEqual(m['native_rows'],3)
            self.assertEqual(m['reconciliation']['matched_identical'],1);self.assertEqual(m['reconciliation']['overlay_rows'],0)
            self.assertEqual(len(m['canonical_receipt_keys']),2);self.assertEqual(len(m['overlap_receipts']),1)
            self.assertEqual(m['overlap_receipts'][0]['receipt_sha256'],digest(objects[m['overlap_receipts'][0]['receipt_key']]))
            self.assertFalse((Path(d)/'overlap.sqlite').exists())
    def test_conflicting_same_trade_fails_without_manifest(self):
        inputs,objects,get=self.fixture();s=inputs['daily_objects'][0];r=json.loads(gzip.decompress(objects[s['key']]))
        r['price']=101.;b=gzip.compress(encode(r));objects[s['key']]=b;s.update(sha256=digest(b),bytes=len(b))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'Conflicting native overlap'):merge(inputs,get,d)
            self.assertFalse((Path(d)/'manifest.json').exists())
    def test_changed_trade_id_does_not_disappear(self):
        inputs,objects,get=self.fixture();s=inputs['daily_objects'][0];r=json.loads(gzip.decompress(objects[s['key']]))
        r['trade_id']='other';b=gzip.compress(encode(r));objects[s['key']]=b;s.update(sha256=digest(b),bytes=len(b))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'absent from canonical'):merge(inputs,get,d)
    def test_bad_source_hash_fails(self):
        inputs,objects,get=self.fixture();inputs['daily_objects'][0]['sha256']='bad'
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'hash mismatch'):merge(inputs,get,d)
    def test_missing_frozen_receipt_fails(self):
        inputs,objects,get=self.fixture();s=inputs['metadata'][-1];r=json.loads(objects[s['key']]);r['receipt_keys'].pop()
        b=encode(r);objects[s['key']]=b;s.update(sha256=digest(b),bytes=len(b))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'coverage mismatch'):merge(inputs,get,d)

if __name__=='__main__':unittest.main()
