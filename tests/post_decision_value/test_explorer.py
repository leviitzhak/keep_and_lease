"""Real checkpoint, causal state construction, bounded replay and HTTP contracts."""
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import torch

from research.post_decision_value.accounting import Goal, Instrument, Ledger, Position
from research.post_decision_value.engine import Delays, Engine, Instruction, Order, Trade
from research.post_decision_value.explorer import ARCHIVE, ARCHIVE_SHA, Explorer, ROOT, Server, load_inference, read_bundle
from research.post_decision_value.liquidation import ClosingRule, liquidate
from research.post_decision_value.market_simulation import DAY, SimulationConfig, digest, generate, load_payload, select_market
from research.post_decision_value.robust_rollout import scenario_clone
from research.post_decision_value.treasury_model import encode


class MarketTests(unittest.TestCase):
    def test_disabled_is_exact_original_object(self):
        source=object()
        self.assertIs(select_market(source),source)
        self.assertIs(select_market(source,{'enabled':False,'seed':'ignored'}),source)
        with self.assertRaises(ValueError):generate({})

    def test_seed_determinism_and_universe_shared_path(self):
        a=generate({'enabled':True,'seed':9});b=generate({'enabled':True,'seed':9})
        self.assertEqual(a.payload(),b.payload())
        full=generate({'enabled':True,'seed':9,'universe':'full'})
        self.assertEqual(a.path,full.path)
        self.assertNotEqual(a.path,generate({'enabled':True,'seed':10}).path)
        self.assertEqual(a.payload(),load_payload(a.payload()).payload())

    def test_regimes_and_maturity(self):
        for regime,sign in [('up',1),('flat',0),('down',-1)]:
            b=generate(dict(enabled=True,trend=regime,volatility_annual=0,rate_volatility=0,premium_volatility=0))
            change=b.path[-1]['spot']-b.path[0]['spot']
            self.assertEqual((change>0)-(change<0),sign)
            self.assertEqual(b.path[-1]['bill'],100.)
            self.assertTrue(all(t.price>0 and t.amount>0 for t in b.trades))
            self.assertTrue(all(t.time<b.instruments[t.symbol].expiry for t in b.trades))

    def test_row_budget_and_input_validation(self):
        for c in ({'enabled':True,'row_cap':10},{'enabled':True,'fee_bps':float('nan')},{'enabled':1},{'enabled':True,'days':0}):
            with self.assertRaises(ValueError):generate(c)
        payload=generate({'enabled':True,'universe':'full','funding_daily_bps':1}).payload()
        with self.assertRaises(ValueError):load_payload(dict(payload,sha256='bad'))
        for edit in ('native','future_seed','duplicate','indicative','funding','window','missing_seed'):
            p=deepcopy(payload)
            if edit=='native':p['trades'][0]['source_payoff']='inverse'
            if edit=='future_seed':p['seeds'][0]['time']=p['start']+1
            if edit=='duplicate':p['trades'].append(p['trades'][0])
            if edit=='indicative':p['metadata']['source_kind']='indicative_quote'
            if edit=='funding':p['funding'][0]['rate']=.02
            if edit=='window':p['label_end']=p['start']-1
            if edit=='missing_seed':p['seeds'].pop()
            p.pop('sha256');p['sha256']=digest(p)
            with self.subTest(edit=edit),self.assertRaises(ValueError):load_payload(p)

    def test_indicative_never_fills_and_backdating_rejected(self):
        p=generate({'enabled':True}).payload();p.pop('sha256')
        p['metadata']['source_kind']='indicative_quote'
        for row in p['seeds']+p['trades']:row['executable']=False
        p['sha256']=digest(p)
        self.assertFalse(load_payload(p).trades[0].executable)
        p.pop('sha256');p['metadata']['source_kind']='observed_trade';p['trades'][0]['executable']=True
        p['trades'][0]['source_time']=p['trades'][0]['time']-1;p['sha256']=digest(p)
        with self.assertRaisesRegex(ValueError,'Backdated'):load_payload(p)

    def test_funding_native_signs_and_idempotence(self):
        for payoff,q,expected in [('linear',.1,-10.),('inverse',10000.,-.0001)]:
            ins=Instrument('F',10000,payoff=payoff,source_payoff=payoff,fee_bps=0)
            for sign in (1,-1):
                ledger=Ledger({'BTC':1.,'USD':10000.},positions={'F':Position(sign*q,100000.)})
                amount=ledger.pay_funding(ins,100,.001,100000.)
                self.assertAlmostEqual(amount,sign*expected)
                before=ledger.balances.copy();self.assertEqual(ledger.pay_funding(ins,100,.001,100000.),0)
                self.assertEqual(ledger.balances,before)
                self.assertEqual(ledger.clone().settled_ids,ledger.settled_ids)

    def funded_engine(self,payoff='linear'):
        ins=Instrument('F',10000,payoff=payoff,source_payoff=payoff,fee_bps=0)
        q=.1 if payoff=='linear' else 10000.
        ledger=Ledger({'BTC':1.,'USD':10000.},positions={'F':Position(q,100000.)})
        e=Engine({'F':ins},ledger,Goal({'BTC':1.,'USD':10000.},5000,10000,mode='weighted_growth'),
                 delays=Delays(observation=0,report=50,jitter=0,congestion=0),participation=1)
        e.seed_market([Trade(100,'F',100000.,1000,'buy','seed',100000.,payoff)],100)
        return e

    def test_funding_delayed_report_and_scenario_replacement(self):
        e=self.funded_engine();f=dict(time=200,symbol='F',rate=.001,price=100000.,source='synthetic_market')
        e.event_trace=[];e.add_funding([f]);e.advance(200)
        self.assertEqual(e.hidden.ledger.balances['USD'],9990.)
        self.assertEqual(e.observable.ledger.balances['USD'],10000.)
        self.assertEqual(e.event_trace[-1]['observed_balances_after']['USD'],10000.)
        self.assertEqual(e.event_trace[-1]['balances_after']['USD'],9990.)
        clone=scenario_clone(e,dict(seed=8,trades=[],funding=[dict(f,time=300,rate=-.001)]))
        clone.advance(250);self.assertEqual(clone.observable.ledger.balances['USD'],9990.)
        clone.advance(350);self.assertEqual(clone.observable.ledger.balances['USD'],10000.)
        self.assertEqual(e.observable.ledger.balances['USD'],10000.)

    def test_tail_pays_funding_before_close(self):
        e=self.funded_engine();e.add_funding([dict(time=200,symbol='F',rate=.001,price=100000.,source='synthetic_market')])
        tr=Trade(300,'F',100000.,1,'buy','close',100000.,'linear')
        result=liquidate(e,[tr],400,ClosingRule(tail_ms=300))
        self.assertTrue(result['done']);self.assertEqual(result['balances']['USD'],9990.)
        self.assertEqual(result['trace'][0]['kind'],'synthetic_funding')
        self.assertEqual(e.hidden.ledger.balances['USD'],10000.)

    def test_no_funding_when_flat_or_already_closed(self):
        e=self.funded_engine();e.add_funding([dict(time=300,symbol='F',rate=.001,price=100000.,source='synthetic_market')])
        tr=Trade(200,'F',100000.,1,'buy','close',100000.,'linear')
        self.assertEqual(liquidate(e,[tr],400,ClosingRule(tail_ms=300))['balances']['USD'],10000.)


class ExplorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        with patch('urllib.request.urlopen',side_effect=AssertionError('Startup must remain offline')):
            cls.app=Explorer()
    def setUp(self):
        self.app.select_checkpoint({});self.market=self.app.market({'kind':'fixture'})
        self.request={'market_id':self.market['id'],'state':deepcopy(self.market['defaults'])}
    def buy(self):
        e,a,h,b,c=self.app.state(self.request)
        self.request['state']['action']=dict(kind='create',orders=[dict(identifier='buy',symbol='BILL',quantity=25,limit=c['price'])])
        return c

    def test_real_inference_and_matching_reference(self):
        case=self.buy();r=self.app.evaluate(self.request);e,a,h,_,_=self.app.state(self.request)
        direct=float(self.app.model.predict([encode(e.observe(),a,e.goal,e.instruments,h)])[0])
        self.assertEqual(direct,r['prediction']['value']);self.assertIsNotNone(r['reference']['value'])
        replay=self.app.replay(self.request)
        self.assertTrue(replay['outcome']['done'])
        self.assertAlmostEqual(replay['outcome']['utility'],r['reference']['value'],places=10)
        self.assertEqual(r['signed_error'],direct-r['reference']['value'])
        self.assertTrue(r['liquidation']['cancelled_pending'])

    def test_checkpoint_load_does_not_change_rng_or_train(self):
        rng=torch.get_rng_state().clone()
        with patch('torch.optim.Adam',side_effect=AssertionError('No optimizer in inference')):
            model=load_inference(self.app.published['selected-model.pt'])
        self.assertTrue(torch.equal(rng,torch.get_rng_state()));self.assertFalse(model.training)
        self.assertFalse(self.app.bootstrap()['simulation_enabled'])
        self.assertNotIn('test',[c['split'] for c in self.app.bootstrap()['cases']])

    def test_future_prices_never_change_current_prediction(self):
        self.buy();before=self.app.evaluate(self.request)
        bundle,case=self.app.markets[self.market['id']]
        changed=deepcopy(bundle);changed.trades=[replace(t,price=t.price+2) for t in changed.trades]
        self.app.markets['changed']=(changed,None)
        request=deepcopy(self.request);request['market_id']='changed';after=self.app.evaluate(request)
        self.assertEqual(before['prediction']['features'],after['prediction']['features'])
        self.assertEqual(before['prediction']['value'],after['prediction']['value'])
        self.assertIsNone(after['reference']['value'])

    def test_time_causality_and_horizon_bounds(self):
        self.request['state']['time']+=DAY
        self.request['state']['horizon_ms']-=DAY
        r=self.app.evaluate(self.request)
        self.assertTrue(all(t['received']<=r['observable']['time'] for t in r['observable']['history']))
        self.request['state']['horizon_ms']+=DAY+1
        with self.assertRaises(ValueError):self.app.evaluate(self.request)

    def test_liabilities_and_full_universe_have_no_invented_prediction(self):
        self.request['state']['flows']=[dict(date=self.market['start']+DAY,currency='USD',amount=-5)]
        r=self.app.evaluate(self.request);self.assertIsNone(r['prediction']['value']);self.assertIsNone(r['reference']['value'])
        m=self.app.market({'kind':'simulation','configuration':{'enabled':True,'universe':'full'}})
        r=self.app.evaluate(dict(market_id=m['id'],state=m['defaults']))
        self.assertIsNone(r['prediction']['value']);self.assertIsNone(r['toy_optimum'])

    def test_simulated_bill_model_is_unvalidated_and_reference_unavailable(self):
        m=self.app.market({'kind':'simulation','configuration':{'enabled':True}})
        r=self.app.evaluate(dict(market_id=m['id'],state=m['defaults']))
        self.assertIsNotNone(r['prediction']['value']);self.assertIsNone(r['reference']['value'])
        self.assertIn('Unvalidated',r['prediction']['validation'])

    def test_inventory_boundary_reference(self):
        case=self.buy();self.request['state']['action']={'kind':'wait'}
        self.request['state']['positions']={'BILL':dict(quantity=25,basis=case['price'])}
        self.request['state']['balances']['USD']-=25*case['price']*(1+case['fee_bps']/10000)
        self.request['state']['horizon_ms']=0
        result=self.app.evaluate(self.request)
        self.assertAlmostEqual(result['liquidation']['utility'],result['reference']['value'],places=10)
        self.assertIsNone(result['toy_optimum'])

    def test_pending_working_amend_cancel_admission(self):
        case=self.buy();order=self.request['state']['action']['orders'][0]
        self.request['state']['orders']=[dict(order,status='working')]
        self.request['state']['action']=dict(kind='amend',targets=['buy'],orders=[dict(order,quantity=5)])
        r=self.app.evaluate(self.request);self.assertTrue(r['prediction']['admissible']);self.assertIsNone(r['reference']['value'])
        self.request['state']['orders'][0]['status']='pending'
        self.request['state']['action']=dict(kind='cancel',targets=['buy'])
        r=self.app.evaluate(self.request);self.assertTrue(r['prediction']['admissible']);self.assertTrue(r['observable']['pending'])
        self.request['state']['action']=dict(kind='create',orders=[dict(order,identifier='bad',quantity=.5)])
        self.assertEqual(self.app.evaluate(self.request)['prediction']['reason'],'native_rounding')

    def test_surface_wait_and_references(self):
        c=self.buy();r=self.app.surface(dict(**self.request,symbol='BILL',quantities=[0,5,25,60],prices=[c['price'],c['price']+.01]))
        self.assertEqual(len(r['cells']),8)
        self.assertTrue(all(x['reference'] is None for x in r['cells'] if x['quantity'] and x['price']!=c['price']))
        with self.assertRaises(ValueError):self.app.surface(dict(**self.request,symbol='BILL',quantities=list(range(64)),prices=[c['price']]))

    def test_churn_stops_incomplete_without_value(self):
        self.buy();r=self.app.replay(dict(**self.request,policy='network',max_decisions=2))
        self.assertFalse(r['outcome']['done']);self.assertNotIn('utility',r['outcome'])
        self.assertLessEqual(len(r['decisions']),2)
        remaining=[d['remaining_ms'] for d in r['decisions']]
        self.assertEqual(remaining,sorted(remaining,reverse=True))

    def test_full_market_short_future_native_close(self):
        for payoff in ('linear','inverse'):
            m=self.app.market({'kind':'simulation','configuration':{'enabled':True,'universe':'full','future_payoff':payoff,'funding_daily_bps':2}})
            request=dict(market_id=m['id'],state=deepcopy(m['defaults']))
            request['state']['positions']={'FUTURE':dict(quantity=-.01 if payoff=='linear' else -1000,basis=100000)}
            request['state']['horizon_ms']=DAY
            r=self.app.replay(request);self.assertTrue(r['outcome']['done']);self.assertTrue(any(e['kind']=='funding' for e in r['events']))
            self.assertEqual(r['outcome']['remaining_positions'],{})

    def test_spot_repurchase_is_explicit_and_survives_closing(self):
        m=self.app.market({'kind':'simulation','configuration':{'enabled':True,'universe':'full','volatility_annual':0}})
        request=dict(market_id=m['id'],state=deepcopy(m['defaults']))
        request['state']['horizon_ms']=DAY
        request['state']['action']=dict(kind='create',orders=[dict(identifier='repurchase',symbol='SPOT',quantity=.005,limit=100100.)])
        r=self.app.replay(request)
        self.assertTrue(r['outcome']['done'])
        self.assertAlmostEqual(r['outcome']['balances']['BTC'],1.005)
        self.assertAlmostEqual(r['outcome']['balances']['USD'],10000-.005*100100*1.0005)

    def test_known_opportunity_and_no_opportunity_controls(self):
        for case in list(self.app.cases.values())[:4]:
            m=self.app.market(dict(kind='fixture',id=case['id']))
            r=self.app.evaluate(dict(market_id=m['id'],state=m['defaults']))
            if case['category']=='profitable':self.assertGreater(r['toy_optimum']['value'],0)
            else:self.assertEqual(r['toy_optimum']['value'],0)

    def test_manifest_hash_and_local_file_failures_keep_model(self):
        blob=self.app.published['selected-model.pt'];old=self.app.model_sha
        with self.assertRaises(ValueError):self.app.import_checkpoint(dict(base64=base64.b64encode(blob).decode(),sha256='bad'))
        self.assertEqual(old,self.app.model_sha)
        result=self.app.import_checkpoint(dict(base64=base64.b64encode(blob).decode(),sha256=hashlib.sha256(blob).hexdigest()))
        self.assertIn('unverified',result['status']);self.assertEqual(result['target'],'diagnostic-hold-boundary-v1')
        with self.assertRaises(ValueError):read_bundle(b'invalid')
        bad=io.BytesIO();torch.save({'schema':'legacy'},bad)
        with self.assertRaisesRegex(ValueError,'legacy'):load_inference(bad.getvalue())

    def test_explicit_download_verifies_before_cache(self):
        blob=(ROOT/'docs/research/post_decision_value'/ARCHIVE).read_bytes()
        class Response(io.BytesIO):
            def geturl(self):
                from research.post_decision_value.explorer import URL
                return URL
        with tempfile.TemporaryDirectory() as temp:
            self.app.cache=Path(temp)
            with patch('urllib.request.urlopen',return_value=Response(blob)):
                result=self.app.download();self.assertTrue(result['verified'])
            self.assertEqual(hashlib.sha256((Path(temp)/ARCHIVE).read_bytes()).hexdigest(),ARCHIVE_SHA)
            with patch('urllib.request.urlopen',return_value=Response(b'wrong')),self.assertRaises(ValueError):self.app.download()
            self.assertEqual((Path(temp)/ARCHIVE).read_bytes(),blob)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=Server(('127.0.0.1',0),Explorer());cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def call(self,method,path,data=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        body=json.dumps(data) if data is not None else None
        conn.request(method,path,body,headers or {});response=conn.getresponse();result=response.read();status=response.status;conn.close()
        return status,result
    def test_bootstrap_static_and_path_traversal(self):
        status,body=self.call('GET','/api/bootstrap');self.assertEqual(status,200)
        token=json.loads(body)['token'];self.assertEqual(token,self.server.token)
        for path in ('/','/app.js','/style.css'):self.assertEqual(self.call('GET',path)[0],200)
        self.assertEqual(self.call('GET','/../accounting.py')[0],404)
        self.assertEqual(self.call('GET','/api/bootstrap',headers={'Host':'evil.example'})[0],403)
    def test_same_origin_token_and_json_validation(self):
        headers={'Content-Type':'application/json','X-Explorer-Token':self.server.token}
        self.assertEqual(self.call('POST','/api/market',{},headers)[0],200)
        self.assertEqual(self.call('POST','/api/market',{},dict(headers,Origin='https://evil.example'))[0],403)
        self.assertEqual(self.call('POST','/api/market',{}, {'Content-Type':'application/json'})[0],403)
        self.assertEqual(self.call('POST','/api/market',[],headers)[0],400)
        self.assertEqual(self.call('POST','/api/market',{'kind':'wrong'},headers)[0],400)
    def test_request_cap(self):
        headers={'Content-Type':'application/json','X-Explorer-Token':self.server.token,'Content-Length':'8000001'}
        self.assertEqual(self.call('POST','/api/market',{},headers)[0],413)
    def test_public_bind_rejected(self):
        with self.assertRaises(ValueError):Server(('0.0.0.0',0),self.server.app)


class FrontendContractTests(unittest.TestCase):
    def test_static_ids_used_by_javascript_exist(self):
        from html.parser import HTMLParser
        import re
        class IDs(HTMLParser):
            def __init__(self):super().__init__();self.ids=[]
            def handle_starttag(self,tag,attrs):
                self.ids.extend(value for key,value in attrs if key=='id')
        root=ROOT/'research/post_decision_value/explorer_web'
        parser=IDs();parser.feed((root/'index.html').read_text())
        self.assertEqual(len(parser.ids),len(set(parser.ids)))
        js=(root/'app.js').read_text()
        used=set(re.findall(r'''\$\(["']([^"']+)["']\)''',js))
        self.assertGreater(len(used),60)
        self.assertEqual(used-set(parser.ids),set())
        # Static assets and SVG renderers contain no remote dependency or API.
        self.assertNotIn('https://',js)
        self.assertNotIn('<script src="https:',(root/'index.html').read_text())

    def test_corrupt_checkpoint_rejected_before_replacing_model(self):
        app=Explorer();before=app.model_sha
        blob=b'not a torch file'
        with self.assertRaises(ValueError):
            app.import_checkpoint(dict(base64=base64.b64encode(blob).decode(),sha256=hashlib.sha256(blob).hexdigest()))
        self.assertEqual(before,app.model_sha)


if __name__=='__main__':unittest.main()
