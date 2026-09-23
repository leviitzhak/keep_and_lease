import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server_main import DeferredApplication


class DeferredApplicationTests(unittest.TestCase):
    def test_health_does_not_load_the_calculation_application(self):
        catalog = json.dumps({"manifest_sha256": "a" * 64})
        with patch.dict(
            os.environ,
            {
                "KEEP_AND_LEASE_JOB_BACKEND": "cloud",
                "KEEP_AND_LEASE_TRADE_CATALOG": catalog,
                "KEEP_AND_LEASE_ENGINE_COMMIT": "commit",
            },
            clear=False,
        ):
            application = DeferredApplication()
            response = TestClient(application).get("/api/v1/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["execution_backend"], "cloud-run-job")
        self.assertEqual(response.json()["engine_commit"], "commit")
        self.assertIsNone(application._application)


if __name__ == "__main__":
    unittest.main()
