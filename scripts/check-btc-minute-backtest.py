#!/usr/bin/env python3
"""Audit the saved full-long strategy as 100% BTC with regular futures by default.

The default path measures the canonical GUI result. --engine-only streams every
interval through the same accounting engine, retaining bounded diagnostics.
Deribit inverse-contract quotes proxy hypothetical regular USD futures prices;
--stale-mark-control is a non-executable research sensitivity, never a data fix.
"""
import argparse
import gzip
import json
import resource
import sys
import time
from pathlib import Path
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import silver_strategy_gui as gui


def btc_payload(interval=60, contract_type="regular", reactivity="same_day", execution_model="observed"):
    """Use the preserved regular BTC preset, derived from the saved silver sleeve."""
    payload = json.loads((ROOT / "strategies/full-btc-long-gradual-1m-regular.json").read_text())["parameters"]
    nested = payload.get("commodity_parameters", {})
    if isinstance(nested, str):
        nested = json.loads(nested)
    btc = dict(nested["btc"])
    btc.update(slv_expense="0", futures_contract_type=contract_type, execution_model=execution_model,
               enable_short_book="false")
    payload["commodity_parameters"] = {"btc": btc}
    for product in gui.PRODUCTS:
        payload[f"weight_{product}"] = "100" if product == "btc" else "0"
    payload.update(weight_treasury="0", execution_interval_seconds=interval,
                   reactivity=reactivity, futures_contract_type=contract_type,
                   slv_expense="0", enable_short_book="false")
    return payload


def spot_linked_stale_control(market):
    """Research sensitivity only: carry last observed F/S, not a tradable quote.

    No future prices or trades enter this control. The initial ratio is seeded
    from the first available candle and spot when a prior trade is unavailable.
    Mutates this freshly built research market, never the imported source files.
    """
    spot, contracts, _, curves = market
    ratios = {}
    changed = 0
    for day in sorted(curves):
        for item in curves[day]:
            symbol = item["symbol"]
            if item["volume"] > 0 or symbol not in ratios:
                ratios[symbol] = item["future"] / spot[day]
            else:
                item["future"] = contracts[symbol][day] = ratios[symbol] * spot[day]
                item["premium"] = ratios[symbol] - 1
                item["lease"] = item["rate"] - item["premium"] * 365 / item["days"]
                changed += 1
    return changed


def engine_audit(market, payload, audit_path=None):
    """Full-resolution accounting with bounded summary retention."""
    stats = {"intervals": 0, "held_contract_intervals": 0,
             "held_zero_volume_intervals": 0, "trade_events": 0,
             "zero_volume_trade_events": 0, "turnover_pct": 0.0,
             "zero_volume_turnover_pct": 0.0,
             "futures_contribution_sum_pct": 0.0,
             "zero_volume_futures_contribution_sum_pct": 0.0,
             "zero_volume_basis_contribution_sum_pct": 0.0,
             "max_nav_reconstruction_difference": 0.0}
    top = []
    stream = gzip.open(audit_path, "wt", encoding="utf-8") if audit_path else None
    first, last, direct_nav = None, None, 1.0

    def consume(row):
        nonlocal first, last, direct_nav
        first = first or row
        last = row
        direct_nav *= 1 + row["slv_daily_return_pct"] / 100
        stats["intervals"] += 1
        day = gui.parse_date(row["date"])
        curve = {c["symbol"]: c for c in market[3][day]}
        stats["max_nav_reconstruction_difference"] = max(
            stats["max_nav_reconstruction_difference"],
            abs(row["nav_reconstruction_difference"]))
        for trade in row["long_futures_trade_details"]:
            stats["trade_events"] += 1
            stats["turnover_pct"] += trade["size_pct"]
            if curve[trade["symbol"]]["volume"] == 0:
                stats["zero_volume_trade_events"] += 1
                stats["zero_volume_turnover_pct"] += trade["size_pct"]
        for item in row["holding_ledger"]:
            if item["holding_type"] != "future":
                continue
            contribution = 100 * item["pnl_value"] / row["starting_nav"]
            stats["held_contract_intervals"] += 1
            stats["futures_contribution_sum_pct"] += contribution
            if curve[item["name"]]["volume"] == 0:
                stats["held_zero_volume_intervals"] += 1
                stats["zero_volume_futures_contribution_sum_pct"] += contribution
                stats["zero_volume_basis_contribution_sum_pct"] += (
                    contribution - item["position_pct"] * row["slv_daily_return_pct"] / 100)
        if len(top) < 5 or row["interval_return_pct"] > top[-1]["return_pct"]:
            top.append({"date": row["date"], "exit_date": row["exit_date"],
                        "return_pct": row["interval_return_pct"],
                        "spot_return_pct": row["slv_daily_return_pct"],
                        "holdings": [{**h, "entry_candle_volume": curve[h["symbol"]]["volume"]}
                                     for h in row["held_futures"]]})
            top.sort(key=lambda r: r["return_pct"], reverse=True)
            del top[5:]
        if stream:
            stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")

    try:
        _, missing = gui.run_backtest(
            *market, gui.parameters(gui.product_payload(payload, "btc")),
            row_sink=consume, retain_fields=())
    finally:
        if stream:
            stream.close()
    if last is None:
        raise ValueError("No intervals calculated")
    return {"summary": {"start": first["date"], "end": last["exit_date"],
                        "observations": stats["intervals"], "missing_intervals": len(missing),
                        "compounded_return": last["compounded_return_pct"],
                        "direct_holding_return": 100 * (direct_nav - 1)},
            "execution_audit": stats, "largest_positive_intervals": top,
            "audit_jsonl_gz": str(audit_path) if audit_path else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--contract-type", choices=("regular", "inverse"), default="regular")
    parser.add_argument("--reactivity", choices=("same_day", "next_day"), default="same_day",
                        help="next_day means the next execution observation (one minute here)")
    parser.add_argument("--engine-only", action="store_true",
                        help="stream complete rows into audit summaries without building GUI output")
    parser.add_argument("--execution-model", choices=("observed", "legacy_close"), default="observed")
    parser.add_argument("--chunk-output", type=Path, help="Store the complete immutable audit in a new directory")
    parser.add_argument("--server-engine", action="store_true", help="Load all deployed engine markets and use the worker's incremental result encoder")
    parser.add_argument("--fee-bps", type=float, default=0, help="Execution fee per side on actual futures and direct BTC changes")
    parser.add_argument("--half-spread-bps", type=float, default=0)
    parser.add_argument("--slippage-bps", type=float, default=0)
    parser.add_argument("--start", help="UTC start observation boundary")
    parser.add_argument("--end", help="UTC final valuation boundary")
    parser.add_argument("--days", type=int, help="explicit research window measured from first mark")
    parser.add_argument("--stale-mark-control", action="store_true",
                        help="NON-EXECUTABLE sensitivity: carry F/S on zero-volume candles")
    parser.add_argument("--audit-output", type=Path, help="stream every engine audit row as JSONL gzip")
    parser.add_argument("--report", type=Path, help="save the compact diagnostic report")
    parser.add_argument("--profile-output", action="store_true", help="size GUI output sections")
    args = parser.parse_args()
    if args.days is not None and args.days <= 0:
        parser.error("--days must be positive")
    if args.audit_output and not args.engine_only:
        parser.error("--audit-output requires --engine-only")
    payload = btc_payload(args.interval, args.contract_type, args.reactivity, args.execution_model)
    payload["commodity_parameters"]["btc"].update(trading_fee_bps=args.fee_bps,
        half_spread_bps=args.half_spread_bps, slippage_bps=args.slippage_bps)
    payload.update(backtest_start=args.start or "", backtest_end=args.end or "")
    bounds = gui.backtest_bounds(payload)
    started = time.monotonic()
    if args.server_engine:
        from server.engine import StrategyEngine
        engine = StrategyEngine()
        engine.load()
    else:
        gui.MARKETS = gui.build_markets(ROOT, {"btc"})
    market = gui.period_market(gui.MARKETS["btc"], *bounds)
    gui.MARKETS["btc"] = market
    if args.days:
        stop = min(market[0]) + timedelta(days=args.days)
        market = ({d:v for d,v in market[0].items() if d < stop}, market[1], market[2],
                  {d:v for d,v in market[3].items() if d < stop})
        gui.MARKETS["btc"] = market
    changed = spot_linked_stale_control(market) if args.stale_mark_control else 0
    audit = None
    if args.chunk_output:
        from backtest_audit import AuditCollection, DirectoryAuditStore
        audit = AuditCollection(DirectoryAuditStore(args.chunk_output),
            base_url="local-audit", provenance={"parameters": payload})
    result = (engine_audit(market, payload, args.audit_output)
              if args.engine_only else gui.result(payload, audit))
    if args.server_engine and not args.engine_only:
        from server.cloud import GcsResultStore
        # Use the exact worker encoder with a bounded local upload destination.
        class Blob:
            def upload_from_string(self, data, **kwargs):
                if args.chunk_output:
                    (args.chunk_output / "worker-result.json.gz").write_bytes(data)
        class Bucket:
            def blob(self, name):
                return Blob()
        class Client:
            def bucket(self, name):
                return Bucket()
        encoded_result = GcsResultStore(Client(), "validation").write_json(
            "a" * 32, result, {}, 268435456)
    def json_bytes(value):
        return sum(len(part.encode("utf-8")) for part in
                   json.JSONEncoder(separators=(",", ":"), allow_nan=False).iterencode(value))
    encoded_bytes = None if args.engine_only else json_bytes(result)
    profile = {}
    if args.profile_output and not args.engine_only:
        profile = {key: round(json_bytes(value) / 1024**2, 2)
                   for key, value in result.items() if key != "commodity_sleeves"}
        profile["btc_sleeve"] = {key: round(json_bytes(value) / 1024**2, 2)
                                  for key, value in result["commodity_sleeves"]["btc"].items()}
    report = {
        "strategy": "full silver long gradual mapped to 100% BTC; no direct-holding expense",
        "parameters": payload,
        "spot_proxy": gui.PRODUCTS["btc"]["spot_source"],
        "market_observations": len(market[0]),
        "first_mark": min(market[0]).isoformat(),
        "last_mark": max(market[0]).isoformat(),
        "execution_interval_seconds": args.interval,
        "loaded_markets": sorted(gui.MARKETS),
        "worker_encoder": args.server_engine and not args.engine_only,
        "futures_contract_type": args.contract_type,
        "reactivity": args.reactivity,
        "stale_mark_control": args.stale_mark_control,
        "research_control_changed_marks": changed,
        "calculation_path": "streamed_engine_audit" if args.engine_only else "canonical_gui",
        "summary": result["summary"],
        "execution_audit": result.get("execution_audit") or result.get("commodity_sleeves", {}).get("btc", {}).get("execution"),
        "audit_chunks": {k: {"rows": v["rows"], "chunks": len(v["chunks"]),
            "compressed_mib": round(sum(c["compressed_bytes"] for c in v["chunks"])/1024**2, 2)}
            for k, v in result.get("audit", {}).get("datasets", {}).items()},
        "largest_positive_intervals": result.get("largest_positive_intervals"),
        "result_json_mib": round(encoded_bytes / 1024**2, 2) if encoded_bytes is not None else None,
        "output_sections_mib": profile,
        "fits_deployed_256_mib_result_limit": encoded_bytes <= 268435456 if encoded_bytes is not None else None,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }
    text = json.dumps(report, indent=2, default=str)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
