#!/usr/bin/env python3
"""Independently check a funded BTC replay's lossless audit ZIP.

Example::

    python scripts/check-paired-replay-audit.py audit.zip --capital 100000 \
        --fee-bps 10 --interval-seconds .5 --output report.json

Only Python's standard library is used; no application calculation code is
imported. JSONL rows are streamed, with historical orders/pairs indexed in a
temporary SQLite database rather than retained in RAM. The input must be the
full audit archive, not sampled chart data or a selected-period CSV. Optional
--result-json compares independently recomputed numbers to the server result.
Exit status is 0 for passed available checks, 1 for findings, 2 for input errors.
Checks establish internal consistency, not the correctness of external market
data, forecasts, or executable liquidity. See the emitted caveats.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import zipfile


def reject_constant(value):
    raise ValueError("Nonfinite JSON number: " + value)


def loads(value):
    return json.loads(value, parse_constant=reject_constant)


def timestamp_us(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = parsed - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


class Checks:
    def __init__(self):
        self.counts = Counter()
        self.failures = Counter()
        self.examples = defaultdict(list)
        self.max_errors = defaultdict(float)

    def check(self, name, passed, context=None):
        self.counts[name] += 1
        if not passed:
            self.failures[name] += 1
            if len(self.examples[name]) < 4:
                self.examples[name].append(context)

    def equal(self, name, actual, expected, context=None, atol=1e-6, rtol=1e-10):
        finite = (isinstance(actual, (int, float)) and isinstance(expected, (int, float))
                  and math.isfinite(actual) and math.isfinite(expected))
        error = abs(actual - expected) if finite else None
        if error is not None:
            self.max_errors[name] = max(self.max_errors[name], error)
        self.check(name, finite and error <= atol + rtol * abs(expected),
                   {"where": context, "actual": actual, "expected": expected})

    def report(self):
        return {"checks": dict(self.counts), "failure_counts": dict(self.failures),
                "failure_examples": dict(self.examples),
                "maximum_absolute_errors": dict(self.max_errors)}


class Sum:
    """Compensated streaming summation."""
    def __init__(self):
        self.value = self.correction = 0.0

    def add(self, value):
        corrected = value - self.correction
        total = self.value + corrected
        self.correction = (total - self.value) - corrected
        self.value = total


class Moments:
    def __init__(self):
        self.n = 0
        self.mean = self.m2 = 0.0
        self.minimum = math.inf
        self.maximum = -math.inf
        self.total = Sum()

    def add(self, value):
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (value - self.mean)
        self.total.add(value)
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)

    def report(self):
        return {"count": self.n, "sum": self.total.value,
                "mean": self.mean if self.n else None,
                "population_std": math.sqrt(max(0, self.m2 / self.n)) if self.n else None,
                "minimum": self.minimum if self.n else None,
                "maximum": self.maximum if self.n else None}


class HashReader:
    def __init__(self, stream):
        self.stream, self.digest, self.size = stream, hashlib.sha256(), 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        self.size += len(data)
        return data


class Archive:
    def __init__(self, path, checks):
        self.zip = zipfile.ZipFile(path)
        self.checks = checks
        with self.zip.open("manifest.json") as source:
            encoded = source.read(16 * 1024 * 1024 + 1)
        if len(encoded) > 16 * 1024 * 1024:
            raise ValueError("Manifest exceeds 16 MiB reader limit")
        self.manifest = loads(encoded)
        checks.check("manifest_schema", self.manifest.get("schema_version") == 1)
        names = self.zip.namelist()
        checks.check("unique_zip_members", len(names) == len(set(names)))
        self.verified = {}

    def rows(self, dataset_name):
        dataset = self.manifest["datasets"][dataset_name]
        total_rows = compressed_size = uncompressed_size = 0
        for index, entry in enumerate(dataset["chunks"]):
            name = entry["object"]
            if not re.fullmatch(r"[a-z][a-z0-9_]*/[0-9]{6}\.jsonl\.gz", name):
                raise ValueError("Invalid audit member: " + name)
            self.checks.check("chunk_sequence", entry["index"] == index and
                              entry["first_row"] == total_rows, name)
            self.checks.check("chunk_dataset", name.split("/")[0] == dataset_name, name)
            digest, size, count = hashlib.sha256(), 0, 0
            with self.zip.open(name) as source:
                reader = HashReader(source)
                with gzip.GzipFile(fileobj=reader) as decoded:
                    while True:
                        line = decoded.readline(16 * 1024 * 1024 + 1)
                        if not line:
                            break
                        if len(line) > 16 * 1024 * 1024:
                            raise ValueError("Audit row exceeds 16 MiB reader limit")
                        digest.update(line)
                        size += len(line)
                        count += 1
                        row = loads(line)
                        if not isinstance(row, dict):
                            raise ValueError("Audit row must be an object")
                        yield row
                # Include any remaining member bytes in its compressed hash.
                while reader.read(1024 * 1024):
                    pass
            for label, actual, expected in (
                    ("compressed_hash", reader.digest.hexdigest(), entry["compressed_sha256"]),
                    ("uncompressed_hash", digest.hexdigest(), entry["sha256"]),
                    ("compressed_size", reader.size, entry["compressed_bytes"]),
                    ("uncompressed_size", size, entry["uncompressed_bytes"]),
                    ("chunk_rows", count, entry["rows"])):
                self.checks.check(label, actual == expected, name)
            total_rows += count
            compressed_size += reader.size
            uncompressed_size += size
        self.checks.check("dataset_rows", total_rows == dataset["rows"], dataset_name)
        self.verified[dataset_name] = {"rows": total_rows, "chunks": len(dataset["chunks"]),
                                      "compressed_bytes": compressed_size,
                                      "uncompressed_bytes": uncompressed_size}


class Audit:
    def __init__(self, args, archive, db):
        self.args, self.archive, self.db, self.c = args, archive, db, archive.checks
        db.executescript("""
            PRAGMA cache_size=-8192;
            CREATE TABLE orders(id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE pairs(id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE prints(symbol TEXT, trade_id TEXT, quantity REAL, capacity REAL,
                                PRIMARY KEY(symbol,trade_id));
            CREATE TABLE fills(order_id TEXT, trade_id TEXT, symbol TEXT,
                               PRIMARY KEY(order_id,trade_id,symbol));
            CREATE TABLE replacements(order_id TEXT, revision INTEGER, data TEXT,
                                      PRIMARY KEY(order_id,revision));
            CREATE TABLE cancellations(id TEXT PRIMARY KEY, data TEXT);
        """)
        self.kinds, self.reasons, self.statuses = Counter(), Counter(), Counter()
        self.decisions = defaultdict(Moments)
        self.initial_price = self.initial_us = self.event_us = None
        self.initial_count = 0
        self.units = defaultdict(float)
        self.fees, self.turnover, self.commissions, self.delivery_fees = Sum(), Sum(), Sum(), Sum()
        self.reservations, self.pending_variation = {}, {}
        self.last = None
        self.rows = 0
        self.returns, self.direct_returns, self.commodity_returns = Moments(), Moments(), Moments()
        self.log_chain = Sum()
        self.previous_nav, self.peak, self.direct_peak = args.capital, args.capital, 1.0
        self.drawdown = self.direct_drawdown = self.commodity_drawdown = 0.0
        self.commodity_peak = 1.0
        self.min_ratio = math.inf
        self.max_unpaired = 0.0
        self.collateral_breaches = 0
        self.maximum_reported_reconstruction_error = 0.0
        self.day_closes = []

    def replacement(self, row):
        """A request is evidence only; the live limit changes at its arrival."""
        order_id, revision = row["order_id"], row["revision"]
        context = {"order_id": order_id, "revision": revision, "us": row["us"]}
        order = self.get("orders", order_id)
        self.c.check("replacement_has_order", order is not None, context)
        self.c.check("replacement_positive_revision", isinstance(revision, int) and revision > 0, context)
        self.c.check("replacement_positive_limit", math.isfinite(row["limit_price"]) and row["limit_price"] > 0, context)
        if order:
            self.c.check("replacement_order_identity", row["pair_id"] == order["pair_id"] and
                         row["symbol"] == order["symbol"] and row["role"] == order["role"], context)
        clocks = ("observation_us", "decision_started_us", "decision_ready_us",
                  "submitted_us", "eligible_after_us")
        self.c.check("replacement_clocks_causal", all(row[left] <= row[right]
                     for left, right in zip(clocks, clocks[1:])), context)
        stored = self.db.execute("SELECT data FROM replacements WHERE order_id=? AND revision=?",
                                 (str(order_id), revision)).fetchone()
        if row["kind"] == "order_replace_requested":
            self.c.check("unique_replacement_request", stored is None, context)
            self.c.check("replacement_request_after_decision", row["us"] >= row["decision_ready_us"] and
                         row["us"] == row["submitted_us"], context)
            if stored is None:
                self.db.execute("INSERT INTO replacements VALUES(?,?,?)",
                                (str(order_id), revision, json.dumps(row, separators=(",", ":"))))
            return
        self.c.check("replacement_arrival_has_request", stored is not None, context)
        self.c.check("replacement_arrival_after_transport", row["us"] >= row["eligible_after_us"], context)
        if stored:
            request = loads(stored[0])
            self.c.check("unique_replacement_arrival", not request.get("arrived", False), context)
            for name in ("pair_id", "symbol", "role", "limit_price", *clocks):
                self.c.check("replacement_arrival_matches_request", row[name] == request[name],
                             {**context, "field": name})
            request["arrived"] = True
            self.db.execute("UPDATE replacements SET data=? WHERE order_id=? AND revision=?",
                            (json.dumps(request, separators=(",", ":")), str(order_id), revision))
        if order:
            if row.get("previous_limit_price") is not None:
                self.c.equal("replacement_previous_live_limit", row["previous_limit_price"],
                             order["limit_price"], context, atol=1e-8)
            else:
                self.c.check("replacement_missing_live_order_not_applied", not row["applied"], context)
            if row["applied"]:
                self.c.check("replacement_revision_advances", revision > order.get("revision", 0), context)
                order.update(limit_price=row["limit_price"], revision=revision,
                             eligible_after_us=row["eligible_after_us"])
                pair = self.get("pairs", row["pair_id"])
                if pair and "fill_revision" in row:
                    self.c.check("replacement_based_on_current_fills", row["fill_revision"] == pair["fill_revision"], context)
                if order["role"] == "target" and pair:
                    ratio = pair["target_quantity_btc"] / pair["source_quantity_btc"]
                    if pair["source_filled"] - pair["target_filled"] / ratio > 1e-12:
                        order["active"] = True
                self.put("orders", order_id, order)

    def cancellation(self, row):
        order = self.get("orders", row["order_id"])
        context = {"order_id": row["order_id"], "us": row["us"]}
        self.c.check("cancellation_has_order", order is not None, context)
        if order:
            self.c.check("cancellation_order_identity", row["pair_id"] == order["pair_id"] and
                         row["symbol"] == order["symbol"] and row["role"] == order["role"], context)
        clocks = ("decision_started_us", "decision_ready_us", "submitted_us", "eligible_after_us")
        self.c.check("cancellation_clocks_causal", all(row[left] <= row[right]
                     for left, right in zip(clocks, clocks[1:])), context)
        if row["kind"] == "order_cancel_requested":
            self.c.check("unique_cancellation_request", self.get("cancellations", row["order_id"]) is None, context)
            self.c.check("cancellation_request_at_submission", row["us"] == row["submitted_us"], context)
            self.put("cancellations", row["order_id"], row)
            return
        request = self.get("cancellations", row["order_id"])
        self.c.check("cancellation_arrival_has_request", request is not None, context)
        self.c.check("cancellation_arrival_after_transport", row["us"] >= row["eligible_after_us"], context)
        if request:
            self.c.check("unique_cancellation_arrival", not request.get("arrived", False), context)
            for name in ("pair_id", "symbol", "role", "reason", *clocks):
                self.c.check("cancellation_arrival_matches_request", row[name] == request[name],
                             {**context, "field": name})
            self.put("cancellations", row["order_id"], {**request, "arrived": True})
        if order and row["applied"]:
            order["active"] = False
            self.put("orders", row["order_id"], order)

    def get(self, table, key):
        record = self.db.execute("SELECT data FROM " + table + " WHERE id=?", (str(key),)).fetchone()
        return loads(record[0]) if record else None

    def put(self, table, key, value):
        self.db.execute("INSERT OR REPLACE INTO " + table + " VALUES(?,?)",
                        (str(key), json.dumps(value, separators=(",", ":"))))

    def event(self, row):
        kind, us = row["kind"], row["us"]
        self.c.check("events_chronological", self.event_us is None or us >= self.event_us,
                     {"kind": kind, "us": us, "previous_us": self.event_us})
        self.event_us = us
        self.kinds[kind] += 1
        if kind == "initial_holding":
            self.initial_count += 1
            self.initial_price, self.initial_us = row["price"], us
            self.units["SPOT"] = row["btc"]
            self.c.equal("initial_endowment", row["btc"] * row["price"], self.args.capital)
        elif kind == "order":
            self.c.check("unique_order", self.get("orders", row["order_id"]) is None, row["order_id"])
            if "decision_started_us" in row:
                self.c.check("initial_order_clocks_causal", row["observation_us"] <= row["decision_started_us"] <=
                             row["decision_ready_us"] <= us <= row["eligible_after_us"], row["order_id"])
            self.put("orders", row["order_id"], {**row, "filled": 0.0,
                     "active": not row.get("conditional", False)})
        elif kind == "order_activation":
            order = self.get("orders", row["order_id"])
            self.c.check("activation_has_order", order is not None, row["order_id"])
            if order:
                order.update(active=True, eligible_after_us=row["eligible_after_us"])
                self.put("orders", row["order_id"], order)
        elif kind in ("order_replace_requested", "order_replace_arrival"):
            self.replacement(row)
        elif kind in ("order_cancel_requested", "order_cancel_arrival"):
            self.cancellation(row)
        elif kind == "paired_transfer":
            self.c.check("unique_pair", self.get("pairs", row["pair_id"]) is None, row["pair_id"])
            self.put("pairs", row["pair_id"], {"source_quantity_btc": row["source_quantity_btc"],
                     "target_quantity_btc": row["target_quantity_btc"], "source_filled": 0.0,
                     "target_filled": 0.0, "source_acknowledged": 0.0,
                     "source_order_id": row["source_order_id"], "target_order_id": row["target_order_id"],
                     "source_symbol": row["source_symbol"], "target_symbol": row["target_symbol"],
                     "source_lots": [], "source_value": 0.0, "target_value": 0.0,
                     "source_fees": 0.0, "target_fees": 0.0,
                     "matched_source_value": 0.0, "matched_source_fees": 0.0,
                     "fill_revision": 0,
                     "decision": row.get("decision", {}),
                     "target_effective_lease": row.get("target_effective_lease"),
                     "fees": 0.0, "result": None})
            started = row.get("decision", {}).get("decision_started_us", us)
            for quote in row.get("decision", {}).get("quote_snapshots", {}).values():
                self.c.check("decision_quotes_causal", quote["source_us"] <= started and quote["available_us"] <= started, us)
        elif kind == "fill":
            self.fill(row)
        elif kind == "fill_acknowledgement":
            self.c.check("acknowledgement_after_exchange_fill", row["exchange_fill_us"] <= us, us)
            order = self.get("orders", row["order_id"])
            pair = self.get("pairs", row["pair_id"])
            self.c.check("acknowledgement_has_order_and_pair", order is not None and pair is not None, us)
            if order and pair and order["role"] == "source":
                pair["source_acknowledged"] += abs(row["signed_btc"])
                self.c.check("source_acknowledgement_capacity", pair["source_acknowledged"] <= pair["source_filled"] + 1e-10, us)
                self.put("pairs", row["pair_id"], pair)
        elif kind == "delivery":
            self.units[row["symbol"]] += row["signed_quantity"]
            self.delivery_fees.add(row.get("fee_usd", 0.0))
        elif kind == "commission_charge":
            self.commissions.add(row["amount_usd"])
        elif kind == "collateral_reservation":
            self.reservations[row["reservation_id"]] = row["amount_usd"]
        elif kind == "collateral_release":
            key = row["reservation_id"]
            old = self.reservations.get(key, 0.0)
            self.c.check("release_within_reservation", row["amount_usd"] <= old + 1e-6, us)
            remaining = old - row["amount_usd"]
            if remaining > 1e-8:
                self.reservations[key] = remaining
            else:
                self.reservations.pop(key, None)
        elif kind == "variation_accrual":
            self.c.check("unique_pending_variation", row["payment_id"] not in self.pending_variation, us)
            self.pending_variation[row["payment_id"]] = row["amount_usd"]
        elif kind == "variation_payment":
            amount = self.pending_variation.pop(row["payment_id"], None)
            self.c.equal("variation_payment_matches_accrual", row["amount_usd"], amount, us)
        elif kind == "pair_risk_limit":
            self.reasons["risk:" + row["reason"]] += 1
            pair = self.get("pairs", row["pair_id"])
            order = self.get("orders", pair["source_order_id"]) if pair else None
            if order:
                order["active"] = False
                self.put("orders", pair["source_order_id"], order)
        elif kind == "paired_decision":
            decision = row["decision"]
            group = ("pending_" if row.get("remaining_quantity") else "new_") + (
                "selected" if row["selected"] else "rejected")
            self.reasons[group + ":" + decision.get("reason", "unknown")] += 1
            edge = decision.get("edge_btc", 0.0)
            self.decisions[group + "_edge_btc"].add(edge)
            self.c.equal("forecast_edge_arithmetic", edge,
                         decision.get("swap_btc", 0.0) - decision.get("keep_btc", 0.0), us, atol=1e-12)
            diagnostics = decision.get("diagnostics", {})
            if "initial_btc" in diagnostics:
                self.c.equal("forecast_required_edge_for_preset", decision["required_edge_btc"],
                             diagnostics["initial_btc"] * .0005, us, atol=1e-12)
            if decision.get("horizon_us") is not None:
                horizon_days = (decision["horizon_us"] - us) / 86400e6
                self.decisions[group + "_horizon_days"].add(horizon_days)
                self.c.check("forecast_horizon_positive", horizon_days > 0, us)
            if row["selected"] and decision.get("reason") != "forced_expiry_exit":
                self.c.check("selected_expected_edge_positive", edge > decision.get("required_edge_btc", 0.0), us)
        elif kind == "paired_transfer_result":
            pair = self.get("pairs", row["pair_id"])
            self.c.check("result_has_pair", pair is not None, row["pair_id"])
            if pair:
                ratio = pair["target_quantity_btc"] / pair["source_quantity_btc"]
                matched = min(pair["source_filled"], pair["target_filled"] / ratio)
                for name, expected in (("source_filled_btc", pair["source_filled"]),
                                       ("target_filled_btc", pair["target_filled"]),
                                       ("matched_source_btc", matched),
                                       ("unpaired_btc", pair["source_filled"] - matched),
                                       ("fees_usd", pair["fees"]),
                                       ("paired_fill_ratio", matched / pair["source_quantity_btc"])):
                    self.c.equal("pair_result_" + name, row[name], expected, row["pair_id"], atol=1e-8)
                pair["result"] = {k: row[k] for k in ("status", "reason", "max_legging_seconds", "max_unpaired_btc")}
                self.effective_entry(row, pair, matched)
                self.put("pairs", row["pair_id"], pair)

    def effective_entry(self, row, pair, matched):
        """Recompute the optional new entry metric from independently matched fills."""
        if "executed_effective_lease" not in row:
            return  # Historical fixed-order archives did not report this measure.
        context = row["pair_id"]
        if pair["source_symbol"] != "SPOT" or pair["target_symbol"] == "SPOT" or matched <= 1e-12:
            self.c.check("effective_lease_only_for_matched_entry", row["executed_effective_lease"] is None, context)
            return
        target_quantity = pair["target_filled"]
        source_vwap = pair["matched_source_value"] / matched
        target_vwap = pair["target_value"] / target_quantity
        for name, expected in (("source_vwap", source_vwap), ("target_vwap", target_vwap),
                               ("matched_source_fees_usd", pair["matched_source_fees"]),
                               ("target_fees_usd", pair["target_fees"])):
            if name in row:
                self.c.equal("matched_entry_" + name, row[name], expected, context, atol=1e-8)
        # The explicit clock/yield provenance prevents guessing between decision-
        # time and completion-time annualization when reading older schema variants.
        expiry_us = row.get("effective_lease_expiry_us")
        rate_us = row.get("effective_lease_rate_time_us")
        cash_rate = row.get("effective_lease_cash_rate")
        self.c.check("effective_lease_has_time_and_rate", expiry_us is not None and rate_us is not None and
                     cash_rate is not None, context)
        if expiry_us is None or rate_us is None or cash_rate is None:
            return
        self.c.check("effective_lease_clock_causal", rate_us <= row["us"], context)
        years = (expiry_us - rate_us) / (365 * 86400e6)
        net_spot = source_vwap - pair["matched_source_fees"] / matched
        if years <= 0 or net_spot <= 0:
            self.c.check("effective_lease_undefined_boundary", row["executed_effective_lease"] is None, context)
            return
        cost_future = target_vwap + pair["target_fees"] / target_quantity
        expected = cash_rate - (cost_future / net_spot - 1) / years
        self.c.equal("executed_effective_lease_from_matched_fills", row["executed_effective_lease"],
                     expected, context, atol=1e-9)
        target = row.get("target_effective_lease", pair.get("target_effective_lease"))
        if target is not None and "effective_lease_shortfall" in row:
            self.c.equal("effective_lease_shortfall", row["effective_lease_shortfall"],
                         max(0.0, target - expected), context, atol=1e-9)

    def fill(self, row):
        us, quantity, symbol = row["us"], row["signed_btc"], row["symbol"]
        value = abs(quantity) * row["price"]
        self.c.equal("fill_fee_10bps_or_cli_rate", row["fee_usd"], value * self.args.fee_bps / 10000, us, atol=1e-8)
        self.c.check("fill_side", row["side"] == ("buy" if quantity > 0 else "sell"), us)
        self.c.check("fill_role_direction", (quantity < 0 if row["role"] == "source" else quantity > 0), us)
        self.c.check("fill_reported_time_causal", row.get("reported_us", us) <= us, us)
        self.c.check("fill_acknowledgement_not_early", row.get("acknowledgement_us", us) >= us, us)
        try:
            self.db.execute("INSERT INTO fills VALUES(?,?,?)", (str(row["order_id"]), str(row["trade_id"]), symbol))
            unique = True
        except sqlite3.IntegrityError:
            unique = False
        self.c.check("unique_fill", unique, {"us": us, "order": row["order_id"]})
        printed = self.db.execute("SELECT quantity,capacity FROM prints WHERE symbol=? AND trade_id=?",
                                  (symbol, str(row["trade_id"]))).fetchone()
        cumulative = abs(quantity) + (printed[0] if printed else 0)
        capacity = row["observed_btc"] * self.args.participation
        if printed:
            self.c.equal("print_capacity_consistent", capacity, printed[1], us, atol=1e-12)
        self.c.check("observed_print_capacity", cumulative <= capacity + 1e-10, us)
        self.db.execute("INSERT OR REPLACE INTO prints VALUES(?,?,?,?)", (symbol, str(row["trade_id"]), cumulative, capacity))
        order = self.get("orders", row["order_id"])
        self.c.check("fill_has_order", order is not None, us)
        if order:
            self.c.check("fill_after_eligibility", us > order["eligible_after_us"], us)
            self.c.check("fill_order_active", order["active"], us)
            self.c.check("fill_order_identity", row["pair_id"] == order["pair_id"] and
                         symbol == order["symbol"] and row["role"] == order["role"], us)
            self.c.check("fill_order_direction", quantity * order["signed_btc"] > 0, us)
            order["filled"] += abs(quantity)
            self.c.check("fill_order_capacity", order["filled"] <= abs(order["signed_btc"]) + 1e-10, us)
            self.c.check("fill_limit", row["price"] <= order["limit_price"] + 1e-8 if quantity > 0
                         else row["price"] >= order["limit_price"] - 1e-8, us)
            if "limit_price" in row:
                self.c.equal("fill_reported_live_limit", row["limit_price"], order["limit_price"], us, atol=1e-8)
            if "order_revision" in row:
                self.c.check("fill_reported_order_revision", row["order_revision"] == order.get("revision", 0), us)
            if "eligible_after_us" in row:
                self.c.check("fill_reported_order_eligibility", row["eligible_after_us"] == order["eligible_after_us"], us)
            self.put("orders", row["order_id"], order)
        pair = self.get("pairs", row["pair_id"])
        self.c.check("fill_has_pair", pair is not None, us)
        if pair:
            pair[row["role"] + "_filled"] += abs(quantity)
            pair["fill_revision"] += 1
            pair["fees"] += row["fee_usd"]
            pair[row["role"] + "_value"] += value
            pair[row["role"] + "_fees"] += row["fee_usd"]
            ratio = pair["target_quantity_btc"] / pair["source_quantity_btc"]
            self.c.check("target_funded_by_prior_source", pair["target_filled"] <= pair["source_filled"] * ratio + 1e-10, us)
            if row["role"] == "target":
                self.c.check("target_after_source_acknowledgement", pair["target_filled"] <= pair["source_acknowledged"] * ratio + 1e-10, us)
                remaining = abs(quantity) / ratio
                while remaining > 1e-12 and pair["source_lots"]:
                    lot = pair["source_lots"][0]
                    take = min(remaining, lot["quantity"])
                    pair["matched_source_value"] += take * lot["price"]
                    pair["matched_source_fees"] += take * lot["fee_per_btc"]
                    remaining -= take
                    lot["quantity"] -= take
                    if lot["quantity"] <= 1e-12:
                        pair["source_lots"].pop(0)
                self.c.check("matched_source_lots_cover_target", remaining <= 1e-10, us)
            else:
                pair["source_lots"].append({"quantity": abs(quantity), "price": row["price"],
                                            "fee_per_btc": row["fee_usd"] / abs(quantity)})
                target_order = self.get("orders", pair["target_order_id"])
                if target_order:
                    target_order["active"] = False
                    self.put("orders", pair["target_order_id"], target_order)
            unpaired = max(0.0, pair["source_filled"] - pair["target_filled"] / ratio)
            self.c.equal("fill_unpaired_quantity", row["unpaired_btc"], unpaired, us, atol=1e-10)
            self.c.check("unpaired_inventory_limit", unpaired <= self.args.max_unpaired_btc + 1e-10, us)
            self.max_unpaired = max(self.max_unpaired, unpaired)
            self.put("pairs", row["pair_id"], pair)
        self.units[symbol] += quantity
        self.c.check("fill_no_short_inventory", self.units[symbol] >= -1e-10, us)
        self.fees.add(row["fee_usd"])
        self.turnover.add(value)

    def valuation(self, row):
        us = row["us"]
        context = row.get("date", us)
        required = ("nav_usd", "cash_usd", "free_cash_usd", "posted_cash_usd", "direct_btc_value_usd",
                    "unsettled_pnl_usd", "pending_variation_usd", "treasury_value_usd", "liabilities_usd",
                    "reserved_cash_usd", "available_cash_usd", "commodity_nav_btc", "units")
        missing = [name for name in required if name not in row]
        if missing:
            raise ValueError("Missing paired valuation fields: " + ", ".join(missing))
        if self.initial_price is None or self.initial_us is None:
            raise ValueError("Valuation precedes initial_holding event")
        interval = round(self.args.interval_seconds * 1e6)
        bounds = self.archive.manifest["datasets"]["btc_trade_valuations"]
        end_us = timestamp_us(bounds["replay_end"])
        expected = min((self.initial_us // interval + 1) * interval, end_us) if self.last is None else min(self.last["us"] + interval, end_us)
        self.c.check("valuation_cadence", us == expected and (self.last is None or us > self.last["us"]), context)
        self.c.check("valuation_within_bounds", self.initial_us < us <= end_us, context)
        self.c.check("valuation_date_matches_us", timestamp_us(row["date"]) == us, context)
        for field in ("mark_us", "reported_mark_us"):
            for symbol, marked_us in row.get(field, {}).items():
                self.c.check(field + "_causal", marked_us <= us, {"date": context, "symbol": symbol})
        nav, cash = row["nav_usd"], row["cash_usd"]
        funding = cash + row["treasury_value_usd"] + row["unsettled_pnl_usd"] + row["pending_variation_usd"] - row["liabilities_usd"]
        self.c.equal("cash_segregation", cash, row["free_cash_usd"] + row["posted_cash_usd"], context)
        self.c.equal("nav_ledger_reconstruction", nav, row["direct_btc_value_usd"] + funding, context)
        self.c.equal("free_collateral_identity", row["free_collateral_usd"], funding - abs(row["futures_notional_usd"]), context)
        self.c.equal("reservation_event_reconstruction", row["reserved_cash_usd"], math.fsum(self.reservations.values()), context)
        self.c.equal("pending_variation_event_reconstruction", row["pending_variation_usd"], math.fsum(self.pending_variation.values()), context)
        for name in ("cash_usd", "free_cash_usd", "posted_cash_usd", "reserved_cash_usd", "available_cash_usd", "liabilities_usd", "treasury_value_usd"):
            self.c.check("nonnegative_" + name, row[name] >= -1e-6, context)
        self.c.check("reservations_within_free_cash", row["reserved_cash_usd"] <= row["free_cash_usd"] + 1e-6, context)
        # This selected policy has cash interest only, no Treasury-security lots.
        if abs(row["treasury_value_usd"]) < 1e-12 and abs(row["pending_variation_usd"]) < 1e-12 and abs(row["liabilities_usd"]) < 1e-12:
            margin = cash + row["unsettled_pnl_usd"] - row["futures_notional_usd"]
            available = max(0.0, min(row["free_cash_usd"], margin) - row["reserved_cash_usd"])
            posted = min(cash, max(0.0, row["futures_notional_usd"] - row["unsettled_pnl_usd"]))
            self.c.equal("cash_available_identity", row["available_cash_usd"], available, context)
            self.c.equal("posted_collateral_identity", row["posted_cash_usd"], posted, context)
        notional = abs(row["futures_notional_usd"])
        if notional > 1e-14:
            ratio = funding / notional
            self.c.equal("collateralization_ratio", row["collateralization_ratio"], ratio, context, atol=1e-9)
            self.min_ratio = min(self.min_ratio, ratio)
            self.collateral_breaches += int(ratio < 1 - 1e-9)
            self.c.check("full_collateralization", ratio >= 1 - 1e-9, context)
        else:
            self.c.check("zero_notional_ratio_null", row["collateralization_ratio"] is None, context)
        spot = row["direct_nav"] * self.initial_price
        self.c.equal("direct_value_from_units_and_spot", row["direct_btc_value_usd"], row["units"].get("SPOT", 0.0) * spot, context)
        self.c.equal("commodity_nav_identity", row["commodity_nav_btc"], nav / spot, context, atol=1e-10)
        for symbol in self.units.keys() | row["units"].keys():
            self.c.equal("inventory_from_fills", row["units"].get(symbol, 0.0), self.units.get(symbol, 0.0),
                         {"date": context, "symbol": symbol}, atol=1e-9)
        self.c.equal("fees_from_fills", row["fees_usd"], self.fees.value + self.delivery_fees.value, context)
        self.c.equal("commissions_not_double_counted", row["fees_usd"], self.commissions.value, context)
        self.c.equal("turnover_from_fills", row["turnover_usd"], self.turnover.value, context, atol=1e-5)
        actual_return = nav / self.previous_nav - 1
        self.c.equal("return_fraction", row["return_fraction"], actual_return, context, atol=1e-12)
        self.c.equal("starting_nav", row["starting_nav"], self.previous_nav / self.args.capital, context, atol=1e-12)
        self.c.equal("ending_nav", row["ending_nav"], nav / self.args.capital, context, atol=1e-12)
        self.returns.add(actual_return)
        self.log_chain.add(math.log1p(actual_return))
        previous_direct = self.last["direct_nav"] if self.last else 1.0
        self.direct_returns.add(row["direct_nav"] / previous_direct - 1)
        commodity_index = nav / (self.args.capital * row["direct_nav"])
        previous_commodity = (self.last["nav_usd"] / (self.args.capital * previous_direct)) if self.last else 1.0
        self.commodity_returns.add(commodity_index / previous_commodity - 1)
        self.peak, self.direct_peak = max(self.peak, nav), max(self.direct_peak, row["direct_nav"])
        self.commodity_peak = max(self.commodity_peak, commodity_index)
        self.drawdown = min(self.drawdown, nav / self.peak - 1)
        self.direct_drawdown = min(self.direct_drawdown, row["direct_nav"] / self.direct_peak - 1)
        self.commodity_drawdown = min(self.commodity_drawdown, commodity_index / self.commodity_peak - 1)
        self.maximum_reported_reconstruction_error = max(self.maximum_reported_reconstruction_error, abs(row["reconstruction_error_usd"]))
        self.c.check("reported_nav_reconstruction_within_gate", abs(row["reconstruction_error_usd"]) <= self.args.capital * 1e-8, context)
        day = context[:10]
        close = {"day": day, "last_valuation": context, "nav_usd": nav, "direct_nav": row["direct_nav"],
                 "commodity_nav_btc": row["commodity_nav_btc"], "fees_usd": row["fees_usd"], "turnover_usd": row["turnover_usd"]}
        if self.day_closes and self.day_closes[-1]["day"] == day:
            self.day_closes[-1] = close
        elif len(self.day_closes) < 400:
            self.day_closes.append(close)
        self.rows += 1
        self.previous_nav, self.last = nav, row

    def run(self):
        event_rows = iter(self.archive.rows("btc_trade_events"))
        event = next(event_rows, None)
        for row in self.archive.rows("btc_trade_valuations"):
            while event is not None and event["us"] <= row["us"]:
                self.event(event)
                event = next(event_rows, None)
            self.valuation(row)
        while event is not None:
            self.event(event)
            event = next(event_rows, None)
        for dataset in self.archive.manifest["datasets"]:
            if dataset not in ("btc_trade_events", "btc_trade_valuations"):
                for _ in self.archive.rows(dataset):
                    pass
        if self.last is None:
            raise ValueError("Empty valuation dataset")
        bounds = self.archive.manifest["datasets"]["btc_trade_valuations"]
        self.c.check("one_initial_holding", self.initial_count == 1, self.initial_count)
        self.c.check("replay_start_matches_initial", timestamp_us(bounds["replay_start"]) == self.initial_us)
        self.c.check("terminal_valuation", self.last["us"] == timestamp_us(bounds["replay_end"]))
        self.c.check("no_events_after_terminal", self.event_us <= self.last["us"])
        terminal_return = self.last["nav_usd"] / self.args.capital - 1
        self.c.equal("compound_return_chain", math.expm1(self.log_chain.value), terminal_return, atol=1e-10)
        pair_summary = {"submitted": 0, "matched_source_btc": 0.0, "requested_source_btc": 0.0,
                        "unresolved_pairs": 0, "maximum_legging_seconds": 0.0}
        for (encoded,) in self.db.execute("SELECT data FROM pairs"):
            pair = loads(encoded)
            pair_summary["submitted"] += 1
            pair_summary["requested_source_btc"] += pair["source_quantity_btc"]
            ratio = pair["target_quantity_btc"] / pair["source_quantity_btc"]
            matched = min(pair["source_filled"], pair["target_filled"] / ratio)
            pair_summary["matched_source_btc"] += matched
            pair_summary["unresolved_pairs"] += int(pair["source_filled"] - matched > 1e-12)
            result = pair["result"]
            self.statuses[result["status"] if result else "no_result"] += 1
            if result:
                pair_summary["maximum_legging_seconds"] = max(pair_summary["maximum_legging_seconds"], result["max_legging_seconds"])
        pair_summary["final_statuses"] = dict(self.statuses)
        pair_summary["maximum_observed_unpaired_btc"] = self.max_unpaired
        statistics = {"observations": self.rows, "initial_price_usd": self.initial_price,
            "initial_commodity_btc": self.args.capital / self.initial_price,
            "ending_nav_usd": self.last["nav_usd"], "ending_nav": self.last["nav_usd"] / self.args.capital,
            "ending_commodity_nav_btc": self.last["commodity_nav_btc"],
            "compounded_return": 100 * terminal_return, "simple_return": 100 * self.returns.total.value,
            "direct_holding_return": 100 * (self.last["direct_nav"] - 1),
            "commodity_return_pct": 100 * (self.last["nav_usd"] / (self.args.capital * self.last["direct_nav"]) - 1),
            "max_drawdown": 100 * self.drawdown, "direct_holding_max_drawdown": 100 * self.direct_drawdown,
            "commodity_max_drawdown_pct": 100 * self.commodity_drawdown,
            "fees_usd": self.fees.value + self.delivery_fees.value, "turnover_usd": self.turnover.value,
            "fills": self.kinds["fill"], "orders": self.kinds["order"],
            "min_collateralization_ratio": self.min_ratio if math.isfinite(self.min_ratio) else None,
            "collateral_breach_count": self.collateral_breaches,
            "max_reported_nav_reconstruction_error_usd": self.maximum_reported_reconstruction_error,
            "usd_interval_return_fractions": self.returns.report(),
            "direct_interval_return_fractions": self.direct_returns.report(),
            "commodity_interval_return_fractions": self.commodity_returns.report()}
        if self.args.result_json:
            result = loads(Path(self.args.result_json).read_text())
            if "summary" not in result and isinstance(result.get("result"), dict):
                result = result["result"]
            for group in ("summary", "trade_replay"):
                for key, expected in result.get(group, {}).items():
                    if key in statistics and isinstance(expected, (int, float)):
                        self.c.equal("headline_" + key, statistics[key], expected, group, atol=1e-7)
        return {"status": "failed" if self.c.failures else "passed_available_checks",
            "input": str(Path(self.args.zip).resolve()), "parameters": {
                "capital_usd": self.args.capital, "fee_bps": self.args.fee_bps,
                "interval_seconds": self.args.interval_seconds, "participation": self.args.participation},
            "verified_datasets": self.archive.verified, "statistics": statistics,
            "event_kinds": dict(self.kinds), "decision_and_risk_reasons": dict(self.reasons),
            "forecast_summaries": {k: v.report() for k, v in self.decisions.items()},
            "transfers": pair_summary, "daily_last_valuations": self.day_closes,
            **self.c.report(), "caveats": [
                "Prices are audited internal observations; the underlying exchange tape is not independently fetched or authenticated.",
                "Spot is derived from direct_nav and the initial holding price. Futures mark prices and lots are absent from valuation rows, so futures notional and unrealized P&L cannot be independently repriced here.",
                "NAV is independently reconstructed from recorded balance constituents. The reported market-P&L/interest reconstruction residual is summarized, not independently proved from every omitted tape mark or interest event.",
                "Observed-volume checks verify recorded 100% participation capacity (or CLI override), not historical order-book executability, venue costs, latency, or USDT/USD parity.",
                "Fees are counted once from fills and delivery; commission_charge is a duplicate evidence stream used only for reconciliation. This checker assumes proportional fees and zero fixed/minimum/per-contract fees.",
                "Full-frequency return statistics include the initial capital before the first, potentially partial, interval. Terminal positions are marked without a liquidation transaction.",
                "Forecast checks assume this preset's uncertainty5bps, zero minimum gain and cost buffer1. They cover reported edge arithmetic and selection thresholds, not predictive accuracy, exhaustive candidate search, or realization within this run's shorter horizon.",
                "No-candidate and pending ticks do not necessarily emit paired_decision events; decision event counts are not all scheduled decisions. Timeout reasons can overlap final partial/completed statuses.",
                "Adaptive replacement requests do not change the checked active limit until an applied arrival event. The recorded causal clocks are checked, but actual network latency and quote depth are not measured.",
                "Effective entry lease, when supplied with its clock/rate provenance, is independently recomputed from FIFO matched source fills and target fills with allocated entry fees. It is an annualized entry-basis diagnostic, not subsequent realized net BTC return.",
                "Return distributions are population moments of full audit intervals, including zero returns; sampled GUI histograms need not match them. Daily last valuations are capped at 400 days.",
                "Checksums detect archive corruption relative to its manifest, not tampering with both archive and manifest. No independent signed manifest is supplied."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip", help="Downloaded full audit ZIP")
    parser.add_argument("--capital", type=float, default=100000)
    parser.add_argument("--fee-bps", type=float, default=10)
    parser.add_argument("--interval-seconds", type=float, default=0.5)
    parser.add_argument("--participation", type=float, default=1.0)
    parser.add_argument("--max-unpaired-btc", type=float, default=0.01)
    parser.add_argument("--result-json", help="Optional server result JSON for headline comparisons")
    parser.add_argument("--output", required=True, help="JSON report destination")
    args = parser.parse_args()
    if not all(math.isfinite(x) for x in (args.capital, args.fee_bps, args.interval_seconds, args.participation, args.max_unpaired_btc)) or args.capital <= 0 or args.fee_bps < 0 or args.interval_seconds < .000001 or not 0 < args.participation <= 1 or args.max_unpaired_btc < 0:
        parser.error("Invalid numeric checking assumptions")
    archive = None
    try:
        checks = Checks()
        archive = Archive(args.zip, checks)
        with tempfile.TemporaryDirectory(prefix="paired-audit-check-") as directory:
            with sqlite3.connect(str(Path(directory) / "indexes.sqlite")) as db:
                report = Audit(args, archive, db).run()
        code = int(report["status"] != "passed_available_checks")
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, zipfile.BadZipFile, sqlite3.Error) as exc:
        report = {"status": "input_or_schema_error", "error": str(exc)}
        code = 2
    finally:
        if archive:
            archive.zip.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "report": str(output.resolve()),
                      "failure_counts": report.get("failure_counts", {}), "error": report.get("error")}, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
