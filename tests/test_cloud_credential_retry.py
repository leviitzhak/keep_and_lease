import runpy
import unittest
from pathlib import Path
from google.auth.exceptions import RefreshError

ROOT = Path(__file__).resolve().parents[1]
retry = runpy.run_path(str(ROOT / 'scripts/retry-cloud-command.py'))['retry']


class CredentialRetryTest(unittest.TestCase):
    def test_transient_recovers(self):
        calls = []
        waits = []
        def operation():
            calls.append(1)
            if len(calls) < 3:
                raise RefreshError('Unable to retrieve Identity Pool subject token', 'connection timeout')
            return 'passed'
        self.assertEqual(retry(operation, waits.append), 'passed')
        self.assertEqual(waits, [2, 4])

    def test_exhaustion_and_permanent_failures(self):
        for error, count in [(RefreshError('connection timeout'), 4),
                             (RefreshError('permission denied'), 1),
                             (ValueError('checksum mismatch'), 1)]:
            calls = []
            def operation():
                calls.append(1)
                raise error
            with self.assertRaises(type(error)):
                retry(operation, lambda _: None)
            self.assertEqual(len(calls), count)

class UploadedRecoveryTest(unittest.TestCase):
    def test_failed_verification_never_creates_receipt(self):
        import hashlib
        import json
        import tempfile
        from unittest.mock import Mock, patch
        module = runpy.run_path(str(ROOT / 'scripts/recover-btc-uploaded-days.py'))
        recover = module['recover']
        state = recover.__globals__
        source = dict(start='2026-08-26T00:00:00', end='2026-08-27T00:00:00',
                      spot=dict(path='spot.gz', sha256=hashlib.sha256(b'tape').hexdigest()), futures={})
        encoded = json.dumps(source).encode()
        store = Mock(manifest_bytes=b'manifest', source_manifest=source,
                     manifest={'source_manifest_sha256': hashlib.sha256(encoded).hexdigest()})
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            raw = out / 'raw/2026-08-26'
            raw.mkdir(parents=True)
            (raw / 'manifest.json').write_bytes(encoded)
            (raw / 'spot.gz').write_bytes(b'tape')
            with patch.dict(state, ParquetTradeStore=lambda _: store,
                            DATASETS={'2026-08-26': hashlib.sha256(b'manifest').hexdigest()}), \
                    patch.object(state['subprocess'], 'run', side_effect=RuntimeError('verification failed')):
                with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                    recover('2026-08-26', out)
            self.assertFalse((out / 'receipts/2026-08-26.json').exists())
