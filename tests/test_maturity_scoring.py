from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public"))

from maturity_scoring import (  # noqa: E402
    BoundaryAnchors,
    PureMaturityPreference,
    RelativeAdjustment,
    score_contracts,
)


def _score(direction, strength):
    contracts = [
        {"symbol": "NEAR", "days": 30, "lease": 0.05 if direction == "long" else -0.05},
        {"symbol": "MID", "days": 180, "lease": 0.05 if direction == "long" else -0.05},
        {"symbol": "FAR", "days": 365, "lease": 0.05 if direction == "long" else -0.05},
    ]
    return score_contracts(
        contracts,
        direction=direction,
        eligibility_threshold=0.0,
        boundary=BoundaryAnchors(30, 0.05, 365, 0.05),
        adjustment=RelativeAdjustment(strength=0.0),
        maturity_preference=PureMaturityPreference(strength=strength),
        target=1.0,
    )


def test_zero_strength_preserves_equal_weights():
    weights, diagnostics = _score("long", 0.0)
    assert weights == {"NEAR": 1 / 3, "MID": 1 / 3, "FAR": 1 / 3}
    assert all(row["pure_maturity_multiplier"] == 1.0 for row in diagnostics)


def test_long_preference_favors_shorter_maturities():
    weights, diagnostics = _score("long", 0.5)
    assert weights["NEAR"] > weights["MID"] > weights["FAR"]
    rows = {row["symbol"]: row for row in diagnostics}
    assert rows["NEAR"]["pure_maturity_multiplier"] > 1.0
    assert rows["FAR"]["pure_maturity_multiplier"] < 1.0


def test_short_preference_favors_longer_maturities():
    weights, diagnostics = _score("short", 0.5)
    assert weights["FAR"] > weights["MID"] > weights["NEAR"]
    rows = {row["symbol"]: row for row in diagnostics}
    assert rows["FAR"]["pure_maturity_multiplier"] > 1.0
    assert rows["NEAR"]["pure_maturity_multiplier"] < 1.0


def test_single_eligible_maturity_is_neutral():
    weights, diagnostics = score_contracts(
        [{"symbol": "ONLY", "days": 90, "lease": 0.05}],
        direction="long",
        eligibility_threshold=0.0,
        boundary=BoundaryAnchors(30, 0.0, 365, 0.0),
        adjustment=RelativeAdjustment(strength=0.0),
        maturity_preference=PureMaturityPreference(strength=2.0),
        target=0.4,
    )
    assert weights == {"ONLY": 0.4}
    assert diagnostics[0]["pure_maturity_coordinate"] == 0.0
    assert diagnostics[0]["pure_maturity_multiplier"] == 1.0


def test_ineligible_contract_does_not_set_maturity_range():
    weights, diagnostics = score_contracts(
        [
            {"symbol": "NEAR", "days": 30, "lease": 0.05},
            {"symbol": "FAR_INELIGIBLE", "days": 1000, "lease": -0.01},
        ],
        direction="long",
        eligibility_threshold=0.0,
        boundary=BoundaryAnchors(30, 0.0, 365, 0.0),
        adjustment=RelativeAdjustment(strength=0.0),
        maturity_preference=PureMaturityPreference(strength=1.0),
        target=1.0,
    )
    assert weights == {"NEAR": 1.0}
    rows = {row["symbol"]: row for row in diagnostics}
    assert rows["NEAR"]["pure_maturity_multiplier"] == 1.0
    assert rows["FAR_INELIGIBLE"]["final_score"] == 0.0


def test_negative_strength_is_rejected():
    try:
        PureMaturityPreference(strength=-0.1)
    except ValueError as error:
        assert "non-negative" in str(error)
    else:
        raise AssertionError("negative maturity preference strength should fail")
