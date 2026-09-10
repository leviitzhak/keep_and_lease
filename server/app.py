"""Versioned HTTP API for the canonical Keep & Lease Python calculation."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
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
    benchmark_service: Any | None = None,
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
    export_slots = threading.BoundedSemaphore(2)
    def benchmarks():
        nonlocal benchmark_service
        if benchmark_service is None:
            if not cloud_mode:
                raise HTTPException(404, "Published benchmarks require the GCP server")
            from google.cloud import storage
            from .benchmarks import BenchmarkService, BUCKET
            benchmark_service = BenchmarkService(storage.Client().bucket(BUCKET))
        return benchmark_service

    def benchmark_data(policy):
        from .benchmarks import RUNS
        if policy not in RUNS:
            raise HTTPException(404, "Unknown published benchmark")
        try:
            return benchmarks().load(policy)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(409, "Stored benchmark could not be loaded: " + str(exc)) from None

    @app.get("/api/v1/benchmarks")
    def benchmark_history(response: Response):
        from .benchmarks import catalog
        response.headers["Cache-Control"] = "private, no-store"
        return {"jobs": catalog() if cloud_mode or benchmark_service is not None else []}

    @app.get("/api/v1/benchmarks/{policy}/result")
    def benchmark_result(policy: str, response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        return benchmark_data(policy)[0]
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

    @app.get("/backtest-runs.js", include_in_schema=False)
    def backtest_runs_runtime() -> FileResponse:
        return static_file("backtest-runs.js", "text/javascript")

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
    def compute_config() -> dict[str, Any]:
        # The web image serves the server adapter, not the Pyodide runtime/data.
        return {"apiBaseUrl": "", "browserFallback": False}

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
        from btc_trade_backtest import validate
        try:
            validate(request.parameters)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
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

    @app.get("/api/v1/trade-data")
    def trade_data():
        from btc_trade_backtest import catalog
        return {"datasets": [catalog()]}

    @app.get("/api/v1/backtests")
    def backtest_history(request: Request, response: Response, limit: int = Query(50, ge=1, le=100),
                         before: str | None = Query(None, pattern="^[0-9a-f]{32}$")):
        response.headers["Cache-Control"] = "private, no-store"
        cursor = owned_job(before, request) if before else None
        jobs = job_service.list_jobs(requester_id(request), limit + 1, cursor)
        items = []
        for job in jobs[:limit]:
            item = job.public()
            # Full logs/provenance remain available on the selected job endpoint.
            for key in ("logs", "provenance", "result_uri", "execution_name"):
                item.pop(key, None)
            items.append(item)
        return {"jobs": items,
                "next_cursor": jobs[limit - 1].id if len(jobs) > limit else None}

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

    @app.post("/api/v1/backtests/{job_id}/resume")
    def resume_backtest(job_id: str, request: Request):
        job = owned_job(job_id, request)
        if not hasattr(job_service, "resume"):
            raise HTTPException(409, "Resume requires the durable GCP worker")
        try:
            job = job_service.resume(job)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {**job.public(), "status_url": f"/api/v1/backtests/{job_id}",
                "result_url": f"/api/v1/backtests/{job_id}/result"}

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

    def completed_audit(job_id, request):
        from backtest_audit import load_manifest
        if request.url.path.startswith("/api/v1/benchmarks/"):
            _, manifest = benchmark_data(job_id)
            return benchmarks().audit_store(job_id), manifest
        job = owned_job(job_id, request)
        if job.status != "completed":
            raise HTTPException(409, "Backtest audit is not ready")
        try:
            store = job_service.audit_store(job)
            return store, load_manifest(store)
        except (KeyError, FileNotFoundError, AttributeError):
            raise HTTPException(404, "No stored audit for this job") from None

    @app.get("/api/v1/backtests/{job_id}/audit")
    @app.get("/api/v1/benchmarks/{job_id}/audit")
    def audit_manifest(job_id: str, request: Request):
        return completed_audit(job_id, request)[1]

    @app.get("/api/v1/backtests/{job_id}/audit/{product}/{index}")
    @app.get("/api/v1/benchmarks/{job_id}/audit/{product}/{index}")
    def audit_chunk(job_id: str, product: str, index: int, request: Request, section: str = "raw"):
        from backtest_audit import read_chunk, project_row
        store, manifest = completed_audit(job_id, request)
        entries = manifest["datasets"].get(product, {}).get("chunks", [])
        if index < 0 or index >= len(entries) or entries[index]["index"] != index:
            raise HTTPException(404, "Unknown audit chunk")
        if section not in ("raw", "spreadsheet", "rate_change"):
            raise HTTPException(400, "Unknown audit section")
        # Fully validate one bounded chunk before returning any of its records.
        rows = [project_row(row, product, section) for row in read_chunk(store, entries[index])]
        if section == "rate_change":
            rows = [point for group in rows for point in group]
        return {"product": product, "index": index, "rows": rows,
                "sha256": entries[index]["sha256"]}

    @app.get("/api/v1/backtests/{job_id}/audit-download/{product}")
    @app.get("/api/v1/benchmarks/{job_id}/audit-download/{product}")
    def audit_download(job_id: str, product: str, request: Request):
        import hashlib
        store, manifest = completed_audit(job_id, request)
        dataset = manifest["datasets"].get(product)
        if dataset is None:
            raise HTTPException(404, "Unknown audit dataset")
        def chunks():
            for entry in dataset["chunks"]:
                data = store.get(entry["object"])
                if hashlib.sha256(data).hexdigest() != entry["compressed_sha256"]:
                    raise ValueError("Audit checksum mismatch")
                yield data
        # Concatenated gzip members are a single valid, lossless JSONL gzip file.
        return StreamingResponse(chunks(), media_type="application/gzip", headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="{product}-full-audit.jsonl.gz"'})

    @app.get("/api/v1/backtests/{job_id}/trade-valuations.csv")
    @app.get("/api/v1/benchmarks/{job_id}/trade-valuations.csv")
    def trade_valuations_csv(job_id: str, request: Request):
        import csv
        import io
        from backtest_audit import read_chunk
        store, manifest = completed_audit(job_id, request)
        dataset = manifest["datasets"].get("btc_trade_valuations")
        if dataset is None:
            raise HTTPException(404, "No trade replay valuations for this run")
        fields = ["date", "us", "nav_usd", "cash_usd", "direct_nav", "futures_notional_usd",
                  "fees_usd", "return_fraction", "reconstruction_error_usd", "units", "targets", "mark_us", "mark_ids"]
        def output():
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(fields)
            yield buffer.getvalue()
            for entry in dataset["chunks"]:
                for row in read_chunk(store, entry):
                    buffer.seek(0)
                    buffer.truncate(0)
                    writer.writerow([json.dumps(row.get(f), separators=(",", ":"))
                                     if isinstance(row.get(f), dict) else row.get(f) for f in fields])
                    yield buffer.getvalue()
        return StreamingResponse(output(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="btc-trade-valuations.csv"',
            "Cache-Control": "private, no-store"})

    @app.get("/api/v1/backtests/{job_id}/audit-download")
    @app.get("/api/v1/benchmarks/{job_id}/audit-download")
    def audit_archive(job_id: str, request: Request):
        from backtest_audit import archive_chunks
        store, manifest = completed_audit(job_id, request)
        return StreamingResponse(archive_chunks(store, manifest), media_type="application/zip", headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="keep-and-lease-full-audit.zip"'})

    @app.get("/api/v1/backtests/{job_id}/spreadsheet")
    @app.get("/api/v1/benchmarks/{job_id}/spreadsheet")
    def trade_spreadsheet(job_id: str, request: Request, start: str, end: str):
        from .replay_exports import period, replay_workbook
        store, manifest = completed_audit(job_id, request)
        if request.url.path.startswith("/api/v1/benchmarks/"):
            result = benchmark_data(job_id)[0]
        else:
            job = owned_job(job_id, request)
            entries = manifest["datasets"].get("btc_trade_valuations", {}).get("chunks", [])
            if not entries:
                raise HTTPException(404, "No trade replay valuations for this run")
            result = {"parameters": job.parameters, "summary": {"start": entries[0]["start"], "end": entries[-1]["end"]},
                      "trade_replay": {"capital_usd": float(job.parameters.get("trade_initial_capital_usd", 100000))}}
        try:
            start, end = period(start, end, result["summary"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Choose an increasing UTC period inside the completed backtest") from None
        if not export_slots.acquire(blocking=False):
            raise HTTPException(429, "Two spreadsheets are already generating on this server; retry shortly")
        def output():
            try:
                yield from replay_workbook(store, manifest, result, start, end)
            finally:
                export_slots.release()
        return StreamingResponse(output(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Cache-Control": "private, no-store",
                     "Content-Disposition": 'attachment; filename="btc-replay-' + start.replace(':','-') + '-to-' + end.replace(':','-') + '.xlsx"'})

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
