"""Causal rolling price-pair bounds and funded limit-then-market replay.

Prices are observed trade proxies, not simultaneous executable quotations.
The two extrema queues per symbol give the exact Cartesian price-pair bounds
without materializing every spot/future combination. All state is checkpointed.
"""
from collections import deque
from dataclasses import replace
import copy
import math

YEAR_US = 365 * 86400 * 1_000_000
EPS = 1e-12


class RollingPriceWindow:
    def __init__(self, seconds):
        self.window_us = round(seconds * 1e6)
        self.queues = {}

    def observe(self, symbol, price, source_us, available_us):
        queues = self.queues.setdefault(symbol, {"min": deque(), "max": deque()})
        for key, queue in queues.items():
            while queue and (queue[-1][0] >= price if key == "min" else queue[-1][0] <= price):
                queue.pop()
            queue.append((price, source_us, available_us))
        self.extrema(symbol, available_us)

    def extrema(self, symbol, now_us):
        queues = self.queues.get(symbol)
        if not queues:
            return None
        for queue in queues.values():
            while queue and queue[0][1] < now_us - self.window_us:
                queue.popleft()
        if not all(queues.values()):
            return None
        return {key: dict(price=q[0][0], source_us=q[0][1], available_us=q[0][2])
                for key, q in queues.items()}

    def bounds(self, symbol, now_us, expiry_us, cash_rate):
        spot, future = self.extrema("SPOT", now_us), self.extrema(symbol, now_us)
        years = (expiry_us - now_us) / YEAR_US
        if not spot or not future or years <= 0:
            return None
        return dict(symbol=symbol, reference_us=now_us, years=years, cash_rate=cash_rate,
                    window_start_us=now_us-self.window_us, window_end_us=now_us,
                    min_lease=cash_rate-(future["max"]["price"]/spot["min"]["price"]-1)/years,
                    max_lease=cash_rate-(future["min"]["price"]/spot["max"]["price"]-1)/years,
                    spot_extrema=spot, future_extrema=future,
                    estimator="all_observed_price_pairs_in_trailing_source_time_window")

    def snapshot(self):
        return {s: {k: list(q) for k, q in qs.items()} for s, qs in self.queues.items()}

    @classmethod
    def restore(cls, seconds, state):
        result = cls(seconds)
        result.queues = {s: {k: deque(tuple(r) for r in rows) for k, rows in qs.items()}
                         for s, qs in state.items()}
        return result


class RollingLeaseExecutionMixin:
    @property
    def rolling_execution(self):
        return self.config.repricing_mode == "rolling_worst"

    def _rolling_context(self, us, source, target):
        spot = self.observed_marks.get("SPOT")
        if spot is None:
            return None
        rates, factors = {}, {"SPOT": 1.0}
        for symbol in (source, target):
            if symbol == "SPOT":
                continue
            bound = self.lease_window.bounds(symbol, us, self.expiries[symbol], self.rate)
            if bound is None:
                return None
            # Lower lease is adverse on entry; higher lease is adverse on exit.
            entry = symbol == target
            delta = (-1 if entry else 1) * self.config.lease_execution_delta_bps / 10000
            worst = bound["min_lease" if entry else "max_lease"]
            target_rate = worst + delta
            factor = 1 + (self.rate-target_rate)*bound["years"]
            if not math.isfinite(factor) or factor <= 0:
                return None
            rates[symbol] = {**bound, "direction": "entry" if entry else "exit",
                             "worst_observed_lease": worst, "execution_delta": delta,
                             "target_lease": target_rate}
            factors[symbol] = factor
        return dict(reference_us=us, spot_reference_price=spot.price, rates=rates,
                    limit_anchor=self.config.limit_anchor,
                    factors=factors, expected_hedge_slippage_bps=self.config.expected_hedge_slippage_bps)

    def _rolling_evaluate(self, us, source, target, spot, config, *, context=None, entry_fees=None):
        from paired_amortized_strategy import evaluate_amortized_transfer
        from paired_transfer_economics import TransferDecision
        context = context or self._rolling_context(us, source.quote.symbol, target.symbol)
        if context is None:
            return TransferDecision(False, "missing_rolling_price_window",
                source_symbol=source.quote.symbol, target_symbol=target.symbol)
        factors = context["factors"]
        decision = evaluate_amortized_transfer(us, source, target, spot,
            cash_rate=self.rate, fees=self.fee_schedules, config=config,
            source_price=spot.price*factors[source.quote.symbol],
            target_price=spot.price*factors[target.symbol],
            account_execution_price_costs=True,
            source_entry_fees=(entry_fees or {}).get("source"),
            target_entry_fees=(entry_fees or {}).get("target"),
            expected_hedge_slippage_bps=self.config.expected_hedge_slippage_bps)
        return replace(decision, diagnostics={**decision.diagnostics,
            "lease_estimator": "all_observed_price_pairs_in_trailing_source_time_window",
            "rolling_lease": context})

    def _rolling_limits(self, context, source, target, observations=None):
        observations = self.observed_marks if observations is None else observations
        factors = context["factors"]
        if context.get("limit_anchor", "relative_price") == "spot":
            spot = context["spot_reference_price"]
            # Futures use observed spot. A spot leg inverts the counterpart's
            # lease relation. Expected hedge slippage remains an admission cost.
            floor = (spot*factors[source] if source != "SPOT" else
                     observations[target].price/factors[target])
            cap = (spot*factors[target] if target != "SPOT" else
                   observations[source].price/factors[source])
            return floor, cap
        ratio = factors[target]/factors[source]
        slip = context["expected_hedge_slippage_bps"] / 10000
        return (observations[target].price*(1+slip)/ratio,
                observations[source].price*(1-slip)*ratio)

    def _initialize_rolling(self, pair, observations):
        context = pair.decision["diagnostics"]["rolling_lease"]
        pair.rolling = pair.repricing_supported = True
        return self._rolling_limits(context, pair.source_symbol, pair.target_symbol, observations)

    def _rolling_order_context(self, context, role, floor, cap, source, target, observations=None):
        context = copy.deepcopy(context)
        observations = self.observed_marks if observations is None else observations
        slip = context["expected_hedge_slippage_bps"]/10000
        source_price = floor if role == "source" else observations[source].price*(1-slip)
        target_price = observations[target].price*(1+slip) if role == "source" else cap
        spot = source_price if source == "SPOT" else target_price if target == "SPOT" else context["spot_reference_price"]
        context.update(source_limit=floor, target_limit=cap,
            expected_source_price=source_price, expected_target_price=target_price)
        for symbol, bound in context["rates"].items():
            price = source_price if symbol == source else target_price
            bound["set_lease"] = bound["cash_rate"]-(price/spot-1)/bound["years"]
        return context

    def _schedule_rolling_reprice(self, us, pair):
        if pair.reprice_pending or pair.transport_pending:
            pair.reprice_dirty = True
            return
        source, target = self.orders[pair.source_symbol], self.orders[pair.target_symbol]
        difference = pair.source_filled_btc-pair.target_filled_btc/pair.ratio
        commands = []
        if abs(difference) > EPS:
            # Once one leg fills, valuation cannot veto the market hedge.
            order = target if difference > 0 else source
            if not order.market_order:
                commands.append((order, order.limit_price, order.lease_context, True))
        elif pair.status == "pending" and not pair.cancel_pending:
            fresh, _ = self._fresh_pair(us, pair.source_symbol, pair.target_symbol)
            if not fresh:
                return
            from paired_transfer_economics import PositionSlice
            quotes = self.observed_quotes()
            quantity = min(abs(source.signed_btc)-source.filled_btc,
                           self.units.get(source.symbol, 0))
            if quantity <= EPS:
                return
            reference = sum(l.quantity*l.reference_price for l in self.ledger.lots.get(source.symbol, []))
            held = self.units.get(source.symbol, 0)
            cash = 0 if source.symbol == "SPOT" else min(self.cash, reference*quantity/held)
            unsettled = 0 if source.symbol == "SPOT" else quantity*quotes[source.symbol].price-reference*quantity/held
            context = self._rolling_context(us, source.symbol, target.symbol)
            decision = self._rolling_evaluate(us, PositionSlice(quotes[source.symbol], quantity, cash, unsettled),
                quotes[target.symbol], quotes["SPOT"], replace(self.config.economics_config(),
                    max_transfer_fraction=1, max_delta_btc=quantity), context=context,
                    entry_fees={"source": self._incremental_fee(source), "target": self._incremental_fee(target)})
            if not decision.accepted:
                self._request_source_cancel(us, "remaining_"+decision.reason)
                return
            floor, cap = self._rolling_limits(context, source.symbol, target.symbol)
            commands = [(order, limit, self._rolling_order_context(context, order.role,
                floor, cap, source.symbol, target.symbol), False)
                for order, limit in ((source, floor), (target, cap))]
        packed = []
        for order, limit, context, market in commands:
            self.queue_sequence += 1
            packed.append(dict(action="replace", pair_id=pair.pair_id,
                order_id=order.identifier, symbol=order.symbol, role=order.role,
                revision=self.queue_sequence, limit_price=limit, market_order=market,
                lease_context=copy.deepcopy(context), binding_constraint="market_hedge" if market else "rolling_worst_lease",
                observation_us=max(self.observed_available_us.get(s, 0) for s in (source.symbol, target.symbol)),
                decision_started_us=us, fill_revision=pair.fill_revision))
        if packed:
            pair.reprice_pending, pair.reprice_dirty = True, False
            self._push_event(self.decision_queue, us+round(self.config.decision_delay_seconds*1e6),
                dict(action="reprice", pair_id=pair.pair_id, commands=packed))

    def _rolling_state(self, us):
        pair = self.pairs.get(self.active_pair_id)
        if not pair:
            return
        for order in self.orders.values():
            current = self._rolling_context(us, pair.source_symbol, pair.target_symbol)
            self.sink(dict(kind="lease_limit_state", us=us, pair_id=pair.pair_id,
                symbol=order.symbol, role=order.role, limit_price=order.limit_price,
                order_revision=order.revision, market_order=order.market_order,
                active=order.active, eligible_after_us=order.eligible_us,
                lease_context=copy.deepcopy(order.lease_context), current_rolling_lease=current))

    def _rolling_match_audit(self, pair, us, first, second, source_qty):
        source = first if first["role"] == "source" else second
        target = second if first["role"] == "source" else first
        context = first["context"]
        spot = (source["price"] if pair.source_symbol == "SPOT" else
                target["price"] if pair.target_symbol == "SPOT" else context["spot_reference_price"])
        for symbol, bound in context["rates"].items():
            price = target["price"] if symbol == pair.target_symbol else source["price"]
            executed = bound["cash_rate"]-(price/spot-1)/bound["years"]
            self.sink(dict(kind="lease_execution", us=us, pair_id=pair.pair_id, symbol=symbol,
                direction=bound["direction"], first_role=first["role"],
                hit_order_id=first["order_id"], hit_order_revision=first["revision"],
                hit_limit_price=first["limit"], first_fill_us=first["us"],
                matched_source_btc=source_qty, source_fill_price=source["price"],
                target_fill_price=target["price"], worst_observed_lease=bound["worst_observed_lease"],
                set_lease=bound["set_lease"], target_lease=bound["target_lease"], execution_delta=bound["execution_delta"],
                executed_lease=executed, executed_minus_set_lease=executed-bound["set_lease"],
                adverse_lease_slippage=(bound["set_lease"]-executed)*(1 if bound["direction"] == "entry" else -1),
                reference_us=context["reference_us"], years=bound["years"], cash_rate=bound["cash_rate"],
                expected_hedge_slippage_bps=context["expected_hedge_slippage_bps"],
                hedge_wait_seconds=(us-first["us"])/1e6, lease_context=context))
            self.latest_lease_execution = dict(pair_id=pair.pair_id, symbol=symbol,
                worst_observed_lease=bound["worst_observed_lease"], set_lease=bound["set_lease"],
                executed_lease=executed, hit_order_revision=first["revision"])

    def _execute_rolling(self, trade):
        pair, order = self.pairs.get(self.active_pair_id), self.orders.get(trade.symbol)
        if not pair or not order or not order.active or not trade.executable or trade.us <= order.eligible_us:
            return
        difference = pair.source_filled_btc-pair.target_filled_btc/pair.ratio
        recovery = abs(difference) > EPS
        if not recovery and (pair.status != "pending" or self._pair_has_responses(pair.pair_id)):
            return
        # A still-resting opposite limit can fill during acknowledgment latency;
        # a market replacement cannot arrive before that acknowledgment.
        if recovery and order.role != ("target" if difference > 0 else "source"):
            return
        buying = order.role == "target"
        if trade.side != ("buy" if buying else "sell"):
            return
        adjustment = (self.config.half_spread_bps+self.config.slippage_bps)/10000
        price = trade.price*(1+adjustment if buying else 1-adjustment)
        if not order.market_order and (price > order.limit_price if buying else price < order.limit_price):
            return
        if not recovery:
            fresh, _ = self._fresh_pair(trade.us, pair.source_symbol, pair.target_symbol)
            if not fresh or self._rolling_context(trade.us, pair.source_symbol, pair.target_symbol) is None:
                return
        quantity = min(abs(order.signed_btc)-order.filled_btc, trade.btc*self.participation,
            abs(difference)*(pair.ratio if buying else 1) if recovery else
            self.config.max_unpaired_btc*(pair.ratio if buying else 1))
        if not buying:
            quantity = min(quantity, self.units.get(order.symbol, 0))
        else:
            # Target-first is allowed only from already free funding, never by
            # borrowing the proceeds of a source sale which has not happened.
            budget = pair.reserved_usd if recovery else self.ledger.available_cash
            from paired_transfer_economics import funded_quantity
            affordable, _ = funded_quantity(budget, price,
                {"target": self._incremental_fee(order)}, "target")
            quantity = min(quantity, affordable)
        if quantity <= EPS:
            return
        if not buying and not recovery:
            # A source print too small to cover the market hedge's fee ticket
            # must not create an unhedgeable first tranche.
            target_order = self.orders[pair.target_symbol]
            reference = self.observed_marks[pair.target_symbol].price*(1+adjustment)
            source_fee = self._incremental_fee(order).total_fee(quantity, quantity*price)
            target_fee = self._incremental_fee(target_order).total_fee(quantity*pair.ratio,
                quantity*pair.ratio*reference)
            if quantity*pair.ratio*reference+target_fee > quantity*price-source_fee+EPS:
                return
        from funded_ledger import FundingError
        signed, ticket = (quantity if buying else -quantity), f"{pair.pair_id}:{order.role}"
        before = self.ledger.available_cash
        funding_before = before+pair.reserved_usd
        try:
            fee = self.ledger.execute_fill(trade.symbol, signed, price, ticket,
                timestamp_us=trade.us, reservation_id=pair.pair_id)
        except FundingError:
            return
        self.ledger.mark(trade.symbol, trade.price, timestamp_us=trade.us)
        if trade.symbol == "SPOT":
            self.plot_spot_pnl -= signed*(price-trade.price)
        else:
            self.plot_futures_pnl -= signed*(price-trade.price)
        order.filled_btc += quantity
        order.filled_value += quantity*price
        order.fee_usd += fee
        pair.fees_usd += fee
        pair.fill_revision += 1
        if buying:
            pair.target_filled_btc += quantity
            pair.target_value_usd += quantity*price
            pair.first_target_fill_us = pair.first_target_fill_us or trade.us
            pair.last_target_fill_us = trade.us
            pair.reserved_usd = max(0, pair.reserved_usd-quantity*price-fee)
        else:
            pair.source_filled_btc += quantity
            pair.source_value_usd += quantity*price
            pair.first_source_fill_us = pair.first_source_fill_us or trade.us
            if not recovery:
                pair.reserved_usd += max(0, self.ledger.available_cash-before)
        lot = dict(quantity=quantity/pair.ratio if buying else quantity,
            price=price, role=order.role, fee_per_source_btc=fee/(quantity/pair.ratio if buying else quantity),
            context=copy.deepcopy(order.lease_context), order_id=order.identifier,
            revision=order.revision, limit=order.limit_price, us=trade.us)
        while lot["quantity"] > EPS and pair.rolling_lots:
            first = pair.rolling_lots[0]
            if first["role"] == lot["role"]:
                break
            matched = min(lot["quantity"], first["quantity"])
            self._rolling_match_audit(pair, trade.us, first, lot, matched)
            source_lot = lot if not buying else first
            pair.matched_source_value_usd += matched*source_lot["price"]
            pair.matched_source_fee_usd += matched*source_lot["fee_per_source_btc"]
            target_lot = lot if buying else first
            pair.matched_target_value_usd += matched*pair.ratio*target_lot["price"]
            pair.matched_target_fee_usd += matched*target_lot["fee_per_source_btc"]
            first["quantity"] -= matched
            lot["quantity"] -= matched
            if first["quantity"] <= EPS:
                pair.rolling_lots.pop(0)
        if lot["quantity"] > EPS:
            pair.rolling_lots.append(lot)
        self.ledger.release(pair.pair_id)
        pair.reserved_usd = min(pair.reserved_usd, self.ledger.available_cash)
        if pair.reserved_usd > EPS:
            self.ledger.reserve(pair.pair_id, pair.reserved_usd)
        if pair.unpaired_btc > EPS:
            pair.first_unpaired_us = pair.first_unpaired_us or trade.us
        else:
            if pair.first_unpaired_us is not None:
                pair.max_legging_us = max(pair.max_legging_us, trade.us-pair.first_unpaired_us)
            pair.first_unpaired_us = None
            pair.reserved_usd = 0
            self.ledger.release(pair.pair_id)
            # Both old instructions remain suspended until a new limit revision
            # arrives, so a recovery market instruction cannot start a new lot.
            for child in self.orders.values():
                child.active = False
        pair.max_unpaired_btc = max(pair.max_unpaired_btc, pair.unpaired_btc)
        self.turnover += quantity*price
        self.fill_count += 1
        self.delayed_fill_count += int(trade.reported_us is not None and trade.us > trade.reported_us)
        ack = trade.us+round(self.config.response_delay_seconds*1e6)
        self._push_event(self.response_queue, ack, dict(pair_id=pair.pair_id,
            order_id=order.identifier, symbol=trade.symbol, signed_btc=signed, exchange_fill_us=trade.us))
        self.sink(dict(kind="fill", us=trade.us, pair_id=pair.pair_id,
            order_id=order.identifier, ticket_id=ticket, trade_id=trade.identifier,
            symbol=trade.symbol, role=order.role, side=trade.side, signed_btc=signed,
            price=price, raw_trade_price=trade.price, observed_btc=trade.btc,
            available_funding_before_usd=funding_before,
            reported_us=self._source_us(trade), source_sequence=trade.sequence,
            fee_usd=fee, cash_usd=self.cash, nav_usd=self.nav, acknowledgement_us=ack,
            reserved_usd=pair.reserved_usd, unpaired_btc=pair.unpaired_btc,
            order_revision=order.revision, limit_price=order.limit_price,
            market_order=order.market_order, eligible_after_us=order.eligible_us,
            lease_context=copy.deepcopy(order.lease_context)))
        self._drain_queues(trade.us)
