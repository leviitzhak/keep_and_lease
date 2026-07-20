#!/usr/bin/env python3
"""Local browser GUI for the parameterized silver lease strategy backtest."""

import json
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backtest_silver_lease_strategy import Parameters, build_market, run_backtest

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "silver_strategy_gui.html"
MARKET = None


def number(payload, name, default, low=None, high=None):
    value = float(payload.get(name, default))
    if low is not None and value < low:
        raise ValueError(f"{name} must be at least {low}")
    if high is not None and value > high:
        raise ValueError(f"{name} must be at most {high}")
    return value


def parameters(payload):
    # Rates and weights arrive as percentages from the GUI.
    pct = lambda name, default: number(payload, name, default) / 100
    p = Parameters(
        min_days=int(number(payload, "min_days", 10, 1, 2000)),
        slv_expense=pct("slv_expense", 0.5),
        slv_start_rate=pct("slv_start_rate", 0.5),
        slv_full_rate=pct("slv_full_rate", -1.5),
        positive_entry_rate=pct("positive_entry_rate", 0),
        positive_full_rate=pct("positive_full_rate", 15),
        long_contract_selection=str(payload.get(
            "long_contract_selection", "shortest_maturity")),
        max_long_future=pct("max_long_future", 50),
        negative_short_start_rate=pct("negative_short_start_rate", -0.5),
        negative_short_full_rate=pct("negative_short_full_rate", -15),
        max_short_fraction_of_slv=pct("max_short_fraction_of_slv", 50),
        negative_maturities=int(number(payload, "negative_maturities", 3, 1, 20)),
        max_share_per_maturity=pct("max_share_per_maturity", 50),
        short_maturity_bonus_per_year=pct("short_maturity_bonus_per_year", 0.4),
        bond_mode=str(payload.get("bond_mode", "accrual")),
        treasury_asset=str(payload.get("treasury_asset", "matched_maturity")),
    )
    if p.bond_mode not in {"accrual", "zero_coupon_mtm"}:
        raise ValueError("Invalid bond mode")
    if p.treasury_asset not in {"matched_maturity", "sgov_proxy"}:
        raise ValueError("Invalid Treasury instrument")
    if p.long_contract_selection not in {"shortest_maturity", "highest_lease_rate"}:
        raise ValueError("Invalid long contract selection")
    if p.slv_start_rate <= p.slv_full_rate:
        raise ValueError("SLV transition start must exceed its full-allocation rate")
    if p.negative_short_start_rate <= p.negative_short_full_rate:
        raise ValueError("Short entry threshold must exceed its full-allocation rate")
    if p.positive_full_rate <= 0:
        raise ValueError("Positive full-allocation rate must be positive")
    if p.positive_entry_rate >= p.positive_full_rate:
        raise ValueError("Long entry rate must be below its full-allocation rate")
    return p


def position_change_stats(rows):
    if len(rows) < 2:
        return {"avg_daily_notional_change_pct": 0.0,
                "avg_daily_futures_notional_change_pct": 0.0}
    all_changes = []
    futures_changes = []
    for previous, current in zip(rows, rows[1:]):
        slv_change = abs(current["slv_weight_pct"] - previous["slv_weight_pct"])
        treasury_change = abs(current["treasury_weight_pct"] - previous["treasury_weight_pct"])
        long_change = abs(current["long_futures_notional_pct"] -
                          previous["long_futures_notional_pct"])
        short_change = abs(current["short_futures_notional_pct"] -
                           previous["short_futures_notional_pct"])
        all_changes.append(slv_change + treasury_change + long_change + short_change)
        futures_changes.append(long_change + short_change)
    return {
        "avg_daily_notional_change_pct": sum(all_changes) / len(all_changes),
        "avg_daily_futures_notional_change_pct": (
            sum(futures_changes) / len(futures_changes)),
    }


def futures_price_series(rows, contracts):
    """Return sparse, chart-ready prices for every contract on output dates."""
    dates = {row["date"]: index for index, row in enumerate(rows)}
    result = {}
    for symbol, prices in contracts.items():
        points = [[dates[day.isoformat()], price] for day, price in prices.items()
                  if day.isoformat() in dates]
        if points:
            result[symbol] = sorted(points)
    return result


def futures_diagnostics(rows, by_day, p):
    """Return per-date futures details for the all-prices chart tooltip."""
    result = []
    for row in rows:
        execution_day = date.fromisoformat(row["execution_date"])
        candidates = by_day.get(execution_day, [])
        eligible = [x for x in candidates if x["days"] >= p.min_days]
        if not eligible:
            result.append({"available": 0})
            continue
        lowest_lease = min(eligible, key=lambda x: (x["lease"], x["days"]))
        highest_lease = max(eligible, key=lambda x: (x["lease"], -x["days"]))
        lowest_premium = min(x["premium"] for x in eligible)
        highest_premium = max(x["premium"] for x in eligible)
        result.append({
            "available": len(eligible),
            "lowest_lease": contract_summary(lowest_lease),
            "highest_lease": contract_summary(highest_lease),
            "lowest_premium_pct": 100 * lowest_premium,
            "highest_premium_pct": 100 * highest_premium,
        })
    return result


def contract_summary(contract):
    return {
        "symbol": contract["symbol"],
        "maturity_days": contract["days"],
        "price": contract["future"],
        "premium_pct": 100 * contract["premium"],
        "lease_pct": 100 * contract["lease"],
    }


def result(payload):
    p = parameters(payload)
    rows, missing = run_backtest(*MARKET, p)
    if not rows:
        raise ValueError("No observations remain with these parameters")
    stride = max(1, (len(rows) + 4999) // 5000)
    sampled = rows[::stride]
    if sampled[-1] is not rows[-1]:
        sampled.append(rows[-1])
    fields = ["date", "interval_return_pct", "simple_cumulative_return_pct",
              "compounded_return_pct", "slv_weight_pct", "treasury_weight_pct",
              "long_futures_notional_pct", "short_futures_notional_pct",
              "long_weighted_maturity_days", "short_weighted_maturity_days",
              "short_shortest_maturity_days", "short_longest_maturity_days",
              "long_weighted_lease_rate_pct", "short_weighted_lease_rate_pct",
              "long_book_interval_return_pct", "short_book_interval_return_pct",
              "long_book_cumulative_return_pct", "short_book_cumulative_return_pct",
              "long_futures_daily_return_pct", "short_futures_daily_return_pct",
              "slv_daily_return_pct", "treasury_daily_return_pct",
              "long_futures_cumulative_return_pct", "short_futures_cumulative_return_pct",
              "slv_cumulative_return_pct", "treasury_cumulative_return_pct",
              "long_futures_compounded_return_pct", "short_futures_compounded_return_pct",
              "slv_compounded_return_pct", "treasury_compounded_return_pct",
              "slv_price", "long_weighted_future_price", "short_weighted_future_price",
              "treasury_position_price_index", "sgov_proxy_price_index",
              "long_weighted_forward_premium_pct",
              "short_weighted_forward_premium_pct", "cash_plus_slv_weight_pct",
              "available_futures_min_maturity_days",
              "available_futures_max_maturity_days"]
    change_stats = position_change_stats(rows)
    return {
        "series": [[row[k] for k in fields] for row in sampled],
        "fields": fields,
        "futures_prices": futures_price_series(sampled, MARKET[1]),
        "futures_diagnostics": futures_diagnostics(sampled, MARKET[3], p),
        "summary": {
            "start": rows[0]["date"], "end": rows[-1]["date"],
            "observations": len(rows), "missing_intervals": len(missing),
            "missing_return_events": missing,
            "simple_return": rows[-1]["simple_cumulative_return_pct"],
            "compounded_return": rows[-1]["compounded_return_pct"],
            "ending_nav": rows[-1]["nav"],
            **change_stats,
        },
    }


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in {"/", "/index.html"}:
            data = PAGE.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/run":
            self.send_error(404); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            body, status = json.dumps(result(payload), allow_nan=False).encode(), 200
        except Exception as exc:
            body, status = json.dumps({"error": str(exc)}).encode(), 400
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(fmt % args)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print("Loading market data...")
    MARKET = build_market(ROOT)
    print(f"Open http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
