"""Bounded GUI research replay of immutable BTC trade prints.

The catalog is deployment-owned: request parameters never select arbitrary files
or cloud URLs. Millisecond clocks are decisions, not synthesized observations.
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import math
import json
import os
import re
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
    configured = os.getenv("KEEP_AND_LEASE_TRADE_CATALOG")
    if configured:
        value = json.loads(configured)
        if set(value) != {"id", "start", "end", "manifest_sha256", "uri", "maximum_decisions"}:
            raise ValueError("Invalid deployment trade catalog")
        if not value["uri"].startswith("gs://keep-and-lease-market-data/btc/trades/"):
            raise ValueError("Trade catalog must use the configured market bucket")
        if not re.fullmatch("[0-9a-f]{64}", value["manifest_sha256"]):
            raise ValueError("Trade catalog requires a manifest SHA-256")
        if not isinstance(value["maximum_decisions"], int) or not 1 <= value["maximum_decisions"] <= 16_000_000:
            raise ValueError("Trade catalog exceeds the implementation decision ceiling")
        start, end = us_time(value["start"]), us_time(value["end"])
        if not 0 < end-start <= 90*86400_000_000:
            raise ValueError("Trade catalog must cover at most 90 days")
        return {**value, "start": iso_time(start), "end": iso_time(end), "minimum_interval_seconds": .001}
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


def validate(payload, *, coverage=None):
    source = payload.get("btc_data_source", "minute")
    if source not in ("minute", "trade_tape"):
        raise ValueError("Unknown BTC data source")
    if source != "trade_tape":
        return None
    from trade_ordering import POLICIES
    if payload.get('trade_ordering', 'sequence') not in POLICIES:
        raise ValueError('Unknown trade ordering policy')
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
    coverage = coverage or catalog()
    lo, hi = gui.backtest_bounds(payload)
    start, end = us_time(lo.isoformat() if lo else coverage["start"]), us_time(hi.isoformat() if hi else coverage["end"])
    if start < us_time(coverage["start"]) or end > us_time(coverage["end"]) or start >= end:
        raise ValueError(f"Trade data covers only [{coverage['start']}, {coverage['end']}) UTC; choose a window inside it")
    limit = coverage["maximum_decisions"]
    if math.ceil((end - start) / interval) > limit:
        raise ValueError(f"Trade replay permits at most {limit:,} decisions; shorten the period to at most {limit * interval / 1e6:g} seconds or increase the interval")
    return p, start, end, interval, delay, capital


def run(payload, data_root, audit_collection, progress=None, *, store=None, coverage=None):
    p, start, end, interval, delay, capital = validate(payload, coverage=coverage)
    notify = progress or (lambda *_: None)
    notify("loading_trade_data", "Verifying selected immutable BTC daily trade partitions")
    dataset_uri = str(getattr(store, "root", "synthetic-fixture")) if store is not None else catalog().get("uri", DATASET_URI)
    if store is None:
        from trade_data_store import ParquetTradeStore
        store = ParquetTradeStore(dataset_uri)
        if hashlib.sha256(store.manifest_bytes).hexdigest() != catalog()["manifest_sha256"]:
            raise ValueError("Trade dataset manifest checksum mismatch")
    store.check_cancelled = audit_collection.check_cancelled
    from trade_ordering import OrderedTradeStore, POLICY_VERSION
    store = OrderedTradeStore(store, payload.get('trade_ordering', 'sequence'), notify)
    manifest = store.source_manifest
    if start < us_time(manifest["start"]) or end > us_time(manifest["end"]):
        raise ValueError("Requested window is outside trade manifest coverage")
    rates = strategy.read_rates(data_root)
    started = time.monotonic()
    from replay_checkpoints import fingerprint
    identity = fingerprint(payload, store.manifest_bytes, data_root)
    journal = audit_collection.checkpoints
    if journal and not getattr(audit_collection.store, "replay_safe", False):
        from backtest_audit import ReplayAuditStore
        audit_collection.store = ReplayAuditStore(audit_collection.store)
    restored = journal.latest() if journal else None
    if restored and restored["identity"] != identity:
        raise ValueError("Checkpoint parameters, engine or dataset differ")
    writer = audit_collection.writer("btc_trade_events")
    valuations = audit_collection.writer("btc_trade_valuations")
    writer.row_limit = valuations.row_limit = 65536
    def emit(row):
        writer.emit({**row, "date": iso_time(row["us"])})
    expiries = {s: us_time(info["expiry"]) for s, info in manifest["futures"].items()}
    if restored:
        account = TapeAccount.restore(restored["account"], emit)
        audit_collection.restore(restored["audit"])
        state = restored["state"]
        if hasattr(store, "accessed_partitions"):
            store.accessed_partitions = restored.get("partitions", [])
        initial_us, initial_price = state["initial_us"], state["initial_price"]
        count, decisions, no_fresh = state["count"], state["decisions"], state["no_fresh"]
        excluded_expiry_prints, delayed_expiry_prints = state["excluded_expiry_prints"], state["delayed_expiry_prints"]
        previous_nav, previous_tick = state["previous_nav"], state["previous_tick"]
        previous_allocation = state["previous_allocation"]
        max_error, simple = state["max_error"], state["simple"]
        max_drawdown, direct_drawdown = state["max_drawdown"], state["direct_drawdown"]
        peak, direct_peak, series = state["peak"], state["direct_peak"], state["series"]
        sample_every = state["sample_every"]
        tape = iter(store.trades(start_us=previous_tick+1, end_us=end))
        event = next(tape, None)
        notify("resuming_trade_replay", f"Resuming after {iso_time(previous_tick)} UTC")
    else:
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
        excluded_expiry_prints = delayed_expiry_prints = 0
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
    if not restored:
        series.append(point(initial_us))
    last_progress = time.monotonic()
    tick = min(previous_tick + interval, end) if restored else min((initial_us // interval + 1) * interval, end)
    checkpoint_hour = previous_tick // 3_600_000_000
    pending_expiries = iter(sorted((expiry, symbol) for symbol, expiry in expiries.items()
                                  if expiry > account.last_us))
    next_expiry = next(pending_expiries, None)
    # Daily closing yields become observable on the next UTC midnight; explicit
    # timestamped yields retain that time. These boundaries need not be clock ticks.
    rate_times = sorted({us_time(strategy._rate_available_at(day, EPOCH).isoformat())
                         for observations in rates.values() for day, _ in observations})
    rate_updates = iter(t for t in rate_times if account.last_us < t <= end)
    next_rate = next(rate_updates, None)
    def settle_through(us):
        nonlocal next_expiry, next_rate
        while (next_expiry and next_expiry[0] <= us) or (next_rate is not None and next_rate <= us):
            if next_rate is not None and next_rate <= us and (not next_expiry or next_rate <= next_expiry[0]):
                account.accrue(next_rate)
                account.rate = strategy.usd_rate(rates, EPOCH+timedelta(microseconds=next_rate), strategy.TENORS[0][0])
                if account.rate is None:
                    raise ValueError("No observable Treasury yield")
                next_rate = next(rate_updates, None)
                continue
            expiry, symbol = next_expiry
            record = manifest["futures"][symbol].get("settlement")
            if account.units.get(symbol, 0) > 1e-14 and not record:
                raise ValueError("Held futures reached expiry without a verified settlement price")
            if record:
                if us_time(record["time"]) != expiry:
                    raise ValueError("Settlement does not match contract expiry")
                account.settle(symbol, expiry, record["price"], record["source"])
            else:
                account.cancel(expiry, "expiry", {symbol})
            next_expiry = next(pending_expiries, None)
    while True:
        audit_collection.check_cancelled()
        while event and event.us <= tick and event.us < end:
            settle_through(event.us)
            if event.symbol == 'SPOT' or event.us < expiries[event.symbol]:
                account.on_trade(event)
            else:
                excluded_expiry_prints += 1
                delayed_expiry_prints += int(event.reported_us is not None and event.reported_us < expiries[event.symbol])
            count += 1
            if count % 8192 == 0:
                audit_collection.check_cancelled()
            event = next(tape, None)
        settle_through(tick)
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
                   mark_us={s: m.us for s, m in account.marks.items()},
                   reported_mark_us={s: m.reported_us if m.reported_us is not None else m.us for s,m in account.marks.items()}, reconstruction_error_usd=error,
                   starting_nav=previous_nav/capital, ending_nav=account.nav/capital,
                   direct_nav=direct, futures_notional_usd=account.collateral, fees_usd=account.fees)
        valuations.emit(row)
        if decisions % sample_every == 0 or tick == end:
            series.append(point(tick))
        previous_nav, previous_tick = account.nav, tick
        if time.monotonic() - last_progress > 10:
            notify("trade_replay", f"{iso_time(tick)} UTC · {decisions:,} decisions · {account.fill_count:,} fills ({100*(tick-start)/(end-start):.2f}%)")
            last_progress = time.monotonic()
        if journal and tick < end and tick // 3_600_000_000 > checkpoint_hour:
            audit_state = audit_collection.snapshot()
            state = dict(initial_us=initial_us, initial_price=initial_price, count=count,
                         excluded_expiry_prints=excluded_expiry_prints, delayed_expiry_prints=delayed_expiry_prints,
                         decisions=decisions, no_fresh=no_fresh, previous_nav=previous_nav,
                         previous_tick=previous_tick, previous_allocation=previous_allocation,
                         max_error=max_error, simple=simple, max_drawdown=max_drawdown,
                         direct_drawdown=direct_drawdown, peak=peak, direct_peak=direct_peak,
                         series=series, sample_every=sample_every)
            journal.save(tick, dict(schema_version=1, identity=identity, account=account.snapshot(),
                                    state=state, audit=audit_state, source_cursor_exclusive_us=tick,
                                    partitions=getattr(store, "accessed_partitions", [])))
            checkpoint_hour = tick // 3_600_000_000
            notify("trade_checkpoint", f"Saved continuous account through {iso_time(tick)} UTC")
        if tick == end:
            break
        tick = min(tick + interval, end)
    provenance = {"dataset_id": (coverage or catalog())["id"], "manifest_sha256": hashlib.sha256(store.manifest_bytes).hexdigest(),
                  "dataset_uri": dataset_uri, "partitions": getattr(store, "accessed_partitions", store.manifest["partitions"])}
    ordering = store.window_report(start,end)
    ordering.update(excluded_expiry_prints=excluded_expiry_prints, delayed_past_expiry_prints=delayed_expiry_prints, delayed_fills=account.delayed_fill_count)
    provenance['ordering'] = ordering
    provenance['anomaly_evidence'] = manifest.get('discrepancy_evidence', [
        dict(instrument=symbol, **info['discrepancy'], evidence_files=info.get('evidence_files', []))
        for symbol,info in manifest['futures'].items() if 'discrepancy' in info])
    audit_collection.provenance['trade_data'] = provenance
    audit = audit_collection.finish()
    measured = {**getattr(store, "timings", {}), **audit_collection.timings}
    measured["ordering_preparation"] = store.preparation_seconds
    measured["replay_wall"] = time.monotonic()-started
    measured["strategy_and_checkpoint"] = max(0.0, measured["replay_wall"] -
        measured.get("decode_and_merge", 0) - measured["audit_compression"] - measured["audit_write"])
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
                                  fees_usd=account.fees, turnover_usd=account.turnover, treasury_interest_usd=account.interest,
                                  max_nav_reconstruction_error_usd=max_error,
                                  plot_sample_every=sample_every,
                                  resumed_after_us=restored["source_cursor_exclusive_us"] if restored else None,
                                  timings_seconds=measured,
                                  end_mark_age_seconds={s: (end-m.us)/1e6 for s,m in account.marks.items()},
                                  assumptions=["Research ordering: "+store.policy+" ("+POLICY_VERSION+"); historical arrival times are unknown",
                                               "Deribit inverse quotes as regular USD futures proxy; Binance USDT/USD assumed 1",
                                               "Same-side subsequent prints; strict later timestamp after delay; cancel/replace each decision",
                                               "Long only; 100% USD collateral; fractional lots; causal Treasury accrual",
                                               "Stale marks value holdings but cannot create fresh signals; no order-book or synchronized latency model",
                                               "First spot print initializes owned BTC; final NAV is marked, without liquidation"]))
