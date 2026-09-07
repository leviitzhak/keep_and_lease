"""Bounded GUI research replay of immutable BTC trade prints.

The catalog is deployment-owned: request parameters never select arbitrary files
or cloud URLs. Millisecond clocks are decisions, not synthesized observations.
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import math
import time

import backtest_silver_lease_strategy as strategy
import silver_strategy_gui as gui
from trade_replay import TapeAccount, Trade

DATASET_ID = "btc-trades-2026-06-25"
MANIFEST_SHA = "9c05efc03118699303e7a55e14205bed29783683a85c165f99319dd3fabc055d"
DATASET_URI = "gs://keep-and-lease-market-data/btc/trades/v1/" + MANIFEST_SHA
START = "2026-06-25T00:00:00"
END = "2026-06-26T00:00:00"
MAX_DECISIONS = 200_000
EPOCH = datetime(1970, 1, 1)


def us_time(value):
    day = gui.backtest_bounds({"backtest_start": value})[0]
    delta = day - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def iso_time(us):
    return (EPOCH + timedelta(microseconds=us)).isoformat(timespec="microseconds")


def catalog():
    return {"id": DATASET_ID, "start": START, "end": END,
            "minimum_interval_seconds": .001, "maximum_decisions": MAX_DECISIONS,
            "manifest_sha256": MANIFEST_SHA}


def milliseconds(value, name, minimum=0):
    try:
        ms = Decimal(str(value)) * 1000
        if not ms.is_finite() or ms < minimum or ms != ms.to_integral_value():
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a multiple of 0.001 seconds, at least {minimum / 1000:g}") from None
    return int(ms) * 1000


def validate(payload):
    source = payload.get("btc_data_source", "minute")
    if source not in ("minute", "trade_tape"):
        raise ValueError("Unknown BTC data source")
    if source != "trade_tape":
        return None
    if gui.portfolio_allocations(payload) != {"btc": 1.0}:
        raise ValueError("Trade replay requires 100% Bitcoin and no other commodity or Treasury sleeve")
    merged = gui.product_payload(payload, "btc")
    # The clock and period are always global, even with a saved commodity profile.
    merged["execution_interval_seconds"] = payload.get("execution_interval_seconds", 0)
    for key in ("bond_mode", "treasury_allocation_mode", "treasury_asset", "reactivity"):
        if key in payload:
            merged[key] = payload[key]
    p = gui.parameters(merged)
    if p.futures_contract_type != "regular" or p.enable_short_book:
        raise ValueError("Trade replay supports regular/linear futures with the short book disabled")
    if p.execution_model not in ("auto", "observed"):
        raise ValueError("Trade replay requires the observed execution model")
    if p.bond_mode != "accrual" or p.treasury_allocation_mode != "shortest_rolling" or p.treasury_asset != "matched_maturity":
        raise ValueError("Trade replay requires matched-maturity Treasury accrual with shortest rolling allocation")
    if payload.get("reactivity", "same_day") != "same_day":
        raise ValueError("Trade replay requires same-day reactivity; use execution delay for latency")
    if p.slv_expense or p.half_spread_bps or p.slippage_bps:
        raise ValueError("Trade replay requires zero proxy expense, half spread and slippage; trading fees are supported")
    if p.max_volume_participation <= 0:
        raise ValueError("Trade participation must be greater than zero")
    interval = milliseconds(payload.get("execution_interval_seconds", 0), "Execution interval", 1)
    delay = milliseconds(merged.get("execution_delay_seconds", 0), "Execution delay")
    capital = gui.number(payload, "trade_initial_capital_usd", 1, .000001)
    lo, hi = gui.backtest_bounds(payload)
    start, end = us_time(lo.isoformat() if lo else START), us_time(hi.isoformat() if hi else END)
    if start < us_time(START) or end > us_time(END) or start >= end:
        raise ValueError(f"Trade data covers only [{START}, {END}) UTC; choose a window inside it")
    if math.ceil((end - start) / interval) > MAX_DECISIONS:
        raise ValueError(f"Trade replay permits at most {MAX_DECISIONS:,} decisions; shorten the period to at most {MAX_DECISIONS * interval / 1e6:g} seconds or increase the interval")
    return p, start, end, interval, delay, capital


def run(payload, data_root, audit_collection, progress=None, *, store=None):
    p, start, end, interval, delay, capital = validate(payload)
    notify = progress or (lambda *_: None)
    notify("loading_trade_data", "Verifying the immutable June 25 BTC trade dataset")
    dataset_uri = str(getattr(store, "root", "synthetic-fixture")) if store is not None else DATASET_URI
    if store is None:
        from trade_data_store import ParquetTradeStore
        store = ParquetTradeStore(DATASET_URI)
        if hashlib.sha256(store.manifest_bytes).hexdigest() != MANIFEST_SHA:
            raise ValueError("Trade dataset manifest checksum mismatch")
    manifest = store.source_manifest
    if start < us_time(manifest["start"]) or end > us_time(manifest["end"]):
        raise ValueError("Requested window is outside trade manifest coverage")
    rates = strategy.read_rates(data_root)
    writer = audit_collection.writer("btc_trade_events")
    valuations = audit_collection.writer("btc_trade_valuations")
    def emit(row):
        writer.emit({**row, "date": iso_time(row["us"])})
    account = TapeAccount(capital, p.max_volume_participation, delay, p.trading_fee_bps, emit)
    expiries = {s: us_time(info["expiry"]) for s, info in manifest["futures"].items()}
    for symbol, info in manifest["futures"].items():
        seed = info.get("seed")
        if seed:
            mark = Trade(seed["timestamp"] * 1000, symbol, seed["price"],
                         seed["amount"] / seed["price"], seed["direction"], seed["trade_id"],
                         not any(seed.get(k) for k in ("block_trade_id", "block_rfq_id", "combo_id")))
            if mark.us >= us_time(manifest["start"]):
                raise ValueError("Trade seed is not causal")
            account.marks[symbol] = mark
    # A later selected start uses actual prior futures prints, not future marks.
    if start > us_time(manifest["start"]):
        for event in store.trades(end_us=start, symbols=set(expiries)):
            account.marks[event.symbol] = event
            audit_collection.check_cancelled()
    tape = iter(store.trades(start_us=start, end_us=end))
    event = next(tape, None)
    count = 0
    while event and event.symbol != "SPOT":
        account.marks[event.symbol] = event
        count += 1
        event = next(tape, None)
    if event is None:
        raise ValueError("No spot trades in the selected window")
    initial_us, initial_price = event.us, event.price
    account.initialize_spot(event)
    count += 1
    event = next(tape, None)
    account.rate = strategy.usd_rate(rates, EPOCH + timedelta(microseconds=initial_us), strategy.TENORS[0][0])
    if account.rate is None:
        raise ValueError("No observable Treasury yield at the selected start")
    decisions = no_fresh = 0
    previous_nav, previous_tick, previous_allocation = capital, initial_us, None
    max_error = simple = max_drawdown = direct_drawdown = 0.0
    peak, direct_peak = capital, 1.0
    series = []
    sample_every = max(1, math.ceil((end - start) / interval / 2000))
    fields = ["date", "nav", "direct_nav", "cash_usd", "spot_value_usd", "futures_notional_usd", "fees_usd", "max_mark_age_seconds"]
    def point(tick):
        held_ages = [(tick - account.marks[s].us) / 1e6 for s, q in account.units.items() if q > 0]
        return [iso_time(tick), account.nav / capital, account.marks["SPOT"].price / initial_price,
                account.cash, account.units.get("SPOT", 0) * account.marks["SPOT"].price,
                account.collateral, account.fees, max(held_ages, default=0)]
    series.append(point(initial_us))
    last_progress = time.monotonic()
    tick = min((initial_us // interval + 1) * interval, end)
    while True:
        audit_collection.check_cancelled()
        while event and event.us <= tick and event.us < end:
            account.on_trade(event)
            count += 1
            if count % 8192 == 0:
                audit_collection.check_cancelled()
            event = next(tape, None)
        account.accrue(tick)
        day = EPOCH + timedelta(microseconds=tick)
        account.rate = strategy.usd_rate(rates, day, strategy.TENORS[0][0])
        if account.rate is None or account.nav <= 0:
            raise ValueError("Missing Treasury yield or insolvent trade replay account")
        for symbol, quantity in account.units.items():
            if symbol != "SPOT" and quantity > 1e-14 and expiries[symbol] <= tick:
                raise ValueError("Held futures reached expiry without a verified settlement price")
        spot = account.marks["SPOT"].price
        candidates = []
        for symbol, expiry in expiries.items():
            mark = account.marks.get(symbol)
            days = (expiry - tick) / 86400e6
            if mark is None or not mark.executable or days <= 0 or tick - mark.us > p.max_quote_age_seconds * 1e6:
                continue
            rate = strategy.usd_rate(rates, day, days)
            if rate is None:
                continue
            premium = mark.price / spot - 1
            candidates.append(dict(symbol=symbol, days=days, future=mark.price, spot=spot,
                                   premium=premium, rate=rate, lease=rate-premium*365/days, volume=mark.btc))
        previous = {"base_longs": {s: q * account.marks[s].price / account.nav
                                   for s, q in account.units.items() if s != "SPOT" and q > 0}, "shorts": {}}
        if previous_allocation is not None:
            previous["base_treasury"] = previous_allocation
        desired = strategy.positions_for_day(candidates, p, previous, elapsed_days=(tick-previous_tick)/86400e6)
        targets = None
        if tick < end:
            decisions += 1
            if desired and tick-account.marks["SPOT"].us <= p.max_quote_age_seconds*1e6:
                previous_allocation = desired["base_treasury"]
                targets = {s: w*account.nav/account.marks[s].price for s, w in desired["base_longs"].items()}
                targets["SPOT"] = desired["slv"]*account.nav/spot
                account.submit_targets(tick, targets)
            else:
                account.cancel(tick, "no_fresh_signal")
                no_fresh += 1
        else:
            account.cancel(tick, "end_of_window")
        error = account.reconstruction_error()
        max_error = max(max_error, abs(error))
        if max_error > capital * 1e-8:
            raise ValueError("Trade replay NAV does not reconcile")
        simple += account.nav/previous_nav-1
        peak = max(peak, account.nav)
        max_drawdown = min(max_drawdown, account.nav/peak-1)
        direct = spot/initial_price
        direct_peak = max(direct_peak, direct)
        direct_drawdown = min(direct_drawdown, direct/direct_peak-1)
        row = dict(kind="valuation", us=tick, date=iso_time(tick), nav_usd=account.nav,
                   cash_usd=account.cash, units=dict(account.units), targets=targets,
                   return_fraction=account.nav/previous_nav-1,
                   mark_ids={s: m.identifier for s, m in account.marks.items()},
                   mark_us={s: m.us for s, m in account.marks.items()}, reconstruction_error_usd=error,
                   starting_nav=previous_nav/capital, ending_nav=account.nav/capital,
                   direct_nav=direct, futures_notional_usd=account.collateral, fees_usd=account.fees)
        valuations.emit(row)
        if decisions % sample_every == 0 or tick == end:
            series.append(point(tick))
        previous_nav, previous_tick = account.nav, tick
        if time.monotonic() - last_progress > 10:
            notify("trade_replay", f"{iso_time(tick)} UTC · {decisions:,} decisions · {account.fill_count:,} fills")
            last_progress = time.monotonic()
        if tick == end:
            break
        tick = min(tick + interval, end)
    provenance = {"dataset_id": DATASET_ID, "manifest_sha256": hashlib.sha256(store.manifest_bytes).hexdigest(),
                  "dataset_uri": dataset_uri, "partitions": store.manifest["partitions"]}
    audit_collection.provenance["trade_data"] = provenance
    audit = audit_collection.finish()
    return dict(result_kind="btc_trade_replay", parameters=payload, fields=fields, series=series, audit=audit,
                backtest_period=dict(actual_start=iso_time(initial_us), actual_end=iso_time(end),
                                     requested_start=iso_time(start), requested_end=iso_time(end)),
                summary=dict(start=iso_time(initial_us), end=iso_time(end),
                             compounded_return=100*(account.nav/capital-1), ending_nav=account.nav/capital,
                             direct_holding_return=100*(direct-1), simple_return=100*simple,
                             max_drawdown=100*max_drawdown, direct_holding_max_drawdown=100*direct_drawdown,
                             observations=valuations.count, missing_intervals=0),
                trade_replay=dict(**provenance, interval_seconds=interval/1e6, delay_seconds=delay/1e6,
                                  capital_usd=capital, participation=p.max_volume_participation,
                                  decisions=decisions, market_events=count, fills=account.fill_count,
                                  orders=account.order_count, cancelled_remainders=account.cancellation_count,
                                  no_fresh_curve_decisions=no_fresh, warmup_us=initial_us-start,
                                  fees_usd=account.fees, treasury_interest_usd=account.interest,
                                  max_nav_reconstruction_error_usd=max_error,
                                  plot_sample_every=sample_every,
                                  end_mark_age_seconds={s: (end-m.us)/1e6 for s,m in account.marks.items()},
                                  assumptions=["Deribit inverse quotes as regular USD futures proxy; Binance USDT/USD assumed 1",
                                               "Same-side subsequent prints; strict later timestamp after delay; cancel/replace each decision",
                                               "Long only; 100% USD collateral; fractional lots; causal Treasury accrual",
                                               "Stale marks value holdings but cannot create fresh signals; no order-book or synchronized latency model",
                                               "First spot print initializes owned BTC; final NAV is marked, without liquidation"]))
