#!/usr/bin/env python3
"""Run bounded authenticated checks against the private Keep & Lease service."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ALLOWED_ACTIONS = {"health", "gui", "backtest"}
SMOKE_FIXTURES: dict[str, dict[str, Any]] = {
    "silver-default": {"weight_silver": 100},
}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MAX_PARAMETER_BYTES = 100_000
MAX_RESULT_BYTES = 50 * 1024 * 1024
MIN_POLL_SECONDS = 2
MAX_POLL_SECONDS = 30
MAX_TIMEOUT_SECONDS = 7 * 60


class OperatorError(RuntimeError):
    pass


def load_request(path: Path) -> dict[str, Any]:
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorError(f"Cannot read request JSON: {exc}") from exc

    if not isinstance(request, dict):
        raise OperatorError("Request must be a JSON object")
    if request.get("schema_version") != 1:
        raise OperatorError("schema_version must be 1")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise OperatorError("request_id must contain only letters, digits, dot, underscore, or dash")
    actions = request.get("actions")
    if not isinstance(actions, list) or not actions:
        raise OperatorError("actions must be a non-empty array")
    if len(actions) != len(set(actions)):
        raise OperatorError("actions must not contain duplicates")
    unknown = set(actions) - ALLOWED_ACTIONS
    if unknown:
        raise OperatorError(f"Unsupported actions: {', '.join(sorted(unknown))}")

    backtest = request.get("backtest")
    if "backtest" in actions:
        if not isinstance(backtest, dict):
            raise OperatorError("backtest action requires a backtest object")
        if backtest.get("confirm_billable") is not True:
            raise OperatorError("backtest.confirm_billable must be true")
        fixture = backtest.get("fixture")
        if fixture not in SMOKE_FIXTURES:
            raise OperatorError(
                f"backtest.fixture must be one of: {', '.join(sorted(SMOKE_FIXTURES))}"
            )
        if "parameters" in backtest:
            raise OperatorError("Arbitrary backtest parameters are not accepted by the public operator workflow")
        parameters = SMOKE_FIXTURES[fixture]
        encoded = json.dumps(parameters, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_PARAMETER_BYTES:
            raise OperatorError("backtest.parameters exceeds 100,000 encoded bytes")
        timeout = backtest.get("timeout_seconds", 360)
        poll = backtest.get("poll_seconds", 10)
        if not isinstance(timeout, int) or not 30 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise OperatorError("backtest.timeout_seconds must be between 30 and 420")
        if not isinstance(poll, int) or not MIN_POLL_SECONDS <= poll <= MAX_POLL_SECONDS:
            raise OperatorError("backtest.poll_seconds must be between 2 and 30")
        if not isinstance(backtest.get("verify_result", False), bool):
            raise OperatorError("backtest.verify_result must be boolean")
    elif backtest is not None:
        raise OperatorError("backtest object is only allowed with the backtest action")

    return request


def same_origin_url(base_uri: str, path_or_url: str) -> str:
    base = urllib.parse.urlsplit(base_uri)
    target = urllib.parse.urlsplit(urllib.parse.urljoin(base_uri.rstrip("/") + "/", path_or_url))
    if target.scheme != "https" or target.netloc != base.netloc:
        raise OperatorError("Server returned a URL outside the configured Cloud Run origin")
    return urllib.parse.urlunsplit(target)


class Client:
    def __init__(self, base_uri: str, identity_token: str) -> None:
        parsed = urllib.parse.urlsplit(base_uri)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise OperatorError("KEEP_AND_LEASE_WEB_URI must be an HTTPS origin")
        self.base_uri = base_uri.rstrip("/")
        self.identity_token = identity_token

    def request(
        self,
        method: str,
        path_or_url: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[bytes, dict[str, str], int]:
        url = same_origin_url(self.base_uri, path_or_url)
        headers = {
            "Authorization": f"Bearer {self.identity_token}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "keep-and-lease-cloud-operator/1",
        }
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read(MAX_RESULT_BYTES + 1)
                if len(data) > MAX_RESULT_BYTES:
                    raise OperatorError("Response exceeded the 50 MiB operator artifact limit")
                return data, dict(response.headers.items()), response.status
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise OperatorError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OperatorError(f"{method} {url} failed: {exc.reason}") from exc

    def json(
        self,
        method: str,
        path_or_url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data, _, _ = self.request(method, path_or_url, payload)
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError as exc:
            raise OperatorError("Endpoint did not return valid JSON") from exc
        if not isinstance(decoded, dict):
            raise OperatorError("Endpoint returned JSON that is not an object")
        return decoded


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


SAFE_JOB_FIELDS = {
    "job_id",
    "status",
    "stage",
    "created_at",
    "started_at",
    "completed_at",
    "elapsed_seconds",
    "cancellation_requested",
    "result_size_bytes",
    "compressed_result_size_bytes",
    "result_checksum_sha256",
    "heartbeat_at",
    "attempt",
    "peak_rss_mb",
    "stage_timings_seconds",
}


def sanitized_job(value: dict[str, Any]) -> dict[str, Any]:
    sanitized = {key: value.get(key) for key in SAFE_JOB_FIELDS if key in value}
    sanitized["error_present"] = bool(value.get("error"))
    return sanitized


def run_backtest(client: Client, config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    parameters = SMOKE_FIXTURES[config["fixture"]]
    submitted = client.json(
        "POST",
        "/api/v1/backtests",
        {"schema_version": 1, "parameters": parameters},
    )
    write_json(output_dir / "backtest-submission.json", sanitized_job(submitted))
    status_url = submitted.get("status_url")
    result_url = submitted.get("result_url")
    if not isinstance(status_url, str) or not isinstance(result_url, str):
        raise OperatorError("Backtest submission omitted status_url or result_url")

    deadline = time.monotonic() + config.get("timeout_seconds", 360)
    poll_seconds = config.get("poll_seconds", 10)
    status_doc: dict[str, Any] = submitted
    while time.monotonic() < deadline:
        status_doc = client.json("GET", status_url)
        write_json(output_dir / "backtest-status.json", sanitized_job(status_doc))
        state = status_doc.get("status")
        print(f"backtest status: {state}", flush=True)
        if state in {"completed", "failed", "cancelled"}:
            break
        time.sleep(poll_seconds)
    else:
        try:
            cancelled = client.json("DELETE", status_url)
            write_json(output_dir / "backtest-timeout-cancellation.json", sanitized_job(cancelled))
        except OperatorError as exc:
            write_json(output_dir / "backtest-timeout-cancellation.json", {"cancel_failed": True})
            raise OperatorError(
                "Backtest exceeded the bounded timeout and its cancellation request failed"
            ) from exc
        raise OperatorError("Backtest exceeded the bounded timeout; cancellation was requested")

    if status_doc.get("status") != "completed":
        raise OperatorError(f"Backtest ended with status {status_doc.get('status')!r}")
    if config.get("verify_result", False):
        data, _, status = client.request("GET", result_url)
        write_json(
            output_dir / "backtest-result-metadata.json",
            {
                "http_status": status,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
    return status_doc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    request = load_request(args.request)
    web_uri = os.environ.get("KEEP_AND_LEASE_WEB_URI", "")
    identity_token = os.environ.get("KEEP_AND_LEASE_ID_TOKEN", "")
    if not web_uri:
        raise OperatorError("KEEP_AND_LEASE_WEB_URI is required")
    if not identity_token:
        raise OperatorError("KEEP_AND_LEASE_ID_TOKEN is required")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        args.output_dir / "request-summary.json",
        {
            "schema_version": request["schema_version"],
            "request_id": request["request_id"],
            "actions": request["actions"],
            "web_uri": web_uri,
        },
    )

    client = Client(web_uri, identity_token)
    if "health" in request["actions"] or "gui" in request["actions"]:
        health = client.json("GET", "/api/v1/health")
        write_json(args.output_dir / "health.json", health)
        if health.get("status") != "ok":
            raise OperatorError("Health response status is not ok")
        build = client.json("GET", "/build-info.json")
        write_json(args.output_dir / "build-info.json", build)
    if "backtest" in request["actions"]:
        run_backtest(client, request["backtest"], args.output_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OperatorError as exc:
        print(f"cloud operator error: {exc}", file=sys.stderr)
        raise SystemExit(2)
