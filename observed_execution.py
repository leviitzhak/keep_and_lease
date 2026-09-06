"""Causal, quantity-preserving execution for a regular long-only BTC sleeve.

Positive-volume candle closes are a named research fill assumption. Quotes use
bid/ask; carried marks may value inventory but never fill an order. No access to
the next interval's observations is permitted in ``position``.
"""
from collections import deque
from datetime import timedelta
import math


class ObservedExecution:
    def __init__(self, p, first_spot, resolution_seconds):
        if p.futures_contract_type != "regular" or p.enable_short_book:
            raise ValueError("Observed BTC execution supports regular futures with the short book disabled")
        self.p = p
        self.resolution = resolution_seconds
        self.quantities = {}
        self.direct_units = 1.0 / first_spot
        self.cash = 0.0
        self.orders = deque()
        self.active = None
        self.template = None
        self.used_observations = {}

    def position(self, target, day, spot, curve, nav):
        p = self.p
        current = {x["symbol"]: x for x in curve}
        # Values and expiries of held instruments must exist now. In particular,
        # an absent expiry settlement cannot be replaced by a future spot quote.
        for symbol in self.quantities:
            if symbol not in current:
                raise ValueError(f"Missing causal valuation/expiry settlement for held {symbol} at {day.isoformat()}")
        marked = self.cash + self.direct_units * spot
        if not math.isclose(marked, nav, rel_tol=1e-10, abs_tol=1e-10):
            raise AssertionError("Execution inventory does not reconcile to starting NAV")
        if target is not None:
            self.template = target
            self.orders.append((day, dict(target["base_longs"]), target["bond_days"]))
        extra = self.resolution if p.reactivity == "next_day" else 0
        cutoff = day - timedelta(seconds=p.execution_delay_seconds + extra)
        # Strictly later observations are required even with zero requested lag.
        while self.orders and self.orders[0][0] < day and self.orders[0][0] <= cutoff:
            self.active = self.orders.popleft()
        fills, pending = [], []
        future_cost = direct_cost = 0.0
        target_weights = self.active[1] if self.active else {}
        signal_day = self.active[0] if self.active else None
        spot_observed = bool(curve and curve[0].get("spot_observed", False))
        if self.active and spot_observed:
            # Reductions precede increases to limit temporary gross exposure.
            symbols = sorted(set(self.quantities) | set(target_weights),
                             key=lambda s: (target_weights.get(s, 0) > 0, s))
            for symbol in symbols:
                quote = current.get(symbol)
                if quote is None:
                    if target_weights.get(symbol, 0):
                        pending.append({"symbol": symbol, "reason": "no current valuation"})
                    continue
                mark = quote["future"]
                old = self.quantities.get(symbol, 0.0)
                wanted = target_weights.get(symbol, 0.0) * nav / mark
                change = wanted - old
                if abs(change) <= 1e-15:
                    continue
                available = quote.get("available_at")
                age = quote.get("quote_age_seconds")
                # The whole candle must follow the decision; its earlier trades
                # must never be selected using an end-of-bar signal.
                eligible = (quote.get("observed", False) and available is not None
                            and available > signal_day and available <= day
                            and quote.get("observation_start", available) >= signal_day
                            and (available - signal_day).total_seconds() >= p.execution_delay_seconds + extra
                            and age is not None and age <= p.max_quote_age_seconds
                            and quote.get("days", 0) > 0
                            and self.used_observations.get(symbol) != available)
                if not eligible:
                    pending.append({"symbol": symbol, "reason": "awaiting eligible observation",
                                    "target_quantity": wanted, "held_quantity": old})
                    continue
                action = "buy" if change > 0 else "sell"
                quoted = quote.get("ask" if change > 0 else "bid")
                is_quote = quote.get("source_kind") == "quote"
                if is_quote and quoted is None:
                    pending.append({"symbol": symbol, "reason": "missing executable side"})
                    continue
                capacity = (quote.get("ask_size" if change > 0 else "bid_size")
                            if is_quote else quote.get("volume", 0))
                if capacity is not None:
                    if not math.isfinite(capacity) or capacity < 0:
                        raise ValueError("Invalid normalized execution size")
                    change = math.copysign(min(abs(change), capacity * p.max_volume_participation), change)
                if change > 0:
                    used = sum(q * current[s]["future"] for s, q in self.quantities.items())
                    ceiling = min(p.max_futures_treasury_fraction, sum(target_weights.values())) * nav
                    change = min(change, max(0.0, ceiling - used) / mark)
                if abs(change) <= 1e-15:
                    pending.append({"symbol": symbol, "reason": "insufficient size"})
                    continue
                spread = 0 if quoted is not None else p.half_spread_bps
                fill_price = (quoted or mark) * (1 + (1 if change > 0 else -1) *
                                                (spread + p.slippage_bps) / 10000)
                fee = abs(change) * fill_price * p.trading_fee_bps / 10000
                price_cost = change * (fill_price - mark)
                future_cost += fee + price_cost
                quantity = old + change
                if abs(quantity) <= 1e-15:
                    self.quantities.pop(symbol, None)
                else:
                    self.quantities[symbol] = quantity
                self.used_observations[symbol] = available
                fills.append({"symbol": symbol, "action": action, "quantity_change": change,
                              "quantity_before": old, "quantity_after": quantity,
                              "target_quantity": wanted, "mark_price": mark, "price": fill_price,
                              "fee_usd": fee, "price_cost_usd": price_cost,
                              "signal_time": signal_day.isoformat(), "fill_time": day.isoformat(),
                              "available_at": available.isoformat(),
                              "observation_start": quote["observation_start"].isoformat(),
                              "observed": True, "quote_age_seconds": age,
                              "source_kind": quote.get("source_kind"),
                              "available_size_btc": capacity,
                              "size_validated": capacity is not None})
                if abs(quantity - wanted) > 1e-15:
                    pending.append({"symbol": symbol, "reason": "partial fill",
                                    "target_quantity": wanted, "held_quantity": quantity})
        future_notional = sum(q * current[s]["future"] for s, q in self.quantities.items())
        # Pair achieved futures exposure with Treasury collateral/direct holding.
        # No futures fill means quantities remain held, including the direct leg.
        if spot_observed and (fills or (self.active and not self.quantities and not target_weights)):
            remaining = max(0.0, nav - future_cost - future_notional)
            old_value = self.direct_units * spot
            spot_cost_rate = (p.trading_fee_bps + p.half_spread_bps + p.slippage_bps) / 10000
            # Solve X + c*abs(X-old_value) = remaining for the direct target.
            new_value = ((remaining + spot_cost_rate * old_value) / (1 + spot_cost_rate)
                         if remaining >= old_value else
                         max(0.0, (remaining - spot_cost_rate * old_value) / (1 - spot_cost_rate)))
            new_units = new_value / spot
            direct_cost = abs(new_units - self.direct_units) * spot * spot_cost_rate
            if abs(new_units - self.direct_units) > 1e-15:
                fills.append({"symbol": "BTC-USD", "action": "buy" if new_units > self.direct_units else "sell",
                              "quantity_change": new_units - self.direct_units,
                              "quantity_before": self.direct_units, "quantity_after": new_units,
                              "mark_price": spot, "cost_usd": direct_cost,
                              "signal_time": signal_day.isoformat(), "fill_time": day.isoformat(),
                              "source_kind": "spot_candle_research", "observed": True})
            self.direct_units = new_units
        total_cost = future_cost + direct_cost
        self.cash = nav - self.direct_units * spot - total_cost
        if self.cash < -1e-10 or nav <= total_cost:
            raise ValueError("Execution costs exceed available capital")
        self.cash = max(0.0, self.cash)
        template = self.template or {
            "mode": "neutral", "signal": 0, "positive_signal": 0, "negative_signal": 0,
            "bond_days": 91, "long_leg": {}, "short_leg": {},
            "diagnostic_longs": {}, "diagnostic_shorts": {},
        }
        longs = {s: q * current[s]["future"] / nav for s, q in self.quantities.items()}
        result = {**template, "slv": self.direct_units * spot / nav,
                  "base_slv": self.direct_units * spot / nav,
                  "treasury": self.cash / nav, "base_treasury": self.cash / nav,
                  "base_longs": longs, "longs": longs, "shorts": {},
                  "contracts": current, "long_extension": 0, "extension_ratio": 0,
                  "bond_days": self.active[2] if self.active else 91}
        quality = [{"symbol": s, "observed": current[s].get("observed", False),
                    "last_observed_at": (current[s]["last_observed_at"].isoformat()
                                         if current[s].get("last_observed_at") else None),
                    "quote_age_seconds": current[s].get("quote_age_seconds"),
                    "source_kind": current[s].get("source_kind")}
                   for s in longs]
        result["execution_audit"] = {"model": "observed", "fills": fills,
                                     "pending_orders": pending, "valuation_marks": quality,
                                     "future_cost_usd": future_cost, "direct_cost_usd": direct_cost,
                                     "total_cost_usd": total_cost,
                                     "order_signal_time": signal_day.isoformat() if signal_day else None,
                                     "decision_time": day.isoformat(),
                                     "simulation_initial_notional_usd": 1.0}
        return result

    def settle(self, day, exit_day, spot_start, spot_end, contracts, treasury_return, elapsed, nav):
        self.cash *= 1 + treasury_return
        for symbol, quantity in self.quantities.items():
            prices = contracts.get(symbol, {})
            if day not in prices or exit_day not in prices:
                raise ValueError(f"Missing valuation/settlement for held {symbol} at {exit_day.isoformat()}")
            self.cash += quantity * (prices[exit_day] - prices[day])
        self.direct_units -= self.direct_units * spot_start * self.p.slv_expense * elapsed / 365 / spot_end
        equity = self.cash + self.direct_units * spot_end
        if not math.isclose(equity, nav, rel_tol=1e-10, abs_tol=1e-10):
            raise AssertionError("Execution inventory does not reconcile to ending NAV")
