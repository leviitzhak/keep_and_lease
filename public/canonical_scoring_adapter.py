"""Install the canonical maturity scoring engine into the browser backtest.

The historical backtest module still contains compatibility helper functions used by
older local scripts. The deployed worker calls :func:`install`, replacing the
active score helper with this adapter. All boundary and pure-maturity score
calculations therefore come from ``maturity_scoring.py``.
"""

from __future__ import annotations

from contextlib import contextmanager

from maturity_scoring import (
    BoundaryAnchors,
    PureMaturityPreference,
    RelativeAdjustment,
    signed_distance,
)


_CONTEXT = {"minimum": 0.0, "maximum": 0.0}


def _number(payload, name, default):
    raw = payload.get(name, default)
    if raw is None or str(raw).strip() == "":
        raw = default
    return float(raw)


def _configure_parameters(parameter_object, payload):
    """Attach canonical scoring controls to the mutable legacy parameter object."""
    parameter_object.long_relative_strength = _number(
        payload, "long_relative_strength", 1.0)
    parameter_object.long_score_rate_scale = _number(
        payload, "long_score_rate_scale", 1.0) / 100.0
    parameter_object.long_score_adjustment_clip = _number(
        payload, "long_score_adjustment_clip", 3.0)
    parameter_object.long_pure_maturity_strength = _number(
        payload, "long_pure_maturity_strength", 0.25)

    parameter_object.short_relative_strength = _number(
        payload, "short_relative_strength", 1.0)
    parameter_object.short_score_rate_scale = _number(
        payload, "short_score_rate_scale", 1.0) / 100.0
    parameter_object.short_score_adjustment_clip = _number(
        payload, "short_score_adjustment_clip", 3.0)
    parameter_object.short_pure_maturity_strength = _number(
        payload, "short_pure_maturity_strength", 0.25)

    # Validate at request parsing time so the GUI receives a useful error.
    for direction in ("long", "short"):
        RelativeAdjustment(
            strength=getattr(parameter_object, f"{direction}_relative_strength"),
            rate_scale=getattr(parameter_object, f"{direction}_score_rate_scale"),
            clip=getattr(parameter_object, f"{direction}_score_adjustment_clip"),
        )
        PureMaturityPreference(
            strength=getattr(
                parameter_object, f"{direction}_pure_maturity_strength"))
    return parameter_object


def _boundary(parameter_object, direction):
    intercept = getattr(parameter_object, f"{direction}_maturity_line_intercept")
    slope_per_year = getattr(
        parameter_object, f"{direction}_maturity_line_slope_per_year")
    return BoundaryAnchors.from_slope_intercept(
        maturity_1=0.0,
        maturity_2=365.0,
        slope=slope_per_year / 365.0,
        intercept=intercept,
    )


def _adjustment(parameter_object, direction):
    return RelativeAdjustment(
        strength=getattr(parameter_object, f"{direction}_relative_strength", 1.0),
        rate_scale=getattr(parameter_object, f"{direction}_score_rate_scale", 0.01),
        clip=getattr(parameter_object, f"{direction}_score_adjustment_clip", 3.0),
    )


def _preference(parameter_object, direction):
    return PureMaturityPreference(
        strength=getattr(
            parameter_object, f"{direction}_pure_maturity_strength", 0.25))


def canonical_adjusted_score(base_score, contract, parameter_object, direction):
    """Apply the boundary multiplier and then the pure-maturity multiplier."""
    if base_score <= 0:
        return 0.0
    maturity = float(contract["days"])
    rate = float(contract["lease"])
    adjustment = _adjustment(parameter_object, direction)
    distance = signed_distance(rate, maturity, _boundary(parameter_object, direction),
                               direction)
    boundary_score = adjustment.score(base_score, distance)
    maturity_multiplier = _preference(parameter_object, direction).multiplier(
        maturity, _CONTEXT["minimum"], _CONTEXT["maximum"], direction)
    return boundary_score * maturity_multiplier


@contextmanager
def _maturity_context(candidates, minimum_days):
    maturities = [float(row["days"]) for row in candidates
                  if float(row["days"]) >= minimum_days]
    previous = dict(_CONTEXT)
    if maturities:
        _CONTEXT.update(minimum=min(maturities), maximum=max(maturities))
    else:
        _CONTEXT.update(minimum=0.0, maximum=0.0)
    try:
        yield
    finally:
        _CONTEXT.update(previous)


def install(strategy_module, gui_module):
    """Make the canonical module the only active deployed scoring implementation."""
    original_positions_for_day = strategy_module.positions_for_day
    original_parameters = gui_module.parameters

    def parameters(payload):
        return _configure_parameters(original_parameters(payload), payload)

    def positions_for_day(candidates, parameter_object, previous=None):
        with _maturity_context(candidates, parameter_object.min_days):
            return original_positions_for_day(candidates, parameter_object, previous)

    strategy_module.maturity_line_adjusted_score = canonical_adjusted_score
    strategy_module.positions_for_day = positions_for_day
    gui_module.parameters = parameters
    return strategy_module, gui_module
