"""Causal, funded paired transfers for the BTC linear-price research proxy.

Actual exchange inventory, delayed observations and delayed fill acknowledgements
are separate state. A durable transfer serializes bounded source/target chunks;
its reservations and fee tickets survive decisions and checkpoints. Trade volume
is a participation assumption, never displayed executable depth.
"""
from dataclasses import asdict, dataclass, field, replace
import copy
import heapq
import math

from trade_replay import Trade
from funded_ledger import ContractSpec, FeeSchedule, FundedLedger, FundingError

YEAR_US = 365 * 86400 * 1_000_000
EPS = 1e-12


@dataclass
class PairedConfig:
    max_transfer_fraction: float = .25
    cash_reserve_fraction: float = .01
    max_legging_seconds: float = 30
    max_unpaired_btc: float = .01
    max_quote_age_seconds: float = 1
    max_quote_skew_seconds: float = 1
    price_limit_bps: float = 10
    spot_feed_delay_seconds: float = 0
    futures_feed_delay_seconds: float = 0
    response_delay_seconds: float = 0
    roll_lead_days: float = 1
    max_rate_age_days: float = 7
    settlement_interval_seconds: float = 86400
    spot_fixed_fee_usd: float = 0
    spot_min_fee_usd: float = 0
    futures_fixed_fee_usd: float = 0
    futures_min_fee_usd: float = 0
    futures_per_contract_fee_usd: float = 0
    half_spread_bps: float = 0
    slippage_bps: float = 0
    proxy_expense_rate: float = 0
    economics_payload: dict = field(default_factory=dict)

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == "economics_payload":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"paired_{name} must be finite and nonnegative")
        for name in ("max_transfer_fraction", "max_legging_seconds", "max_unpaired_btc",
                     "max_quote_age_seconds", "settlement_interval_seconds", "max_rate_age_days"):
            if getattr(self, name) <= 0:
                raise ValueError(f"paired_{name} must be positive")
        if self.max_transfer_fraction > 1 or self.cash_reserve_fraction >= 1:
            raise ValueError("Paired fractions require 0 < maximum <= 1 and 0 <= reserve < 1")
        if self.price_limit_bps >= 10000:
            raise ValueError("paired_price_limit_bps must be below 10000")

    @classmethod
    def from_payload(cls, payload, merged=None, p=None):
        source = {**(merged or {}), **(payload or {})}
        economic_keys = {"horizon_days", "horizons_days", "max_horizon_days", "uncertainty_bps",
                         "cost_buffer_multiplier", "min_gain_btc", "settlement_basis_bps"}
        allowed = set(cls.__dataclass_fields__) - {"economics_payload", "half_spread_bps", "slippage_bps", "proxy_expense_rate"}
        unknown = {k for k in source if k.startswith("paired_") and k[7:] not in allowed | economic_keys}
        if unknown:
            raise ValueError("Unsupported paired setting: " + ", ".join(sorted(unknown)))
        values = {key: float(source["paired_" + key]) for key in allowed if "paired_" + key in source}
        if "max_quote_age_seconds" not in values:
            age = getattr(p, "max_quote_age_seconds", source.get("max_quote_age_seconds"))
            if age is not None:
                values["max_quote_age_seconds"] = float(age)
        values["economics_payload"] = {k: v for k, v in source.items() if k.startswith("paired_")}
        for cost in ("half_spread_bps", "slippage_bps"):
            values[cost] = float(getattr(p, cost, source.get(cost, 0)))
        values["proxy_expense_rate"] = float(getattr(p, "slv_expense", float(source.get("slv_expense", 0))/100))
        result = cls(**values)
        # Parse economics here too, before a durable job is accepted.
        result.economics_config()
        return result

    def economics_config(self):
        from paired_transfer_economics import EconomicsConfig
        parsed = EconomicsConfig.from_payload({**self.economics_payload,
            "paired_max_transfer_fraction": self.max_transfer_fraction,
            "paired_cash_reserve_fraction": self.cash_reserve_fraction,
            "paired_price_limit_bps": self.price_limit_bps,
            "paired_settlement_interval_seconds": self.settlement_interval_seconds})
        return replace(parsed, half_spread_bps=self.half_spread_bps,
                       slippage_bps=self.slippage_bps, proxy_expense_rate=self.proxy_expense_rate,
                       max_quote_age_seconds=self.max_quote_age_seconds,
                       max_quote_skew_seconds=self.max_quote_skew_seconds)


@dataclass
class PairedOrder:
    identifier: int
    pair_id: str
    role: str
    symbol: str
    signed_btc: float
    submitted_us: int
    eligible_us: int
    limit_price: float
    filled_btc: float = 0
    filled_value: float = 0
    fee_usd: float = 0
    active: bool = True


@dataclass
class Transfer:
    pair_id: str
    source_symbol: str
    target_symbol: str
    source_quantity_btc: float
    target_quantity_btc: float
    submitted_us: int
    decision: dict
    source_order_id: int
    target_order_id: int
    status: str = "pending"
    source_filled_btc: float = 0
    target_filled_btc: float = 0
    source_value_usd: float = 0
    target_value_usd: float = 0
    fees_usd: float = 0
    matched_source_value_usd: float = 0
    unmatched_source_lots: list = field(default_factory=list)
    reserved_usd: float = 0
    first_unpaired_us: int | None = None
    max_unpaired_btc: float = 0
    max_legging_us: int = 0
    completed_us: int | None = None
    reason: str = "economic_surplus"

    @property
    def ratio(self):
        return self.target_quantity_btc / self.source_quantity_btc

    @property
    def matched_source_btc(self):
        return min(self.source_filled_btc, self.target_filled_btc / self.ratio)

    @property
    def unpaired_btc(self):
        return max(0, self.source_filled_btc - self.matched_source_btc)


class PairedTransferAccount:
    """TapeAccount-compatible adapter with a separate self-financing ledger.

    Only one transfer may reserve resources at once. Source sales/closures are
    actual fills before the target can be submitted. Each next source chunk waits
    until the preceding target and all relevant acknowledgements are complete.
    A timeout stops new source exposure; its funded target remains a recovery
    order with the original price limit, and all unresolved quantities remain in
    the audit. Missing liquidity cannot be made atomic by the simulator.
    """
    def __init__(self, capital, participation=1.0, delay_us=0, fee_bps=0,
                 sink=None, config=None, expiries=None):
        if not math.isfinite(capital) or capital <= 0:
            raise ValueError("Positive finite capital required")
        if not math.isfinite(participation) or not 0 < participation <= 1:
            raise ValueError("Participation must be in (0, 1]")
        if not isinstance(delay_us, (int, float)) or not math.isfinite(delay_us) or delay_us < 0:
            raise ValueError("Delay must be finite and nonnegative")
        if not math.isfinite(fee_bps) or fee_bps < 0:
            raise ValueError("Fees must be finite and nonnegative")
        self.initial, self.participation = float(capital), float(participation)
        self.delay_us, self.fee = int(delay_us), fee_bps / 10000
        self.config = config if isinstance(config, PairedConfig) else PairedConfig(**(config or {}))
        self.expiries = dict(expiries or {})
        self.sink = sink or (lambda row: None)
        self.last_us, self.rate = None, 0.0
        self.marks, self.observed_marks, self.observed_available_us = {}, {}, {}
        self.orders, self.pairs = {}, {}
        self.active_pair_id = None
        self.order_id = self.pair_sequence = self.queue_sequence = 0
        self.feed_queue, self.response_queue = [], []
        self.known_units = {}
        self.fill_count = self.order_count = self.cancellation_count = self.delayed_fill_count = 0
        self.turnover = self.plot_spot_pnl = self.plot_futures_pnl = 0.0
        self.plot_treasury_index = 1.0
        self.decision_count = self.rejected_count = self.no_trade_count = self.timeout_count = 0
        self.latest_decision = None
        self.finalized = dict(count=0, completed=0, partial=0, cancelled=0,
                              matched_source_btc=0.0, requested_source_btc=0.0,
                              max_unpaired_btc=0.0, max_legging_seconds=0.0)
        self.last_reason = "initial"
        self._ledger_clock = None
        self.fee_schedules = {
            "spot": FeeSchedule(fee_bps=fee_bps, fixed=self.config.spot_fixed_fee_usd,
                                minimum=self.config.spot_min_fee_usd),
            "futures": FeeSchedule(fee_bps=fee_bps, fixed=self.config.futures_fixed_fee_usd,
                                   minimum=self.config.futures_min_fee_usd,
                                   per_unit=self.config.futures_per_contract_fee_usd),
            "delivery": FeeSchedule(),
        }
        self.ledger = FundedLedger(capital, fee_schedules=self.fee_schedules,
                                   cash_interest_proxy=True, sink=self._ledger_event)
        for symbol in self.expiries:
            self._ensure_contract(symbol)

    def _ledger_event(self, row):
        row = dict(row)
        if row.get("kind") in ("fill", "valuation_mark", "funding_interest", "interest", "custody_expense"):
            # Valuations carry cumulative exact amounts and mark provenance;
            # a 90-day tape is not copied into a second per-print ledger journal.
            return
        row.setdefault("us", row.get("timestamp_us") or self._ledger_clock or self.last_us or 0)
        if self.active_pair_id:
            row.setdefault("pair_id", self.active_pair_id)
        self.sink(row)

    def _ensure_contract(self, symbol):
        if symbol != "SPOT" and symbol not in self.ledger.contracts:
            self.ledger.register_contract(ContractSpec(symbol))

    @property
    def units(self):
        return self.ledger.units

    @property
    def cash(self):
        return self.ledger.cash

    @property
    def nav(self):
        return self.ledger.nav

    @property
    def collateral(self):
        return self.ledger.collateral

    @property
    def fees(self):
        return self.ledger.fees

    @property
    def interest(self):
        return self.ledger.interest

    @property
    def funding_equity(self):
        return (self.cash + self.ledger.treasury_value + self.ledger.unrealized_pnl_usd()
                + sum(x["amount_usd"] for x in self.ledger.pending_variation.values())
                - self.ledger.liabilities_usd)

    @property
    def free_collateral(self):
        return self.funding_equity-self.collateral

    def valuation_state(self):
        spot = self.marks.get("SPOT")
        pair = self.pairs.get(self.active_pair_id)
        return dict(direct_btc_value_usd=self.units.get("SPOT", 0)*(spot.price if spot else 0),
                    free_cash_usd=self.ledger.free_cash_usd,
                    posted_cash_usd=self.ledger.posted_cash_usd,
                    unsettled_pnl_usd=self.ledger.unrealized_pnl_usd(),
                    pending_variation_usd=sum(x["amount_usd"] for x in self.ledger.pending_variation.values()),
                    reserved_cash_usd=sum(self.ledger.reservations.values()),
                    available_cash_usd=self.ledger.available_cash,
                    treasury_value_usd=self.ledger.treasury_value,
                    liabilities_usd=self.ledger.liabilities_usd,
                    commodity_nav_btc=self.nav/spot.price if spot else None,
                    active_pair_id=self.active_pair_id,
                    transfer_status=pair.status if pair else None,
                    unpaired_btc=pair.unpaired_btc if pair else 0)

    @property
    def market_pnl(self):
        return self.plot_spot_pnl + self.plot_futures_pnl

    def reconstruction_error(self):
        return self.nav - (self.initial + self.market_pnl + self.interest - self.fees)

    def _queue_observation(self, trade):
        delay = self.config.spot_feed_delay_seconds if trade.symbol == "SPOT" else self.config.futures_feed_delay_seconds
        available = trade.us + round(delay * 1e6)
        self.queue_sequence += 1
        heapq.heappush(self.feed_queue, (available, self.queue_sequence, asdict(trade)))

    @staticmethod
    def _source_us(trade):
        return trade.us if trade.reported_us is None else trade.reported_us

    def _drain_queues(self, us):
        while self.feed_queue and self.feed_queue[0][0] <= us:
            available, _, data = heapq.heappop(self.feed_queue)
            trade = Trade(**data)
            previous = self.observed_marks.get(trade.symbol)
            # Late observations may be recorded, but cannot rewind signal time.
            if previous is None or (self._source_us(trade), trade.us) >= (self._source_us(previous), previous.us):
                self.observed_marks[trade.symbol] = trade
                self.observed_available_us[trade.symbol] = available
        while self.response_queue and self.response_queue[0][0] <= us:
            available, _, data = heapq.heappop(self.response_queue)
            symbol = data["symbol"]
            self.known_units[symbol] = self.known_units.get(symbol, 0) + data["signed_btc"]
            kind = "settlement_acknowledgement" if data.get("response_kind") == "settlement" else "fill_acknowledgement"
            self.sink(dict(kind=kind, us=available, **data))
            pair = self.pairs.get(data["pair_id"])
            if pair and self.active_pair_id == pair.pair_id:
                target = self.orders.get(pair.target_symbol)
                if target and not target.active and pair.unpaired_btc > EPS:
                    target.active = True
                    target.eligible_us = available + self.delay_us
                    self.sink(dict(kind="order_activation", us=available, pair_id=pair.pair_id,
                                   order_id=target.identifier, symbol=target.symbol,
                                   eligible_after_us=target.eligible_us))
        self._maybe_complete(us)

    def bootstrap_observations(self):
        """Seed pre-window exchange marks into their original availability clocks."""
        self.feed_queue = []
        self.observed_marks = {}
        self.observed_available_us = {}
        for mark in sorted(self.marks.values(), key=lambda t: (t.us, t.symbol)):
            self._ensure_contract(mark.symbol)
            self.ledger.mark(mark.symbol, mark.price, timestamp_us=mark.us)
            self._queue_observation(mark)
        if self.last_us is not None:
            self._drain_queues(self.last_us)

    def initialize_spot(self, trade):
        if self.units.get("SPOT", 0) or self.marks.get("SPOT"):
            raise ValueError("Spot already initialized")
        if trade.price <= 0 or not math.isfinite(trade.price):
            raise ValueError("Spot price must be positive and finite")
        self.last_us = self._ledger_clock = trade.us
        self.marks["SPOT"] = trade
        self.ledger.initialize_spot(self.initial / trade.price, trade.price)
        self.known_units = dict(self.units)
        self.bootstrap_observations()
        self.sink(dict(kind="initial_holding", us=trade.us, btc=self.units["SPOT"],
                       price=trade.price, trade_id=trade.identifier))

    def accrue(self, us):
        if self.last_us is not None and us < self.last_us:
            raise ValueError("Events must be chronological")
        if self.last_us is not None:
            interval = max(1, round(self.config.settlement_interval_seconds * 1e6))
            boundary = (self.last_us // interval + 1) * interval
            cursor = self.last_us
            while boundary <= us:
                self._ledger_clock = boundary
                self._accrue_interval((boundary - cursor) / 1e6)
                self.plot_treasury_index *= math.exp(self.rate * (boundary - cursor) / YEAR_US)
                for symbol, quantity in list(self.units.items()):
                    if symbol != "SPOT" and quantity > EPS and symbol in self.marks:
                        self.ledger.settle_variation(symbol, self.marks[symbol].price,
                                                     available=True, timestamp_us=boundary)
                cursor, boundary = boundary, boundary + interval
            self._ledger_clock = us
            self._accrue_interval((us - cursor) / 1e6)
            self.plot_treasury_index *= math.exp(self.rate * (us - cursor) / YEAR_US)
        self.last_us = self._ledger_clock = us
        self._drain_queues(us)
        self._check_timeout(us)

    def _accrue_interval(self, seconds):
        self.ledger.accrue(seconds, self.rate)
        if self.config.proxy_expense_rate and seconds:
            before = self.units.get("SPOT", 0)
            self.ledger.accrue_spot_expense(seconds, self.config.proxy_expense_rate)
            self.known_units["SPOT"] = max(0, self.known_units.get("SPOT", 0)-before+self.units.get("SPOT", 0))

    def observed_quotes(self, us=None):
        from paired_transfer_economics import QuoteSnapshot
        if us is not None:
            self._drain_queues(us)
        return {s: QuoteSnapshot(symbol=s, price=t.price, source_us=self._source_us(t),
                                available_us=self.observed_available_us[s],
                                expiry_us=self.expiries.get(s), size_btc=None)
                for s, t in self.observed_marks.items()}

    def _fresh_pair(self, us, source, target):
        marks = [self.observed_marks.get(s) for s in ("SPOT", source, target)]
        if any(m is None for m in marks):
            return False, "missing_observation"
        if any(not m.executable for m in marks):
            return False, "non_executable_observation"
        times = [self._source_us(m) for m in marks]
        if any(t > us or us - t > self.config.max_quote_age_seconds * 1e6 for t in times):
            return False, "stale_observation"
        if max(times) - min(times) > self.config.max_quote_skew_seconds * 1e6:
            return False, "observation_skew"
        if any(self.expiries.get(s, us + 1) <= us for s in (source, target) if s != "SPOT"):
            return False, "expired_contract"
        return True, "fresh"

    def decide(self, us, expiries=None, rate_snapshot=None, candidate=None):
        """Compare incremental common-horizon wealth; KEEP preserves live pairs."""
        self.accrue(us)
        if expiries is not None:
            self.expiries.update(expiries)
        self.decision_count += 1
        if self.active_pair_id is not None or self.response_queue:
            self._reevaluate_pending(us, rate_snapshot)
            return None
        rate_permitted = True
        if rate_snapshot is not None:
            permits = getattr(rate_snapshot, "allows_new_transfers", None)
            if permits is None and isinstance(rate_snapshot, dict):
                permits = rate_snapshot.get("allows_new_transfers", not rate_snapshot.get("stale", False))
            if permits is False:
                self.last_reason = "stale_treasury_rate"
                rate_permitted = False
        if candidate is not None:
            return self.start_transfer(us, candidate)
        from paired_transfer_economics import PositionSlice, evaluate_transfer
        quotes = self.observed_quotes()
        spot = quotes.get("SPOT")
        if spot is None:
            self.last_reason = "missing_spot_observation"
            self.no_trade_count += 1
            return None
        config = self.config.economics_config()
        candidates = []
        held = self.units
        for source_symbol, quantity in sorted(held.items()):
            if quantity <= EPS or source_symbol not in quotes:
                continue
            source_quote = quotes[source_symbol]
            risk_exit = (source_symbol != "SPOT" and source_quote.expiry_us-us <= self.config.roll_lead_days*86400e6)
            if not rate_permitted and not risk_exit:
                continue
            source_cash = (0 if source_symbol == "SPOT" else
                           sum(lot.quantity*lot.reference_price for lot in self.ledger.lots.get(source_symbol, [])))
            # Own fill/settlement references are known; unreceived market marks
            # must not enter the discretionary forecast through hidden U(t).
            unsettled = 0 if source_symbol == "SPOT" else quantity*source_quote.price-source_cash
            source_cash = min(self.cash, source_cash)
            source = PositionSlice(source_quote, quantity, source_cash, unsettled)
            for target_symbol, target in sorted(quotes.items()):
                if source_symbol == target_symbol:
                    continue
                if not rate_permitted and target_symbol != "SPOT":
                    continue
                valid, reason = self._fresh_pair(us, source_symbol, target_symbol)
                if not valid:
                    self.last_reason = reason
                    continue
                if target_symbol != "SPOT" and target.expiry_us - us <= self.config.roll_lead_days * 86400e6:
                    continue
                decision = evaluate_transfer(us, source, target, spot, cash_rate=self.rate,
                    fees=self.fee_schedules,
                    config=replace(config, max_transfer_fraction=1, size_fractions=(1,)) if risk_exit else config)
                data = decision.to_dict() if hasattr(decision, "to_dict") else asdict(decision)
                data["rate_snapshot"] = (rate_snapshot.as_dict() if hasattr(rate_snapshot, "as_dict")
                                         else rate_snapshot)
                data["cash_rate"] = self.rate
                if (risk_exit and data.get("horizon_us") is not None and data.get("target_quantity_btc", 0) > EPS
                        and data.get("diagnostics", {}).get("swap", {}).get("funding_feasible", False)):
                    data["accepted"] = True
                    data["reason"] = "forced_expiry_exit"
                    data["diagnostics"]["risk_override"] = "configured_roll_lead"
                candidates.append(data)
        accepted = [d for d in candidates if d.get("accepted")]
        if not accepted:
            self.no_trade_count += 1
            self.last_reason = "no_net_gain" if candidates else self.last_reason
            self.latest_decision = max(candidates, key=lambda x: x.get("edge_btc", -math.inf), default=None)
            if self.latest_decision:
                self.sink(dict(kind="paired_decision", us=us, selected=False,
                               candidates_evaluated=len(candidates), decision=self.latest_decision))
            return None
        forced = [d for d in accepted if d.get("reason") == "forced_expiry_exit"]
        selected = max(forced or accepted, key=lambda d: (d["edge_btc"], -d["horizon_us"], d["target_symbol"]))
        self.latest_decision = selected
        self.sink(dict(kind="paired_decision", us=us, selected=True,
                       candidates_evaluated=len(candidates), decision=selected))
        return self.start_transfer(us, selected)

    def _reevaluate_pending(self, us, rate_snapshot):
        pair = self.pairs.get(self.active_pair_id)
        self.last_reason = "pending_transfer"
        if (pair is None or pair.status != "pending" or self._pair_has_responses(pair.pair_id)
                or pair.reason == "forced_expiry_exit"):
            return
        remaining = pair.source_quantity_btc-pair.source_filled_btc
        if remaining <= EPS:
            return
        valid, reason = self._fresh_pair(us, pair.source_symbol, pair.target_symbol)
        if not valid:
            self.last_reason = "pending_" + reason
            return  # Freshness gates source fills without erasing inventory.
        permits = getattr(rate_snapshot, "allows_new_transfers", True)
        if isinstance(rate_snapshot, dict):
            permits = rate_snapshot.get("allows_new_transfers", not rate_snapshot.get("stale", False))
        if not permits:
            self._stop_source(us, "stale_treasury_rate")
            return
        from paired_transfer_economics import PositionSlice, IncrementalFeeSchedule, evaluate_transfer
        quotes = self.observed_quotes()
        source_quote = quotes[pair.source_symbol]
        held = self.units.get(pair.source_symbol, 0)
        remaining = min(remaining, held)
        reference = (0 if pair.source_symbol == "SPOT" else
                     sum(l.quantity*l.reference_price for l in self.ledger.lots.get(pair.source_symbol, [])))
        source_cash = 0 if pair.source_symbol == "SPOT" else reference*remaining/held
        unsettled = 0 if pair.source_symbol == "SPOT" else remaining*source_quote.price-source_cash
        entry_fees = {}
        for role, symbol in (("source", pair.source_symbol), ("target", pair.target_symbol)):
            order = self.orders[symbol]
            product = "spot" if symbol == "SPOT" else "futures"
            entry_fees[role] = IncrementalFeeSchedule(self.fee_schedules[product], order.filled_btc,
                                                      order.filled_value, order.fee_usd)
        data = evaluate_transfer(us, PositionSlice(source_quote, remaining, source_cash, unsettled),
            quotes[pair.target_symbol], quotes["SPOT"], cash_rate=self.rate,
            fees=self.fee_schedules, entry_fees=entry_fees,
            config=replace(self.config.economics_config(), max_transfer_fraction=1, size_fractions=(1,)),
            target_quantity_btc=remaining*pair.ratio,
            execution_price_overrides={"source": self.orders[pair.source_symbol].limit_price,
                                       "target": self.orders[pair.target_symbol].limit_price},
            comparison_horizon_us=pair.decision.get("horizon_us"),
            horizon_limit_us=pair.decision.get("horizon_us")).to_dict()
        self.sink(dict(kind="paired_decision", us=us, pair_id=pair.pair_id,
                       selected=data["accepted"], remaining_quantity=True, decision=data))
        if not data["accepted"]:
            self._stop_source(us, "remaining_"+data["reason"])


    def start_transfer(self, us, decision=None, **kwargs):
        """Submit one immutable accepted decision; caller cannot replace a pair."""
        self.accrue(us)
        data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or kwargs)
        if not data.get("accepted", True):
            self.last_reason = data.get("reason", "economic_rejection")
            return None
        source, target = data["source_symbol"], data["target_symbol"]
        source_qty = float(data["source_quantity_btc"])
        target_qty = float(data["target_quantity_btc"])
        if source == target or not all(math.isfinite(q) and q > EPS for q in (source_qty, target_qty)):
            raise ValueError("Paired transfer requires distinct symbols and positive finite sizes")
        if self.active_pair_id is not None or self.response_queue:
            self.last_reason = "pending_transfer"
            self.rejected_count += 1
            return None
        valid, reason = self._fresh_pair(us, source, target)
        if not valid or source_qty > self.units.get(source, 0) + EPS:
            self.last_reason = reason if not valid else "insufficient_source_inventory"
            self.rejected_count += 1
            return None
        probe = FundedLedger.restore(self.ledger.snapshot())
        source_pad = (self.config.price_limit_bps+self.config.half_spread_bps+self.config.slippage_bps)/10000
        try:
            probe.execute_fill(source, -min(source_qty, self.config.max_unpaired_btc),
                               self.observed_marks[source].price*(1-source_pad), "source-preflight")
        except FundingError:
            self.last_reason = "first_chunk_unfunded"
            self.rejected_count += 1
            self.sink(dict(kind="paired_decision", us=us, selected=False,
                           decision={**data, "accepted": False, "reason": self.last_reason}))
            return None
        self.pair_sequence += 1
        pair_id = f"pair-{self.pair_sequence}"
        source_order_id, target_order_id = self.order_id + 1, self.order_id + 2
        self.order_id += 2
        data = {**data, "quote_kind": "last_trade_participation_proxy", "quote_snapshots": {
            s: dict(price=self.observed_marks[s].price, source_us=self._source_us(self.observed_marks[s]),
                    available_us=self.observed_available_us[s],
                    source_age_us=us-self._source_us(self.observed_marks[s]),
                    observed_trade_btc=self.observed_marks[s].btc)
            for s in {"SPOT", source, target}}}
        pair = Transfer(pair_id, source, target, source_qty, target_qty, us, data,
                        source_order_id, target_order_id)
        pair.reason = data.get("reason", "economic_surplus")
        self.pairs[pair_id] = pair
        self.active_pair_id = pair_id
        pad = (self.config.price_limit_bps+self.config.half_spread_bps+self.config.slippage_bps) / 10000
        self.orders[source] = PairedOrder(source_order_id, pair_id, "source", source,
            -source_qty, us, us + self.delay_us, self.observed_marks[source].price * (1-pad))
        self.orders[target] = PairedOrder(target_order_id, pair_id, "target", target,
            target_qty, us, us + self.delay_us, self.observed_marks[target].price * (1+pad), active=False)
        self.order_count += 2
        self.sink(dict(kind="paired_transfer", us=us, **asdict(pair)))
        for order in self.orders.values():
            self.sink(dict(kind="order", us=us, order_id=order.identifier, pair_id=pair_id,
                           symbol=order.symbol, signed_btc=order.signed_btc,
                           eligible_after_us=order.eligible_us, role=order.role,
                           limit_price=order.limit_price, conditional=not order.active))
        self.last_reason = "transfer_submitted"
        return pair

    def _pair_has_responses(self, pair_id):
        return any(item[2]["pair_id"] == pair_id for item in self.response_queue)

    def _check_timeout(self, us):
        pair = self.pairs.get(self.active_pair_id)
        if not pair:
            return
        if pair.first_unpaired_us is not None:
            pair.max_legging_us = max(pair.max_legging_us, us-pair.first_unpaired_us)
        if pair.status == "pending":
            clock = pair.first_unpaired_us
            reason = "legging_timeout"
            if clock is None and pair.source_filled_btc <= EPS:
                clock, reason = pair.submitted_us, "unfilled_timeout"
            if clock is not None and us-clock > self.config.max_legging_seconds * 1e6:
                self.timeout_count += 1
                self._stop_source(us, reason)

    def _stop_source(self, us, reason):
        pair = self.pairs.get(self.active_pair_id)
        if not pair:
            return
        source = self.orders.get(pair.source_symbol)
        if source and source.active:
            source.active = False
            self.cancellation_count += int(abs(source.signed_btc)-source.filled_btc > EPS)
        pair.reason = reason
        pair.status = "timed_out" if reason in ("legging_timeout", "unfilled_timeout") else "cancelled"
        self.sink(dict(kind="pair_risk_limit", us=us, pair_id=pair.pair_id, reason=reason,
                       unpaired_btc=pair.unpaired_btc, reserved_usd=pair.reserved_usd))
        self._maybe_complete(us)

    def _maybe_complete(self, us):
        pair = self.pairs.get(self.active_pair_id)
        if not pair or self._pair_has_responses(pair.pair_id):
            return
        filled = pair.source_filled_btc >= pair.source_quantity_btc - EPS
        halted = pair.status in ("cancelled", "timed_out")
        if pair.unpaired_btc > EPS or not (filled or halted):
            return
        pair.status = "completed" if filled else ("partial" if pair.source_filled_btc > EPS else pair.status)
        pair.completed_us = us
        self.ledger.release(pair.pair_id)
        pair.reserved_usd = 0
        self._emit_pair_result(pair, us)
        self.orders.clear()
        self.active_pair_id = None
        self._archive_pair(pair)

    def _archive_pair(self, pair):
        """Closed IDs cannot be reused; their detailed history is in the audit."""
        totals = self.finalized
        totals["count"] += 1
        if pair.status in ("completed", "partial", "cancelled"):
            totals[pair.status] += 1
        totals["matched_source_btc"] += pair.matched_source_btc
        totals["requested_source_btc"] += pair.source_quantity_btc
        totals["max_unpaired_btc"] = max(totals["max_unpaired_btc"], pair.max_unpaired_btc)
        totals["max_legging_seconds"] = max(totals["max_legging_seconds"], pair.max_legging_us/1e6)
        for role in ("source", "target"):
            self.ledger.fee_engine.tickets.pop(f"{pair.pair_id}:{role}", None)
        self.pairs.pop(pair.pair_id, None)

    def _emit_pair_result(self, pair, us):
        data = asdict(pair)
        data.update(matched_source_btc=pair.matched_source_btc,
                    unpaired_btc=pair.unpaired_btc,
                    paired_fill_ratio=pair.matched_source_btc/pair.source_quantity_btc,
                    max_legging_seconds=pair.max_legging_us/1e6)
        if pair.matched_source_btc > EPS:
            source_vwap = pair.matched_source_value_usd / pair.matched_source_btc
            target_vwap = pair.target_value_usd / pair.target_filled_btc
            snapshots = pair.decision.get("quote_snapshots", {})
            if pair.source_symbol == "SPOT" or pair.target_symbol == "SPOT":
                future = pair.target_symbol if pair.source_symbol == "SPOT" else pair.source_symbol
                maturity = (self.expiries.get(future, pair.submitted_us) - pair.submitted_us) / YEAR_US
                if maturity > 0:
                    sf = target_vwap if pair.source_symbol == "SPOT" else source_vwap
                    ss = source_vwap if pair.source_symbol == "SPOT" else target_vwap
                    rate_data = pair.decision.get("rate_snapshot") or {}
                    fixed_rate = rate_data.get("annual_rate", pair.decision.get("cash_rate", self.rate))
                    observed = fixed_rate - (snapshots[future]["price"]/snapshots["SPOT"]["price"]-1)/maturity
                    executed = fixed_rate - (sf/ss-1)/maturity
                    data.update(observed_lease=observed, executed_price_only_lease=executed,
                                lease_price_deviation=executed-observed,
                                direction_adjusted_lease_deviation=(executed-observed)*(1 if pair.source_symbol == "SPOT" else -1))
                    remaining = (self.expiries[future]-us)/YEAR_US
                    data["completion_lease"] = self.rate-(sf/ss-1)/remaining if remaining > 0 else None
        self.sink(dict(kind="paired_transfer_result", us=us, **data))

    def on_trade(self, trade):
        if not all(math.isfinite(x) and x > 0 for x in (trade.price, trade.btc)):
            raise ValueError("Trade requires positive finite price and volume")
        if trade.side not in ("buy", "sell"):
            raise ValueError("Unknown aggressor side")
        previous = self.marks.get(trade.symbol)
        if previous and (trade.us < previous.us or trade.identifier == previous.identifier):
            raise ValueError("Duplicate or out-of-order print")
        self.accrue(trade.us)
        self._ensure_contract(trade.symbol)
        held = self.units.get(trade.symbol, 0)
        pnl = held * (trade.price-previous.price) if previous else 0
        if trade.symbol == "SPOT":
            self.plot_spot_pnl += pnl
        else:
            self.plot_futures_pnl += pnl
        self.marks[trade.symbol] = trade
        self.ledger.mark(trade.symbol, trade.price, timestamp_us=trade.us)
        self._queue_observation(trade)
        self._drain_queues(trade.us)
        self._execute(trade)

    def _execute(self, trade):
        pair = self.pairs.get(self.active_pair_id)
        order = self.orders.get(trade.symbol)
        if not pair or not order or not order.active or not trade.executable or trade.us <= order.eligible_us:
            return
        if self._pair_has_responses(pair.pair_id):
            return
        buying = order.signed_btc > 0
        if trade.side != ("buy" if buying else "sell"):
            return
        adjustment = (self.config.half_spread_bps+self.config.slippage_bps)/10000
        fill_price = trade.price*(1+adjustment if buying else 1-adjustment)
        if (buying and fill_price > order.limit_price) or (not buying and fill_price < order.limit_price):
            return
        available = min(abs(order.signed_btc)-order.filled_btc, trade.btc*self.participation)
        if order.role == "source":
            if pair.status != "pending":
                return
            valid, _ = self._fresh_pair(trade.us, pair.source_symbol, pair.target_symbol)
            if not valid:
                return
            available = min(available, max(0, self.config.max_unpaired_btc-pair.unpaired_btc), self.units.get(trade.symbol, 0))
        else:
            available = min(available, pair.source_filled_btc*pair.ratio-pair.target_filled_btc)
        if available <= EPS:
            return
        ticket = f"{pair.pair_id}:{order.role}"
        signed = available if buying else -available
        before_available = self.ledger.available_cash
        try:
            fee = self.ledger.execute_fill(trade.symbol, signed, fill_price, ticket,
                                          timestamp_us=trade.us, reservation_id=pair.pair_id)
        except FundingError:
            # Find the actual affordable fraction without mutating failed trades.
            low, high = 0.0, available
            state = self.ledger.snapshot()
            for _ in range(45):
                mid = (low+high)/2
                probe = FundedLedger.restore(state)
                try:
                    probe.execute_fill(trade.symbol, mid if buying else -mid, fill_price,
                                       ticket, timestamp_us=trade.us, reservation_id=pair.pair_id)
                    low = mid
                except FundingError:
                    high = mid
            if low <= EPS:
                return
            available, signed = low, low if buying else -low
            fee = self.ledger.execute_fill(trade.symbol, signed, fill_price, ticket,
                                          timestamp_us=trade.us, reservation_id=pair.pair_id)
        self.ledger.mark(trade.symbol, trade.price, timestamp_us=trade.us)
        execution_pnl = -signed*(fill_price-trade.price)
        if trade.symbol == "SPOT":
            self.plot_spot_pnl += execution_pnl
        else:
            self.plot_futures_pnl += execution_pnl
        order.filled_btc += available
        order.filled_value += available*fill_price
        order.fee_usd += fee
        pair.fees_usd += fee
        if order.role == "source":
            pair.source_filled_btc += available
            pair.source_value_usd += available*fill_price
            pair.unmatched_source_lots.append([available, fill_price])
            if pair.first_unpaired_us is None:
                pair.first_unpaired_us = trade.us
            # Reserve only money actually released by this exchange-side fill.
            released = max(0, self.ledger.available_cash-before_available)
            pair.reserved_usd += released
            if pair.reserved_usd > EPS:
                self.ledger.reserve(pair.pair_id, pair.reserved_usd)
            self.orders[pair.target_symbol].active = False
        else:
            pair.target_filled_btc += available
            pair.target_value_usd += available*fill_price
            to_match = available/pair.ratio
            while to_match > EPS and pair.unmatched_source_lots:
                lot = pair.unmatched_source_lots[0]
                matched = min(to_match, lot[0])
                pair.matched_source_value_usd += matched*lot[1]
                lot[0] -= matched
                to_match -= matched
                if lot[0] <= EPS:
                    pair.unmatched_source_lots.pop(0)
            # The ledger's reservation tracks actual remaining free funds.
            pair.reserved_usd = max(0, pair.reserved_usd-available*fill_price-fee)
            self.ledger.release(pair.pair_id)
            if pair.reserved_usd > EPS:
                self.ledger.reserve(pair.pair_id, min(pair.reserved_usd, self.ledger.available_cash))
            pair.reserved_usd = self.ledger.reservations.get(pair.pair_id, 0)
            if pair.unpaired_btc <= EPS:
                if pair.first_unpaired_us is not None:
                    pair.max_legging_us = max(pair.max_legging_us, trade.us-pair.first_unpaired_us)
                pair.first_unpaired_us = None
        pair.max_unpaired_btc = max(pair.max_unpaired_btc, pair.unpaired_btc)
        self.turnover += available*fill_price
        self.fill_count += 1
        self.delayed_fill_count += int(trade.reported_us is not None and trade.us > trade.reported_us)
        ack_at = trade.us + round(self.config.response_delay_seconds*1e6)
        self.queue_sequence += 1
        heapq.heappush(self.response_queue, (ack_at, self.queue_sequence,
            dict(pair_id=pair.pair_id, order_id=order.identifier, symbol=trade.symbol,
                 signed_btc=signed, exchange_fill_us=trade.us)))
        self.sink(dict(kind="fill", us=trade.us, pair_id=pair.pair_id,
                       order_id=order.identifier, ticket_id=ticket, trade_id=trade.identifier,
                       symbol=trade.symbol, role=order.role, side=trade.side,
                       reported_us=self._source_us(trade), source_sequence=trade.sequence,
                       signed_btc=signed, price=fill_price, raw_trade_price=trade.price, observed_btc=trade.btc,
                       fee_usd=fee, cash_usd=self.cash, nav_usd=self.nav,
                       acknowledgement_us=ack_at, reserved_usd=pair.reserved_usd,
                       unpaired_btc=pair.unpaired_btc))
        self._drain_queues(trade.us)

    def cancel(self, us, reason="cancelled", symbols=None):
        self.accrue(us)
        pair = self.pairs.get(self.active_pair_id)
        if not pair or (symbols is not None and not {pair.source_symbol, pair.target_symbol} & set(symbols)):
            return
        self._stop_source(us, reason)
        # Unmatched fills cannot be erased. Preserve their recovery order and
        # reservation, even when end-of-window/expiry prevents further fills.
        if reason in ("end_of_window", "expiry") and self.active_pair_id:
            for order in self.orders.values():
                order.active = False
            self._emit_pair_result(pair, us)

    def settle(self, symbol, us, price, source):
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid verified delivery price")
        self.accrue(us)
        self.cancel(us, "expiry", {symbol})
        quantity = self.units.get(symbol, 0)
        previous = self.marks.get(symbol)
        if quantity and previous:
            self.plot_futures_pnl += quantity*(price-previous.price)
        self._ensure_contract(symbol)
        self.ledger.settle_expiry(symbol, price, timestamp_us=us)
        self.marks[symbol] = Trade(us, symbol, price, 0, "buy", "settlement:"+symbol, False)
        if quantity:
            self.queue_sequence += 1
            heapq.heappush(self.response_queue, (us+round(self.config.response_delay_seconds*1e6),
                self.queue_sequence, dict(pair_id=None, symbol=symbol, signed_btc=-quantity,
                                         exchange_fill_us=us, response_kind="settlement")))
            self._drain_queues(us)
        self.sink(dict(kind="settlement", us=us, symbol=symbol, price=price,
                       quantity_btc=quantity, source=source, nav_usd=self.nav))

    def summary(self):
        pairs = list(self.pairs.values())
        totals = self.finalized
        return dict(strategy="cost_aware_paired", submitted_pairs=totals["count"]+len(pairs),
                    completed=totals["completed"]+sum(p.status == "completed" for p in pairs),
                    partial=totals["partial"]+sum(p.status == "partial" for p in pairs),
                    cancelled=totals["cancelled"]+sum(p.status == "cancelled" for p in pairs),
                    timed_out=self.timeout_count,
                    unresolved=sum(p.unpaired_btc > EPS for p in pairs),
                    rejected=self.rejected_count, decisions=self.decision_count,
                    keep_decisions=self.no_trade_count, last_reason=self.last_reason,
                    matched_source_btc=totals["matched_source_btc"]+sum(p.matched_source_btc for p in pairs),
                    requested_source_btc=totals["requested_source_btc"]+sum(p.source_quantity_btc for p in pairs),
                    max_unpaired_btc=max([totals["max_unpaired_btc"]]+[p.max_unpaired_btc for p in pairs]),
                    max_legging_seconds=max([totals["max_legging_seconds"]]+[p.max_legging_us/1e6 for p in pairs]),
                    latest_decision=self.latest_decision,
                    actual_units=dict(self.units), known_units=dict(self.known_units),
                    pending_feed_records=len(self.feed_queue), pending_responses=len(self.response_queue),
                    reserved_usd=sum(p.reserved_usd for p in pairs),
                    execution_model="tape participation; bounded staged source-first transfers",
                    settlement_model="scheduled last-trade USD linear-proxy variation; not official venue marks")

    diagnostics = summary

    def snapshot(self):
        state = {k: v for k, v in vars(self).items()
                 if k not in ("sink", "ledger", "config", "fee_schedules", "marks", "observed_marks", "orders", "pairs")}
        state.update(schema_version=1, config=asdict(self.config), ledger=self.ledger.snapshot(),
                     marks={s: asdict(t) for s, t in self.marks.items()},
                     observed_marks={s: asdict(t) for s, t in self.observed_marks.items()},
                     orders={s: asdict(o) for s, o in self.orders.items()},
                     pairs={s: asdict(p) for s, p in self.pairs.items()})
        return copy.deepcopy(state)

    @classmethod
    def restore(cls, state, sink=None):
        state = copy.deepcopy(state)
        if state.get("schema_version") != 1:
            raise ValueError("Unsupported paired account checkpoint")
        account = cls(state["initial"], state["participation"], state["delay_us"],
                      state["fee"]*10000, sink, PairedConfig(**state["config"]), state["expiries"])
        for key, value in state.items():
            if key in ("schema_version", "config", "ledger"):
                continue
            constructor = {"marks": Trade, "observed_marks": Trade, "orders": PairedOrder, "pairs": Transfer}.get(key)
            setattr(account, key, {s: constructor(**v) for s, v in value.items()} if constructor else value)
        account.feed_queue = [tuple(row) for row in account.feed_queue]
        account.response_queue = [tuple(row) for row in account.response_queue]
        heapq.heapify(account.feed_queue)
        heapq.heapify(account.response_queue)
        account.ledger = FundedLedger.restore(state["ledger"], sink=account._ledger_event)
        return account


PairedTapeAccount = PairedTransferAccount
