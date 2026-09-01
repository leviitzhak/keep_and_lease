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
from collections import Counter, defaultdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from maturity_scoring import (
    BoundaryAnchors, PureMaturityAdjustment, RelativeAdjustment, adjusted_score, allocate_scores,
    signed_distance,
)
from rate_change_attribution import InstrumentAttribution, build_rate_change_point
from market_data_store import (
    ASSET_BY_PREFIX, data_directory, read_cached_asset, read_contract_csvs,
    read_spot_csv,
)

MONTHS = dict(zip("FGHJKMNQUVXZ", range(1, 13)))
TENORS = [(91, "DTB3"), (182, "DTB6"), (365, "DGS1"),
          (730, "DGS2"), (1095, "DGS3"), (1825, "DGS5")]


@dataclass
class Parameters:
    min_days: int
    reactivity: str = "same_day"
    long_allocation_half_life_days: float = 0.0
    short_allocation_half_life_days: float = 0.0
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
    long_maturity_line_intercept: float = 0.0
    long_maturity_line_slope_per_year: float = 0.004
    long_relative_strength: float = 1.0
    long_score_rate_scale: float | None = None
    long_score_adjustment_clip: float | None = None
    long_pure_maturity_strength: float = 0.0
    long_pure_maturity_scale_days: float = 365.0
    long_pure_maturity_clip: float = 3.0
    long_maturity_bonus_per_year: float = 0.004
    long_extreme_qualification_rate: float = 0.08
    long_extreme_maturity_advantage_per_year: float = 0.005
    long_extreme_maturity_bonus_per_year: float = 0.01
    max_futures_treasury_fraction: float = 0.50
    negative_short_start_rate: float = -0.005
    negative_short_full_rate: float = -0.15
    max_short_fraction_of_long_leg: float = 0.50
    short_contract_selection: str = "weighted_lease_rate"
    short_maturity_line_intercept: float = 0.0
    short_maturity_line_slope_per_year: float = 0.004
    short_relative_strength: float = 1.0
    short_score_rate_scale: float | None = None
    short_score_adjustment_clip: float | None = None
    short_pure_maturity_strength: float = 0.0
    short_pure_maturity_scale_days: float = 365.0
    short_pure_maturity_clip: float = 3.0
    score_rate_scale: float = 0.01
    score_adjustment_clip: float = 3.0
    short_maturity_bonus_per_year: float = 0.004
    short_extreme_qualification_rate: float = -0.08
    short_extreme_maturity_advantage_per_year: float = 0.005
    short_extreme_maturity_bonus_per_year: float = 0.01
    bond_mode: str = "accrual"
    treasury_asset: str = "matched_maturity"
    treasury_allocation_mode: str = "shortest_rolling"


def clamp(x, low=0.0, high=1.0):
    return max(low, min(high, x))


def smooth_allocation(target, previous, half_life_days, elapsed_days):
    """Move an allocation toward its target with a calendar-day half-life.

    A zero half-life disables smoothing.  Contract ranking remains current;
    this function changes only the total notional allocated to a leg.
    """
    if previous is None or half_life_days <= 0:
        return target
    alpha = 1.0 - 2.0 ** (-max(0.0, elapsed_days) / half_life_days)
    return previous + alpha * (target - previous)


def parse_date(value):
    value = value.strip().strip('"')
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(value)


def expiry_from_symbol(symbol):
    """Infer the contract month from TurtleTrader's PREFIXyyM symbols."""
    match = re.fullmatch(r"[A-Z]+(\d{2})([FGHJKMNQUVXZ])", symbol.upper())
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


def read_generic_contracts(root, archive_name, symbol_prefix):
    """Read an unscaled TurtleTrader individual-contract archive.

    Unlike the old silver source, the additional archives already contain
    decimal exchange prices.  A prefix filter also excludes the stray CC
    (cocoa) file bundled in the corn archive.
    """
    asset = ASSET_BY_PREFIX.get(symbol_prefix.upper())
    if asset:
        cached = read_cached_asset(Path(root), asset)
        if cached is not None:
            return cached[1], cached[2]
        materialized = data_directory(Path(root)) / asset / "futures"
        if materialized.is_dir():
            return read_contract_csvs(Path(root), asset, symbol_prefix)
    contracts, volumes = {}, {}
    with zipfile.ZipFile(root / archive_name) as archive:
        for filename in archive.namelist():
            if not filename.lower().endswith(".txt"):
                continue
            symbol = Path(filename).stem.upper()
            if not re.fullmatch(
                    rf"{re.escape(symbol_prefix.upper())}\d{{2}}[FGHJKMNQUVXZ]",
                    symbol):
                continue
            rows = {}
            stream = io.TextIOWrapper(archive.open(filename), encoding="utf-8-sig")
            for row in csv.reader(stream):
                if not row or row[0].strip('"').lower() == "date":
                    continue
                try:
                    day, value = parse_date(row[0]), float(row[4])
                    if value <= 0:
                        continue
                    rows[day] = value
                    volumes[(symbol, day)] = (
                        float(row[5]) if len(row) > 5 and row[5] else 0.0)
                except (ValueError, TypeError, IndexError):
                    pass
            if rows:
                contracts[symbol] = rows
    return contracts, volumes


def build_proxy_market(root, archive_name, symbol_prefix):
    """Build a curve market using the nearest live future as the direct proxy.

    Spot histories of consistent quality are not available for every added
    market.  The nearest live contract is therefore the explicit direct-
    commodity proxy.  Deferred premiums and lease signals are measured against
    it; no continuous-series back adjustment is applied.
    """
    contracts, volumes = read_generic_contracts(
        root, archive_name, symbol_prefix)
    rates = read_rates(root)
    quotes = defaultdict(list)
    for symbol, prices in contracts.items():
        expiry = expiry_from_symbol(symbol)
        if not expiry:
            continue
        for day, value in prices.items():
            days = (expiry - day).days
            if days > 0:
                quotes[day].append((days, -volumes.get((symbol, day), 0.0),
                                    symbol, value))
    spot = {day: min(day_quotes)[3]
            for day, day_quotes in quotes.items() if day_quotes}
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
            by_day[day].append({
                "symbol": symbol, "days": days, "future": future,
                "spot": physical, "rate": rate, "premium": premium,
                "lease": lease, "volume": volumes.get((symbol, day), 0.0)})
    return spot, contracts, rates, by_day


def build_spot_market(root, archive_name, symbol_prefix, spot):
    """Build a futures curve against an independently observed cash price."""
    contracts, volumes = read_generic_contracts(
        root, archive_name, symbol_prefix)
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
            by_day[day].append({
                "symbol": symbol, "days": days, "future": future,
                "spot": physical, "rate": rate, "premium": premium,
                "lease": lease, "volume": volumes.get((symbol, day), 0.0)})
    usable_days = set(by_day)
    return ({day: value for day, value in spot.items() if day in usable_days},
            contracts, rates, by_day)


def read_zip_spot(root, member):
    result = {}
    with zipfile.ZipFile(root / "gold_silver.zip") as archive:
        stream = io.TextIOWrapper(archive.open(member), encoding="utf-8-sig")
        for row in csv.DictReader(stream):
            try:
                value = float(row["price"])
                if value > 0:
                    result[date.fromisoformat(row["date"])] = value
            except (ValueError, TypeError, KeyError):
                pass
    return result


def read_csv_spot(root, filename, value_column):
    result = {}
    with open(root / filename, encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            try:
                value = float(row[value_column])
                if value > 0:
                    result[date.fromisoformat(row["observation_date"])] = value
            except (ValueError, TypeError, KeyError):
                pass
    return result


def read_spot(root):
    cached = read_cached_asset(Path(root), "silver")
    if cached is not None:
        return cached[0]
    if (data_directory(Path(root)) / "silver").is_dir():
        return read_spot_csv(Path(root), "silver")
    return read_zip_spot(root, "silver_price.csv")


def read_contracts(root, spot):
    cached = read_cached_asset(Path(root), "silver")
    if cached is not None:
        return cached[1], cached[2]
    if (data_directory(Path(root)) / "silver" / "futures").is_dir():
        return read_contract_csvs(Path(root), "silver", "SI", spot)
    contracts = {}
    volumes = {}
    with zipfile.ZipFile(root / "si.zip") as archive:
        for filename in archive.namelist():
            if not filename.endswith(".txt"):
                continue
            symbol = filename[:-4]
            rows = {}
            parsed = []
            stream = io.TextIOWrapper(archive.open(filename), encoding="utf-8-sig")
            for row in csv.reader(stream):
                if not row or row[0].strip('"').lower() == "date":
                    continue
                try:
                    day, raw = parse_date(row[0]), float(row[4])
                    physical = spot.get(day)
                    if not physical or physical <= 0:
                        continue
                    scales = (1, 10, 100, 1000, 10000)
                    daily_scale = min(
                        scales, key=lambda scale: abs(raw / scale / physical - 1))
                    parsed.append((day, raw, daily_scale,
                                   float(row[5]) if len(row) > 5 else 0.0))
                except (ValueError, TypeError, IndexError):
                    pass
            # Quote scale is fixed within a contract file. Inferring it for
            # each row can create a spurious 10x jump on a volatile spot day.
            if parsed:
                contract_scale = Counter(x[2] for x in parsed).most_common(1)[0][0]
                for day, raw, _, volume in parsed:
                    rows[day] = raw / contract_scale
                    volumes[(symbol, day)] = volume
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
    """Compatibility adapter to the canonical score-to-weight converter."""
    return allocate_scores(dict(items), total)


def scoring_boundary(p, direction):
    """Return the canonical two-anchor boundary in maturity-day units."""
    intercept = getattr(p, f"{direction}_maturity_line_intercept")
    slope = getattr(p, f"{direction}_maturity_line_slope_per_year")
    return BoundaryAnchors.from_slope_intercept(
        0.0, 365.0, slope / 365.0, intercept)


def scoring_adjustment(p, direction):
    return RelativeAdjustment(
        strength=getattr(p, f"{direction}_relative_strength"),
        rate_scale=(getattr(p, f"{direction}_score_rate_scale")
                    or p.score_rate_scale),
        clip=(getattr(p, f"{direction}_score_adjustment_clip")
              if getattr(p, f"{direction}_score_adjustment_clip") is not None
              else p.score_adjustment_clip),
    )


def pure_maturity_adjustment(p, direction):
    return PureMaturityAdjustment(
        strength=getattr(p, f"{direction}_pure_maturity_strength"),
        scale_days=getattr(p, f"{direction}_pure_maturity_scale_days"),
        clip=getattr(p, f"{direction}_pure_maturity_clip"),
    )


def maturity_line_score(contract, p, direction):
    """Compatibility adapter returning the canonical signed distance."""
    return signed_distance(
        contract["lease"], contract["days"], scoring_boundary(p, direction),
        direction)


def maturity_line_adjusted_score(base_score, contract, p, direction):
    """Compatibility adapter to the one canonical relative scoring formula."""
    return adjusted_score(
        base_score, contract["lease"], contract["days"],
        scoring_boundary(p, direction), scoring_adjustment(p, direction),
        direction, pure_maturity_adjustment(p, direction))


def score_diagnostic(contract, p, direction, eligibility_threshold,
                     target_weight=0.0):
    """Explain a score using the same canonical primitives used for trading."""
    rate = contract["lease"]
    eligible = (rate >= eligibility_threshold if direction == "long"
                else rate <= eligibility_threshold)
    base = (rate - eligibility_threshold if direction == "long"
            else eligibility_threshold - rate)
    boundary = scoring_boundary(p, direction)
    adjustment = scoring_adjustment(p, direction)
    distance = signed_distance(rate, contract["days"], boundary, direction)
    rate_adjustment = adjustment.signed_adjustment(distance)
    pure_adjustment = pure_maturity_adjustment(
        p, direction).signed_adjustment(contract["days"], direction)
    final = (max(0.0, base) / adjustment.rate_scale
             + rate_adjustment + pure_adjustment
             if eligible else None)
    return {
        "symbol": contract["symbol"], "direction": direction,
        "maturity_days": contract["days"], "rate_pct": 100 * rate,
        "boundary_value_pct": 100 * boundary.value(contract["days"]),
        "eligible": eligible, "signed_distance_pct": 100 * distance,
        "base_score": max(0.0, base),
        "relative_adjustment": rate_adjustment,
        "pure_maturity_adjustment": pure_adjustment,
        "final_score": final, "target_weight_pct": 100 * target_weight,
    }


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
        base_score = max(1e-9, -contract["lease"])
        score = maturity_line_adjusted_score(
            base_score, contract, p, "short")
        ranked.append((contract["symbol"], score))
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


def positions_for_day(candidates, p, previous=None, elapsed_days=1.0):
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
        def select_long(contracts):
            lease_floor = min(x["lease"] for x in contracts)
            return max(
                contracts, key=lambda x: (
                    maturity_line_adjusted_score(
                        max(1e-9, x["lease"] - lease_floor),
                        x, p, "long"),
                    -x["days"], x["volume"]))
    else:
        select_long = lambda contracts: min(
            contracts, key=lambda x: (x["days"], -x["volume"]))
    if p.long_contract_selection == "weighted_lease_rate":
        long_leg = proportional_allocation([
            (x["symbol"], maturity_line_adjusted_score(
                max(1e-9, x["lease"] - min(
                    candidate["lease"] for candidate in eligible)),
                x, p, "long"))
            for x in eligible
        ], 1.0)
    else:
        diagnostic_long = select_long(eligible)
        long_leg = {diagnostic_long["symbol"]: 1.0}

    # The long and short books are independent. Select the long contract using
    # the configured maturity/rate policy after enforcing the entry threshold.
    positive = [x for x in eligible if x["lease"] > p.positive_entry_rate]
    # Fixed allocation is unconditional: enabled fixed legs allocate their
    # configured maximum even when no contract crosses an entry threshold.
    long_candidates = (eligible if p.long_futures_entry_mode == "fixed"
                       else positive)
    selected_positive = select_long(long_candidates) if long_candidates else None
    # SLV is controlled by the lease rate of the configured long book, not by
    # the most negative contract used to construct the short-futures signal.
    long_signal = weighted_contract_value(long_leg, contract_map, "lease")
    # A line can suppress every weighted diagnostic score.  The direct/fund
    # allocation still needs a market lease signal, so fall back to the best
    # eligible lease without creating a futures allocation.
    if long_signal is None:
        long_signal = max(x["lease"] for x in eligible)

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
    if p.long_futures_entry_mode == "fixed":
        positive_strength = 1.0
    negative_strength = clamp(
        (short_start_rate - signal) /
        (short_start_rate - p.negative_short_full_rate))
    if p.short_futures_entry_mode == "fixed":
        negative_strength = 1.0
    # The configured commodity sleeve is the complete long commodity leg.
    # A share of that leg is implemented by Treasury collateral + long futures;
    # the complementary share is held in the replicating fund.  Therefore,
    # whenever both implementations are enabled, fund + futures replication = 1.
    futures_treasury_share = (
        p.max_futures_treasury_fraction * positive_strength
        if p.enable_cash_long_futures_leg else 0.0)
    futures_treasury_share = clamp(futures_treasury_share)
    futures_treasury_share = smooth_allocation(
        futures_treasury_share,
        previous.get("base_treasury") if previous else None,
        p.long_allocation_half_life_days,
        elapsed_days,
    )
    # The fund is structurally the complement of futures replication.  Keep
    # accepting the legacy parameter for JSON compatibility, but never allow
    # it to leave the base commodity leg under-invested.
    slv_weight = 1.0 - futures_treasury_share
    treasury_weight = futures_treasury_share

    # Long-futures notional equals the Treasury-funded replication share; it is
    # no longer an independent overlay on top of a fully invested base.
    base_longs = {}
    long_notional = futures_treasury_share
    allocation_long_candidates = (
        long_candidates if long_candidates else
        (eligible if long_notional > 0 else []))
    allocation_selected_positive = (
        selected_positive if selected_positive else
        (select_long(allocation_long_candidates)
         if allocation_long_candidates else None))
    if allocation_long_candidates and p.long_contract_selection == "weighted_lease_rate":
        long_score_threshold = (
            min(x["lease"] for x in allocation_long_candidates) - 1e-9
            if p.long_futures_entry_mode == "fixed" or not long_candidates
            else p.positive_entry_rate)
        base_longs = proportional_allocation([
            (x["symbol"], maturity_line_adjusted_score(
                x["lease"] - long_score_threshold, x, p, "long"))
            for x in allocation_long_candidates
        ], long_notional)
    elif allocation_selected_positive:
        base_longs[allocation_selected_positive["symbol"]] = (
            long_notional)
    total_short = (p.max_short_fraction_of_long_leg * negative_strength
                   if p.enable_short_book else 0.0)
    total_short = smooth_allocation(
        total_short,
        previous.get("long_extension") if previous else None,
        p.short_allocation_half_life_days,
        elapsed_days,
    )
    # The short book is defined as short futures plus an equal-sized extension
    # of the active base long book.  If both long sleeves are inactive there is
    # no composition to extend, so the complete short book must also be zero.
    if slv_weight + sum(base_longs.values()) <= 0:
        total_short = 0.0

    # Score trades off negative lease edge against a preference for longer
    # maturity (the opposite of the long book). A 0.02 bonus means one extra
    # year can compensate for 2 percentage points less-negative annualized
    # lease rate.
    negative = [x for x in eligible if x["lease"] < short_start_rate]
    short_candidates = (eligible if p.short_futures_entry_mode == "fixed"
                        else negative)
    short_score_threshold = (
        max(x["lease"] for x in short_candidates) + 1e-9
        if short_candidates and p.short_futures_entry_mode == "fixed"
        else short_start_rate)
    allocation_short_candidates = (
        short_candidates if short_candidates else
        (eligible if total_short > 0 else []))
    allocation_short_threshold = (
        max(x["lease"] for x in allocation_short_candidates) + 1e-9
        if allocation_short_candidates and not short_candidates
        else short_score_threshold)
    for x in allocation_short_candidates:
        # A short's lease edge is the magnitude of lease rate minus entry
        # threshold. It is positive because qualifying leases are below entry.
        base_score = max(0.0, allocation_short_threshold - x["lease"])
        x["short_score"] = maturity_line_adjusted_score(
            base_score, x, p, "short")
    if allocation_short_candidates and p.short_contract_selection == "lowest_lease_rate":
        lowest = min(allocation_short_candidates, key=lambda x: (x["lease"], x["days"], -x["volume"]))
        shorts = {lowest["symbol"]: total_short}
    else:
        scores = [(x["symbol"], x["short_score"])
                  for x in allocation_short_candidates]
        shorts = proportional_allocation(scores, total_short)

    # Resize with the signal, but change contracts only for a better lease or
    # when the configured minimum-maturity boundary forces a roll.
    base_longs = _sticky_contract_book(
        base_longs, previous.get("base_longs") if previous else None,
        contract_map, {x["symbol"] for x in allocation_long_candidates}, "long", p)
    shorts = _sticky_contract_book(
        shorts, previous.get("shorts") if previous else None,
        contract_map, {x["symbol"] for x in allocation_short_candidates}, "short", p)

    # A short-futures position is paired with an equally sized extension of
    # the complete long commodity leg.  Treasury collateral is not counted as
    # a second long leg: fund exposure + long-futures exposure is the commodity
    # leg against which the short fraction is defined.
    base_long_total = slv_weight + sum(base_longs.values())
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
        if p.short_contract_selection == "lowest_lease_rate":
            lowest = min(eligible, key=lambda x: (x["lease"], x["days"], -x["volume"]))
            short_leg = {lowest["symbol"]: 1.0}
        else:
            # The diagnostic portfolio is threshold-independent, but it still
            # uses the canonical relative scoring pipeline.  Setting the gate
            # to the highest observed rate makes every available contract
            # eligible without introducing a separate maturity formula.
            diagnostic_threshold = max(x["lease"] for x in eligible) + 1e-12
            short_leg = proportional_allocation([
                (x["symbol"], maturity_line_adjusted_score(
                    diagnostic_threshold - x["lease"], x, p, "short"))
                for x in eligible
            ], 1.0)
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
    if p.treasury_allocation_mode == "rate_weighted_maturities":
        available = [
            (tenor, asof_rate(rates, tenor, day))
            for tenor, _ in TENORS
        ]
        available = [(tenor, rate) for tenor, rate in available
                     if rate is not None]
        if not available:
            return 0.0
        positive_total = sum(max(0.0, rate) for _, rate in available)
        if positive_total > 0:
            weights = [
                (tenor, max(0.0, rate) / positive_total)
                for tenor, rate in available
            ]
        else:
            # If the complete curve is non-positive, use the least-negative
            # tenor rather than creating undefined or negative allocations.
            best = max(available, key=lambda item: item[1])[0]
            weights = [(tenor, 1.0 if tenor == best else 0.0)
                       for tenor, _ in available]
        return sum(
            weight * bond_return(
                rates, day, next_day, tenor, p.bond_mode)
            for tenor, weight in weights
        )
    if p.treasury_allocation_mode == "shortest_rolling":
        return bond_return(rates, day, next_day, TENORS[0][0], p.bond_mode)
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


def _rescaled_book_return(book, target_total, day, next_day, contracts, direction):
    """Counterfactual return contribution from retaining the prior contract mix."""
    source_total = sum(book.values())
    if not source_total or not target_total:
        return 0.0, True
    result = 0.0
    for symbol, weight in book.items():
        value, found = futures_interval_return(symbol, day, next_day, contracts)
        if not found:
            return 0.0, False
        result += direction * target_total * weight / source_total * value
    return result, True


def multiplicative_log_contributions(total_return, contributions):
    """Map additive daily contributions to exact, order-free return factors.

    If ``total_return = sum(contributions.values())``, the returned log
    contributions sum to ``log1p(total_return)``.  Consequently, multiplying
    ``exp(log_contribution)`` for every component reconstructs exactly
    ``1 + total_return`` (up to floating-point precision).
    """
    if total_return <= -1.0:
        raise ValueError("multiplicative attribution requires return > -100%")
    values = dict(contributions)
    if not values:
        return {}
    # Absorb tiny arithmetic drift so the identity remains exact in output.
    anchor = max(values, key=lambda name: abs(values[name]))
    values[anchor] += total_return - sum(values.values())
    scale = (math.log1p(total_return) / total_return
             if abs(total_return) > 1e-15 else 1.0)
    logs = {name: value * scale for name, value in values.items()}
    logs[anchor] += math.log1p(total_return) - sum(logs.values())
    return logs


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
    lease_book_nav = 1.0
    keep_book_nav = 1.0
    keep_contribution_nav = 1.0
    replicating_fund_book_nav = 1.0
    futures_treasury_book_nav = 1.0
    lease_factor_nav = 1.0
    keep_factor_nav = 1.0
    lease_fund_factor_nav = 1.0
    lease_futures_treasury_factor_nav = 1.0
    lease_value = 1.0
    keep_value = 0.0
    replicating_value = None
    futures_treasury_value = None
    initial_commodity_price = None
    asset_simple = {"long_futures": 0.0, "short_futures": 0.0, "slv": 0.0, "treasury": 0.0}
    asset_nav = {"long_futures": 1.0, "short_futures": 1.0, "slv": 1.0, "treasury": 1.0}
    sgov_proxy_nav = 1.0
    missing_futures_intervals = []
    previous_valid_position = None
    previous_position = None
    if p.reactivity == "same_day":
        intervals = zip(days, days, days[1:])
    elif p.reactivity == "next_day":
        intervals = zip(days, days[1:], days[2:])
    else:
        raise ValueError("reactivity must be 'same_day' or 'next_day'")
    previous_signal_day = None
    # Same-day mode forms the close-derived signal and rebalances at that close;
    # next-day mode executes it at the following available close.  In either
    # case, the resulting position earns the execution-to-exit return.
    for signal_day, execution_day, exit_day in intervals:
        signal_elapsed = ((signal_day - previous_signal_day).days
                          if previous_signal_day else 0.0)
        position = positions_for_day(
            by_day[signal_day], p, previous_position, signal_elapsed)
        previous_position = position
        previous_signal_day = signal_day
        if execution_day not in spot or exit_day not in spot:
            continue
        execution_lag = (execution_day - signal_day).days
        holding_days = max(1.0, position["bond_days"] - execution_lag)
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
        long_futures_contribution = 0.0
        base_long_futures_contribution = 0.0
        valid_interval = True
        short_total = sum(position["shorts"].values())
        long_total = sum(position["longs"].values())
        for symbol, weight in position["longs"].items():
            value, found = futures_interval_return(symbol, execution_day, exit_day, contracts)
            contribution = weight * value
            long_futures_contribution += contribution
            portfolio_return += contribution
            base_contribution = position["base_longs"].get(symbol, 0.0) * value
            base_long_futures_contribution += base_contribution
            base_long_return += base_contribution
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

        # Exact daily return attribution. Futures price returns are separated
        # into the contemporaneous silver move and basis-related effects. The
        # roll/rebalance effect is the difference versus retaining the prior
        # contract mix at the current side's total notional. The remaining
        # basis effect is split into implied lease carry and lease-rate/basis
        # repricing; the final residual is retained so the displayed columns
        # always reconcile exactly to the portfolio return.
        raw_spot_return = spot[exit_day] / spot[execution_day] - 1
        silver_price_component = (
            position["slv"] + long_total - short_total) * raw_spot_return
        slv_expense_component = -position["slv"] * p.slv_expense * elapsed / 365
        treasury_component = position["treasury"] * treasury_return
        actual_futures_component = long_futures_contribution + short_futures_return
        futures_basis_component = actual_futures_component - (
            long_total - short_total) * raw_spot_return
        roll_component = 0.0
        if previous_valid_position is not None:
            kept_long, long_found = _rescaled_book_return(
                previous_valid_position["longs"], long_total,
                execution_day, exit_day, contracts, 1.0)
            kept_short, short_found = _rescaled_book_return(
                previous_valid_position["shorts"], short_total,
                execution_day, exit_day, contracts, -1.0)
            if long_found and short_found:
                roll_component = actual_futures_component - kept_long - kept_short
        lease_carry_component = 0.0
        for symbol, weight in position["longs"].items():
            lease_carry_component += weight * position["contracts"][symbol]["lease"] * elapsed / 365
        for symbol, weight in position["shorts"].items():
            lease_carry_component -= weight * position["contracts"][symbol]["lease"] * elapsed / 365
        rate_change_instruments = []
        for direction, holdings in ((1.0, position["longs"]),
                                    (-1.0, position["shorts"])):
            for symbol, weight in holdings.items():
                start = position["contracts"][symbol]
                start_price = contracts.get(symbol, {}).get(execution_day)
                end_price = contracts.get(symbol, {}).get(exit_day)
                remaining_days = max(0, start["days"] - elapsed)
                end_rate = usd_rate(rates, exit_day, remaining_days)
                if not start_price or not end_price or end_rate is None:
                    continue
                # Freeze the start lease curve while allowing the observed spot
                # and USD-rate legs to move.  This mirrors the engine's simple
                # annualized premium convention: premium=(r-usd_lease)*T.
                frozen_end_price = spot[exit_day] * (
                    1 + (end_rate - start["lease"]) * remaining_days / 365)
                rate_change_instruments.append(InstrumentAttribution(
                    symbol=symbol,
                    signed_notional=direction * weight,
                    start_maturity=start["days"],
                    observed_end_value=end_price / start_price,
                    frozen_curve_end_value=frozen_end_price / start_price,
                    rate_before=start["lease"],
                    rate_after=(
                        end_rate - (end_price / spot[exit_day] - 1) *
                        365 / remaining_days if remaining_days else None),
                ))
        rate_change_points = [build_rate_change_point(
            start_date=execution_day.isoformat(), end_date=exit_day.isoformat(),
            leg=leg, commodity="commodity", instruments=[
                item for item in rate_change_instruments
                if (item.signed_notional > 0) == (leg == "long")],
            portfolio_value=1.0)
            for leg in ("long", "short")]
        lease_repricing_component = sum(
            point["rate_change_pnl"] for point in rate_change_points)
        attributed = (silver_price_component + slv_expense_component +
                      treasury_component + lease_carry_component +
                      lease_repricing_component + roll_component)
        attribution_residual = portfolio_return - attributed
        matched_long_extension_return = position["extension_ratio"] * base_long_return
        short_book_return = matched_long_extension_return + short_futures_return
        fund_lease_contribution = position["base_slv"] * spot_return
        futures_treasury_lease_contribution = (
            position["base_treasury"] * treasury_return +
            base_long_futures_contribution)
        replication_weight = sum(position["base_longs"].values())
        futures_treasury_book_return = (
            treasury_return + base_long_futures_contribution / replication_weight
            if replication_weight > 0 else None)
        keep_book_standalone_return = (
            short_book_return / short_total if short_total > 0 else None)
        strategy_logs = multiplicative_log_contributions(
            portfolio_return,
            {"lease": base_long_return, "keep": short_book_return})
        lease_logs = multiplicative_log_contributions(
            base_long_return,
            {"fund": fund_lease_contribution,
             "futures_treasury": futures_treasury_lease_contribution})
        starting_nav = nav
        if replicating_value is None:
            replicating_value = position["base_slv"]
            futures_treasury_value = position["base_treasury"]
            initial_commodity_price = spot[execution_day]
        replicating_value += starting_nav * fund_lease_contribution
        futures_treasury_value += starting_nav * futures_treasury_lease_contribution
        lease_value += starting_nav * base_long_return
        keep_value += starting_nav * short_book_return
        simple += portfolio_return
        long_simple += base_long_return
        extension_simple += matched_long_extension_return
        short_simple += short_book_return
        nav *= 1 + portfolio_return
        lease_book_nav *= 1 + base_long_return
        keep_contribution_nav *= 1 + short_book_return
        replicating_fund_book_nav *= 1 + spot_return
        if keep_book_standalone_return is not None:
            keep_book_nav *= 1 + keep_book_standalone_return
        if futures_treasury_book_return is not None:
            futures_treasury_book_nav *= 1 + futures_treasury_book_return
        lease_factor_nav *= math.exp(strategy_logs["lease"])
        keep_factor_nav *= math.exp(strategy_logs["keep"])
        lease_fund_factor_nav *= math.exp(lease_logs["fund"])
        lease_futures_treasury_factor_nav *= math.exp(
            lease_logs["futures_treasury"])
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
        # Diagnostics describe the curve that decided the allocation. Futures
        # trade prices below are still measured on the execution close.
        market_diagnostics = market_diagnostics_for_day(
            by_day.get(signal_day, []), p)
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
            diagnostic_longs, contracts, execution_day)
        short_weighted_future_price = weighted_futures_price(
            diagnostic_shorts, contracts, execution_day)
        long_usd_rate = matched_usd_rate_details(
            rates, signal_day, diagnostic_longs, diagnostic_contracts)
        short_usd_rate = matched_usd_rate_details(
            rates, signal_day, diagnostic_shorts, diagnostic_contracts)
        # Rebalance at the displayed close.  Compare with the preceding
        # position and weight the executed contracts by absolute traded notional.
        prior_longs = previous_valid_position["longs"] if previous_valid_position else {}
        prior_shorts = previous_valid_position["shorts"] if previous_valid_position else {}
        (entered_long_price, entered_long_size,
         exited_long_price, exited_long_size) = futures_trade_prices(
            prior_longs, position["longs"], contracts, execution_day)
        (entered_short_price, entered_short_size,
         exited_short_price, exited_short_size) = futures_trade_prices(
            prior_shorts, position["shorts"], contracts, execution_day)
        long_trade_details = futures_trade_details(
            prior_longs, position["longs"], contracts, execution_day)
        short_trade_details = futures_trade_details(
            prior_shorts, position["shorts"], contracts, execution_day)
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
        commodity_price_index = spot[exit_day] / initial_commodity_price
        output.append({"date": execution_day.isoformat(), "exit_date": exit_day.isoformat(),
                       "signal_date": signal_day.isoformat(),
                       "execution_date": execution_day.isoformat(), "mode": position["mode"],
                       "signal_annual_pct": 100 * position["signal"],
                       "positive_signal_annual_pct": 100 * position["positive_signal"],
                       "negative_signal_annual_pct": 100 * position["negative_signal"],
                       "interval_return_pct": 100 * portfolio_return,
                       "silver_price_return_contribution_pct": 100 * silver_price_component,
                       "slv_expense_contribution_pct": 100 * slv_expense_component,
                       "treasury_return_contribution_pct": 100 * treasury_component,
                       "lease_carry_contribution_pct": 100 * lease_carry_component,
                       "lease_rate_change_contribution_pct": 100 * lease_repricing_component,
                       "rate_change_attribution_points": rate_change_points,
                       "rolling_contribution_pct": 100 * roll_component,
                       "other_return_contribution_pct": 100 * attribution_residual,
                       "long_book_interval_return_pct": 100 * base_long_return,
                       "matched_long_extension_interval_return_pct": (
                           100 * matched_long_extension_return),
                       "short_book_interval_return_pct": 100 * short_book_return,
                       "lease_book_interval_return_pct": 100 * base_long_return,
                       "keep_book_interval_return_pct": (
                           100 * keep_book_standalone_return
                           if keep_book_standalone_return is not None else None),
                       "keep_book_contribution_interval_return_pct": (
                           100 * short_book_return),
                       "replicating_fund_book_interval_return_pct": 100 * spot_return,
                       "futures_treasury_book_interval_return_pct": (
                           100 * futures_treasury_book_return
                           if futures_treasury_book_return is not None else None),
                       "lease_book_factor_interval_return_pct": (
                           100 * math.expm1(strategy_logs["lease"])),
                       "keep_book_factor_interval_return_pct": (
                           100 * math.expm1(strategy_logs["keep"])),
                       "lease_fund_factor_interval_return_pct": (
                           100 * math.expm1(lease_logs["fund"])),
                       "lease_futures_treasury_factor_interval_return_pct": (
                           100 * math.expm1(lease_logs["futures_treasury"])),
                       "simple_cumulative_return_pct": 100 * simple,
                       "long_book_cumulative_return_pct": 100 * long_simple,
                       "matched_long_extension_cumulative_return_pct": (
                           100 * extension_simple),
                       "short_book_cumulative_return_pct": 100 * short_simple,
                       "compounded_return_pct": 100 * (nav - 1), "nav": nav,
                       "replicating_leg_value": replicating_value,
                       "futures_treasury_value": futures_treasury_value,
                       "lease_book_value": lease_value,
                       "keep_book_value": keep_value,
                       "replicating_leg_underlying_value": replicating_value / commodity_price_index,
                       "futures_treasury_underlying_value": futures_treasury_value / commodity_price_index,
                       "lease_book_underlying_value": lease_value / commodity_price_index,
                       "keep_book_underlying_value": keep_value / commodity_price_index,
                       "initial_replicating_leg_value": position["base_slv"],
                       "initial_futures_treasury_value": position["base_treasury"],
                       "lease_book_compounded_return_pct": 100 * (lease_book_nav - 1),
                       "keep_book_compounded_return_pct": 100 * (keep_book_nav - 1),
                       "keep_book_contribution_compounded_return_pct": (
                           100 * (keep_contribution_nav - 1)),
                       "replicating_fund_book_compounded_return_pct": (
                           100 * (replicating_fund_book_nav - 1)),
                       "futures_treasury_book_compounded_return_pct": (
                           100 * (futures_treasury_book_nav - 1)),
                       "lease_book_attributed_factor_compounded_return_pct": (
                           100 * (lease_factor_nav - 1)),
                       "keep_book_attributed_factor_compounded_return_pct": (
                           100 * (keep_factor_nav - 1)),
                       "lease_fund_attributed_factor_compounded_return_pct": (
                           100 * (lease_fund_factor_nav - 1)),
                       "lease_futures_treasury_attributed_factor_compounded_return_pct": (
                           100 * (lease_futures_treasury_factor_nav - 1)),
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
                       "slv_price": spot[execution_day],
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
                       "resulting_long_futures_size_pct": 100 * sum(position["longs"].values()),
                       "resulting_short_futures_size_pct": 100 * sum(position["shorts"].values()),
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
        previous_valid_position = position
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
    parser.add_argument("--max-futures-treasury-fraction", type=float, default=0.50,
                        help="Maximum fraction of the full commodity leg implemented with Treasury collateral + long futures")
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
                                max_futures_treasury_fraction=args.max_futures_treasury_fraction,
                                negative_short_start_rate=args.negative_short_start_rate,
                                negative_short_full_rate=args.negative_short_full_rate,
                                max_short_fraction_of_long_leg=args.max_short_fraction_of_long_leg,
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
