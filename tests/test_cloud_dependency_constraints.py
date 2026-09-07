from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_google_api_core_stays_below_firestore_routing_regression():
    requirements = (ROOT / "requirements-cloud.txt").read_text(encoding="utf-8")
    assert "google-api-core[grpc]==2.34.0" in requirements
