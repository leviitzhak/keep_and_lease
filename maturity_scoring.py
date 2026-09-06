"""Reusable maturity/rate boundary scoring primitives.

The functions in this module implement the canonical scoring rules documented in
``docs/SCORING.md``.  They are deliberately independent of a particular market
or GUI so commodity futures and Treasury/cash instruments can share the same
validated implementation.
"""

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class BoundaryAnchors:
    """Two points defining a linear boundary in maturity/rate space."""

    maturity_1: float
    rate_1: float
    maturity_2: float
    rate_2: float

    def __post_init__(self) -> None:
        if self.maturity_2 <= self.maturity_1:
            raise ValueError("second boundary maturity must exceed the first")

    @property
    def slope(self) -> float:
        return ((self.rate_2 - self.rate_1) /
                (self.maturity_2 - self.maturity_1))

    @property
    def intercept(self) -> float:
        return self.rate_1 - self.slope * self.maturity_1

    def value(self, maturity: float) -> float:
        return self.rate_1 + self.slope * (maturity - self.maturity_1)

    @classmethod
    def from_slope_intercept(
            cls, maturity_1: float, maturity_2: float,
            slope: float, intercept: float) -> "BoundaryAnchors":
        """Migrate an old slope/intercept line without changing its geometry."""
        return cls(
            maturity_1=maturity_1,
            rate_1=intercept + slope * maturity_1,
            maturity_2=maturity_2,
            rate_2=intercept + slope * maturity_2,
        )


@dataclass(frozen=True)
class RelativeAdjustment:
    """Dimensionless, bounded relative score adjustment."""

    strength: float = 1.0
    rate_scale: float = 0.01
    clip: float = 3.0

    def __post_init__(self) -> None:
        if self.rate_scale <= 0:
            raise ValueError("rate_scale must be positive")
        if self.clip < 0:
            raise ValueError("clip must be non-negative")

    def normalized(self, signed_distance: float) -> float:
        raw = signed_distance / self.rate_scale
        return max(-self.clip, min(self.clip, raw))

    def signed_adjustment(self, signed_distance: float) -> float:
        """Return the signed dimensionless contribution to a softmax logit."""
        return self.strength * self.normalized(signed_distance)

    def multiplier(self, signed_distance: float) -> float:
        """Compatibility view of the former relative multiplier."""
        return 1.0 + self.signed_adjustment(signed_distance)

    def score(self, base_score: float, signed_distance: float) -> float:
        """Return a signed, dimensionless softmax logit."""
        return base_score / self.rate_scale + self.signed_adjustment(
            signed_distance)


@dataclass(frozen=True)
class PureMaturityAdjustment:
    """Rate-independent preference for shorter longs or longer shorts."""

    strength: float = 0.0
    scale_days: float = 365.0
    clip: float = 3.0

    def __post_init__(self) -> None:
        if self.scale_days <= 0:
            raise ValueError("scale_days must be positive")
        if self.clip < 0:
            raise ValueError("clip must be non-negative")

    def normalized(self, maturity: float, direction: str) -> float:
        normalized = max(-self.clip, min(self.clip, maturity / self.scale_days))
        if direction == "long":
            return -normalized
        if direction == "short":
            return normalized
        raise ValueError("direction must be 'long' or 'short'")

    def signed_adjustment(self, maturity: float, direction: str) -> float:
        """Return the signed dimensionless pure-maturity logit contribution."""
        return self.strength * self.normalized(maturity, direction)

    def multiplier(self, maturity: float, direction: str) -> float:
        """Compatibility view used by diagnostics and older callers."""
        return 1.0 + self.signed_adjustment(maturity, direction)


def signed_distance(rate: float, maturity: float, boundary: BoundaryAnchors,
                    direction: str) -> float:
    """Return the canonical vertical distance for a long or short candidate."""
    line = boundary.value(maturity)
    if direction == "long":
        return rate - line
    if direction == "short":
        return -rate - line
    raise ValueError("direction must be 'long' or 'short'")


def adjusted_score(base_score: float, rate: float, maturity: float,
                   boundary: BoundaryAnchors, adjustment: RelativeAdjustment,
                   direction: str,
                   maturity_adjustment: PureMaturityAdjustment | None = None) -> float:
    logit = adjustment.score(
        base_score,
        signed_distance(rate, maturity, boundary, direction),
    )
    if maturity_adjustment is not None:
        logit += maturity_adjustment.signed_adjustment(maturity, direction)
    return logit


def allocate_scores(scores: Mapping[str, float], target: float) -> dict[str, float]:
    """Softmax signed logits into weights that exactly preserve the target."""
    if target <= 0 or not scores:
        return {}
    finite = {key: float(value) for key, value in scores.items()
              if math.isfinite(float(value))}
    if not finite:
        return {}
    maximum = max(finite.values())
    exponentials = {
        key: math.exp(max(-700.0, value - maximum))
        for key, value in finite.items()
    }
    total = sum(exponentials.values())
    weights = {
        key: target * value / total
        for key, value in exponentials.items()
    }
    # Put the unavoidable floating-point remainder on the largest allocation
    # so callers can rely on exact book-target preservation.
    largest = max(weights, key=weights.get)
    weights[largest] += target - sum(weights.values())
    return weights


def score_contracts(
        contracts: Iterable[Mapping[str, float | str]], *, direction: str,
        eligibility_threshold: float, boundary: BoundaryAnchors,
        adjustment: RelativeAdjustment, target: float,
        maturity_adjustment: PureMaturityAdjustment | None = None,
        rate_key: str = "lease", maturity_key: str = "days",
        symbol_key: str = "symbol") -> tuple[dict[str, float], list[dict]]:
    """Gate, score and allocate a contract universe with complete diagnostics.

    Long base score is the rate above the long eligibility threshold.  Short base
    score is the amount by which the rate is below the short threshold.  Maturity
    is passed in the caller's chosen unit; boundary anchors must use that unit.
    """
    diagnostics: list[dict] = []
    scores: dict[str, float] = {}
    for contract in contracts:
        symbol = str(contract[symbol_key])
        rate = float(contract[rate_key])
        maturity = float(contract[maturity_key])
        eligible = (rate >= eligibility_threshold if direction == "long"
                    else rate <= eligibility_threshold)
        base = (rate - eligibility_threshold if direction == "long"
                else eligibility_threshold - rate)
        distance = signed_distance(rate, maturity, boundary, direction)
        rate_adjustment = adjustment.signed_adjustment(distance)
        pure_adjustment = (
            maturity_adjustment.signed_adjustment(maturity, direction)
            if maturity_adjustment else 0.0)
        final = (max(0.0, base) / adjustment.rate_scale
                 + rate_adjustment + pure_adjustment
                 if eligible else None)
        if eligible:
            scores[symbol] = final
        diagnostics.append({
            "symbol": symbol,
            "maturity": maturity,
            "rate": rate,
            "eligible": eligible,
            "boundary_value": boundary.value(maturity),
            "signed_distance": distance,
            "base_score": max(0.0, base),
            "relative_adjustment": rate_adjustment,
            "pure_maturity_adjustment": pure_adjustment,
            "final_score": final,
            "target_weight": 0.0,
        })
    weights = allocate_scores(scores, target)
    for row in diagnostics:
        row["target_weight"] = weights.get(row["symbol"], 0.0)
    return weights, diagnostics
