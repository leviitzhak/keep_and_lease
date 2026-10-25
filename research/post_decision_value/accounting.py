"""Signed native ledgers and dated, funded delivery-equivalent accounting.

Separate from the existing long-only FundedLedger: its public semantics remain
unchanged. A pledge is a cash restriction, never another asset or an expense.
All dates are integer milliseconds. Floating values are checked at native lots;
this is a research ledger, not an exchange reconciliation implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from copy import deepcopy
import math

EPS = 1e-9
YEAR = 365.25 * 86400000


@dataclass(frozen=True)
class Instrument:
    symbol: str
    expiry: int
    payoff: str = "linear"
    tick: float = 2.5
    lot: float = .0001
    fee_bps: float = 1.0
    margin_fraction: float = .1
    source_payoff: str = "inverse"

    def __post_init__(self):
        if self.payoff not in ("linear", "inverse"):
            raise ValueError("Unsupported payoff")
        if not self.symbol or self.expiry <= 0:
            raise ValueError("Exact identity and expiry required")
        for x in (self.tick, self.lot):
            if not math.isfinite(x) or x <= 0:
                raise ValueError("Positive finite tick/lot required")
        if not 0 <= self.margin_fraction <= 1 or not 0 <= self.fee_bps < 100:
            raise ValueError("Invalid fee/margin assumption")

    @property
    def currency(self):
        return "USD" if self.payoff == "linear" else "BTC"

    def round_quantity(self, quantity):
        return math.copysign(math.floor(abs(quantity) / self.lot + 1e-10) * self.lot, quantity)

    def round_price(self, price, side):
        fn = math.floor if side > 0 else math.ceil
        return fn(price / self.tick + (1e-10 if side > 0 else -1e-10)) * self.tick

    def btc(self, quantity, basis):
        return quantity if self.payoff == "linear" else quantity / basis

    def claims(self, quantity, basis):
        return {"BTC": self.btc(quantity, basis),
                "USD": -quantity * basis if self.payoff == "linear" else -quantity}

    def pnl(self, quantity, basis, price):
        if min(price, basis) <= 0:
            raise ValueError("Nonpositive settlement basis")
        return quantity * (price - basis) if self.payoff == "linear" else quantity * (1 / basis - 1 / price)

    def fee(self, quantity, price):
        native_notional = abs(quantity * price) if self.payoff == "linear" else abs(quantity / price)
        return native_notional * self.fee_bps / 10000

    def print_capacity(self, amount, price, source_payoff="inverse"):
        if source_payoff != self.source_payoff or amount < 0 or price <= 0:
            raise ValueError("Invalid native source units")
        if source_payoff == self.payoff:
            return amount
        if source_payoff == "inverse" and self.payoff == "linear":
            return amount / price
        raise ValueError("Unsupported source conversion")


@dataclass
class Position:
    quantity: float
    basis: float


@dataclass
class Cashflow:
    identifier: str
    date: int
    currency: str
    amount: float
    kind: str


@dataclass
class Ledger:
    balances: dict = field(default_factory=lambda: {"BTC": 0., "USD": 0.})
    positions: dict = field(default_factory=dict)
    flows: list = field(default_factory=list)
    collateral: dict = field(default_factory=lambda: {"BTC": 0., "USD": 0.})
    credit_limit: float = 0.
    debt_principal: float = 0.
    fees: dict = field(default_factory=lambda: {"BTC": 0., "USD": 0.})
    settled_ids: list = field(default_factory=list)

    def clone(self):
        return deepcopy(self)

    def holdings(self, instruments):
        h = dict(self.balances)
        for s, p in self.positions.items():
            for currency, amount in instruments[s].claims(p.quantity, p.basis).items():
                h[currency] += amount
        for flow in self.flows:
            h[flow.currency] += flow.amount
        return h

    def schedule(self, instruments):
        result = [asdict(x) for x in self.flows]
        for s, p in self.positions.items():
            result.append(dict(identifier=s, date=instruments[s].expiry, kind="funded_expiry_bridge",
                               claims=instruments[s].claims(p.quantity, p.basis)))
        return sorted(result, key=lambda x: (x["date"], x["identifier"]))

    def fill(self, instrument, quantity, price):
        if not math.isfinite(quantity) or price <= 0 or not math.isfinite(price):
            raise ValueError("Invalid fill")
        fee = instrument.fee(quantity, price)
        self.balances[instrument.currency] -= fee
        self.fees[instrument.currency] += fee
        old = self.positions.get(instrument.symbol)
        if old is None:
            if abs(quantity) > EPS:
                self.positions[instrument.symbol] = Position(quantity, price)
            return
        q = old.quantity + quantity
        if old.quantity * quantity < 0:
            closed = math.copysign(min(abs(old.quantity), abs(quantity)), old.quantity)
            self.balances[instrument.currency] += instrument.pnl(closed, old.basis, price)
            if abs(q) < EPS:
                del self.positions[instrument.symbol]
            elif q * old.quantity > 0:
                old.quantity = q
            else:
                self.positions[instrument.symbol] = Position(q, price)
        else:
            basis = ((old.quantity * old.basis + quantity * price) / q if instrument.payoff == "linear"
                     else q / (old.quantity / old.basis + quantity / price))
            self.positions[instrument.symbol] = Position(q, basis)

    def variation(self, instrument, price):
        p = self.positions.get(instrument.symbol)
        if p:
            self.balances[instrument.currency] += instrument.pnl(p.quantity, p.basis, price)
            p.basis = price

    def bridge(self, instrument, index, executable_spot, *, observed, fee_bps=0.):
        if not observed:
            raise ValueError("Observed settlement and executable bridge evidence required")
        if min(index, executable_spot) <= 0:
            raise ValueError("Positive settlement/bridge prices required")
        p = self.positions.get(instrument.symbol)
        if p is None:
            return
        q = p.quantity if instrument.payoff == "linear" else p.quantity / index
        self.variation(instrument, index)
        self.balances["BTC"] += q
        cost = abs(q * executable_spot) * fee_bps / 10000
        self.balances["USD"] -= q * executable_spot + cost
        self.fees["USD"] += cost
        del self.positions[instrument.symbol]

    def pledge(self, currency, amount):
        if amount < 0 or amount > self.balances[currency] + EPS:
            raise ValueError("Collateral not available")
        self.collateral[currency] = amount

    def borrow(self, amount, due, interest=0.):
        if amount <= 0 or interest < 0 or self.debt_principal + amount > self.credit_limit + EPS:
            raise ValueError("No authorized credit capacity")
        self.balances["USD"] += amount
        self.debt_principal += amount
        self.flows.append(Cashflow(f"debt-{len(self.flows)}", due, "USD", -amount-interest, "debt"))

    def buy_treasury(self, identifier, cost, receipts, *, enabled=False):
        if not enabled:
            raise ValueError("Treasury account capability not enabled")
        if cost < 0 or cost > self.balances["USD"] - self.collateral["USD"]:
            raise ValueError("Unfunded Treasury")
        if any(x.identifier.startswith(identifier + ":") for x in self.flows):
            raise ValueError("Duplicate Treasury")
        self.balances["USD"] -= cost
        self.flows.extend(Cashflow(f"{identifier}:{i}", t, "USD", v, "treasury") for i, (t, v) in enumerate(receipts))

    def resolve_cashflows(self, now):
        for f in list(self.flows):
            if f.date <= now:
                self.balances[f.currency] += f.amount
                self.flows.remove(f)
                self.settled_ids.append(f.identifier)
        if not any(f.kind == "debt" for f in self.flows):
            self.debt_principal = 0.

    def marked_wealth(self, instruments, marks, spot):
        wealth = self.balances["USD"] + self.balances["BTC"] * spot
        for s, p in self.positions.items():
            payoff = instruments[s].pnl(p.quantity, p.basis, marks[s])
            wealth += payoff * (spot if instruments[s].currency == "BTC" else 1)
        # No unobserved price is manufactured for Treasury claims.
        debt = sum(f.amount * (spot if f.currency == "BTC" else 1) for f in self.flows if f.kind == "debt")
        return dict(USD=wealth + debt, BTC=(wealth + debt) / spot,
                    unmarked_assets=any(f.kind == "treasury" for f in self.flows))

    def funding_headroom(self, instruments, spot, resolution, stress=(.5, 1., 2.), bridge_bps=10.):
        """Finite scenario test of interim VM, margin and dated bridges.

        Run independent adverse settlement prices per expiry. Available spot is
        not monetized to fund a USD deficit. Future credit is never presumed.
        """
        if any(i.expiry > resolution for s, i in instruments.items() if s in self.positions):
            return -math.inf
        if any(f.date > resolution for f in self.flows):
            return -math.inf
        minimum = math.inf
        for factor in stress:
            p = self.clone()
            margin = {"USD": 0., "BTC": 0.}
            for s, pos in p.positions.items():
                ins = instruments[s]
                value = abs(pos.quantity * spot) if ins.payoff == "linear" else abs(pos.quantity / spot)
                margin[ins.currency] += value * ins.margin_fraction
                # Mark stress consumes liquidity, but does not create new LT wealth.
                p.variation(ins, spot * factor)
            for c in ("USD", "BTC"):
                minimum = min(minimum, (p.balances[c] - max(p.collateral[c], margin[c])) * (spot if c == "BTC" else 1))
            dates = sorted({instruments[s].expiry for s in p.positions} | {f.date for f in p.flows})
            for date in dates:
                # Conservative convention: bridge debits precede same-date receipts.
                for s in list(p.positions):
                    ins = instruments[s]
                    if ins.expiry == date:
                        q = p.positions[s].quantity
                        px = spot * factor
                        executable = px * (1 + math.copysign(bridge_bps/10000, q))
                        p.bridge(ins, px, executable, observed=True)
                        minimum = min(minimum, p.balances["USD"], p.balances["BTC"] * spot)
                p.resolve_cashflows(date)
                minimum = min(minimum, p.balances["USD"], p.balances["BTC"] * spot)
        return minimum


@dataclass
class Goal:
    initial: dict
    horizon: int
    resolution: int
    drawdown: float = .1
    absolute_floors: dict = field(default_factory=dict)
    scales: dict = field(default_factory=dict)
    mode: str = "basket"
    reference: dict = field(default_factory=lambda: {"BTC": 100000., "USD": 1.})
    target: dict = field(default_factory=lambda: {"BTC": .6, "USD": .4})
    tolerance: float = .02
    target_deadline: int | None = None
    maintain_band: bool = False
    failure_penalty: float = 1.
    composition_penalty: float = 1.

    def __post_init__(self):
        if self.mode not in ("basket", "target", "btc") or not 0 <= self.drawdown <= 1:
            raise ValueError("Invalid goal")
        if self.resolution < self.horizon:
            raise ValueError("Claim resolution precedes horizon")
        if set(self.initial) != {"BTC", "USD"} or any(v < 0 for v in self.initial.values()):
            raise ValueError("v1 requires nonnegative BTC/USD quantities")
        for c, v in self.initial.items():
            if not math.isfinite(v):
                raise ValueError("Nonfinite initial holding")
            if v == 0 and (c not in self.absolute_floors or self.scales.get(c, 0) <= 0):
                raise ValueError("Zero initial holding requires absolute floor and positive scale")
        if self.mode == "btc" and self.initial["BTC"] <= 0:
            raise ValueError("BTC objective needs positive initial BTC")
        if abs(sum(self.target.values()) - 1) > EPS or any(v <= 0 for v in self.reference.values()):
            raise ValueError("Invalid composition/reference")
        if not 0 <= self.tolerance < 1 or min(self.failure_penalty, self.composition_penalty) < 0:
            raise ValueError("Invalid goal penalties/tolerance")
        if self.target_deadline is None:
            self.target_deadline = self.horizon

    def floor(self, currency):
        return (1 - self.drawdown) * self.initial[currency] if self.initial[currency] > 0 else self.absolute_floors[currency]

    def scale(self, currency):
        return self.initial[currency] or self.scales[currency]

    def headroom(self, holdings):
        return {c: holdings[c] - self.floor(c) for c in self.initial}

    def composition(self, holdings):
        wealth = sum(holdings[c] * self.reference[c] for c in self.initial)
        if wealth <= 0:
            return False, 1., wealth
        error = max(abs(holdings[c] * self.reference[c] / wealth - self.target[c]) for c in self.initial)
        return error <= self.tolerance + EPS, error, wealth

    def required_target_value(self):
        # Necessary (not sufficient) wealth; exact in the two-commodity case.
        return max(self.floor(c) * self.reference[c] / min(1., self.target[c] + self.tolerance) for c in self.initial)

    def outcome(self, holdings, failed=False):
        growth = {c: (holdings[c] - self.initial[c]) / self.scale(c) for c in self.initial}
        attained, error, wealth = self.composition(holdings)
        if self.mode == "target":
            base = wealth / sum(self.initial[c] * self.reference[c] for c in self.initial) - 1
            utility = base - self.composition_penalty * max(0., error - self.tolerance)
        else:
            utility = growth["BTC"] if self.mode == "btc" else min(growth[c] for c in growth if self.initial[c] > 0)
        return dict(growth=growth, utility=utility - self.failure_penalty * failed,
                    failed=bool(failed), attained=attained, composition_error=error,
                    fixed_reference_value=wealth, score_is_surrogate=self.mode == "target")
