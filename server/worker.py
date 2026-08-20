"""Execute exactly one durable backtest job and then exit."""

from __future__ import annotations

import json
import os
import resource
import signal
import socket
import sys
import time
import uuid
from typing import Any

from .cloud import (
    CloudSettings,
    FirestoreJobRepository,
    GcsResultStore,
    Heartbeat,
)
from .engine import StrategyEngine


class CancellationRequested(Exception):
    pass


class WorkerInterrupted(Exception):
    pass


def peak_rss_mb() -> float:
    # Linux reports ru_maxrss in KiB; Cloud Run containers are Linux.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


class WorkerRunner:
    def __init__(
        self,
        repository: Any,
        results: Any,
        engine: Any,
        *,
        heartbeat_seconds: float = 15.0,
        maximum_result_bytes: int | None = None,
    ) -> None:
        self.repository = repository
        self.results = results
        self.engine = engine
        self.heartbeat_seconds = heartbeat_seconds
        self.maximum_result_bytes = maximum_result_bytes or int(
            os.getenv("KEEP_AND_LEASE_MAX_RESULT_BYTES", str(100 * 1024 * 1024))
        )
        self.interrupted = False

    def request_interruption(self) -> None:
        self.interrupted = True

    def run(self, job_id: str) -> int:
        execution_name = os.getenv("CLOUD_RUN_EXECUTION")
        lease_owner = execution_name or (
            f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        job = self.repository.claim(job_id, lease_owner, execution_name)
        if not job or job.status == "cancelled":
            return 0
        if job.status != "running" or job.lease_owner != lease_owner:
            raise RuntimeError("Backtest job is already claimed or is not runnable")

        started = time.monotonic()
        stage_started = started
        current_stage = "starting"
        timings: dict[str, float] = {}

        def close_stage(next_stage: str) -> None:
            nonlocal current_stage, stage_started
            now = time.monotonic()
            timings[current_stage] = timings.get(current_stage, 0.0) + (now - stage_started)
            current_stage = next_stage
            stage_started = now

        with Heartbeat(
            self.repository, job_id, lease_owner, self.heartbeat_seconds
        ) as heartbeat:
            def progress(stage: str, detail: str) -> None:
                if self.interrupted:
                    raise WorkerInterrupted("Cloud Run sent SIGTERM to the calculation worker")
                if heartbeat.cancel_requested.is_set():
                    raise CancellationRequested("Cancellation requested")
                close_stage(stage)
                self.repository.progress(job_id, lease_owner, stage, detail)

            try:
                provenance = self.engine.provenance()
                for key in (
                    "application_version",
                    "engine_commit",
                    "data_manifest_hash",
                    "image_ref",
                ):
                    expected = job.provenance.get(key)
                    actual = provenance.get(key)
                    if expected and expected != "unknown" and expected != actual:
                        raise ValueError(
                            f"Worker provenance mismatch for {key}: expected {expected}, got {actual}"
                        )
                result = self.engine.run_backtest(job.parameters, progress)
                close_stage("encoding_result")
                self.repository.progress(
                    job_id, lease_owner, "encoding_result", "Encoding the result as strict JSON"
                )
                encoded = json.dumps(
                    result, allow_nan=False, separators=(",", ":")
                ).encode("utf-8")
                if len(encoded) > self.maximum_result_bytes:
                    raise ValueError(
                        f"Backtest result exceeds the {self.maximum_result_bytes}-byte server limit"
                    )
                if heartbeat.cancel_requested.is_set():
                    raise CancellationRequested("Cancellation requested")

                close_stage("uploading_result")
                self.repository.progress(
                    job_id, lease_owner, "uploading_result", "Publishing the compressed result"
                )
                stored = self.results.write(
                    job_id,
                    encoded,
                    {
                        "engine_commit": str(provenance.get("engine_commit", "unknown")),
                        "data_manifest_hash": str(
                            provenance.get("data_manifest_hash", "unknown")
                        ),
                        "parameter_hash": job.parameter_hash,
                    },
                )
                if heartbeat.cancel_requested.is_set():
                    raise CancellationRequested("Cancellation requested")
                close_stage("completed")
                timings["total"] = time.monotonic() - started
                self.repository.complete(
                    job_id,
                    lease_owner,
                    stored,
                    peak_rss_mb(),
                    timings,
                    provenance,
                )
                return 0
            except CancellationRequested as exc:
                close_stage("cancelled")
                timings["total"] = time.monotonic() - started
                self.repository.mark_cancelled(job_id, str(exc))
                return 0
            except WorkerInterrupted as exc:
                close_stage("interrupted")
                timings["total"] = time.monotonic() - started
                current = self.repository.get(job_id)
                if current and current.cancellation_requested:
                    self.repository.mark_cancelled(job_id, "Calculation execution cancelled")
                    return 0
                self.repository.fail(
                    job_id,
                    str(exc),
                    stage="interrupted",
                    peak_rss_mb=peak_rss_mb(),
                    stage_timings=timings,
                )
                return 143
            except Exception as exc:  # noqa: BLE001 - persist every worker failure.
                close_stage("failed")
                timings["total"] = time.monotonic() - started
                self.repository.fail(
                    job_id,
                    str(exc),
                    peak_rss_mb=peak_rss_mb(),
                    stage_timings=timings,
                )
                return 1


def main() -> int:
    job_id = os.getenv("KEEP_AND_LEASE_JOB_ID", "")
    if not job_id:
        print("KEEP_AND_LEASE_JOB_ID is required", file=sys.stderr)
        return 2

    settings = CloudSettings.from_env()
    runner = WorkerRunner(
        FirestoreJobRepository.from_settings(settings),
        GcsResultStore.from_settings(settings),
        StrategyEngine(),
    )

    def interrupt(_signum: int, _frame: Any) -> None:
        runner.request_interruption()
        # Raising from the main-thread signal handler interrupts Python strategy
        # execution promptly enough to persist an actionable terminal state before
        # Cloud Run's shutdown grace period expires.
        raise WorkerInterrupted("Cloud Run sent SIGTERM to the calculation worker")

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    return runner.run(job_id)


if __name__ == "__main__":
    raise SystemExit(main())
