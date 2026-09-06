#!/usr/bin/env python3
"""Run the saved full-long strategy as 100% BTC through the canonical GUI API.

Print a compact reproducible audit, never a full minute-by-minute result dump.
"""
import argparse
import json
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import silver_strategy_gui as gui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    payload = json.loads((ROOT / "strategies/full silver long gradual").read_text())["parameters"]
    nested = payload.get("commodity_parameters", {})
    if isinstance(nested, str):
        nested = json.loads(nested)
    btc = dict(nested.get("silver", {}))
    btc.update(slv_expense="0", futures_contract_type="inverse", enable_short_book="false")
    payload["commodity_parameters"] = {"btc": btc}
    for product in gui.PRODUCTS:
        payload[f"weight_{product}"] = "100" if product == "btc" else "0"
    payload.update(weight_treasury="0", execution_interval_seconds=args.interval)
    started = time.monotonic()
    gui.MARKETS = gui.build_markets(ROOT, {"btc"})
    market = gui.MARKETS["btc"]
    result = gui.result(payload)
    encoded_bytes = sum(len(part.encode("utf-8")) for part in
                        json.JSONEncoder(separators=(",", ":"), allow_nan=False).iterencode(result))
    print(json.dumps({
        "strategy": "full silver long gradual mapped to 100% BTC; no direct-holding expense",
        "spot_proxy": gui.PRODUCTS["btc"]["spot_source"],
        "market_observations": len(market[0]),
        "first_mark": min(market[0]).isoformat(),
        "last_mark": max(market[0]).isoformat(),
        "execution_interval_seconds": args.interval,
        "summary": result["summary"],
        "result_json_mib": round(encoded_bytes / 1024**2, 2),
        "fits_deployed_256_mib_result_limit": encoded_bytes <= 268435456,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
