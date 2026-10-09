#!/usr/bin/env python3
"""Audit only the already acquired fixed 1OZ MBO dataset; no vendor API calls."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import contextlib
import importlib.util
import io
import itertools
import json
import os
from pathlib import Path
import re
import tempfile

from download_1oz_mbo import BUCKET, CONFIG, PREFIX, PROJECT, SYMBOLS, Store, digest, partitions, validate_expiries


class Book:
    def __init__(self):
        self.orders = {}
        self.initialized = False
        self.errors = Counter()

    def apply(self, action, side, order_id, price, size):
        if action == "R":
            self.orders.clear()
            self.initialized = True
        elif action == "A":
            if order_id in self.orders:
                self.errors["duplicate_add"] += 1
            if price > 0 and price < 9223372036854775807 and size > 0 and side in ("A", "B"):
                self.orders[order_id] = (side, price, size)
        elif action in ("M", "C"):
            existing = self.orders.get(order_id)
            if existing is None:
                self.errors[f"unknown_{action}"] += 1
                self.initialized = False
                return
            if action == "M":
                if size <= 0:
                    self.orders.pop(order_id)
                else:
                    self.orders[order_id] = (side, price, size)
            elif size > existing[2]:
                self.errors["cancel_exceeds_size"] += 1
                self.initialized = False
                self.orders.pop(order_id)
            elif size == existing[2]:
                self.orders.pop(order_id)
            else:
                self.orders[order_id] = (*existing[:2], existing[2] - size)

    def condition(self):
        bids = [price for side, price, size in self.orders.values() if side == "B" and size > 0]
        asks = [price for side, price, size in self.orders.values() if side == "A" and size > 0]
        if not self.initialized:
            return "uninitialized"
        if not bids or not asks:
            return "one_sided_or_empty"
        if max(bids) >= min(asks):
            return "locked_or_crossed"
        return "two_sided"


def blank(symbol, day):
    return dict(symbol=symbol, day=day, records=0, live_records=0, snapshot_records=0,
                trade_records=0, trade_quantity=0, live_book_updates=0,
                two_sided_events=0, locked_or_crossed_events=0, uninitialized_events=0,
                first_live=None, last_live=None, first_trade=None, last_trade=None,
                timestamp_outside_partition=0, timestamp_regressions=0,
                actions={}, book_errors={})


def check_request(request):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    if set(request) != {"schema_version", "request_id", "action", "result_public_key_pem"}:
        raise ValueError("Unexpected audit request fields")
    if request["schema_version"] != 1 or request["action"] != "audit" or not re.fullmatch(r"[a-z0-9-]{1,64}", request["request_id"]):
        raise ValueError("Invalid fixed audit request")
    key = serialization.load_pem_public_key(request["result_public_key_pem"].encode())
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise ValueError("Require RSA public key of at least 3072 bits")
    return key


def run(request, report):
    import databento as db
    import google.auth
    from google.cloud import storage
    import pandas as pd

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    store = Store(storage.Client(project=PROJECT, credentials=credentials).bucket(BUCKET))
    state = store.restore()
    items = partitions()
    if set(state["streams"]) != {item["name"] for item in items}:
        raise ValueError("Checkpoint has missing or unexpected partitions")
    for item in items:
        row = state["streams"][item["name"]]
        if row["status"] != "done" or row["request"] != item["request"]:
            raise ValueError("A partition is incomplete or has unexpected request parameters")
    report.update(source_download_run=37914266209, config=CONFIG,
                  reserved_estimated_usd=state["reserved_estimated_usd"],
                  expected_daily_files=len(items) - 1, checked_files=0, checksum_failures=0,
                  compressed_bytes=0, daily=[], contracts=[], pairs=[], files=[],
                  unexpected_symbols=[], duplicate_records=0,
                  methodology="Book states evaluated only at F_LAST. Snapshot records excluded from live activity and trade counts. Partial cancellation reduces size; T/F do not change book state. Quote-minute overlap requires a two-sided uncrossed completed non-snapshot book event in each contract within the same UTC minute; it is not a fill or a continuous-time liquidity guarantee. Crossed states can occur outside trading hours. Per-instrument sequence gaps are not treated as missing records because requests filter the wider feed.")
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        def fetch(item):
            row = state["streams"][item["name"]]
            path = work / f"{item['name']}.dbn.zst"
            store.local(row, path)
            return item["name"], path
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = dict(pool.map(fetch, items))
        report["checked_files"] = len(paths)
        report["compressed_bytes"] = sum(path.stat().st_size for path in paths.values())
        for item in items:
            meta = db.DBNStore.from_file(paths[item["name"]]).metadata
            if str(meta.schema) != item["request"]["schema"] or str(meta.dataset) != CONFIG["dataset"]:
                raise ValueError("DBN metadata disagrees with partition")
        definitions = db.DBNStore.from_file(paths["definitions"]).to_df()
        expiries = validate_expiries(definitions)
        report["expiries"] = expiries
        books = {symbol: Book() for symbol in SYMBOLS}
        event_dates = {symbol: set() for symbol in SYMBOLS}
        trade_dates = {symbol: set() for symbol in SYMBOLS}
        quote_minutes = {symbol: set() for symbol in SYMBOLS}
        aggregate = {symbol: blank(symbol, "ALL") for symbol in SYMBOLS}
        integers = [key for key, value in blank("", "").items() if type(value) is int]
        unexpected = set()
        for item in items[1:]:
            path = paths[item["name"]]
            frame = db.DBNStore.from_file(path).to_df(pretty_ts=False, pretty_px=False, map_symbols=True).reset_index()
            day = item["request"]["start"][:10]
            start = pd.Timestamp(item["request"]["start"]).value
            end = pd.Timestamp(item["request"]["end"]).value
            daily = {symbol: blank(symbol, day) for symbol in SYMBOLS}
            minute_sets = {symbol: set() for symbol in SYMBOLS}
            prior_ts = {}
            report["duplicate_records"] += int(frame.duplicated().sum())
            if not frame.empty:
                required = ["symbol", "ts_recv", "action", "side", "order_id", "price", "size", "flags"]
                if not set(required).issubset(frame.columns):
                    raise ValueError("Decoded MBO fields are missing")
                for symbol, timestamp, action, side, order_id, price, size, flags in frame[required].itertuples(index=False, name=None):
                    if symbol not in daily:
                        unexpected.add(str(symbol))
                        continue
                    row, book = daily[symbol], books[symbol]
                    flags, action, side = int(flags), str(action), str(side)
                    timestamp = int(timestamp)
                    snapshot = bool(flags & 32)
                    row["records"] += 1
                    row["actions"][action] = row["actions"].get(action, 0) + 1
                    before = book.errors.copy()
                    book.apply(action, side, int(order_id), int(price), int(size))
                    for error, count in (book.errors - before).items():
                        row["book_errors"][error] = row["book_errors"].get(error, 0) + count
                    if snapshot:
                        row["snapshot_records"] += 1
                        continue
                    row["live_records"] += 1
                    if not start <= timestamp < end:
                        row["timestamp_outside_partition"] += 1
                        continue
                    event_dates[symbol].add(day)
                    iso = pd.Timestamp(timestamp, tz="UTC").isoformat()
                    row["first_live"] = min(row["first_live"] or iso, iso)
                    row["last_live"] = max(row["last_live"] or iso, iso)
                    if not flags & 8 and symbol in prior_ts and timestamp < prior_ts[symbol]:
                        row["timestamp_regressions"] += 1
                    prior_ts[symbol] = timestamp
                    if action in ("A", "M", "C", "R"):
                        row["live_book_updates"] += 1
                    if action == "T":
                        row["trade_records"] += 1
                        row["trade_quantity"] += int(size)
                        row["first_trade"] = min(row["first_trade"] or iso, iso)
                        row["last_trade"] = max(row["last_trade"] or iso, iso)
                        trade_dates[symbol].add(day)
                    if flags & 128:
                        condition = book.condition()
                        if condition == "two_sided":
                            row["two_sided_events"] += 1
                            minute_sets[symbol].add(timestamp // 60_000_000_000)
                        elif condition == "locked_or_crossed":
                            row["locked_or_crossed_events"] += 1
                        elif condition == "uninitialized":
                            row["uninitialized_events"] += 1
            report["files"].append(dict(day=day, bytes=path.stat().st_size, records=len(frame),
                sha256=state["streams"][item["name"]]["sha256"],
                not_found=list(db.DBNStore.from_file(path).metadata.not_found or [])))
            for symbol, row in daily.items():
                row["two_sided_event_minutes"] = len(minute_sets[symbol])
                report["daily"].append(row)
                quote_minutes[symbol].update(minute_sets[symbol])
                target = aggregate[symbol]
                for key in integers:
                    target[key] += row[key]
                for key in ("actions", "book_errors"):
                    for name, count in row[key].items():
                        target[key][name] = target[key].get(name, 0) + count
                for key in ("first_live", "first_trade"):
                    if row[key]:
                        target[key] = min(target[key] or row[key], row[key])
                for key in ("last_live", "last_trade"):
                    if row[key]:
                        target[key] = max(target[key] or row[key], row[key])
        report["unexpected_symbols"] = sorted(unexpected)
        for symbol, row in aggregate.items():
            row.update(expiry=expiries[symbol], active_days=len(event_dates[symbol]),
                traded_days=len(trade_dates[symbol]), two_sided_event_minutes=len(quote_minutes[symbol]),
                active_dates=sorted(event_dates[symbol]), traded_dates=sorted(trade_dates[symbol]))
            report["contracts"].append(row)
        for a, b in itertools.combinations(SYMBOLS, 2):
            expiry_a, expiry_b = pd.Timestamp(expiries[a]), pd.Timestamp(expiries[b])
            active = sorted(event_dates[a] & event_dates[b])
            traded = sorted(trade_dates[a] & trade_dates[b])
            shared_minutes = quote_minutes[a] & quote_minutes[b]
            report["pairs"].append(dict(near=a, far=b, near_expiry=expiries[a], far_expiry=expiries[b],
                expiry_gap_days=(expiry_b - expiry_a).total_seconds() / 86400,
                within_three_months=expiry_b <= expiry_a + pd.DateOffset(months=3),
                common_active_days=len(active), first_common_active=active[0] if active else None,
                last_common_active=active[-1] if active else None,
                common_traded_days=len(traded), common_traded_dates=traded,
                common_two_sided_event_minutes=len(shared_minutes),
                common_two_sided_event_days=len({minute // 1440 for minute in shared_minutes}),
                min_leg_trade_quantity=min(aggregate[a]["trade_quantity"], aggregate[b]["trade_quantity"])))
        report["status"] = "completed"
        run_id = os.environ.get("GITHUB_RUN_ID", "local")
        suffix = f"audits/{request['request_id']}/{run_id}/summary.json"
        store.json(suffix, report)
        report["audit_storage"] = f"gs://{BUCKET}/{PREFIX}/{suffix}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    key = check_request(request)
    if args.validate_only:
        print("Fixed read-only audit request validated")
        return 0
    report = {"request_id": request["request_id"], "source_commit": os.environ.get("GITHUB_SHA")}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            run(request, report)
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__, error_message=str(exc)[:600])
    spec = importlib.util.spec_from_file_location("encryption", "scripts/cloud-databento-research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.encrypt_result(report, key, Path("gold-audit-evidence/result.encrypted.json"))
    print(json.dumps({"request_id": request["request_id"], "status": report["status"],
                      "error_type": report.get("error_type")}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
