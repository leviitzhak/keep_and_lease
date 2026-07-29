#!/usr/bin/env python3
"""Runnable GUI preview for PR #15 anchored maturity scoring.

This entry point reuses the existing market loader and backtest engine, while
patching the active maturity score path to the canonical two-anchor model in
``maturity_scoring.py``.  It is intentionally isolated so the production GUI
can remain stable until the preview has been reviewed.
"""

import json
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import backtest_silver_lease_strategy as engine
from maturity_scoring import BoundaryAnchors, RelativeAdjustment, adjusted_score

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "pr15_preview.html"
MARKET = None


def _number(payload, name, default):
    raw = payload.get(name, default)
    return float(default if raw is None or str(raw).strip() == "" else raw)


def preview_parameters(payload):
    """Build ordinary engine parameters and attach preview-only anchor fields."""
    pct = lambda name, default: _number(payload, name, default) / 100.0
    p = engine.Parameters(
        min_days=int(_number(payload, "min_days", 10)),
        positive_entry_rate=pct("positive_entry_rate", 0),
        positive_full_rate=pct("positive_full_rate", 15),
        long_contract_selection=str(payload.get(
            "long_contract_selection", "weighted_lease_rate")),
        max_long_future=pct("max_long_future", 50),
        negative_short_start_rate=pct("negative_short_start_rate", -0.5),
        negative_short_full_rate=pct("negative_short_full_rate", -15),
        max_short_fraction_of_slv=pct("max_short_fraction_of_slv", 50),
        short_contract_selection=str(payload.get(
            "short_contract_selection", "weighted_lease_rate")),
        bond_mode=str(payload.get("bond_mode", "accrual")),
    )
    p.long_boundary = BoundaryAnchors(
        _number(payload, "long_anchor_1_days", 30),
        pct("long_anchor_1_rate", 0.5),
        _number(payload, "long_anchor_2_days", 365),
        pct("long_anchor_2_rate", 5.0),
    )
    p.short_boundary = BoundaryAnchors(
        _number(payload, "short_anchor_1_days", 30),
        pct("short_anchor_1_rate", 0.5),
        _number(payload, "short_anchor_2_days", 365),
        pct("short_anchor_2_rate", 5.0),
    )
    p.long_adjustment = RelativeAdjustment(
        strength=_number(payload, "long_relative_strength", 0.5),
        rate_scale=pct("long_rate_scale", 1.0),
        clip=_number(payload, "long_relative_clip", 2.0),
    )
    p.short_adjustment = RelativeAdjustment(
        strength=_number(payload, "short_relative_strength", 0.5),
        rate_scale=pct("short_rate_scale", 1.0),
        clip=_number(payload, "short_relative_clip", 2.0),
    )
    return p


def anchored_maturity_score(base_score, contract, p, direction):
    """Drop-in replacement for the legacy slope/intercept score function."""
    boundary = p.long_boundary if direction == "long" else p.short_boundary
    adjustment = p.long_adjustment if direction == "long" else p.short_adjustment
    return adjusted_score(
        base_score=base_score,
        rate=contract["lease"],
        maturity=contract["days"],
        boundary=boundary,
        adjustment=adjustment,
        direction=direction,
    )


def run_preview(payload):
    global MARKET
    if MARKET is None:
        MARKET = engine.build_market(ROOT)
    p = preview_parameters(payload)
    original = engine.maturity_line_adjusted_score
    engine.maturity_line_adjusted_score = anchored_maturity_score
    try:
        rows, missing = engine.run_backtest(*MARKET, p)
    finally:
        engine.maturity_line_adjusted_score = original
    if not rows:
        raise ValueError("No observations remain with these parameters")
    stride = max(1, (len(rows) + 2999) // 3000)
    sampled = rows[::stride]
    if sampled[-1] is not rows[-1]:
        sampled.append(rows[-1])
    fields = (
        "date", "compounded_return_pct", "simple_cumulative_return_pct",
        "interval_return_pct", "long_futures_notional_pct",
        "short_futures_notional_pct", "long_weighted_maturity_days",
        "short_weighted_maturity_days", "long_weighted_lease_rate_pct",
        "short_weighted_lease_rate_pct",
    )
    compact = [{key: row.get(key) for key in fields} for row in sampled]
    return {
        "rows": compact,
        "summary": {
            "start": rows[0]["date"],
            "end": rows[-1]["date"],
            "observations": len(rows),
            "compounded_return_pct": rows[-1]["compounded_return_pct"],
            "simple_return_pct": rows[-1]["simple_cumulative_return_pct"],
            "ending_nav": rows[-1]["nav"],
            "missing_intervals": len(missing),
        },
        "resolved": {
            "long_boundary": asdict(p.long_boundary),
            "short_boundary": asdict(p.short_boundary),
            "long_adjustment": asdict(p.long_adjustment),
            "short_adjustment": asdict(p.short_adjustment),
        },
    }


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html", "/pr15_preview.html"):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/run":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = run_preview(payload)
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
        except Exception as exc:  # preview endpoint should return actionable errors
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = engine.argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"PR15 preview: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
