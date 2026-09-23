"""Cost-aware ranking without arbitrary holding-horizon grids.

Every instrument is compared on an annualized lease return after the costs that
remain between now and expiry.  Existing inventory uses a KEEP return, which
does not charge its sunk entry ticket.  A proposed destination includes the
source exit, destination entry and destination expiry/default-position costs.
The direct BTC holding is the default instrument and earns the negative custody
or proxy-expense rate.

The module selects transfers only.  Durable orders, funding reservations,
partial fills and latency remain the responsibility of ``paired_transfer``.
"""
from dataclasses import asdict, replace
import math

from paired_transfer_economics import (
    EPS, YEAR_US, PositionSlice, QuoteSnapshot, TransferDecision, funded_quantity,
)


def _fee(fees, product, quantity, price):
    schedule = (fees or {}).get(product)
    return 0.0 if schedule is None or quantity <= 0 else float(
        schedule.total_fee(quantity, quantity * price))


def _years(now_us, quote):
    if quote.symbol == "SPOT":
        return None
    value = (quote.expiry_us - now_us) / YEAR_US if quote.expiry_us is not None else 0.0
    return value if math.isfinite(value) and value > 0 else None


def gross_lease_rate(now_us, quote, spot, cash_rate):
    """Annual simple lease convention used by the existing BTC research path."""
    if quote.symbol == "SPOT":
        return None
    years = _years(now_us, quote)
    if years is None or min(quote.price, spot.price) <= 0:
        return None
    value = cash_rate - (quote.price / spot.price - 1.0) / years
    return value if math.isfinite(value) else None


def keep_amortized_return(now_us, position, spot, *, cash_rate, fees, config):
    """Return remaining on held inventory; its historical entry cost is sunk."""
    quote, quantity = position.quote, position.quantity_btc
    if quote.symbol == "SPOT":
        return dict(symbol="SPOT", gross_rate=-config.proxy_expense_rate,
                    amortized_rate=-config.proxy_expense_rate, years=None,
                    remaining_cost_usd=0.0, entry_cost_is_sunk=True)
    years = _years(now_us, quote)
    gross = gross_lease_rate(now_us, quote, spot, cash_rate)
    if years is None or gross is None:
        return None
    # At modeled cash delivery, return to the default direct holding.  Delivery
    # and the replacement spot ticket are still future costs; the opening
    # future ticket is deliberately absent.
    delivery = _fee(fees, "delivery", quantity, quote.price)
    spot_buy = _fee(fees, "spot", quantity, spot.price)
    capital = max(EPS, quantity * spot.price)
    cost_rate = (delivery + spot_buy) / capital / years
    return dict(symbol=quote.symbol, gross_rate=gross,
                amortized_rate=gross - config.conservative_lease_bps / 10000 - cost_rate,
                years=years, remaining_cost_usd=delivery + spot_buy,
                annualized_cost_rate=cost_rate, entry_cost_is_sunk=True)


def _released_cash(source, quantity, source_price, fees):
    product = "spot" if source.quote.symbol == "SPOT" else "futures"
    fee = _fee(fees, product, quantity, source_price)
    fraction = quantity / source.quantity_btc
    cash = source.cash_usd * fraction
    unsettled = source.unsettled_pnl_usd * fraction
    if source.quote.symbol == "SPOT":
        released = cash + quantity * source_price - fee
    else:
        released = cash + unsettled + quantity * (source_price - source.quote.price) - fee
    return released, fee


def evaluate_amortized_transfer(now_us, source, target, spot, *, cash_rate,
                                fees=None, config, source_price=None,
                                target_price=None, source_entry_fees=None,
                                target_entry_fees=None):
    """Compare a destination's fee-amortized return with the source KEEP rate.

    The comparison horizon is always the relevant expiry: target expiry for a
    future destination, or source expiry when returning to perpetual direct BTC.
    No arbitrary list of 1/3/7/... day holding periods is consulted.
    """
    base = dict(source_symbol=source.quote.symbol, target_symbol=target.symbol)
    reject = lambda reason, **extra: TransferDecision(False, reason, **base, **extra)
    if source.quote.symbol == target.symbol or source.quantity_btc <= 0:
        return reject("unchanged_position")
    if spot.symbol != "SPOT" or min(spot.price, source.quote.price, target.price) <= 0:
        return reject("unavailable_price")
    source_price = source.quote.price if source_price is None else float(source_price)
    target_price = target.price if target_price is None else float(target_price)
    if min(source_price, target_price) <= 0:
        return reject("unavailable_execution_price")
    keep = keep_amortized_return(now_us, source, spot, cash_rate=cash_rate,
                                 fees=fees, config=config)
    if keep is None:
        return reject("unavailable_keep_return")

    quantity = min(source.quantity_btc * config.max_transfer_fraction,
                   config.max_delta_btc)
    if source.quote.size_btc is not None:
        quantity = min(quantity, source.quote.size_btc)
    if target.size_btc is not None:
        quantity = min(quantity, target.size_btc)
    if quantity <= EPS:
        return reject("no_transfer_quantity")

    source_product = "spot" if source.quote.symbol == "SPOT" else "futures"
    target_product = "spot" if target.symbol == "SPOT" else "futures"
    source_fees = ({source_product: source_entry_fees}
                   if source_entry_fees is not None else fees)
    target_fees = ({target_product: target_entry_fees}
                   if target_entry_fees is not None else fees)
    released, source_exit_fee = _released_cash(source, quantity, source_price, source_fees)
    budget = max(0.0, released) * (1 - config.cash_reserve_fraction)
    target_quantity, target_entry_fee = funded_quantity(
        budget, target_price, target_fees, target_product)
    target_quantity = min(quantity, target_quantity)
    target_entry_fee = _fee(target_fees, target_product, target_quantity, target_price)
    if target_quantity <= EPS:
        return reject("entry_costs_exceed_funding")

    if target.symbol == "SPOT":
        years = _years(now_us, source.quote)
        # The perpetual candidate itself earns only negative proxy expense.  A
        # future source's remaining life is the conservative period over which
        # the actual exit and spot-entry tickets must recover.
        if years is None:
            return reject("no_cost_amortization_period")
        gross = -config.proxy_expense_rate
        future_cost = 0.0
        horizon_us = source.quote.expiry_us
    else:
        years = _years(now_us, replace(target, price=target_price))
        gross = gross_lease_rate(now_us, replace(target, price=target_price), spot, cash_rate)
        if years is None or gross is None:
            return reject("unavailable_target_return")
        future_cost = (_fee(fees, "delivery", target_quantity, target_price)
                       + _fee(fees, "spot", target_quantity, spot.price))
        horizon_us = target.expiry_us

    capital = max(EPS, target_quantity * spot.price)
    transfer_cost = source_exit_fee + target_entry_fee + future_cost
    annualized_cost = transfer_cost / capital / years
    candidate_rate = (gross - config.conservative_lease_bps / 10000
                      - annualized_cost)
    improvement = candidate_rate - keep["amortized_rate"]
    required = config.min_improvement_bps / 10000
    accepted = improvement > required + EPS
    reason = ("amortized_return_improvement" if accepted
              else "amortized_improvement_below_buffer")
    # BTC edge is an audit-scale approximation only; selection uses the exact
    # annualized rate comparison above, not this field.
    edge_btc = target_quantity * improvement * years
    required_btc = target_quantity * required * years
    diagnostics = dict(
        selection_model="expiry_amortized_return_ranking",
        lease_estimator="causal_sufficiently_close_spot_future_observations",
        no_discrete_holding_horizons=True,
        source_keep=keep,
        target_candidate=dict(symbol=target.symbol, gross_rate=gross,
            amortized_rate=candidate_rate, years=years,
            conservative_lease_discount_bps=config.conservative_lease_bps,
            source_exit_fee_usd=source_exit_fee,
            target_entry_fee_usd=target_entry_fee,
            target_expiry_and_default_position_cost_usd=future_cost,
            annualized_cost_rate=annualized_cost),
        annualized_improvement=improvement,
        required_annualized_improvement=required,
        source_sale_limit=source_price,
        target_buy_limit=target_price,
        cash_reserve_usd=max(0.0, released - budget),
        residual_source_quantity_btc=source.quantity_btc - quantity,
        max_delta_btc=config.max_delta_btc,
        maximum_transfer_fraction=config.max_transfer_fraction,
        ranking_order="worst held KEEP return to best candidate amortized return",
        transition_costs_in_amortized_return=True,
        liquidity_assumption=("displayed_quantity_limit" if target.size_btc is not None
                              else "tape_participation_no_observed_order_book_depth"),
    )
    return TransferDecision(accepted, reason, **base,
        source_quantity_btc=quantity, target_quantity_btc=target_quantity,
        source_cash_usd=source.cash_usd * quantity / source.quantity_btc,
        entry_cost_usd=source_exit_fee + target_entry_fee,
        horizon_us=horizon_us, keep_btc=quantity,
        swap_btc=quantity + edge_btc, edge_btc=edge_btc,
        required_edge_btc=required_btc,
        source_fraction=quantity / source.quantity_btc,
        diagnostics=diagnostics)


def solve_amortized_price_limit(now_us, source, target, spot, *, price_role,
                                counterpart_price, cash_rate, fees, config,
                                target_quantity_btc=None, entry_fees=None):
    """Find the adverse execution boundary that still passes the rank hurdle."""
    if price_role not in ("source", "target"):
        raise ValueError("price_role must be source or target")
    entry_fees = entry_fees or {}

    def evaluate(price):
        decision = evaluate_amortized_transfer(now_us, source, target, spot,
            cash_rate=cash_rate, fees=fees, config=config,
            source_price=price if price_role == "source" else counterpart_price,
            target_price=price if price_role == "target" else counterpart_price,
            source_entry_fees=entry_fees.get("source"),
            target_entry_fees=entry_fees.get("target"))
        if target_quantity_btc is not None and decision.target_quantity_btc + EPS < target_quantity_btc:
            return replace(decision, accepted=False, reason="fixed_target_exceeds_funding")
        return decision

    reference = source.quote.price if price_role == "source" else target.price
    accepted_price = rejected_price = None
    accepted_decision = None
    price = reference
    for _ in range(64):
        decision = evaluate(price)
        if decision.accepted:
            accepted_price, accepted_decision = price, decision
            break
        price = price * 2 if price_role == "source" else price / 2
        if not math.isfinite(price) or price <= 0:
            return None, None
    if accepted_price is None:
        return None, None
    price = accepted_price
    for _ in range(64):
        price = price / 2 if price_role == "source" else price * 2
        if not math.isfinite(price) or price <= 0:
            return None, None
        decision = evaluate(price)
        if not decision.accepted:
            rejected_price = price
            break
        accepted_price, accepted_decision = price, decision
    if rejected_price is None:
        return None, None
    for _ in range(56):
        middle = (accepted_price + rejected_price) / 2
        decision = evaluate(middle)
        if decision.accepted:
            accepted_price, accepted_decision = middle, decision
        else:
            rejected_price = middle
    boundary = dict(price_role=price_role, accepted_price=accepted_price,
                    rejected_price=rejected_price,
                    fixed_counterpart_price=counterpart_price,
                    required_annualized_improvement=config.min_improvement_bps / 10000)
    accepted_decision = replace(accepted_decision, diagnostics={
        **accepted_decision.diagnostics, "amortized_price_boundary": boundary})
    return accepted_price, accepted_decision


def rank_amortized_decisions(decisions):
    """Worst held KEEP first, then best candidate; deterministic tie breaks."""
    def field(row, name, default=None):
        return row.get(name, default) if isinstance(row, dict) else getattr(row, name, default)
    def diagnostics(row):
        return field(row, "diagnostics", {}) or {}
    return sorted(decisions, key=lambda decision: (
        diagnostics(decision).get("source_keep", {}).get("amortized_rate", math.inf),
        -diagnostics(decision).get("target_candidate", {}).get("amortized_rate", -math.inf),
        field(decision, "source_symbol", ""), field(decision, "target_symbol", "")))
