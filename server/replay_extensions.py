"""Cloud-only GUI/API wiring for extending a completed BTC trade replay."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

INTERNAL_PARENT_KEY = "__keep_and_lease_extension_parent_job_id"


def engine_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Return parameters visible to the strategy engine and saved result."""
    return {key: value for key, value in parameters.items()
            if not key.startswith("__keep_and_lease_")}


class ExtendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backtest_end: str


def _requester_id(request: Request) -> str | None:
    raw = (request.headers.get("x-goog-authenticated-user-id")
           or request.headers.get("x-goog-authenticated-user-email"))
    return raw.strip().lower() if raw and raw.strip() else None


def install(app) -> None:
    """Install the dedicated extension endpoint on the production API app."""
    if any(getattr(route, "path", None) == "/api/v1/backtests/{job_id}/extend"
           for route in app.routes):
        return

    @app.post("/api/v1/backtests/{job_id}/extend", include_in_schema=False)
    def extend_backtest(job_id: str, body: ExtendRequest, request: Request):
        service = app.state.jobs
        if not all(hasattr(service, name) for name in ("submit", "results", "provenance")):
            raise HTTPException(409, "Backtest extension requires the durable GCP worker")
        parent = service.get(job_id)
        owner = _requester_id(request)
        if not parent or parent.owner_id != owner:
            raise HTTPException(404, "Unknown backtest job")
        if parent.status != "completed" or parent.parameters.get("btc_data_source") != "trade_tape":
            raise HTTPException(409, "Only a completed BTC trade replay can be extended")
        if parent.provenance != service.provenance:
            raise HTTPException(409, "Extension requires the original deployed engine and data revision")
        if not hasattr(service.results, "checkpoint_store") or service.results.checkpoint_store(parent.id).latest() is None:
            raise HTTPException(
                409,
                "This completed replay has no durable checkpoint to extend from; start a fresh run with the later end",
            )

        from btc_trade_backtest import catalog, us_time, validate
        old_parameters = engine_parameters(parent.parameters)
        old_end = old_parameters.get("backtest_end") or catalog()["end"]
        try:
            if us_time(body.backtest_end) <= us_time(old_end):
                raise ValueError("The new end must be later than the completed run end")
            new_parameters = dict(old_parameters)
            new_parameters["backtest_end"] = body.backtest_end
            validate(new_parameters)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        new_parameters[INTERNAL_PARENT_KEY] = parent.id
        child, cached = service.submit(new_parameters, owner)
        return {
            **child.public(),
            "cached": cached,
            "extension_parent_job_id": parent.id,
            "status_url": f"/api/v1/backtests/{child.id}",
            "result_url": f"/api/v1/backtests/{child.id}/result",
        }


def seed_extension(job, repository, results, engine, audit, progress) -> dict[str, Any]:
    """Fork the parent's verified audit/checkpoint prefix into a child job once."""
    parent_id = job.parameters.get(INTERNAL_PARENT_KEY)
    parameters = engine_parameters(job.parameters)
    if not parent_id:
        return parameters
    if audit.checkpoints is None:
        raise ValueError("Replay extension requires durable checkpoints")
    if audit.checkpoints.latest() is not None:
        # A restarted child already owns its forked checkpoint; ordinary replay
        # recovery will continue from it without touching the parent again.
        return parameters

    parent = repository.get(parent_id)
    if (not parent or parent.owner_id != job.owner_id or parent.status != "completed"
            or parent.parameters.get("btc_data_source") != "trade_tape"):
        raise ValueError("Extension parent is unavailable or not owned by this run")
    if parent.provenance != job.provenance:
        raise ValueError("Extension parent engine or data revision differs")
    parent_checkpoint = results.checkpoint_store(parent.id).latest()
    if parent_checkpoint is None:
        raise ValueError("Extension parent has no durable checkpoint")

    from btc_trade_backtest import catalog
    from replay_extension import extend_checkpoint
    from trade_data_store import ParquetTradeStore

    trade_store = ParquetTradeStore(catalog()["uri"])
    progress("extension_seed", "Verifying parent checkpoint and audited prefix")
    extend_checkpoint(
        parent_checkpoint,
        engine_parameters(parent.parameters),
        parameters,
        trade_store.manifest_bytes,
        engine.data_root,
        results.audit_store(parent.id),
        audit.store,
        audit.checkpoints,
    )
    progress("extension_seed", "Verified parent prefix copied; continuing from durable checkpoint")
    return parameters
