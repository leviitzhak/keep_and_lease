#!/usr/bin/env python3
"""Independently validate a streamed trade-pilot order/fill audit."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    report = json.loads((args.run / "report.json").read_text())
    active, last_trade = {}, {}
    counts = {"rows": 0, "orders": 0, "fills": 0, "valuations": 0}
    last_us, last_valuation = -1, report["start_us"]
    def check(condition, message):
        if not condition:
            raise ValueError(message)
    with gzip.open(args.run / "audit.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            counts["rows"] += 1
            check(row["us"] >= last_us, "Audit not chronological")
            last_us = row["us"]
            kind = row["kind"]
            if kind == "order":
                active[row["order_id"]] = [row, 0., 0.]
                counts["orders"] += 1
            elif kind == "fill":
                order, quantity, value = active[row["order_id"]]
                q = abs(row["signed_btc"])
                check(row["us"] > order["eligible_after_us"], "Early fill")
                check(row["signed_btc"] * order["signed_btc"] > 0, "Wrong fill direction")
                check(row["side"] == ("buy" if row["signed_btc"] > 0 else "sell"), "Wrong aggressor side")
                check(q <= row["observed_btc"] * report["participation"] + 1e-12, "Excess print participation")
                check(last_trade.get(row["symbol"]) != row["trade_id"], "Reused trade capacity")
                last_trade[row["symbol"]] = row["trade_id"]
                check(quantity + q <= abs(order["signed_btc"]) + 1e-10, "Order overfilled")
                active[row["order_id"]][1:] = [quantity + q, value + q * row["price"]]
                counts["fills"] += 1
            elif kind == "order_end":
                order, quantity, value = active.pop(row["order_id"])
                check(math.isclose(quantity, row["filled_btc"], abs_tol=1e-12), "Fill total mismatch")
                check(quantity == 0 if row["vwap"] is None else math.isclose(value / quantity, row["vwap"], rel_tol=1e-12), "VWAP mismatch")
            elif kind == "valuation":
                check(row["us"] - last_valuation <= 1_000_000, "Missing second")
                check(all(t <= row["us"] for t in row["mark_us"].values()), "Future valuation mark")
                check(abs(row["reconstruction_error_usd"]) <= report["capital_usd"] * 1e-8, "NAV reconstruction failure")
                last_valuation = row["us"]
                counts["valuations"] += 1
    check(not active and last_valuation == report["end_us"], "Incomplete audit")
    check(counts["orders"] == report["orders"] and counts["fills"] == report["fills"], "Summary differs from audit")
    with (args.run / "audit.jsonl.gz").open("rb") as stream:
        counts["audit_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    counts["status"] = "passed"
    (args.run / "audit-validation.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
