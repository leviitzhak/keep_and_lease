import unittest
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
from server.app import create_app
from server.cloud import CloudJobService, FirestoreJobRepository
from server.job_models import Job, history_page
from server.jobs import JobStore
from tests.test_server_api import FakeEngine
from tests.test_cloud_jobs import FakeLauncher


class BacktestHistoryTests(unittest.TestCase):
    def test_web_image_contains_referenced_gui_scripts(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / 'public/silver_strategy_gui.html').read_bytes()
        self.assertEqual(html, (root / 'silver_strategy_gui.html').read_bytes())
        docker = (root / 'Dockerfile.web').read_text()
        exceptions = (root / '.dockerignore').read_text().splitlines()
        for asset in re.findall(r'<script src="/([^"?]+)', html.decode()):
            path = 'public/' + asset
            self.assertTrue((root / path).is_file(), path)
            self.assertIn(path, docker, path)
            self.assertIn('!' + path, exceptions, path)


    def test_owner_scoped_pages_include_all_states_and_no_result_bodies(self):
        service = JobStore(FakeEngine())
        for index, state in enumerate(('queued', 'running', 'completed', 'failed', 'cancelled')):
            job = Job(f'{index:032x}', {'weight_btc': 100}, str(index), owner_id='alice',
                      status=state, created_at=10, result={'large': 'not in history'})
            service._jobs[job.id] = job
        secret = Job('f' * 32, {}, 'secret', owner_id='bob', created_at=20)
        service._jobs[secret.id] = secret
        client = TestClient(create_app(FakeEngine(), service))
        headers = {'x-goog-authenticated-user-id': 'alice'}
        cursor = None
        found = []
        while True:
            page = client.get('/api/v1/backtests', params={'limit': 2, **({'before': cursor} if cursor else {})}, headers=headers)
            self.assertEqual(page.status_code, 200)
            data = page.json()
            found.extend(data['jobs'])
            cursor = data['next_cursor']
            if not cursor:
                break
        self.assertEqual([item['job_id'] for item in found], [f'{i:032x}' for i in reversed(range(5))])
        self.assertEqual({item['status'] for item in found}, {'queued', 'running', 'completed', 'failed', 'cancelled'})
        self.assertTrue(all('result' not in item and 'logs' not in item for item in found))
        self.assertEqual(client.get('/api/v1/backtests', params={'before': secret.id}, headers=headers).status_code, 404)
        self.assertEqual(client.get('/api/v1/backtests?limit=101', headers=headers).status_code, 422)
        self.assertEqual(client.get('/api/v1/backtests?before=bad', headers=headers).status_code, 422)

    def test_firestore_query_filters_owner_before_reading(self):
        repository = FirestoreJobRepository.__new__(FirestoreJobRepository)
        repository.jobs = Mock()
        repository.jobs.where.return_value.stream.return_value = [
            SimpleNamespace(id='a'*32, to_dict=lambda: {'parameters': {}, 'parameter_hash': 'x', 'owner_id': 'alice', 'created_at': 1})]
        jobs = repository.list_jobs('alice', 2)
        repository.jobs.where.assert_called_once_with('owner_id', '==', 'alice')
        self.assertEqual([j.id for j in jobs], ['a'*32])

    def test_separate_submissions_launch_without_waiting_for_other_execution(self):
        class Repository:
            def __init__(self): self.jobs = {}
            def submit(self, parameters, provenance, owner_id=None):
                identifier = f'{len(self.jobs)+1:032x}'
                job = Job(identifier, parameters, identifier, owner_id=owner_id)
                self.jobs[identifier] = job
                return job, False, True
            def record_launch(self, identifier, operation): return self.jobs[identifier]
            def list_jobs(self, owner_id, limit, before): return history_page(self.jobs.values(), owner_id, limit, before)
            def fail_if_stale(self, identifier, **kwargs): return self.jobs[identifier]
        repo = Repository()
        launcher = FakeLauncher()
        service = CloudJobService(repo, Mock(), launcher, provenance={"engine_commit": "fixture"})
        first, _ = service.submit({'variant': 1}, 'alice')
        second, _ = service.submit({'variant': 2}, 'alice')
        self.assertEqual(launcher.launched, [first.id, second.id])
        self.assertEqual(first.status, 'queued')
        self.assertEqual(len(service.list_jobs('alice')), 2)
