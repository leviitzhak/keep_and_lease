"""Request boundaries, private evidence, and write-ahead acquisition state."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
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
            state={'streams':{'future-bbo-1m':{'status':'inflight'}},'reserved_estimated_usd':.5}
            cache.checkpoint(Path(folder)/'state.json',state)
            bucket.blob.return_value.upload_from_filename.assert_not_called()
            saved=bucket.blob.return_value.upload_from_string.call_args
            self.assertEqual(json.loads(saved.args[0]),state)
            self.assertEqual(saved.kwargs['if_generation_match'],0)

    def test_done_raw_is_durable_before_done_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            bucket=Mock();bucket.blob.return_value.exists.return_value=False
            cache=runner.Cache(bucket,'mbt',Path(folder),Mock())
            cache.checkpoint(Path(folder)/'state.json',{'streams':{'future-bbo-1m':{'status':'done','sha256':'a'*64}}})
            methods=[call[0] for call in bucket.mock_calls]
            self.assertLess(methods.index('blob().upload_from_filename'),methods.index('blob().upload_from_string'))

if __name__=='__main__':unittest.main()
