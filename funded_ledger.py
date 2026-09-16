"""Self-financing, fully funded USD-linear ledger for paired-transfer research.

This is deliberately separate from ``trade_replay.TapeAccount``. Trade marks
value a position; they do not make its unrealized profit spendable. Native
inverse contracts, borrowing and short positions fail closed. Synthetic bonds
and interest on cash are explicit research assumptions, never actual securities.
"""
from dataclasses import asdict, dataclass
import math


YEAR_SECONDS = 365 * 86400
EPS = 1e-9


class FundingError(ValueError):
    """An instruction cannot be financed without borrowing/outside cash."""


def _number(value, name, minimum=None):
    value = float(value)
    if not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError(f"{name} must be finite" + (f" and >= {minimum}" if minimum is not None else ""))
    return value


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    multiplier: float = 1.0
    payoff: str = "linear"
    currency: str = "USD"
    proxy_label: str = "USD-linear research proxy"

    def __post_init__(self):
        if not self.symbol or self.symbol == "SPOT":
            raise ValueError("A distinct futures symbol is required")
        multiplier = _number(self.multiplier, "multiplier", 0)
        if multiplier == 0:
            raise ValueError("multiplier must be positive")
        object.__setattr__(self, "multiplier", multiplier)
        if self.payoff != "linear" or self.currency != "USD":
            raise ValueError("Only USD-linear payoff/collateral is modeled; native inverse is unsupported")


@dataclass(frozen=True)
class FeeSchedule:
    fee_bps: float = 0.0
    per_unit: float = 0.0
    fixed: float = 0.0
    minimum: float = 0.0
    cap: float | None = None
    currency: str = "USD"

    def __post_init__(self):
        for name in ("fee_bps", "per_unit", "fixed", "minimum"):
            object.__setattr__(self, name, _number(getattr(self, name), name, 0))
        if self.cap is not None:
            object.__setattr__(self, "cap", _number(self.cap, "cap", self.minimum))
        if self.currency != "USD":
            raise ValueError("Non-USD commission requires an explicit causal FX model")

    def total_fee(self, quantity, notional):
        quantity = _number(quantity, "filled quantity", 0)
        notional = _number(notional, "filled notional", 0)
        if quantity == 0:
            if notional:
                raise ValueError("Zero fills cannot have filled notional")
            return 0.0
        fee = max(self.minimum, self.fixed + self.per_unit * quantity + self.fee_bps * notional / 10000)
        return min(fee, self.cap) if self.cap is not None else fee


class FeeEngine:
    """Cumulative order-ticket charging; cancellation does not erase history."""

    def __init__(self, schedules=None):
        self.schedules = {key: (value if isinstance(value, FeeSchedule) else FeeSchedule(**value))
                          for key, value in (schedules or {}).items()}
        self.tickets = {}

    def estimate(self, product, ticket_id, quantity, notional):
        if not ticket_id:
            raise ValueError("A durable commission ticket ID is required")
        quantity, notional = abs(_number(quantity, "quantity")), abs(_number(notional, "notional"))
        schedule = self.schedules.get(product, FeeSchedule())
        old = self.tickets.get(str(ticket_id))
        if old and (old["product"] != product or old["schedule"] != asdict(schedule)):
            raise ValueError("A fee ticket cannot change its product or fee schedule")
        if quantity == 0:
            if notional:
                raise ValueError("Zero fills cannot have filled notional")
            return 0.0
        total = schedule.total_fee(quantity + (old["quantity"] if old else 0),
                                   notional + (old["notional"] if old else 0))
        return max(0.0, total - (old["charged"] if old else 0))

    def charge(self, product, ticket_id, quantity, notional):
        quantity, notional = abs(quantity), abs(notional)
        increment = self.estimate(product, ticket_id, quantity, notional)
        if quantity == 0:
            return 0.0
        key = str(ticket_id)
        old = self.tickets.get(key, {"product": product, "schedule": asdict(self.schedules.get(product, FeeSchedule())),
                                     "quantity": 0.0, "notional": 0.0, "charged": 0.0})
        self.tickets[key] = dict(old, quantity=old["quantity"] + quantity,
                                 notional=old["notional"] + notional, charged=old["charged"] + increment)
        return increment

    def snapshot(self):
        return {"schedules": {key: asdict(value) for key, value in self.schedules.items()},
                "tickets": {key: dict(value, schedule=dict(value["schedule"])) for key, value in self.tickets.items()}}

    @classmethod
    def restore(cls, state):
        engine = cls(state["schedules"])
        engine.tickets = {key: dict(value, schedule=dict(value["schedule"])) for key, value in state["tickets"].items()}
        return engine


@dataclass
class FutureLot:
    quantity: float
    reference_price: float


@dataclass
class TreasuryLot:
    """Synthetic zero coupon, simple-yield discount; price is USD per face USD."""
    face: float
    remaining_seconds: float
    annual_rate: float
    price: float
    haircut: float = 0.0
    tradable: bool = True
    settlement_lag_seconds: float = 0.0
    label: str = "synthetic zero-coupon Treasury proxy"

    @property
    def market_value(self):
        return self.face * self.price


class FundedLedger:
    """Long-only, full-notional funding with cash and optional synthetic bonds.

    Free/posted cash is an internal segregation, not a second asset. All cash
    belongs to one USD venue/account and posted cash can pay that venue's VM.
    No historical margin schedule, repo, FX, settlement calendar or borrowing is
    inferred. Reservations are cash-only; known unpaid debits block new risk.
    """

    VERSION = 1

    def __init__(self, initial_cash_usd, fee_schedules=None, cash_interest_proxy=False, sink=None):
        self.initial = _number(initial_cash_usd, "initial cash", 0)
        self.free_cash_usd, self.posted_cash_usd = self.initial, 0.0
        self.spot_quantity = 0.0
        self.marks, self.mark_metadata, self.contracts, self.lots = {}, {}, {}, {}
        self.treasuries, self.reservations, self.pending_variation = {}, {}, {}
        self.expired = set()
        self.liabilities_usd = 0.0  # borrowing is deliberately disabled
        self.fees = self.interest = self.market_pnl = self.turnover = 0.0
        self.custody_expenses = 0.0
        self.funding_sale_count = self.fill_count = self.settlement_sequence = 0
        self.cash_interest_proxy = bool(cash_interest_proxy)
        self.fee_engine = FeeEngine(fee_schedules)
        self.sink = sink or (lambda row: None)

    @property
    def units(self):
        return {"SPOT": self.spot_quantity, **{key: sum(lot.quantity for lot in lots) for key, lots in self.lots.items()}}

    @property
    def cash(self):
        return self.free_cash_usd + self.posted_cash_usd

    @property
    def treasury_value(self):
        return sum(lot.market_value for lot in self.treasuries.values())

    @property
    def treasury_collateral(self):
        return sum(lot.market_value * (1 - lot.haircut) for lot in self.treasuries.values())

    def unrealized_pnl_usd(self, symbol=None):
        return sum(lot.quantity * self.contracts[key].multiplier * (self.marks[key] - lot.reference_price)
                   for key, lots in self.lots.items() if symbol is None or key == symbol for lot in lots)

    @property
    def nav(self):
        return (self.cash + self.treasury_value + self.spot_quantity * self.marks.get("SPOT", 0)
                + self.unrealized_pnl_usd() + sum(item["amount_usd"] for item in self.pending_variation.values())
                - self.liabilities_usd)

    @property
    def collateral(self):
        """Full-notional policy requirement, not a separate asset in NAV."""
        return sum(sum(lot.quantity for lot in lots) * self.contracts[key].multiplier * self.marks[key]
                   for key, lots in self.lots.items())

    @property
    def margin_excess(self):
        pending_debits = sum(min(0.0, row["amount_usd"]) for row in self.pending_variation.values())
        return self.cash + self.treasury_collateral + self.unrealized_pnl_usd() + pending_debits - self.collateral

    @property
    def available_cash(self):
        return max(0.0, min(self.free_cash_usd, self.margin_excess) - sum(self.reservations.values()))

    @property
    def funding_blocked(self):
        return self.margin_excess < -EPS or any(row["amount_usd"] < -EPS for row in self.pending_variation.values())

    def _emit(self, kind, **details):
        self.sink({"kind": kind, **details, "free_cash_usd": self.free_cash_usd,
                   "posted_cash_usd": self.posted_cash_usd, "unsettled_pnl_usd": self.unrealized_pnl_usd(),
                   "nav_usd": self.nav, "collateral_usd": self.collateral})

    def _rebalance_posted(self):
        needed = max(0.0, self.collateral - self.treasury_collateral - self.unrealized_pnl_usd())
        total = self.cash
        self.posted_cash_usd = min(total, needed)
        self.free_cash_usd = total - self.posted_cash_usd

    def register_contract(self, spec):
        if not isinstance(spec, ContractSpec):
            raise TypeError("An explicit ContractSpec is required")
        if spec.symbol in self.contracts and self.contracts[spec.symbol] != spec:
            raise ValueError("Cannot redefine an existing contract")
        self.contracts[spec.symbol] = spec

    def initialize_spot(self, quantity, price):
        quantity, price = _number(quantity, "quantity", 0), _number(price, "price", 0)
        if price <= 0 or self.fill_count or self.spot_quantity or self.lots or self.treasuries:
            raise ValueError("Spot endowment is permitted only before trading, at a positive price")
        if quantity * price > self.cash + EPS:
            raise FundingError("Initial spot endowment exceeds capital")
        self.free_cash_usd -= quantity * price
        self.spot_quantity = quantity
        self.marks["SPOT"] = price
        self.mark_metadata["SPOT"] = {"timestamp_us": None, "source": "initial endowment"}
        self._emit("initial_endowment", quantity=quantity, price=price)

    def mark(self, symbol, price, timestamp_us=None, source="trade_mark_proxy"):
        price = _number(price, "mark price", 0)
        if symbol != "SPOT" and symbol not in self.contracts:
            raise ValueError("Contract must be registered before valuation")
        old = self.marks.get(symbol, price)
        quantity = self.spot_quantity if symbol == "SPOT" else self.units.get(symbol, 0) * self.contracts[symbol].multiplier
        self.market_pnl += quantity * (price - old)
        self.marks[symbol] = price
        self.mark_metadata[symbol] = {"timestamp_us": timestamp_us, "source": source}
        self._rebalance_posted()
        self._emit("valuation_mark", symbol=symbol, price=price, timestamp_us=timestamp_us, source=source)

    def reserve(self, reservation_id, amount_usd):
        amount = _number(amount_usd, "reservation", 0)
        if not reservation_id:
            raise ValueError("A durable reservation ID is required")
        old = self.reservations.get(str(reservation_id), 0)
        if amount > self.available_cash + old + EPS:
            raise FundingError("Reservation exceeds unencumbered immediately available cash")
        self.reservations[str(reservation_id)] = amount
        self._emit("collateral_reservation", reservation_id=str(reservation_id), amount_usd=amount)

    def release(self, reservation_id):
        amount = self.reservations.pop(str(reservation_id), 0.0)
        self._emit("collateral_release", reservation_id=str(reservation_id), amount_usd=amount)
        return amount

    def _consume_reservation(self, reservation_id, amount):
        if reservation_id is not None and str(reservation_id) in self.reservations:
            key = str(reservation_id)
            consumed = min(self.reservations[key], max(0.0, amount))
            self.reservations[key] -= consumed
            if self.reservations[key] <= EPS:
                self.reservations.pop(key)
            self._emit("collateral_release", reservation_id=key, amount_usd=consumed, reason="filled")

    def estimate_fee(self, product, ticket_id, quantity, notional):
        return self.fee_engine.estimate(product, ticket_id, quantity, notional)

    def _charge_fee(self, product, ticket_id, quantity, notional):
        fee = self.fee_engine.charge(product, ticket_id, quantity, notional)
        self.fees += fee
        if fee:
            self._emit("commission_charge", product=product, ticket_id=str(ticket_id), amount_usd=fee)
        return fee

    def _funding_plan(self, debit, ticket_prefix):
        """Plan immediate bond sales without mutating anything on rejection."""
        needed = max(0.0, debit - self.cash)
        plan = []
        for key, lot in self.treasuries.items():
            if needed <= EPS:
                break
            if not lot.tradable or lot.settlement_lag_seconds > 0 or lot.price <= 0:
                continue
            ticket = f"{ticket_prefix}:funding:{key}"
            max_fee = self.estimate_fee("treasury", ticket, lot.face, lot.market_value)
            available = lot.market_value - max_fee
            if available <= 0:
                continue
            face = lot.face
            if available > needed:
                low, high = 0.0, lot.face
                for _ in range(64):
                    middle = (low + high) / 2
                    net = middle * lot.price - self.estimate_fee("treasury", ticket, middle, middle * lot.price)
                    if net >= needed:
                        high = middle
                    else:
                        low = middle
                face = high
            fee = self.estimate_fee("treasury", ticket, face, face * lot.price)
            plan.append((key, face, fee, ticket))
            needed -= face * lot.price - fee
        if needed > EPS:
            raise FundingError("Payment lacks cash or immediately realizable Treasury proceeds; borrowing disabled")
        return plan

    def _apply_funding(self, plan):
        for key, face, fee, ticket in plan:
            lot = self.treasuries[key]
            value = face * lot.price
            lot.face -= face
            self.free_cash_usd += value - fee
            self._charge_fee("treasury", ticket, face, value)
            self.funding_sale_count += 1
            if lot.face <= EPS:
                self.treasuries.pop(key)
            self._emit("treasury_fill", lot_id=key, signed_face=-face, price=lot.price,
                       ticket_id=ticket, reason="cash funding")

    def _debit(self, amount):
        if amount < 0:
            self.free_cash_usd -= amount
            return
        take = min(self.free_cash_usd, amount)
        self.free_cash_usd -= take
        self.posted_cash_usd -= amount - take
        if self.posted_cash_usd < -EPS:
            raise AssertionError("Preflight funding invariant violated")
        self.posted_cash_usd = max(0.0, self.posted_cash_usd)

    def _preflight(self, capacity_delta, debit, ticket_id, reservation_id, increasing_risk):
        if increasing_risk and self.funding_blocked:
            raise FundingError("Known margin shortfall or unpaid variation blocks new risk")
        plan = self._funding_plan(debit, str(ticket_id))
        funding_capacity_change = sum(face * self.treasuries[key].price * self.treasuries[key].haircut - fee
                                      for key, face, fee, _ in plan)
        others = sum(value for key, value in self.reservations.items() if key != str(reservation_id))
        after = self.margin_excess + capacity_delta + funding_capacity_change
        if increasing_risk and after < others - EPS:
            raise FundingError("Insufficient full-notional collateral after costs and reservations")
        return plan

    def fill_spot(self, signed_quantity, price, ticket_id, timestamp_us=None, reservation_id=None):
        quantity, price = _number(signed_quantity, "quantity"), _number(price, "fill price", 0)
        if price <= 0:
            raise ValueError("Fill price must be positive")
        quantity_tolerance = 8 * max(math.ulp(self.spot_quantity), math.ulp(abs(quantity)))
        if self.spot_quantity + quantity < -quantity_tolerance:
            raise FundingError("Spot borrowing/short selling is disabled")
        if self.spot_quantity + quantity < 0:
            quantity = -self.spot_quantity
        if quantity == 0:
            return 0.0
        notional = abs(quantity) * price
        fee = self.estimate_fee("spot", ticket_id, abs(quantity), notional)
        debit = quantity * price + fee
        plan = self._preflight(-debit, debit, ticket_id, reservation_id, quantity > 0)
        self.mark("SPOT", price, timestamp_us, "execution")
        self._apply_funding(plan)
        self._debit(debit)
        self.spot_quantity = max(0.0, self.spot_quantity + quantity)
        self._charge_fee("spot", ticket_id, abs(quantity), notional)
        self._consume_reservation(reservation_id, max(0.0, debit))
        self.fill_count += 1
        self.turnover += notional
        self._rebalance_posted()
        self._emit("fill", symbol="SPOT", signed_quantity=quantity, price=price, fee_usd=fee,
                   ticket_id=str(ticket_id), timestamp_us=timestamp_us)
        return fee

    def close_value(self, symbol, quantity):
        quantity = _number(quantity, "close quantity", 0)
        if quantity > self.units.get(symbol, 0) + EPS:
            raise ValueError("Close quantity exceeds held position")
        return quantity * self.contracts[symbol].multiplier * self.marks[symbol]

    def _close_pnl(self, symbol, quantity, price):
        result, remaining = 0.0, quantity
        for lot in self.lots.get(symbol, []):
            take = min(remaining, lot.quantity)
            result += take * self.contracts[symbol].multiplier * (price - lot.reference_price)
            remaining -= take
            if remaining <= 0:
                break
        return result

    def _remove_lots(self, symbol, quantity):
        if quantity >= sum(lot.quantity for lot in self.lots.get(symbol, [])):
            self.lots[symbol] = []
            return
        remaining, kept = quantity, []
        for lot in self.lots.get(symbol, []):
            take = min(remaining, lot.quantity)
            lot.quantity -= take
            remaining -= take
            if lot.quantity > 0:
                kept.append(lot)
        self.lots[symbol] = kept

    def fill_future(self, symbol, signed_quantity, price, ticket_id, timestamp_us=None, reservation_id=None):
        return self._future_fill(symbol, signed_quantity, price, ticket_id, timestamp_us, reservation_id, "futures")

    def _future_fill(self, symbol, signed_quantity, price, ticket_id, timestamp_us, reservation_id, product):
        if symbol not in self.contracts or symbol in self.expired:
            raise ValueError("An unexpired, explicitly registered contract is required")
        quantity, price = _number(signed_quantity, "quantity"), _number(price, "fill price", 0)
        if price == 0 and product != "delivery":
            raise ValueError("Execution price must be positive")
        held = self.units.get(symbol, 0)
        quantity_tolerance = 8 * max(math.ulp(held), math.ulp(abs(quantity)))
        if held + quantity < -quantity_tolerance:
            raise FundingError("Short futures/leverage is disabled")
        if held + quantity < 0:
            quantity = -held
        if quantity == 0:
            return 0.0
        multiplier = self.contracts[symbol].multiplier
        notional = abs(quantity) * multiplier * price
        fee = self.estimate_fee(product, ticket_id, abs(quantity), notional)
        realized = self._close_pnl(symbol, -quantity, price) if quantity < 0 else 0.0
        # Existing mark movement cancels between marked exposure and U in the
        # fully funded linear-long collateral test.
        capacity_delta = -quantity * multiplier * price - fee
        plan = self._preflight(capacity_delta, fee - realized, ticket_id, reservation_id, quantity > 0)
        self.mark(symbol, price, timestamp_us, "delivery" if product == "delivery" else "execution")
        self._apply_funding(plan)
        self._debit(fee - realized)
        if quantity < 0:
            self._remove_lots(symbol, -quantity)
        else:
            lots = self.lots.setdefault(symbol, [])
            if lots and lots[-1].reference_price == price:
                lots[-1].quantity += quantity
            else:
                lots.append(FutureLot(quantity, price))
        self._charge_fee(product, ticket_id, abs(quantity), notional)
        self._consume_reservation(reservation_id, max(0.0, quantity * multiplier * price) + fee)
        self.fill_count += int(product != "delivery")
        self.turnover += notional if product != "delivery" else 0
        self._rebalance_posted()
        self._emit("delivery" if product == "delivery" else "fill", symbol=symbol,
                   signed_quantity=quantity, price=price, realized_pnl_usd=realized, fee_usd=fee,
                   ticket_id=str(ticket_id), timestamp_us=timestamp_us)
        return fee

    def execute_fill(self, symbol, signed_quantity, price, ticket_id, **kwargs):
        if symbol == "SPOT":
            return self.fill_spot(signed_quantity, price, ticket_id, **kwargs)
        return self.fill_future(symbol, signed_quantity, price, ticket_id, **kwargs)

    def settle_variation(self, symbol, price, available=True, timestamp_us=None, payment_id=None):
        """Accrue VM then pay it, or retain an explicit payable/receivable.

        A failed mandatory debit remains a known payable and raises FundingError;
        it never turns into a negative cash balance or disappears from NAV.
        """
        if payment_id is not None and str(payment_id) in self.pending_variation:
            raise ValueError("Variation payment ID already pending")
        if symbol not in self.contracts:
            raise ValueError("Variation applies only to a registered futures contract")
        self.mark(symbol, price, timestamp_us, "settlement_reference")
        amount = self.unrealized_pnl_usd(symbol)
        quantity = self.units.get(symbol, 0.0)
        # All lots acquire the SAME accounting reference, even if their signed
        # P&L happens to net to zero. Their separate FIFO basis then carries no
        # further information and retaining it would bloat long checkpoints.
        self.lots[symbol] = [FutureLot(quantity, float(price))] if quantity > 0 else []
        if amount == 0:
            self._rebalance_posted()
            return 0.0
        self.settlement_sequence += 1
        key = str(payment_id or f"vm:{self.settlement_sequence}:{symbol}")
        self.pending_variation[key] = {"symbol": symbol, "amount_usd": amount, "timestamp_us": timestamp_us}
        self._rebalance_posted()
        self._emit("variation_accrual", payment_id=key, symbol=symbol, amount_usd=amount)
        if available:
            self.pay_variation(key)
        return amount

    def pay_variation(self, payment_id):
        key = str(payment_id)
        if key not in self.pending_variation:
            raise ValueError("Unknown or already paid variation")
        amount = self.pending_variation[key]["amount_usd"]
        try:
            plan = self._funding_plan(-amount, key)
        except FundingError:
            self._emit("margin_call", payment_id=key, amount_usd=-amount, reason="immediate cash unavailable")
            raise
        self._apply_funding(plan)
        self._debit(-amount)
        self.pending_variation.pop(key)
        self._rebalance_posted()
        self._emit("variation_payment", payment_id=key, amount_usd=amount)
        return amount

    def settle_expiry(self, symbol, price, ticket_id=None, timestamp_us=None):
        if symbol in self.expired:
            raise ValueError("Contract expiry already settled")
        quantity = self.units.get(symbol, 0)
        fee = self._future_fill(symbol, -quantity, price, ticket_id or f"delivery:{symbol}",
                                timestamp_us, None, "delivery")
        self.expired.add(symbol)
        self._emit("expiry", symbol=symbol, price=price, quantity=quantity)
        return fee

    def buy_treasury(self, lot_id, face, remaining_seconds, annual_rate, ticket_id=None,
                     haircut=0.0, tradable=True, settlement_lag_seconds=0.0):
        face = _number(face, "face", 0)
        remaining = _number(remaining_seconds, "remaining maturity", 0)
        rate = _number(annual_rate, "annual rate")
        haircut = _number(haircut, "haircut", 0)
        lag = _number(settlement_lag_seconds, "settlement lag", 0)
        denominator = 1 + rate * remaining / YEAR_SECONDS
        if lot_id in self.treasuries or denominator <= 0 or haircut > 1 or face == 0:
            raise ValueError("Distinct positive Treasury lot and valid simple-yield price/haircut required")
        price = 1 / denominator
        value, ticket = face * price, ticket_id or f"treasury:buy:{lot_id}"
        fee = self.estimate_fee("treasury", ticket, face, value)
        if value + fee > self.available_cash + EPS:
            raise FundingError("Treasury purchase requires unreserved free cash")
        self._debit(value + fee)
        self.treasuries[lot_id] = TreasuryLot(face, remaining, rate, price, haircut, bool(tradable), lag)
        self._charge_fee("treasury", ticket, face, value)
        self._rebalance_posted()
        self._emit("treasury_fill", lot_id=lot_id, signed_face=face, price=price, ticket_id=ticket)

    def set_treasury_haircut(self, lot_id, haircut):
        haircut = _number(haircut, "haircut", 0)
        if haircut > 1:
            raise ValueError("haircut must be <= 1")
        self.treasuries[lot_id].haircut = haircut
        self._rebalance_posted()
        self._emit("collateral_haircut", lot_id=lot_id, haircut=haircut)

    def sell_treasury(self, lot_id, face, ticket_id):
        lot = self.treasuries[lot_id]
        face = _number(face, "face", 0)
        if not lot.tradable or lot.settlement_lag_seconds > 0:
            raise FundingError("Treasury is not immediately tradable/settled in this model")
        if face > lot.face + EPS:
            raise ValueError("Sale exceeds Treasury face held")
        if face == 0:
            return 0.0
        value = face * lot.price
        fee = self.estimate_fee("treasury", ticket_id, face, value)
        if self.cash + value < fee - EPS:
            raise FundingError("Treasury sale cannot fund its commission")
        if self.margin_excess + value * lot.haircut - fee < -EPS:
            raise FundingError("Treasury sale cost would breach full funding")
        lot.face -= face
        self.free_cash_usd += value
        self._debit(fee)
        self._charge_fee("treasury", ticket_id, face, value)
        if lot.face <= EPS:
            self.treasuries.pop(lot_id)
        self._rebalance_posted()
        self._emit("treasury_fill", lot_id=lot_id, signed_face=-face, price=lot.price, ticket_id=ticket_id)
        return fee

    def accrue(self, seconds, annual_rate):
        seconds, rate = _number(seconds, "elapsed seconds", 0), _number(annual_rate, "annual rate")
        income = 0.0
        # Split at actual maturity boundaries so redeemed cash earns subsequent
        # cash-proxy interest, independent of the caller's observation frequency.
        boundaries = sorted({seconds, *(lot.remaining_seconds for lot in self.treasuries.values()
                                         if lot.remaining_seconds <= seconds)})
        previous = 0.0
        for boundary in boundaries:
            elapsed = boundary - previous
            previous = boundary
            increment = 0.0
            if self.cash_interest_proxy and elapsed:
                factor = math.expm1(rate * elapsed / YEAR_SECONDS)
                increment = self.cash * factor
                self.free_cash_usd *= 1 + factor
                self.posted_cash_usd *= 1 + factor
            matured = []
            # Time passage is interest; yield repricing is a separate mark.
            for key, lot in list(self.treasuries.items()):
                before = lot.market_value
                lot.remaining_seconds = max(0.0, lot.remaining_seconds - elapsed)
                lot.price = 1 / (1 + lot.annual_rate * lot.remaining_seconds / YEAR_SECONDS)
                increment += lot.market_value - before
                if lot.remaining_seconds == 0:
                    self.free_cash_usd += lot.face
                    self.treasuries.pop(key)
                    matured.append((key, lot.face))
            self.interest += increment
            income += increment
            self._rebalance_posted()
            for key, face in matured:
                self._emit("treasury_redemption", lot_id=key, amount_usd=face)
        if seconds:
            self._emit("interest", seconds=seconds, amount_usd=income,
                       cash_interest_proxy=self.cash_interest_proxy, annual_rate=rate)
        return income

    def accrue_spot_expense(self, seconds, annual_rate):
        """Explicit direct-holding custody proxy, paid in commodity units.

        This is not a futures fee or a fictitious spot sale. Valuing the units
        consumed at the last available mark reconciles the NAV expense once.
        """
        seconds = _number(seconds, "elapsed seconds", 0)
        rate = _number(annual_rate, "custody expense rate", 0)
        consumed = self.spot_quantity * -math.expm1(-rate * seconds / YEAR_SECONDS)
        expense = consumed * self.marks.get("SPOT", 0.0)
        self.spot_quantity -= consumed
        self.fees += expense
        self.custody_expenses += expense
        if consumed:
            self._emit("custody_expense", seconds=seconds, annual_rate=rate,
                       consumed_commodity=consumed, amount_usd=expense,
                       assumption="direct-holding expense paid in commodity units")
        return expense

    def mark_treasury(self, lot_id, annual_rate):
        lot = self.treasuries[lot_id]
        rate = _number(annual_rate, "annual rate")
        denominator = 1 + rate * lot.remaining_seconds / YEAR_SECONDS
        if denominator <= 0:
            raise ValueError("Synthetic Treasury discount denominator must be positive")
        before = lot.market_value
        lot.annual_rate, lot.price = rate, 1 / denominator
        self.market_pnl += lot.market_value - before
        self._rebalance_posted()
        self._emit("treasury_mark", lot_id=lot_id, price=lot.price, annual_rate=rate)

    def reconstruction_error(self):
        return self.nav - (self.initial + self.market_pnl + self.interest - self.fees)

    def snapshot(self):
        state = {key: value for key, value in vars(self).items()
                 if key not in ("sink", "contracts", "lots", "treasuries", "fee_engine", "expired")}
        # Nested mutable state must not alias the live account/checkpoint.
        for key in ("marks", "reservations"):
            state[key] = dict(state[key])
        for key in ("mark_metadata", "pending_variation"):
            state[key] = {name: dict(value) for name, value in state[key].items()}
        state.update(version=self.VERSION, contracts={key: asdict(value) for key, value in self.contracts.items()},
                     lots={key: [asdict(lot) for lot in lots] for key, lots in self.lots.items()},
                     treasuries={key: asdict(value) for key, value in self.treasuries.items()},
                     fee_engine=self.fee_engine.snapshot(), expired=sorted(self.expired))
        return state

    @classmethod
    def restore(cls, state, sink=None):
        if state.get("version") != cls.VERSION:
            raise ValueError("Unsupported funded ledger checkpoint")
        ledger = cls(state["initial"], cash_interest_proxy=state["cash_interest_proxy"], sink=sink)
        expected = set(ledger.snapshot())
        if set(state) != expected:
            raise ValueError("Malformed funded ledger checkpoint")
        for key, value in state.items():
            if key in ("version", "contracts", "lots", "treasuries", "fee_engine", "expired"):
                continue
            if key in ("marks", "reservations"):
                value = dict(value)
            if key in ("mark_metadata", "pending_variation"):
                value = {name: dict(row) for name, row in value.items()}
            setattr(ledger, key, value)
        ledger.contracts = {key: ContractSpec(**value) for key, value in state["contracts"].items()}
        ledger.lots = {key: [FutureLot(**value) for value in lots] for key, lots in state["lots"].items()}
        ledger.treasuries = {key: TreasuryLot(**value) for key, value in state["treasuries"].items()}
        ledger.fee_engine = FeeEngine.restore(state["fee_engine"])
        ledger.expired = set(state["expired"])
        return ledger
