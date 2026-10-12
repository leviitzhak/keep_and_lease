"""Request boundaries, private evidence, and write-ahead acquisition state."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runner',ROOT/'scripts/cloud-databento-research.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.pem=cls.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def request(self):
        return dict(schema_version=1,request_id='test',action='estimate',result_public_key_pem=self.pem)

    def test_only_metadata_server_errors_are_retried(self):
        from databento.common.error import BentoServerError
        client=Mock();client.metadata.get_cost.side_effect=[BentoServerError(503),.12]
        with patch.object(runner.time,'sleep'):
            self.assertEqual(runner.metadata_cost(client,symbols=['SICZ6']),.12)
        self.assertEqual(client.metadata.get_cost.call_count,2)
        client.timeseries.get_range.assert_not_called()

    def test_recovery_requires_matching_failed_request_and_covers_exact_month(self):
        import pandas as pd
        c=dict(future_symbol='MBTV6',start='2026-09-01T00:00:00Z',end='2026-10-01T00:00:00Z')
        item={'name':'future-definition','request':dict(dataset='GLBX.MDP3',symbols=['MBTV6'],schema='definition',start=c['start'],end=c['end'])}
        gold=Mock();gold.requests_for.return_value=[item]
        state={'streams':{'future-definition':dict(status='inflight',request=item['request'])},'reserved_estimated_usd':.053}
        self.assertEqual(runner.acquisition_requests(gold,c,state,{}),[item])
        parts=runner.acquisition_requests(gold,c,state,{'reviewed_recovery_run':37313440074})
        self.assertEqual(len(parts),6)
        self.assertEqual(pd.Timestamp(parts[0]['request']['start']),pd.Timestamp(c['start']))
        self.assertEqual(pd.Timestamp(parts[-1]['request']['end']),pd.Timestamp(c['end']))
        for left,right in zip(parts,parts[1:]):self.assertEqual(left['request']['end'],right['request']['start'])
        self.assertEqual(state['reserved_estimated_usd'],.053)
        state['streams']['future-definition']['request']={'symbols':['OTHER']}
        with self.assertRaises(ValueError):runner.acquisition_requests(gold,c,state,{'reviewed_recovery_run':37313440074})

    def test_request_cannot_expand_scope_or_budget(self):
        runner.validate_request(self.request())
        for field,value in [('command','bash'),('max_cost_usd',100),('source_commit','x'),('secret','another-key')]:
            request=self.request();request[field]=value
            with self.assertRaises(ValueError):runner.validate_request(request)
        for action in ('submit-mbo','download','trade'):
            request=self.request();request['action']=action
            with self.assertRaises(ValueError):runner.validate_request(request)

    def test_screen_requires_explicit_both_snapshot_sources(self):
        request=self.request();request['action']='screen'
        request['references']={p:dict(units_per_share=.001,source='issuer',as_of='2026-10-02') for p in runner.PRESETS}
        runner.validate_request(request)
        request['references']['mbt']['units_per_share']=float('nan')
        with self.assertRaises(ValueError):runner.validate_request(request)

    def test_treasury_study_accepts_only_fixed_metadata_request(self):
        request=self.request();request['study']=runner.TREASURY_STUDY
        runner.validate_request(request)
        for extra in ({'action':'screen'}, {'start':'2020-01-01'}, {'symbols':['ES.FUT']},
                      {'reviewed_recovery_run':37313440074}, {'study':'arbitrary'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                runner.validate_request({**request,**extra})

    def test_treasury_quote_has_exact_window_and_never_acquires_data(self):
        client=Mock()
        client.metadata.get_dataset_range.return_value={'start':'2010-01-01T00:00:00Z','end':'2026-10-11T00:00:00Z'}
        client.symbology.resolve.side_effect=lambda **kw: {'result': {symbol:[{'s':'1'}] for symbol in kw['symbols'] if symbol.endswith('Z6')}}
        client.metadata.get_cost.side_effect=lambda **kw: .25 if kw['stype_in']=='parent' else .2
        report={};runner.treasury_quote_plan(client,report)
        self.assertEqual(client.metadata.get_cost.call_count,48)
        self.assertEqual(set(report['quotes']),set(runner.TREASURY_PRODUCTS))
        for product,row in report['quotes'].items():
            self.assertEqual(row['outright_symbols'],[product+'Z6'])
            for scope in ('parent_family','outrights'):
                self.assertEqual(set(row[scope]),set(runner.TREASURY_SCHEMAS))
                for value in row[scope].values():
                    self.assertEqual(value['request']['start'],runner.TREASURY_START)
                    self.assertEqual(value['request']['end'],runner.TREASURY_END)
        self.assertEqual(report['totals_usd']['parent_family']['mbo'],1.5)
        self.assertAlmostEqual(report['totals_usd']['outrights']['mbo'],1.2)
        self.assertFalse(report['paid_download_started'])
        client.timeseries.get_range.assert_not_called()
        client.batch.submit_job.assert_not_called()

    def test_treasury_quote_rejects_truncated_data_window(self):
        client=Mock();client.metadata.get_dataset_range.return_value={'start':'2010-01-01T00:00:00Z','end':'2026-10-09T00:00:00Z'}
        with self.assertRaises(ValueError):runner.treasury_quote_plan(client,{})
        client.metadata.get_cost.assert_not_called()
        client.symbology.resolve.assert_not_called()

    def test_only_recipient_can_read_encrypted_summary(self):
        payload={'private':'test-market-statistics','status':'completed'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'result.json'
            runner.encrypt_result(payload,self.key.public_key(),path)
            raw=path.read_text();self.assertNotIn('test-market-statistics',raw)
            envelope=json.loads(raw)
            data_key=self.key.decrypt(base64.b64decode(envelope['wrapped_key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
            plain=AESGCM(data_key).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['ciphertext']),b'databento-research-v1')
            self.assertEqual(json.loads(plain),payload)

    def test_inflight_state_is_uploaded_before_any_done_file(self):
        with tempfile.TemporaryDirectory() as folder:
            bucket=Mock();gold=Mock();cache=runner.Cache(bucket,'sic',Path(folder),gold)
            state={'streams':{'future-definition':{'status':'inflight'}},'reserved_estimated_usd':.5}
            cache.checkpoint(Path(folder)/'state.json',state)
            bucket.blob.return_value.upload_from_filename.assert_not_called()
            saved=bucket.blob.return_value.upload_from_string.call_args
            self.assertEqual(json.loads(saved.args[0]),state)
            self.assertEqual(saved.kwargs['if_generation_match'],0)

    def test_done_raw_is_durable_before_done_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            bucket=Mock();bucket.blob.return_value.exists.return_value=False
            cache=runner.Cache(bucket,'mbt',Path(folder),Mock())
            cache.checkpoint(Path(folder)/'state.json',{'streams':{'future-definition':{'status':'done','sha256':'a'*64}}})
            methods=[call[0] for call in bucket.mock_calls]
            self.assertLess(methods.index('blob().upload_from_filename'),methods.index('blob().upload_from_string'))

if __name__=='__main__':unittest.main()

