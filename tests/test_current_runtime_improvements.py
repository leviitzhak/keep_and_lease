import gzip
import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import btc_trade_backtest as replay
from replay_checkpoints import decode, encode
from server.app import create_app
from server.job_models import Job
from server.replay_extensions import INTERNAL_PARENT_KEY, engine_parameters, install as install_extensions, seed_extension
from server.strategy_catalog import install
from tests.test_btc_trade_backtest import payload
from tests.test_server_api import FakeEngine


class CurrentRuntimeImprovementsTests(unittest.TestCase):
    def test_checked_in_strategies_are_exposed_read_only(self):
        app = create_app(FakeEngine())
        install(app)
        with TestClient(app) as client:
            response = client.get('/api/v1/strategies')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        strategies = response.json()['strategies']
        names = {item['name'] for item in strategies}
        self.assertIn('full silver long gradual', names)
        self.assertIn('research-btc-long-gradual-500ms', names)
        self.assertTrue(all(isinstance(item['parameters'], dict) for item in strategies))

    def test_trade_replay_defaults_to_100k_and_3000_plot_points(self):
        parameters = payload()
        parameters.pop('trade_initial_capital_usd', None)
        parameters.pop('trade_plot_max_points', None)
        validated = replay.validate(parameters)
        self.assertEqual(validated[5], 100000)
        self.assertEqual(validated[6], 3000)

    def test_trade_plot_point_limit_is_bounded(self):
        for value in (499, 10001):
            parameters = payload()
            parameters['trade_plot_max_points'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                replay.validate(parameters)

    def test_checkpoint_infinity_sentinel_uses_strict_json_and_roundtrips(self):
        encoded = encode({'minimum': math.inf, 'negative': -math.inf, 'finite': 1.25})
        raw = gzip.decompress(encoded)
        self.assertNotIn(b'Infinity', raw)
        self.assertNotIn(b'NaN', raw)
        restored = decode(encoded)
        self.assertEqual(restored['minimum'], math.inf)
        self.assertEqual(restored['negative'], -math.inf)
        self.assertEqual(restored['finite'], 1.25)
        with self.assertRaisesRegex(ValueError, 'NaN'):
            encode({'invalid': math.nan})

    def test_public_job_hides_extension_parent_metadata(self):
        p = payload()
        p[INTERNAL_PARENT_KEY] = 'a' * 32
        job = Job('b' * 32, p, 'hash')
        self.assertNotIn(INTERNAL_PARENT_KEY, job.public()['parameters'])
        self.assertEqual(engine_parameters(p), job.public()['parameters'])

    def test_completed_replay_can_request_later_end_through_dedicated_api(self):
        provenance = {'engine_commit': 'same'}
        parent_parameters = payload()
        parent_parameters['backtest_end'] = '2026-06-25T00:00:02'
        parent = Job('a' * 32, parent_parameters, 'parent-hash', owner_id='user@example.com',
                     status='completed', provenance=provenance)
        child = Job('b' * 32, {}, 'child-hash', owner_id='user@example.com', provenance=provenance)
        class Service:
            results = object()
            def __init__(self): self.provenance = provenance; self.submitted = None
            def get(self, job_id): return parent if job_id == parent.id else None
            def submit(self, parameters, owner):
                self.submitted = dict(parameters)
                child.parameters = dict(parameters)
                return child, False
            def capabilities(self): return {'schema_version': 1, 'engine_commit': 'same'}
        service = Service()
        app = create_app(FakeEngine(), job_service=service)
        install_extensions(app)
        with TestClient(app) as client:
            response = client.post(
                f'/api/v1/backtests/{parent.id}/extend',
                headers={'x-goog-authenticated-user-email': 'user@example.com'},
                json={'backtest_end': '2026-06-25T00:00:03'},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(service.submitted[INTERNAL_PARENT_KEY], parent.id)
        self.assertEqual(service.submitted['backtest_end'], '2026-06-25T00:00:03')
        self.assertNotIn(INTERNAL_PARENT_KEY, response.json()['parameters'])
        self.assertEqual(response.json()['extension_parent_job_id'], parent.id)

    def test_extension_worker_seeds_parent_prefix_once_with_engine_parameters(self):
        old = payload(); old['backtest_end'] = '2026-06-25T00:00:02'
        new = dict(old, backtest_end='2026-06-25T00:00:03')
        child_parameters = dict(new); child_parameters[INTERNAL_PARENT_KEY] = 'a' * 32
        provenance = {'engine_commit': 'same'}
        parent = Job('a' * 32, old, 'old', owner_id='owner', status='completed', provenance=provenance)
        child = Job('b' * 32, child_parameters, 'new', owner_id='owner', status='running', provenance=provenance)
        repository = Mock(); repository.get.return_value = parent
        child_checkpoints = Mock(); child_checkpoints.latest.return_value = None
        parent_checkpoints = Mock(); parent_checkpoints.latest.return_value = {'identity': 'parent'}
        results = Mock()
        results.checkpoint_store.side_effect = lambda job_id: parent_checkpoints if job_id == parent.id else child_checkpoints
        parent_audit, child_audit = object(), object()
        results.audit_store.return_value = parent_audit
        audit = SimpleNamespace(checkpoints=child_checkpoints, store=child_audit)
        engine = SimpleNamespace(data_root='root')
        progress = Mock()
        trade_store = SimpleNamespace(manifest_bytes=b'manifest')
        with patch('trade_data_store.ParquetTradeStore', return_value=trade_store), \
             patch('replay_extension.extend_checkpoint') as extend:
            calculated = seed_extension(child, repository, results, engine, audit, progress)
        self.assertEqual(calculated, new)
        extend.assert_called_once_with(
            {'identity': 'parent'}, old, new, b'manifest', 'root',
            parent_audit, child_audit, child_checkpoints,
        )
        self.assertEqual(progress.call_count, 2)


if __name__ == '__main__':
    unittest.main()
