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
    roll_only_if_better: bool = True
    force_roll_at_min_days: bool = True
    enable_short_book: bool = True
    enable_slv_leg: bool = True
    enable_cash_long_futures_leg: bool = True
    slv_entry_mode: str = "gradual"
    long_futures_entry_mode: str = "gradual"
    short_futures_entry_mode: str = "gradual"
    slv_expense: float = 0.005
    slv_start_rate: float = 0.005
    slv_full_rate: float = -0.015
    positive_entry_rate: float = 0.0
    positive_full_rate: float = 0.15
    long_contract_selection: str = "shortest_maturity"
    long_maturity_bonus_per_year: float = 0.004
    max_long_future: float = 0.50
    negative_short_start_rate: float = -0.005
    negative_short_full_rate: float = -0.15
    max_short_fraction_of_slv: float = 0.50
    short_contract_selection: str = "weighted_lease_rate"
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
    if not observations:
        return None
    index = bisect_right(observations, (day, float("inf"))) - 1
    if index >= 0 and observations[index][0] == day:
        return observations[index][1]
    right_index = index + 1
    if index < 0:
        return observations[0][1]
    if right_index >= len(observations):
        return observations[-1][1]
    left_day, left_rate = observations[index]
    right_day, right_rate = observations[right_index]
    alpha = ((day - left_day).days /
             (right_day - left_day).days)
    return left_rate + alpha * (right_rate - left_rate)


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


def usd_rate_components(series, day, days):
    """Return the curve tenors, rates, and interpolation weights for a maturity."""
    curve = [(tenor, asof_rate(series, tenor, day)) for tenor, _ in TENORS]
    curve = [(tenor, value) for tenor, value in curve if value is not None]
    if not curve:
        return []
    if days <= curve[0][0]:
        return [(curve[0][0], curve[0][1], 1.0)]
    if days >= curve[-1][0]:
        return [(curve[-1][0], curve[-1][1], 1.0)]
    for (left_t, left_r), (right_t, right_r) in zip(curve, curve[1:]):
        if left_t <= days <= right_t:
            alpha = (days - left_t) / (right_t - left_t)
            if alpha == 0:
                return [(left_t, left_r, 1.0)]
            if alpha == 1:
                return [(right_t, right_r, 1.0)]
            return [(left_t, left_r, 1 - alpha),
                    (right_t, right_r, alpha)]
    return []


def matched_usd_rate_details(series, day, positions, contracts):
    """Aggregate curve interpolation across a weighted futures selection."""
    total = sum(positions.values())
    if total <= 0:
        return {"rate": None, "components": []}
    components = defaultdict(lambda: {"weight": 0.0, "rate_weight": 0.0})
    for symbol, position_weight in positions.items():
        contract = contracts.get(symbol)
        if not contract:
            continue
        for tenor, rate, interpolation_weight in usd_rate_components(
                series, day, contract["days"]):
            combined_weight = position_weight / total * interpolation_weight
            components[tenor]["weight"] += combined_weight
            components[tenor]["rate_weight"] += combined_weight * rate
    details = []
    for tenor, values in sorted(components.items()):
        if values["weight"] <= 0:
            continue
        details.append({
            "maturity_days": tenor,
            "rate_pct": 100 * values["rate_weight"] / values["weight"],
            "weight_pct": 100 * values["weight"],
        })
    return {
        "rate": sum(x["rate_pct"] * x["weight_pct"] for x in details) / 10000
                if details else None,
        "components": details,
    }


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


def proportional_allocation(items, total):
    """Allocate total across ``(key, score)`` items in proportion to score."""
    if total <= 0 or not items:
        return {}
    score_sum = sum(score for _, score in items)
    if score_sum <= 0:
        return {}
    return {key: total * score / score_sum for key, score in items if score > 0}


def market_diagnostics_for_day(candidates, p):
    """Select chart diagnostics from quotes available on the charted day."""
    eligible = [x for x in candidates if x["days"] >= p.min_days]
    if not eligible:
        return None
    contracts = {x["symbol"]: x for x in eligible}
    nearest = min(eligible, key=lambda x: (x["days"], -x["volume"]))
    longs = {nearest["symbol"]: 1.0}

    # Build the threshold-independent short diagnostics here, alongside their
    # eligibility filtering.  Keeping this operation self-contained prevents
    # the GUI request path from depending on a separately defined helper.
    ranked = []
    for contract in eligible:
        score = (-contract["lease"] + p.short_maturity_bonus_per_year *
                 contract["days"] / 365)
        ranked.append((contract["symbol"], max(score, 1e-9)))
    ranked.sort(key=lambda item: item[1], reverse=True)
    shorts = proportional_allocation(ranked, 1.0)
    short_total = sum(shorts.values())
    if short_total:
        shorts = {symbol: weight / short_total
                  for symbol, weight in shorts.items()}
    return {
        "contracts": contracts,
        "longs": longs,
        "shorts": shorts,
        "min_maturity_days": min(x["days"] for x in eligible),
        "max_maturity_days": max(x["days"] for x in eligible),
    }


def _sticky_contract_book(desired, previous, contract_map, qualifying_symbols,
                          direction, p):
    """Keep held maturities unless a replacement improves the lease signal."""
    desired_total = sum(desired.values())
    if desired_total <= 0:
        return {}
    previous = previous or {}
    held = {symbol: weight for symbol, weight in previous.items()
            if symbol in contract_map and
            (symbol in qualifying_symbols or not p.force_roll_at_min_days)}
    if not held or not p.roll_only_if_better:
        return desired
    forced = (p.force_roll_at_min_days and
              any(contract_map[symbol]["days"] <= p.min_days for symbol in held))
    held_lease = weighted_contract_value(held, contract_map, "lease")
    desired_lease = weighted_contract_value(desired, contract_map, "lease")
    better = (desired_lease > held_lease if direction == "long"
              else desired_lease < held_lease)
    if forced or better:
        return desired
    held_total = sum(held.values())
    return {symbol: desired_total * weight / held_total
            for symbol, weight in held.items()}


def positions_for_day(candidates, p, previous=None):
    eligible = [x for x in candidates if x["days"] >= p.min_days]
    if not eligible:
        return None
    # Keep quotes below the new-entry maturity floor available for an existing
    # position when the user explicitly disables the forced minimum-day roll.
    contract_map = {x["symbol"]: x for x in candidates if x["days"] > 0}
    # The performance charts are diagnostics for a hypothetical 100% position
    # in each leg.  Select their contracts independently of the thresholds
    # which decide whether the portfolio actually takes the position.
    if p.long_contract_selection in {"highest_lease_rate", "weighted_lease_rate"}:
        select_long = lambda contracts: max(
            contracts, key=lambda x: (x["lease"], -x["days"], x["volume"]))
    else:
        select_long = lambda contracts: min(
            contracts, key=lambda x: (x["days"], -x["volume"]))
    if p.long_contract_selection == "weighted_lease_rate":
        lease_floor = min(x["lease"] for x in eligible)
        longest_days = max(x["days"] for x in eligible)
        long_leg = proportional_allocation([
            (x["symbol"], x["lease"] - lease_floor + 1e-9 +
             p.long_maturity_bonus_per_year * (longest_days - x["days"]) / 365)
            for x in eligible
        ], 1.0)
    else:
        diagnostic_long = select_long(eligible)
        long_leg = {diagnostic_long["symbol"]: 1.0}

    # The long and short books are independent. Select the long contract using
    # the configured maturity/rate policy after enforcing the entry threshold.
    positive = [x for x in eligible if x["lease"] > p.positive_entry_rate]
    selected_positive = select_long(positive) if positive else None
    # SLV is controlled by the lease rate of the configured long book, not by
    # the most negative contract used to construct the short-futures signal.
    long_signal = weighted_contract_value(long_leg, contract_map, "lease")

    # Any eligible maturity, including the shortest, can enter the short book,
    # but only after its lease rate passes the explicit negative entry threshold.
    # The maturity bonus ranks already-eligible contracts; it cannot make a
    # positive or insufficiently negative lease rate eligible.
    short_start_rate = p.negative_short_start_rate
    best_negative = min(eligible, key=lambda x: x["lease"])
    signal = best_negative["lease"]
    positive_strength = (clamp(
        (selected_positive["lease"] - p.positive_entry_rate) /
        (p.positive_full_rate - p.positive_entry_rate)) if selected_positive else 0.0)
    if selected_positive and p.long_futures_entry_mode == "fixed":
        positive_strength = 1.0
    negative_strength = clamp(
        (short_start_rate - signal) /
        (short_start_rate - p.negative_short_full_rate))
    if signal < short_start_rate and p.short_futures_entry_mode == "fixed":
        negative_strength = 1.0
    slv_weight = clamp(
        (p.slv_start_rate - long_signal) /
        (p.slv_start_rate - p.slv_full_rate))
    if long_signal < p.slv_start_rate and p.slv_entry_mode == "fixed":
        slv_weight = 1.0
    if not p.enable_slv_leg:
        slv_weight = 0.0
    treasury_weight = ((1.0 - slv_weight)
                       if p.enable_cash_long_futures_leg else 0.0)

    # Treasury and SLV form the fully invested base, while long futures are an
    # overlay sized independently by their positive lease signal.
    base_longs = {}
    long_notional = (p.max_long_future * positive_strength
                     if p.enable_cash_long_futures_leg else 0.0)
    if positive and p.long_contract_selection == "weighted_lease_rate":
        longest_days = max(x["days"] for x in positive)
        base_longs = proportional_allocation([
            (x["symbol"],
             (x["lease"] - p.positive_entry_rate) +
             p.long_maturity_bonus_per_year * (longest_days - x["days"]) / 365)
            for x in positive
        ], long_notional)
    elif selected_positive:
        base_longs[selected_positive["symbol"]] = (
            long_notional)
    total_short = (p.max_short_fraction_of_slv * negative_strength
                   if p.enable_short_book else 0.0)
    # The short book is defined as short futures plus an equal-sized extension
    # of the active base long book.  If both long sleeves are inactive there is
    # no composition to extend, so the complete short book must also be zero.
    if treasury_weight + slv_weight + sum(base_longs.values()) <= 0:
        total_short = 0.0

    # Score trades off negative lease edge against a preference for longer
    # maturity (the opposite of the long book). A 0.02 bonus means one extra
    # year can compensate for 2 percentage points less-negative annualized
    # lease rate.
    negative = [x for x in eligible if x["lease"] < short_start_rate]
    for x in negative:
        # A short's lease edge is the magnitude of lease rate minus entry
        # threshold. It is positive because qualifying leases are below entry.
        x["short_score"] = abs(x["lease"] - short_start_rate) + \
                           p.short_maturity_bonus_per_year * x["days"] / 365
    if negative and p.short_contract_selection == "lowest_lease_rate":
        lowest = min(negative, key=lambda x: (x["lease"], x["days"], -x["volume"]))
        shorts = {lowest["symbol"]: total_short}
    else:
        scores = [(x["symbol"], x["short_score"]) for x in negative]
        shorts = proportional_allocation(scores, total_short)

    # Resize with the signal, but change contracts only for a better lease or
    # when the configured minimum-maturity boundary forces a roll.
    base_longs = _sticky_contract_book(
        base_longs, previous.get("base_longs") if previous else None,
        contract_map, {x["symbol"] for x in positive}, "long", p)
    shorts = _sticky_contract_book(
        shorts, previous.get("shorts") if previous else None,
        contract_map, {x["symbol"] for x in negative}, "short", p)

    # A short-futures position is paired with an equally sized extension of
    # the complete base long book.  The extension retains the same relative
    # mix of long futures, SLV, and Treasuries.
    base_long_total = treasury_weight + slv_weight + sum(base_longs.values())
    long_extension = total_short
    extension_ratio = long_extension / base_long_total if base_long_total else 0.0
    treasury = treasury_weight * (1.0 + extension_ratio)
    slv = slv_weight * (1.0 + extension_ratio)
    longs = {symbol: weight * (1.0 + extension_ratio)
             for symbol, weight in base_longs.items()}

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
            short_leg_candidates.append((x["symbol"], score + 1e-9))
        if p.short_contract_selection == "lowest_lease_rate":
            lowest = min(eligible, key=lambda x: (x["lease"], x["days"], -x["volume"]))
            short_leg = {lowest["symbol"]: 1.0}
        else:
            short_leg = proportional_allocation(short_leg_candidates, 1.0)
    if shorts:
        bond_days = sum(shorts[s] * contract_map[s]["days"] for s in shorts) / sum(shorts.values())
    elif selected_positive:
        bond_days = selected_positive["days"]
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
    return {"mode": mode, "signal": long_signal,
            "positive_signal": selected_positive["lease"] if selected_positive else 0.0,
            "negative_signal": signal, "slv": slv,
            "treasury": treasury, "longs": longs,
            "shorts": shorts, "long_leg": long_leg, "short_leg": short_leg,
            "diagnostic_longs": long_leg, "diagnostic_shorts": short_leg,
            "base_slv": slv_weight, "base_treasury": treasury_weight,
            "base_longs": base_longs, "long_extension": long_extension,
            "extension_ratio": extension_ratio,
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


def futures_trade_prices(previous, current, contracts, day):
    """Return weighted entry/exit prices and traded notionals for one book side."""
    entries = {}
    exits = {}
    for symbol in set(previous) | set(current):
        change = current.get(symbol, 0.0) - previous.get(symbol, 0.0)
        if change > 0:
            entries[symbol] = change
        elif change < 0:
            exits[symbol] = -change
    return (weighted_futures_price(entries, contracts, day), sum(entries.values()),
            weighted_futures_price(exits, contracts, day), sum(exits.values()))


def futures_trade_details(previous, current, contracts, day):
    """Return the individual contract changes executed on a rebalance day."""
    trades = []
    for symbol in sorted(set(previous) | set(current)):
        change = current.get(symbol, 0.0) - previous.get(symbol, 0.0)
        price = contracts.get(symbol, {}).get(day)
        if change and price is not None:
            trades.append({"symbol": symbol, "price": price,
                           "size_pct": 100 * abs(change),
                           "action": "entry" if change > 0 else "exit"})
    return trades


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
    # Ignore stray weekend records. Exchange holidays have no observation, so
    # each interval automatically runs to the next available business day.
    days = sorted(day for day in by_day if day in spot and day.weekday() < 5)
    output = []
    simple = 0.0
    long_simple = 0.0
    extension_simple = 0.0
    short_simple = 0.0
    nav = 1.0
    asset_simple = {"long_futures": 0.0, "short_futures": 0.0, "slv": 0.0, "treasury": 0.0}
    asset_nav = {"long_futures": 1.0, "short_futures": 1.0, "slv": 1.0, "treasury": 1.0}
    sgov_proxy_nav = 1.0
    missing_futures_intervals = []
    scheduled_positions = {}
    previous_position = None
    for signal_day, execution_day in zip(days, days[1:]):
        previous_position = positions_for_day(
            by_day[signal_day], p, previous_position)
        scheduled_positions[execution_day] = previous_position
    # Signal at t, execute at t+1, and measure P&L from t+1 to t+2.
    for signal_day, execution_day, exit_day in zip(days, days[1:], days[2:]):
        position = scheduled_positions.get(execution_day)
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
        base_long_return = (position["base_treasury"] * treasury_return +
                            position["base_slv"] * spot_return)
        short_futures_return = 0.0
        valid_interval = True
        short_total = sum(position["shorts"].values())
        long_total = sum(position["longs"].values())
        for symbol, weight in position["longs"].items():
            value, found = futures_interval_return(symbol, execution_day, exit_day, contracts)
            contribution = weight * value
            portfolio_return += contribution
            base_long_return += position["base_longs"].get(symbol, 0.0) * value
            if not found:
                missing_futures_intervals.append({
                    "signal_date": signal_day.isoformat(),
                    "execution_date": execution_day.isoformat(),
                    "exit_date": exit_day.isoformat(), "leg": "long",
                    "symbol": symbol, "reason": "missing futures price"})
            valid_interval = valid_interval and found
        for symbol, weight in position["shorts"].items():
            value, found = futures_interval_return(symbol, execution_day, exit_day, contracts)
            contribution = -weight * value
            short_futures_return += contribution
            portfolio_return += contribution
            if not found:
                missing_futures_intervals.append({
                    "signal_date": signal_day.isoformat(),
                    "execution_date": execution_day.isoformat(),
                    "exit_date": exit_day.isoformat(), "leg": "short",
                    "symbol": symbol, "reason": "missing futures price"})
            valid_interval = valid_interval and found
        # Do not invent a zero futures return when a held contract has no next
        # observation. Skip that entire portfolio interval instead.
        if not valid_interval:
            continue
        matched_long_extension_return = position["extension_ratio"] * base_long_return
        short_book_return = matched_long_extension_return + short_futures_return
        simple += portfolio_return
        long_simple += base_long_return
        extension_simple += matched_long_extension_return
        short_simple += short_book_return
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
                if not found:
                    missing_futures_intervals.append({
                        "signal_date": signal_day.isoformat(),
                        "execution_date": execution_day.isoformat(),
                        "exit_date": exit_day.isoformat(), "leg": key,
                        "symbol": symbol, "reason": "missing futures price"})
            asset_returns[key] = (selected_return / selected_total
                                  if selected_valid else None)
        for key, value in asset_returns.items():
            if value is not None:
                asset_simple[key] += value
                asset_nav[key] *= 1 + value
        long_weighted_days = weighted_contract_value(position["longs"], position["contracts"], "days")
        short_weighted_days = weighted_contract_value(position["shorts"], position["contracts"], "days")
        # Chart diagnostics describe the displayed (exit) date, rather than the
        # earlier signal date used for the portfolio. This keeps them aligned
        # with the spot/futures quotes and date shown by the chart tooltip.
        market_diagnostics = market_diagnostics_for_day(by_day.get(exit_day, []), p)
        diagnostic_contracts = (market_diagnostics["contracts"]
                                if market_diagnostics else {})
        diagnostic_longs = market_diagnostics["longs"] if market_diagnostics else {}
        diagnostic_shorts = market_diagnostics["shorts"] if market_diagnostics else {}
        long_weighted_lease = weighted_contract_value(
            diagnostic_longs, diagnostic_contracts, "lease")
        short_weighted_lease = weighted_contract_value(
            diagnostic_shorts, diagnostic_contracts, "lease")
        long_forward_maturity_days = weighted_contract_value(
            diagnostic_longs, diagnostic_contracts, "days")
        short_forward_maturity_days = weighted_contract_value(
            diagnostic_shorts, diagnostic_contracts, "days")
        long_weighted_future_price = weighted_futures_price(
            diagnostic_longs, contracts, exit_day)
        short_weighted_future_price = weighted_futures_price(
            diagnostic_shorts, contracts, exit_day)
        long_usd_rate = matched_usd_rate_details(
            rates, exit_day, diagnostic_longs, diagnostic_contracts)
        short_usd_rate = matched_usd_rate_details(
            rates, exit_day, diagnostic_shorts, diagnostic_contracts)
        # The currently held position is rebalanced on the displayed exit date.
        # Compare it with the next scheduled position and weight prices by the
        # absolute notional traded when several contracts change together.
        next_position = scheduled_positions.get(exit_day)
        next_longs = next_position["longs"] if next_position else {}
        next_shorts = next_position["shorts"] if next_position else {}
        (entered_long_price, entered_long_size,
         exited_long_price, exited_long_size) = futures_trade_prices(
            position["longs"], next_longs, contracts, exit_day)
        (entered_short_price, entered_short_size,
         exited_short_price, exited_short_size) = futures_trade_prices(
            position["shorts"], next_shorts, contracts, exit_day)
        long_trade_details = futures_trade_details(
            position["longs"], next_longs, contracts, exit_day)
        short_trade_details = futures_trade_details(
            position["shorts"], next_shorts, contracts, exit_day)
        # Premium charts are market diagnostics, not position diagnostics.  Use
        # the threshold-independent books so a null means that a source quote
        # is unavailable, rather than merely that the strategy did not trade.
        long_weighted_premium = weighted_contract_value(
            diagnostic_longs, diagnostic_contracts, "premium")
        short_weighted_premium = weighted_contract_value(
            diagnostic_shorts, diagnostic_contracts, "premium")
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
                       "long_book_interval_return_pct": 100 * base_long_return,
                       "matched_long_extension_interval_return_pct": (
                           100 * matched_long_extension_return),
                       "short_book_interval_return_pct": 100 * short_book_return,
                       "simple_cumulative_return_pct": 100 * simple,
                       "long_book_cumulative_return_pct": 100 * long_simple,
                       "matched_long_extension_cumulative_return_pct": (
                           100 * extension_simple),
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
                       "entered_long_futures_price": entered_long_price,
                       "entered_short_futures_price": entered_short_price,
                       "exited_long_futures_price": exited_long_price,
                       "exited_short_futures_price": exited_short_price,
                       "entered_long_futures_size_pct": 100 * entered_long_size,
                       "entered_short_futures_size_pct": 100 * entered_short_size,
                       "exited_long_futures_size_pct": 100 * exited_long_size,
                       "exited_short_futures_size_pct": 100 * exited_short_size,
                       "resulting_long_futures_size_pct": 100 * sum(next_longs.values()),
                       "resulting_short_futures_size_pct": 100 * sum(next_shorts.values()),
                       "long_futures_trade_details": long_trade_details,
                       "short_futures_trade_details": short_trade_details,
                       "long_matched_usd_rate_pct": (
                           100 * long_usd_rate["rate"]
                           if long_usd_rate["rate"] is not None else None),
                       "short_matched_usd_rate_pct": (
                           100 * short_usd_rate["rate"]
                           if short_usd_rate["rate"] is not None else None),
                       "long_matched_usd_rate_components": long_usd_rate["components"],
                       "short_matched_usd_rate_components": short_usd_rate["components"],
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
                       "long_weighted_forward_premium_pct": (
                           100 * long_weighted_premium if long_weighted_premium is not None else None),
                       "short_weighted_forward_premium_pct": (
                           100 * short_weighted_premium if short_weighted_premium is not None else None),
                       "long_forward_maturity_days": long_forward_maturity_days,
                       "short_forward_maturity_days": short_forward_maturity_days,
                       "allocation_long_lease_signal_pct": 100 * position["signal"],
                       "long_book_extension_pct": 100 * position["long_extension"],
                       "available_futures_min_maturity_days": (
                           market_diagnostics["min_maturity_days"]
                           if market_diagnostics else None),
                       "available_futures_max_maturity_days": (
                           market_diagnostics["max_maturity_days"]
                           if market_diagnostics else None),
                       "cash_plus_slv_weight_pct": 100 * (position["treasury"] + position["slv"]),
                       "short_shortest_maturity_days": shortest_short_maturity_days,
                       "short_longest_maturity_days": longest_short_maturity_days,
                       "number_of_futures_maturities": len(position["longs"]) + len(position["shorts"]),
                       "largest_futures_maturity_share_pct": 100 * largest_share,
                       "long_symbols": ";".join(position["longs"]),
                       "short_symbols": ";".join(position["shorts"])})
    return output, missing_futures_intervals


def write_csv(path, rows, fieldnames=None):
    if not rows and not fieldnames:
        return
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames or list(rows[0]))
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
    parser.add_argument("--positive-entry-rate", type=float, default=0.0,
                        help="Lease rate above which a contract becomes eligible for a long")
    parser.add_argument("--long-contract-selection",
                        choices=["shortest_maturity", "highest_lease_rate",
                                 "weighted_lease_rate"],
                        default="shortest_maturity",
                        help="How to select among long contracts above the entry rate")
    parser.add_argument("--max-long-future", type=float, default=0.50)
    parser.add_argument("--long-maturity-bonus-per-year", type=float, default=0.004,
                        help="Added long score per year shorter than the longest candidate")
    parser.add_argument("--negative-short-start-rate", type=float, default=-0.005,
                        help="Lease rate below which a contract becomes eligible for shorting")
    parser.add_argument("--negative-short-full-rate", type=float, default=-0.15)
    parser.add_argument("--max-short-fraction-of-slv", type=float, default=0.50,
                        help="Maximum short-futures notional as a fraction of capital")
    parser.add_argument("--short-contract-selection",
                        choices=["weighted_lease_rate", "lowest_lease_rate"],
                        default="weighted_lease_rate")
    parser.add_argument("--short-maturity-bonus-per-year", type=float, default=0.004,
                        help="Added short-selection score per extra year of maturity")
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
                                positive_entry_rate=args.positive_entry_rate,
                                positive_full_rate=args.positive_full_rate,
                                long_contract_selection=args.long_contract_selection,
                                long_maturity_bonus_per_year=args.long_maturity_bonus_per_year,
                                max_long_future=args.max_long_future,
                                negative_short_start_rate=args.negative_short_start_rate,
                                negative_short_full_rate=args.negative_short_full_rate,
                                max_short_fraction_of_slv=args.max_short_fraction_of_slv,
                                short_contract_selection=args.short_contract_selection,
                                short_maturity_bonus_per_year=args.short_maturity_bonus_per_year,
                                bond_mode=args.bond_mode,
                                treasury_asset=args.treasury_asset)
        rows, missing = run_backtest(spot, contracts, rates, by_day, parameters)
        write_csv(args.output_dir / f"strategy_min_{min_days}d.csv", rows)
        write_csv(args.output_dir / f"missing_returns_min_{min_days}d.csv", missing,
                  ["signal_date", "execution_date", "exit_date", "leg", "symbol", "reason"])
        if rows:
            summary.append({"min_days": min_days, "bond_mode": args.bond_mode,
                            "start": rows[0]["date"], "end": rows[-1]["date"],
                            "observations": len(rows),
                            "simple_total_return_pct": rows[-1]["simple_cumulative_return_pct"],
                            "compounded_total_return_pct": rows[-1]["compounded_return_pct"],
                            "ending_nav": rows[-1]["nav"],
                            "missing_futures_intervals": len(missing)})
    write_csv(args.output_dir / "summary.csv", summary)
    config = vars(args).copy()
    config["root"] = str(config["root"]); config["output_dir"] = str(config["output_dir"])
    with open(args.output_dir / "parameters.json", "w", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
