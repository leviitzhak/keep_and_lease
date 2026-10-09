#!/usr/bin/env python3
"""Fixed, resumable 1OZ MBO acquisition using the existing research operator."""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

PROJECT = "keep-and-lease"
BUCKET = "keep-and-lease-market-data"
PREFIX = "research/databento/gold-1oz-mbo-2026-07-09-to-2026-10-09-v1"
STUDY = "gold-1oz-mbo-three-month-v1"
SYMBOLS = ["1OZG7", "1OZJ7", "1OZM7", "1OZQ7", "1OZV7", "1OZZ7",
           "1OZG8", "1OZJ8", "1OZM8", "1OZQ8"]
MAX_COST = 0.25
MAX_ATTEMPTS = 2
CONFIG = {"version": 1, "dataset": "GLBX.MDP3", "schema": "mbo",
          "start": "2026-07-09", "end": "2026-10-09", "symbols": SYMBOLS,
          "max_cumulative_estimated_usd": MAX_COST}


def validate_request(request):
    if set(request) != {"schema_version", "request_id", "action", "study"}:
        raise ValueError("Unexpected request fields")
    if request["schema_version"] != 1 or request["study"] != STUDY or request["action"] != "download":
        raise ValueError("Only the authorized fixed 1OZ MBO download is supported")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", request["request_id"]):
        raise ValueError("Invalid request ID")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_digest(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def partitions():
    import pandas as pd
    common = dict(dataset=CONFIG["dataset"], symbols=SYMBOLS, stype_in="raw_symbol")
    rows = [{"name": "definitions", "request": dict(common, schema="definition",
              start="2026-10-04", end=CONFIG["end"])}]
    for day in pd.date_range(CONFIG["start"], CONFIG["end"], inclusive="left", tz="UTC"):
        rows.append({"name": f"mbo-{day:%Y%m%d}", "request": dict(common, schema="mbo",
                    start=day.isoformat(), end=(day + pd.Timedelta(days=1)).isoformat())})
    return rows


class Store:
    def __init__(self, bucket):
        self.bucket = bucket

    def json(self, suffix, value):
        self.bucket.blob(f"{PREFIX}/{suffix}").upload_from_string(
            json.dumps(value, allow_nan=False, default=str),
            content_type="application/json", if_generation_match=0)

    def restore(self):
        checkpoints = list(self.bucket.list_blobs(prefix=f"{PREFIX}/checkpoints/"))
        if not checkpoints:
            return {"config": copy.deepcopy(CONFIG), "streams": {}, "reserved_estimated_usd": 0.0}
        state = json.loads(max(checkpoints, key=lambda blob: blob.name).download_as_bytes())
        if state["config"] != CONFIG:
            raise ValueError("Persisted scope differs from the authorized fixed study")
        return state

    def checkpoint(self, state):
        self.json(f"checkpoints/{time.time_ns():020d}-{uuid.uuid4().hex}.json", state)

    def verify(self, row):
        blob = self.bucket.blob(row["object"])
        blob.reload()
        if (blob.metadata or {}).get("sha256") != row["sha256"] or blob.size != row["size"]:
            raise ValueError("Completed persistent object failed its integrity check")

    def recover(self, name, row):
        objects = list(self.bucket.list_blobs(prefix=f"{PREFIX}/raw/{name}/{row['attempt_id']}/"))
        if not objects:
            return False
        if len(objects) != 1:
            raise ValueError("Ambiguous raw object recovery")
        blob = objects[0]
        blob.reload()
        meta = blob.metadata or {}
        if meta.get("request_sha256") != request_digest(row["request"]) or not meta.get("sha256"):
            raise ValueError("Recovered object does not match the reserved request")
        row.update(status="done", object=blob.name, sha256=meta["sha256"], size=blob.size)
        return True

    def raw(self, name, row, path):
        sha = digest(path)
        object_name = f"{PREFIX}/raw/{name}/{row['attempt_id']}/{sha}.dbn.zst"
        blob = self.bucket.blob(object_name)
        blob.metadata = {"sha256": sha, "request_sha256": request_digest(row["request"])}
        blob.upload_from_filename(path, if_generation_match=0)
        row.update(status="done", object=object_name, sha256=sha, size=Path(path).stat().st_size)

    def local(self, row, path):
        self.bucket.blob(row["object"]).download_to_filename(path)
        if digest(path) != row["sha256"]:
            raise ValueError("Downloaded persistent object has a checksum mismatch")


def finite_cost(value):
    cost = float(value)
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("Invalid vendor cost estimate")
    return cost


def check_budget(state, amount):
    if state["reserved_estimated_usd"] + amount > MAX_COST + 1e-9:
        raise ValueError("Cumulative estimated data purchases would exceed USD 0.25")


def metadata_cost(client, request):
    from databento.common.error import BentoServerError
    for attempt in range(3):
        try:
            return finite_cost(client.metadata.get_cost(**request))
        except BentoServerError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def retryable(exc):
    import requests
    return isinstance(exc, (requests.Timeout, requests.ConnectionError)) or (
        getattr(exc, "http_status", 0) or 0) >= 500


def acquire(item, cost, client, store, state, work, verify_dbn, is_retryable=retryable):
    name, request = item["name"], item["request"]
    row = state["streams"].get(name)
    if row and row["request"] != request:
        raise ValueError("Persisted partition request differs")
    if row and row["status"] == "done":
        store.verify(row)
        return row
    if row and store.recover(name, row):
        store.checkpoint(state)
        return row
    attempts = row.get("attempts", 0) if row else 0
    while attempts < MAX_ATTEMPTS:
        check_budget(state, cost)
        attempts += 1
        row = {"status": "inflight", "request": request, "attempts": attempts,
               "attempt_id": uuid.uuid4().hex, "estimated_usd": cost}
        state["streams"][name] = row
        state["reserved_estimated_usd"] += cost
        # Persist the conservative cost reservation before any billable API call.
        store.checkpoint(state)
        path = work / f"{name}-{row['attempt_id']}.dbn.zst"
        try:
            client.timeseries.get_range(**request, path=path)
        except Exception as exc:
            row.update(status="interrupted", error_type=type(exc).__name__,
                       http_status=getattr(exc, "http_status", None))
            store.checkpoint(state)
            path.unlink(missing_ok=True)
            if attempts == MAX_ATTEMPTS or not is_retryable(exc):
                raise
            time.sleep(2)
            continue
        # An upload/checkpoint failure never immediately triggers a second paid request.
        verify_dbn(path, request)
        store.raw(name, row, path)
        store.checkpoint(state)
        path.unlink(missing_ok=True)
        return row
    raise ValueError("Partition reached its bounded download-attempt limit")


def validate_expiries(frame):
    import pandas as pd
    if not {"raw_symbol", "expiration"}.issubset(frame.columns):
        raise ValueError("Definitions are missing symbols or expirations")
    expiries = {}
    cutoff = pd.Timestamp("2027-01-09", tz="UTC")
    codes = "FGHJKMNQUVXZ"
    for symbol in SYMBOLS:
        selected = frame[frame["raw_symbol"] == symbol]
        values = pd.to_datetime(selected["expiration"], utc=True).dropna().unique()
        if len(values) != 1 or pd.Timestamp(values[0]) < cutoff:
            raise ValueError("Missing, conflicting or insufficient remaining maturity")
        expiry = pd.Timestamp(values[0])
        month = pd.Timestamp(year=2020 + int(symbol[-1]), month=codes.index(symbol[-2]) + 1,
                             day=1, tz="UTC")
        if not month - pd.offsets.MonthBegin(1) <= expiry < month:
            raise ValueError("Vendor expiration does not match the 1OZ contract month")
        if "instrument_class" in selected and not selected["instrument_class"].eq("F").all():
            raise ValueError("Definition is not an outright future")
        expiries[symbol] = expiry
    for symbol, expiry in expiries.items():
        if not any(other != symbol and max(expiry, second) <= min(expiry, second) + pd.DateOffset(months=3)
                   for other, second in expiries.items()):
            raise ValueError("Contract has no eligible expiry within three calendar months")
    return {symbol: expiry.isoformat() for symbol, expiry in expiries.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    validate_request(request)
    if args.validate_only:
        print("Fixed download scope validated")
        return 0
    status, store, state, report = 0, None, None, {}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            import databento as db
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            from google.cloud import storage

            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            response = AuthorizedSession(credentials).get(
                f"https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets/databento-api-key/versions/latest:access",
                timeout=30)
            response.raise_for_status()
            key = base64.b64decode(response.json()["payload"]["data"]).decode().strip()
            if not key:
                raise ValueError("Secret is empty")
            client = db.Historical(key)
            store = Store(storage.Client(project=PROJECT, credentials=credentials).bucket(BUCKET))
            state = store.restore()
            work = Path("work/gold-1oz-mbo")
            work.mkdir(parents=True, exist_ok=True)
            run = os.environ.get("GITHUB_RUN_ID", uuid.uuid4().hex)
            report = {"request_id": request["request_id"], "workflow_run_id": run,
                      "source_commit": os.environ.get("GITHUB_SHA"), "config": CONFIG,
                      "storage": f"gs://{BUCKET}/{PREFIX}/", "status": "started"}
            run_prefix = f"runs/{request['request_id']}/{run}"
            store.json(f"{run_prefix}/started.json", report)
            items, costs = partitions(), {}
            # Recover completed uploads before estimating the remaining purchase plan.
            for item in items:
                row = state["streams"].get(item["name"])
                if row and row["status"] == "done":
                    store.verify(row)
                elif row and store.recover(item["name"], row):
                    store.checkpoint(state)
            for item in items:
                row = state["streams"].get(item["name"])
                costs[item["name"]] = 0.0 if row and row["status"] == "done" else metadata_cost(client, item["request"])
            check_budget(state, sum(costs.values()))
            store.json(f"{run_prefix}/plan.json", {"partitions": items, "estimates_usd": costs,
                "previous_reserved_estimated_usd": state["reserved_estimated_usd"]})

            def verify_dbn(path, request):
                meta = db.DBNStore.from_file(path).metadata
                if str(meta.schema) != request["schema"] or str(meta.dataset) != CONFIG["dataset"]:
                    raise ValueError("Downloaded DBN metadata does not match the request")

            definition = acquire(items[0], costs["definitions"], client, store, state, work, verify_dbn)
            definition_path = work / "verified-definitions.dbn.zst"
            store.local(definition, definition_path)
            expiries = validate_expiries(db.DBNStore.from_file(definition_path).to_df())
            store.json(f"{run_prefix}/verified-contracts.json", {"expiries": expiries})
            definition_path.unlink()
            for item in items[1:]:
                acquire(item, costs[item["name"]], client, store, state, work, verify_dbn)
            report.update(status="completed", reserved_estimated_usd=state["reserved_estimated_usd"],
                          completed_daily_partitions=len(items) - 1,
                          objects={name: row for name, row in state["streams"].items()})
            store.json(f"{run_prefix}/completed.json", report)
        except Exception as exc:
            status = 1
            report.update(status="failed", error_type=type(exc).__name__,
                          http_status=getattr(exc, "http_status", None))
            if getattr(exc, "response", None) is not None:
                report["http_status"] = exc.response.status_code
            if store is not None:
                try:
                    store.json(f"failures/{time.time_ns()}-{uuid.uuid4().hex}.json", report)
                except Exception:
                    pass
    print(json.dumps({"request_id": request["request_id"], "status": report.get("status"),
                      "error_type": report.get("error_type"), "http_status": report.get("http_status"),
                      "storage": f"gs://{BUCKET}/{PREFIX}/"}))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
