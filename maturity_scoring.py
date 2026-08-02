"""Reusable maturity/rate boundary scoring primitives.

The functions in this module implement the canonical scoring rules documented in
``docs/SCORING.md``.  They are deliberately independent of a particular market
or GUI so commodity futures and Treasury/cash instruments can share the same
validated implementation.
"""

from dataclasses import dataclass
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

    def multiplier(self, signed_distance: float) -> float:
        return max(0.0, 1.0 + self.strength * self.normalized(signed_distance))

    def score(self, base_score: float, signed_distance: float) -> float:
        if base_score <= 0:
            return 0.0
        return base_score * self.multiplier(signed_distance)


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
                   direction: str) -> float:
    return adjustment.score(
        base_score,
        signed_distance(rate, maturity, boundary, direction),
    )


def allocate_scores(scores: Mapping[str, float], target: float) -> dict[str, float]:
    """Convert positive scores to weights that exactly preserve the target."""
    if target <= 0:
        return {}
    positive = {key: value for key, value in scores.items() if value > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    weights = {key: target * value / total for key, value in positive.items()}
    # Put the unavoidable floating-point remainder on the final instrument so
    # callers can rely on exact book-target preservation.
    last = next(reversed(weights))
    weights[last] += target - sum(weights.values())
    return weights


def score_contracts(
        contracts: Iterable[Mapping[str, float | str]], *, direction: str,
        eligibility_threshold: float, boundary: BoundaryAnchors,
        adjustment: RelativeAdjustment, target: float,
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
        multiplier = adjustment.multiplier(distance)
        final = adjustment.score(base, distance) if eligible else 0.0
        if final > 0:
            scores[symbol] = final
        diagnostics.append({
            "symbol": symbol,
            "maturity": maturity,
            "rate": rate,
            "eligible": eligible,
            "boundary_value": boundary.value(maturity),
            "signed_distance": distance,
            "base_score": max(0.0, base),
            "relative_multiplier": multiplier,
            "final_score": final,
            "target_weight": 0.0,
        })
    weights = allocate_scores(scores, target)
    for row in diagnostics:
        row["target_weight"] = weights.get(row["symbol"], 0.0)
    return weights, diagnostics
