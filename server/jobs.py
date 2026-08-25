"""In-process job service retained for local development and compatibility tests."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
import uuid
from typing import Any

from .engine import StrategyEngine
from .job_models import FINAL_STATES, Job


class JobStore:
    def __init__(self, engine: StrategyEngine) -> None:
        self.engine = engine
        self._jobs: dict[str, Job] = {}
        self._completed_by_hash: dict[str, str] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

    def parameter_hash(
        self, parameters: dict[str, Any], owner_id: str | None = None
    ) -> str:
        provenance = (
            self.engine.provenance() if hasattr(self.engine, "provenance") else {}
        )
        encoded = json.dumps(
            {
                "schema_version": 1,
                "parameters": parameters,
                "provenance": provenance,
                **({"owner_id": owner_id} if owner_id else {}),
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def submit(
        self, parameters: dict[str, Any], owner_id: str | None = None
    ) -> tuple[Job, bool]:
        digest = self.parameter_hash(parameters, owner_id)
        with self._lock:
            cached_id = self._completed_by_hash.get(digest)
            if cached_id and cached_id in self._jobs:
                return self._jobs[cached_id], True
            provenance = (
                self.engine.provenance() if hasattr(self.engine, "provenance") else {}
            )
            job = Job(
                uuid.uuid4().hex,
                dict(parameters),
                digest,
                owner_id=owner_id,
                provenance=provenance,
            )
            job.logs.append({
                "at": job.created_at, "stage": job.stage, "detail": job.detail,
            })
            self._jobs[job.id] = job
            self._queue.put(job.id)
            return job, False

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest_completed(self, owner_id: str | None = None) -> Job | None:
        """Return the most recently completed in-process job, if any."""
        with self._lock:
            completed = [
                job for job in self._jobs.values()
                if job.status == "completed"
                and job.result is not None
                and job.owner_id == owner_id
            ]
            return max(
                completed,
                key=lambda job: job.completed_at or job.created_at,
                default=None,
            )

    def result(self, job: Job) -> dict[str, Any] | None:
        return job.result

    def cancel(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status in FINAL_STATES:
                return job
            job.cancellation_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.stage = "cancelled"
                job.detail = "Cancelled before calculation started"
                job.completed_at = time.time()
                job.logs.append({
                    "at": job.completed_at,
                    "stage": job.stage,
                    "detail": job.detail,
                })
            return job

    def _progress(self, job: Job, stage: str, detail: str) -> None:
        with self._lock:
            job.stage = stage
            job.detail = detail
            job.logs.append({"at": time.time(), "stage": stage, "detail": detail})

    def _work(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                job = self.get(job_id)
                if not job or job.status == "cancelled":
                    continue
                with self._lock:
                    job.status = "running"
                    job.stage = "starting"
                    job.detail = "Starting the server-side Python calculation"
                    job.started_at = time.time()
                    job.logs.append({
                        "at": job.started_at,
                        "stage": job.stage,
                        "detail": job.detail,
                    })
                result = self.engine.run_backtest(
                    job.parameters,
                    lambda stage, detail, current=job: self._progress(
                        current, stage, detail
                    ),
                )
                encoded = json.dumps(
                    result, allow_nan=False, separators=(",", ":")
                ).encode("utf-8")
                maximum = int(os.getenv(
                    "KEEP_AND_LEASE_MAX_RESULT_BYTES", str(100 * 1024 * 1024)
                ))
                if len(encoded) > maximum:
                    raise ValueError(f"Backtest result exceeds the {maximum}-byte server limit")
                with self._lock:
                    job.result_size_bytes = len(encoded)
                    job.completed_at = time.time()
                    if job.cancellation_requested:
                        job.status = "cancelled"
                        job.stage = "cancelled"
                        job.detail = "Cancellation requested while running; completed result discarded"
                    else:
                        job.result = result
                        job.status = "completed"
                        job.stage = "completed"
                        job.detail = "Backtest completed"
                        self._completed_by_hash[job.parameter_hash] = job.id
                    job.logs.append({
                        "at": job.completed_at,
                        "stage": job.stage,
                        "detail": job.detail,
                    })
            except Exception as exc:  # noqa: BLE001 - persist a stable API error.
                with self._lock:
                    job.status = "failed"
                    job.stage = "failed"
                    job.error = str(exc)
                    job.detail = str(exc)
                    job.completed_at = time.time()
                    job.logs.append({
                        "at": job.completed_at,
                        "stage": job.stage,
                        "detail": job.detail,
                    })
            finally:
                self._queue.task_done()
