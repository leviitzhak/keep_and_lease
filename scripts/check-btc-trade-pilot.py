#!/usr/bin/env python3
"""Replay the saved full BTC long gradual rule on a one-second research clock.

Every raw trade remains an execution/valuation event. CLI research only: not a
new GUI engine, no activation of the trade cache as the production data provider.
"""
import argparse
import csv
import gzip
import hashlib
import heapq
import io
import json
import resource
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backtest_silver_lease_strategy as strategy
import silver_strategy_gui as gui
from trade_replay import TapeAccount, Trade


def timestamp_us(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000_000)


def spot_trades(path):
    with zipfile.ZipFile(path) as zipped:
        name, = zipped.namelist()
        with zipped.open(name) as stream:
            for row in csv.reader(io.TextIOWrapper(stream)):
                ts = int(row[4])
                yield Trade(ts * 1000 if ts < 10 ** 14 else ts, "SPOT", float(row[1]),
                            float(row[2]), "sell" if row[5].lower() == "true" else "buy", row[0])


def future_trade(symbol, row):
    return Trade(row["timestamp"] * 1000, symbol, row["price"],
                 row["amount"] / row["price"], row["direction"], row["trade_id"],
                 not any(row.get(k) for k in ("block_trade_id", "block_rfq_id", "combo_id")))


def future_trades(symbol, path):
    with gzip.open(path, "rt") as stream:
        for line in stream:
            yield future_trade(symbol, json.loads(line))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "work/btc-trade-pilot/2026-06-25")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capital", type=float, default=1)
    parser.add_argument("--participation", type=float, default=1, help="Fraction of eligible print volume, (0,1]")
    parser.add_argument("--delay-ms", type=int, default=0)
    parser.add_argument("--fee-bps", type=float, default=0)
    args = parser.parse_args()
    started = time.monotonic()
    manifest = json.loads((args.data / "manifest.json").read_text())
    if args.output.exists():
        raise ValueError("Use a new audit output directory; completed evidence is immutable")
    args.output.mkdir(parents=True)
    for info in [manifest["spot"], *manifest["futures"].values()]:
        with (args.data / info["path"]).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Input checksum mismatch")
    preset_path = ROOT / "strategies/research-btc-long-gradual-1s-trade-pilot.json"
    payload = json.loads(preset_path.read_text())["parameters"]
    p = gui.parameters(gui.product_payload(payload, "btc"))
    if p.bond_mode != "accrual" or p.treasury_allocation_mode != "shortest_rolling" or p.enable_short_book:
        raise ValueError("Pilot requires the saved long-only, shortest Treasury accrual preset")
    rates = strategy.read_rates(ROOT)
    start, end = timestamp_us(manifest["start"]), timestamp_us(manifest["end"])
    if end - start != 86400 * 1_000_000:
        raise ValueError("Pilot accepts exactly one UTC day")
    audit_path = args.output / "audit.jsonl.gz"
    with gzip.open(audit_path, "wt", encoding="utf-8") as audit:
        def emit(row):
            audit.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
        account = TapeAccount(args.capital, args.participation, args.delay_ms * 1000, args.fee_bps, emit)
        streams = [spot_trades(args.data / manifest["spot"]["path"])]
        streams += [future_trades(s, args.data / info["path"]) for s, info in sorted(manifest["futures"].items())]
        tape = iter(heapq.merge(*streams, key=lambda t: (t.us, t.symbol)))
        event = next(tape, None)
        warmup_events = 0
        while event and event.symbol != "SPOT":
            account.marks[event.symbol] = event
            warmup_events += 1
            event = next(tape, None)
        if event is None:
            raise ValueError("No spot trades")
        initial_us, initial_price = event.us, event.price
        account.initialize_spot(event)
        for symbol, info in manifest["futures"].items():
            if info["seed"] and symbol not in account.marks:
                seed = future_trade(symbol, info["seed"])
                if seed.us >= start:
                    raise ValueError("Seed is not causal")
                account.marks[symbol] = seed
        event = next(tape, None)
        count, decisions, no_fresh_curve = 1 + warmup_events, 0, 0
        initial_day = datetime.fromtimestamp(initial_us / 1_000_000, timezone.utc).replace(tzinfo=None)
        account.rate = strategy.usd_rate(rates, initial_day, strategy.TENORS[0][0]) or 0.0
        max_error, minimum_cash, previous_nav = 0.0, 0.0, account.nav
        for tick in range((initial_us // 1_000_000 + 1) * 1_000_000, end + 1, 1_000_000):
            while event and event.us <= tick and event.us < end:
                account.on_trade(event)
                count += 1
                minimum_cash = min(minimum_cash, account.cash)
                event = next(tape, None)
            account.accrue(tick)
            day = datetime.fromtimestamp(tick / 1_000_000, timezone.utc).replace(tzinfo=None)
            account.rate = strategy.usd_rate(rates, day, strategy.TENORS[0][0]) or 0.0
            spot = account.marks["SPOT"].price
            candidates = []
            for symbol, info in manifest["futures"].items():
                mark = account.marks.get(symbol)
                days = (timestamp_us(info["expiry"]) - tick) / (86400 * 1_000_000)
                if mark is None or not mark.executable or days <= 0 or tick - mark.us > p.max_quote_age_seconds * 1_000_000:
                    continue
                rate = strategy.usd_rate(rates, day, days)
                if rate is None:
                    continue
                premium = mark.price / spot - 1
                candidates.append(dict(symbol=symbol, days=days, future=mark.price, spot=spot,
                                       premium=premium, rate=rate, lease=rate - premium * 365 / days,
                                       volume=mark.btc))
            if account.nav <= 0:
                raise ValueError("Insolvent pilot account")
            previous = {"base_longs": {s: q * account.marks[s].price / account.nav
                                        for s, q in account.units.items() if s != "SPOT" and q > 0},
                        "shorts": {}}
            desired = strategy.positions_for_day(candidates, p, previous, elapsed_days=1 / 86400)
            targets = None
            if tick < end:
                decisions += 1
                if desired and tick - account.marks["SPOT"].us <= p.max_quote_age_seconds * 1_000_000:
                    targets = {s: w * account.nav / account.marks[s].price for s, w in desired["base_longs"].items()}
                    targets["SPOT"] = desired["slv"] * account.nav / spot
                    account.submit_targets(tick, targets)
                else:
                    # Missing fresh signals do not imply liquidation or an invented price.
                    account.cancel(tick, "no_fresh_signal")
                    no_fresh_curve += 1
            else:
                account.cancel(tick, "end_of_window")
            error = account.reconstruction_error()
            max_error = max(max_error, abs(error))
            emit(dict(kind="valuation", us=tick, nav_usd=account.nav, cash_usd=account.cash,
                      units=account.units, targets=targets, return_fraction=account.nav / previous_nav - 1,
                      mark_ids={s: m.identifier for s, m in account.marks.items()},
                      mark_us={s: m.us for s, m in account.marks.items()},
                      reconstruction_error_usd=error))
            previous_nav = account.nav
        expected_trades = manifest["spot"]["rows"] + sum(x["rows"] for x in manifest["futures"].values())
        # Trades before the first spot print were causal warm-up marks only.
        if count != expected_trades:
            raise ValueError("Trade count differs from manifest")
        if max_error > args.capital * 1e-8:
            raise ValueError("NAV does not reconcile")
    report = dict(date=manifest["start"][:10], start_us=initial_us, end_us=end,
                  warmup_us=initial_us - start, decisions=decisions,
                  interval_seconds=1, market_events=count, source_market_events=expected_trades,
                  no_fresh_curve_decisions=no_fresh_curve, capital_usd=args.capital,
                  participation=args.participation, delay_ms=args.delay_ms, fee_bps=args.fee_bps,
                  strategy_return_pct=100 * (account.nav / args.capital - 1),
                  direct_return_pct=100 * (account.marks["SPOT"].price / initial_price - 1),
                  fills=account.fill_count, orders=account.order_count,
                  cancelled_remainders=account.cancellation_count,
                  turnover_usd=account.turnover, fees_usd=account.fees,
                  treasury_interest_usd=account.interest,
                  max_nav_reconstruction_error_usd=max_error, minimum_cash_usd=minimum_cash,
                  end_units=account.units, end_cash_usd=account.cash,
                  end_mark_age_seconds={s: (end - m.us) / 1_000_000 for s, m in account.marks.items()},
                  audit_bytes=audit_path.stat().st_size,
                  peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  wall_seconds=time.monotonic() - started,
                  preset_sha256=hashlib.sha256(preset_path.read_bytes()).hexdigest(),
                  input_manifest_sha256=hashlib.sha256((args.data / "manifest.json").read_bytes()).hexdigest(),
                  code_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                               for name in ("trade_replay.py", "scripts/check-btc-trade-pilot.py",
                                            "backtest_silver_lease_strategy.py", "silver_strategy_gui.py")},
                  assumptions=manifest["assumptions"] + [
                      "First observed spot price initializes an already-owned BTC endowment; not an entry fill",
                      "Same-side aggressor prints; strict later timestamp; cancel/replace each second",
                      "Identified block/RFQ/combo prints cannot fill orders or create entry signals",
                      "100% marked USD collateral, continuous regular-futures cash MTM, fractional lots",
                      "At equal timestamps cross-venue events use symbol order; no synchronized feed latency",
                      "One-day research replay, not CME performance or order-book execution"])
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
