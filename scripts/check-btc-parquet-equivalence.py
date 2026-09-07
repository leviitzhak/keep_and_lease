#!/usr/bin/env python3
"""Compare every engine-facing Parquet event with the independently parsed raw tape."""
import argparse
import hashlib
import heapq
import json
import runpy
import sys
import time
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trade_data_store import ParquetTradeStore


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "work/btc-trade-pilot/2026-06-25")
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = runpy.run_path(str(ROOT / "scripts/check-btc-trade-pilot.py"))
    source = json.loads((args.data / "manifest.json").read_text())
    store = ParquetTradeStore(args.parquet)
    if hashlib.sha256((args.data / "manifest.json").read_bytes()).hexdigest() != store.manifest["source_manifest_sha256"]:
        raise ValueError("Raw and normalized inputs have different provenance")
    streams = [raw["spot_trades"](args.data / source["spot"]["path"])]
    streams += [raw["future_trades"](s, args.data / item["path"]) for s, item in sorted(source["futures"].items())]
    count, started, digest = 0, time.monotonic(), hashlib.sha256()
    for left, right in zip_longest(heapq.merge(*streams, key=lambda t: (t.us, t.symbol)), store.trades()):
        if left != right:
            raise ValueError(f"Event mismatch at index {count}: {left!r} != {right!r}")
        digest.update((repr(left) + "\n").encode())
        count += 1
    report = dict(status="passed", events=count, event_stream_sha256=digest.hexdigest(),
                  wall_seconds=time.monotonic() - started, parquet_manifest_sha256=hashlib.sha256(store.manifest_bytes).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
