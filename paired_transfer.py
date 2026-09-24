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
from rolling_lease_execution import RollingLeaseExecutionMixin, RollingPriceWindow
from funded_ledger import ContractSpec, FeeSchedule, FundedLedger, FundingError

YEAR_US = 365 * 86400 * 1_000_000
EPS = 1e-12


@dataclass
class PairedConfig:
    selection_mode: str = "horizon_wealth"
    max_transfer_fraction: float = .25
    max_delta_btc: float = .01
    min_improvement_bps: float = 5
    conservative_lease_bps: float = 0
    cash_reserve_fraction: float = .01
    max_legging_seconds: float = 30
    max_unpaired_btc: float = .01
    max_quote_age_seconds: float = 1
    max_quote_skew_seconds: float = 1
    price_limit_bps: float = 10
    repricing_mode: str = "fixed"
    limit_anchor: str = "relative_price"
    lease_window_seconds: float = 5
    lease_execution_delta_bps: float = 5
    expected_hedge_slippage_bps: float = 1
    execution_confidence: float = .95
    execution_min_samples: int = 100
    calibration_days: float = 10
    waiting_seconds: float = 30
    execution_size_grid_btc: tuple = (.0001, .001, .01, .1)
    study_max_horizon_seconds: float = 60
    observation_delay_seconds: float = 0
    decision_delay_seconds: float = 0
    order_delay_seconds: float | None = None
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
            if name in ("economics_payload", "repricing_mode", "selection_mode", "limit_anchor", "execution_size_grid_btc") or (name == "order_delay_seconds" and value is None):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"paired_{name} must be finite and nonnegative")
        if self.limit_anchor not in ("relative_price", "spot"):
            raise ValueError("paired_limit_anchor must be relative_price or spot")
        if self.repricing_mode not in ("fixed", "adaptive", "empirical", "rolling_worst"):
            raise ValueError("paired_repricing_mode must be fixed, adaptive, empirical or rolling_worst")
        if self.selection_mode not in ("horizon_wealth", "amortized_rank"):
            raise ValueError("paired_selection_mode must be horizon_wealth or amortized_rank")
        if self.selection_mode == "amortized_rank" and self.repricing_mode == "empirical":
            raise ValueError("Empirical execution is calibrated for the horizon-wealth selector only")
        if self.repricing_mode == "rolling_worst" and self.selection_mode != "amortized_rank":
            raise ValueError("Rolling worst lease execution requires amortized_rank")
        if self.lease_window_seconds < .000001 or self.expected_hedge_slippage_bps >= 10000:
            raise ValueError("Lease window must be positive and expected hedge slippage below 10000 bps")
        grid = self.execution_size_grid_btc
        if isinstance(grid, str):
            grid = tuple(float(item.strip()) for item in grid.split(",") if item.strip())
        if not grid or any(isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q) or q <= 0 for q in grid):
            raise ValueError("paired_execution_size_grid_btc requires positive finite quantities")
        self.execution_size_grid_btc = tuple(sorted(set(grid)))
        if not 0 < self.execution_confidence < 1:
            raise ValueError("paired_execution_confidence must be between zero and one")
        if self.execution_min_samples < 1 or int(self.execution_min_samples) != self.execution_min_samples:
            raise ValueError("paired_execution_min_samples must be a positive integer")
        self.execution_min_samples = int(self.execution_min_samples)
        if min(self.calibration_days, self.waiting_seconds, self.study_max_horizon_seconds) <= 0:
            raise ValueError("Paired calibration, waiting and study horizons must be positive")
        if self.waiting_seconds > self.study_max_horizon_seconds:
            raise ValueError("paired_waiting_seconds exceeds the calibrated study horizon")
        if self.repricing_mode == "empirical" and any((self.spot_fixed_fee_usd, self.spot_min_fee_usd,
                self.futures_fixed_fee_usd, self.futures_min_fee_usd, self.futures_per_contract_fee_usd)):
            raise ValueError("Empirical execution currently supports proportional fees only")
        for name in ("max_transfer_fraction", "max_delta_btc", "max_legging_seconds", "max_unpaired_btc",
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
        values = {key: (source["paired_" + key] if key in ("repricing_mode", "selection_mode", "limit_anchor", "execution_size_grid_btc") or source["paired_" + key] is None
                        else float(source["paired_" + key]))
                  for key in allowed if "paired_" + key in source}
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
            "paired_max_delta_btc": self.max_delta_btc,
            "paired_min_improvement_bps": self.min_improvement_bps,
            "paired_conservative_lease_bps": self.conservative_lease_bps,
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
    revision: int = 0
    decision_started_us: int | None = None
    decision_ready_us: int | None = None
    observation_us: int | None = None
    market_order: bool = False
    lease_context: dict = field(default_factory=dict)


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
    target_effective_lease: float | None = None
    repricing_supported: bool = False
    fill_revision: int = 0
    reprice_pending: bool = False
    reprice_dirty: bool = False
    transport_pending: int = 0
    matched_source_fee_usd: float = 0
    cancel_pending: bool = False
    funding_cap_revision: int = -1
    funding_cap_price: float = 0
    empirical: bool = False
    deadline_us: int | None = None
    first_source_fill_us: int | None = None
    first_target_fill_us: int | None = None
    last_target_fill_us: int | None = None
    outcome_recorded: bool = False
    rolling: bool = False
    rolling_lots: list = field(default_factory=list)
    matched_target_value_usd: float = 0
    matched_target_fee_usd: float = 0

    @property
    def ratio(self):
        return self.target_quantity_btc / self.source_quantity_btc

    @property
    def matched_source_btc(self):
        return min(self.source_filled_btc, self.target_filled_btc / self.ratio)

    @property
    def unpaired_btc(self):
        if self.rolling:
            return abs(self.source_filled_btc - self.target_filled_btc/self.ratio)
        return max(0, self.source_filled_btc - self.matched_source_btc)


class PairedTransferAccount(RollingLeaseExecutionMixin):
    """TapeAccount-compatible adapter with a separate self-financing ledger.

    Only one transfer may reserve resources at once. In the original modes,
    source sales/closures are actual fills before the target can be submitted.
    Rolling-worst execution also permits an already-funded target to lead. Each next source chunk waits
    until the preceding target and all relevant acknowledgements are complete.
    A timeout stops new source exposure; its funded target remains a recovery
    order, retaining its fixed limit or adapting to acknowledged execution costs
    according to the configured mode. All unresolved quantities remain in the
    audit. Missing liquidity cannot be made atomic by the simulator.
    """
    def __init__(self, capital, participation=1.0, delay_us=0, fee_bps=0,
                 sink=None, config=None, expiries=None, empirical_model=None):
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
        if self.config.order_delay_seconds is not None:
            self.delay_us = round(self.config.order_delay_seconds * 1e6)
        self.expiries = dict(expiries or {})
        if isinstance(empirical_model, dict):
            from paired_execution_study import FrozenExecutionModel
            empirical_model = FrozenExecutionModel.from_dict(empirical_model)
        self.empirical_model = empirical_model
        self.lease_window = RollingPriceWindow(self.config.lease_window_seconds)
        self.latest_lease_execution = None
        self.cash_recovery = None
        self.recovery_sequence = 0
        self.empirical_stats = dict(instructions=0, completed_by_deadline=0, deadline_failed=0,
            partial_at_deadline=0, unfilled_at_deadline=0, end_window_censored=0,
            archived_unmatched_source_btc=0.0, cash_restorations=0, cash_restored_btc=0.0,
            restoration_deadline_failed=0, restoration_residual_cash_usd=0.0,
            wait_seconds={}, latest_instruction=None)
        self.sink = sink or (lambda row: None)
        self.last_us, self.rate = None, 0.0
        self.marks, self.observed_marks, self.observed_available_us = {}, {}, {}
        self.orders, self.pairs = {}, {}
        self.active_pair_id = None
        self.order_id = self.pair_sequence = self.queue_sequence = 0
        self.feed_queue, self.response_queue = [], []
        self.decision_queue, self.command_queue = [], []
        self.pending_initial_decision = False
        self.replacement_count = 0
        self._draining = False
        self.known_units = {}
        self.fill_count = self.order_count = self.cancellation_count = self.delayed_fill_count = 0
        self.turnover = self.plot_spot_pnl = self.plot_futures_pnl = 0.0
        self.plot_treasury_index = 1.0
        self.decision_count = self.rejected_count = self.no_trade_count = self.timeout_count = 0
        self.latest_decision = None
        self.latest_pair_result = None
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
        available = trade.us + round((delay + self.config.observation_delay_seconds) * 1e6)
        self.queue_sequence += 1
        heapq.heappush(self.feed_queue, (available, self.queue_sequence, asdict(trade)))

    @staticmethod
    def _source_us(trade):
        return trade.us if trade.reported_us is None else trade.reported_us

    def _push_event(self, queue, available, data):
        self.queue_sequence += 1
        heapq.heappush(queue, (int(available), self.queue_sequence, data))

    def _drain_queues(self, us):
        # One chronological scheduler is essential: a decision completing between
        # two delayed observations must never use the later observation.
        if self._draining:
            return
        self._draining = True
        outer_ledger_clock = self._ledger_clock
        try:
            queues = (self.feed_queue, self.response_queue, self.decision_queue, self.command_queue)
            while True:
                next_event = min(((q[0][0], i) for i, q in enumerate(queues) if q and q[0][0] <= us),
                                 default=None)
                if next_event is None:
                    break
                available, index = next_event
                # Ledger reservations released by an acknowledgement/cancel
                # belong to that queued event, not the later caller's clock.
                self._ledger_clock = available
                _, _, data = heapq.heappop(queues[index])
                if index == 0:
                    trade = Trade(**data)
                    previous = self.observed_marks.get(trade.symbol)
                    if previous is None or (self._source_us(trade), trade.us) >= (self._source_us(previous), previous.us):
                        self.observed_marks[trade.symbol] = trade
                        self.observed_available_us[trade.symbol] = available
                        if self.rolling_execution:
                            self.lease_window.observe(trade.symbol, trade.price, self._source_us(trade), available)
                        pair = self.pairs.get(self.active_pair_id)
                        if pair and (trade.symbol in (pair.source_symbol, pair.target_symbol)
                                     or pair.rolling and trade.symbol == "SPOT"):
                            self._schedule_reprice(available)
                elif index == 1:
                    symbol = data["symbol"]
                    self.known_units[symbol] = self.known_units.get(symbol, 0) + data["signed_btc"]
                    kind = "settlement_acknowledgement" if data.get("response_kind") == "settlement" else "fill_acknowledgement"
                    self.sink(dict(kind=kind, us=available, **data))
                    pair = self.pairs.get(data["pair_id"])
                    if pair and self.active_pair_id == pair.pair_id:
                        target = self.orders.get(pair.target_symbol)
                        if pair.repricing_supported:
                            self._schedule_reprice(available)
                        elif target and not target.active and pair.unpaired_btc > EPS:
                            # Even an unchanged recovery instruction takes decision
                            # time before its order transport can begin.
                            ready = available + round(self.config.decision_delay_seconds * 1e6)
                            self._push_event(self.command_queue, ready + self.delay_us,
                                dict(action="activate", pair_id=pair.pair_id, order_id=target.identifier,
                                     symbol=target.symbol, decision_started_us=available, decision_ready_us=ready))
                elif index == 2:
                    self._finish_decision(available, data)
                else:
                    self._apply_command(available, data)
                self._maybe_complete(available)
            self._ledger_clock = us
            self._maybe_complete(us)
        finally:
            self._ledger_clock = outer_ledger_clock
            self._draining = False

    def _finish_decision(self, us, data):
        if data["action"] == "initial":
            self.pending_initial_decision = False
            self.start_transfer(us, data["decision"], _ready=True,
                                _observations=data["observations"], _available=data["available"])
            return
        pair = self.pairs.get(data["pair_id"])
        if not pair or self.active_pair_id != pair.pair_id:
            return
        if data["action"] == "cancel_source":
            data["decision_ready_us"] = us
            data["submitted_us"] = us
            data["eligible_after_us"] = us + self.delay_us
            self._push_event(self.command_queue, us+self.delay_us, data)
            self.sink(dict(kind="order_cancel_requested", us=us, **data))
            return
        pair.reprice_pending = False
        dirty, pair.reprice_dirty = pair.reprice_dirty, False
        pair.transport_pending += len(data["commands"])
        for command in data["commands"]:
            command["decision_ready_us"] = us
            command["submitted_us"] = us
            command["eligible_after_us"] = us + self.delay_us
            self._push_event(self.command_queue, us + self.delay_us, command)
            self.sink(dict(kind="order_replace_requested", us=us, **command))
        if dirty:
            self._schedule_reprice(us)

    def _apply_command(self, us, data):
        if data["action"] == "instruction_deadline":
            pair = self.pairs.get(data["pair_id"])
            if pair and self.active_pair_id == pair.pair_id:
                self._finish_empirical_pair(pair, us, "deadline")
            return
        if data["action"] in ("restore_begin", "restore_arrival", "restore_deadline"):
            self._apply_restore_command(us, data)
            return
        pair = self.pairs.get(data["pair_id"])
        order = self.orders.get(data["symbol"])
        valid = bool(pair and self.active_pair_id == pair.pair_id and order
                     and order.identifier == data["order_id"])
        if data["action"] == "cancel_source":
            self.sink(dict(kind="order_cancel_arrival", us=us, applied=valid, **data))
            if valid:
                pair.cancel_pending = False
                self._stop_source(us, data["reason"])
            return
        if data["action"] == "activate":
            if valid and pair.unpaired_btc > EPS and not self._pair_has_responses(pair.pair_id):
                order.active = True
                order.eligible_us = us
                self.sink(dict(kind="order_activation", us=us, pair_id=pair.pair_id,
                               order_id=order.identifier, symbol=order.symbol,
                               eligible_after_us=us, decision_started_us=data["decision_started_us"],
                               decision_ready_us=data["decision_ready_us"]))
            return
        if valid:
            pair.transport_pending = max(0, pair.transport_pending-1)
        reason = None
        if not valid:
            reason = "closed_or_replaced_pair"
        elif data["fill_revision"] != pair.fill_revision:
            reason = "fills_changed_during_latency"
        elif pair.reason in ("end_of_window", "expiry"):
            reason = "window_or_contract_closed"
        elif order.role == "source" and pair.status != "pending" and not (pair.rolling and data.get("market_order")):
            reason = "source_halted"
        elif data["revision"] <= order.revision:
            reason = "superseded_revision"
        elif self._pair_has_responses(pair.pair_id):
            reason = "awaiting_fill_acknowledgement"
        elif (not pair.rolling and abs(data["limit_price"]-order.limit_price) <= max(1e-8, abs(order.limit_price)*1e-10)
                and not (order.role == "target" and pair.unpaired_btc > EPS and not order.active)):
            reason = "unchanged_limit"
            order.revision = data["revision"]
        previous = order.limit_price if valid else None
        if reason is None:
            order.limit_price = data["limit_price"]
            order.revision = data["revision"]
            order.eligible_us = us
            order.decision_started_us = data["decision_started_us"]
            order.decision_ready_us = data["decision_ready_us"]
            order.observation_us = data["observation_us"]
            if pair.rolling:
                order.market_order = data.get("market_order", False)
                order.lease_context = copy.deepcopy(data.get("lease_context", {}))
                order.active = True
            if order.role == "target" and pair.unpaired_btc > EPS:
                order.active = True
            self.replacement_count += 1
        self.sink(dict(kind="order_replace_arrival", us=us, previous_limit_price=previous,
                       applied=reason is None, rejection_reason=reason, **data))
        if valid and (pair.reprice_dirty or reason in ("fills_changed_during_latency", "awaiting_fill_acknowledgement")):
            self._schedule_reprice(us)

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
                # Earlier observations, acknowledgements and commands must be
                # audited before this settlement. At the exact same timestamp,
                # scheduled variation settles before queued agent actions.
                self._drain_queues(boundary - 1)
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

    def _fresh_pair(self, us, source, target, observations=None):
        observations = self.observed_marks if observations is None else observations
        marks = [observations.get(s) for s in ("SPOT", source, target)]
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
        if self.rolling_execution:
            self._rolling_state(us)
        if self.cash_recovery is not None:
            self.last_reason = "bounded_cash_restoration"
            return None
        if self.pending_initial_decision:
            self.last_reason = "pending_decision"
            return None
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
        from paired_amortized_strategy import evaluate_amortized_transfer, rank_amortized_decisions
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
                if self.config.selection_mode == "amortized_rank":
                    decision = (self._rolling_evaluate(us, source, target, spot, config)
                        if self.rolling_execution else evaluate_amortized_transfer(us, source, target, spot,
                            cash_rate=self.rate, fees=self.fee_schedules, config=config))
                elif self.config.repricing_mode == "empirical" and not risk_exit:
                    decision = self._evaluate_empirical(us, source, target, spot, config)
                else:
                    risk_fraction = (min(1.0, self.config.max_unpaired_btc/quantity)
                                     if risk_exit and self.config.repricing_mode == "empirical" else 1.0)
                    decision = evaluate_transfer(us, source, target, spot, cash_rate=self.rate,
                        fees=self.fee_schedules,
                        config=replace(config, max_transfer_fraction=risk_fraction, size_fractions=(1,)) if risk_exit else config)
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
        if self.config.selection_mode == "amortized_rank":
            candidates = [d.to_dict() if hasattr(d, "to_dict") else d for d in
                          rank_amortized_decisions(candidates)]
        accepted = [d for d in candidates if d.get("accepted")]
        if not accepted:
            self.no_trade_count += 1
            self.last_reason = ("no_amortized_improvement" if self.config.selection_mode == "amortized_rank"
                                else "no_net_gain") if candidates else self.last_reason
            self.latest_decision = ((candidates[0] if candidates else None)
                if self.config.selection_mode == "amortized_rank" else
                max(candidates, key=lambda x: x.get("edge_btc", -math.inf), default=None))
            if self.latest_decision:
                self.sink(dict(kind="paired_decision", us=us, selected=False,
                               candidates_evaluated=len(candidates), decision=self.latest_decision))
            return None
        forced = [d for d in accepted if d.get("reason") == "forced_expiry_exit"]
        selected = ((forced or accepted)[0] if self.config.selection_mode == "amortized_rank" else
                    max(forced or accepted, key=lambda d: (d["edge_btc"], -d["horizon_us"], d["target_symbol"])))
        self.latest_decision = selected
        self.sink(dict(kind="paired_decision", us=us, selected=True,
                       candidates_evaluated=len(candidates), decision=selected))
        return self.start_transfer(us, selected)

    def _reevaluate_pending(self, us, rate_snapshot):
        pair = self.pairs.get(self.active_pair_id)
        self.last_reason = "pending_transfer"
        if pair and pair.empirical:
            self._schedule_reprice(us)
            return
        if pair and pair.repricing_supported:
            permitted = getattr(rate_snapshot, "allows_new_transfers", True)
            if isinstance(rate_snapshot, dict):
                permitted = rate_snapshot.get("allows_new_transfers", not rate_snapshot.get("stale", False))
            if not permitted:
                self._request_source_cancel(us, "stale_treasury_rate")
            self._schedule_reprice(us)
            if pair.unpaired_btc > EPS or pair.repricing_supported:
                return
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
            self._request_source_cancel(us, "stale_treasury_rate")
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
        if self.config.selection_mode == "amortized_rank":
            from paired_amortized_strategy import evaluate_amortized_transfer
            data = evaluate_amortized_transfer(us,
                PositionSlice(source_quote, remaining, source_cash, unsettled),
                quotes[pair.target_symbol], quotes["SPOT"], cash_rate=self.rate,
                fees=self.fee_schedules,
                source_entry_fees=entry_fees["source"],
                target_entry_fees=entry_fees["target"],
                config=replace(self.config.economics_config(), max_transfer_fraction=1,
                               max_delta_btc=remaining),
                source_price=self.orders[pair.source_symbol].limit_price,
                target_price=self.orders[pair.target_symbol].limit_price).to_dict()
        else:
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
            self._request_source_cancel(us, "remaining_"+data["reason"])


    def start_transfer(self, us, decision=None, **kwargs):
        """Submit one immutable accepted decision; caller cannot replace a pair."""
        ready = kwargs.pop("_ready", False)
        snapshots = kwargs.pop("_observations", None)
        observed_available = kwargs.pop("_available", None)
        if not ready:
            self.accrue(us)
        data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or kwargs)
        observations = ({s: Trade(**t) for s, t in snapshots.items()} if snapshots is not None
                        else self.observed_marks)
        observed_available = self.observed_available_us if observed_available is None else observed_available
        if (not ready and self.config.repricing_mode == "empirical"
                and round(self.config.decision_delay_seconds*1e6)+self.delay_us >= round(self.config.waiting_seconds*1e6)):
            self.last_reason = "decision_and_transport_exhaust_execution_deadline"
            self.rejected_count += 1
            return None
        if not ready and self.config.decision_delay_seconds:
            if self.pending_initial_decision or self.active_pair_id is not None or self.response_queue:
                self.last_reason = "pending_decision" if self.pending_initial_decision else "pending_transfer"
                return None
            decision_ready = us + round(self.config.decision_delay_seconds * 1e6)
            data = {**data, "decision_started_us": us, "decision_ready_us": decision_ready}
            self.pending_initial_decision = True
            self._push_event(self.decision_queue, decision_ready, dict(action="initial", decision=data,
                observations={s: asdict(t) for s, t in observations.items()}, available=dict(observed_available)))
            self.sink(dict(kind="paired_decision_pending", us=us, decision_started_us=us,
                           decision_ready_us=decision_ready, decision=data))
            self.last_reason = "decision_in_progress"
            return None
        data.setdefault("decision_started_us", us)
        data.setdefault("decision_ready_us", us)
        if not data.get("accepted", True):
            self.last_reason = data.get("reason", "economic_rejection")
            return None
        if self.rolling_execution and not data.get("diagnostics", {}).get("rolling_lease"):
            self.last_reason = "missing_rolling_price_window"
            self.rejected_count += 1
            return None
        source, target = data["source_symbol"], data["target_symbol"]
        source_qty = float(data["source_quantity_btc"])
        target_qty = float(data["target_quantity_btc"])
        if source == target or not all(math.isfinite(q) and q > EPS for q in (source_qty, target_qty)):
            raise ValueError("Paired transfer requires distinct symbols and positive finite sizes")
        if self.config.repricing_mode == "empirical" and source_qty > self.config.max_unpaired_btc+EPS:
            self.last_reason = "empirical_instruction_exceeds_tranche_cap"
            self.rejected_count += 1
            return None
        if self.active_pair_id is not None or self.response_queue:
            self.last_reason = "pending_transfer"
            self.rejected_count += 1
            return None
        freshness_us = data["decision_started_us"] if self.config.repricing_mode == "empirical" else us
        valid, reason = self._fresh_pair(freshness_us, source, target, observations)
        if not valid or source_qty > self.units.get(source, 0) + EPS:
            self.last_reason = reason if not valid else "insufficient_source_inventory"
            self.rejected_count += 1
            return None
        probe = FundedLedger.restore(self.ledger.snapshot())
        source_pad = (self.config.price_limit_bps+self.config.half_spread_bps+self.config.slippage_bps)/10000
        try:
            probe.execute_fill(source, -min(source_qty, self.config.max_unpaired_btc),
                               observations[source].price*(1-source_pad), "source-preflight")
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
            s: dict(price=observations[s].price, source_us=self._source_us(observations[s]),
                    available_us=observed_available[s],
                    source_age_us=us-self._source_us(observations[s]),
                    observed_trade_btc=observations[s].btc)
            for s in {"SPOT", source, target}}}
        pair = Transfer(pair_id, source, target, source_qty, target_qty, us, data,
                        source_order_id, target_order_id)
        pair.reason = data.get("reason", "economic_surplus")
        pair.empirical = self.config.repricing_mode == "empirical"
        if pair.empirical:
            pair.deadline_us = data["decision_started_us"] + round(self.config.waiting_seconds*1e6)
            self.empirical_stats["instructions"] += 1
            self._push_event(self.command_queue, max(us, pair.deadline_us),
                             dict(action="instruction_deadline", pair_id=pair_id))
        self.pairs[pair_id] = pair
        self.active_pair_id = pair_id
        pad = (self.config.price_limit_bps+self.config.half_spread_bps+self.config.slippage_bps) / 10000
        if self.rolling_execution:
            source_limit, target_limit = self._initialize_rolling(pair, observations)
        elif pair.empirical:
            details = data.get("diagnostics", {})
            source_limit = details.get("source_sale_limit", observations[source].price*(1-pad))
            target_limit = details.get("target_buy_limit", observations[target].price*(1+pad))
            self._initialize_empirical(pair, source_limit, target_limit)
        else:
            source_limit, target_limit = self._initialize_adaptive(pair, observations,
                observations[source].price*(1-pad), observations[target].price*(1+pad))
        observation_us = max(observed_available[s] for s in (source, target))
        self.orders[source] = PairedOrder(source_order_id, pair_id, "source", source,
            -source_qty, us, us + self.delay_us, source_limit,
            decision_started_us=data["decision_started_us"], decision_ready_us=us,
            observation_us=observation_us)
        self.orders[target] = PairedOrder(target_order_id, pair_id, "target", target,
            target_qty, us, us + self.delay_us, target_limit, active=pair.rolling,
            decision_started_us=data["decision_started_us"], decision_ready_us=us,
            observation_us=observation_us)
        if pair.rolling:
            for order in self.orders.values():
                order.lease_context = self._rolling_order_context(data["diagnostics"]["rolling_lease"],
                    order.role, source_limit, target_limit, source, target, observations)
        self.order_count += 2
        self.sink(dict(kind="paired_transfer", us=us, **asdict(pair)))
        for order in self.orders.values():
            self.sink(dict(kind="order", us=us, order_id=order.identifier, pair_id=pair_id,
                           symbol=order.symbol, signed_btc=order.signed_btc,
                           eligible_after_us=order.eligible_us, role=order.role,
                           limit_price=order.limit_price, conditional=not order.active, revision=0,
                           lease_context=copy.deepcopy(order.lease_context), market_order=False,
                           decision_started_us=order.decision_started_us, decision_ready_us=us,
                           observation_us=observation_us, target_effective_lease=pair.target_effective_lease,
                           deadline_us=pair.deadline_us, execution_policy="empirical" if pair.empirical else self.config.repricing_mode))
        self.last_reason = "transfer_submitted"
        return pair

    def _incremental_fee(self, order):
        from paired_transfer_economics import IncrementalFeeSchedule
        product = "spot" if order.symbol == "SPOT" else "futures"
        return IncrementalFeeSchedule(self.fee_schedules[product], order.filled_btc,
                                      order.filled_value, order.fee_usd)

    def _initialize_adaptive(self, pair, observations, source_limit, target_limit):
        """Pin the desired net-entry lease to the admissible economic boundary.

        Roll/reverse routes retain their original limits: this lease convention
        specifically describes selling spot and buying a long future.
        """
        if self.config.selection_mode == "amortized_rank" and self.config.repricing_mode == "adaptive":
            return self._initialize_amortized_adaptive(pair, observations, source_limit, target_limit)
        if (self.config.repricing_mode != "adaptive" or pair.source_symbol != "SPOT"
                or pair.target_symbol == "SPOT" or pair.reason == "forced_expiry_exit"):
            return source_limit, target_limit
        from paired_transfer_economics import (QuoteSnapshot, PositionSlice,
            effective_lease_rate, solve_economic_price_limit)
        now = pair.decision["decision_started_us"]
        snapshots = pair.decision["quote_snapshots"]
        quotes = {symbol: QuoteSnapshot(symbol, mark.price, self._source_us(mark),
                    snapshots[symbol]["available_us"], self.expiries.get(symbol))
                  for symbol, mark in observations.items() if symbol in snapshots}
        rate = pair.decision.get("cash_rate", self.rate)
        horizon = pair.decision.get("horizon_us")
        if horizon is None or rate is None:
            return source_limit, target_limit
        cap, boundary = solve_economic_price_limit(now,
            PositionSlice(quotes["SPOT"], pair.source_quantity_btc),
            quotes[pair.target_symbol], quotes["SPOT"], counterpart_price=source_limit,
            target_quantity_btc=pair.target_quantity_btc, comparison_horizon_us=horizon,
            reference_price=target_limit, cash_rate=rate, fees=self.fee_schedules,
            config=self.config.economics_config())
        if cap is None:
            pair.decision["adaptive_limit_reason"] = "no_admissible_economic_boundary"
            return source_limit, target_limit
        years = (self.expiries[pair.target_symbol] - now) / YEAR_US
        source_fee = self.fee_schedules["spot"].total_fee(pair.source_quantity_btc,
                                                       pair.source_quantity_btc*source_limit)
        target_fee = self.fee_schedules["futures"].total_fee(pair.target_quantity_btc,
                                                          pair.target_quantity_btc*cap)
        lease = effective_lease_rate(source_limit, cap, cash_rate=rate, remaining_years=years,
            spot_quantity_btc=pair.source_quantity_btc, futures_quantity_btc=pair.target_quantity_btc,
            spot_fee_usd=source_fee, futures_fee_usd=target_fee)
        if lease is not None:
            pair.target_effective_lease = lease
            pair.repricing_supported = True
            pair.decision["adaptive_price_boundary"] = boundary.diagnostics["economic_price_boundary"]
            pair.decision["target_effective_lease"] = lease
            pair.decision["adaptive_limit_reason"] = "economic_and_funding_boundary"
            return source_limit, cap
        return source_limit, target_limit

    def _initialize_amortized_adaptive(self, pair, observations, source_limit, target_limit):
        """Set symmetric fee-aware boundaries for the ranked transfer."""
        from paired_transfer_economics import PositionSlice, QuoteSnapshot
        from paired_amortized_strategy import solve_amortized_price_limit
        now = pair.decision["decision_started_us"]
        snapshots = pair.decision["quote_snapshots"]
        quotes = {symbol: QuoteSnapshot(symbol, mark.price, self._source_us(mark),
                    snapshots[symbol]["available_us"], self.expiries.get(symbol))
                  for symbol, mark in observations.items() if symbol in snapshots}
        held = self.units.get(pair.source_symbol, 0)
        reference = (0.0 if pair.source_symbol == "SPOT" else
                     sum(lot.quantity * lot.reference_price
                         for lot in self.ledger.lots.get(pair.source_symbol, [])))
        source_cash = 0.0 if pair.source_symbol == "SPOT" or held <= EPS else min(
            self.cash, reference * pair.source_quantity_btc / held)
        unsettled = (0.0 if pair.source_symbol == "SPOT" or held <= EPS else
                     pair.source_quantity_btc * quotes[pair.source_symbol].price -
                     reference * pair.source_quantity_btc / held)
        source = PositionSlice(quotes[pair.source_symbol], pair.source_quantity_btc,
                               source_cash, unsettled)
        config = replace(self.config.economics_config(), max_transfer_fraction=1,
                         max_delta_btc=pair.source_quantity_btc)
        floor, source_boundary = solve_amortized_price_limit(now, source,
            quotes[pair.target_symbol], quotes["SPOT"], price_role="source",
            counterpart_price=target_limit, cash_rate=self.rate,
            fees=self.fee_schedules, config=config,
            target_quantity_btc=pair.target_quantity_btc)
        if floor is None:
            pair.decision["adaptive_limit_reason"] = "no_amortized_source_boundary"
            return source_limit, target_limit
        cap, target_boundary = solve_amortized_price_limit(now, source,
            quotes[pair.target_symbol], quotes["SPOT"], price_role="target",
            counterpart_price=floor, cash_rate=self.rate,
            fees=self.fee_schedules, config=config,
            target_quantity_btc=pair.target_quantity_btc)
        if cap is None:
            pair.decision["adaptive_limit_reason"] = "no_amortized_target_boundary"
            return source_limit, target_limit
        candidate = target_boundary.diagnostics["target_candidate"]
        pair.target_effective_lease = candidate["amortized_rate"]
        pair.repricing_supported = True
        pair.decision["adaptive_source_boundary"] = source_boundary.diagnostics.get(
            "amortized_price_boundary")
        pair.decision["adaptive_target_boundary"] = target_boundary.diagnostics.get(
            "amortized_price_boundary")
        pair.decision["target_amortized_return"] = pair.target_effective_lease
        pair.decision["adaptive_limit_reason"] = "amortized_return_and_funding_boundary"
        return max(source_limit, floor), min(target_limit, cap)

    def _schedule_amortized_reprice(self, us, pair):
        """Continuously derive either leg's limit from its observed counterpart."""
        if pair.reprice_pending or pair.transport_pending or pair.cancel_pending:
            pair.reprice_dirty = True
            return
        fresh, _ = self._fresh_pair(us, pair.source_symbol, pair.target_symbol)
        if not fresh:
            return
        from paired_transfer_economics import PositionSlice
        from paired_amortized_strategy import solve_amortized_price_limit
        quotes = self.observed_quotes()
        source_order, target_order = self.orders[pair.source_symbol], self.orders[pair.target_symbol]
        remaining_source = abs(source_order.signed_btc) - source_order.filled_btc
        remaining_target = abs(target_order.signed_btc) - target_order.filled_btc
        if remaining_target <= EPS:
            return
        held = self.units.get(pair.source_symbol, 0)
        reference = (0.0 if pair.source_symbol == "SPOT" else
                     sum(lot.quantity * lot.reference_price
                         for lot in self.ledger.lots.get(pair.source_symbol, [])))
        source_cash = 0.0 if pair.source_symbol == "SPOT" or held <= EPS else min(
            self.cash, reference * max(remaining_source, pair.unpaired_btc) / held)
        unsettled = (0.0 if pair.source_symbol == "SPOT" or held <= EPS else
                     max(remaining_source, pair.unpaired_btc) * quotes[pair.source_symbol].price -
                     reference * max(remaining_source, pair.unpaired_btc) / held)
        quantity = max(remaining_source, pair.unpaired_btc)
        if quantity <= EPS:
            return
        source = PositionSlice(quotes[pair.source_symbol], quantity, source_cash, unsettled)
        config = replace(self.config.economics_config(), max_transfer_fraction=1,
                         max_delta_btc=quantity)
        source_fee = self._incremental_fee(source_order)
        target_fee = self._incremental_fee(target_order)
        entry_fees = {"source": source_fee, "target": target_fee}
        pad = (self.config.half_spread_bps + self.config.slippage_bps) / 10000
        commands = []
        if pair.unpaired_btc > EPS and pair.unmatched_source_lots:
            lot = pair.unmatched_source_lots[0]
            anchor = lot[1]
            cap, boundary = solve_amortized_price_limit(us, source,
                quotes[pair.target_symbol], quotes["SPOT"], price_role="target",
                counterpart_price=anchor, cash_rate=self.rate, fees=self.fee_schedules,
                config=config, target_quantity_btc=remaining_target,
                entry_fees=entry_fees)
            if cap is None:
                self._request_source_cancel(us, "remaining_amortized_improvement_below_buffer")
                return
            # Never exceed the cash actually released by the first leg.
            fee = target_fee.total_fee(remaining_target, remaining_target * cap)
            funding_cap = max(0.0, pair.reserved_usd - fee) / remaining_target
            cap = min(cap, funding_cap)
            if cap > EPS:
                commands.append((target_order, cap, anchor, lot[2] * lot[3],
                                 "amortized_return_and_released_cash"))
        else:
            observed_target = quotes[pair.target_symbol].price * (1 + pad)
            floor, _ = solve_amortized_price_limit(us, source,
                quotes[pair.target_symbol], quotes["SPOT"], price_role="source",
                counterpart_price=observed_target, cash_rate=self.rate,
                fees=self.fee_schedules, config=config,
                target_quantity_btc=remaining_target, entry_fees=entry_fees)
            if floor is None:
                self._request_source_cancel(us, "remaining_amortized_improvement_below_buffer")
                return
            commands.append((source_order, floor, observed_target,
                             target_fee.total_fee(remaining_target,
                                                  remaining_target * observed_target),
                             "amortized_return"))
            observed_source = quotes[pair.source_symbol].price * (1 - pad)
            cap, _ = solve_amortized_price_limit(us, source,
                quotes[pair.target_symbol], quotes["SPOT"], price_role="target",
                counterpart_price=observed_source, cash_rate=self.rate,
                fees=self.fee_schedules, config=config,
                target_quantity_btc=remaining_target, entry_fees=entry_fees)
            if cap is not None:
                commands.append((target_order, cap, observed_source,
                                 source_fee.total_fee(remaining_source,
                                                      remaining_source * observed_source),
                                 "conditional_observed_counterpart"))
        packed = []
        observation = max(self.observed_available_us.get(pair.source_symbol, 0),
                          self.observed_available_us.get(pair.target_symbol, 0))
        for order, limit, anchor, anchor_fee, binding in commands:
            needs_activation = order.role == "target" and pair.unpaired_btc > EPS and not order.active
            tolerance = max(1e-8, abs(order.limit_price) * 1e-10)
            if not needs_activation and abs(limit - order.limit_price) <= tolerance:
                continue
            self.queue_sequence += 1
            packed.append(dict(action="replace", pair_id=pair.pair_id,
                order_id=order.identifier, symbol=order.symbol, role=order.role,
                revision=self.queue_sequence, limit_price=limit,
                counterpart_price=anchor, counterpart_fee_usd=anchor_fee,
                target_effective_lease=pair.target_effective_lease,
                binding_constraint=binding, observation_us=observation,
                decision_started_us=us, fill_revision=pair.fill_revision))
        if packed:
            pair.reprice_pending = True
            pair.reprice_dirty = False
            self._push_event(self.decision_queue,
                us + round(self.config.decision_delay_seconds * 1e6),
                dict(action="reprice", pair_id=pair.pair_id, commands=packed))

    def _schedule_reprice(self, us):
        pair = self.pairs.get(self.active_pair_id)
        if not pair or not pair.repricing_supported or self._pair_has_responses(pair.pair_id):
            return
        if pair.empirical and us >= pair.deadline_us:
            return
        if pair.reprice_pending or pair.transport_pending:
            pair.reprice_dirty = True
            return
        if pair.reason in ("end_of_window", "expiry"):
            return
        if pair.rolling:
            return self._schedule_rolling_reprice(us, pair)
        if self.config.selection_mode == "amortized_rank":
            return self._schedule_amortized_reprice(us, pair)
        from paired_transfer_economics import counterpart_price_limit
        source, target = self.orders[pair.source_symbol], self.orders[pair.target_symbol]
        remaining_years = (self.expiries[pair.target_symbol] - us) / YEAR_US
        if remaining_years <= 0 or self.rate is None:
            return
        commands = []
        source_fee, target_fee = self._incremental_fee(source), self._incremental_fee(target)
        # Match one acknowledged source lot at a time. Future observations cannot
        # replace its actual execution price, including after a source timeout.
        if pair.empirical:
            # One calibrated instruction is a whole small source tranche. Its
            # source order accumulates prints without waiting for individual
            # acknowledgements; hedge submission waits for the entire tranche.
            if pair.source_filled_btc < pair.source_quantity_btc-EPS or target.active:
                return
            target_quantity = abs(target.signed_btc)-target.filled_btc
            if target_quantity <= EPS:
                return
            net_source = pair.source_value_usd-source.fee_usd
            remaining_budget = net_source*(1-self.config.cash_reserve_fraction)-pair.target_value_usd-target.fee_usd
            funding_cap = counterpart_price_limit(instrument="futures",
                counterpart_price=max(0.0, remaining_budget)/target_quantity,
                target_lease_rate=0.0, cash_rate=0.0, remaining_years=1.0,
                quantity_btc=target_quantity, fee_schedule=target_fee)
            if funding_cap is None:
                return
            authorized = pair.decision["authorized_target_cap"]
            cap = min(authorized, funding_cap)
            if cap > EPS:
                commands.append((target, cap, pair.source_value_usd/pair.source_filled_btc,
                                 source.fee_usd, "authorized_execution_budget" if authorized <= funding_cap else "released_cash_and_reserve"))
        elif pair.unpaired_btc > EPS and pair.unmatched_source_lots:
            lot = pair.unmatched_source_lots[0]
            quantity, anchor = lot[:2]
            fee_per_btc = lot[2] if len(lot) > 2 else source.fee_usd/max(source.filled_btc, EPS)
            target_quantity = min(quantity*pair.ratio, abs(target.signed_btc)-target.filled_btc)
            original_quantity = lot[3] if len(lot) > 3 else quantity
            already_spent = lot[4] if len(lot) > 4 else 0.0
            actual_fee = quantity*fee_per_btc
            # A minimum/fixed fee may be charged on the first tiny target fill.
            # Keep the ORIGINAL lot's total fee-inclusive spend budget and
            # subtract all actual target costs already paid; recalculating only
            # on its shrinking quantity would forget that first-fill charge.
            factor = (pair.decision["authorized_unit_ratio"] if pair.empirical else
                      1+(self.rate-pair.target_effective_lease)*remaining_years)
            lease_budget = ((anchor-fee_per_btc)*factor*original_quantity*pair.ratio-already_spent)
            if lease_budget <= EPS or target_quantity <= EPS:
                return
            cap = counterpart_price_limit(instrument="futures",
                counterpart_price=lease_budget/target_quantity, target_lease_rate=0.0,
                cash_rate=0.0, remaining_years=1.0, quantity_btc=target_quantity,
                counterpart_quantity_btc=target_quantity, fee_schedule=target_fee)
            if cap is None:
                return
            # The cash reserve belongs to the entire source lot, including any
            # target prefix already filled, and is never borrowed for repricing.
            budget = min(pair.reserved_usd,
                original_quantity*(anchor-fee_per_btc)*(1-self.config.cash_reserve_fraction)-already_spent)
            if pair.funding_cap_revision != pair.fill_revision:
                funding_cap = counterpart_price_limit(instrument="futures",
                    counterpart_price=max(0.0, budget)/target_quantity,
                    target_lease_rate=0.0, cash_rate=0.0, remaining_years=1.0,
                    quantity_btc=target_quantity, fee_schedule=target_fee)
                pair.funding_cap_price = funding_cap or 0.0
                pair.funding_cap_revision = pair.fill_revision
            binding = "authorized_execution_budget" if pair.empirical else "effective_lease"
            if pair.funding_cap_price < cap:
                cap, binding = pair.funding_cap_price, "released_cash_and_reserve"
            if cap > EPS:
                commands.append((target, cap, anchor, actual_fee, binding))
        elif pair.status == "pending" and not pair.cancel_pending:
            fresh, _ = self._fresh_pair(us, pair.source_symbol, pair.target_symbol)
            if not fresh:
                return
            remaining_source = abs(source.signed_btc)-source.filled_btc
            remaining_target = remaining_source*pair.ratio
            if remaining_source <= EPS or remaining_target <= EPS:
                return
            pad = (self.config.price_limit_bps+self.config.half_spread_bps+self.config.slippage_bps)/10000
            observed_future = self.observed_marks[pair.target_symbol].price*(1+pad)
            estimated_target_fee = target_fee.total_fee(remaining_target, remaining_target*observed_future)
            floor = counterpart_price_limit(instrument="spot", counterpart_price=observed_future,
                target_lease_rate=pair.target_effective_lease, cash_rate=self.rate,
                remaining_years=remaining_years, quantity_btc=remaining_source,
                counterpart_quantity_btc=remaining_target, counterpart_fee_usd=estimated_target_fee,
                fee_schedule=source_fee)
            if floor is not None:
                required_source_net = ((remaining_target*observed_future+estimated_target_fee)
                    / (remaining_source*(1-self.config.cash_reserve_fraction)))
                funding_floor = counterpart_price_limit(instrument="spot",
                    counterpart_price=required_source_net, target_lease_rate=0.0,
                    cash_rate=0.0, remaining_years=1.0, quantity_btc=remaining_source,
                    fee_schedule=source_fee)
                if funding_floor is None:
                    return
                floor = math.nextafter(max(floor, funding_floor), math.inf)
                # A lease screen alone does not prove terminal BTC gain. Recheck
                # the full KEEP comparison for this frozen price decision, using
                # the future price expected at the source floor. The conditional
                # future order is repriced again from the actual source fill.
                tolerance = max(1e-8, abs(source.limit_price)*1e-10)
                if abs(floor-source.limit_price) > tolerance:
                    from paired_transfer_economics import PositionSlice, evaluate_transfer
                    quotes = self.observed_quotes()
                    check = evaluate_transfer(us, PositionSlice(quotes["SPOT"], remaining_source),
                        quotes[pair.target_symbol], quotes["SPOT"], cash_rate=self.rate,
                        fees=self.fee_schedules, entry_fees={"source": source_fee, "target": target_fee},
                        config=replace(self.config.economics_config(), max_transfer_fraction=1, size_fractions=(1,)),
                        target_quantity_btc=remaining_target,
                        execution_price_overrides={"source": floor, "target": observed_future},
                        comparison_horizon_us=pair.decision.get("horizon_us"),
                        horizon_limit_us=pair.decision.get("horizon_us"))
                    if not check.accepted:
                        self.sink(dict(kind="paired_reprice_rejected", us=us, pair_id=pair.pair_id,
                            decision_started_us=us, reason=check.reason, source_limit=floor,
                            target_limit=observed_future, edge_btc=check.edge_btc,
                            required_edge_btc=check.required_edge_btc))
                        self._request_source_cancel(us, "remaining_"+check.reason)
                        return
                commands.append((source, floor, observed_future, estimated_target_fee, "effective_lease_and_net_btc"))
                # Both conditional limits come from the opposite observed leg.
                observed_spot = self.observed_marks["SPOT"].price*(1-pad)
                estimated_source_fee = source_fee.total_fee(remaining_source, remaining_source*observed_spot)
                provisional_cap = counterpart_price_limit(instrument="futures", counterpart_price=observed_spot,
                    target_lease_rate=pair.target_effective_lease, cash_rate=self.rate,
                    remaining_years=remaining_years, quantity_btc=remaining_target,
                    counterpart_quantity_btc=remaining_source, counterpart_fee_usd=estimated_source_fee,
                    fee_schedule=target_fee)
                if provisional_cap is not None:
                    commands.append((target, provisional_cap, observed_spot,
                                     estimated_source_fee, "conditional_observed_counterpart"))
        packed = []
        observation = max((self.observed_available_us.get(s, 0)
                           for s in (pair.source_symbol, pair.target_symbol)), default=us)
        for order, limit, anchor, anchor_fee, binding in commands:
            needs_activation = order.role == "target" and pair.unpaired_btc > EPS and not order.active
            tolerance = max(1e-8, abs(order.limit_price)*1e-10)
            if not needs_activation and abs(limit-order.limit_price) <= tolerance:
                continue
            # One frozen decision at a time, but transport commands can overlap.
            # Each revision is monotonically numbered and guarded by fill state.
            self.queue_sequence += 1
            packed.append(dict(action="replace", pair_id=pair.pair_id, order_id=order.identifier,
                symbol=order.symbol, role=order.role, revision=self.queue_sequence,
                limit_price=limit, counterpart_price=anchor, counterpart_fee_usd=anchor_fee,
                target_effective_lease=pair.target_effective_lease, binding_constraint=binding,
                observation_us=observation, decision_started_us=us, fill_revision=pair.fill_revision))
        if not packed:
            return
        pair.reprice_pending = True
        pair.reprice_dirty = False
        self._push_event(self.decision_queue, us+round(self.config.decision_delay_seconds*1e6),
                         dict(action="reprice", pair_id=pair.pair_id, commands=packed))

    def _evaluate_empirical(self, us, source, target, spot, config, **kwargs):
        from paired_transfer_economics import evaluate_transfer_with_execution, TransferDecision
        if any((self.config.spot_fixed_fee_usd, self.config.spot_min_fee_usd,
                self.config.futures_fixed_fee_usd, self.config.futures_min_fee_usd,
                self.config.futures_per_contract_fee_usd)):
            return TransferDecision(False, "empirical_nonproportional_fees_unsupported", source.quote.symbol, target.symbol)
        config = replace(config, max_transfer_fraction=min(config.max_transfer_fraction,
            self.config.max_unpaired_btc/max(source.quantity_btc, EPS)))
        return evaluate_transfer_with_execution(us, source, target, spot, cash_rate=self.rate,
            fees=self.fee_schedules, config=config, execution_model=self.empirical_model,
            deadline_seconds=kwargs.pop("deadline_seconds", self.config.waiting_seconds),
            required_joint_probability=self.config.execution_confidence,
            min_samples=self.config.execution_min_samples,
            candidate_quantities_btc=self.config.execution_size_grid_btc, **kwargs)

    def _initialize_empirical(self, pair, source_limit, target_limit):
        from paired_transfer_economics import effective_lease_rate
        qs, qt = pair.source_quantity_btc, pair.target_quantity_btc
        if not all(math.isfinite(value) and value > 0 for value in (source_limit, target_limit)):
            raise ValueError("Empirical protected limits must be positive and finite")
        source_product = "spot" if pair.source_symbol == "SPOT" else "futures"
        target_product = "spot" if pair.target_symbol == "SPOT" else "futures"
        source_fee = self.fee_schedules[source_product].total_fee(qs, qs*source_limit)
        target_fee = self.fee_schedules[target_product].total_fee(qt, qt*target_limit)
        pair.repricing_supported = pair.source_symbol == "SPOT" and pair.target_symbol != "SPOT"
        if pair.repricing_supported:
            net_source = source_limit-source_fee/qs
            if net_source <= 0:
                raise ValueError("Empirical instruction has no funded source proceeds")
            pair.decision["authorized_unit_ratio"] = (target_limit+target_fee/qt)/net_source
            years = (self.expiries[pair.target_symbol]-pair.decision["decision_started_us"])/YEAR_US
            pair.target_effective_lease = effective_lease_rate(source_limit, target_limit,
                cash_rate=pair.decision.get("cash_rate", self.rate), remaining_years=years,
                spot_quantity_btc=qs, futures_quantity_btc=qt,
                spot_fee_usd=source_fee, futures_fee_usd=target_fee)
        pair.decision["authorized_target_cap"] = target_limit
        pair.decision["authorized_source_floor"] = source_limit
        pair.decision["execution_policy"] = "empirical"
        pair.decision["deadline_us"] = pair.deadline_us
        pair.decision["quantity_ratio_frozen"] = pair.ratio

    @staticmethod
    def _distribution_add(container, name, value, resolution=.001):
        if value is None or not math.isfinite(value):
            return
        stats = container.setdefault(name, dict(count=0, total=0.0, minimum=value, maximum=value,
                                                 resolution=resolution, bins={}))
        stats["count"] += 1
        stats["total"] += value
        stats["minimum"] = min(stats["minimum"], value)
        stats["maximum"] = max(stats["maximum"], value)
        key = str(math.ceil(value/resolution))
        stats["bins"][key] = stats["bins"].get(key, 0)+1

    @staticmethod
    def _distribution_summary(stats):
        result = dict(count=stats["count"], mean=stats["total"]/stats["count"],
                      min=stats["minimum"], max=stats["maximum"], resolution=stats["resolution"])
        cumulative = 0
        quantiles = {name: max(1, math.ceil(stats["count"]*q))
                     for name, q in (("p50", .5), ("p90", .9), ("p95", .95), ("p99", .99))}
        for bucket, count in sorted(stats["bins"].items(), key=lambda item: int(item[0])):
            cumulative += count
            for name, rank in quantiles.items():
                if name not in result and cumulative >= rank:
                    result[name] = int(bucket)*stats["resolution"]
        return result

    def _record_empirical_outcome(self, pair, us, outcome):
        if pair.outcome_recorded:
            return
        pair.outcome_recorded = True
        totals = self.empirical_stats
        completed = (pair.source_filled_btc >= pair.source_quantity_btc-EPS
                     and pair.unpaired_btc <= EPS and pair.last_target_fill_us is not None
                     and pair.last_target_fill_us < pair.deadline_us)
        if completed:
            totals["completed_by_deadline"] += 1
            outcome = "completed"
        elif outcome == "end_window_censored":
            totals["end_window_censored"] += 1
        else:
            totals["deadline_failed"] += 1
            totals["partial_at_deadline" if pair.source_filled_btc > EPS else "unfilled_at_deadline"] += 1
        totals["archived_unmatched_source_btc"] += pair.unpaired_btc
        start = pair.decision["decision_started_us"]
        end = pair.last_target_fill_us if completed else us
        waits = dict(instruction=(end-start)/1e6,
            source=(pair.first_source_fill_us-start)/1e6 if pair.first_source_fill_us is not None else None,
            hedge=(pair.last_target_fill_us-pair.first_source_fill_us)/1e6
                  if pair.last_target_fill_us is not None and pair.first_source_fill_us is not None else None)
        for name, value in waits.items():
            self._distribution_add(totals["wait_seconds"], name, value)
        execution = pair.decision.get("diagnostics", {})
        prediction = execution.get("execution_joint_success_probability")
        if prediction is not None and outcome != "end_window_censored":
            totals["prediction_count"] = totals.get("prediction_count", 0)+1
            totals["prediction_total"] = totals.get("prediction_total", 0.0)+prediction
        slippage = annualized = None
        if pair.matched_source_btc > EPS and pair.target_symbol != "SPOT":
            snapshots = pair.decision["quote_snapshots"]
            actual_ratio = (pair.target_value_usd/pair.target_filled_btc)/(pair.matched_source_value_usd/pair.matched_source_btc)
            observed_ratio = snapshots[pair.target_symbol]["price"]/snapshots[pair.source_symbol]["price"]
            slippage = (actual_ratio-observed_ratio)*10000
            years = (self.expiries[pair.target_symbol]-start)/YEAR_US
            annualized = slippage/years if years > 0 else None
            self._distribution_add(totals, "actual_slippage_bps", slippage, .01)
            self._distribution_add(totals, "annualized_slippage_bps", annualized, .01)
        record = dict(pair_id=pair.pair_id, status=outcome, decision_started_us=start,
            deadline_us=pair.deadline_us, completed_by_deadline=completed,
            requested_source_btc=pair.source_quantity_btc, requested_target_btc=pair.target_quantity_btc,
            actual_source_btc=pair.source_filled_btc, actual_target_btc=pair.target_filled_btc,
            unmatched_source_btc=pair.unpaired_btc, residual_cash_usd=pair.reserved_usd,
            predicted_completion_probability=prediction,
            instruction_wait_seconds=waits["instruction"], source_wait_seconds=waits["source"],
            hedge_wait_seconds=waits["hedge"], actual_slippage_bps=slippage,
            annualized_slippage_bps=annualized, actual_annualized_slippage_bps=annualized, maturity_reference_us=start,
            first_source_fill_us=pair.first_source_fill_us, first_target_fill_us=pair.first_target_fill_us,
            last_target_fill_us=pair.last_target_fill_us)
        totals["latest_instruction"] = record
        self.sink(dict(kind="empirical_instruction_result", us=us, **record))

    def _finish_empirical_pair(self, pair, us, outcome):
        if self.active_pair_id != pair.pair_id:
            return
        for order in self.orders.values():
            order.active = False
        pair.max_legging_us = max(pair.max_legging_us,
            us-pair.first_unpaired_us if pair.first_unpaired_us is not None else 0)
        self._record_empirical_outcome(pair, us, outcome)
        complete = self.empirical_stats["latest_instruction"]["completed_by_deadline"]
        pair.status = ("completed" if complete else "censored" if outcome == "end_window_censored"
                       else "partial" if pair.source_filled_btc > EPS else "timed_out")
        pair.reason = outcome
        pair.completed_us = us
        if outcome == "deadline" and not complete:
            self.timeout_count += 1
        unmatched = pair.unpaired_btc
        # Only net proceeds belonging to unmatched source quantity may fund the
        # spot fallback. Matched futures retain their actual collateral/reserve.
        restore_budget = min(pair.reserved_usd, sum(lot[0]*(lot[1]-(lot[2] if len(lot)>2 else 0))
                                                   for lot in pair.unmatched_source_lots))
        self._emit_pair_result(pair, us)
        self.ledger.release(pair.pair_id)
        pair.reserved_usd = 0
        self.orders.clear()
        self.active_pair_id = None
        self._archive_pair(pair)
        if unmatched > EPS and restore_budget > EPS and outcome != "end_window_censored":
            latest_ack = max([us]+[row[0] for row in self.response_queue if row[2].get("pair_id") == pair.pair_id])
            self._start_cash_restoration(us, latest_ack, pair, restore_budget, unmatched)

    def _start_cash_restoration(self, us, decision_us, pair, budget, quantity):
        self.recovery_sequence += 1
        identifier = f"restore-{self.recovery_sequence}"
        budget = min(budget, self.ledger.available_cash)
        if budget <= EPS:
            return
        self.ledger.reserve(identifier, budget)
        details = pair.decision.get("diagnostics", {})
        source_budget = details.get("execution_budget_bps", 0.0)
        self.cash_recovery = dict(identifier=identifier, pair_id=pair.pair_id, budget_usd=budget,
            remaining_cash_usd=budget, requested_btc=quantity, filled_btc=0.0, filled_value=0.0, fee_usd=0.0,
            decision_started_us=decision_us, deadline_us=decision_us+round(self.config.waiting_seconds*1e6),
            limit_price=None, eligible_us=None, active=False,
            budget_bps=max(self.config.price_limit_bps, source_budget))
        self.empirical_stats["cash_restorations"] += 1
        self._push_event(self.command_queue, decision_us,
                         dict(action="restore_begin", pair_id=pair.pair_id, recovery_id=identifier))
        self._push_event(self.command_queue, self.cash_recovery["deadline_us"],
                         dict(action="restore_deadline", pair_id=pair.pair_id, recovery_id=identifier))
        self.sink(dict(kind="cash_restore_pending", us=us, **self.cash_recovery))

    def _apply_restore_command(self, us, data):
        recovery = self.cash_recovery
        if not recovery or recovery["identifier"] != data["recovery_id"]:
            return
        if data["action"] == "restore_deadline":
            self._finish_cash_restoration(us, "deadline")
            return
        if data["action"] == "restore_arrival":
            if us < recovery["deadline_us"]:
                recovery["active"] = True
                recovery["eligible_us"] = us
                self.sink(dict(kind="cash_restore_arrival", us=us, **recovery))
            return
        spot = self.observed_marks.get("SPOT")
        if spot is None or not spot.executable or us-self._source_us(spot) > self.config.max_quote_age_seconds*1e6:
            self._finish_cash_restoration(us, "missing_fresh_spot")
            return
        from paired_transfer_economics import funded_quantity
        cap = spot.price*(1+recovery["budget_bps"]/10000)
        quantity, _ = funded_quantity(recovery["remaining_cash_usd"], cap, self.fee_schedules, "spot")
        recovery["requested_btc"] = min(recovery["requested_btc"], quantity)
        recovery["limit_price"] = cap
        recovery["observation_us"] = self.observed_available_us["SPOT"]
        recovery["decision_ready_us"] = us+round(self.config.decision_delay_seconds*1e6)
        arrival = recovery["decision_ready_us"]+self.delay_us
        self._push_event(self.command_queue, arrival,
            dict(action="restore_arrival", pair_id=recovery["pair_id"], recovery_id=recovery["identifier"]))
        self.order_count += 1
        self.sink(dict(kind="cash_restore_order", us=us, eligible_after_us=arrival, **recovery))

    def _execute_restore(self, trade):
        recovery = self.cash_recovery
        if (not recovery or not recovery["active"] or trade.symbol != "SPOT" or trade.side != "buy"
                or not trade.executable or trade.us <= recovery["eligible_us"] or trade.us >= recovery["deadline_us"]):
            return
        adjustment = (self.config.half_spread_bps+self.config.slippage_bps)/10000
        price = trade.price*(1+adjustment)
        if price > recovery["limit_price"]:
            return
        from paired_transfer_economics import funded_quantity, IncrementalFeeSchedule
        schedule = IncrementalFeeSchedule(self.fee_schedules["spot"], recovery["filled_btc"],
                                          recovery["filled_value"], recovery["fee_usd"])
        affordable, _ = funded_quantity(recovery["remaining_cash_usd"], price, {"spot": schedule}, "spot")
        quantity = min(recovery["requested_btc"]-recovery["filled_btc"], affordable, trade.btc*self.participation)
        if quantity <= EPS:
            return
        fee = self.ledger.execute_fill("SPOT", quantity, price, recovery["identifier"],
                                      timestamp_us=trade.us, reservation_id=recovery["identifier"])
        self.ledger.mark("SPOT", trade.price, timestamp_us=trade.us)
        self.plot_spot_pnl -= quantity*(price-trade.price)
        recovery["filled_btc"] += quantity
        recovery["filled_value"] += quantity*price
        recovery["fee_usd"] += fee
        recovery["remaining_cash_usd"] = max(0.0, recovery["remaining_cash_usd"]-quantity*price-fee)
        self.turnover += quantity*price
        self.fill_count += 1
        self.empirical_stats["cash_restored_btc"] += quantity
        self._push_event(self.response_queue, trade.us+round(self.config.response_delay_seconds*1e6),
            dict(pair_id=recovery["pair_id"], order_id=recovery["identifier"], symbol="SPOT",
                 signed_btc=quantity, exchange_fill_us=trade.us))
        self.sink(dict(kind="cash_restore_fill", us=trade.us, pair_id=recovery["pair_id"],
            recovery_id=recovery["identifier"], symbol="SPOT", signed_btc=quantity, price=price,
            fee_usd=fee, trade_id=trade.identifier, observed_btc=trade.btc,
            remaining_cash_usd=recovery["remaining_cash_usd"], nav_usd=self.nav,
            eligible_after_us=recovery["eligible_us"], deadline_us=recovery["deadline_us"]))
        if recovery["filled_btc"] >= recovery["requested_btc"]-EPS:
            self._finish_cash_restoration(trade.us, "filled")
        self._drain_queues(trade.us)

    def _finish_cash_restoration(self, us, reason):
        recovery = self.cash_recovery
        if not recovery:
            return
        self.ledger.release(recovery["identifier"])
        self.empirical_stats["restoration_residual_cash_usd"] += recovery["remaining_cash_usd"]
        if reason == "deadline" and recovery["filled_btc"] < recovery["requested_btc"]-EPS:
            self.empirical_stats["restoration_deadline_failed"] += 1
        self.sink(dict(kind="cash_restore_result", us=us, reason=reason, **recovery))
        self.ledger.fee_engine.tickets.pop(recovery["identifier"], None)
        self.lease_window = RollingPriceWindow(self.config.lease_window_seconds)
        self.latest_lease_execution = None
        self.cash_recovery = None
        self.command_queue[:] = [row for row in self.command_queue if row[2].get("recovery_id") != recovery["identifier"]]
        heapq.heapify(self.command_queue)

    def _empirical_summary(self):
        result = copy.deepcopy(self.empirical_stats)
        result["wait_seconds"] = {key: self._distribution_summary(value)
                                  for key, value in result["wait_seconds"].items()}
        for key in ("actual_slippage_bps", "annualized_slippage_bps"):
            if key in result:
                result[key] = self._distribution_summary(result[key])
        count = result["completed_by_deadline"]+result["deadline_failed"]
        result["completion_probability"] = result["completed_by_deadline"]/count if count else None
        predictions = result.get("prediction_count", 0)
        result["predicted_completion_probability_mean"] = result.pop("prediction_total", 0)/predictions if predictions else None
        result["residual_cash_usd"] = self.ledger.available_cash
        result["active_cash_restoration"] = copy.deepcopy(self.cash_recovery)
        result["completion_probability_denominator"] = count
        result["calibration_estimate_is_conditional"] = True
        return result

    def _pair_has_responses(self, pair_id):
        return any(item[2]["pair_id"] == pair_id for item in self.response_queue)

    def _check_timeout(self, us):
        pair = self.pairs.get(self.active_pair_id)
        if not pair:
            return
        if pair.first_unpaired_us is not None:
            pair.max_legging_us = max(pair.max_legging_us, us-pair.first_unpaired_us)
        if pair.empirical:
            return  # An explicit exchange GTD event owns this instruction's deadline.
        if pair.status == "pending":
            clock = pair.first_unpaired_us
            reason = "legging_timeout"
            if clock is None and pair.source_filled_btc <= EPS:
                clock, reason = pair.submitted_us, "unfilled_timeout"
            if clock is not None and us-clock > self.config.max_legging_seconds * 1e6:
                self.timeout_count += 1
                self._stop_source(us, reason)

    def _request_source_cancel(self, us, reason):
        """An economic cancellation travels through the same two outbound stages."""
        pair = self.pairs.get(self.active_pair_id)
        if not pair or pair.status != "pending" or pair.cancel_pending:
            return
        pair.cancel_pending = True
        source = self.orders[pair.source_symbol]
        data = dict(action="cancel_source", pair_id=pair.pair_id, order_id=source.identifier,
                    symbol=source.symbol, role="source", reason=reason, decision_started_us=us)
        self._push_event(self.decision_queue, us+round(self.config.decision_delay_seconds*1e6), data)
        if not self._draining:
            self._drain_queues(us)

    def _stop_source(self, us, reason):
        pair = self.pairs.get(self.active_pair_id)
        if not pair:
            return
        source = self.orders.get(pair.source_symbol)
        if source and source.active:
            source.active = bool(pair.rolling and pair.target_filled_btc/pair.ratio > pair.source_filled_btc+EPS)
            self.cancellation_count += int(abs(source.signed_btc)-source.filled_btc > EPS)
        if pair.rolling and pair.target_filled_btc/pair.ratio <= pair.source_filled_btc+EPS and pair.unpaired_btc <= EPS:
            self.orders[pair.target_symbol].active = False
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
        if pair.empirical:
            self._record_empirical_outcome(pair, us, "completed" if filled else "partial_cancelled")
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
        for queue in (self.decision_queue, self.command_queue):
            queue[:] = [event for event in queue if event[2].get("pair_id") != pair.pair_id]
            heapq.heapify(queue)

    def _emit_pair_result(self, pair, us):
        data = asdict(pair)
        data.update(matched_source_btc=pair.matched_source_btc,
                    unpaired_btc=pair.unpaired_btc,
                    paired_fill_ratio=pair.matched_source_btc/pair.source_quantity_btc,
                    max_legging_seconds=pair.max_legging_us/1e6)
        if pair.matched_source_btc > EPS:
            source_vwap = pair.matched_source_value_usd / pair.matched_source_btc
            matched_target = pair.matched_source_btc*pair.ratio if pair.rolling else pair.target_filled_btc
            target_vwap = (pair.matched_target_value_usd if pair.rolling else pair.target_value_usd) / matched_target
            target_order = self.orders.get(pair.target_symbol)
            target_fees = pair.matched_target_fee_usd if pair.rolling else target_order.fee_usd if target_order else 0.0
            data.update(source_vwap=source_vwap, target_vwap=target_vwap,
                        matched_source_fees_usd=pair.matched_source_fee_usd, target_fees_usd=target_fees)
            if pair.source_symbol == "SPOT" and pair.target_symbol != "SPOT" and self.rate is not None:
                from paired_transfer_economics import effective_lease_rate
                years = (self.expiries.get(pair.target_symbol, us)-us)/YEAR_US
                effective = effective_lease_rate(source_vwap, target_vwap, cash_rate=self.rate,
                    remaining_years=years, spot_quantity_btc=pair.matched_source_btc,
                    futures_quantity_btc=matched_target,
                    spot_fee_usd=pair.matched_source_fee_usd, futures_fee_usd=target_fees)
                data.update(executed_effective_lease=effective, effective_lease_rate_time_us=us,
                            effective_lease_expiry_us=self.expiries.get(pair.target_symbol),
                            effective_lease_cash_rate=self.rate,
                            effective_lease_shortfall=(max(0.0, pair.target_effective_lease-effective)
                                if pair.target_effective_lease is not None and effective is not None else None))
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
        self.latest_pair_result = {key: data.get(key) for key in (
            "pair_id", "status", "target_effective_lease", "executed_effective_lease", "effective_lease_shortfall",
            "matched_source_btc", "source_vwap", "target_vwap", "effective_lease_rate_time_us", "effective_lease_cash_rate")}
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
        if self.config.repricing_mode in ("adaptive", "empirical", "rolling_worst"):
            self._execute(trade)
            self._execute_restore(trade)
        self._queue_observation(trade)
        self._drain_queues(trade.us)
        if self.config.repricing_mode not in ("adaptive", "empirical", "rolling_worst"):
            self._execute(trade)

    def _execute(self, trade):
        if self.rolling_execution:
            return self._execute_rolling(trade)
        pair = self.pairs.get(self.active_pair_id)
        order = self.orders.get(trade.symbol)
        if not pair or not order or not order.active or not trade.executable or trade.us <= order.eligible_us:
            return
        if self._pair_has_responses(pair.pair_id) and not pair.empirical:
            return
        if pair.empirical and trade.us >= pair.deadline_us:
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
            if pair.status != "pending" or (pair.repricing_supported and not pair.empirical and pair.unpaired_btc > EPS):
                return
            if not pair.empirical:
                valid, _ = self._fresh_pair(trade.us, pair.source_symbol, pair.target_symbol)
                if not valid:
                    return
            available = min(available, max(0, self.config.max_unpaired_btc-pair.unpaired_btc), self.units.get(trade.symbol, 0))
        else:
            available = min(available, pair.source_filled_btc*pair.ratio-pair.target_filled_btc)
            if pair.repricing_supported and not pair.empirical and pair.unmatched_source_lots:
                available = min(available, pair.unmatched_source_lots[0][0]*pair.ratio)
        if available <= EPS:
            return
        if order.role == "source" and pair.repricing_supported and not pair.empirical:
            # A tiny print must not open a source lot whose whole approved
            # target cannot pay the first fixed/minimum ticket charge. With
            # serialized chunks there would be no subsequent source sale to
            # repair that fee deficit. Leave the source order for a feasible
            # print instead; there is still no assumed displayed depth.
            target_order = self.orders[pair.target_symbol]
            prospective_target = available*pair.ratio
            source_fee = self._incremental_fee(order).total_fee(available, available*fill_price)
            target_reference = min(target_order.limit_price,
                self.observed_marks[pair.target_symbol].price*(1+adjustment))
            target_fee = self._incremental_fee(target_order).total_fee(
                prospective_target, prospective_target*target_reference)
            released = available*fill_price-source_fee
            budget = released*(1-self.config.cash_reserve_fraction)
            if (prospective_target*target_reference+target_fee
                    > budget+EPS*max(1.0, abs(budget))):
                self.last_reason = "source_chunk_cannot_fund_target_ticket"
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
        pair.fill_revision += 1
        if order.role == "source":
            pair.source_filled_btc += available
            if pair.first_source_fill_us is None:
                pair.first_source_fill_us = trade.us
            pair.source_value_usd += available*fill_price
            pair.unmatched_source_lots.append([available, fill_price, fee/available, available, 0.0])
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
            if pair.first_target_fill_us is None:
                pair.first_target_fill_us = trade.us
            pair.last_target_fill_us = trade.us
            pair.target_value_usd += available*fill_price
            if pair.repricing_supported and not pair.empirical:
                order.active = False
            to_match = available/pair.ratio
            while to_match > EPS and pair.unmatched_source_lots:
                lot = pair.unmatched_source_lots[0]
                matched = min(to_match, lot[0])
                pair.matched_source_value_usd += matched*lot[1]
                pair.matched_source_fee_usd += matched*(lot[2] if len(lot) > 2 else 0)
                if len(lot) > 4:
                    target_matched = matched*pair.ratio
                    lot[4] += target_matched*fill_price + fee*target_matched/available
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
                       unpaired_btc=pair.unpaired_btc, order_revision=order.revision,
                       limit_price=order.limit_price, eligible_after_us=order.eligible_us,
                       target_effective_lease=pair.target_effective_lease))
        self._drain_queues(trade.us)

    def cancel(self, us, reason="cancelled", symbols=None):
        self.accrue(us)
        pair = self.pairs.get(self.active_pair_id)
        if reason == "end_of_window" and self.cash_recovery is not None:
            self._finish_cash_restoration(us, "end_window_censored")
        if self.pending_initial_decision:
            if self.config.repricing_mode == "empirical" and reason == "end_of_window":
                pending = next((row[2]["decision"] for row in self.decision_queue if row[2].get("action") == "initial"), None)
                if pending is not None:
                    self.empirical_stats["instructions"] += 1
                    self.empirical_stats["end_window_censored"] += 1
                    self._distribution_add(self.empirical_stats["wait_seconds"], "instruction", (us-pending["decision_started_us"])/1e6)
                    self.sink(dict(kind="empirical_instruction_result", us=us, pair_id=None,
                        status="end_window_censored", decision_started_us=pending["decision_started_us"],
                        deadline_us=pending["decision_started_us"]+round(self.config.waiting_seconds*1e6),
                        completed_by_deadline=False, actual_source_btc=0.0, actual_target_btc=0.0,
                        unmatched_source_btc=0.0, residual_cash_usd=0.0,
                        reason="decision_not_completed_before_window_end"))
            self.decision_queue[:] = [row for row in self.decision_queue if row[2].get("action") != "initial"]
            heapq.heapify(self.decision_queue)
            self.pending_initial_decision = False
            self.sink(dict(kind="paired_decision_cancelled", us=us, reason=reason))
        if not pair or (symbols is not None and not {pair.source_symbol, pair.target_symbol} & set(symbols)):
            return
        if pair.empirical and reason in ("end_of_window", "expiry"):
            self._finish_empirical_pair(pair, us, "end_window_censored" if reason == "end_of_window" else "contract_expiry")
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
        return dict(strategy="cost_aware_paired", selection_mode=self.config.selection_mode,
                    submitted_pairs=totals["count"]+len(pairs),
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
                    latest_decision=self.latest_decision, latest_pair_result=self.latest_pair_result,
                    latest_lease_execution=self.latest_lease_execution,
                    limit_anchor=self.config.limit_anchor,
                    lease_window_seconds=self.config.lease_window_seconds,
                    lease_execution_delta_bps=self.config.lease_execution_delta_bps,
                    expected_hedge_slippage_bps=self.config.expected_hedge_slippage_bps,
                    actual_units=dict(self.units), known_units=dict(self.known_units),
                    pending_feed_records=len(self.feed_queue), pending_responses=len(self.response_queue),
                    pending_decisions=len(self.decision_queue), pending_order_commands=len(self.command_queue),
                    replacement_count=self.replacement_count, repricing_mode=self.config.repricing_mode,
                    empirical_execution=self._empirical_summary() if self.config.repricing_mode == "empirical" else None,
                    observation_delay_seconds=self.config.observation_delay_seconds,
                    decision_delay_seconds=self.config.decision_delay_seconds, order_delay_seconds=self.delay_us/1e6,
                    spot_feed_delay_seconds=self.config.spot_feed_delay_seconds,
                    futures_feed_delay_seconds=self.config.futures_feed_delay_seconds,
                    response_delay_seconds=self.config.response_delay_seconds,
                    reserved_usd=sum(p.reserved_usd for p in pairs),
                    execution_model=("tape participation; either funded limit first, then market hedge" if self.rolling_execution else
                                     "tape participation; bounded staged source-first transfers"),
                    settlement_model="scheduled last-trade USD linear-proxy variation; not official venue marks")

    diagnostics = summary

    def snapshot(self):
        state = {k: v for k, v in vars(self).items()
                 if k not in ("sink", "ledger", "config", "fee_schedules", "marks", "observed_marks", "orders", "pairs", "empirical_model", "lease_window")}
        state.update(schema_version=1, config=asdict(self.config), ledger=self.ledger.snapshot(),
                     lease_window=self.lease_window.snapshot(),
                     empirical_model=(self.empirical_model.snapshot() if hasattr(self.empirical_model, "snapshot")
                                      else self.empirical_model.to_dict() if self.empirical_model is not None else None),
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
                      state["fee"]*10000, sink, PairedConfig(**state["config"]), state["expiries"], state.get("empirical_model"))
        for key, value in state.items():
            if key in ("schema_version", "config", "ledger", "empirical_model", "lease_window"):
                continue
            constructor = {"marks": Trade, "observed_marks": Trade, "orders": PairedOrder, "pairs": Transfer}.get(key)
            setattr(account, key, {s: constructor(**v) for s, v in value.items()} if constructor else value)
        account.lease_window = RollingPriceWindow.restore(account.config.lease_window_seconds, state.get("lease_window", {}))
        account.feed_queue = [tuple(row) for row in account.feed_queue]
        account.response_queue = [tuple(row) for row in account.response_queue]
        account.decision_queue = [tuple(row) for row in account.decision_queue]
        account.command_queue = [tuple(row) for row in account.command_queue]
        account._draining = False
        heapq.heapify(account.feed_queue)
        heapq.heapify(account.response_queue)
        heapq.heapify(account.decision_queue)
        heapq.heapify(account.command_queue)
        account.ledger = FundedLedger.restore(state["ledger"], sink=account._ledger_event)
        return account


PairedTapeAccount = PairedTransferAccount
