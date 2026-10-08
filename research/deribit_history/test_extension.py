import gzip,json,tempfile,unittest
from pathlib import Path
from download_extension import ACTION,JOBS,audit,stamp,validate_request

class ExtensionTests(unittest.TestCase):
    def test_only_fixed_request(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'request.json';valid={'schema_version':1,'action':ACTION,'sequence':1}
            p.write_text(json.dumps(valid));self.assertEqual(validate_request(p),valid)
            for bad in [{**valid,'bucket':'other'}, {**valid,'action':'arbitrary'}, {**valid,'sequence':True}]:
                p.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):validate_request(p)
    def test_exact_windows(self):
        self.assertEqual((stamp(JOBS['earlier-sep26'][2])-stamp(JOBS['earlier-sep26'][1]))/86400000,92)
        self.assertEqual((stamp(JOBS['missing-mar27'][2])-stamp(JOBS['missing-mar27'][1]))/86400000,90)
        self.assertEqual(JOBS['earlier-sep26'][1:],JOBS['earlier-dec26'][1:])
    def test_audit_flags_and_duplicate_rejection(self):
        lo=stamp('2026-03-06');r={'instrument_name':'BTC-25SEP26','timestamp':lo+1000,'trade_seq':1,'trade_id':'x','price':70000,'index_price':69000,'amount':100,'contracts':10}
        s={**r,'trade_seq':2,'trade_id':'y','block_trade_id':'block'}
        meta={'rows':2,'discrepancy':{'counts':{},'max_reversal_ms':0}}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'raw.gz'
            with gzip.open(p,'wt') as f:f.write(json.dumps(r)+'\n'+json.dumps(s)+'\n')
            a=audit(p,'BTC-25SEP26',lo,lo+86400000,meta)
            self.assertEqual((a['raw_trades'],a['ordinary_trades'],a['ordinary_usd_face']),(2,1,100))
            with gzip.open(p,'wt') as f:f.write(json.dumps(r)+'\n'+json.dumps(r)+'\n')
            with self.assertRaises(ValueError):audit(p,'BTC-25SEP26',lo,lo+86400000,meta)

if __name__=='__main__':unittest.main()
