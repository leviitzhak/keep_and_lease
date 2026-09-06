#!/usr/bin/env python3
"""Build the immutable SQLite market-data cache used by server images."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data_store import build_database


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print(build_database(ROOT, target))
