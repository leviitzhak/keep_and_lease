"""Economic direction, causal joins, costs and resumable purchase boundaries."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
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

    def other_market(self, preset):
        self.c = gold.config_at(gold.PRESETS[preset])
        m = gold.market(self.c)
        self.c.update(contracts=2, future_fee_usd_per_contract=1,
                      holding_fee_usd_per_share=.001, holding_min_fee_usd=1)
        if preset == "sic":
            units_per_share, future_ask, holding_bid = .9, 61, 54
        else:
            units_per_share, future_ask, holding_bid = .0005, 101000, 50
            self.expiry = pd.Timestamp("2026-10-30T16:00:00Z")
        self.frames["future-definition"] = pd.DataFrame({"raw_symbol": [self.c["future_symbol"]],
            "expiration": [self.expiry], "maturity_year": [2026], "maturity_month": [m["month"]]})
        self.frames["future-bbo-1m"]["ask_px_00"] = future_ask
        self.frames["future-bbo-1m"]["bid_px_00"] = future_ask - 1
        holding = self.frames.pop("iau-bbo-1m")
        holding["bid_px_00"], holding["ask_px_00"] = holding_bid, holding_bid + .01
        holding["bid_sz_00"], holding["ask_sz_00"] = 10000, 10000
        self.frames[f"{m['holding'].lower()}-bbo-1m"] = holding
        self.refs = self.refs.rename(columns={"ounces_per_share": "units_per_share"})
        self.refs["units_per_share"] = units_per_share

    def test_sic_size_and_fee_scaling(self):
        self.other_market("sic")
        self.frames["slv-bbo-1m"].loc[0, "bid_sz_00"] = 222
        samples, summary = self.run_analysis()
        self.assertEqual(len(samples), 1)
        row = samples.iloc[0]
        self.assertEqual(row.holding_shares_needed, 223)
        self.assertEqual(row.underlying_quantity, 200)
        self.assertAlmostEqual(row.holding_rounding_residual_units, .7)
        self.assertAlmostEqual(row.entry_cost_usd_per_unit, 3 / 200)
        self.assertAlmostEqual(row.long_lease_gross_pct, 100 * (.05 - (61 / 60 - 1) / row.maturity_years))
        self.assertEqual(summary["market"]["units_per_contract"], 100)

    def test_mbt_fractional_size_and_october_maturity(self):
        self.other_market("mbt")
        # Sufficient IBIT shares alone must not pass insufficient futures depth.
        self.frames["future-bbo-1m"].loc[0, "ask_sz_00"] = 1
        samples, summary = self.run_analysis()
        self.assertEqual(len(samples), 1)
        row = samples.iloc[0]
        self.assertEqual(row.holding_shares_needed, 400)
        self.assertAlmostEqual(row.underlying_quantity, .2)
        self.assertAlmostEqual(row.entry_cost_usd_per_unit, 15)
        self.assertAlmostEqual(row.long_lease_gross_pct, 100 * (.05 - .01 / row.maturity_years))
        self.assertAlmostEqual(row.long_gain_to_expiry_after_entry_cost_bps,
                               (.05 * row.maturity_years - .01 - 15 / 100000) * 10000)
        self.assertEqual(summary["expiry"], self.expiry.isoformat())

    def test_presets_keep_gold_cache_compatible_and_isolate_other_contracts(self):
        original = json.loads(gold.DEFAULT_CONFIG.read_text())
        self.assertEqual(self.c, original)
        self.assertEqual(gold.default_output(self.c).name, "databento-1oz-sep2026")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            state = gold.state_at(output, original)
            gold.save_json(output / "state.json", state)
            self.assertEqual(gold.state_at(output, self.c), state)
            with self.assertRaisesRegex(ValueError, "different configuration"):
                gold.state_at(output, gold.config_at(gold.PRESETS["sic"]))
        for preset, symbol, holding in (("gold", "1OZZ6", "IAU"), ("sic", "SICZ6", "SLV"), ("mbt", "MBTV6", "IBIT")):
            c = gold.config_at(gold.PRESETS[preset])
            for stage in ("preview", "mbo"):
                items = gold.requests_for(c, stage)
                self.assertEqual(items[0]["request"]["symbols"], [symbol])
                self.assertEqual(items[1]["request"]["symbols"], [holding])
                self.assertEqual(items[1]["name"].split("-")[0], holding.lower())

    def test_bitcoin_reference_rejects_ounce_units_and_gold_only_flag(self):
        c = gold.config_at(gold.PRESETS["mbt"])
        args = SimpleNamespace(reference_csv=None, units_per_share=.0005, iau_oz_per_share=None, cash_rate_pct=4)
        refs, provenance = gold.reference_data(args, c)
        self.assertEqual(refs.iloc[0].units_per_share, .0005)
        self.assertEqual(provenance["underlying_unit"], "BTC")
        args.iau_oz_per_share = .02
        with self.assertRaisesRegex(ValueError, "only for gold"):
            gold.reference_data(args, c)
        with tempfile.TemporaryDirectory() as folder:
            args.reference_csv = Path(folder) / "refs.csv"
            self.refs.to_csv(args.reference_csv, index=False)
            with self.assertRaisesRegex(ValueError, "BTC per IBIT"):
                gold.reference_data(args, c)

    def test_comparison_uses_shared_timestamps_and_reports_different_cash_assumptions(self):
        samples, summary = self.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            outputs = [Path(folder) / name for name in ("gold", "sic")]
            gold.save_json(outputs[0] / "lease-summary.json", summary)
            samples.to_csv(outputs[0] / "lease-samples.csv.gz", index=False)
            self.other_market("sic")
            self.refs["usd_rate"] = .04
            silver, summary = self.run_analysis()
            gold.save_json(outputs[1] / "lease-summary.json", summary)
            silver.iloc[:1].to_csv(outputs[1] / "lease-samples.csv.gz", index=False)
            report = gold.compare_outputs(outputs)
            self.assertEqual(report["common_samples"], 1)
            self.assertFalse(report["same_cash_rate_on_common_samples"])
            row = report["contracts"][0]
            self.assertEqual(row["all_qualified_samples"]["samples"], 2)
            self.assertEqual(row["common_timestamps"]["samples"], 1)
            self.assertAlmostEqual(row["common_timestamps"]["long_lease_after_entry_cost_pct"]["median"],
                                   samples.iloc[0].long_lease_after_entry_cost_pct)
            summary["config"]["end"] = "2026-09-30T00:00:00Z"
            gold.save_json(outputs[1] / "lease-summary.json", summary)
            with self.assertRaisesRegex(ValueError, "same date window"):
                gold.compare_outputs(outputs)


if __name__ == "__main__":
    unittest.main()
