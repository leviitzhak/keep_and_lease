"""Research-only causal trade-tape fills for long, fully funded regular futures.

Trade prints are a volume proxy, not displayed depth or evidence of queue access.
Integer microseconds preserve native event ordering. No candle interpolation.
"""
from dataclasses import dataclass
import math

YEAR_US = 365 * 86400 * 1_000_000


@dataclass(frozen=True)
class Trade:
    us: int
    symbol: str
    price: float
    btc: float
    side: str  # aggressor side: buys consume ask-side prints
    identifier: str
    executable: bool = True


@dataclass
class Order:
    identifier: int
    symbol: str
    signed_btc: float
    submitted_us: int
    eligible_us: int
    filled_btc: float = 0.0
    filled_value: float = 0.0


class TapeAccount:
    """Mark and book every partial fill at its actual event time.

    Cash collateral equals 100% of long regular-future marked notional. Mark P&L
    settles to USD continuously for research, with fractional hypothetical lots.
    Orders are replaced on each decision; an incomplete order never becomes a
    completed holding. The sink receives a complete order/fill/cancellation audit.
    """
    def __init__(self, capital, participation=1.0, delay_us=0, fee_bps=0, sink=None):
        if not math.isfinite(capital) or capital <= 0:
            raise ValueError("Positive finite capital required")
        if not math.isfinite(participation) or not 0 < participation <= 1:
            raise ValueError("Participation must be in (0, 1]")
        if delay_us < 0 or not math.isfinite(fee_bps) or fee_bps < 0:
            raise ValueError("Delay and fees must be nonnegative")
        self.cash = capital
        self.initial = capital
        self.participation, self.delay_us, self.fee = participation, delay_us, fee_bps / 10000
        self.sink = sink or (lambda row: None)
        self.units, self.marks, self.orders = {}, {}, {}
        self.order_id, self.last_us, self.rate = 0, None, 0.0
        self.interest = self.fees = self.market_pnl = self.turnover = 0.0
        self.fill_count = self.order_count = self.cancellation_count = 0

    def accrue(self, us):
        if self.last_us is not None:
            if us < self.last_us:
                raise ValueError("Events must be chronological")
            value = self.cash * self.rate * (us - self.last_us) / YEAR_US
            self.cash += value
            self.interest += value
        self.last_us = us

    @property
    def nav(self):
        spot = self.marks.get("SPOT")
        return self.cash + self.units.get("SPOT", 0) * (spot.price if spot else 0)

    @property
    def collateral(self):
        return sum(q * self.marks[s].price for s, q in self.units.items() if s != "SPOT")

    def initialize_spot(self, trade):
        if self.units or self.marks.get("SPOT"):
            raise ValueError("Spot already initialized")
        self.accrue(trade.us)
        self.marks["SPOT"] = trade
        self.units["SPOT"] = self.cash / trade.price
        self.cash = 0.0
        self.sink(dict(kind="initial_holding", us=trade.us, btc=self.units["SPOT"],
                       price=trade.price, trade_id=trade.identifier))

    def cancel(self, us, reason="replace"):
        for order in self.orders.values():
            self.sink(dict(kind="order_end", us=us, reason=reason, order_id=order.identifier,
                           symbol=order.symbol, requested_btc=abs(order.signed_btc),
                           filled_btc=order.filled_btc,
                           vwap=order.filled_value / order.filled_btc if order.filled_btc else None,
                           remainder_btc=max(0, abs(order.signed_btc) - order.filled_btc)))
            if abs(order.signed_btc) - order.filled_btc > 1e-14:
                self.cancellation_count += 1
        self.orders.clear()

    def submit_targets(self, us, targets):
        self.accrue(us)
        self.cancel(us)
        for symbol in sorted(set(targets) | set(self.units)):
            target = targets.get(symbol, 0.0)
            if not math.isfinite(target) or target < 0:
                raise ValueError("Only finite long target quantities supported")
            delta = target - self.units.get(symbol, 0.0)
            if abs(delta) < 1e-14:
                continue
            self.order_id += 1
            order = Order(self.order_id, symbol, delta, us, us + self.delay_us)
            self.orders[symbol] = order
            self.order_count += 1
            self.sink(dict(kind="order", us=us, order_id=order.identifier, symbol=symbol,
                           signed_btc=delta, eligible_after_us=order.eligible_us))

    def on_trade(self, trade):
        if not all(math.isfinite(x) and x > 0 for x in (trade.price, trade.btc)):
            raise ValueError("Trade requires positive finite price and volume")
        if trade.side not in ("buy", "sell"):
            raise ValueError("Unknown aggressor side")
        previous = self.marks.get(trade.symbol)
        if previous and (trade.us < previous.us or trade.identifier == previous.identifier):
            raise ValueError("Duplicate or out-of-order print")
        self.accrue(trade.us)
        held = self.units.get(trade.symbol, 0.0)
        pnl = held * (trade.price - previous.price) if previous else 0.0
        self.market_pnl += pnl
        if trade.symbol != "SPOT":
            self.cash += pnl
        self.marks[trade.symbol] = trade
        order = self.orders.get(trade.symbol)
        if order is None or not trade.executable or trade.us <= order.eligible_us:
            return
        buying = order.signed_btc > 0
        if trade.side != ("buy" if buying else "sell"):
            return
        remaining = max(0.0, abs(order.signed_btc) - order.filled_btc)
        capacity = max(0.0, self.cash - self.collateral) / (trade.price * (1 + self.fee)) if buying else held
        quantity = min(remaining, trade.btc * self.participation, capacity)
        if quantity <= 1e-14:
            return
        signed = quantity if buying else -quantity
        fee = quantity * trade.price * self.fee
        self.cash -= fee
        self.fees += fee
        if trade.symbol == "SPOT":
            self.cash -= signed * trade.price
        self.units[trade.symbol] = held + signed
        order.filled_btc += quantity
        order.filled_value += quantity * trade.price
        self.turnover += quantity * trade.price
        self.fill_count += 1
        self.sink(dict(kind="fill", us=trade.us, symbol=trade.symbol,
                       order_id=order.identifier, trade_id=trade.identifier, side=trade.side,
                       signed_btc=signed, price=trade.price, observed_btc=trade.btc,
                       fee_usd=fee, cash_usd=self.cash, nav_usd=self.nav))
        if self.cash < -1e-8 * self.initial:
            raise ValueError("Unfunded cash balance")

    def reconstruction_error(self):
        return self.nav - (self.initial + self.market_pnl + self.interest - self.fees)
