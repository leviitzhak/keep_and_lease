"""Exact discrete-event research exchange with a separately copied observation.

Ordering at identical milliseconds: contractual cash receipts, due messages, exchange tape, reports. Messages
and reports each use a FIFO adapter; amendments replace remaining quantity and
lose priority. This is an explicit hypothetical adapter, not a venue-rule claim.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from copy import deepcopy
from itertools import product
import hashlib
import heapq
import math
import random

from .accounting import EPS, Goal, Instrument, Ledger


@dataclass(frozen=True)
class Trade:
    time: int
    symbol: str
    price: float
    amount: float
    side: str
    identifier: str
    index: float
    source_payoff: str = "inverse"
    executable: bool = True
    source_time: int | None = None


@dataclass(frozen=True)
class Order:
    identifier: str
    symbol: str
    quantity: float
    limit: float
    group: str = ""
    created: int = 0
    tif: str = "GTC"


@dataclass(frozen=True)
class Instruction:
    kind: str = "wait"
    orders: tuple = ()
    targets: tuple = ()

    def payload(self):
        return asdict(self)


@dataclass
class ObservableState:
    time: int
    ledger: Ledger
    market: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    confirmed: dict = field(default_factory=dict)
    uncertain: dict = field(default_factory=dict)
    pending: list = field(default_factory=list)
    reserved: dict = field(default_factory=lambda: {"BTC": 0., "USD": 0.})
    submitted: int = 0
    group_fills: dict = field(default_factory=dict)
    last_decision: int = 0
    failure_observed: bool = False
    reserved_assets: dict = field(default_factory=dict)


@dataclass
class HiddenExchangeState:
    ledger: Ledger
    orders: dict = field(default_factory=dict)
    queue: list = field(default_factory=list)
    serial: int = 0
    message_fifo: int = 0
    report_fifo: int = 0
    group_fills: dict = field(default_factory=dict)
    fills: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    processed: int = 0
    min_headroom: dict = field(default_factory=lambda: {"BTC": math.inf, "USD": math.inf})
    min_funding: float = math.inf
    peak_async: float = 0.
    last_marks: dict = field(default_factory=dict)
    last_index: float = 0.


@dataclass(frozen=True)
class Delays:
    observation: int = 100
    decision: int = 10
    delivery: int = 100
    report: int = 100
    jitter: float = .5
    congestion: float = .5

    def draw(self, seed, channel, identifier, time):
        """Counter keyed draws preserve common scenarios despite different actions."""
        def uniform(key):
            return int.from_bytes(hashlib.sha256(f"{seed}:{key}".encode()).digest()[:8], "big") / 2**64
        common = 1 + self.congestion * uniform(f"congestion:{time // 60000}")
        base = getattr(self, channel)
        return max(0, round(base * common * (1 + self.jitter * (2 * uniform(f"{channel}:{identifier}") - 1))))


def post_decision(obs, action, instruments, *, _share_observations=False):
    """Pure local transformation; never consult hidden state or draw latency."""
    # Internal admission/feature callers only read market/history and never expose
    # this temporary state. Public/default transformations remain fully detached.
    memo = {id(obs.market):obs.market,id(obs.history):obs.history} if _share_observations else None
    x = deepcopy(obs, memo)
    x.last_decision = x.time
    if action.kind == "wait":
        return x
    request_id = f"request-{x.submitted}"
    x.submitted += 1
    x.pending.append(dict(id=request_id, submitted=x.time, instruction=action.payload()))
    for o in action.orders:
        x.uncertain.setdefault(o.identifier, []).append(o)
    # Cancel/edit keeps the previous order and its resources until a report.
    x.reserved = {"USD": 0., "BTC": 0.}
    x.reserved_assets={}
    for variants in x.uncertain.values():
        costs = {"USD": 0., "BTC": 0.}
        assets={}
        for o in variants:
            ins = instruments[o.symbol]
            if not ins.is_future:
                costs['USD']=max(costs['USD'],max(0.,o.quantity*o.limit)+ins.fee(o.quantity,o.limit))
                if o.quantity<0:
                    if ins.payoff=='spot':costs['BTC']=max(costs['BTC'],-o.quantity)
                    else:assets[o.symbol]=max(assets.get(o.symbol,0.),-o.quantity)
            elif ins.currency == "USD":
                costs["USD"] = max(costs["USD"], abs(o.quantity * o.limit) + ins.fee(o.quantity, o.limit))
            else:
                costs["BTC"] = max(costs["BTC"], abs(o.quantity / o.limit) + ins.fee(o.quantity, o.limit))
        for c in costs:
            x.reserved[c] += costs[c]
        for s,q in assets.items():x.reserved_assets[s]=x.reserved_assets.get(s,0.)+q
    return x


def possible_orders(obs, max_orders=6):
    if len(obs.uncertain) > max_orders:
        raise ValueError("uncertainty_budget")
    # Existing and amendment versions can both partially fill. Model each
    # version independently (conservative superset) instead of assuming atomicity.
    flat = [o for variants in obs.uncertain.values() for o in variants]
    if len(flat) > max_orders:
        raise ValueError("uncertainty_budget")
    return flat


def admissible(obs, action, goal, instruments, async_cap=.02):
    try:
        if action.kind not in ("wait", "create", "amend", "cancel", "emergency", "batch"):
            return False, "unsupported_instruction"
        if action.kind in ("wait", "cancel", "emergency") and action.orders:
            return False, "invalid_instruction_shape"
        if action.kind == "wait" and action.targets:
            return False, "invalid_instruction_shape"
        if action.kind == "create" and action.targets:
            return False, "invalid_instruction_shape"
        if action.kind == "batch" and any(t not in obs.uncertain for t in action.targets):
            return False, "unknown_batch_target"
        if action.kind == "amend" and (not action.orders or any(o.identifier not in action.targets or o.identifier not in obs.uncertain for o in action.orders)):
            return False, "unknown_amendment"
        if len({o.identifier for o in action.orders}) != len(action.orders):
            return False, "duplicate_order_id"
        for o in action.orders:
            ins = instruments[o.symbol]
            if not ins.tradable(obs.time,goal.resolution):
                return False, "expiry_outside_support"
            if o.quantity == 0 or not math.isfinite(o.limit) or o.limit <= 0 or o.tif != "GTC":
                return False, "invalid_order"
            if abs(ins.round_quantity(o.quantity)-o.quantity) > EPS or abs(o.limit/ins.tick-round(o.limit/ins.tick)) > EPS:
                return False, "native_rounding"
            if action.kind == "create" and o.identifier in obs.uncertain:
                return False, "duplicate_order_id"
            if action.kind == "batch" and o.identifier in obs.uncertain and o.identifier not in action.targets:
                return False, "duplicate_order_id"
        x = post_decision(obs, action, instruments, _share_observations=True)
        choices = possible_orders(x)
        if not obs.market:
            return (action.kind == "wait" and not choices), "no_market"
        spot = max(obs.market.values(), key=lambda r: r["received"])["index"]
        for subset in product((False, True), repeat=len(choices)):
            p = obs.ledger.clone()
            groups = dict(obs.group_fills)
            for used, order in zip(subset, choices):
                if used:
                    ins = instruments[order.symbol]
                    p.fill(ins, order.quantity, order.limit)
                    if order.group:
                        groups[order.group] = groups.get(order.group, 0.) + ins.btc(order.quantity, order.limit)
            if sum(abs(v) for v in groups.values()) > async_cap + EPS:
                return False, "asynchronous_cap"
            if any(v < -EPS for v in goal.headroom(p.holdings(instruments)).values()):
                return False, "holding_floor"
            if p.funding_headroom(instruments, spot, goal.resolution) < -EPS:
                return False, "dated_funding"
            if goal.mode == "target" and goal.maintain_band and obs.time >= goal.target_deadline and not goal.composition(p.holdings(instruments))[0]:
                return False, "target_band"
        return True, "feasible"
    except (ValueError, KeyError) as e:
        return False, str(e)


class CandidateGenerator:
    def __init__(self, budget=128, quantities=(.005, .01), offsets=(-.005, 0., .005), async_cap=.02):
        if not 2 <= budget <= 128:
            raise ValueError("Candidate budget must be 2..128")
        self.budget, self.quantities, self.offsets, self.async_cap = budget, quantities, offsets, async_cap

    def generate(self, obs, goal, instruments):
        candidates = [Instruction()]
        ids = tuple(sorted(obs.uncertain))
        emergency = Instruction("emergency", targets=ids)
        if ids:
            candidates.append(Instruction("cancel", targets=ids))
            # Local amendments retain identity; total remaining qty is explicit.
            for oid in ids:
                old = obs.uncertain[oid][-1]
                ref = obs.market.get(old.symbol)
                if ref:
                    ins = instruments[old.symbol]
                    price = ins.round_price(ref["price"], old.quantity)
                    candidates.append(Instruction("amend", (Order(oid, old.symbol, old.quantity, price, old.group, obs.time),), (oid,)))
        symbols = [s for s in sorted(instruments) if s in obs.market and obs.time < instruments[s].expiry <= goal.resolution]
        serial = obs.submitted
        def order(s, q_btc, offset, leg, group=""):
            ins, ref = instruments[s], obs.market[s]["price"]
            price = ins.round_price(ref*(1+offset), q_btc)
            q = ins.round_quantity(q_btc if ins.payoff == "linear" else q_btc * price)
            return Order(f"o-{serial}-{leg}", s, q, price, group, obs.time)
        # Pairs first: independent legs, unequal sizes allow both BTC and USD growth.
        for a in range(len(symbols)):
            for b in range(a+1, len(symbols)):
                for size, sign, ratio, offset in product(self.quantities, (1,-1), (1., .99), self.offsets):
                    group = f"g-{serial}"
                    legs = (order(symbols[a], sign*size, offset, 0, group),
                            order(symbols[b], -sign*size*ratio, -offset, 1, group))
                    candidates.append(Instruction("create", legs))
        for s, size, sign, offset in product(symbols, self.quantities, (1,-1), self.offsets):
            candidates.append(Instruction("create", (order(s, sign*size, offset, 0),)))
        # A conservative limit prevents exponentially large uncertainty envelopes.
        if ids:
            candidates = [a for a in candidates if a.kind != "create"]
        candidates = candidates[:self.budget-1]
        candidates.append(emergency)
        accepted, audit = [], []
        seen = set()
        for action in candidates:
            key = repr(action)
            if key in seen:
                continue
            seen.add(key)
            ok, reason = admissible(obs, action, goal, instruments, self.async_cap)
            audit.append(dict(instruction=action.payload(), accepted=ok, reason=reason))
            if ok:
                accepted.append(action)
        # Emergency is cancel-only: it cannot promise immediate recovery. Keep a
        # failed path and stop new risk if all admissible actions disappear.
        if not accepted:
            accepted = [emergency]
        return accepted, audit


class Engine:
    def __init__(self, instruments, ledger, goal, seed=0, delays=None, participation=.1, async_cap=.02, event_cap=100000):
        if not 0 < participation <= 1:
            raise ValueError("Participation must be in (0,1]")
        self.instruments, self.goal, self.seed = instruments, goal, seed
        self.delays = delays or Delays()
        self.participation, self.async_cap, self.event_cap = participation, async_cap, event_cap
        self.observable = ObservableState(0, ledger.clone())
        self.hidden = HiddenExchangeState(ledger.clone())
        self.now = 0
        self.truncated = False
        self.audit = []
        for ins in instruments.values():
            if ins.is_future or ins.payoff=='treasury':self._event(ins.expiry, 3, "expiry_guard", ins.symbol)
            for date,_ in ins.cashflows:self._event(date,-1,'asset_cashflow',ins.symbol)
        for flow in ledger.flows:
            self._event(flow.date, 3, "cashflow", None)

    def _event(self, time, priority, kind, payload):
        h = self.hidden
        h.serial += 1
        heapq.heappush(h.queue, (time, priority, h.serial, kind, payload))

    def add_tape(self, trades):
        for trade in trades:
            if trade.time < self.now:
                raise ValueError("Tape precedes replay clock")
            self._event(trade.time, 1, "trade", trade)
        if len(self.hidden.queue) > self.event_cap:
            raise ValueError("Tape event cap")

    def seed_market(self, trades, start):
        self.now = start
        self.observable.time = start
        for ins in self.instruments.values():
            if ins.expiry<start and ins.symbol in self.hidden.ledger.positions:raise ValueError('Expired inventory at replay start')
            for date,_ in ins.cashflows:
                if date<start:
                    for ledger in (self.hidden.ledger,self.observable.ledger):
                        if ins.payment_id(date) not in ledger.settled_ids:ledger.settled_ids.append(ins.payment_id(date))
        self.hidden.queue=[x for x in self.hidden.queue if x[0]>=start];heapq.heapify(self.hidden.queue)
        for tr in trades:
            if tr.time + self.delays.draw(self.seed, "observation", tr.identifier, tr.time) > start:
                raise ValueError("Seed is not yet observable")
            received = tr.time + self.delays.draw(self.seed, "observation", tr.identifier, tr.time)
            self._observe_trade(tr, received)
            self.hidden.last_marks[tr.symbol] = tr.price
            self.hidden.last_index = tr.index
        self._check()

    def observe(self):
        # Only this type reaches candidates/model. No queue, future tape or true
        # balances are included, even when exchange fills have already occurred.
        return deepcopy(self.observable)

    def submit(self, action):
        if action.kind == "emergency" and action.orders:
            raise ValueError("Emergency may only cancel orders")
        ok, reason = admissible(self.observable, action, self.goal, self.instruments, self.async_cap)
        if not ok and action.kind != "emergency":
            raise ValueError(reason)
        if not ok:
            self.hidden.failures.append(dict(time=self.now, reason="no_feasible_action:" + reason))
        x = post_decision(self.observable, action, self.instruments)
        x.last_decision = self.now
        self.observable = x
        if action.kind == "wait":
            return x
        request = x.pending[-1]["id"]
        arrival = self.now + self.delays.draw(self.seed, "decision", request, self.now) + self.delays.draw(self.seed, "delivery", request, self.now)
        arrival = max(arrival, self.hidden.message_fifo)
        self.hidden.message_fifo = arrival
        self._event(arrival, 0, "message", (request, action))
        return deepcopy(x)

    def _report(self, payload, key):
        arrival = max(self.now + self.delays.draw(self.seed, "report", key, self.now), self.hidden.report_fifo)
        self.hidden.report_fifo = arrival
        self._event(arrival, 2, "report", payload)

    def _observe_trade(self, tr, received):
        row = dict(time=tr.time, received=received, symbol=tr.symbol, price=tr.price,
                   index=tr.index, amount=tr.amount, side=tr.side, identifier=tr.identifier)
        previous = self.observable.market.get(tr.symbol)
        if previous is None or tr.time >= previous["time"]:
            self.observable.market[tr.symbol] = row
        self.observable.history.append(row)
        self.observable.history = self.observable.history[-64:]

    def _check(self):
        h = self.hidden
        holding = h.ledger.holdings(self.instruments)
        rooms = self.goal.headroom(holding)
        for c, v in rooms.items():
            h.min_headroom[c] = min(h.min_headroom[c], v)
            if v < -EPS:
                h.failures.append(dict(time=self.now, reason="floor:"+c))
        if h.last_index:
            funding = h.ledger.funding_headroom(self.instruments, h.last_index, self.goal.resolution)
            h.min_funding = min(h.min_funding, funding)
            if funding < -EPS:
                h.failures.append(dict(time=self.now, reason="funding"))
        asynchronous = sum(abs(v) for v in h.group_fills.values())
        h.peak_async = max(h.peak_async, asynchronous)
        if asynchronous > self.async_cap + EPS:
            h.failures.append(dict(time=self.now, reason="asynchronous_cap"))
        if self.goal.mode == "target" and self.goal.maintain_band and self.now >= self.goal.target_deadline and not self.goal.composition(holding)[0]:
            h.failures.append(dict(time=self.now, reason="target_band"))

    def advance(self, until):
        if until < self.now:
            raise ValueError("Clock cannot go backwards")
        h = self.hidden
        while h.queue and h.queue[0][0] <= until:
            if h.processed >= self.event_cap:
                self.truncated = True
                return
            t, _, sequence, kind, data = heapq.heappop(h.queue)
            self.now = t
            self.observable.time = t
            h.processed += 1
            if kind == "message":
                request, action = data
                live_before = set(h.orders)
                for target in action.targets:
                    h.orders.pop(target, None)
                for order in action.orders:
                    replacing = action.kind == "amend" or (action.kind == "batch" and order.identifier in action.targets)
                    if self.instruments[order.symbol].tradable(t,self.goal.resolution) and (not replacing or order.identifier in live_before):
                        h.orders[order.identifier] = order
                snapshot = {oid: h.orders.get(oid) for oid in set(action.targets) | {o.identifier for o in action.orders}}
                self._report(dict(kind="ack", request=request, snapshot=snapshot), f"ack:{sequence}")
            elif kind == "trade":
                tr = data
                h.last_marks[tr.symbol], h.last_index = tr.price, tr.index
                ins = self.instruments[tr.symbol]
                capacity = ins.print_capacity(tr.amount, tr.price, tr.source_payoff) * self.participation
                if tr.executable and tr.side in ("buy", "sell") and t < ins.expiry:
                    for oid, order in list(h.orders.items()):
                        eligible = order.symbol == tr.symbol and ((order.quantity > 0 and tr.side == "sell" and tr.price < order.limit) or (order.quantity < 0 and tr.side == "buy" and tr.price > order.limit))
                        if not eligible:
                            continue
                        qty = ins.round_quantity(min(abs(order.quantity), capacity,h.ledger.cash_asset_capacity(ins,order.quantity,order.limit)))
                        if qty <= EPS:
                            continue
                        qty = math.copysign(qty, order.quantity)
                        capacity -= abs(qty)
                        h.ledger.fill(ins, qty, order.limit)
                        remainder = order.quantity - qty
                        remaining = Order(oid, order.symbol, remainder, order.limit, order.group, order.created) if abs(remainder) > EPS else None
                        if remaining:
                            h.orders[oid] = remaining
                        else:
                            del h.orders[oid]
                        if order.group:
                            h.group_fills[order.group] = h.group_fills.get(order.group, 0.) + ins.btc(qty, order.limit)
                        fill = dict(time=t, order=oid, symbol=order.symbol, quantity=qty, price=order.limit,
                                    source_id=tr.identifier, source_time=tr.source_time or tr.time,
                                    source_price=tr.price, source_amount=tr.amount, group=order.group,
                                    wait_ms=t-order.created, remaining=abs(remainder))
                        h.fills.append(fill)
                        self._report(dict(kind="fill", order=order, quantity=qty, remaining=remaining), f"fill:{sequence}:{oid}")
                        self._check()  # Check each intermediate fill, never only the package end.
                received = t + self.delays.draw(self.seed, "observation", tr.identifier, t)
                self._event(received, 2, "observation", tr)
            elif kind == "observation":
                self._observe_trade(data, t)
            elif kind == "report":
                if data["kind"] == "fill":
                    order = data["order"]
                    ins = self.instruments[order.symbol]
                    self.observable.ledger.fill(ins, data["quantity"], order.limit)
                    if order.group:
                        self.observable.group_fills[order.group] = self.observable.group_fills.get(order.group, 0.) + ins.btc(data["quantity"], order.limit)
                    self._confirm(order.identifier, data["remaining"])
                elif data["kind"] == "settled":
                    self.observable.ledger.bridge(self.instruments[data["symbol"]], data["index"], data["spot"], observed=True)
                elif data['kind']=='asset_cashflow':
                    paid=self.observable.ledger.pay_asset(self.instruments[data['symbol']],data['date'])
                    if abs(paid-data['amount'])>EPS:raise ValueError('Delayed asset cashflow ownership mismatch')
                else:
                    self.observable.pending = [p for p in self.observable.pending if p["id"] != data["request"]]
                    for oid, order in data["snapshot"].items():
                        self._confirm(oid, order)
                # Preserve later, still-pending amendment/create uncertainty.
                for pending in self.observable.pending:
                    for o in pending["instruction"]["orders"]:
                        order = Order(**o)
                        variants = self.observable.uncertain.setdefault(order.identifier, [])
                        if order not in variants:
                            variants.append(order)
                reserved = post_decision(self.observable, Instruction("cancel"), self.instruments)
                self.observable.reserved,self.observable.reserved_assets=reserved.reserved,reserved.reserved_assets
            elif kind=='asset_cashflow':
                amount=h.ledger.pay_asset(self.instruments[data],t)
                self._report(dict(kind='asset_cashflow',symbol=data,date=t,amount=amount),f'asset:{data}:{t}')
            elif kind == "settlement":
                symbol, index, spot, observed = data
                ins = self.instruments[symbol]
                if t != ins.expiry:
                    raise ValueError("Settlement date mismatch")
                h.ledger.bridge(ins, index, spot, observed=observed)
                # Fixture settlement reports use the same delayed FIFO channel.
                self._report(dict(kind="settled", symbol=symbol, index=index, spot=spot), f"settled:{sequence}")
            elif kind == "expiry_guard":
                expired={k:None for k,o in h.orders.items() if o.symbol==data}
                h.orders = {k:o for k,o in h.orders.items() if o.symbol != data}
                if expired:self._report(dict(kind='ack',request=None,snapshot=expired),f'expired:{data}')
                if data in h.ledger.positions and self.instruments[data].is_future:
                    self.truncated = True
                    h.failures.append(dict(time=t, reason="missing_observed_settlement:"+data))
                    return
            elif kind == "cashflow":
                pass
            else:
                raise ValueError("Unknown event")
            h.ledger.resolve_cashflows(t)
            self.observable.ledger.resolve_cashflows(t)
            self._check()
        self.now = until
        self.observable.time = until
        self._check()

    def _confirm(self, oid, order):
        if order:
            self.observable.confirmed[oid] = order
            self.observable.uncertain[oid] = [order]
        else:
            self.observable.confirmed.pop(oid, None)
            self.observable.uncertain.pop(oid, None)

    def outcome(self):
        if self.truncated or self.now < self.goal.horizon:
            return dict(done=False, truncated=True, failure_reason="runtime_or_horizon_incomplete")
        h = self.hidden
        holdings = h.ledger.holdings(self.instruments)
        summary = self.goal.outcome(holdings, bool(h.failures))
        summary.update(done=True, truncated=False, holdings=holdings, balances=dict(h.ledger.balances),
                       holding_status="contractual/projected" if h.ledger.positions or h.ledger.flows or h.ledger.projected_receipts else "realized",
                       projected_receipts=list(h.ledger.projected_receipts),
                       marked_wealth=h.ledger.marked_wealth(self.instruments, h.last_marks, h.last_index),
                       min_floor_headroom=h.min_headroom, min_funding_usd=h.min_funding,
                       peak_async_btc=h.peak_async, credit_used=h.ledger.debt_principal,
                       fills=len(h.fills), turnover_usd=sum(self.instruments[f['symbol']].notional_usd(f['quantity'],f['price']) for f in h.fills),
                       turnover_btc=sum(abs(self.instruments[f["symbol"]].btc(f["quantity"], f["price"])) for f in h.fills),
                       fees=dict(h.ledger.fees), failures=h.failures, schedule=h.ledger.schedule(self.instruments),
                       pending_messages=len(self.observable.pending), live_orders=len(h.orders),
                       wait_ms=[f["wait_ms"] for f in h.fills],
                       partial_fills=sum(f["remaining"] > EPS for f in h.fills),
                       full_fills=sum(f["remaining"] <= EPS for f in h.fills))
        return summary
