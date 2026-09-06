import time
import unittest

from fastapi.testclient import TestClient

from server.app import create_app


class FakeEngine:
    loaded = True

    def capabilities(self):
        return {"schema_version": 1, "loaded": True, "products": {}}

    def run_backtest(self, parameters, progress=None):
        if progress:
            progress("running", "fake calculation")
        if parameters.get("fail"):
            raise ValueError("requested failure")
        return {"fields": ["date"], "series": [["2000-01-03"]], "parameters": parameters}

    def inspect_day(self, parameters, requested_date):
        return {"requested_date": requested_date, "parameters": parameters}


class ServerApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(FakeEngine()))

    def wait_for(self, job_id):
        for _ in range(100):
            state = self.client.get(f"/api/v1/backtests/{job_id}").json()
            if state["status"] in {"completed", "failed", "cancelled"}:
                return state
            time.sleep(0.01)
        self.fail("job did not finish")

    def test_backtest_returns_the_engine_payload_unchanged(self):
        created = self.client.post("/api/v1/backtests", json={
            "schema_version": 1, "parameters": {"weight_silver": 100}
        })
        self.assertEqual(created.status_code, 202)
        state = self.wait_for(created.json()["job_id"])
        self.assertEqual(state["status"], "completed")
        result = self.client.get(created.json()["result_url"])
        self.assertEqual(result.json()["parameters"], {"weight_silver": 100})
        latest = self.client.get("/api/v1/backtests/latest")
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["job_id"], created.json()["job_id"])
        restored = self.client.get(latest.json()["result_url"])
        self.assertEqual(restored.json(), result.json())

    def test_latest_result_is_empty_before_a_completed_run(self):
        client = TestClient(create_app(FakeEngine()))
        self.assertEqual(client.get("/api/v1/backtests/latest").status_code, 204)

    def test_latest_result_and_job_access_are_scoped_to_iap_identity(self):
        owner = {"x-goog-authenticated-user-id": "accounts.google.com:user-1"}
        other = {"x-goog-authenticated-user-id": "accounts.google.com:user-2"}
        created = self.client.post(
            "/api/v1/backtests",
            headers=owner,
            json={"schema_version": 1, "parameters": {"weight_gold": 100}},
        ).json()
        for _ in range(100):
            state = self.client.get(created["status_url"], headers=owner).json()
            if state["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(
            self.client.get("/api/v1/backtests/latest", headers=owner).json()["job_id"],
            created["job_id"],
        )
        self.assertEqual(
            self.client.get("/api/v1/backtests/latest", headers=other).status_code,
            204,
        )
        self.assertEqual(
            self.client.get(created["result_url"], headers=other).status_code,
            404,
        )

    def test_identical_completed_request_reuses_cached_job(self):
        request = {"schema_version": 1, "parameters": {"min_days": 30}}
        first = self.client.post("/api/v1/backtests", json=request).json()
        self.wait_for(first["job_id"])
        second = self.client.post("/api/v1/backtests", json=request)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["cached"])
        self.assertEqual(second.json()["job_id"], first["job_id"])

    def test_inspection_uses_the_same_parameter_document(self):
        response = self.client.post("/api/v1/inspections", json={
            "schema_version": 1, "date": "2001-02-03", "parameters": {"weight_gold": 20}
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["parameters"], {"weight_gold": 20})

    def test_unsupported_schema_is_rejected(self):
        response = self.client.post("/api/v1/backtests", json={
            "schema_version": 2, "parameters": {}
        })
        self.assertEqual(response.status_code, 400)

    def test_engine_failure_is_reported_by_job_status_and_result(self):
        created = self.client.post("/api/v1/backtests", json={
            "schema_version": 1, "parameters": {"fail": True}
        }).json()
        state = self.wait_for(created["job_id"])
        self.assertEqual(state["status"], "failed")
        self.assertIn("requested failure", state["error"])
        self.assertEqual(self.client.get(created["result_url"]).status_code, 422)


if __name__ == "__main__":
    unittest.main()
