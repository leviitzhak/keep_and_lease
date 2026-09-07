#!/usr/bin/env python3
"""Create an immutable, batch-written Parquet copy of the downloaded pilot day."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trade_data_store import convert

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("work/btc-trade-pilot/2026-06-25"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = convert(args.data, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "source_manifest"}, indent=2))
