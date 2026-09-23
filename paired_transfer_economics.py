"""Causal KEEP-versus-transfer forecasts for the funded BTC research policy.

This module never fills an order. Prices are explicit trade-print proxies and the
forecast holds spot flat while today's futures basis fades linearly toward a
configured settlement-reference basis. This is an assumption, not earned carry.
All candidates start with exactly the same marked capital as their KEEP slice.
"""
from dataclasses import asdict, dataclass, field, replace
import math

from funded_ledger import FeeSchedule

DAY_US = 86400 * 1_000_000
YEAR_US = 365 * DAY_US
EPS = 1e-10


@dataclass(frozen=True)
class QuoteSnapshot:
    symbol: str
    price: float
    source_us: int
    available_us: int
    expiry_us: int | None = None
    size_btc: float | None = None
    price_kind: str = "trade_print_proxy"


@dataclass(frozen=True)
class PositionSlice:
    quote: QuoteSnapshot
    quantity_btc: float
    cash_usd: float = 0.0
    unsettled_pnl_usd: float = 0.0


@dataclass(frozen=True)
class EconomicsConfig:
    horizon_days: tuple[float, ...] = (1, 3, 7, 14, 30)
    max_horizon_days: float = 30.0
    uncertainty_bps: float = 5.0
    cost_buffer_multiplier: float = 1.0
    min_gain_btc: float = 0.0
    max_transfer_fraction: float = 0.25
    size_fractions: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0)
    cash_reserve_fraction: float = 0.01
    price_limit_bps: float = 10.0
    half_spread_bps: float = 0.0
    slippage_bps: float = 0.0
    proxy_expense_rate: float = 0.0
    settlement_interval_seconds: float = 86400.0
    settlement_basis_bps: float = 0.0
    max_quote_age_seconds: float = 1.0
    max_quote_skew_seconds: float = 1.0

    def __post_init__(self):
        nonnegative = (self.uncertainty_bps, self.min_gain_btc, self.price_limit_bps,
                       self.max_quote_age_seconds, self.max_quote_skew_seconds,
                       self.half_spread_bps, self.slippage_bps, self.proxy_expense_rate)
        if any(not math.isfinite(x) or x < 0 for x in nonnegative):
            raise ValueError("Economic buffers and quote limits must be finite and nonnegative")
        if not math.isfinite(self.cost_buffer_multiplier) or self.cost_buffer_multiplier < 1:
            raise ValueError("Cost buffer multiplier must be at least one")
        if not math.isfinite(self.max_horizon_days) or not 0 < self.max_horizon_days <= 3650:
            raise ValueError("Maximum forecast horizon must be in (0, 3650] days")
        if not self.horizon_days or any(not math.isfinite(x) or x <= 0 for x in self.horizon_days):
            raise ValueError("Forecast horizons must be positive and finite")
        if not math.isfinite(self.max_transfer_fraction) or not 0 < self.max_transfer_fraction <= 1:
            raise ValueError("Maximum transfer fraction must be in (0, 1]")
        if not self.size_fractions or any(not math.isfinite(x) or not 0 < x <= 1 for x in self.size_fractions):
            raise ValueError("Candidate size fractions must be in (0, 1]")
        if not math.isfinite(self.cash_reserve_fraction) or not 0 <= self.cash_reserve_fraction < 1:
            raise ValueError("Cash reserve fraction must be in [0, 1)")
        if self.execution_bps >= 10000:
            raise ValueError("Price limit must be below 10000 bps")
        if not math.isfinite(self.settlement_interval_seconds) or self.settlement_interval_seconds < 1:
            raise ValueError("Variation settlement interval must be at least one second")
        if self.max_horizon_days * 86400 / self.settlement_interval_seconds > 4096:
            raise ValueError("Forecast horizon permits at most 4096 variation settlements; shorten it or increase the settlement interval")
        if not math.isfinite(self.settlement_basis_bps) or self.settlement_basis_bps <= -10000:
            raise ValueError("Settlement-reference basis must imply a positive price")

    @property
    def execution_bps(self):
        return self.price_limit_bps + self.half_spread_bps + self.slippage_bps

    @classmethod
    def from_payload(cls, payload):
        # Support the early plural spelling when loading research parameter files.
        raw = payload.get("paired_horizon_days", payload.get("paired_horizons_days", "1,3,7,14,30"))
        if isinstance(raw, str):
            try:
                horizons = tuple(float(x.strip()) for x in raw.split(",") if x.strip())
            except ValueError:
                raise ValueError("Paired holding horizons must be comma-separated days") from None
        else:
            horizons = tuple(float(x) for x in raw)
        mapping = {
            "max_horizon_days": "paired_max_horizon_days",
            "uncertainty_bps": "paired_uncertainty_bps",
            "cost_buffer_multiplier": "paired_cost_buffer_multiplier",
            "min_gain_btc": "paired_min_gain_btc",
            "max_transfer_fraction": "paired_max_transfer_fraction",
            "cash_reserve_fraction": "paired_cash_reserve_fraction",
            "price_limit_bps": "paired_price_limit_bps",
            "settlement_interval_seconds": "paired_settlement_interval_seconds",
            "settlement_basis_bps": "paired_settlement_basis_bps",
            "max_quote_age_seconds": "max_quote_age_seconds",
            "max_quote_skew_seconds": "paired_max_quote_skew_seconds",
        }
        defaults = cls()
        return cls(horizon_days=horizons,
                   half_spread_bps=float(payload.get("half_spread_bps", 0)),
                   slippage_bps=float(payload.get("slippage_bps", 0)),
                   proxy_expense_rate=float(payload.get("slv_expense", 0)) / 100, **{
            key: float(payload.get(name, getattr(defaults, key))) for key, name in mapping.items()})


@dataclass(frozen=True)
class IncrementalFeeSchedule:
    """Snapshot of an existing child ticket's still-unpaid marginal commission.

    Use only as an ``entry_fees`` override. A future liquidation has its own
    ticket and must continue to use the ordinary full fee schedule.
    """
    schedule: object
    cumulative_quantity: float = 0.0
    cumulative_notional: float = 0.0
    already_paid: float = 0.0

    def __post_init__(self):
        if any(not math.isfinite(v) or v < 0 for v in (
                self.cumulative_quantity, self.cumulative_notional, self.already_paid)):
            raise ValueError("Existing fee-ticket totals must be finite and nonnegative")

    @property
    def currency(self):
        return getattr(self.schedule, "currency", "USD")

    def total_fee(self, quantity, notional):
        if quantity <= 0:
            return 0.0
        total = self.schedule.total_fee(self.cumulative_quantity + quantity,
                                       self.cumulative_notional + notional)
        return max(0.0, total - self.already_paid)


@dataclass(frozen=True)
class Forecast:
    terminal_btc: float
    terminal_cash_usd: float
    interest_usd: float
    futures_pnl_usd: float
    exit_cost_usd: float
    projected_future_price: float | None
    minimum_cash_usd: float
    funding_feasible: bool


@dataclass(frozen=True)
class TransferDecision:
    accepted: bool
    reason: str
    source_symbol: str
    target_symbol: str
    source_quantity_btc: float = 0.0
    target_quantity_btc: float = 0.0
    source_cash_usd: float = 0.0
    entry_cost_usd: float = 0.0
    horizon_us: int | None = None
    keep_btc: float = 0.0
    swap_btc: float = 0.0
    edge_btc: float = 0.0
    required_edge_btc: float = 0.0
    source_fraction: float = 0.0
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _fee(fees, product, quantity, notional):
    if quantity <= 0:
        return 0.0
    schedule = (fees or {}).get(product)
    amount = 0.0 if schedule is None else float(schedule.total_fee(quantity, notional))
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("Fee schedules must produce finite nonnegative USD fees")
    if schedule is not None and getattr(schedule, "currency", "USD") != "USD":
        raise ValueError("Economic forecasts require USD fee schedules")
    return amount


def funded_quantity(budget, price, fees=None, product="futures"):
    """Largest nonnegative quantity with quantity*price + ticket fee <= budget.

    The fixed/minimum charge applies once to the filled ticket, not once per
    binary-search iteration or hypothetical partial fill.
    """
    if not math.isfinite(budget) or budget <= 0:
        return 0.0, 0.0
    if not math.isfinite(price) or price <= 0:
        raise ValueError("A positive funding price is required")
    high = budget / price
    if high * price + _fee(fees, product, high, high * price) <= budget:
        return high, _fee(fees, product, high, high * price)
    low = 0.0
    for _ in range(64):
        mid = (low + high) / 2
        if mid * price + _fee(fees, product, mid, mid * price) <= budget:
            low = mid
        else:
            high = mid
    if low <= EPS * max(1.0, budget / price):
        return 0.0, 0.0
    return low, _fee(fees, product, low, low * price)


def effective_lease_rate(spot_price, futures_price, *, cash_rate, remaining_years,
                         spot_quantity_btc=1.0, futures_quantity_btc=None,
                         spot_fee_usd=0.0, futures_fee_usd=0.0):
    """Net-entry annual lease for selling spot and buying a funded long future.

    The convention is ``r - (net_future / net_spot - 1) / T``, with fees
    allocated per unit of their respective matched legs. Prices may be executed
    VWAPs or explicit prospective prices. This is an entry-basis statistic, not
    a terminal BTC forecast: cash reserves, unequal exposure, future exit fees,
    variation timing and cash compounding still require ``evaluate_transfer``.
    Nonpositive maturity or spot proceeds make the statistic undefined.
    """
    futures_quantity_btc = spot_quantity_btc if futures_quantity_btc is None else futures_quantity_btc
    if (any(not math.isfinite(v) for v in (spot_price, futures_price, cash_rate,
            remaining_years, spot_quantity_btc, futures_quantity_btc,
            spot_fee_usd, futures_fee_usd)) or min(spot_price, futures_price,
            remaining_years, spot_quantity_btc, futures_quantity_btc) <= 0 or
            min(spot_fee_usd, futures_fee_usd) < 0):
        return None
    net_spot = spot_price - spot_fee_usd / spot_quantity_btc
    net_future = futures_price + futures_fee_usd / futures_quantity_btc
    if net_spot <= 0 or not math.isfinite(net_future):
        return None
    lease = cash_rate - (net_future / net_spot - 1.0) / remaining_years
    return lease if math.isfinite(lease) else None


def _affine_counterpart_limit(instrument, bound, quantity, schedule, fee_per_unit):
    """Exact branches for the ledger's capped/minimum affine ticket schedule.

    An existing ticket adds its paid quantity/notional before calculating the
    cumulative fee, then subtracts the actual fee already charged. All possible
    affine branches are cheap to solve; evaluating the real fee validates which
    candidate lies inside its branch. Arbitrary schedules use the general search.
    """
    cumulative_quantity = cumulative_notional = paid = 0.0
    if isinstance(schedule, IncrementalFeeSchedule):
        cumulative_quantity = schedule.cumulative_quantity
        cumulative_notional = schedule.cumulative_notional
        paid = schedule.already_paid
        schedule = schedule.schedule
    if schedule is None:
        pieces = ((0.0, 0.0),)
    elif isinstance(schedule, FeeSchedule):
        intercept = (schedule.fixed + schedule.per_unit * (cumulative_quantity + quantity)
                     + schedule.fee_bps * cumulative_notional / 10000 - paid)
        slope = schedule.fee_bps * quantity / 10000
        pieces = [(0.0, 0.0), (max(0.0, schedule.minimum - paid), 0.0),
                  (intercept, slope)]
        if schedule.cap is not None:
            pieces.append((max(0.0, schedule.cap - paid), 0.0))
    else:
        return None
    sign = 1 if instrument == "futures" else -1
    for intercept, slope in pieces:
        denominator = 1 + sign * slope / quantity
        if denominator <= 0:
            continue
        price = (bound - sign * intercept / quantity) / denominator
        if not math.isfinite(price) or price <= 0:
            continue
        value = price + sign * fee_per_unit(price)
        if not math.isclose(value, bound, rel_tol=2e-14, abs_tol=1e-13):
            continue
        # Choose the conservative representable side of a rounded solution.
        for _ in range(4):
            if (value <= bound if instrument == "futures" else value >= bound):
                return price
            price = math.nextafter(price, 0.0 if instrument == "futures" else math.inf)
            value = price + sign * fee_per_unit(price)
    return None


def counterpart_price_limit(*, instrument, counterpart_price, target_lease_rate,
                            cash_rate, remaining_years, quantity_btc,
                            counterpart_quantity_btc=None, counterpart_fee_usd=0.0,
                            fee_schedule=None):
    """Maximum future BUY or minimum spot SELL preserving a net-entry lease.

    ``counterpart_price`` and its fee are fixed evidence, normally an executed
    VWAP and actual allocated fee after the first leg fills. Before a fill they
    are an observed price and estimated fee. ``fee_schedule`` estimates only
    the still-open leg and can be an ``IncrementalFeeSchedule``. The two limits
    are conditional on their counterpart evidence, not an atomic fill promise.

    Fee schedules must have nondecreasing total fees and net spot proceeds as
    price increases (as the supported USD schedules do below 100% commission).
    The funded ledger and full KEEP comparison remain separate mandatory gates.
    """
    if instrument not in ("spot", "futures"):
        raise ValueError("Lease counterpart must be spot or futures")
    counterpart_quantity_btc = quantity_btc if counterpart_quantity_btc is None else counterpart_quantity_btc
    if (any(not math.isfinite(v) for v in (counterpart_price, target_lease_rate,
            cash_rate, remaining_years, quantity_btc, counterpart_quantity_btc,
            counterpart_fee_usd)) or min(counterpart_price, remaining_years,
            quantity_btc, counterpart_quantity_btc) <= 0 or counterpart_fee_usd < 0):
        return None
    ratio = 1.0 + (cash_rate - target_lease_rate) * remaining_years
    if not math.isfinite(ratio) or ratio <= 0:
        return None
    fees = {instrument: fee_schedule} if fee_schedule is not None else None
    fee_per_unit = lambda p: _fee(fees, instrument, quantity_btc, quantity_btc * p) / quantity_btc
    if instrument == "futures":
        net_spot = counterpart_price - counterpart_fee_usd / counterpart_quantity_btc
        ceiling = net_spot * ratio
        if not math.isfinite(ceiling) or ceiling <= 0 or fee_per_unit(0) >= ceiling:
            return None
        exact = _affine_counterpart_limit(instrument, ceiling, quantity_btc, fee_schedule, fee_per_unit)
        if exact is not None:
            return exact
        low, high = 0.0, ceiling
        for _ in range(64):
            mid = (low + high) / 2
            if mid + fee_per_unit(mid) <= ceiling:
                low = mid
            else:
                high = mid
        return low if low > 0 else None
    net_future = counterpart_price + counterpart_fee_usd / counterpart_quantity_btc
    floor = net_future / ratio
    if not math.isfinite(floor) or floor <= 0:
        return None
    exact = _affine_counterpart_limit(instrument, floor, quantity_btc, fee_schedule, fee_per_unit)
    if exact is not None:
        return exact
    low, high = 0.0, floor
    for _ in range(64):
        if high - fee_per_unit(high) >= floor:
            break
        high *= 2
        if not math.isfinite(high) or not math.isfinite(quantity_btc * high):
            return None
    else:
        return None
    for _ in range(64):
        mid = (low + high) / 2
        if mid - fee_per_unit(mid) >= floor:
            high = mid
        else:
            low = mid
    return high


def solve_economic_price_limit(now_us, source, target, spot, *, counterpart_price,
                               cash_rate, target_quantity_btc, comparison_horizon_us,
                               price_role="target", fees=None, config=None,
                               entry_fees=None, reference_price=None):
    """Find the last accepted buy cap/sell floor under the full KEEP forecast.

    ``source`` is the exact already-selected quantity, assigned cash and
    unsettled P&L. The search fixes that size, the target quantity and the
    absolute common horizon; it cannot manufacture acceptance by shrinking a
    ticket or changing its holding period. ``price_role='target'`` maximizes a
    target BUY price with the source SELL price fixed to ``counterpart_price``;
    ``'source'`` minimizes a source SELL price with the target BUY price fixed.

    Returns ``(price, accepted_decision)`` or ``(None, None)``. The last accepted
    side of the numerical bracket preserves the strictly positive net BTC
    hurdle, including funding, entry/exit costs and uncertainty. This helper
    supports all evaluator routes; interpreting its boundary as a single lease
    rate is supported only for SPOT-to-future transfers.
    """
    if price_role not in ("source", "target"):
        raise ValueError("Economic price role must be source or target")
    cfg = replace(config or EconomicsConfig(), max_transfer_fraction=1.0, size_fractions=(1.0,))
    quote = source.quote if price_role == "source" else target
    reference_price = quote.price if reference_price is None else reference_price
    if any(not math.isfinite(v) or v <= 0 for v in (reference_price, counterpart_price)):
        return None, None
    opposite = "target" if price_role == "source" else "source"

    def evaluate(price):
        return evaluate_transfer(now_us, source, target, spot, cash_rate=cash_rate,
            fees=fees, config=cfg, entry_fees=entry_fees,
            target_quantity_btc=target_quantity_btc,
            execution_price_overrides={price_role: price, opposite: counterpart_price},
            comparison_horizon_us=comparison_horizon_us)

    price = reference_price
    decision = evaluate(price)
    # Locate one accepted point before looking for the first rejected bound.
    for _ in range(64):
        if decision.accepted:
            break
        price = price / 2 if price_role == "target" else price * 2
        if not math.isfinite(price) or price <= 0:
            return None, None
        decision = evaluate(price)
    else:
        return None, None
    accepted_price, accepted_decision = price, decision
    for _ in range(64):
        price = price * 2 if price_role == "target" else price / 2
        if not math.isfinite(price) or price <= 0:
            return None, None
        decision = evaluate(price)
        if not decision.accepted:
            break
        accepted_price, accepted_decision = price, decision
    else:
        return None, None
    rejected_price = price
    rejected_decision = decision
    for _ in range(56):
        price = (accepted_price + rejected_price) / 2
        if price in (accepted_price, rejected_price):
            break
        decision = evaluate(price)
        if decision.accepted:
            accepted_price, accepted_decision = price, decision
        else:
            rejected_price = price
            rejected_decision = decision
    boundary = dict(price_role=price_role, accepted_price=accepted_price,
                    rejected_price=rejected_price, binding_reason=rejected_decision.reason,
                    fixed_source_quantity_btc=source.quantity_btc,
                    fixed_target_quantity_btc=target_quantity_btc,
                    fixed_horizon_us=comparison_horizon_us)
    accepted_decision = replace(accepted_decision, diagnostics={
        **accepted_decision.diagnostics, "economic_price_boundary": boundary})
    return accepted_price, accepted_decision


def _projected_price(quote, spot_price, at_us, now_us, config):
    remaining = (quote.expiry_us - at_us) / (quote.expiry_us - now_us)
    initial_basis = quote.price / spot_price - 1.0
    settlement_basis = config.settlement_basis_bps / 10000.0
    return spot_price * (1 + settlement_basis + (initial_basis - settlement_basis) * remaining)


def _forecast(now_us, horizon_us, quote, quantity, cash, unsettled,
              spot_price, cash_rate, fees, config, *, entry_reference=None):
    """Mark, pay scheduled proxy variation, then liquidate at a common horizon."""
    interest = pnl_total = exit_cost = 0.0
    minimum_cash = cash
    projected = None
    rate_per_us = cash_rate / YEAR_US
    if quote.symbol == "SPOT":
        growth = math.expm1(rate_per_us * (horizon_us - now_us))
        interest = cash * growth
        cash += interest
        # An already-held spot unit requires no new terminal spot trade.
        additional, commission = funded_quantity(cash, spot_price * (1 + config.execution_bps / 10000), fees, "spot")
        residual = max(0.0, cash - additional * spot_price * (1 + config.execution_bps / 10000) - commission)
        held_btc = quantity * math.exp(-config.proxy_expense_rate * (horizon_us - now_us) / YEAR_US)
        return Forecast(held_btc + additional + residual / spot_price, cash, interest, 0.0, commission,
                        None, min(minimum_cash, cash), cash >= -EPS)
    reference = quote.price if entry_reference is None else entry_reference
    # New lots may have an adverse entry limit above their indicative mark.
    pending_pnl = unsettled + quantity * (quote.price - reference)
    last_mark = quote.price
    last_us = now_us
    interval = int(round(config.settlement_interval_seconds * 1_000_000))
    boundary = (now_us // interval + 1) * interval
    funding_feasible = cash + pending_pnl + EPS >= quantity * quote.price
    while boundary < horizon_us:
        carry = cash * math.expm1(rate_per_us * (boundary - last_us))
        interest += carry
        cash += carry
        mark = _projected_price(quote, spot_price, boundary, now_us, config)
        vm = pending_pnl + quantity * (mark - last_mark)
        cash += vm
        pnl_total += vm
        pending_pnl = 0.0
        last_mark, last_us = mark, boundary
        minimum_cash = min(minimum_cash, cash)
        funding_feasible &= cash + EPS >= quantity * mark
        boundary += interval
    carry = cash * math.expm1(rate_per_us * (horizon_us - last_us))
    interest += carry
    cash += carry
    projected = _projected_price(quote, spot_price, horizon_us, now_us, config)
    at_expiry = horizon_us == quote.expiry_us
    liquidation_price = projected if at_expiry else projected * (1 - config.execution_bps / 10000)
    pnl = pending_pnl + quantity * (liquidation_price - last_mark)
    cash += pnl
    pnl_total += pnl
    product = "delivery" if at_expiry else "futures"
    commission = _fee(fees, product, quantity, quantity * liquidation_price)
    cash -= commission
    exit_cost += commission
    minimum_cash = min(minimum_cash, cash)
    funding_feasible &= cash >= -EPS
    if cash <= 0:
        return Forecast(0.0, cash, interest, pnl_total, exit_cost, projected,
                        minimum_cash, False)
    btc, commission = funded_quantity(cash, spot_price * (1 + config.execution_bps / 10000), fees, "spot")
    exit_cost += commission
    residual = max(0.0, cash - btc * spot_price * (1 + config.execution_bps / 10000) - commission)
    return Forecast(btc + residual / spot_price, cash, interest, pnl_total, exit_cost, projected,
                    minimum_cash, bool(funding_feasible))


def _quote_failure(quote, now_us, config):
    if not quote.symbol or not math.isfinite(quote.price) or quote.price <= 0:
        return "unavailable_price"
    if quote.source_us > now_us or quote.available_us > now_us or quote.available_us < quote.source_us:
        return "quote_not_available"
    if now_us - quote.source_us > config.max_quote_age_seconds * 1_000_000:
        return "stale_quote"
    if quote.symbol != "SPOT" and (quote.expiry_us is None or quote.expiry_us <= now_us):
        return "unavailable_future_expiry"
    if quote.size_btc is not None and (not math.isfinite(quote.size_btc) or quote.size_btc <= 0):
        return "unavailable_liquidity"
    return None


def evaluate_transfer(now_us, source, target, spot, *, cash_rate, fees=None,
                      config=None, horizon_limit_us=None, entry_fees=None,
                      target_quantity_btc=None, execution_price_overrides=None,
                      comparison_horizon_us=None):
    """Choose the highest conservative NET BTC gain over KEEP among feasible sizes.

    ``source`` is the actual funded inventory slice, including its assigned cash
    and unsettled P&L; historical entry prices/fees intentionally are not inputs.
    A caller may further bound horizon by risk/funding/exit-liquidity constraints.
    ``entry_fees`` optionally overrides "source"/"target" with cumulative-ticket
    marginal schedules for pending-transfer re-evaluation. Terminal liquidation
    uses ordinary future ticket fees; past entry charges remain sunk.
    Pending orders may fix ``target_quantity_btc`` for the entire source slice,
    the original child limits in ``execution_price_overrides`` (source/target),
    and the original absolute ``comparison_horizon_us``. These preserve the
    actual remaining instruction while current quotes inform future forecasts.
    ``size_btc=None`` explicitly means no book quantity evidence: a subsequent
    tape participation executor, not this forecast, determines actual fills.
    """
    config = config or EconomicsConfig()
    entry_fees = entry_fees or {}
    execution_price_overrides = execution_price_overrides or {}
    base = dict(source_symbol=source.quote.symbol, target_symbol=target.symbol)
    reject = lambda reason, **extra: TransferDecision(False, reason, **base, **extra)
    if target_quantity_btc is not None and (not math.isfinite(target_quantity_btc) or target_quantity_btc <= 0):
        return reject("invalid_fixed_target_quantity")
    if set(execution_price_overrides) - {"source", "target"} or any(
            not math.isfinite(v) or v <= 0 for v in execution_price_overrides.values()):
        return reject("invalid_execution_price_override")
    if source.quote.symbol == target.symbol:
        return reject("unchanged_position")
    if spot.symbol != "SPOT":
        return reject("unavailable_spot_price")
    if cash_rate is None or not math.isfinite(cash_rate):
        return reject("unavailable_cash_rate")
    if abs(cash_rate) * config.max_horizon_days / 365 > 100:
        return reject("unsupported_cash_rate_magnitude")
    if not all(math.isfinite(x) for x in (source.quantity_btc, source.cash_usd, source.unsettled_pnl_usd)):
        return reject("invalid_funding_state")
    if source.quantity_btc <= 0 or source.cash_usd < 0:
        return reject("unavailable_inventory")
    for quote in (source.quote, target, spot):
        failure = _quote_failure(quote, now_us, config)
        if failure:
            return reject(failure)
    clocks = [x.source_us for x in (source.quote, target, spot)]
    if max(clocks) - min(clocks) > config.max_quote_skew_seconds * 1_000_000:
        return reject("quote_skew")
    end = now_us + round(config.max_horizon_days * DAY_US)
    for quote in (source.quote, target):
        if quote.symbol != "SPOT":
            end = min(end, quote.expiry_us)
    if horizon_limit_us is not None:
        end = min(end, horizon_limit_us)
    if end <= now_us:
        return reject("no_feasible_horizon")
    horizons = sorted({min(end, now_us + round(d * DAY_US)) for d in config.horizon_days})
    horizons = [h for h in horizons if h > now_us]
    if comparison_horizon_us is not None:
        if (not isinstance(comparison_horizon_us, int) or
                not now_us < comparison_horizon_us <= end):
            return reject("no_feasible_horizon")
        horizons = [comparison_horizon_us]
    if not horizons:
        return reject("no_feasible_horizon")
    maximum_fraction = config.max_transfer_fraction
    if source.quote.size_btc is not None:
        maximum_fraction = min(maximum_fraction, source.quote.size_btc / source.quantity_btc)
    if target.size_btc is not None:
        # Target exposure never exceeds source quantity, so this conservative
        # boundary includes feasible small transfers even below the fixed grid.
        maximum_fraction = min(maximum_fraction, target.size_btc /
                               (target_quantity_btc if target_quantity_btc is not None else source.quantity_btc))
    limit = config.execution_bps / 10000
    source_exit_price = execution_price_overrides.get("source", source.quote.price * (1 - limit))
    target_entry_price = execution_price_overrides.get("target", target.price * (1 + limit))
    initial_whole = source.cash_usd + source.unsettled_pnl_usd
    if source.quote.symbol == "SPOT":
        initial_whole += source.quantity_btc * spot.price
    if not math.isfinite(initial_whole) or initial_whole <= 0:
        return reject("unavailable_capital")
    source_product = "spot" if source.quote.symbol == "SPOT" else "futures"
    target_product = "spot" if target.symbol == "SPOT" else "futures"
    source_fees = ({source_product: entry_fees["source"]} if "source" in entry_fees else fees)
    target_fees = ({target_product: entry_fees["target"]} if "target" in entry_fees else fees)
    alternatives = []
    best = None
    for factor in sorted(set(config.size_fractions)):
        fraction = maximum_fraction * factor
        quantity = source.quantity_btc * fraction
        source_cash = source.cash_usd * fraction
        source_unsettled = source.unsettled_pnl_usd * fraction
        entry_cost = 0.0
        if source.quote.symbol == "SPOT":
            entry_cost = _fee(source_fees, "spot", quantity, quantity * source_exit_price)
            released_cash = source_cash + quantity * source_exit_price - entry_cost
        else:
            entry_cost = _fee(source_fees, "futures", quantity, quantity * source_exit_price)
            released_cash = source_cash + source_unsettled + quantity * (source_exit_price - source.quote.price) - entry_cost
        budget = released_cash * (1 - config.cash_reserve_fraction)
        if target_quantity_btc is not None:
            target_quantity = target_quantity_btc * fraction
            target_fee = _fee(target_fees, target_product, target_quantity, target_quantity * target_entry_price)
            if target_quantity > quantity + EPS:
                alternatives.append(dict(source_fraction=fraction, reason="fixed_target_increases_exposure"))
                continue
            if target_quantity * target_entry_price + target_fee > budget + EPS * max(1.0, abs(budget)):
                alternatives.append(dict(source_fraction=fraction, reason="fixed_target_exceeds_funding"))
                continue
        else:
            target_quantity, target_fee = funded_quantity(budget, target_entry_price, target_fees, target_product)
            # Never increase commodity exposure merely because a cheaper future
            # permits a larger fully funded quantity; keep the surplus as cash.
            if target_quantity > quantity:
                target_quantity = quantity
                target_fee = _fee(target_fees, target_product, target_quantity, target_quantity * target_entry_price)
        if target_quantity <= 0:
            alternatives.append(dict(source_fraction=fraction, reason="entry_costs_exceed_funding"))
            continue
        if target.size_btc is not None and target_quantity > target.size_btc + EPS:
            alternatives.append(dict(source_fraction=fraction, reason="target_liquidity_limit"))
            continue
        entry_cost += target_fee
        target_cash = released_cash - target_fee
        if target.symbol == "SPOT":
            target_cash -= target_quantity * target_entry_price
        for horizon in horizons:
            keep = _forecast(now_us, horizon, source.quote, quantity, source_cash,
                             source_unsettled, spot.price, cash_rate, fees, config)
            swap = _forecast(now_us, horizon, target, target_quantity, target_cash,
                             0.0, spot.price, cash_rate, fees, config,
                             entry_reference=target_entry_price)
            initial_btc = initial_whole * fraction / spot.price
            extra_cost = max(0.0, entry_cost + swap.exit_cost_usd - keep.exit_cost_usd)
            required = (initial_btc * config.uncertainty_bps / 10000 + config.min_gain_btc
                        + (config.cost_buffer_multiplier - 1) * extra_cost / spot.price)
            edge = swap.terminal_btc - keep.terminal_btc
            feasible = keep.funding_feasible and swap.funding_feasible
            accepted = feasible and edge > required + EPS * max(1.0, initial_btc)
            reason = ("net_gain_exceeds_buffer" if accepted else
                      "forecast_funding_shortfall" if not feasible else "keep_net_gain_below_buffer")
            alternatives.append(dict(source_fraction=fraction, horizon_us=horizon,
                                     keep_btc=keep.terminal_btc, swap_btc=swap.terminal_btc,
                                     edge_btc=edge, required_edge_btc=required, reason=reason))
            diagnostics = dict(
                forecast_model="flat_spot_linear_residual_basis_to_configured_reference",
                payoff_model="linear_usd_price_proxy", cash_model="cash_interest_proxy",
                cash_rate=cash_rate, cash_accrual="exp(rate * elapsed_years_365)",
                settlement_model="scheduled_latest_trade_proxy",
                settlement_interval_seconds=config.settlement_interval_seconds,
                settlement_basis_bps=config.settlement_basis_bps,
                source_quote=asdict(source.quote), target_quote=asdict(target), spot_quote=asdict(spot),
                initial_btc=initial_btc, initial_capital_usd=initial_btc * spot.price,
                source_sale_limit=source_exit_price, target_buy_limit=target_entry_price,
                target_cash_usd=target_cash, cash_reserve_usd=max(0.0, released_cash - budget),
                residual_source_quantity_btc=source.quantity_btc - quantity,
                exposure_quantity_change_btc=target_quantity - quantity,
                source_unsettled_pnl_usd=source_unsettled,
                keep=asdict(keep), swap=asdict(swap),
                uncertainty_bps=config.uncertainty_bps,
                incremental_future_cost_usd=extra_cost,
                costs_already_deducted_once=True,
                fixed_target_quantity_btc=target_quantity_btc,
                execution_price_overrides=dict(execution_price_overrides),
                fixed_comparison_horizon_us=comparison_horizon_us,
                marginal_entry_tickets=sorted(entry_fees),
                half_spread_bps=config.half_spread_bps, slippage_bps=config.slippage_bps,
                proxy_expense_rate=config.proxy_expense_rate,
                break_even_method="linearized_forecast_screen_not_guaranteed",
                projected_break_even_days=((horizon - now_us) / DAY_US * extra_cost / (edge * spot.price + extra_cost)
                                          if edge * spot.price + extra_cost > 0 else None),
                horizon_limit_us=end,
                liquidity_assumption=("displayed_quantity_limit" if target.size_btc is not None
                                      else "tape_participation_no_observed_depth"),
            )
            candidate = TransferDecision(accepted, reason, **base,
                source_quantity_btc=quantity, target_quantity_btc=target_quantity,
                source_cash_usd=source_cash, entry_cost_usd=entry_cost,
                horizon_us=horizon, keep_btc=keep.terminal_btc, swap_btc=swap.terminal_btc,
                edge_btc=edge, required_edge_btc=required, source_fraction=fraction,
                diagnostics=diagnostics)
            # Admissibility first; maximize absolute incremental BTC, then surplus.
            rank = (accepted, feasible, edge, edge - required)
            if best is None or rank > best[0]:
                best = (rank, candidate)
    if best is None:
        reasons = {row["reason"] for row in alternatives}
        reason = next(iter(reasons)) if target_quantity_btc is not None and len(reasons) == 1 else "no_feasible_size"
        return reject(reason, diagnostics={"alternatives": alternatives})
    decision = best[1]
    return TransferDecision(**{**asdict(decision),
        "diagnostics": {**decision.diagnostics, "alternatives": alternatives,
                        "evaluated_sizes": len(config.size_fractions), "evaluated_horizons": len(horizons)}})


def _execution_outcome_forecast(now_us, horizon_us, source, target, spot, *,
                                target_quantity, outcome, deadline_seconds,
                                budget_bps, cash_rate, fees, config):
    """Value a sampled joint path and its bounded spot-restoration fallback.

    Study representatives retain VWAPs and quantity-weighted fill times, not
    individual fills. Entry cash flows therefore occur at those mean times;
    pre-deadline variation is carried to the deadline. This approximation is
    explicit in the caller's audit. A path exceeding the authorized print-price
    budget cannot be treated as a fill outside the limit: use the adverse funded
    source-sale/no-hedge/restoration branch instead.
    """
    quantity = source.quantity_btc
    source_fraction = float(outcome.get("source_fill_fraction", 0))
    target_fraction = float(outcome.get("target_fill_fraction", 0))
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in (source_fraction, target_fraction)):
        raise ValueError("Execution fill fractions must be in [0, 1]")
    limit = budget_bps / 10000
    # The study records modeled execution prices, including configured spread
    # and slippage. Applying those adjustments here again would double-charge.
    administrative_censor = outcome.get("administratively_censored", bool(outcome.get("censored"))
        and outcome.get("censor_reason") not in ("waiting_deadline", "contract_expired"))
    tail = bool(administrative_censor) or float(outcome.get("max_adverse_budget_bps") or 0) > budget_bps + 1e-9
    if tail:
        source_fraction, target_fraction = 1.0, 0.0
        source_price = spot.price * (1 - limit)
    else:
        source_ratio = float(outcome.get("source_vwap_ratio") or 1.0)
        target_ratio = float(outcome.get("target_vwap_ratio") or 1.0)
        if not all(math.isfinite(v) and v > 0 for v in (source_ratio, target_ratio)):
            raise ValueError("Execution price ratios must be positive and finite")
        source_price = spot.price * source_ratio
    sold = quantity * source_fraction
    # Historical target capacity is measured against the study's SAME source
    # quantity; the new funded target quantity is often smaller. Never claim
    # more fill capacity than observed, or hedge unfilled source inventory.
    hedged = (min(target_quantity, quantity * target_fraction)
              if source_fraction >= 1 - 1e-10 else 0.0)
    target_price = target.price * (float(outcome.get("target_vwap_ratio") or 1.0))
    target_prefix_bound = hedged > EPS and hedged < quantity * target_fraction - EPS
    if target_prefix_bound:
        # A smaller funded hedge consumes an unknown prefix of the study's
        # larger hedge. Its full VWAP can be cheaper than that prefix. The worst
        # observed target price (or authorized cap) is a conservative cost bound.
        worst = outcome.get("worst_future_adverse_bps")
        worst = budget_bps if worst is None else max(0.0, float(worst))
        target_price = target.price * (1 + worst / 10000)
    if not tail and (source_price + EPS < spot.price * (1 - limit) or
                     target_price > target.price * (1 + limit) + EPS):
        raise ValueError("Execution outcome contradicts its within-budget label")
    deadline_us = now_us + round(deadline_seconds * 1e6)
    if deadline_us >= horizon_us:
        raise ValueError("Execution deadline must precede the holding horizon")
    growth = lambda seconds: math.exp(cash_rate * seconds / (365 * 86400))
    elapsed = (horizon_us - now_us) / YEAR_US
    if sold <= EPS:
        keep = _forecast(now_us, horizon_us, source.quote, quantity, source.cash_usd,
                         source.unsettled_pnl_usd, spot.price, cash_rate, fees, config)
        return dict(terminal_btc=keep.terminal_btc, funding_feasible=keep.funding_feasible,
                    source_filled_btc=0.0, target_filled_btc=0.0, restored_spot_btc=0.0,
                    entry_and_restore_fees_usd=0.0, tail_fallback=tail)
    source_delay = min(deadline_seconds, max(0.0, float(outcome.get("source_fill_delay_seconds") or 0)))
    if tail:
        source_delay = deadline_seconds if cash_rate >= 0 else 0.0
    target_delay = min(deadline_seconds, max(source_delay, float(outcome.get("target_fill_delay_seconds") or source_delay)))
    source_fee = _fee(fees, "spot", sold, sold * source_price)
    net_proceeds = max(0.0, sold * source_price - source_fee)
    # A representative path must still respect full funding at its own prices.
    affordable, _ = funded_quantity(net_proceeds * (1 - config.cash_reserve_fraction),
                                     target_price, fees, "futures")
    hedged = min(hedged, affordable)
    target_fee = _fee(fees, "futures", hedged, hedged * target_price)
    cash = (source.cash_usd * growth(deadline_seconds)
            + net_proceeds * growth(deadline_seconds - source_delay)
            - target_fee * growth(deadline_seconds - target_delay))
    matched_source = hedged / (target_quantity / quantity) if target_quantity > 0 else 0.0
    unmatched = max(0.0, sold - matched_source)
    # Spot restoration uses only unmatched net sale proceeds and actual free
    # funds; it may buy fewer BTC after price movement and another commission.
    restoration_budget = min(max(0.0, cash - hedged * target_price),
                             net_proceeds * unmatched / sold)
    restore_ratio = float(outcome.get("deadline_spot_ratio") or 1.0)
    if not math.isfinite(restore_ratio) or restore_ratio <= 0:
        raise ValueError("Deadline spot ratio must be positive and finite")
    restore_pad = max(budget_bps, config.price_limit_bps) / 10000
    restore_price = spot.price * restore_ratio * (1 + restore_pad)
    restored, restore_fee = funded_quantity(restoration_budget, restore_price, fees, "spot")
    restored = min(restored, unmatched)
    restore_fee = _fee(fees, "spot", restored, restored * restore_price)
    cash_without_restoration = cash
    cash -= restored * restore_price + restore_fee
    at_deadline = replace(target, price=_projected_price(target, spot.price, deadline_us, now_us, config),
                          source_us=deadline_us, available_us=deadline_us)
    remaining_spot = ((quantity - sold) * math.exp(-config.proxy_expense_rate * elapsed)
                      + restored * math.exp(-config.proxy_expense_rate * (horizon_us - deadline_us) / YEAR_US))
    if hedged > EPS:
        after = _forecast(deadline_us, horizon_us, at_deadline, hedged, cash, 0.0,
                          spot.price, cash_rate, fees, config, entry_reference=target_price)
    else:
        after = _forecast(deadline_us, horizon_us, spot, 0.0, cash, 0.0,
                          spot.price, cash_rate, fees, config)
    terminal = remaining_spot + after.terminal_btc
    if unmatched > EPS:
        # Restoration has no measured second-stage liquidity distribution yet.
        # Do not credit BTC gains that depend on an assumed cheap repurchase:
        # use the lower wealth of cap-priced restoration and retained cash.
        no_restore = _forecast(deadline_us, horizon_us, at_deadline if hedged > EPS else spot,
            hedged if hedged > EPS else 0.0, cash_without_restoration, 0.0,
            spot.price, cash_rate, fees, config,
            **({"entry_reference": target_price} if hedged > EPS else {}))
        without_restore = ((quantity - sold) * math.exp(-config.proxy_expense_rate * elapsed)
                           + no_restore.terminal_btc)
        if without_restore < terminal:
            terminal, restored, restore_fee = without_restore, 0.0, 0.0
    if tail:
        # A clipped historical path does not reveal the exact limit-order
        # prefix. Its conservative proxy cannot earn a profit from a fictitious
        # full sale followed by a cheaper repurchase on a path that never filled.
        keep = _forecast(now_us, horizon_us, source.quote, quantity, source.cash_usd,
                         source.unsettled_pnl_usd, spot.price, cash_rate, fees, config)
        terminal = min(terminal, keep.terminal_btc)
    return dict(terminal_btc=terminal,
                funding_feasible=after.funding_feasible,
                source_filled_btc=sold, target_filled_btc=hedged,
                restored_spot_btc=restored,
                entry_and_restore_fees_usd=source_fee + target_fee + restore_fee,
                tail_fallback=tail, target_prefix_cost_bound=target_prefix_bound)


def evaluate_transfer_with_execution(now_us, source, target, spot, *, cash_rate,
                                     execution_model, fees=None, config=None,
                                     deadline_seconds=30.0, required_joint_probability=.95,
                                     candidate_quantities_btc=(.0001, .001, .01, .1),
                                     min_samples=30, horizon_limit_us=None,
                                     comparison_horizon_us=None, entry_fees=None,
                                     target_quantity_btc=None):
    """Select a calibrated small transfer using ALL empirical execution outcomes.

    Empirical adverse-price allowance affects entry prices only. Size the target
    at those funded prices BEFORE fixing its source/target ratio; keep reserve,
    commissions and terminal execution costs separate. ``edge_btc`` is the
    weighted expected edge including misses and bounded restoration; diagnostics
    retain the distinct conservative all-filled budget edge. Model labels must
    be available strictly before this decision. Other routes fail closed.
    """
    config = config or EconomicsConfig()
    base = dict(source_symbol=source.quote.symbol, target_symbol=target.symbol)
    reject = lambda reason, **extra: TransferDecision(False, reason, **base, **extra)
    if source.quote.symbol != "SPOT" or target.symbol == "SPOT":
        return reject("empirical_execution_route_unsupported")
    if (not math.isfinite(deadline_seconds) or deadline_seconds <= 0 or
            not math.isfinite(required_joint_probability) or not 0 < required_joint_probability <= 1):
        return reject("invalid_execution_forecast_settings")
    if entry_fees:
        # Existing tickets are rechecked by the execution controller at their
        # approved ratio/caps; fresh-study sizing must not erase sunk fills.
        return reject("empirical_forecast_requires_new_ticket")
    for product in ("spot", "futures"):
        schedule = (fees or {}).get(product)
        if schedule is not None and any(getattr(schedule, key, 0) for key in ("fixed", "minimum", "per_unit")):
            return reject("empirical_nonproportional_fees_unsupported")
    if isinstance(execution_model, dict):
        from paired_execution_study import FrozenExecutionModel
        execution_model = FrozenExecutionModel.from_dict(execution_model)
    if execution_model is None or not hasattr(execution_model, "forecast"):
        return reject("execution_model_unavailable")
    maximum = source.quantity_btc * config.max_transfer_fraction
    if source.quote.size_btc is not None:
        maximum = min(maximum, source.quote.size_btc)
    if target.size_btc is not None:
        maximum = min(maximum, target.size_btc)
    quantities = sorted({float(q) for q in candidate_quantities_btc
                         if math.isfinite(float(q)) and 0 < float(q) <= maximum + EPS})
    if not quantities:
        return reject("no_calibrated_execution_size")
    cfg = replace(config, max_transfer_fraction=1.0, size_fractions=(1.0,))
    candidates, failures = [], []
    for quantity in quantities:
        model = execution_model.forecast(target.symbol, target.expiry_us, now_us,
            quantity, deadline_seconds, required_joint_probability, min_samples)
        if not model.get("available", False):
            failures.append(dict(quantity_btc=quantity, reason=model.get("reason", "execution_forecast_unavailable")))
            continue
        cutoff = model.get("label_cutoff_us")
        if not isinstance(cutoff, int) or cutoff >= now_us:
            failures.append(dict(quantity_btc=quantity, reason="execution_model_not_causal"))
            continue
        budget = float(model.get("budget_bps", math.nan))
        probability = float(model.get("all_outcome_probability", 0))
        if (not math.isfinite(budget) or not 0 <= budget < 10000 or
                not math.isfinite(probability) or not required_joint_probability <= probability <= 1):
            failures.append(dict(quantity_btc=quantity, reason="execution_joint_confidence_unattainable"))
            continue
        outcomes = model.get("outcomes", [])
        weights = [float(row.get("weight", 0)) for row in outcomes]
        if (not outcomes or any(not math.isfinite(w) or w < 0 for w in weights) or
                not math.isclose(sum(weights), 1.0, rel_tol=0, abs_tol=1e-8)):
            failures.append(dict(quantity_btc=quantity, reason="invalid_execution_outcome_weights"))
            continue
        if any(not math.isclose(float(row.get("requested_source_btc", quantity)), quantity,
                                rel_tol=1e-9, abs_tol=1e-12) for row in outcomes):
            failures.append(dict(quantity_btc=quantity, reason="execution_quantity_not_calibrated"))
            continue
        source_floor = source.quote.price * (1 - budget / 10000)
        target_cap = target.price * (1 + budget / 10000)
        fraction = quantity / source.quantity_btc
        slice_ = replace(source, quantity_btc=quantity, cash_usd=source.cash_usd * fraction,
                         unsettled_pnl_usd=source.unsettled_pnl_usd * fraction)
        initial = evaluate_transfer(now_us, slice_, target, spot, cash_rate=cash_rate,
            fees=fees, config=cfg, horizon_limit_us=horizon_limit_us,
            target_quantity_btc=(target_quantity_btc * fraction if target_quantity_btc is not None else None),
            execution_price_overrides={"source": source_floor, "target": target_cap},
            comparison_horizon_us=comparison_horizon_us)
        metadata = {**{key: model.get(key) for key in ("model_id", "calibration_end_us", "label_cutoff_us",
            "samples", "scope", "scenario_approximation")}, **model.get("metadata", {})}

        def skipped_expected(conservative):
            """A failed mandatory gate cannot be rescued by expected outcomes."""
            feasible = (conservative.diagnostics.get("keep", {}).get("funding_feasible", False)
                        and conservative.diagnostics.get("swap", {}).get("funding_feasible", False))
            return replace(conservative, accepted=False, source_fraction=fraction,
                reason=("empirical_conservative_gain_below_buffer" if feasible
                        else "empirical_forecast_funding_shortfall"),
                diagnostics={**conservative.diagnostics,
                    "execution_model": metadata, "execution_budget_bps": budget,
                    "execution_deadline_seconds": deadline_seconds,
                    "execution_joint_success_probability": probability,
                    "execution_completion_probability": model.get("completion_probability"),
                    "execution_scenario_count": len(outcomes),
                    "execution_expected_evaluation": "skipped_conservative_rejection",
                    "execution_expected_value_kind": "not_evaluated",
                    "execution_decision_edge_kind": "conservative_budget_edge",
                    "expected_edge_btc": None, "expected_swap_btc": None,
                    "conservative_budget_edge_btc": conservative.edge_btc,
                    "conservative_budget_swap_btc": conservative.swap_btc,
                    "calibrated_source_quantity_btc": quantity,
                    "residual_source_quantity_btc": source.quantity_btc - quantity,
                    "execution_budget_applied_to": "entry_only",
                    "execution_price_adjustments_included": True})

        # evaluate_transfer ranks acceptance before gain, so a rejected best
        # candidate proves EVERY horizon at this exact size failed the required
        # conservative gate. No empirical scenario can change that decision.
        alternatives = initial.diagnostics.get("alternatives", [])
        all_horizons = {row["horizon_us"] for row in alternatives if "horizon_us" in row}
        horizons = sorted(h for h in all_horizons if h > now_us + round(deadline_seconds * 1e6))
        if not horizons:
            failures.append(dict(quantity_btc=quantity,
                reason="no_feasible_execution_horizon" if all_horizons else initial.reason))
            continue
        if not initial.accepted:
            if initial.horizon_us not in horizons:
                selected_horizon = max((row for row in alternatives if row.get("horizon_us") in horizons),
                                       key=lambda row: row.get("edge_btc", -math.inf))["horizon_us"]
                initial = evaluate_transfer(now_us, slice_, target, spot, cash_rate=cash_rate,
                    fees=fees, config=cfg, horizon_limit_us=horizon_limit_us,
                    target_quantity_btc=initial.target_quantity_btc,
                    execution_price_overrides={"source": source_floor, "target": target_cap},
                    comparison_horizon_us=selected_horizon)
            if initial.horizon_us is not None:
                candidates.append(skipped_expected(initial))
            else:
                failures.append(dict(quantity_btc=quantity, reason=initial.reason))
            continue
        for horizon in horizons:
            if horizon <= now_us + round(deadline_seconds * 1e6):
                continue
            conservative = initial if initial.horizon_us == horizon else evaluate_transfer(
                now_us, slice_, target, spot, cash_rate=cash_rate, fees=fees, config=cfg,
                horizon_limit_us=horizon_limit_us,
                target_quantity_btc=initial.target_quantity_btc,
                execution_price_overrides={"source": source_floor, "target": target_cap},
                comparison_horizon_us=horizon)
            if not conservative.accepted:
                candidates.append(skipped_expected(conservative))
                continue
            forecast_rows = []
            try:
                for row in outcomes:
                    forecast_rows.append(_execution_outcome_forecast(now_us, horizon, slice_, target, spot,
                        target_quantity=conservative.target_quantity_btc, outcome=row,
                        deadline_seconds=deadline_seconds, budget_bps=budget,
                        cash_rate=cash_rate, fees=fees, config=cfg))
            except (ValueError, TypeError, OverflowError):
                failures.append(dict(quantity_btc=quantity, reason="invalid_execution_outcome"))
                continue
            expected = sum(w * row["terminal_btc"] for w, row in zip(weights, forecast_rows))
            edge = expected - conservative.keep_btc
            feasible = (conservative.diagnostics.get("keep", {}).get("funding_feasible", False)
                        and conservative.diagnostics.get("swap", {}).get("funding_feasible", False)
                        and all(row["funding_feasible"] for row in forecast_rows))
            accepted = (feasible and conservative.accepted and
                        edge > conservative.required_edge_btc + EPS * max(1.0, conservative.diagnostics.get("initial_btc", 0)))
            diagnostics = {**conservative.diagnostics,
                "execution_model": metadata, "execution_budget_bps": budget,
                "execution_deadline_seconds": deadline_seconds,
                "execution_joint_success_probability": probability,
                "execution_completion_probability": model.get("completion_probability"),
                "execution_scenario_count": len(outcomes),
                "execution_scenario_approximation": "weighted_source_VWAP_mean_fill_time; smaller_hedge_prefix_at_worst_fill_price; pre_deadline_variation_at_deadline; min_restore_or_cash_wealth; adverse_tail_capped_at_KEEP",
                "execution_expected_value_kind": "conservative_weighted_empirical_estimate",
                "execution_expected_evaluation": "evaluated",
                "execution_decision_edge_kind": "conservative_weighted_empirical_estimate",
                "execution_target_prefix_bound_probability": sum(w for w, row in zip(weights, forecast_rows) if row.get("target_prefix_cost_bound")),
                "expected_edge_btc": edge, "expected_swap_btc": expected,
                "conservative_budget_edge_btc": conservative.edge_btc,
                "conservative_budget_swap_btc": conservative.swap_btc,
                "expected_entry_and_restore_fees_usd": sum(w * row["entry_and_restore_fees_usd"] for w, row in zip(weights, forecast_rows)),
                "expected_source_filled_btc": sum(w * row["source_filled_btc"] for w, row in zip(weights, forecast_rows)),
                "expected_target_filled_btc": sum(w * row["target_filled_btc"] for w, row in zip(weights, forecast_rows)),
                "expected_restored_spot_btc": sum(w * row["restored_spot_btc"] for w, row in zip(weights, forecast_rows)),
                "execution_tail_fallback_probability": sum(w for w, row in zip(weights, forecast_rows) if row["tail_fallback"]),
                "calibrated_source_quantity_btc": quantity,
                "residual_source_quantity_btc": source.quantity_btc - quantity,
                "execution_budget_applied_to": "entry_only", "source_sale_limit": source_floor,
                "execution_price_adjustments_included": True,
                "target_buy_limit": target_cap}
            reason = ("empirical_expected_net_gain_exceeds_buffer" if accepted else
                      "empirical_forecast_funding_shortfall" if not feasible else
                      "empirical_conservative_gain_below_buffer" if not conservative.accepted else
                      "empirical_expected_gain_below_buffer")
            candidates.append(replace(conservative, accepted=accepted, reason=reason,
                swap_btc=expected, edge_btc=edge, source_fraction=fraction, diagnostics=diagnostics))
    if not candidates:
        return reject(failures[-1]["reason"] if failures else "no_feasible_execution_horizon",
                      diagnostics={"execution_candidate_failures": failures})
    best = max(candidates, key=lambda item: (item.accepted, item.edge_btc))
    return replace(best, diagnostics={**best.diagnostics, "execution_candidate_failures": failures,
        "execution_candidates_evaluated": len(candidates)})
