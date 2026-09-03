from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKLOADS = ROOT / "infra" / "gcp" / "workloads"
EXPECTED_MAX_RESULT_BYTES = 256 * 1024 * 1024


def test_gcp_result_limit_is_permanent_and_consistent():
    variables = (WORKLOADS / "variables.tf").read_text(encoding="utf-8")
    main = (WORKLOADS / "main.tf").read_text(encoding="utf-8")
    documentation = (ROOT / "docs" / "GOOGLE_CLOUD_RUN_SETUP.md").read_text(
        encoding="utf-8"
    )

    assert 'variable "max_result_bytes"' in variables
    assert f"default     = {EXPECTED_MAX_RESULT_BYTES}" in variables
    assert main.count('name  = "KEEP_AND_LEASE_MAX_RESULT_BYTES"') == 2
    assert main.count("value = tostring(var.max_result_bytes)") == 2
    assert f"{EXPECTED_MAX_RESULT_BYTES:,} bytes" in documentation
