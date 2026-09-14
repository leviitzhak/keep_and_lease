"""Shared durable job and result models for local and cloud execution."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

FINAL_STATES = {"completed", "failed", "cancelled"}


@dataclass
class Job:
    id: str
    parameters: dict[str, Any]
    parameter_hash: str
    owner_id: str | None = None
    status: str = "queued"
    stage: str = "queued"
    detail: str = "Waiting for the calculation worker"
    created_at: float = field(default_factory=time.time)
    queued_at: float | None = None
    started_at: float | None = None
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    cancellation_requested: bool = False
    result_size_bytes: int | None = None
    compressed_result_size_bytes: int | None = None
    result_uri: str | None = None
    result_checksum_sha256: str | None = None
    compressed_checksum_sha256: str | None = None
    execution_name: str | None = None
    launch_operation_name: str | None = None
    lease_owner: str | None = None
    heartbeat_at: float | None = None
    attempt: int = 0
    peak_rss_mb: float | None = None
    stage_timings_seconds: dict[str, float] = field(default_factory=dict)
    logs: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        now = self.completed_at or time.time()
        public_parameters = {
            key: value for key, value in self.parameters.items()
            if not key.startswith("__keep_and_lease_")
        }
        return {
            "job_id": self.id,
            "status": self.status,
            "stage": self.stage,
            "detail": self.detail,
            "parameter_hash": self.parameter_hash,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_seconds": max(0.0, now - (self.started_at or self.created_at)),
            "error": self.error,
            "cancellation_requested": self.cancellation_requested,
            "result_size_bytes": self.result_size_bytes,
            "compressed_result_size_bytes": self.compressed_result_size_bytes,
            "result_uri": self.result_uri,
            "result_checksum_sha256": self.result_checksum_sha256,
            "execution_name": self.execution_name,
            "heartbeat_at": self.heartbeat_at,
            "attempt": self.attempt,
            "peak_rss_mb": self.peak_rss_mb,
            "stage_timings_seconds": dict(self.stage_timings_seconds),
            "parameters": public_parameters,
            "provenance": self.provenance,
            "logs": list(self.logs),
        }


@dataclass(frozen=True)
class ResultStream:
    """A streamed HTTP result returned by the durable object-store adapter."""

    body: Iterable[bytes]
    content_length: int | None
    headers: dict[str, str] = field(default_factory=dict)
    media_type: str = "application/json"


@dataclass(frozen=True)
class StoredResult:
    uri: str
    result_size_bytes: int
    compressed_size_bytes: int
    result_checksum_sha256: str
    compressed_checksum_sha256: str


def history_page(jobs, owner_id, limit=50, before=None):
    """Stable newest-first pages, including tied creation times and all states."""
    boundary = (before.created_at, before.id) if before else None
    return sorted(
        (job for job in jobs if job.owner_id == owner_id
         and (boundary is None or (job.created_at, job.id) < boundary)),
        key=lambda job: (job.created_at, job.id), reverse=True,
    )[:limit]
