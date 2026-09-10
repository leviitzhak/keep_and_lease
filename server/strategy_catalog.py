"""Read-only catalog of checked-in strategy parameter sets for the live GUI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "strategies"


def load_catalog() -> list[dict[str, Any]]:
    if not STRATEGY_DIR.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(p for p in STRATEGY_DIR.iterdir() if p.is_file() and not p.name.startswith(".")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("schema_version") != 1 or not isinstance(value.get("parameters"), dict):
            continue
        items.append({"name": path.stem if path.suffix == ".json" else path.name,
                      "parameters": value["parameters"]})
    return items


def install(app: FastAPI) -> None:
    if any(getattr(route, "path", None) == "/api/v1/strategies" for route in app.routes):
        return

    @app.get("/api/v1/strategies", include_in_schema=False)
    def strategy_catalog(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return {"strategies": load_catalog()}
        except OSError as exc:
            raise HTTPException(500, f"Unable to read checked-in strategies: {exc}") from None
