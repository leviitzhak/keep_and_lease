import gzip,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from research.post_decision_value import download_expiry_inputs as d

XML=b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"><entry><content><m:properties><d:INDEX_DATE>2025-01-02T00:00:00</d:INDEX_DATE><d:ROUND_B1_CLOSE_13WK_2>4.5</d:ROUND_B1_CLOSE_13WK_2><d:CUSIP_13WK>123456789</d:CUSIP_13WK><d:MATURITY_DATE_13WK>2025-04-03T00:00:00</d:MATURITY_DATE_13WK></m:properties></content></entry></feed>'''

class ExpiryInputTests(unittest.TestCase):
    def test_delivery_conflicts_and_nonfinite_rejected(self):
        a={'data':[{'date':'2025-01-02','delivery_price':100.}]}
        self.assertEqual(len(d.delivery_rows([a,a])),1)
        for x in (101.,float('nan')):
            with self.assertRaises(ValueError):d.delivery_rows([a,{'data':[{'date':'2025-01-02','delivery_price':x}]}])

    def test_treasury_current_and_old_schema_and_no_intraday_availability(self):
        r=d.treasury_rows(XML)[0]
        self.assertEqual(r['available_not_before'],'2025-01-03')
        self.assertEqual(r['rates_percent'],{'ROUND_B1_CLOSE_13WK_2':4.5})
        self.assertEqual(r['security_metadata']['CUSIP_13WK'],'123456789')
        self.assertEqual(d.treasury_rows(XML.replace(b'INDEX_DATE',b'NEW_DATE')),[r])

    def test_settlement_account_aggregates_not_used_and_conflicts_rejected(self):
        r=dict(type='settlement',timestamp=1000,instrument_name='BTC-27DEC24',mark_price=100.,index_price=99.,profit_loss=999999)
        x=d.settlement_rows([{'settlements':[r,r|{'instrument_name':'BTC-PERPETUAL'}]}])
        self.assertEqual(len(x),1);self.assertNotIn('profit_loss',x[0])
        with self.assertRaises(ValueError):d.settlement_rows([{'settlements':[r,r|{'mark_price':101.}]}])

    def test_immutable_cache_hash_and_request_budget(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);url='https://example.invalid/fixed';key=d.sha(url.encode());raw=b'{}'
            (p/(key+'.gz')).write_bytes(gzip.compress(raw));d.write(p/(key+'.json'),dict(url=url,sha256=d.sha(raw),bytes=2,body=key+'.gz'))
            cache=d.PublicCache(p,max_requests=0);self.assertEqual(cache.get(url),raw)
            with self.assertRaises(RuntimeError):cache.get(url+'2')
            (p/(key+'.gz')).write_bytes(gzip.compress(b'[]'))
            with self.assertRaises(ValueError):cache.get(url)

    def test_server_page_cap_uses_actual_count_not_requested_count(self):
        offsets=[]
        class FakeCache:
            def __init__(self,*a,**kw):self.start=time.monotonic();self.requests=0;self.bytes=0;self.records=[]
            def get(self,url):
                year=url.rsplit('=',1)[1]
                return XML.replace(b'2025-',(year+'-').encode())
            def rpc(self,method,**params):
                if method=='get_last_settlements_by_currency':return {'settlements':[],'continuation':'none'}
                off=params['offset'];offsets.append(off)
                return {'data':[{'date':f'2025-01-{i+1:02}','delivery_price':100.+i} for i in range(off,min(5,off+2))],'records_total':5}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);plan=d.encode({'instruments':[]});(p/'plan').write_bytes(plan)
            with patch.object(d,'PublicCache',FakeCache),patch.object(d,'PLAN_SHA',d.sha(plan)):
                report=d.collect(p/'out',p/'plan')
            self.assertEqual(offsets,[0,2,4]);self.assertTrue(report['delivery_api_complete']);self.assertEqual(report['delivery_rows'],5)
            class StuckCache(FakeCache):
                count=0
                def rpc(self,method,**params):
                    if method!='get_last_settlements_by_currency':return super().rpc(method,**params)
                    self.count+=1
                    return {'settlements':[dict(type='settlement',timestamp=1000,instrument_name='BTC-27DEC24',mark_price=100.,index_price=100.)],
                            'continuation':str(self.count)}
            with patch.object(d,'PublicCache',StuckCache),patch.object(d,'PLAN_SHA',d.sha(plan)):
                stuck=d.collect(p/'stuck',p/'plan')
            self.assertFalse(stuck['daily_api_complete'])
            self.assertIn('did not move backward',stuck['errors'][0]['error'])

if __name__=='__main__':unittest.main()
