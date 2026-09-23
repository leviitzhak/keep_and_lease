"""Development and container entry point for the computation API."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import uvicorn


class DeferredApplication:
    """Bind Cloud Run before importing the full calculation application."""

    def __init__(self) -> None:
        self._application: Any | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _health() -> bytes:
        catalog = json.loads(os.getenv("KEEP_AND_LEASE_TRADE_CATALOG", "{}"))
        version = (Path(__file__).resolve().parent / "VERSION").read_text(
            encoding="utf-8"
        ).strip()
        payload = {
            "status": "ok",
            "schema_version": 1,
            "loaded": False,
            "execution_backend": (
                "cloud-run-job"
                if os.getenv("KEEP_AND_LEASE_JOB_BACKEND") == "cloud"
                else "in-process"
            ),
            "products": {},
            "trade_manifest_sha256": catalog.get("manifest_sha256", "unknown"),
            "application_version": version,
            "engine_commit": os.getenv("KEEP_AND_LEASE_ENGINE_COMMIT", "unknown"),
            "data_manifest_hash": os.getenv(
                "KEEP_AND_LEASE_DATA_MANIFEST_HASH", "unknown"
            ),
            "image_ref": os.getenv("KEEP_AND_LEASE_IMAGE_REF", "unknown"),
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    async def _load(self):
        if self._application is None:
            async with self._lock:
                if self._application is None:
                    from server.app import app as application
                    from server.replay_extensions import install as install_replay_extensions
                    from server.strategy_catalog import install as install_strategy_catalog

                    install_strategy_catalog(application)
                    install_replay_extensions(application)
                    self._application = application
        return self._application

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] == "http" and scope.get("path") == "/api/v1/health":
            body = self._health()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        application = await self._load()
        await application(scope, receive, send)


app = DeferredApplication()


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
