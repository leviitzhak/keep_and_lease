"""Load and execute the canonical strategy engine under ordinary CPython."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import silver_strategy_gui as gui

ProgressCallback = Callable[[str, str], None]


class StrategyEngine:
    """One read-only market snapshot shared by all server-side calculations."""

    def __init__(self, data_root: Path | None = None) -> None:
        configured_root = os.getenv("KEEP_AND_LEASE_DATA_ROOT")
        self.data_root = Path(configured_root) if configured_root else (
            data_root or Path(__file__).resolve().parents[1]
        )
        self._load_lock = threading.Lock()
        self._execution_lock = threading.Lock()
        self._loaded = False
        self._loaded_at: float | None = None
        self._provenance: dict[str, Any] | None = None

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self, progress: ProgressCallback | None = None) -> None:
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            notify = progress or (lambda _stage, _detail: None)
            notify("loading_data", f"Loading market histories from {self.data_root}")
            gui.MARKETS = gui.build_markets(self.data_root)
            if "silver" not in gui.MARKETS:
                detail = gui.MARKET_LOAD_ERRORS.get(
                    "silver", "canonical silver market data is unavailable"
                )
                raise ValueError(f"Unable to load the required silver market: {detail}")
            # Keep the legacy single-market alias synchronized without loading
            # the same histories a second time.
            gui.MARKET = gui.MARKETS["silver"]
            self._loaded = True
            self._loaded_at = time.time()
            notify("ready", "Calculation engine and market histories are ready")

    def run_backtest(
        self, parameters: dict[str, Any], progress: ProgressCallback | None = None,
        *, audit_collection=None,
    ) -> dict[str, Any]:
        notify = progress or (lambda _stage, _detail: None)
        self.load(notify)
        notify("running", "Running the requested backtest")
        with self._execution_lock:
            result = gui.result(parameters, audit_collection)
        notify("serializing", "Validating the complete result payload")
        return result

    def run_backtest_with_audit(self, parameters, audit_collection, progress=None):
        return self.run_backtest(parameters, progress, audit_collection=audit_collection)

    def inspect_day(
        self, parameters: dict[str, Any], requested_date: str
    ) -> dict[str, Any]:
        self.load()
        with self._execution_lock:
            return gui.inspection_for_day(parameters, requested_date)

    def provenance(self) -> dict[str, Any]:
        if self._provenance is not None:
            return dict(self._provenance)
        version_file = Path(__file__).resolve().parents[1] / "VERSION"
        version = version_file.read_text(encoding="utf-8").strip()
        configured_manifest = os.getenv("KEEP_AND_LEASE_DATA_MANIFEST_HASH")
        if configured_manifest:
            manifest_hash = configured_manifest
        else:
            from market_data_store import source_manifest_hash
            manifest_hash = source_manifest_hash(self.data_root)
        self._provenance = {
            "application_version": version,
            "engine_commit": os.getenv(
                "KEEP_AND_LEASE_ENGINE_COMMIT",
                os.getenv("RENDER_GIT_COMMIT", os.getenv("GITHUB_SHA", "unknown")),
            ),
            "data_manifest_hash": manifest_hash,
            "image_ref": os.getenv("KEEP_AND_LEASE_IMAGE_REF", "unknown"),
        }
        return dict(self._provenance)

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "loaded": self.loaded,
            "data_root": str(self.data_root),
            "products": gui.PRODUCTS,
            "market_load_errors": gui.MARKET_LOAD_ERRORS if self.loaded else {},
            **self.provenance(),
        }
