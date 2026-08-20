import gzip
import hashlib
import json
import time
import unittest

from fastapi.testclient import TestClient

from server.app import create_app
from server.cloud import (
    CloudJobService,
    CloudRunJobLauncher,
    GcsResultStore,
    parameter_hash,
)
from server.job_models import Job, ResultStream, StoredResult
from server.worker import WorkerRunner


class FakeRepository:
    def __init__(self, job=None):
        self.job = job
        self.failed = None
        self.completed = None
        self.cancelled = None
        self.cancellation_error = None
        self.launch_operation = None

    def submit(self, parameters, provenance):
        if self.job and self.job.status in {"queued", "running", "completed"}:
            return self.job, self.job.status == "completed", False
        digest = parameter_hash(parameters, provenance)
        self.job = Job("a" * 32, dict(parameters), digest, provenance=provenance)
        return self.job, False, True

    def record_launch(self, _job_id, operation_name):
        self.launch_operation = operation_name
        self.job.launch_operation_name = operation_name
        return self.job

    def fail_if_stale(self, _job_id, **_kwargs):
        return self.job

    def claim(self, _job_id, lease_owner, execution_name):
        if self.job.cancellation_requested:
            self.job.status = "cancelled"
            return self.job
        self.job.status = "running"
        self.job.lease_owner = lease_owner
        self.job.execution_name = execution_name
        self.job.started_at = time.time()
        return self.job

    def progress(self, _job_id, _lease_owner, stage, detail):
        self.job.stage = stage
        self.job.detail = detail
        return self.job

    def heartbeat(self, _job_id, _lease_owner):
        self.job.heartbeat_at = time.time()
        return True

    def get(self, _job_id):
        return self.job

    def complete(self, _job_id, _lease_owner, stored, peak_rss, timings, provenance):
        self.completed = (stored, peak_rss, timings, provenance)
        self.job.status = "completed"
        self.job.result_uri = stored.uri
        self.job.result_size_bytes = stored.result_size_bytes
        return self.job

    def fail(self, _job_id, detail, **kwargs):
        self.failed = (detail, kwargs)
        self.job.status = "failed"
        self.job.error = detail
        return self.job

    def request_cancel(self, _job_id):
        self.job.cancellation_requested = True
        return self.job

    def mark_cancelled(self, _job_id, detail):
        self.cancelled = detail
        self.job.status = "cancelled"
        return self.job

    def record_cancellation_error(self, _job_id, detail):
        self.cancellation_error = detail
        self.job.detail = detail
        return self.job


class FakeLauncher:
    def __init__(self, failure=None):
        self.failure = failure
        self.launched = []
        self.cancelled = []

    def launch(self, job_id):
        self.launched.append(job_id)
        if self.failure:
            raise self.failure
        return "operations/launch-1"

    def cancel(self, execution_name):
        self.cancelled.append(execution_name)
        if self.failure:
            raise self.failure


class FakeRunClient:
    def __init__(self):
        self.request = None

    def run_job(self, request):
        self.request = request
        return type(
            "Operation",
            (),
            {"operation": type("RawOperation", (), {"name": "operations/run-1"})()},
        )()


class FakeExecutionsClient:
    def __init__(self):
        self.request = None

    def cancel_execution(self, request):
        self.request = request


class FakeResultStore:
    def __init__(self):
        self.encoded = None
        self.metadata = None

    def write(self, job_id, encoded, metadata):
        self.encoded = encoded
        self.metadata = metadata
        return StoredResult(
            f"gs://results/jobs/{job_id}/result.json.gz",
            len(encoded),
            len(encoded) // 2,
            hashlib.sha256(encoded).hexdigest(),
            "compressed",
        )

    def open(self, job):
        return job.result_uri


class FakeEngine:
    def run_backtest(self, parameters, progress=None):
        progress("running", "fake calculation")
        return {"parameters": parameters, "series": [["2000-01-03", 1.0]]}

    def provenance(self):
        return {"engine_commit": "commit", "data_manifest_hash": "manifest"}


class FakeBlob:
    def __init__(self):
        self.payload = None
        self.kwargs = None
        self.metadata = None
        self.cache_control = None

    def upload_from_string(self, payload, **kwargs):
        self.payload = payload
        self.kwargs = kwargs


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return self.objects.setdefault(name, FakeBlob())


class FakeStorageClient:
    def __init__(self):
        self.value = FakeBucket()

    def bucket(self, _name):
        return self.value


class FakeWebJobService:
    def __init__(self):
        self.job = Job("d" * 32, {}, "hash", status="completed")
        self.payload = gzip.compress(b'{"durable":true}', mtime=0)

    def capabilities(self):
        return {"schema_version": 1, "execution_backend": "cloud-run-job"}

    def get(self, _job_id):
        return self.job

    def result(self, _job):
        return ResultStream(
            [self.payload],
            len(self.payload),
            {"Content-Encoding": "gzip"},
        )

    def cancel(self, _job_id):
        return self.job


class CloudJobTests(unittest.TestCase):
    def test_parameter_hash_includes_immutable_provenance(self):
        first = parameter_hash({"weight": 1}, {"engine_commit": "a"})
        same = parameter_hash({"weight": 1}, {"engine_commit": "a"})
        changed = parameter_hash({"weight": 1}, {"engine_commit": "b"})
        self.assertEqual(first, same)
        self.assertNotEqual(first, changed)

    def test_web_persists_before_launch_and_records_operation(self):
        repository = FakeRepository()
        launcher = FakeLauncher()
        service = CloudJobService(
            repository,
            FakeResultStore(),
            launcher,
            {"engine_commit": "commit", "data_manifest_hash": "manifest"},
        )
        job, cached = service.submit({"weight": 25})
        self.assertFalse(cached)
        self.assertEqual(launcher.launched, [job.id])
        self.assertEqual(repository.launch_operation, "operations/launch-1")

    def test_cloud_run_launcher_passes_only_the_durable_job_id_override(self):
        jobs = FakeRunClient()
        executions = FakeExecutionsClient()
        launcher = CloudRunJobLauncher(
            "projects/project/locations/region/jobs/calculation", jobs, executions
        )
        job_id = "f" * 32
        self.assertEqual(launcher.launch(job_id), "operations/run-1")
        self.assertEqual(jobs.request["name"], launcher.job_name)
        override = jobs.request["overrides"]["container_overrides"][0]
        self.assertEqual(override["name"], "worker")
        self.assertEqual(
            override["env"],
            [{"name": "KEEP_AND_LEASE_JOB_ID", "value": job_id}],
        )
        launcher.cancel("projects/project/locations/region/executions/execution-1")
        self.assertEqual(
            executions.request["name"],
            "projects/project/locations/region/executions/execution-1",
        )

    def test_launch_failure_is_a_durable_failed_job(self):
        repository = FakeRepository()
        service = CloudJobService(
            repository,
            FakeResultStore(),
            FakeLauncher(RuntimeError("quota exhausted")),
            {"engine_commit": "commit"},
        )
        job, cached = service.submit({})
        self.assertFalse(cached)
        self.assertEqual(job.status, "failed")
        self.assertIn("quota exhausted", job.error)

    def test_remote_cancellation_failure_is_persisted(self):
        provenance = {"engine_commit": "commit"}
        job = Job(
            "9" * 32,
            {},
            parameter_hash({}, provenance),
            status="running",
            execution_name="projects/p/locations/l/executions/e",
        )
        repository = FakeRepository(job)
        service = CloudJobService(
            repository,
            FakeResultStore(),
            FakeLauncher(RuntimeError("permission denied")),
            provenance,
        )
        cancelled = service.cancel(job.id)
        self.assertTrue(cancelled.cancellation_requested)
        self.assertIn("permission denied", repository.cancellation_error)
        self.assertEqual(cancelled.detail, repository.cancellation_error)

    def test_worker_executes_one_job_and_publishes_metrics(self):
        provenance = {"engine_commit": "commit", "data_manifest_hash": "manifest"}
        job = Job("b" * 32, {"weight": 25}, parameter_hash({"weight": 25}, provenance))
        repository = FakeRepository(job)
        results = FakeResultStore()
        runner = WorkerRunner(
            repository,
            results,
            FakeEngine(),
            heartbeat_seconds=0.01,
        )
        self.assertEqual(runner.run(job.id), 0)
        self.assertEqual(job.status, "completed")
        self.assertEqual(json.loads(results.encoded)["parameters"], {"weight": 25})
        self.assertEqual(results.metadata["parameter_hash"], job.parameter_hash)
        self.assertGreaterEqual(repository.completed[1], 0)
        self.assertIn("total", repository.completed[2])

    def test_interrupted_worker_persists_an_actionable_failure(self):
        job = Job("e" * 32, {}, "hash")
        repository = FakeRepository(job)
        runner = WorkerRunner(repository, FakeResultStore(), FakeEngine())
        runner.request_interruption()
        self.assertEqual(runner.run(job.id), 143)
        self.assertEqual(job.status, "failed")
        self.assertEqual(repository.failed[1]["stage"], "interrupted")
        self.assertIn("SIGTERM", repository.failed[0])

    def test_result_object_is_deterministic_gzip_and_create_only(self):
        client = FakeStorageClient()
        store = GcsResultStore(client, "results")
        encoded = b'{"ok":true}'
        stored = store.write("c" * 32, encoded, {"engine_commit": "commit"})
        blob = client.value.objects[f"jobs/{'c' * 32}/result.json.gz"]
        self.assertEqual(gzip.decompress(blob.payload), encoded)
        self.assertEqual(blob.kwargs["if_generation_match"], 0)
        self.assertEqual(blob.kwargs["checksum"], "crc32c")
        self.assertEqual(blob.kwargs["content_type"], "application/gzip")
        self.assertEqual(stored.result_checksum_sha256, hashlib.sha256(encoded).hexdigest())

    def test_cloud_result_stream_preserves_the_json_api_contract(self):
        client = TestClient(create_app(job_service=FakeWebJobService()))
        health = client.get("/api/v1/health")
        self.assertEqual(health.json()["execution_backend"], "cloud-run-job")
        self.assertIn("Multi-asset lease strategy", client.get("/").text)
        self.assertIn("Server-first calculation adapter", client.get("/backtest-worker-v13.js").text)
        self.assertEqual(client.get("/compute-config.json").json(), {"apiBaseUrl": ""})
        result = client.get(f"/api/v1/backtests/{'d' * 32}/result")
        self.assertEqual(result.json(), {"durable": True})
        inspection = client.post(
            "/api/v1/inspections",
            json={"schema_version": 1, "date": "2000-01-03", "parameters": {}},
        )
        self.assertEqual(inspection.status_code, 503)


if __name__ == "__main__":
    unittest.main()
