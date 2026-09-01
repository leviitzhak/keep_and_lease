#!/usr/bin/env python3
"""Local browser GUI for the parameterized silver lease strategy backtest."""

import json
import math
import os
from statistics import median
from dataclasses import replace
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zipfile import BadZipFile

from backtest_silver_lease_strategy import (
    Parameters, build_market, build_proxy_market, build_spot_market,
    multiplicative_log_contributions,
    TENORS, asof_rate, positions_for_day, read_csv_spot, read_zip_spot,
    run_backtest, score_diagnostic)
from market_data_store import data_directory, read_cached_asset, read_spot_csv

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "silver_strategy_gui.html"
MARKET = None
MARKETS = None
MARKET_LOAD_ERRORS = {}

PRODUCTS = {
    "silver": {"label": "Silver", "archive": None, "prefix": "SI",
               "spot_source": "LBMA silver fixing", "etf": "SLV",
               "replication": "physical-backed"},
    "gold": {"label": "Gold", "archive": "gc.zip", "prefix": "GC",
             "spot_source": "London gold fixing", "etf": "IAU / GLD",
             "replication": "physical-backed"},
    "oil": {"label": "WTI oil", "archive": "cl.zip", "prefix": "CL",
            "spot_source": "EIA Cushing WTI spot", "etf": "USO",
            "replication": "futures-based"},
    "wheat": {"label": "Wheat", "archive": "w.zip", "prefix": "W",
              "spot_source": "nearest live future (cash history pending)",
              "etf": "WEAT", "replication": "futures-based"},
    "corn": {"label": "Corn", "archive": "c.zip", "prefix": "C",
             "spot_source": "nearest live future (cash history pending)",
             "etf": "CORN", "replication": "futures-based"},
    "soybeans": {"label": "Soybeans", "archive": "s.zip", "prefix": "S",
                 "spot_source": "nearest live future (cash history pending)",
                 "etf": "SOYB", "replication": "futures-based"},
    "sp500": {"label": "S&P 500", "archive": "sp.zip", "prefix": "SP",
              "spot_source": "nearest live future (cash-index history pending)",
              "etf": "SPY / IVV", "replication": "equity-backed"},
}

DEFAULT_DEPLOYMENT_PRODUCTS = ("silver", "gold", "sp500")


def build_markets(root, enabled_products=None):
    import time
    global MARKET_LOAD_ERRORS
    markets, MARKET_LOAD_ERRORS = {}, {}
    if enabled_products is None:
        configured = os.getenv(
            "KEEP_AND_LEASE_PRODUCTS", ",".join(DEFAULT_DEPLOYMENT_PRODUCTS)
        )
        enabled_products = {
            item.strip() for item in configured.split(",") if item.strip()
        }
    else:
        enabled_products = set(enabled_products)
    builders = {
        "silver": lambda: build_market(root),
        "gold": lambda: build_spot_market(
            root, "gc.zip", "GC", _asset_spot(root, "gold", "gold_price.csv")),
        "oil": lambda: build_spot_market(
            root, "cl.zip", "CL",
            read_csv_spot(root, "DCOILWTICO.csv", "DCOILWTICO")),
    }
    for key, spec in PRODUCTS.items():
        if key not in enabled_products:
            MARKET_LOAD_ERRORS[key] = (
                "not enabled in this deployment; materialize its spot and "
                "contract histories before adding it to KEEP_AND_LEASE_PRODUCTS"
            )
            continue
        builder = builders.get(key, lambda spec=spec: build_proxy_market(
            root, spec["archive"], spec["prefix"]))
        started = time.monotonic()
        print(f"Building {key} market…", flush=True)
        try:
            markets[key] = builder()
            print(
                f"Built {key} market in {time.monotonic() - started:.1f}s",
                flush=True,
            )
        except (BadZipFile, FileNotFoundError, OSError, ValueError) as exc:
            MARKET_LOAD_ERRORS[key] = str(exc)
            print(
                f"Skipped {key} market after {time.monotonic() - started:.1f}s: {exc}",
                flush=True,
            )
    return markets


def _asset_spot(root, asset, legacy_member):
    cached = read_cached_asset(Path(root), asset)
    if cached is not None:
        return cached[0]
    if (data_directory(Path(root)) / asset).is_dir():
        return read_spot_csv(Path(root), asset)
    return read_zip_spot(root, legacy_member)


def number(payload, name, default, low=None, high=None):
    raw = payload.get(name, default)
    # An HTML number input sends an empty string when the user clears it.
    # Treat that the same as an omitted value so optional/defaulted controls do
    # not turn an otherwise valid backtest request into a float conversion error.
    value = float(default if raw is None or str(raw).strip() == "" else raw)
    if low is not None and value < low:
        raise ValueError(f"{name} must be at least {low}")
    if high is not None and value > high:
        raise ValueError(f"{name} must be at most {high}")
    return value


def product_payload(payload, product):
    """Overlay product-specific settings on the global configuration.

    API clients may send either ``commodity_parameters: {gold: {...}}`` or
    flat ``gold__parameter`` keys.  This keeps the engine independent of the
    current GUI's product list and lets every commodity own its thresholds,
    scoring curve, caps, and leg switches.
    """
    merged = dict(payload)
    nested = payload.get("commodity_parameters", {})
    if isinstance(nested, dict) and isinstance(nested.get(product), dict):
        merged.update(nested[product])
    prefix = f"{product}__"
    merged.update({key[len(prefix):]: value for key, value in payload.items()
                   if key.startswith(prefix)})
    return merged


def parameters(payload):
    # Rates and weights arrive as percentages from the GUI.
    pct = lambda name, default: number(payload, name, default) / 100
    flag = lambda name, default: str(payload.get(
        name, "true" if default else "false")).lower() == "true"
    def boundary(direction):
        anchor_names = (
            f"{direction}_line_maturity_1", f"{direction}_line_rate_1",
            f"{direction}_line_maturity_2", f"{direction}_line_rate_2")
        if not any(name in payload for name in anchor_names):
            return (
                pct(f"{direction}_maturity_line_intercept", 0),
                pct(f"{direction}_maturity_line_slope_per_year",
                    payload.get(f"{direction}_maturity_bonus_per_year", 0.4)),
            )
        maturity_1 = number(payload, f"{direction}_line_maturity_1", 30, 0)
        maturity_2 = number(payload, f"{direction}_line_maturity_2", 365, 0)
        if maturity_2 <= maturity_1:
            raise ValueError(
                f"{direction} boundary maturity 2 must exceed maturity 1")
        rate_1 = pct(f"{direction}_line_rate_1", 0.033)
        rate_2 = pct(f"{direction}_line_rate_2", 0.4)
        slope = (rate_2 - rate_1) * 365 / (maturity_2 - maturity_1)
        return rate_1 - slope * maturity_1 / 365, slope

    long_intercept, long_slope = boundary("long")
    short_intercept, short_slope = boundary("short")
    p = Parameters(
        min_days=int(number(payload, "min_days", 10, 1, 2000)),
        reactivity=str(payload.get("reactivity", "same_day")),
        long_allocation_half_life_days=number(
            payload, "long_allocation_half_life_days", 0, 0, 10000),
        short_allocation_half_life_days=number(
            payload, "short_allocation_half_life_days", 0, 0, 10000),
        roll_only_if_better=flag("roll_only_if_better", True),
        force_roll_at_min_days=flag("force_roll_at_min_days", True),
        enable_short_book=flag("enable_short_book", True),
        # Legacy JSON may contain enable_slv_leg=false.  The fund is now the
        # mandatory complement of Treasury-collateralized futures replication.
        enable_slv_leg=True,
        enable_cash_long_futures_leg=flag("enable_cash_long_futures_leg", True),
        slv_entry_mode=str(payload.get("slv_entry_mode", "gradual")),
        long_futures_entry_mode=str(payload.get(
            "long_futures_entry_mode", "gradual")),
        short_futures_entry_mode=str(payload.get(
            "short_futures_entry_mode", "gradual")),
        slv_expense=pct("slv_expense", 0.5),
        slv_start_rate=pct("slv_start_rate", 0.5),
        slv_full_rate=pct("slv_full_rate", -1.5),
        positive_entry_rate=pct("positive_entry_rate", 0),
        positive_full_rate=pct("positive_full_rate", 15),
        long_contract_selection=str(payload.get(
            "long_contract_selection", "shortest_maturity")),
        long_maturity_line_intercept=long_intercept,
        long_maturity_line_slope_per_year=long_slope,
        long_relative_strength=number(
            payload, "long_relative_strength", 1, 0, 100),
        long_score_rate_scale=pct("long_score_rate_scale", 1),
        long_score_adjustment_clip=number(
            payload, "long_score_adjustment_clip", 3, 0, 100),
        long_pure_maturity_strength=number(
            payload, "long_pure_maturity_strength", 0, 0, 100),
        long_maturity_bonus_per_year=pct("long_maturity_bonus_per_year", 0.4),
        long_extreme_qualification_rate=pct(
            "long_extreme_qualification_rate",
            float(payload.get("long_extreme_activation_rate", 10)) -
            float(payload.get("long_extreme_band", 2))),
        long_extreme_maturity_advantage_per_year=pct(
            "long_extreme_maturity_advantage_per_year", 0.5),
        long_extreme_maturity_bonus_per_year=pct(
            "long_extreme_maturity_bonus_per_year", 1),
        max_futures_treasury_fraction=pct("max_futures_treasury_fraction", 50),
        negative_short_start_rate=pct("negative_short_start_rate", -0.5),
        negative_short_full_rate=pct("negative_short_full_rate", -15),
        max_short_fraction_of_long_leg=pct("max_short_fraction_of_long_leg", 50),
        short_contract_selection=str(payload.get(
            "short_contract_selection", "weighted_lease_rate")),
        short_maturity_line_intercept=short_intercept,
        short_maturity_line_slope_per_year=short_slope,
        short_relative_strength=number(
            payload, "short_relative_strength", 1, 0, 100),
        short_score_rate_scale=pct("short_score_rate_scale", 1),
        short_score_adjustment_clip=number(
            payload, "short_score_adjustment_clip", 3, 0, 100),
        short_pure_maturity_strength=number(
            payload, "short_pure_maturity_strength", 0, 0, 100),
        pure_maturity_scale_days=number(
            payload, "pure_maturity_scale_days", 365, 1, 10000),
        pure_maturity_clip=number(
            payload, "pure_maturity_clip", 3, 0, 100),
        score_rate_scale=pct("long_score_rate_scale", 1),
        score_adjustment_clip=number(
            payload, "long_score_adjustment_clip", 3, 0, 100),
        short_maturity_bonus_per_year=pct("short_maturity_bonus_per_year", 0.4),
        short_extreme_qualification_rate=pct(
            "short_extreme_qualification_rate",
            float(payload.get("short_extreme_activation_rate", -10)) +
            float(payload.get("short_extreme_band", 2))),
        short_extreme_maturity_advantage_per_year=pct(
            "short_extreme_maturity_advantage_per_year", 0.5),
        short_extreme_maturity_bonus_per_year=pct(
            "short_extreme_maturity_bonus_per_year", 1),
        bond_mode=str(payload.get("bond_mode", "accrual")),
        treasury_asset=str(payload.get("treasury_asset", "matched_maturity")),
        treasury_allocation_mode=str(payload.get(
            "treasury_allocation_mode", "shortest_rolling")),
    )
    if p.bond_mode not in {"accrual", "zero_coupon_mtm"}:
        raise ValueError("Invalid bond mode")
    if p.reactivity not in {"same_day", "next_day"}:
        raise ValueError("Invalid strategy reactivity")
    if p.treasury_asset not in {"matched_maturity", "sgov_proxy"}:
        raise ValueError("Invalid Treasury instrument")
    if p.treasury_allocation_mode not in {
            "shortest_rolling", "rate_weighted_maturities"}:
        raise ValueError("Invalid Treasury allocation mode")
    if p.long_contract_selection not in {
            "shortest_maturity", "highest_lease_rate", "weighted_lease_rate"}:
        raise ValueError("Invalid long contract selection")
    if p.short_contract_selection not in {"weighted_lease_rate", "lowest_lease_rate"}:
        raise ValueError("Invalid short contract selection")
    for name in ("slv_entry_mode", "long_futures_entry_mode",
                 "short_futures_entry_mode"):
        if getattr(p, name) not in {"gradual", "fixed"}:
            raise ValueError(f"Invalid {name}")
    if p.slv_start_rate <= p.slv_full_rate:
        raise ValueError("SLV transition start must exceed its full-allocation rate")
    if p.negative_short_start_rate <= p.negative_short_full_rate:
        raise ValueError("Short entry threshold must exceed its full-allocation rate")
    if p.positive_entry_rate >= p.positive_full_rate:
        raise ValueError("Long entry rate must be below its full-allocation rate")
    if p.score_rate_scale <= 0:
        raise ValueError("Score rate scale must be positive")
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

def max_drawdown(nav_values):
    peak = nav_values[0]
    worst = 0.0
    for value in nav_values:
        peak = max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1)
    return -100 * worst


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
        chart_day = date.fromisoformat(row["date"])
        candidates = by_day.get(chart_day, [])
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
            "shortest_maturity_days": min(x["days"] for x in eligible),
            "longest_maturity_days": max(x["days"] for x in eligible),
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


def statistics_points(by_day, contracts, p, limit=12000):
    """Historical eligible contract observations for maturity scatter plots."""
    points = []
    next_quotes = {}
    for symbol, prices in contracts.items():
        quoted_days = sorted(prices)
        next_quotes[symbol] = {
            day: quoted_days[index + 1]
            for index, day in enumerate(quoted_days[:-1])
        }
    for day, candidates in sorted(by_day.items()):
        for contract in candidates:
            if contract["days"] < p.min_days:
                continue
            symbol = contract["symbol"]
            next_day = next_quotes.get(symbol, {}).get(day)
            current_price = contracts.get(symbol, {}).get(day)
            next_price = contracts.get(symbol, {}).get(next_day) if next_day else None
            next_return = (next_price / current_price - 1
                           if current_price and next_price is not None else None)
            points.append({
                "date": day.isoformat(), "symbol": symbol,
                "days": contract["days"],
                "annualized_lease_pct": 100 * contract["lease"],
                "forward_premium_pct": 100 * contract["premium"],
                "actual_lease_pct": 100 * contract["lease"] * contract["days"] / 365,
                "next_date": next_day.isoformat() if next_day else None,
                "next_elapsed_days": (next_day - day).days if next_day else None,
                "next_return_pct": 100 * next_return if next_return is not None else None,
            })
    if len(points) <= limit:
        return points
    stride = len(points) / limit
    return [points[int(i * stride)] for i in range(limit)]


def treasury_statistics_points(rates, limit=12000):
    """Historical Treasury yield observations for rate/maturity scatters."""
    labels = {91: "3m", 182: "6m", 365: "1y", 730: "2y",
              1095: "3y", 1825: "5y"}
    points = []
    for tenor, _ in TENORS:
        for day, rate in rates.get(tenor, []):
            points.append({
                "date": day.isoformat(),
                "symbol": labels.get(tenor, f"{tenor}d"),
                "days": tenor,
                "interest_rate_pct": 100 * rate,
            })
    points.sort(key=lambda item: (item["date"], item["days"]))
    if len(points) <= limit:
        return points
    stride = len(points) / limit
    return [points[int(i * stride)] for i in range(limit)]


def treasury_rate_change_points(rates, limit=12000):
    """Observed yield changes and zero-coupon duration return by tenor."""
    points = []
    labels = {tenor: symbol for tenor, symbol in TENORS}
    for tenor, observations in rates.items():
        for (start_day, start_rate), (end_day, end_rate) in zip(
                observations, observations[1:]):
            change = end_rate - start_rate
            points.append({
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "date": end_day.isoformat(),
                "symbol": labels.get(tenor, f"{tenor}d"),
                "days": tenor,
                "yield_change_pct": 100 * change,
                "rate_change_return_pct": -100 * tenor / 365 * change,
            })
    if len(points) <= limit:
        return points
    stride = len(points) / limit
    return [points[int(i * stride)] for i in range(limit)]


def inspection_for_day(payload, requested_day):
    """Return contract curves and the cash yield curve for one inspected day."""
    global MARKETS
    if MARKETS is None:
        MARKETS = {"silver": MARKET}
    selected = date.fromisoformat(requested_day)
    weights = portfolio_allocations(payload)
    result = {"requested_date": requested_day, "commodities": {}}
    resolved_days = []
    for key in weights:
        if key == "treasury":
            continue
        p = parameters(product_payload(payload, key))
        market = MARKETS[key]
        available_days = sorted(market[3])
        if not available_days:
            continue
        actual = min(available_days, key=lambda day: abs(day - selected))
        resolved_days.append(actual)
        candidates = [item for item in market[3].get(actual, [])
                      if item["days"] >= p.min_days]
        position = positions_for_day(candidates, p) or {}
        long_weights = position.get("base_longs", {})
        short_weights = position.get("shorts", {})
        contracts = []
        for item in sorted(candidates, key=lambda candidate: candidate["days"]):
            row = contract_summary(item)
            row["long_scoring"] = score_diagnostic(
                item, p, "long", p.positive_entry_rate,
                long_weights.get(item["symbol"], 0.0))
            row["short_scoring"] = score_diagnostic(
                item, p, "short", p.negative_short_start_rate,
                short_weights.get(item["symbol"], 0.0))
            contracts.append(row)
        result["commodities"][key] = {
            "label": PRODUCTS[key]["label"],
            "date": actual.isoformat(),
            "contracts": contracts,
        }
    rates = next(iter(MARKETS.values()))[2]
    treasury_curve = []
    labels = {91: "3m", 182: "6m", 365: "1y", 730: "2y",
              1095: "3y", 1825: "5y"}
    for tenor, _ in TENORS:
        rate = asof_rate(rates, tenor, selected)
        if rate is not None:
            treasury_curve.append({
                "symbol": labels.get(tenor, f"{tenor}d"),
                "maturity_days": tenor,
                "interest_rate_pct": 100 * rate,
            })
    result["treasury"] = {"date": requested_day, "curve": treasury_curve}
    return result


def annual_statistics(rows):
    """Calendar-year lease means and compounded strategy/SLV returns."""
    years = {}
    for row in rows:
        year = str(row["date"])[:4]
        bucket = years.setdefault(year, {
            "long": [], "short": [], "strategy_nav": 1.0,
            "slv_nav": 1.0, "long_futures_nav": 1.0,
            "short_futures_nav": 1.0, "observations": 0,
            "long_buys": [], "long_sales": [],
            "short_buys": [], "short_sales": [],
        })
        if row.get("long_weighted_lease_rate_pct") is not None:
            bucket["long"].append(row["long_weighted_lease_rate_pct"])
        if row.get("short_weighted_lease_rate_pct") is not None:
            bucket["short"].append(row["short_weighted_lease_rate_pct"])
        bucket["strategy_nav"] *= 1 + row["interval_return_pct"] / 100
        bucket["slv_nav"] *= 1 + row["slv_daily_return_pct"] / 100
        if row.get("long_futures_daily_return_pct") is not None:
            bucket["long_futures_nav"] *= (
                1 + row["long_futures_daily_return_pct"] / 100)
        if row.get("short_futures_daily_return_pct") is not None:
            bucket["short_futures_nav"] *= (
                1 + row["short_futures_daily_return_pct"] / 100)
        bucket["observations"] += 1
        for trade in row.get("long_futures_trade_details", []):
            target = "long_buys" if trade["action"] == "entry" else "long_sales"
            bucket[target].append((trade["price"], trade["size_pct"]))
        for trade in row.get("short_futures_trade_details", []):
            target = "short_sales" if trade["action"] == "entry" else "short_buys"
            bucket[target].append((trade["price"], trade["size_pct"]))
    def weighted_price(trades):
        volume = sum(size for _, size in trades)
        return (sum(price * size for price, size in trades) / volume
                if volume else None)
    return [{
        "year": year,
        "mean_long_lease_rate_pct": (
            sum(bucket["long"]) / len(bucket["long"]) if bucket["long"] else None),
        "mean_short_lease_rate_pct": (
            sum(bucket["short"]) / len(bucket["short"]) if bucket["short"] else None),
        "silver_return_pct": 100 * (bucket["slv_nav"] - 1),
        "strategy_return_pct": 100 * (bucket["strategy_nav"] - 1),
        # These are the economically meaningful rolling-sleeve returns: daily
        # returns of the held contracts are chain-linked through every roll.
        "long_rolling_return_pct": 100 * (bucket["long_futures_nav"] - 1),
        "short_rolling_return_pct": 100 * (bucket["short_futures_nav"] - 1),
        "long_buy_vwap": weighted_price(bucket["long_buys"]),
        "long_sale_vwap": weighted_price(bucket["long_sales"]),
        "short_buy_vwap": weighted_price(bucket["short_buys"]),
        "short_sale_vwap": weighted_price(bucket["short_sales"]),
        # A pooled annual VWAP ratio is retained only as a trading-price
        # diagnostic. It is not a portfolio return when contracts/volumes differ.
        "long_vwap_ratio_pct": (
            100 * (weighted_price(bucket["long_sales"]) /
                   weighted_price(bucket["long_buys"]) - 1)
            if weighted_price(bucket["long_buys"]) is not None and
            weighted_price(bucket["long_sales"]) is not None else None),
        "short_vwap_ratio_pct": (
            100 * (weighted_price(bucket["short_sales"]) /
                   weighted_price(bucket["short_buys"]) - 1)
            if weighted_price(bucket["short_buys"]) is not None and
            weighted_price(bucket["short_sales"]) is not None else None),
        "observations": bucket["observations"],
    } for year, bucket in sorted(years.items())]


def extreme_return_statistics(rows, threshold_pct=1.0, limit=10):
    """Rank both tails and attach exact daily attribution and path diagnostics."""
    component_fields = {
        "silver_price_pct": "silver_price_return_contribution_pct",
        "lease_carry_pct": "lease_carry_contribution_pct",
        "lease_rate_change_pct": "lease_rate_change_contribution_pct",
        "rolling_pct": "rolling_contribution_pct",
        "treasury_pct": "treasury_return_contribution_pct",
        "slv_expense_pct": "slv_expense_contribution_pct",
        "other_pct": "other_return_contribution_pct",
    }
    ending_nav = rows[-1].get("nav", 1.0) if rows else 1.0
    enriched = []
    for index, row in enumerate(rows):
        previous_nav = rows[index - 1].get("nav", 1.0) if index else 1.0
        event_nav = row.get("nav", previous_nav * (1 + row["interval_return_pct"] / 100))
        next_return = rows[index + 1]["interval_return_pct"] if index + 1 < len(rows) else None
        record = {
            "date": row["date"], "return_pct": row["interval_return_pct"],
            "nav_before": previous_nav, "nav_after": event_nav,
            "next_day_return_pct": next_return,
            "return_after_event_pct": (100 * (ending_nav / event_nav - 1)
                                       if event_nav else None),
            "long_symbols": row.get("long_symbols", ""),
            "short_symbols": row.get("short_symbols", ""),
        }
        record.update({key: row.get(field, 0.0)
                       for key, field in component_fields.items()})
        record["reconciled_pct"] = sum(record[key] for key in component_fields)
        enriched.append(record)
    qualifying = [row for row in enriched if row["return_pct"] > threshold_pct]
    return {
        "threshold_pct": threshold_pct,
        "count": len(qualifying),
        "highest": sorted(
            qualifying, key=lambda row: row["return_pct"], reverse=True)[:limit],
        "lowest": sorted(enriched, key=lambda row: row["return_pct"])[:limit],
    }


def outlier_statistics(rows, limit=50):
    """Robustly flag unusual returns without silently deleting or correcting them."""
    values = [row["interval_return_pct"] for row in rows]
    center = median(values)
    mad = median([abs(value - center) for value in values]) or 1e-12
    scale = 1.4826 * mad
    flagged = []
    for index, row in enumerate(rows):
        value = row["interval_return_pct"]
        robust_z = (value - center) / scale
        next_value = rows[index + 1]["interval_return_pct"] if index + 1 < len(rows) else None
        reversal = (next_value is not None and value * next_value < 0 and
                    abs(value) > 5 * scale and abs(next_value) > 5 * scale)
        if abs(robust_z) >= 8 or abs(value) >= 25:
            flagged.append({
                "date": row["date"], "return_pct": value,
                "robust_z": robust_z, "next_return_pct": next_value,
                "immediate_reversal": reversal,
                "silver_price_pct": row.get("silver_price_return_contribution_pct", 0),
                "lease_rate_change_pct": row.get("lease_rate_change_contribution_pct", 0),
                "rolling_pct": row.get("rolling_contribution_pct", 0),
            })
    flagged.sort(key=lambda item: abs(item["robust_z"]), reverse=True)
    return {"median_pct": center, "mad_pct": mad, "count": len(flagged),
            "flagged": flagged[:limit]}
def sleeve_result(payload, market=None, product="silver"):
    p = parameters(product_payload(payload, product))
    market = market or MARKET
    rows, missing = run_backtest(*market, p)
    if not rows:
        raise ValueError("No observations remain with these parameters")
    stride = max(1, (len(rows) + 4999) // 5000)
    sampled = rows[::stride]
    if sampled[-1] is not rows[-1]:
        sampled.append(rows[-1])
    fields = ["date", "exit_date", "interval_return_pct", "simple_cumulative_return_pct",
              "compounded_return_pct", "slv_weight_pct", "treasury_weight_pct",
              "long_futures_notional_pct", "short_futures_notional_pct",
              "long_weighted_maturity_days", "short_weighted_maturity_days",
              "short_shortest_maturity_days", "short_longest_maturity_days",
              "long_weighted_lease_rate_pct", "short_weighted_lease_rate_pct",
              "long_book_interval_return_pct", "short_book_interval_return_pct",
              "matched_long_extension_interval_return_pct",
              "long_book_cumulative_return_pct", "short_book_cumulative_return_pct",
              "matched_long_extension_cumulative_return_pct",
              "lease_book_interval_return_pct", "keep_book_interval_return_pct",
              "keep_book_contribution_interval_return_pct",
              "replicating_fund_book_interval_return_pct",
              "futures_treasury_book_interval_return_pct",
              "lease_book_factor_interval_return_pct",
              "keep_book_factor_interval_return_pct",
              "lease_fund_factor_interval_return_pct",
              "lease_futures_treasury_factor_interval_return_pct",
              "lease_book_compounded_return_pct",
              "keep_book_compounded_return_pct",
              "keep_book_contribution_compounded_return_pct",
              "replicating_fund_book_compounded_return_pct",
              "futures_treasury_book_compounded_return_pct",
              "lease_book_attributed_factor_compounded_return_pct",
              "keep_book_attributed_factor_compounded_return_pct",
              "lease_fund_attributed_factor_compounded_return_pct",
              "lease_futures_treasury_attributed_factor_compounded_return_pct",
              "replicating_leg_value", "futures_treasury_value",
              "lease_book_value", "keep_book_value",
              "replicating_leg_underlying_value",
              "futures_treasury_underlying_value",
              "lease_book_underlying_value", "keep_book_underlying_value",
              "initial_replicating_leg_value",
              "initial_futures_treasury_value",
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
              "available_futures_max_maturity_days",
              "long_forward_maturity_days", "short_forward_maturity_days",
              "allocation_long_lease_signal_pct", "long_book_extension_pct",
              "entered_long_futures_price", "entered_short_futures_price",
              "exited_long_futures_price", "exited_short_futures_price",
              "long_matched_usd_rate_pct", "short_matched_usd_rate_pct",
              "entered_long_futures_size_pct", "entered_short_futures_size_pct",
              "exited_long_futures_size_pct", "exited_short_futures_size_pct",
              "resulting_long_futures_size_pct", "resulting_short_futures_size_pct"]
    fields += ["silver_price_return_contribution_pct",
               "slv_expense_contribution_pct",
               "treasury_return_contribution_pct",
               "lease_carry_contribution_pct",
               "lease_rate_change_contribution_pct",
               "rolling_contribution_pct", "other_return_contribution_pct"]
    change_stats = position_change_stats(rows)
    slv_nav = 1.0
    slv_nav_values = [slv_nav]
    for row in rows:
        slv_nav *= 1 + row["slv_daily_return_pct"] / 100
        slv_nav_values.append(slv_nav)
    comparisons = []
    for selection in ("weighted_lease_rate", "highest_lease_rate"):
        comparison_parameters = replace(p, long_contract_selection=selection)
        comparison_rows, _ = (rows, missing) if selection == p.long_contract_selection else run_backtest(
            *market, comparison_parameters)
        if not comparison_rows:
            continue
        change = position_change_stats(comparison_rows)
        def compound(field):
            nav = 1.0
            for row in comparison_rows:
                value = row.get(field)
                if value is not None:
                    nav *= 1 + value / 100
            return 100 * (nav - 1)
        long_daily = [r["long_futures_daily_return_pct"] for r in comparison_rows
                      if r.get("long_futures_daily_return_pct") is not None]
        mean_daily = sum(long_daily) / len(long_daily) if long_daily else 0.0
        annualized_volatility = ((sum((x - mean_daily) ** 2 for x in long_daily) /
                                  max(1, len(long_daily) - 1)) ** 0.5 * 252 ** 0.5
                                 if long_daily else None)
        contract_turnover = sum(
            sum(t["size_pct"] for t in r.get("long_futures_trade_details", []))
            for r in comparison_rows) / len(comparison_rows)
        comparisons.append({
            "selection": selection,
            "strategy_return_pct": comparison_rows[-1]["compounded_return_pct"],
            "long_rolling_return_pct": compound("long_futures_daily_return_pct"),
            "treasury_return_pct": compound("treasury_daily_return_pct"),
            "mean_long_notional_pct": sum(r["long_futures_notional_pct"] for r in comparison_rows) / len(comparison_rows),
            "mean_long_lease_pct": sum(r["allocation_long_lease_signal_pct"] for r in comparison_rows) / len(comparison_rows),
            "mean_long_maturity_days": sum((r["long_weighted_maturity_days"] or 0) for r in comparison_rows) / len(comparison_rows),
            "avg_daily_contract_turnover_pct": contract_turnover,
            "long_annualized_volatility_pct": annualized_volatility,
            "worst_long_day_pct": min(long_daily) if long_daily else None,
        })
    return {
        "_full_rows": rows,
        "series": [[row[k] for k in fields] for row in sampled],
        "fields": fields,
        "product": product,
        "product_label": PRODUCTS.get(product, {}).get("label", product.title()),
        "direct_proxy": PRODUCTS.get(product, {}).get("spot_source"),
        "replicating_etf": PRODUCTS.get(product, {}).get("etf"),
        "replication_type": PRODUCTS.get(product, {}).get("replication"),
        "futures_prices": futures_price_series(sampled, market[1]),
        "futures_diagnostics": futures_diagnostics(sampled, market[3], p),
        "statistics_points": statistics_points(market[3], market[1], p),
        "treasury_statistics_points": treasury_statistics_points(market[2]),
        "treasury_rate_change_points": treasury_rate_change_points(market[2]),
        "rate_change_attribution_points": [
            {**point, "commodity": product,
             "date": point["end_date"],
             "symbol": point["leg"],
             "days": point["weighted_maturity"],
             "rate_change_return_pct": 100 * point["position_relative_return"]}
            for row in rows
            for point in row.get("rate_change_attribution_points", [])
            if not point.get("excluded")
        ],
        "annual_statistics": annual_statistics(rows),
        "extreme_return_statistics": extreme_return_statistics(rows),
        "outlier_statistics": outlier_statistics(rows),
        "selection_comparison": comparisons,
        "usd_rate_diagnostics": [{
            "long": row["long_matched_usd_rate_components"],
            "short": row["short_matched_usd_rate_components"],
        } for row in sampled],
        "futures_trade_diagnostics": [{
            "long": row["long_futures_trade_details"],
            "short": row["short_futures_trade_details"],
            "resulting_long_size_pct": row["resulting_long_futures_size_pct"],
            "resulting_short_size_pct": row["resulting_short_futures_size_pct"],
        } for row in sampled],
        "summary": {
            "start": rows[0]["date"], "end": rows[-1]["date"],
            "observations": len(rows), "missing_intervals": len(missing),
            "missing_return_events": missing,
            "simple_return": rows[-1]["simple_cumulative_return_pct"],
            "compounded_return": rows[-1]["compounded_return_pct"],
            "ending_nav": rows[-1]["nav"],
            "max_drawdown": max_drawdown([1.0] + [row["nav"] for row in rows]),
            "direct_holding_return": 100 * (slv_nav - 1),
            "direct_holding_max_drawdown": max_drawdown(slv_nav_values),
            # Compatibility aliases for older saved browser results.
            "direct_silver_return": 100 * (slv_nav - 1),
            "direct_silver_max_drawdown": max_drawdown(slv_nav_values),
            **change_stats,
        },
    }


def portfolio_allocations(payload):
    weights = {}
    for key in PRODUCTS:
        value = number(payload, f"weight_{key}", 100 if key == "silver" else 0,
                       0, 10000)
        if value > 0:
            weights[key] = value
    treasury = number(payload, "weight_treasury", 0, 0, 10000)
    if treasury > 0:
        weights["treasury"] = treasury
    if not weights:
        raise ValueError(
            "At least one commodity or Treasury proportion must be positive")
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def aggregate_portfolio(sleeves, target_weights, rebalance):
    """Combine independently calculated sleeves with explicit rebalancing."""
    component_fields = {
        "underlying_price": "silver_price_return_contribution_pct",
        "lease_carry": "lease_carry_contribution_pct",
        "lease_rate_change": "lease_rate_change_contribution_pct",
        "rolling": "rolling_contribution_pct",
        "treasury": "treasury_return_contribution_pct",
        "fund_expense": "slv_expense_contribution_pct",
        "other": "other_return_contribution_pct",
    }
    maps = {
        key: {row["date"]: row for row in sleeve["_full_rows"]}
        for key, sleeve in sleeves.items()
    }
    dates = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    if not dates:
        raise ValueError("The selected commodities have no overlapping history")
    nav = 1.0
    simple = 0.0
    direct_nav = 1.0
    direct_unrebalanced_nav = 1.0
    sleeve_values = dict(target_weights)
    direct_values = dict(target_weights)
    direct_unrebalanced_values = dict(target_weights)
    asset_factor_nav = {key: 1.0 for key in target_weights}
    output = []
    attribution = []
    previous_period = None
    schedules = {
        "daily": lambda d: d,
        "monthly": lambda d: d[:7],
        "quarterly": lambda d: f"{d[:4]}-Q{(int(d[5:7])-1)//3+1}",
        "annual": lambda d: d[:4],
        "none": lambda d: "never",
    }
    if rebalance not in schedules:
        raise ValueError("Invalid rebalancing choice")
    for day in dates:
        reference_row = maps[next(iter(sleeves))][day]
        exit_day = reference_row.get("exit_date", day)
        interval_exits = {
            maps[key][day].get("exit_date", day)
            for key in maps
        }
        if len(interval_exits) != 1:
            raise ValueError(
                f"Commodity holding intervals ending after {day} are not aligned")
        period = schedules[rebalance](day)
        if rebalance != "none" and previous_period is not None and period != previous_period:
            sleeve_values = {key: nav * weight for key, weight in target_weights.items()}
            direct_values = {
                key: direct_nav * weight for key, weight in target_weights.items()}
        previous_period = period
        start_nav = sum(sleeve_values.values())
        start_direct = sum(direct_values.values())
        start_direct_unrebalanced = sum(direct_unrebalanced_values.values())
        contributions = {}
        direct_contributions = {}
        direct_unrebalanced_contributions = {}
        day_attribution = {"date": exit_day, "start_date": day, "assets": {}}
        for key in target_weights:
            effective_weight = sleeve_values[key] / start_nav
            if key == "treasury":
                reference = maps[next(iter(sleeves))][day]
                daily = reference["treasury_daily_return_pct"] / 100
                direct_daily = daily
                component_values = {"treasury": 100 * effective_weight * daily}
            else:
                daily = maps[key][day]["interval_return_pct"] / 100
                direct_daily = maps[key][day]["slv_daily_return_pct"] / 100
                component_values = {
                    name: effective_weight * maps[key][day].get(field, 0.0)
                    for name, field in component_fields.items()
                }
                component_values["other"] += (
                    100 * effective_weight * daily
                    - sum(component_values.values()))
            contributions[key] = effective_weight * daily
            direct_contributions[key] = (
                direct_values[key] / start_direct * direct_daily)
            direct_unrebalanced_contributions[key] = (
                direct_unrebalanced_values[key] /
                start_direct_unrebalanced * direct_daily)
            day_attribution["assets"][key] = {
                "effective_weight_pct": 100 * effective_weight,
                "contribution_pct": 100 * contributions[key],
                "components": component_values,
                "reconciliation_difference_pct": (
                    100 * contributions[key] - sum(component_values.values())),
            }
            sleeve_values[key] *= 1 + daily
            direct_values[key] *= 1 + direct_daily
            direct_unrebalanced_values[key] *= 1 + direct_daily
        daily_return = sum(contributions.values())
        direct_return = sum(direct_contributions.values())
        direct_unrebalanced_return = sum(
            direct_unrebalanced_contributions.values())
        asset_logs = multiplicative_log_contributions(
            daily_return, contributions)
        for key, log_contribution in asset_logs.items():
            asset_factor_nav[key] *= math.exp(log_contribution)
        nav *= 1 + daily_return
        direct_nav *= 1 + direct_return
        direct_unrebalanced_nav *= 1 + direct_unrebalanced_return
        simple += daily_return
        row = [
            exit_day, day, 100 * daily_return, 100 * simple, 100 * (nav - 1),
            100 * direct_return, 100 * (direct_nav - 1), nav,
        ]
        row.extend(100 * contributions[key] for key in target_weights)
        row.extend([
            100 * direct_unrebalanced_return,
            100 * (direct_unrebalanced_nav - 1),
        ])
        row.extend(
            100 * (asset_factor_nav[key] - 1) for key in target_weights)
        output.append(row)
        day_attribution["portfolio_return_pct"] = 100 * daily_return
        day_attribution["reconciled_pct"] = sum(
            asset["contribution_pct"]
            for asset in day_attribution["assets"].values())
        attribution.append(day_attribution)
    fields = [
        "date", "start_date", "interval_return_pct", "simple_cumulative_return_pct",
        "compounded_return_pct", "direct_daily_return_pct",
        "direct_compounded_return_pct", "nav",
    ] + [f"{key}_contribution_pct" for key in target_weights] + [
        "direct_unrebalanced_daily_return_pct",
        "direct_unrebalanced_compounded_return_pct",
    ] + [f"{key}_attributed_factor_compounded_return_pct"
         for key in target_weights]
    return fields, output, attribution


def result(payload):
    global MARKETS
    if MARKETS is None:
        MARKETS = {"silver": MARKET}
    weights = portfolio_allocations(payload)
    commodity_weights = {
        key: value for key, value in weights.items() if key != "treasury"
    }
    unavailable = [key for key in commodity_weights if key not in MARKETS]
    if unavailable:
        details = "; ".join(
            f"{key}: {MARKET_LOAD_ERRORS.get(key, 'market data unavailable')}"
            for key in unavailable)
        raise ValueError(
            "Selected commodity data could not be loaded (" + details +
            "). Set those proportions to zero or repair the market archive.")
    rebalance = str(payload.get("portfolio_rebalancing", "daily"))
    sleeves = {
        key: sleeve_result(payload, MARKETS[key], key)
        for key in commodity_weights
    }
    cash_reference = None
    aggregation_sleeves = sleeves
    if not sleeves:
        # A Treasury-only portfolio still needs a calendar and rate-return
        # series.  Reuse any loaded market's calendar without adding its
        # commodity return or exposing it as an invested sleeve.
        reference_key, reference_market = next(iter(MARKETS.items()))
        cash_reference = sleeve_result(payload, reference_market, reference_key)
        aggregation_sleeves = {"_cash_reference": cash_reference}
    fields, series, attribution = aggregate_portfolio(
        aggregation_sleeves, weights, rebalance)
    if (len(sleeves) == 1 and "silver" in sleeves and rebalance == "daily"
            and "treasury" not in weights):
        # Keep the legacy silver-only response shape without making the
        # response self-referential.  Mutating sleeves["silver"] here and then
        # attaching `sleeves` as commodity_sleeves creates the cycle
        # answer -> commodity_sleeves -> silver -> answer, which json.dumps
        # rejects with "Circular reference detected".
        answer = dict(sleeves["silver"])
        answer["portfolio"] = {
            "weights": {"silver": 1.0}, "rebalancing": rebalance,
            "available_products": PRODUCTS,
        }
        answer["daily_attribution"] = attribution
        answer["portfolio_fields"] = fields
        answer["portfolio_series"] = series
        answer["commodity_sleeves"] = sleeves
        answer["treasury_statistics_points"] = next(
            iter(sleeves.values()))["treasury_statistics_points"]
        answer.pop("_full_rows", None)
        for sleeve in sleeves.values():
            sleeve.pop("_full_rows", None)
        return answer
    for sleeve in sleeves.values():
        sleeve.pop("_full_rows", None)
    treasury_points = (next(iter(sleeves.values()))["treasury_statistics_points"]
                       if sleeves else cash_reference["treasury_statistics_points"])
    treasury_change_points = (
        next(iter(sleeves.values()))["treasury_rate_change_points"]
        if sleeves else cash_reference["treasury_rate_change_points"])
    nav_values = [1.0] + [row[fields.index("nav")] for row in series]
    direct_nav_values = [1.0] + [
        1 + row[fields.index("direct_compounded_return_pct")] / 100
        for row in series]
    direct_unrebalanced_nav_values = [1.0] + [
        1 + row[fields.index(
            "direct_unrebalanced_compounded_return_pct")] / 100
        for row in series]
    return {
        "fields": fields,
        "series": series,
        "daily_attribution": attribution,
        "commodity_sleeves": sleeves,
        "treasury_statistics_points": treasury_points,
        "treasury_rate_change_points": treasury_change_points,
        "portfolio": {
            "weights": weights, "rebalancing": rebalance,
            "available_products": PRODUCTS,
        },
        "summary": {
            "start": series[0][0], "end": series[-1][0],
            "observations": len(series),
            "simple_return": series[-1][2],
            "compounded_return": series[-1][3],
            "ending_nav": series[-1][6],
            "max_drawdown": max_drawdown(nav_values),
            "direct_holding_return": series[-1][5],
            "direct_holding_max_drawdown": max_drawdown(direct_nav_values),
            "direct_unrebalanced_return": series[-1][fields.index(
                "direct_unrebalanced_compounded_return_pct")],
            "direct_unrebalanced_max_drawdown": max_drawdown(
                direct_unrebalanced_nav_values),
            "direct_silver_return": series[-1][5],
            "direct_silver_max_drawdown": max_drawdown(direct_nav_values),
            "missing_intervals": sum(
                x["summary"]["missing_intervals"] for x in sleeves.values()),
            "missing_return_events": [],
            "avg_daily_futures_notional_change_pct": sum(
                commodity_weights[key] * sleeves[key]["summary"][
                    "avg_daily_futures_notional_change_pct"] for key in sleeves),
            "avg_daily_notional_change_pct": sum(
                commodity_weights[key] * sleeves[key]["summary"][
                    "avg_daily_notional_change_pct"] for key in sleeves),
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
