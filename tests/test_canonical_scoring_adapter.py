from pathlib import Path
from types import SimpleNamespace
import sys


PUBLIC = Path(__file__).resolve().parents[1] / "public"
if str(PUBLIC) not in sys.path:
    sys.path.insert(0, str(PUBLIC))

import canonical_scoring_adapter as adapter


class FakeStrategy:
    def maturity_line_adjusted_score(self, base_score, contract, parameters,
                                     direction):
        raise AssertionError("legacy scoring helper remained active")

    def positions_for_day(self, candidates, parameters, previous=None):
        return {
            row["symbol"]: self.maturity_line_adjusted_score(
                1.0, row, parameters, previous)
            for row in candidates
        }


class FakeGui:
    @staticmethod
    def parameters(payload):
        return SimpleNamespace(
            min_days=10,
            long_maturity_line_intercept=0.01,
            long_maturity_line_slope_per_year=0.0,
            short_maturity_line_intercept=0.01,
            short_maturity_line_slope_per_year=0.0,
        )


def candidates(rate):
    return [
        {"symbol": "near", "days": 30, "lease": rate},
        {"symbol": "far", "days": 365, "lease": rate},
    ]


def payload():
    return {
        "long_relative_strength": 0,
        "short_relative_strength": 0,
        "long_pure_maturity_strength": 0.5,
        "short_pure_maturity_strength": 0.5,
    }


def test_adapter_routes_long_scoring_to_shorter_maturity_preference():
    strategy, gui = adapter.install(FakeStrategy(), FakeGui())
    scores = strategy.positions_for_day(candidates(0.02), gui.parameters(payload()),
                                        "long")
    assert scores["near"] > scores["far"]


def test_adapter_routes_short_scoring_to_longer_maturity_preference():
    strategy, gui = adapter.install(FakeStrategy(), FakeGui())
    scores = strategy.positions_for_day(candidates(-0.02), gui.parameters(payload()),
                                        "short")
    assert scores["far"] > scores["near"]


def test_zero_strength_preserves_equal_scores_for_equal_rates():
    strategy, gui = adapter.install(FakeStrategy(), FakeGui())
    settings = payload()
    settings["long_pure_maturity_strength"] = 0
    scores = strategy.positions_for_day(candidates(0.02), gui.parameters(settings),
                                        "long")
    assert scores["near"] == scores["far"]


def test_invalid_strength_is_rejected_during_parameter_parsing():
    _, gui = adapter.install(FakeStrategy(), FakeGui())
    settings = payload()
    settings["short_pure_maturity_strength"] = -0.1
    try:
        gui.parameters(settings)
    except ValueError as error:
        assert "non-negative" in str(error)
    else:
        raise AssertionError("negative pure-maturity strength was accepted")
