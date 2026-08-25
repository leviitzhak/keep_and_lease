"""Google Cloud durable job, result, and Cloud Run execution adapters."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Self

from .job_models import FINAL_STATES, Job, ResultStream, StoredResult

JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MAX_LOG_ENTRIES = 100


def _require_job_id(job_id: str) -> str:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("Invalid backtest job ID")
    return job_id


def runtime_provenance() -> dict[str, Any]:
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip()
    return {
        "application_version": version,
        "engine_commit": os.getenv(
            "KEEP_AND_LEASE_ENGINE_COMMIT", os.getenv("GITHUB_SHA", "unknown")
        ),
        "data_manifest_hash": os.getenv(
            "KEEP_AND_LEASE_DATA_MANIFEST_HASH", "unknown"
        ),
        "image_ref": os.getenv(
            "KEEP_AND_LEASE_WORKER_IMAGE_REF",
            os.getenv("KEEP_AND_LEASE_IMAGE_REF", "unknown"),
        ),
    }


def parameter_hash(
    parameters: dict[str, Any],
    provenance: dict[str, Any],
    owner_id: str | None = None,
) -> str:
    encoded = json.dumps(
        {
            "schema_version": 1,
            "parameters": parameters,
            "provenance": provenance,
            **({"owner_id": owner_id} if owner_id else {}),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CloudSettings:
    project_id: str
    region: str
    job_name: str
    results_bucket: str
    firestore_collection: str = "backtests"
    cache_collection: str = "backtest_cache"

    @classmethod
    def from_env(cls) -> CloudSettings:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        region = os.getenv("KEEP_AND_LEASE_GCP_REGION")
        job_name = os.getenv("KEEP_AND_LEASE_CLOUD_RUN_JOB")
        results_bucket = os.getenv("KEEP_AND_LEASE_RESULTS_BUCKET")
        missing = [
            name
            for name, value in (
                ("GOOGLE_CLOUD_PROJECT", project_id),
                ("KEEP_AND_LEASE_GCP_REGION", region),
                ("KEEP_AND_LEASE_CLOUD_RUN_JOB", job_name),
                ("KEEP_AND_LEASE_RESULTS_BUCKET", results_bucket),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing cloud configuration: {', '.join(missing)}")
        full_job_name = (
            job_name
            if str(job_name).startswith("projects/")
            else f"projects/{project_id}/locations/{region}/jobs/{job_name}"
        )
        return cls(
            project_id=str(project_id),
            region=str(region),
            job_name=full_job_name,
            results_bucket=str(results_bucket),
            firestore_collection=os.getenv(
                "KEEP_AND_LEASE_FIRESTORE_COLLECTION", "backtests"
            ),
            cache_collection=os.getenv(
                "KEEP_AND_LEASE_FIRESTORE_CACHE_COLLECTION", "backtest_cache"
            ),
        )


def _job_from_document(job_id: str, value: dict[str, Any]) -> Job:
    fields = {
        name: value[name]
        for name in Job.__dataclass_fields__
        if name != "id" and name in value
    }
    return Job(id=job_id, **fields)


class FirestoreJobRepository:
    """Transactional job state with a parameter-hash cache pointer."""

    def __init__(
        self,
        client: Any,
        collection: str = "backtests",
        cache_collection: str = "backtest_cache",
    ) -> None:
        self.client = client
        self.jobs = client.collection(collection)
        self.cache = client.collection(cache_collection)

    @classmethod
    def from_settings(cls, settings: CloudSettings) -> FirestoreJobRepository:
        from google.cloud import firestore

        return cls(
            firestore.Client(project=settings.project_id),
            settings.firestore_collection,
            settings.cache_collection,
        )

    @staticmethod
    def _document(job: Job) -> dict[str, Any]:
        value = asdict(job)
        value.pop("id", None)
        value.pop("result", None)
        return value

    def submit(
        self,
        parameters: dict[str, Any],
        provenance: dict[str, Any],
        owner_id: str | None = None,
    ) -> tuple[Job, bool, bool]:
        from google.cloud import firestore

        digest = parameter_hash(parameters, provenance, owner_id)
        cache_ref = self.cache.document(digest)
        transaction = self.client.transaction()

        @firestore.transactional
        def create_or_reuse(txn: Any) -> tuple[Job, bool, bool]:
            cache_snapshot = cache_ref.get(transaction=txn)
            if cache_snapshot.exists:
                cached_job_id = cache_snapshot.to_dict().get("job_id")
                if cached_job_id:
                    cached_ref = self.jobs.document(cached_job_id)
                    cached_snapshot = cached_ref.get(transaction=txn)
                    if cached_snapshot.exists:
                        cached_job = _job_from_document(
                            cached_job_id, cached_snapshot.to_dict()
                        )
                        if cached_job.status in {"queued", "running", "completed"}:
                            return cached_job, cached_job.status == "completed", False

            job = Job(
                id=uuid.uuid4().hex,
                parameters=dict(parameters),
                parameter_hash=digest,
                owner_id=owner_id,
                provenance=dict(provenance),
            )
            job.logs.append(
                {"at": job.created_at, "stage": job.stage, "detail": job.detail}
            )
            txn.create(self.jobs.document(job.id), self._document(job))
            txn.set(
                cache_ref,
                {"job_id": job.id, "parameter_hash": digest, "updated_at": time.time()},
            )
            return job, False, True

        return create_or_reuse(transaction)

    def get(self, job_id: str) -> Job | None:
        snapshot = self.jobs.document(_require_job_id(job_id)).get()
        if not snapshot.exists:
            return None
        return _job_from_document(job_id, snapshot.to_dict())

    def latest_completed(self, owner_id: str | None = None) -> Job | None:
        """Find the newest durable result without requiring a composite index."""
        latest = None
        for snapshot in self.jobs.where("status", "==", "completed").stream():
            value = snapshot.to_dict()
            if value.get("status") != "completed" or not value.get("result_uri"):
                continue
            job = _job_from_document(snapshot.id, value)
            if job.owner_id != owner_id:
                continue
            if latest is None or (
                job.completed_at or job.created_at
            ) > (latest.completed_at or latest.created_at):
                latest = job
        return latest

    def _transition(
        self,
        job_id: str,
        mutate: Callable[[Job], bool],
    ) -> Job | None:
        from google.cloud import firestore

        job_ref = self.jobs.document(_require_job_id(job_id))
        transaction = self.client.transaction()

        @firestore.transactional
        def update(txn: Any) -> Job | None:
            snapshot = job_ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            job = _job_from_document(job_id, snapshot.to_dict())
            if mutate(job):
                txn.set(job_ref, self._document(job))
            return job

        return update(transaction)

    @staticmethod
    def _append_log(job: Job, at: float | None = None) -> None:
        job.logs.append(
            {"at": at or time.time(), "stage": job.stage, "detail": job.detail}
        )
        job.logs = job.logs[-MAX_LOG_ENTRIES:]

    def record_launch(self, job_id: str, operation_name: str | None) -> Job | None:
        def mutate(job: Job) -> bool:
            if job.status != "queued":
                return False
            job.launch_operation_name = operation_name
            job.detail = "Calculation Job execution requested"
            self._append_log(job)
            return True

        return self._transition(job_id, mutate)

    def claim(
        self, job_id: str, lease_owner: str, execution_name: str | None
    ) -> Job | None:
        now = time.time()

        def mutate(job: Job) -> bool:
            if job.status == "cancelled" or job.cancellation_requested:
                if job.status not in FINAL_STATES:
                    job.status = "cancelled"
                    job.stage = "cancelled"
                    job.detail = "Cancelled before calculation started"
                    job.completed_at = now
                    self._append_log(job, now)
                    return True
                return False
            if job.status != "queued":
                return False
            job.status = "running"
            job.stage = "starting"
            job.detail = "Starting the server-side Python calculation"
            job.started_at = now
            job.heartbeat_at = now
            job.lease_owner = lease_owner
            job.execution_name = execution_name
            job.attempt += 1
            self._append_log(job, now)
            return True

        return self._transition(job_id, mutate)

    def progress(
        self, job_id: str, lease_owner: str, stage: str, detail: str
    ) -> Job | None:
        now = time.time()

        def mutate(job: Job) -> bool:
            if job.status != "running" or job.lease_owner != lease_owner:
                return False
            job.stage = stage
            job.detail = detail
            job.heartbeat_at = now
            self._append_log(job, now)
            return True

        return self._transition(job_id, mutate)

    def heartbeat(self, job_id: str, lease_owner: str) -> bool:
        now = time.time()

        def mutate(job: Job) -> bool:
            if job.status != "running" or job.lease_owner != lease_owner:
                return False
            job.heartbeat_at = now
            return True

        job = self._transition(job_id, mutate)
        return bool(job and job.status == "running" and job.lease_owner == lease_owner)

    def request_cancel(self, job_id: str) -> Job | None:
        now = time.time()

        def mutate(job: Job) -> bool:
            if job.status in FINAL_STATES:
                return False
            job.cancellation_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.stage = "cancelled"
                job.detail = "Cancelled before calculation started"
                job.completed_at = now
            else:
                job.detail = "Cancellation requested"
            self._append_log(job, now)
            return True

        return self._transition(job_id, mutate)

    def mark_cancelled(self, job_id: str, detail: str) -> Job | None:
        now = time.time()

        def mutate(job: Job) -> bool:
            if job.status in FINAL_STATES:
                return False
            job.status = "cancelled"
            job.stage = "cancelled"
            job.detail = detail
            job.cancellation_requested = True
            job.completed_at = now
            job.heartbeat_at = now
            self._append_log(job, now)
            return True

        return self._transition(job_id, mutate)

    def record_cancellation_error(self, job_id: str, detail: str) -> Job | None:
        """Keep a failed remote-cancel attempt visible without losing the request."""

        def mutate(job: Job) -> bool:
            if job.status in FINAL_STATES or not job.cancellation_requested:
                return False
            job.detail = detail
            self._append_log(job)
            return True

        return self._transition(job_id, mutate)

    def complete(
        self,
        job_id: str,
        lease_owner: str,
        stored: StoredResult,
        peak_rss_mb: float,
        stage_timings: dict[str, float],
        provenance: dict[str, Any],
    ) -> Job | None:
        now = time.time()

        def mutate(job: Job) -> bool:
            if job.status != "running" or job.lease_owner != lease_owner:
                return False
            if job.cancellation_requested:
                job.status = "cancelled"
                job.stage = "cancelled"
                job.detail = "Cancellation requested while running; result discarded"
            else:
                job.status = "completed"
                job.stage = "completed"
                job.detail = "Backtest completed"
                job.result_uri = stored.uri
                job.result_size_bytes = stored.result_size_bytes
                job.compressed_result_size_bytes = stored.compressed_size_bytes
                job.result_checksum_sha256 = stored.result_checksum_sha256
                job.compressed_checksum_sha256 = stored.compressed_checksum_sha256
                job.provenance = dict(provenance)
            job.completed_at = now
            job.heartbeat_at = now
            job.peak_rss_mb = peak_rss_mb
            job.stage_timings_seconds = dict(stage_timings)
            self._append_log(job, now)
            return True

        return self._transition(job_id, mutate)

    def fail(
        self,
        job_id: str,
        detail: str,
        *,
        stage: str = "failed",
        peak_rss_mb: float | None = None,
        stage_timings: dict[str, float] | None = None,
    ) -> Job | None:
        now = time.time()

        def mutate(job: Job) -> bool:
            if job.status in FINAL_STATES:
                return False
            job.status = "failed"
            job.stage = stage
            job.detail = detail
            job.error = detail
            job.completed_at = now
            job.heartbeat_at = now
            job.peak_rss_mb = peak_rss_mb
            job.stage_timings_seconds = dict(stage_timings or {})
            self._append_log(job, now)
            return True

        return self._transition(job_id, mutate)

    def fail_if_stale(
        self,
        job_id: str,
        *,
        queued_timeout_seconds: float,
        heartbeat_timeout_seconds: float,
    ) -> Job | None:
        now = time.time()

        def mutate(job: Job) -> bool:
            queued_stale = (
                job.status == "queued"
                and now - job.created_at > queued_timeout_seconds
            )
            running_stale = (
                job.status == "running"
                and job.heartbeat_at is not None
                and now - job.heartbeat_at > heartbeat_timeout_seconds
            )
            if not (queued_stale or running_stale):
                return False
            job.status = "failed"
            job.stage = "worker_lost"
            job.detail = (
                "Calculation worker did not start before its durable lease expired"
                if queued_stale
                else "Calculation worker heartbeat expired"
            )
            job.error = job.detail
            job.completed_at = now
            self._append_log(job, now)
            return True

        return self._transition(job_id, mutate)


class CloudRunJobLauncher:
    def __init__(self, job_name: str, jobs_client: Any, executions_client: Any) -> None:
        self.job_name = job_name
        self.jobs_client = jobs_client
        self.executions_client = executions_client

    @classmethod
    def from_settings(cls, settings: CloudSettings) -> CloudRunJobLauncher:
        from google.cloud import run_v2

        return cls(settings.job_name, run_v2.JobsClient(), run_v2.ExecutionsClient())

    def launch(self, job_id: str) -> str | None:
        _require_job_id(job_id)
        operation = self.jobs_client.run_job(
            request={
                "name": self.job_name,
                "overrides": {
                    "container_overrides": [
                        {
                            "name": "worker",
                            "env": [
                                {
                                    "name": "KEEP_AND_LEASE_JOB_ID",
                                    "value": job_id,
                                }
                            ],
                        }
                    ]
                },
            }
        )
        raw_operation = getattr(operation, "operation", None)
        return getattr(raw_operation, "name", None)

    def cancel(self, execution_name: str | None) -> None:
        if execution_name:
            self.executions_client.cancel_execution(request={"name": execution_name})


class GcsResultStore:
    def __init__(self, client: Any, bucket_name: str) -> None:
        self.client = client
        self.bucket_name = bucket_name
        self.bucket = client.bucket(bucket_name)

    @classmethod
    def from_settings(cls, settings: CloudSettings) -> GcsResultStore:
        from google.cloud import storage

        return cls(storage.Client(project=settings.project_id), settings.results_bucket)

    def write(
        self, job_id: str, encoded_result: bytes, metadata: dict[str, str]
    ) -> StoredResult:
        _require_job_id(job_id)
        compressed = gzip.compress(encoded_result, compresslevel=6, mtime=0)
        result_sha = hashlib.sha256(encoded_result).hexdigest()
        compressed_sha = hashlib.sha256(compressed).hexdigest()
        object_name = f"jobs/{job_id}/result.json.gz"
        blob = self.bucket.blob(object_name)
        blob.cache_control = "private, no-store"
        blob.metadata = {
            **metadata,
            "original_content_type": "application/json",
            "result_sha256": result_sha,
            "compressed_sha256": compressed_sha,
        }
        blob.upload_from_string(
            compressed,
            content_type="application/gzip",
            if_generation_match=0,
            checksum="crc32c",
        )
        return StoredResult(
            uri=f"gs://{self.bucket_name}/{object_name}",
            result_size_bytes=len(encoded_result),
            compressed_size_bytes=len(compressed),
            result_checksum_sha256=result_sha,
            compressed_checksum_sha256=compressed_sha,
        )

    def open(self, job: Job) -> ResultStream:
        prefix = f"gs://{self.bucket_name}/"
        if not job.result_uri or not job.result_uri.startswith(prefix):
            raise ValueError("Job result does not belong to the configured result bucket")
        object_name = job.result_uri[len(prefix):]
        expected = f"jobs/{_require_job_id(job.id)}/result.json.gz"
        if object_name != expected:
            raise ValueError("Job result object path is invalid")
        blob = self.bucket.blob(object_name)
        blob.reload()

        def chunks() -> Any:
            with blob.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    yield chunk

        headers = {
            "Content-Encoding": "gzip",
            "Cache-Control": "private, no-store",
        }
        if job.result_checksum_sha256:
            headers["X-Content-SHA256"] = job.result_checksum_sha256
        return ResultStream(chunks(), blob.size, headers)


class CloudJobService:
    """Web-facing orchestrator: persist first, launch second, and never calculate."""

    def __init__(
        self,
        repository: FirestoreJobRepository,
        results: GcsResultStore,
        launcher: CloudRunJobLauncher,
        provenance: dict[str, Any] | None = None,
        queued_timeout_seconds: float | None = None,
        heartbeat_timeout_seconds: float | None = None,
    ) -> None:
        self.repository = repository
        self.results = results
        self.launcher = launcher
        self.provenance = provenance or runtime_provenance()
        self.queued_timeout_seconds = queued_timeout_seconds or float(
            os.getenv("KEEP_AND_LEASE_QUEUED_TIMEOUT_SECONDS", "900")
        )
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds or float(
            os.getenv("KEEP_AND_LEASE_HEARTBEAT_TIMEOUT_SECONDS", "120")
        )

    def submit(
        self, parameters: dict[str, Any], owner_id: str | None = None
    ) -> tuple[Job, bool]:
        job, cached, should_launch = self.repository.submit(
            parameters, self.provenance, owner_id
        )
        if not should_launch and job.status in {"queued", "running"}:
            job = self._reconcile(job) or job
            if job.status == "failed":
                job, cached, should_launch = self.repository.submit(
                    parameters, self.provenance, owner_id
                )
        if should_launch:
            try:
                operation_name = self.launcher.launch(job.id)
                job = self.repository.record_launch(job.id, operation_name) or job
            except Exception as exc:  # noqa: BLE001 - persist cloud client failures.
                job = self.repository.fail(
                    job.id, f"Unable to start calculation Job: {exc}", stage="launch_failed"
                ) or job
        return job, cached

    def get(self, job_id: str) -> Job | None:
        job = self.repository.get(job_id)
        return self._reconcile(job) if job else None

    def latest_completed(self, owner_id: str | None = None) -> Job | None:
        return self.repository.latest_completed(owner_id)

    def _reconcile(self, job: Job) -> Job | None:
        if job.status not in {"queued", "running"}:
            return job
        return self.repository.fail_if_stale(
            job.id,
            queued_timeout_seconds=self.queued_timeout_seconds,
            heartbeat_timeout_seconds=self.heartbeat_timeout_seconds,
        )

    def result(self, job: Job) -> ResultStream:
        return self.results.open(job)

    def cancel(self, job_id: str) -> Job | None:
        job = self.repository.request_cancel(job_id)
        if not job or job.status in {"completed", "failed"}:
            return job
        if job.execution_name:
            try:
                self.launcher.cancel(job.execution_name)
                job = self.repository.mark_cancelled(
                    job.id, "Cloud Run calculation execution cancelled"
                ) or job
            except Exception as exc:  # noqa: BLE001 - preserve the durable request.
                detail = f"Cancellation requested; remote cancellation failed: {exc}"
                job = self.repository.record_cancellation_error(job.id, detail) or job
        return job

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "loaded": False,
            "execution_backend": "cloud-run-job",
            "products": {},
            **self.provenance,
        }


def create_cloud_job_service(settings: CloudSettings | None = None) -> CloudJobService:
    resolved = settings or CloudSettings.from_env()
    return CloudJobService(
        FirestoreJobRepository.from_settings(resolved),
        GcsResultStore.from_settings(resolved),
        CloudRunJobLauncher.from_settings(resolved),
    )


class Heartbeat:
    def __init__(
        self,
        repository: FirestoreJobRepository,
        job_id: str,
        lease_owner: str,
        interval_seconds: float,
    ) -> None:
        self.repository = repository
        self.job_id = job_id
        self.lease_owner = lease_owner
        self.interval_seconds = interval_seconds
        self.cancel_requested = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval_seconds + 1)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            job = self.repository.get(self.job_id)
            if not job or job.status != "running":
                return
            if job.cancellation_requested:
                self.cancel_requested.set()
            if not self.repository.heartbeat(self.job_id, self.lease_owner):
                return
