"""Versioned HTTP API for the canonical Keep & Lease Python calculation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .engine import StrategyEngine
from .jobs import JobStore


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    parameters: dict[str, Any] = Field(default_factory=dict)


class InspectionRequest(BacktestRequest):
    date: str


def create_app(engine: StrategyEngine | None = None) -> FastAPI:
    calculation_engine = engine or StrategyEngine()
    jobs = JobStore(calculation_engine)
    app = FastAPI(title="Keep & Lease computation API", version="1.0.0")
    app.state.engine = calculation_engine
    app.state.jobs = jobs

    allowed = [
        origin.strip()
        for origin in os.getenv("KEEP_AND_LEASE_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if allowed:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed,
            allow_origin_regex=os.getenv("KEEP_AND_LEASE_ALLOWED_ORIGIN_REGEX") or None,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["content-type"],
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", **calculation_engine.capabilities()}

    @app.post("/api/v1/backtests", status_code=status.HTTP_202_ACCEPTED)
    def create_backtest(request: BacktestRequest, response: Response) -> dict[str, Any]:
        if request.schema_version != 1:
            raise HTTPException(400, "Unsupported schema_version")
        import json
        encoded_size = len(json.dumps(request.parameters).encode("utf-8"))
        if encoded_size > 100_000:
            raise HTTPException(413, "Parameter document is too large")
        job, cached = jobs.submit(request.parameters)
        if cached:
            response.status_code = status.HTTP_200_OK
        return {
            **job.public(),
            "cached": cached,
            "status_url": f"/api/v1/backtests/{job.id}",
            "result_url": f"/api/v1/backtests/{job.id}/result",
        }

    @app.get("/api/v1/backtests/{job_id}")
    def backtest_status(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Unknown backtest job")
        return job.public()

    @app.get("/api/v1/backtests/{job_id}/result")
    def backtest_result(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Unknown backtest job")
        if job.status == "failed":
            raise HTTPException(422, job.error or "Backtest failed")
        if job.status == "cancelled":
            raise HTTPException(409, "Backtest was cancelled")
        if job.status != "completed" or job.result is None:
            raise HTTPException(409, "Backtest result is not ready")
        # Return the engine object unchanged so browser and server consumers see
        # precisely the same fields, plots, statistics, and inspection inputs.
        return job.result

    @app.delete("/api/v1/backtests/{job_id}")
    def cancel_backtest(job_id: str) -> dict[str, Any]:
        job = jobs.cancel(job_id)
        if not job:
            raise HTTPException(404, "Unknown backtest job")
        return job.public()

    @app.post("/api/v1/inspections")
    def inspect_day(request: InspectionRequest) -> dict[str, Any]:
        if request.schema_version != 1:
            raise HTTPException(400, "Unsupported schema_version")
        try:
            return calculation_engine.inspect_day(request.parameters, request.date)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return app


app = create_app()
