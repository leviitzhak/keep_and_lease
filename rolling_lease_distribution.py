"""Exact, causal rolling distributions of lease rates over observed trades.

Each eligible trade has one vote in the median. Prices are kept in a bounded
sorted list, so querying the two middle values does not sort the tape again.
For spot history, transform both middle prices before averaging their leases:
the reciprocal of the median spot is not generally the median reciprocal.
"""
from bisect import bisect_left, insort
from collections import deque

from rolling_lease_execution import YEAR_US


class RollingLeaseDistributionWindow:
    def __init__(self, seconds):
        self.window_us = round(seconds * 1e6)
        self.observations = {}
        self.prices = {}

    def _expire(self, symbol, now_us):
        rows = self.observations.get(symbol, ())
        prices = self.prices.get(symbol, [])
        while rows and rows[0][1] < now_us - self.window_us:
            price, _, _ = rows.popleft()
            prices.pop(bisect_left(prices, price))

    def observe(self, symbol, price, source_us, available_us):
        rows = self.observations.setdefault(symbol, deque())
        prices = self.prices.setdefault(symbol, [])
        rows.append((price, source_us, available_us))
        insort(prices, price)
        self._expire(symbol, available_us)

    def statistics(self, symbol, now_us):
        self._expire(symbol, now_us)
        prices = self.prices.get(symbol, [])
        if not prices:
            return None
        n = len(prices)
        lo, hi = prices[(n-1)//2], prices[n//2]
        rows = self.observations[symbol]
        return dict(count=n, minimum=prices[0], maximum=prices[-1],
                    median=(lo+hi)/2, median_reciprocal=(1/lo+1/hi)/2,
                    first_source_us=rows[0][1], last_source_us=rows[-1][1],
                    last_available_us=rows[-1][2])

    def distributions(self, symbol, now_us, expiry_us, cash_rate,
                      current_spot, current_future, alpha, combine):
        spot, future = self.statistics("SPOT", now_us), self.statistics(symbol, now_us)
        years = (expiry_us-now_us)/YEAR_US
        if not spot or not future or years <= 0:
            return None
        spot_rates = dict(
            minimum=cash_rate-(current_future/spot["minimum"]-1)/years,
            median=cash_rate-(current_future*spot["median_reciprocal"]-1)/years,
            maximum=cash_rate-(current_future/spot["maximum"]-1)/years)
        future_rates = dict(
            minimum=cash_rate-(future["maximum"]/current_spot-1)/years,
            median=cash_rate-(future["median"]/current_spot-1)/years,
            maximum=cash_rate-(future["minimum"]/current_spot-1)/years)
        for rates in (spot_rates, future_rates):
            rates["target"] = rates["median"]+alpha*(rates["maximum"]-rates["median"])
        a, b = spot_rates["target"], future_rates["target"]
        target = min(a, b) if combine == "min" else max(a, b) if combine == "max" else (a+b)/2
        return dict(symbol=symbol, reference_us=now_us, years=years, cash_rate=cash_rate,
                    window_start_us=now_us-self.window_us, window_end_us=now_us,
                    current_spot_price=current_spot, current_future_price=current_future,
                    spot_history=spot, future_history=future,
                    spot_history_leases=spot_rates, future_history_leases=future_rates,
                    min_lease=min(spot_rates["minimum"], future_rates["minimum"]),
                    max_lease=max(spot_rates["maximum"], future_rates["maximum"]),
                    target_alpha=alpha, target_combine=combine, target_lease=target,
                    median_weighting="observed_trades",
                    estimator="current_leg_against_separate_trailing_trade_distributions")

    def snapshot(self):
        return {symbol: list(rows) for symbol, rows in self.observations.items()}

    @classmethod
    def restore(cls, seconds, state):
        result = cls(seconds)
        result.observations = {s: deque(tuple(r) for r in rows) for s, rows in state.items()}
        result.prices = {s: sorted(r[0] for r in rows) for s, rows in state.items()}
        return result
