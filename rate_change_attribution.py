"""Start-of-period maturity and curve-change attribution helpers.

These helpers enforce the timing and ownership conventions in
``docs/BACKTEST_ENGINE.md``.  Pricing-model-specific callers provide observed
and frozen-curve end values; this module handles signed holdings,
normalization, reconstruction details and scatter-point eligibility.
"""

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class InstrumentAttribution:
    symbol: str
    signed_notional: float
    start_maturity: float
    observed_end_value: float
    frozen_curve_end_value: float
    rate_before: float | None = None
    rate_after: float | None = None

    @property
    def absolute_notional(self) -> float:
        return abs(self.signed_notional)

    @property
    def rate_change_pnl(self) -> float:
        return self.signed_notional * (
            self.observed_end_value - self.frozen_curve_end_value)


def absolute_notional_weighted_maturity(
        instruments: Iterable[InstrumentAttribution]) -> float | None:
    instruments = list(instruments)
    denominator = sum(item.absolute_notional for item in instruments)
    if denominator <= 0:
        return None
    return sum(item.absolute_notional * item.start_maturity
               for item in instruments) / denominator


def build_rate_change_point(
        *, start_date: str, end_date: str, leg: str, commodity: str,
        instruments: Iterable[InstrumentAttribution],
        portfolio_value: float | None,
        minimum_position_size: float = 0.0) -> dict:
    """Build one reconstructable maturity-versus-rate-change-return point."""
    items = list(instruments)
    absolute_notional = sum(item.absolute_notional for item in items)
    weighted_maturity = absolute_notional_weighted_maturity(items)
    pnl = sum(item.rate_change_pnl for item in items)

    exclusion_reason = None
    if not items:
        exclusion_reason = "no instruments"
    elif absolute_notional <= minimum_position_size:
        exclusion_reason = "position below minimum size"
    elif weighted_maturity is None:
        exclusion_reason = "zero absolute notional"

    portfolio_relative = (
        pnl / portfolio_value
        if exclusion_reason is None and portfolio_value not in (None, 0)
        else None
    )
    position_relative = (
        pnl / absolute_notional
        if exclusion_reason is None and absolute_notional > 0
        else None
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "leg": leg,
        "commodity": commodity,
        "weighted_maturity": weighted_maturity,
        "rate_change_pnl": pnl,
        "portfolio_relative_return": portfolio_relative,
        "position_relative_return": position_relative,
        "absolute_notional": absolute_notional,
        "excluded": exclusion_reason is not None,
        "exclusion_reason": exclusion_reason,
        "instruments": [{
            "symbol": item.symbol,
            "signed_notional": item.signed_notional,
            "absolute_weight": (
                item.absolute_notional / absolute_notional
                if absolute_notional > 0 else None),
            "start_maturity": item.start_maturity,
            "rate_before": item.rate_before,
            "rate_after": item.rate_after,
            "observed_end_value": item.observed_end_value,
            "frozen_curve_end_value": item.frozen_curve_end_value,
            "rate_change_pnl": item.rate_change_pnl,
        } for item in items],
    }


def group_scatter_points(points: Iterable[Mapping]) -> dict[str, list[dict]]:
    """Return one scatter series per active leg and commodity combination."""
    result: dict[str, list[dict]] = {}
    for point in points:
        if point.get("excluded"):
            continue
        key = f"{point['leg']}::{point['commodity']}"
        result.setdefault(key, []).append(dict(point))
    return result
