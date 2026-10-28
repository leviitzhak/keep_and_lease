"""Signed native ledgers and dated, funded delivery-equivalent accounting.

Separate from the existing long-only FundedLedger: its public semantics remain
unchanged. A pledge is a cash restriction, never another asset or an expense.
All dates are integer milliseconds. Floating values are checked at native lots;
this is a research ledger, not an exchange reconciliation implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
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
    underlying_per_unit: float = 1.
    cashflows: tuple = ()  # (payment timestamp, USD per native unit), known terms.
    enabled: bool = True
    listed_at: int = 0

    def __post_init__(self):
        if self.payoff not in ("linear", "inverse", "spot", "proxy", "treasury"):
            raise ValueError("Unsupported payoff")
        if not self.symbol or self.expiry <= 0:
            raise ValueError("Exact identity and expiry required")
        for x in (self.tick, self.lot):
            if not math.isfinite(x) or x <= 0:
                raise ValueError("Positive finite tick/lot required")
        if not 0 <= self.margin_fraction <= 1 or not 0 <= self.fee_bps < 100:
            raise ValueError("Invalid fee/margin assumption")
        if not math.isfinite(self.underlying_per_unit) or self.underlying_per_unit<=0:
            raise ValueError('Positive observable proxy conversion required')
        if not self.is_future and self.source_payoff!=self.payoff:
            raise ValueError('Cash assets require explicitly typed native source units')
        if self.payoff=='treasury':
            if not self.cashflows or any(t<=0 or t>self.expiry or not math.isfinite(v) or v<=0 for t,v in self.cashflows):
                raise ValueError('Explicit positive dated Treasury receipts required')
            if len({t for t,_ in self.cashflows})!=len(self.cashflows) or max(t for t,_ in self.cashflows)!=self.expiry:
                raise ValueError('Unique receipt dates ending at maturity required')
        elif self.cashflows:
            raise ValueError('Only Treasury instruments have USD receipts')

    @property
    def is_future(self):return self.payoff in ('linear','inverse')

    def tradable(self,now,resolution):
        return self.enabled and self.listed_at<=now<self.expiry and (self.payoff in ('spot','proxy') or self.expiry<=resolution)

    def notional_usd(self,quantity,price):return abs(quantity) if self.payoff=='inverse' else abs(quantity*price)

    def payment_id(self,date):return f'asset:{self.symbol}:{date}'

    def price_scale(self,btc_reference):
        return sum(v for _,v in self.cashflows) if self.payoff=='treasury' else btc_reference*self.underlying_per_unit if self.payoff=='proxy' else btc_reference

    @property
    def currency(self):
        return "BTC" if self.payoff == "inverse" else "USD"

    def round_quantity(self, quantity):
        return math.copysign(math.floor(abs(quantity) / self.lot + 1e-10) * self.lot, quantity)

    def round_price(self, price, side):
        fn = math.floor if side > 0 else math.ceil
        return fn(price / self.tick + (1e-10 if side > 0 else -1e-10)) * self.tick

    def btc(self, quantity, basis):
        if self.payoff=='treasury':return 0.
        if self.payoff=='proxy':return quantity*self.underlying_per_unit
        return quantity / basis if self.payoff=='inverse' else quantity

    def claims(self, quantity, basis):
        if not self.is_future:
            return {'BTC':self.btc(quantity,basis),'USD':quantity*sum(v for _,v in self.cashflows)}
        return {"BTC": self.btc(quantity, basis),
                "USD": -quantity * basis if self.payoff == "linear" else -quantity}

    def pnl(self, quantity, basis, price):
        if not self.is_future:raise ValueError('Cash assets have inventory, not futures variation')
        if min(price, basis) <= 0:
            raise ValueError("Nonpositive settlement basis")
        return quantity * (price - basis) if self.payoff == "linear" else quantity * (1 / basis - 1 / price)

    def fee(self, quantity, price):
        native_notional = abs(quantity / price) if self.payoff == "inverse" else abs(quantity * price)
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
    projected_receipts: list = field(default_factory=list)

    def clone(self):
        # All leaves are numeric/string primitives. Copy every mutable container
        # and dataclass explicitly: event-by-event funding stress calls this
        # millions of times, where generic deepcopy bookkeeping dominates.
        return Ledger(balances=self.balances.copy(),
                      positions={s: Position(p.quantity, p.basis) for s, p in self.positions.items()},
                      flows=[Cashflow(f.identifier, f.date, f.currency, f.amount, f.kind) for f in self.flows],
                      collateral=self.collateral.copy(), credit_limit=self.credit_limit,
                      debt_principal=self.debt_principal, fees=self.fees.copy(),
                      settled_ids=self.settled_ids.copy(),projected_receipts=self.projected_receipts.copy())

    def holdings(self, instruments):
        h = dict(self.balances)
        for s, p in self.positions.items():
            ins=instruments[s]
            claims=ins.claims(p.quantity,p.basis)
            if ins.payoff=='treasury':claims['USD']=p.quantity*sum(v for t,v in ins.cashflows if ins.payment_id(t) not in self.settled_ids)
            for currency, amount in claims.items():
                h[currency] += amount
        for flow in self.flows:
            h[flow.currency] += flow.amount
        return h

    def schedule(self, instruments):
        result = [asdict(x) for x in self.flows]
        for s, p in self.positions.items():
            ins=instruments[s]
            if ins.payoff=='treasury':
                result.extend(dict(identifier=ins.payment_id(t),date=t,kind='treasury',currency='USD',amount=p.quantity*v)
                              for t,v in ins.cashflows if ins.payment_id(t) not in self.settled_ids)
                continue
            if not ins.is_future:continue
            result.append(dict(identifier=s, date=instruments[s].expiry, kind="funded_expiry_bridge",
                               claims=instruments[s].claims(p.quantity, p.basis)))
        return sorted(result, key=lambda x: (x["date"], x["identifier"]))

    def fill(self, instrument, quantity, price):
        if not math.isfinite(quantity) or price <= 0 or not math.isfinite(price):
            raise ValueError("Invalid fill")
        fee = instrument.fee(quantity, price)
        if not instrument.is_future:
            owned=self.balances['BTC'] if instrument.payoff=='spot' else self.positions.get(instrument.symbol,Position(0.,price)).quantity
            free=owned-self.collateral['BTC'] if instrument.payoff=='spot' else owned
            if quantity<0 and free+quantity < -EPS:raise ValueError('Unowned or pledged cash asset sale')
            debit=quantity*price+fee
            if debit>self.balances['USD']-self.collateral['USD']+EPS:raise ValueError('Cash purchase requires settled unpledged USD')
            self.balances['USD']-=debit;self.fees['USD']+=fee
            if instrument.payoff=='spot':self.balances['BTC']+=quantity
            elif abs(owned+quantity)<EPS:self.positions.pop(instrument.symbol,None)
            else:self.positions[instrument.symbol]=Position(owned+quantity,price)
            return
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

    def pay_funding(self, instrument, date, rate, price):
        """Explicit signed synthetic funding; positive rate is paid by longs.

        Linear contracts pay quantity * price * rate USD; inverse contracts
        pay quantity / price * rate BTC. No funding schedule is implied.
        """
        if (not instrument.is_future or not math.isfinite(rate) or
                abs(rate) > .01 or not math.isfinite(price) or price <= 0):
            raise ValueError('Invalid explicit funding event')
        key = f'funding:{instrument.symbol}:{date}'
        if key in self.settled_ids:
            return 0.
        self.settled_ids.append(key)
        pos = self.positions.get(instrument.symbol)
        q = pos.quantity if pos else 0.
        amount = -rate * (q / price if instrument.payoff == 'inverse' else q * price)
        self.balances[instrument.currency] += amount
        return amount

    def variation(self, instrument, price):
        if not instrument.is_future:raise ValueError('No variation on cash assets')
        p = self.positions.get(instrument.symbol)
        if p:
            self.balances[instrument.currency] += instrument.pnl(p.quantity, p.basis, price)
            p.basis = price

    def bridge(self, instrument, index, executable_spot, *, observed, fee_bps=0.):
        if not instrument.is_future:raise ValueError('Expiry bridge applies to futures only')
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

    def cash_asset_capacity(self,instrument,quantity,price):
        if instrument.is_future:return abs(quantity)
        if quantity>0:return max(0.,self.balances['USD']-self.collateral['USD'])/(price*(1+instrument.fee_bps/10000))
        if instrument.payoff=='spot':return max(0.,self.balances['BTC']-self.collateral['BTC'])
        return self.positions.get(instrument.symbol,Position(0.,price)).quantity

    def pay_asset(self,instrument,date):
        if instrument.payoff!='treasury':raise ValueError('Only Treasury receipts can be paid')
        identifier=instrument.payment_id(date)
        if identifier in self.settled_ids:return 0.
        amounts=[v for t,v in instrument.cashflows if t==date]
        if len(amounts)!=1:raise ValueError('No contractual cash payment on this date')
        quantity=self.positions.get(instrument.symbol,Position(0.,0.)).quantity
        amount=quantity*amounts[0];self.balances['USD']+=amount;self.settled_ids.append(identifier)
        if amount: self.projected_receipts.append(identifier)
        if date==instrument.expiry:self.positions.pop(instrument.symbol,None)
        return amount

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
        unmarked=False
        for s, p in self.positions.items():
            if not instruments[s].is_future:
                if s in marks:wealth+=p.quantity*marks[s]
                else:unmarked=True
                continue
            payoff = instruments[s].pnl(p.quantity, p.basis, marks[s])
            wealth += payoff * (spot if instruments[s].currency == "BTC" else 1)
        # No unobserved price is manufactured for Treasury claims.
        debt = sum(f.amount * (spot if f.currency == "BTC" else 1) for f in self.flows if f.kind == "debt")
        return dict(USD=wealth + debt, BTC=(wealth + debt) / spot,
                    unmarked_assets=unmarked or any(f.kind == "treasury" for f in self.flows))

    def funding_headroom(self, instruments, spot, resolution, stress=(.5, 1., 2.), bridge_bps=10.):
        """Finite scenario test of interim VM, margin and dated bridges.

        Run three parallel price stresses through every expiry. Available spot is
        not monetized to fund a USD deficit. Future credit is never presumed.
        """
        if any(i.expiry > resolution for s, i in instruments.items() if s in self.positions and (i.is_future or i.payoff=='treasury')):
            return -math.inf
        if any(f.date > resolution for f in self.flows):
            return -math.inf
        minimum = math.inf
        for factor in stress:
            p = self.clone()
            margin = {"USD": 0., "BTC": 0.}
            for s, pos in p.positions.items():
                ins = instruments[s]
                if not ins.is_future:continue
                value = abs(pos.quantity * spot) if ins.payoff == "linear" else abs(pos.quantity / spot)
                margin[ins.currency] += value * ins.margin_fraction
                # Mark stress consumes liquidity, but does not create new LT wealth.
                p.variation(ins, spot * factor)
            for c in ("USD", "BTC"):
                minimum = min(minimum, (p.balances[c] - max(p.collateral[c], margin[c])) * (spot if c == "BTC" else 1))
            dates = sorted({instruments[s].expiry for s in p.positions if instruments[s].is_future} | {f.date for f in p.flows} |
                           {t for s in p.positions for t,_ in instruments[s].cashflows if instruments[s].payment_id(t) not in p.settled_ids})
            for date in dates:
                # Conservative convention: bridge debits precede same-date receipts.
                for s in list(p.positions):
                    ins = instruments[s]
                    if ins.is_future and ins.expiry == date:
                        q = p.positions[s].quantity
                        px = spot * factor
                        executable = px * (1 + math.copysign(bridge_bps/10000, q))
                        p.bridge(ins, px, executable, observed=True)
                        minimum = min(minimum, p.balances["USD"], p.balances["BTC"] * spot)
                for s in list(p.positions):
                    ins=instruments[s]
                    if any(t==date for t,_ in ins.cashflows):p.pay_asset(ins,date)
                p.resolve_cashflows(date)
                minimum = min(minimum, p.balances["USD"], p.balances["BTC"] * spot)
        return minimum


@dataclass
class Goal:
    initial: dict
    horizon: int
    resolution: int
    drawdown: float | dict = .1
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
    growth_weights: dict = field(default_factory=lambda: {'BTC':.5,'USD':.5})
    loss_aversion: float = 10.

    def __post_init__(self):
        drops = self.drawdown.values() if isinstance(self.drawdown, dict) else [self.drawdown]
        if self.mode not in ("basket", "target", "btc", "gated_max", "weighted_growth") or any(not 0 <= d <= 1 for d in drops):
            raise ValueError("Invalid goal")
        if (set(self.growth_weights)!={'BTC','USD'} or
            any(not math.isfinite(w) or w<0 for w in self.growth_weights.values()) or
            abs(sum(self.growth_weights.values())-1)>EPS or
            not math.isfinite(self.loss_aversion) or self.loss_aversion<=0):
            raise ValueError('Nonnegative normalized growth weights and positive finite loss aversion required')
        if isinstance(self.drawdown, dict) and set(self.drawdown) != {"BTC", "USD"}:
            raise ValueError("Per-commodity drawdowns must cover BTC and USD")
        if self.resolution < self.horizon:
            raise ValueError("Claim resolution precedes horizon")
        if set(self.initial) != {"BTC", "USD"} or any(v < 0 for v in self.initial.values()):
            raise ValueError("v1 requires nonnegative BTC/USD quantities")
        if not any(v > 0 for v in self.initial.values()):
            raise ValueError("At least one positive initial holding required")
        for c, v in self.initial.items():
            if not math.isfinite(v):
                raise ValueError("Nonfinite initial holding")
            if v == 0 and (c not in self.absolute_floors or self.scales.get(c, 0) <= 0):
                raise ValueError("Zero initial holding requires absolute floor and positive scale")
        if self.mode == "btc" and self.initial["BTC"] <= 0:
            raise ValueError("BTC objective needs positive initial BTC")
        if set(self.target) != {"BTC", "USD"} or set(self.reference) != {"BTC", "USD"}:
            raise ValueError("BTC/USD target and reference required")
        if any(not 0 <= v <= 1 for v in self.target.values()) or abs(sum(self.target.values()) - 1) > EPS or any(not math.isfinite(v) or v <= 0 for v in self.reference.values()):
            raise ValueError("Invalid composition/reference")
        if not 0 <= self.tolerance < 1 or min(self.failure_penalty, self.composition_penalty) < 0:
            raise ValueError("Invalid goal penalties/tolerance")
        if self.target_deadline is None:
            self.target_deadline = self.horizon

    def floor(self, currency):
        drop = self.drawdown[currency] if isinstance(self.drawdown, dict) else self.drawdown
        return (1 - drop) * self.initial[currency] if self.initial[currency] > 0 else self.absolute_floors[currency]

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
        elif self.mode=='weighted_growth':
            active=[c for c in growth if self.initial[c]>0]
            utility=sum(self.growth_weights[c]*max(0.,growth[c]) for c in active)
            utility-=self.loss_aversion*sum(max(0.,-growth[c]) for c in active)
        elif self.mode=='gated_max':
            # Exact sign test: do not hide a small real loss behind a tolerance.
            active=[growth[c] for c in growth if self.initial[c]>0]
            low=min(active);utility=low if low<0 else max(active)
        else:
            utility = growth["BTC"] if self.mode == "btc" else min(growth[c] for c in growth if self.initial[c] > 0)
        return dict(growth=growth, utility=utility - self.failure_penalty * failed,objective=self.mode,
                    objective_parameters=dict(weights=self.growth_weights.copy(),loss_aversion=self.loss_aversion) if self.mode=='weighted_growth' else {},
                    failed=bool(failed), attained=attained, composition_error=error,
                    fixed_reference_value=wealth, score_is_surrogate=self.mode == "target")
