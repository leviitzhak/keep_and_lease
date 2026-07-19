#!/usr/bin/env python3
"""Parameterized backtest for the implied-silver-lease allocation strategy.

The data are daily TurtleTrader individual COMEX silver contract closes, the
LBMA silver price, and FRED Treasury yields. Futures are treated as notional
overlays; margin and transaction costs are deliberately ignored.
"""

import argparse
import calendar
import csv
import io
import json
import math
import re
import zipfile
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

MONTHS = dict(zip("FGHJKMNQUVXZ", range(1, 13)))
TENORS = [(91, "DTB3"), (182, "DTB6"), (365, "DGS1"),
          (730, "DGS2"), (1095, "DGS3"), (1825, "DGS5")]


@dataclass
class Parameters:
    min_days: int
    slv_expense: float = 0.005
    slv_start_rate: float = 0.005
    slv_full_rate: float = -0.015
    positive_full_rate: float = 0.15
    max_long_future: float = 0.50
    negative_short_start_rate: float = -0.005
    negative_short_full_rate: float = -0.15
    max_short_fraction_of_slv: float = 0.50
    negative_maturities: int = 3
    max_share_per_maturity: float = 0.50
    short_maturity_bonus_per_year: float = 0.004
    bond_mode: str = "accrual"
    treasury_asset: str = "matched_maturity"


def clamp(x, low=0.0, high=1.0):
    return max(low, min(high, x))


def parse_date(value):
    value = value.strip().strip('"')
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(value)


def expiry_from_symbol(symbol):
    match = re.fullmatch(r"SI(\d{2})([FGHJKMNQUVXZ])", symbol)
    if not match:
        return None
    yy, month_code = int(match.group(1)), match.group(2)
    year = 1900 + yy if yy >= 60 else 2000 + yy
    month = MONTHS[month_code]
    expiry = date(year, month, calendar.monthrange(year, month)[1])
    business_days = 0
    while business_days < 3:
        if expiry.weekday() < 5:
            business_days += 1
        if business_days < 3:
            expiry -= timedelta(days=1)
    return expiry


def read_spot(root):
    result = {}
    with zipfile.ZipFile(root / "gold_silver.zip") as archive:
        stream = io.TextIOWrapper(archive.open("silver_price.csv"), encoding="utf-8-sig")
        for row in csv.DictReader(stream):
            try:
                value = float(row["price"])
                if value > 0:
                    result[date.fromisoformat(row["date"])] = value
            except (ValueError, KeyError):
                pass
    return result


def read_contracts(root, spot):
    contracts = {}
    volumes = {}
    with zipfile.ZipFile(root / "si.zip") as archive:
        for filename in archive.namelist():
            if not filename.endswith(".txt"):
                continue
            symbol = filename[:-4]
            rows = {}
            stream = io.TextIOWrapper(archive.open(filename), encoding="utf-8-sig")
            for row in csv.reader(stream):
                if not row or row[0].strip('"').lower() == "date":
                    continue
                try:
                    day, raw = parse_date(row[0]), float(row[4])
                    physical = spot.get(day)
                    if not physical or physical <= 0:
                        continue
                    candidates = [raw / scale for scale in (1, 10, 100, 1000, 10000)]
                    price = min(candidates, key=lambda value: abs(value / physical - 1))
                    rows[day] = price
                    volumes[(symbol, day)] = float(row[5]) if len(row) > 5 else 0.0
                except (ValueError, TypeError, IndexError):
                    pass
            if rows:
                contracts[symbol] = rows
    return contracts, volumes


def read_rates(root):
    series = {}
    for tenor, name in TENORS:
        observations = []
        with open(root / f"{name}.csv", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                try:
                    observations.append((date.fromisoformat(row["observation_date"]),
                                         float(row[name]) / 100))
                except (ValueError, TypeError, KeyError):
                    pass
        observations.sort()
        series[tenor] = observations
    return series


def asof_rate(series, tenor, day):
    observations = series[tenor]
    index = bisect_right(observations, (day, float("inf"))) - 1
    if index >= 0 and (day - observations[index][0]).days <= 7:
        return observations[index][1]
    return None


def usd_rate(series, day, days):
    curve = [(tenor, asof_rate(series, tenor, day)) for tenor, _ in TENORS]
    curve = [(tenor, value) for tenor, value in curve if value is not None]
    if not curve:
        return None
    if days <= curve[0][0]:
        return curve[0][1]
    if days >= curve[-1][0]:
        return curve[-1][1]
    for (left_t, left_r), (right_t, right_r) in zip(curve, curve[1:]):
        if left_t <= days <= right_t:
            alpha = (days - left_t) / (right_t - left_t)
            return left_r + alpha * (right_r - left_r)
    return None


def build_market(root):
    spot = read_spot(root)
    contracts, volumes = read_contracts(root, spot)
    rates = read_rates(root)
    by_day = defaultdict(list)
    for symbol, prices in contracts.items():
        expiry = expiry_from_symbol(symbol)
        if not expiry:
            continue
        for day, future in prices.items():
            days = (expiry - day).days
            physical = spot.get(day)
            rate = usd_rate(rates, day, days) if days > 0 else None
            if days <= 0 or not physical or rate is None:
                continue
            premium = future / physical - 1
            lease = rate - premium * 365 / days
            by_day[day].append({"symbol": symbol, "days": days, "future": future,
                                "spot": physical, "rate": rate, "premium": premium,
                                "lease": lease, "volume": volumes.get((symbol, day), 0.0)})
    return spot, contracts, rates, by_day


def capped_proportional(items, total, cap):
    """Allocate total across (key, score) items proportionally with a share cap."""
    if total <= 0 or not items:
        return {}
    result = {key: 0.0 for key, _ in items}
    active = list(items)
    remaining = total
    while active and remaining > 1e-15:
        score_sum = sum(score for _, score in active)
        if score_sum <= 0:
            break
        next_active = []
        allocated = 0.0
        for key, score in active:
            proposed = remaining * score / score_sum
            room = total * cap - result[key]
            addition = min(proposed, max(0.0, room))
            result[key] += addition
            allocated += addition
            if room - addition > 1e-15:
                next_active.append((key, score))
        if allocated <= 1e-15:
            break
        remaining -= allocated
        active = next_active
    return {key: value for key, value in result.items() if value > 0}


def full_notional_diagnostic_books(eligible, p):
    if not eligible:
        return {}, {}
    nearest = min(eligible, key=lambda x: (x["days"], -x["volume"]))
    longs = {nearest["symbol"]: 1.0}

    # Use the short-book ranking without applying the entry/full-allocation
    # thresholds. The constant threshold term does not affect ranking, so the
    # threshold-free score is negative lease plus the maturity bonus.
    ranked = []
    for x in eligible:
        score = -x["lease"] + p.short_maturity_bonus_per_year * x["days"] / 365
        ranked.append((x["symbol"], max(score, 1e-9)))
    ranked.sort(key=lambda item: item[1], reverse=True)
    shorts = capped_proportional(ranked[:p.negative_maturities], 1.0, p.max_share_per_maturity)
    short_total = sum(shorts.values())
    if short_total:
        shorts = {symbol: weight / short_total for symbol, weight in shorts.items()}
    return longs, shorts


def positions_for_day(candidates, p):
    eligible = [x for x in candidates if x["days"] >= p.min_days]
    if not eligible:
        return None
    contract_map = {x["symbol"]: x for x in eligible}
    # The performance charts are diagnostics for a hypothetical 100% position
    # in each leg.  Select their contracts independently of the thresholds
    # which decide whether the portfolio actually takes the position.
    nearest_long_leg = min(eligible, key=lambda x: (x["days"], -x["volume"]))
    long_leg = {nearest_long_leg["symbol"]: 1.0}

    # The long and short books are independent. The long book uses the nearest
    # eligible contract whose lease rate is positive.
    positive = [x for x in eligible if x["lease"] > 0]
    nearest_positive = min(positive, key=lambda x: (x["days"], -x["volume"])) if positive else None
    longs = {}
    if nearest_positive:
        longs[nearest_positive["symbol"]] = p.max_long_future * clamp(
            nearest_positive["lease"] / p.positive_full_rate)

    # Cash allocation follows the lowest observed lease rate. By default SLV
    # rises from zero at +0.5% to 100% at -1.5%: ±1% around -expense (=-0.5%).
    cash_signal = min(x["lease"] for x in eligible)
    slv_weight = clamp((p.slv_start_rate - cash_signal) /
                       (p.slv_start_rate - p.slv_full_rate))

    # Any eligible maturity, including the shortest, can enter the short book,
    # but only after its lease rate passes the explicit negative entry threshold.
    # The maturity bonus ranks already-eligible contracts; it cannot make a
    # positive or insufficiently negative lease rate eligible.
    short_start_rate = p.negative_short_start_rate
    best_negative = min(eligible, key=lambda x: x["lease"])
    signal = best_negative["lease"]
    short_fraction = p.max_short_fraction_of_slv * clamp(
        (short_start_rate - signal) /
        (short_start_rate - p.negative_short_full_rate))
    total_short = slv_weight * short_fraction

    # Score trades off negative lease edge against a preference for maturity.
    # A 0.02 bonus means one extra year can compensate for 2 percentage points
    # less-negative annualized lease rate.
    negative = [x for x in eligible if x["lease"] < short_start_rate]
    for x in negative:
        x["short_score"] = (short_start_rate - x["lease"]) + \
                           p.short_maturity_bonus_per_year * x["days"] / 365
    negative.sort(key=lambda x: x["short_score"], reverse=True)
    negative = negative[:p.negative_maturities]
    scores = [(x["symbol"], x["short_score"]) for x in negative]
    shorts = capped_proportional(scores, total_short, p.max_share_per_maturity)

    # When the strategy has a short position, its diagnostic must use exactly
    # the same maturities and relative allocations.  Only use a
    # threshold-independent selection when the strategy has no short at all.
    if shorts:
        short_leg = dict(shorts)
    else:
        short_leg_candidates = []
        for x in eligible:
            score = max(0.0, short_start_rate - x["lease"]) + \
                    p.short_maturity_bonus_per_year * x["days"] / 365
            short_leg_candidates.append((x["symbol"], score))
        short_leg_candidates.sort(key=lambda item: item[1], reverse=True)
        short_leg = capped_proportional(
            short_leg_candidates[:p.negative_maturities], 1.0,
            p.max_share_per_maturity)
    if shorts:
        bond_days = sum(shorts[s] * contract_map[s]["days"] for s in shorts) / sum(shorts.values())
    elif nearest_positive:
        bond_days = nearest_positive["days"]
    else:
        bond_days = best_negative["days"]
    if longs and shorts:
        mode = "long_and_short"
    elif longs:
        mode = "positive"
    elif shorts:
        mode = "negative"
    else:
        mode = "neutral"
    return {"mode": mode, "signal": cash_signal,
            "positive_signal": nearest_positive["lease"] if nearest_positive else 0.0,
            "negative_signal": signal, "slv": slv_weight,
            "treasury": 1 - slv_weight, "longs": longs,
            "shorts": shorts, "long_leg": long_leg, "short_leg": short_leg,
            "diagnostic_longs": long_leg, "diagnostic_shorts": short_leg,
            "bond_days": bond_days, "contracts": contract_map}


def bond_return(rates, day, next_day, days, mode):
    elapsed = (next_day - day).days
    current_yield = usd_rate(rates, day, days)
    if current_yield is None:
        return 0.0
    if mode == "accrual":
        return current_yield * elapsed / 365
    remaining = max(1.0, days - elapsed)
    next_yield = usd_rate(rates, next_day, remaining)
    if next_yield is None:
        return current_yield * elapsed / 365
    current_price = (1 + current_yield) ** (-days / 365)
    next_price = (1 + next_yield) ** (-remaining / 365)
    return next_price / current_price - 1


def treasury_position_return(rates, day, next_day, days, p):
    if p.treasury_asset == "sgov_proxy":
        rate = asof_rate(rates, 91, day)
        elapsed = (next_day - day).days
        return 0.0 if rate is None else rate * elapsed / 365
    return bond_return(rates, day, next_day, days, p.bond_mode)


def futures_interval_return(symbol, day, next_day, contracts):
    prices = contracts.get(symbol, {})
    if day not in prices or next_day not in prices or prices[day] <= 0:
        return 0.0, False
    return prices[next_day] / prices[day] - 1, True


def weighted_contract_value(positions, contracts, field):
    total = sum(positions.values())
    if not total:
        return None
    return sum(weight * contracts[symbol][field]
               for symbol, weight in positions.items()) / total


def weighted_futures_price(positions, contracts, day):
    total = sum(positions.values())
    if not total:
        return None
    if any(day not in contracts.get(symbol, {}) for symbol in positions):
        return None
    return sum(weight * contracts[symbol][day]
               for symbol, weight in positions.items()) / total


def diagnostic_futures_return(positions, day, next_day, contracts, direction):
    if not positions:
        return None
    result = 0.0
    for symbol, weight in positions.items():
        value, found = futures_interval_return(symbol, day, next_day, contracts)
        if not found:
            return None
        result += direction * weight * value
    return result


def run_backtest(spot, contracts, rates, by_day, p):
    days = sorted(day for day in by_day if day in spot)
    output = []
    simple = 0.0
    long_simple = 0.0
    short_simple = 0.0
    nav = 1.0
    asset_simple = {"long_futures": 0.0, "short_futures": 0.0, "slv": 0.0, "treasury": 0.0}
    asset_nav = {"long_futures": 1.0, "short_futures": 1.0, "slv": 1.0, "treasury": 1.0}
    sgov_proxy_nav = 1.0
    missing_futures_intervals = 0
    # Signal at t, execute at t+1, and measure P&L from t+1 to t+2.
    for signal_day, execution_day, exit_day in zip(days, days[1:], days[2:]):
        position = positions_for_day(by_day[signal_day], p)
        if position is None or execution_day not in spot or exit_day not in spot:
            continue
        lag = (execution_day - signal_day).days
        holding_days = max(1.0, position["bond_days"] - lag)
        elapsed = (exit_day - execution_day).days
        treasury_return = treasury_position_return(rates, execution_day, exit_day, holding_days, p)
        sgov_proxy_return = treasury_position_return(
            rates, execution_day, exit_day, holding_days,
            Parameters(min_days=p.min_days, treasury_asset="sgov_proxy"))
        spot_return = spot[exit_day] / spot[execution_day] - 1 - p.slv_expense * elapsed / 365
        portfolio_return = position["treasury"] * treasury_return + position["slv"] * spot_return
        long_return = 0.0
        short_return = 0.0
        valid_interval = True
        short_total = sum(position["shorts"].values())
        long_total = sum(position["longs"].values())
        for symbol, weight in position["longs"].items():
            value, found = futures_interval_return(symbol, execution_day, exit_day, contracts)
            contribution = weight * value
            long_return += contribution
            portfolio_return += contribution
            missing_futures_intervals += int(not found)
            valid_interval = valid_interval and found
        for symbol, weight in position["shorts"].items():
            value, found = futures_interval_return(symbol, execution_day, exit_day, contracts)
            contribution = -weight * value
            short_return += contribution
            portfolio_return += contribution
            missing_futures_intervals += int(not found)
            valid_interval = valid_interval and found
        # Do not invent a zero futures return when a held contract has no next
        # observation. Skip that entire portfolio interval instead.
        if not valid_interval:
            continue
        simple += portfolio_return
        long_simple += long_return
        short_simple += short_return
        nav *= 1 + portfolio_return
        sgov_proxy_nav *= 1 + sgov_proxy_return
        # Standalone leg returns always represent a fully invested leg.  They
        # are deliberately independent of the portfolio's allocation signal.
        asset_returns = {"slv": spot_return, "treasury": treasury_return}
        for key, selected, direction in (
                ("long_futures", position["long_leg"], 1.0),
                ("short_futures", position["short_leg"], -1.0)):
            selected_total = sum(selected.values())
            selected_return = 0.0
            selected_valid = bool(selected_total)
            for symbol, weight in selected.items():
                value, found = futures_interval_return(
                    symbol, execution_day, exit_day, contracts)
                selected_valid = selected_valid and found
                selected_return += direction * weight * value
            asset_returns[key] = (selected_return / selected_total
                                  if selected_valid else None)
        for key, value in asset_returns.items():
            if value is not None:
                asset_simple[key] += value
                asset_nav[key] *= 1 + value
        long_weighted_days = weighted_contract_value(position["longs"], position["contracts"], "days")
        short_weighted_days = weighted_contract_value(position["shorts"], position["contracts"], "days")
        long_weighted_lease = weighted_contract_value(position["longs"], position["contracts"], "lease")
        short_weighted_lease = weighted_contract_value(position["shorts"], position["contracts"], "lease")
        long_weighted_future_price = weighted_futures_price(
            position["diagnostic_longs"], contracts, exit_day)
        short_weighted_future_price = weighted_futures_price(
            position["diagnostic_shorts"], contracts, exit_day)
        if short_total:
            short_maturities = [position["contracts"][s]["days"] for s in position["shorts"]]
            shortest_short_maturity_days = min(short_maturities)
            longest_short_maturity_days = max(short_maturities)
        else:
            shortest_short_maturity_days = None
            longest_short_maturity_days = None
        if short_total:
            weighted_days = short_weighted_days
            largest_share = max(position["shorts"].values()) / short_total
        elif long_total:
            weighted_days = long_weighted_days
            largest_share = 1.0
        else:
            weighted_days = position["bond_days"]
            largest_share = 0.0
        output.append({"date": exit_day.isoformat(), "signal_date": signal_day.isoformat(),
                       "execution_date": execution_day.isoformat(), "mode": position["mode"],
                       "signal_annual_pct": 100 * position["signal"],
                       "positive_signal_annual_pct": 100 * position["positive_signal"],
                       "negative_signal_annual_pct": 100 * position["negative_signal"],
                       "interval_return_pct": 100 * portfolio_return,
                       "long_book_interval_return_pct": 100 * long_return,
                       "short_book_interval_return_pct": 100 * short_return,
                       "simple_cumulative_return_pct": 100 * simple,
                       "long_book_cumulative_return_pct": 100 * long_simple,
                       "short_book_cumulative_return_pct": 100 * short_simple,
                       "compounded_return_pct": 100 * (nav - 1), "nav": nav,
                       "long_futures_daily_return_pct": (
                           100 * asset_returns["long_futures"]
                           if asset_returns["long_futures"] is not None else None),
                       "short_futures_daily_return_pct": (
                           100 * asset_returns["short_futures"]
                           if asset_returns["short_futures"] is not None else None),
                       "slv_daily_return_pct": (
                           100 * asset_returns["slv"] if asset_returns["slv"] is not None else None),
                       "treasury_daily_return_pct": (
                           100 * asset_returns["treasury"]
                           if asset_returns["treasury"] is not None else None),
                       "long_futures_cumulative_return_pct": 100 * asset_simple["long_futures"],
                       "short_futures_cumulative_return_pct": 100 * asset_simple["short_futures"],
                       "slv_cumulative_return_pct": 100 * asset_simple["slv"],
                       "treasury_cumulative_return_pct": 100 * asset_simple["treasury"],
                       "long_futures_compounded_return_pct": 100 * (asset_nav["long_futures"] - 1),
                       "short_futures_compounded_return_pct": 100 * (asset_nav["short_futures"] - 1),
                       "slv_compounded_return_pct": 100 * (asset_nav["slv"] - 1),
                       "treasury_compounded_return_pct": 100 * (asset_nav["treasury"] - 1),
                       "slv_price": spot[exit_day],
                       "long_weighted_future_price": long_weighted_future_price,
                       "short_weighted_future_price": short_weighted_future_price,
                       "treasury_position_price_index": 100 * asset_nav["treasury"],
                       "sgov_proxy_price_index": 100 * sgov_proxy_nav,
                       "slv_weight_pct": 100 * position["slv"],
                       "treasury_weight_pct": 100 * position["treasury"],
                       "long_futures_notional_pct": 100 * long_total,
                       "short_futures_notional_pct": 100 * short_total,
                       "weighted_maturity_days": weighted_days,
                       "long_weighted_maturity_days": long_weighted_days,
                       "short_weighted_maturity_days": short_weighted_days,
                       "long_weighted_lease_rate_pct": (
                           100 * long_weighted_lease if long_weighted_lease is not None else None),
                       "short_weighted_lease_rate_pct": (
                           100 * short_weighted_lease if short_weighted_lease is not None else None),
                       "short_shortest_maturity_days": shortest_short_maturity_days,
                       "short_longest_maturity_days": longest_short_maturity_days,
                       "number_of_futures_maturities": len(position["longs"]) + len(position["shorts"]),
                       "largest_futures_maturity_share_pct": 100 * largest_share,
                       "long_symbols": ";".join(position["longs"]),
                       "short_symbols": ";".join(position["shorts"])})
    return output, missing_futures_intervals


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path, default=Path("/workspace/silver-strategy-results"))
    parser.add_argument("--min-days", type=int, nargs="+", default=[2, 10, 30])
    parser.add_argument("--slv-expense", type=float, default=0.005)
    parser.add_argument("--slv-start-rate", type=float, default=0.005)
    parser.add_argument("--slv-full-rate", type=float, default=-0.015)
    parser.add_argument("--positive-full-rate", type=float, default=0.15)
    parser.add_argument("--max-long-future", type=float, default=0.50)
    parser.add_argument("--negative-short-start-rate", type=float, default=-0.005,
                        help="Lease rate below which a contract becomes eligible for shorting")
    parser.add_argument("--negative-short-full-rate", type=float, default=-0.15)
    parser.add_argument("--max-short-fraction-of-slv", type=float, default=0.50)
    parser.add_argument("--negative-maturities", type=int, default=3)
    parser.add_argument("--max-share-per-maturity", type=float, default=0.50)
    parser.add_argument("--short-maturity-bonus-per-year", type=float, default=0.004,
                        help="Added short-selection score per extra year to maturity")
    parser.add_argument("--bond-mode", choices=["accrual", "zero_coupon_mtm"], default="accrual")
    parser.add_argument("--treasury-asset", choices=["matched_maturity", "sgov_proxy"],
                        default="matched_maturity")
    return parser.parse_args()


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    spot, contracts, rates, by_day = build_market(args.root)
    summary = []
    for min_days in args.min_days:
        parameters = Parameters(min_days=min_days, slv_expense=args.slv_expense,
                                slv_start_rate=args.slv_start_rate,
                                slv_full_rate=args.slv_full_rate,
                                positive_full_rate=args.positive_full_rate,
                                max_long_future=args.max_long_future,
                                negative_short_start_rate=args.negative_short_start_rate,
                                negative_short_full_rate=args.negative_short_full_rate,
                                max_short_fraction_of_slv=args.max_short_fraction_of_slv,
                                negative_maturities=args.negative_maturities,
                                max_share_per_maturity=args.max_share_per_maturity,
                                short_maturity_bonus_per_year=args.short_maturity_bonus_per_year,
                                bond_mode=args.bond_mode,
                                treasury_asset=args.treasury_asset)
        rows, missing = run_backtest(spot, contracts, rates, by_day, parameters)
        write_csv(args.output_dir / f"strategy_min_{min_days}d.csv", rows)
        if rows:
            summary.append({"min_days": min_days, "bond_mode": args.bond_mode,
                            "start": rows[0]["date"], "end": rows[-1]["date"],
                            "observations": len(rows),
                            "simple_total_return_pct": rows[-1]["simple_cumulative_return_pct"],
                            "compounded_total_return_pct": rows[-1]["compounded_return_pct"],
                            "ending_nav": rows[-1]["nav"],
                            "missing_futures_intervals": missing})
    write_csv(args.output_dir / "summary.csv", summary)
    config = vars(args).copy()
    config["root"] = str(config["root"]); config["output_dir"] = str(config["output_dir"])
    with open(args.output_dir / "parameters.json", "w", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
