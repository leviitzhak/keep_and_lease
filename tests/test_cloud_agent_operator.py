import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "cloud-agent-operator.py"
SPEC = importlib.util.spec_from_file_location("cloud_agent_operator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class RequestValidationTests(unittest.TestCase):
    def load(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return MODULE.load_request(path)

    def test_health_gui_logs_request(self):
        request = self.load(
            {
                "schema_version": 1,
                "request_id": "health-gui",
                "actions": ["health", "gui"],
            }
        )
        self.assertEqual(request["request_id"], "health-gui")

    def test_backtest_requires_explicit_billable_confirmation(self):
        with self.assertRaises(MODULE.OperatorError):
            self.load(
                {
                    "schema_version": 1,
                    "request_id": "backtest",
                    "actions": ["backtest"],
                    "backtest": {"fixture": "silver-default"},
                }
            )

    def test_rejects_unknown_action(self):
        with self.assertRaises(MODULE.OperatorError):
            self.load(
                {
                    "schema_version": 1,
                    "request_id": "unsafe",
                    "actions": ["shell"],
                }
            )

    def test_rejects_arbitrary_backtest_parameters(self):
        with self.assertRaises(MODULE.OperatorError):
            self.load(
                {
                    "schema_version": 1,
                    "request_id": "private-parameters",
                    "actions": ["backtest"],
                    "backtest": {
                        "confirm_billable": True,
                        "fixture": "silver-default",
                        "parameters": {"secret": 1},
                    },
                }
            )

    def test_sanitized_job_omits_parameters_logs_and_internal_uri(self):
        sanitized = MODULE.sanitized_job(
            {
                "job_id": "job-1",
                "status": "completed",
                "parameters": {"private": 1},
                "logs": [{"detail": "private"}],
                "result_uri": "gs://private/result",
                "error": "private error",
            }
        )
        self.assertEqual(sanitized["job_id"], "job-1")
        self.assertTrue(sanitized["error_present"])
        self.assertNotIn("parameters", sanitized)
        self.assertNotIn("logs", sanitized)
        self.assertNotIn("result_uri", sanitized)

    def test_same_origin_rejects_external_server_url(self):
        with self.assertRaises(MODULE.OperatorError):
            MODULE.same_origin_url("https://service.run.app", "https://example.com/result")


if __name__ == "__main__":
    unittest.main()
