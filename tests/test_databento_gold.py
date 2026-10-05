"""Economic direction, causal joins, costs and resumable purchase boundaries."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("databento_gold", ROOT / "scripts/databento_gold.py")
gold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gold)


class GoldPreviewTests(unittest.TestCase):
    def setUp(self):
        self.c = gold.config_at(gold.DEFAULT_CONFIG)
        self.times = pd.to_datetime(["2026-09-01T14:00:00Z", "2026-09-01T14:01:00Z"])
        self.expiry = pd.Timestamp("2026-11-25T18:30:00Z")
        def quotes(bid, ask, size):
            return pd.DataFrame({"ts_recv": self.times, "ts_event": pd.to_datetime(["2026-08-31T00:00:00Z"] * 2),
                                 "instrument_id": [1, 1], "bid_px_00": [bid] * 2,
                                 "ask_px_00": [ask] * 2, "bid_sz_00": [size] * 2, "ask_sz_00": [size] * 2})
        self.frames = {"future-bbo-1m": quotes(3999, 4001, 5), "iau-bbo-1m": quotes(80, 80.1, 100),
                       "future-definition": pd.DataFrame({"raw_symbol": ["1OZZ6"],
                           "expiration": [self.expiry], "maturity_year": [2026], "maturity_month": [12]})}
        self.refs = pd.DataFrame({"available_at": [pd.Timestamp(self.c["start"])],
                                  "ounces_per_share": [.02], "usd_rate": [.05], "source": ["test"]})
        self.provenance = {"mode": "dated_reference"}

    def run_analysis(self):
        return gold.analyze(self.frames, self.refs, self.provenance, self.c)

    def test_sides_and_actual_expiry_not_december_end(self):
        samples, summary = self.run_analysis()
        t = (self.expiry - self.times[0]).total_seconds() / (365 * 86400)
        self.assertAlmostEqual(samples.iloc[0].long_lease_gross_pct, 100 * (.05 - (4001 / 4000 - 1) / t))
        self.assertGreater(samples.iloc[0].reverse_lease_boundary_pct, samples.iloc[0].long_lease_gross_pct)
        self.assertEqual(summary["coverage"]["long_size_qualified_samples"], 2)
        self.assertEqual(summary["classification"], "sampled_quote_indication")

    def test_future_reference_never_used_early(self):
        self.refs.loc[1] = [self.times[1], .02, .01, "later"]
        samples, _ = self.run_analysis()
        self.assertEqual(list(samples.usd_rate), [.05, .01])

    def test_missing_interval_is_not_forward_filled(self):
        self.frames["iau-bbo-1m"] = self.frames["iau-bbo-1m"].iloc[:1]
        samples, _ = self.run_analysis()
        self.assertEqual(len(samples), 1)

    def test_last_trade_time_does_not_drive_bbo_alignment(self):
        samples, _ = self.run_analysis()
        self.assertEqual(list(samples.timestamp), list(self.times))

    def test_entry_fees_reduce_rate(self):
        self.c.update(future_fee_usd_per_contract=.5, iau_fee_usd_per_share=.001, iau_min_fee_usd=1)
        samples, _ = self.run_analysis()
        first = samples.iloc[0]
        self.assertEqual(first.entry_cost_usd_per_oz, 1.5)
        self.assertAlmostEqual(first.long_lease_gross_pct - first.long_lease_after_entry_cost_pct,
                               100 * 1.5 / 4000 / first.maturity_years)

    def test_etf_share_rounding_and_depth(self):
        self.refs["ounces_per_share"] = .019
        self.frames["iau-bbo-1m"].loc[0, "bid_sz_00"] = 52
        samples, _ = self.run_analysis()
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples.iloc[0].iau_shares_needed, 53)
        self.assertAlmostEqual(samples.iloc[0].iau_rounding_residual_oz, .007)

    def test_bad_or_crossed_quotes_are_excluded(self):
        for value in (float("nan"), float("inf"), 0, 80.2):
            with self.subTest(value=value):
                self.frames["iau-bbo-1m"].loc[0, "bid_px_00"] = value
                samples, _ = self.run_analysis()
                self.assertEqual(len(samples), 1)

    def test_stale_reference_fails(self):
        self.refs["available_at"] = pd.to_datetime(["2026-08-01T00:00:00Z"])
        with self.assertRaisesRegex(ValueError, "No size-qualified"):
            self.run_analysis()

    def test_wrong_expiry_month_is_rejected(self):
        self.frames["future-definition"]["maturity_month"] = 10
        with self.assertRaisesRegex(ValueError, "December 2026"):
            self.run_analysis()

    def test_conflicting_duplicate_samples_fail(self):
        q = self.frames["iau-bbo-1m"]
        other = q.iloc[:1].copy()
        other["bid_px_00"] = 79
        self.frames["iau-bbo-1m"] = pd.concat([q, other])
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.run_analysis()

    def test_budget_counts_previous_requests_and_rejects_nonfinite(self):
        plan = {"new_estimated_usd": 4, "previous_reserved_estimated_usd": 3}
        gold.check_budget(plan, 7)
        for cap in (None, float("nan"), 6):
            with self.assertRaises(ValueError):
                gold.check_budget(plan, cap)

    def test_ambiguous_submission_is_persisted_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            state = gold.state_at(output, self.c)
            row = {**gold.requests_for(self.c, "mbo")[0], "estimated_usd": 1}
            client = Mock()
            client.batch.submit_job.side_effect = RuntimeError("response lost")
            with self.assertRaises(RuntimeError):
                gold.submit_mbo(client, {"requests": [row]}, output, state)
            saved = json.loads((output / "state.json").read_text())
            self.assertEqual(saved["reserved_estimated_usd"], 1)
            with self.assertRaisesRegex(ValueError, "uncertain outcome"):
                gold.submit_mbo(client, {"requests": [row]}, output, saved)
            self.assertEqual(client.batch.submit_job.call_count, 1)

    def test_resume_does_not_submit_new_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            state = gold.state_at(output, self.c)
            row = {**gold.requests_for(self.c, "mbo")[0], "estimated_usd": 1}
            client = Mock()
            client.batch.submit_job.return_value = {"id": "job1"}
            gold.submit_mbo(client, {"requests": [row]}, output, state)
            gold.submit_mbo(client, {"requests": [row]}, output, state)
            self.assertEqual(client.batch.submit_job.call_count, 1)
            self.assertEqual(state["reserved_estimated_usd"], 1)

    def test_batch_checksum_prefix_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            target = output / "batch/job1/metadata.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}")
            state = gold.state_at(output, self.c)
            state["batches"]["future-mbo"] = {"status": "submitted", "job_id": "job1"}
            client = Mock()
            client.batch.list_jobs.return_value = [{"id": "job1", "state": "done"}]
            client.batch.list_files.return_value = [{"filename": "metadata.json", "size": 2,
                                                      "hash": "sha256:" + gold.digest(target)}]
            self.assertFalse(gold.download_mbo(client, output, state))
            self.assertFalse(gold.download_mbo(client, output, state))
            self.assertEqual(client.batch.download.call_count, 1)
            target.write_text("corrupted")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                gold.download_mbo(client, output, state)

    def test_pending_batch_never_submits_another_job(self):
        with tempfile.TemporaryDirectory() as folder:
            state = gold.state_at(Path(folder), self.c)
            state["batches"]["future-mbo"] = {"status": "submitted", "job_id": "job1"}
            client = Mock()
            client.batch.list_jobs.return_value = [{"id": "job1", "state": "processing"}]
            self.assertTrue(gold.download_mbo(client, Path(folder), state))
            client.batch.submit_job.assert_not_called()
            client.batch.download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
