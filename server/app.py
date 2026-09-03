"""Versioned HTTP API for the canonical Keep & Lease Python calculation."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .engine import StrategyEngine
from .job_models import ResultStream
from .jobs import JobStore


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    parameters: dict[str, Any] = Field(default_factory=dict)


class InspectionRequest(BacktestRequest):
    date: str


def create_app(
    engine: StrategyEngine | None = None,
    job_service: Any | None = None,
) -> FastAPI:
    cloud_mode = os.getenv("KEEP_AND_LEASE_JOB_BACKEND", "local") == "cloud"
    calculation_engine = engine
    if job_service is None and cloud_mode:
        from .cloud import create_cloud_job_service

        job_service = create_cloud_job_service()
    if job_service is None:
        calculation_engine = calculation_engine or StrategyEngine()
        job_service = JobStore(calculation_engine)
    app = FastAPI(title="Keep & Lease computation API", version="1.0.0")
    app.state.engine = calculation_engine
    app.state.jobs = job_service
    default_web_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")
    web_root = os.getenv("KEEP_AND_LEASE_WEB_ROOT", default_web_root)

    allowed = [
        origin.strip()
        for origin in os.getenv("KEEP_AND_LEASE_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    allowed_regex = os.getenv("KEEP_AND_LEASE_ALLOWED_ORIGIN_REGEX") or None
    if allowed or allowed_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed,
            allow_origin_regex=allowed_regex,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["content-type"],
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        capabilities = (
            calculation_engine.capabilities()
            if calculation_engine is not None
            else job_service.capabilities()
        )
        return {"status": "ok", **capabilities}

    def static_file(name: str, media_type: str) -> FileResponse:
        path = os.path.join(web_root, name)
        if not os.path.isfile(path):
            raise HTTPException(404, "Web asset is not installed")
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/", include_in_schema=False)
    @app.get("/silver_strategy_gui.html", include_in_schema=False)
    def web_gui() -> FileResponse:
        return static_file("silver_strategy_gui.html", "text/html")

    @app.get("/backtest-worker-v13.js", include_in_schema=False)
    def browser_worker() -> FileResponse:
        return static_file("backtest-worker-v13.js", "text/javascript")

    @app.get("/fflate.js", include_in_schema=False)
    def spreadsheet_runtime() -> FileResponse:
        return static_file("fflate.js", "text/javascript")

    @app.get("/backtest-workbook-v1.js", include_in_schema=False)
    def spreadsheet_template_runtime() -> FileResponse:
        return static_file("backtest-workbook-v1.js", "text/javascript")

    @app.get("/build-info.json", include_in_schema=False)
    def build_info() -> dict[str, Any]:
        capabilities = (
            calculation_engine.capabilities()
            if calculation_engine is not None
            else job_service.capabilities()
        )
        return {
            "version": capabilities.get("application_version", "unknown"),
            "commit": capabilities.get("engine_commit", "unknown"),
        }

    @app.get("/compute-config.json", include_in_schema=False)
    def compute_config() -> dict[str, str]:
        return {"apiBaseUrl": ""}

    def requester_id(request: Request) -> str | None:
        raw = (
            request.headers.get("x-goog-authenticated-user-id")
            or request.headers.get("x-goog-authenticated-user-email")
        )
        return raw.strip().lower() if raw and raw.strip() else None

    def owned_job(job_id: str, request: Request) -> Any:
        job = job_service.get(job_id)
        if not job or job.owner_id != requester_id(request):
            raise HTTPException(404, "Unknown backtest job")
        return job

    @app.post("/api/v1/backtests", status_code=status.HTTP_202_ACCEPTED)
    def create_backtest(
        request: BacktestRequest, http_request: Request, response: Response
    ) -> dict[str, Any]:
        if request.schema_version != 1:
            raise HTTPException(400, "Unsupported schema_version")
        encoded_size = len(json.dumps(request.parameters).encode("utf-8"))
        if encoded_size > 100_000:
            raise HTTPException(413, "Parameter document is too large")
        job, cached = job_service.submit(
            request.parameters, requester_id(http_request)
        )
        if cached:
            response.status_code = status.HTTP_200_OK
        return {
            **job.public(),
            "cached": cached,
            "status_url": f"/api/v1/backtests/{job.id}",
            "result_url": f"/api/v1/backtests/{job.id}/result",
        }

    @app.get("/api/v1/backtests/latest")
    def latest_backtest(request: Request) -> Any:
        job = job_service.latest_completed(requester_id(request))
        if job is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return {
            **job.public(),
            "cached": True,
            "status_url": f"/api/v1/backtests/{job.id}",
            "result_url": f"/api/v1/backtests/{job.id}/result",
        }

    @app.get("/api/v1/backtests/{job_id}")
    def backtest_status(job_id: str, request: Request) -> dict[str, Any]:
        job = owned_job(job_id, request)
        return job.public()

    @app.get("/api/v1/backtests/{job_id}/result")
    def backtest_result(job_id: str, request: Request) -> Any:
        job = owned_job(job_id, request)
        if job.status == "failed":
            raise HTTPException(422, job.error or "Backtest failed")
        if job.status == "cancelled":
            raise HTTPException(409, "Backtest was cancelled")
        if job.status != "completed":
            raise HTTPException(409, "Backtest result is not ready")
        result = job_service.result(job)
        if result is None:
            raise HTTPException(409, "Backtest result is not ready")
        if isinstance(result, ResultStream):
            headers = dict(result.headers)
            # Do not set Content-Length for large result objects. Starlette then
            # uses chunked transfer encoding, avoiding Cloud Run's 32 MiB limit
            # for non-streaming HTTP/1 responses while preserving gzip streaming.
            return StreamingResponse(
                result.body,
                media_type=result.media_type,
                headers=headers,
            )
        # Return the engine object unchanged so browser and server consumers see
        # precisely the same fields, plots, statistics, and inspection inputs.
        return result

    @app.delete("/api/v1/backtests/{job_id}")
    def cancel_backtest(job_id: str, request: Request) -> dict[str, Any]:
        owned_job(job_id, request)
        job = job_service.cancel(job_id)
        if not job:
            raise HTTPException(404, "Unknown backtest job")
        return job.public()

    @app.post("/api/v1/inspections")
    def inspect_day(request: InspectionRequest) -> dict[str, Any]:
        if request.schema_version != 1:
            raise HTTPException(400, "Unsupported schema_version")
        if calculation_engine is None:
            raise HTTPException(
                503,
                "Day inspection is not yet available on the scale-to-zero web service; use a completed backtest result",
            )
        try:
            return calculation_engine.inspect_day(request.parameters, request.date)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return app


app = create_app()
