"""No network: durable resume gates and transactional requeue semantics."""
import copy
import time
import unittest
from unittest.mock import Mock

from server.cloud import CloudJobService, FirestoreJobRepository, parameter_hash
from server.job_models import Job


class ResumeServiceTests(unittest.TestCase):
    def setup_service(self):
        provenance = {'engine_commit': 'tested', 'trade_manifest_sha256': 'dataset'}
        job = Job('a'*32, {'btc_data_source': 'trade_tape'}, 'hash', owner_id='owner',
                  status='failed', attempt=1, execution_name='execution', provenance=provenance)
        repository, results, launcher = Mock(), Mock(), Mock()
        repository.requeue_trade.return_value = job
        repository.record_launch.return_value = job
        launcher.is_finished.return_value = True
        results.checkpoint_store.return_value.latest.return_value = {'identity': 'checkpoint'}
        return CloudJobService(repository, results, launcher, provenance), job

    def test_stopped_run_with_matching_provenance_resumes_once(self):
        service, job = self.setup_service()
        self.assertIs(service.resume(job), job)
        service.repository.requeue_trade.assert_called_once_with(job.id, 1)
        service.launcher.launch.assert_called_once_with(job.id)

    def test_running_worker_missing_checkpoint_or_changed_revision_prevents_launch(self):
        for failure in ('running', 'execution_alive', 'no_checkpoint', 'different_engine', 'candle'):
            service, job = self.setup_service()
            if failure == 'running': job.status = 'running'
            elif failure == 'execution_alive': service.launcher.is_finished.return_value = False
            elif failure == 'no_checkpoint': service.results.checkpoint_store.return_value.latest.return_value = None
            elif failure == 'different_engine': job.provenance = {'engine_commit': 'different'}
            else: job.parameters['btc_data_source'] = 'minute'
            with self.subTest(failure=failure), self.assertRaises(ValueError): service.resume(job)
            service.launcher.launch.assert_not_called()

    def test_requeue_is_compare_and_swap_and_refreshes_queued_deadline(self):
        _, job = self.setup_service()
        job.created_at = time.time()-7200
        job.cancellation_requested = True
        repository = object.__new__(FirestoreJobRepository)
        def transition(job_id, mutate):
            mutate(job)
            return job
        repository._transition = transition
        repository.requeue_trade(job.id, 1)
        self.assertEqual(job.status, 'queued')
        self.assertFalse(job.cancellation_requested)
        self.assertLess(time.time()-job.queued_at, 1)
        self.assertLess(job.created_at, time.time()-7000)
        with self.assertRaises(ValueError): repository.requeue_trade(job.id, 1)

    def test_trade_manifest_changes_job_cache_key(self):
        self.assertNotEqual(parameter_hash({}, {'trade_manifest_sha256': 'a'}, 'owner'),
                            parameter_hash({}, {'trade_manifest_sha256': 'b'}, 'owner'))
