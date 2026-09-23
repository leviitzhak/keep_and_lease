import json
import unittest
from unittest.mock import patch

from paired_execution_study import (
    DAY_US, FrozenExecutionModel, StudyConfig, _Group, runnerstudy, select_execution_candidates,
)
from trade_replay import Trade


class Store:
    manifest_bytes = b"fixture"
    policy = "sequence"

    def __init__(self, events):
        self.events = sorted(events, key=lambda t:(t.us,t.symbol,t.identifier))

    def trades(self, start_us=None, end_us=None):
        return (x for x in self.events if start_us <= x.us < end_us)


def t(us, symbol="SPOT", price=100, btc=1, side=None, **kwargs):
    return Trade(us,symbol,price,btc,side or ("sell" if symbol == "SPOT" else "buy"),
                 f"{symbol}:{us}",**kwargs)


def seeds():
    return [t(-1_000_000),t(-1_000_000,"F")]


class StudyTests(unittest.TestCase):
    def run_study(self, events, **kwargs):
        defaults = dict(quantity_grid_btc=(.01,),waiting_seconds=(.5,1,2),max_quote_age_seconds=10)
        defaults.update(kwargs)
        return runnerstudy(Store(seeds()+events),0,3_000_000,{"F":30*DAY_US},StudyConfig(**defaults))

    def contract(self, report, wait):
        return next(g for g in report["model"]["groups"] if g["scope"]=="contract" and g["wait_seconds"]==wait)

    def test_source_must_finish_before_any_hedge_and_print_capacity_is_respected(self):
        report = self.run_study([t(100_000,btc=.02),t(150_000,"F",btc=1),
                                t(200_000,btc=.02),t(300_000,"F",btc=.02),
                                t(600_000,"F",btc=.02)], participation=.25)
        early = self.contract(report,.5)["outcomes"][0]
        self.assertEqual(early["source_fill_fraction"],1)
        self.assertAlmostEqual(early["target_fill_fraction"],.5)
        self.assertFalse(early["completed"])
        self.assertTrue(self.contract(report,1)["outcomes"][0]["completed"])

    def test_all_three_delays_and_strict_order_arrival(self):
        report = self.run_study([t(200_000,price=80),t(200_001,price=99),
                                t(400_001,"F",price=150),t(400_002,"F",price=101)],
                               observation_delay_seconds=.1,decision_delay_seconds=.1,order_delay_seconds=.1)
        outcome = self.contract(report,.5)["outcomes"][0]
        self.assertTrue(outcome["completed"])
        self.assertEqual(outcome["source_vwap"],99)
        self.assertEqual(outcome["target_vwap"],101)
        self.assertAlmostEqual(outcome["max_adverse_budget_bps"],100)
        expected_basis = 10000*(101/99-1)
        self.assertAlmostEqual(outcome["raw_basis_slip_bps"],expected_basis)
        self.assertAlmostEqual(outcome["annualized_slip_bps"],expected_basis/(30/365))

    def test_unavailable_future_observation_cannot_authorize_cohort(self):
        rows = [t(-200_000),t(-50_000,"F"),t(300_000),t(600_000,"F")]
        report = runnerstudy(Store(rows),0,3_000_000,{"F":30*DAY_US},
            StudyConfig(quantity_grid_btc=(.01,),waiting_seconds=(1,),observation_delay_seconds=.1))
        self.assertEqual(report["summary"]["cohorts_started"],0)
        self.assertEqual(report["model"]["groups"],[])

    def test_resting_partials_continue_but_full_source_ack_precedes_hedge(self):
        report = self.run_study([t(100_000,btc=.005),t(150_000,btc=.01),t(200_000,btc=.01),
                                t(200_001,btc=.005),t(300_001,"F",btc=.01),
                                t(300_002,"F",btc=.005),t(350_000,"F",btc=.01),
                                t(400_003,"F",btc=.005)],response_delay_seconds=.1)
        outcome = self.contract(report,.5)["outcomes"][0]
        self.assertTrue(outcome["completed"])
        self.assertAlmostEqual(outcome["source_fill_delay_seconds"],.125)
        self.assertAlmostEqual(outcome["target_fill_delay_seconds"],.300001)

    def test_cutoff_excludes_full_wait_plus_ack_window(self):
        rows=[]
        report=runnerstudy(Store(seeds()+[t(10_000),t(20_000,"F")]),0,2_000_000,{"F":30*DAY_US},
            StudyConfig(quantity_grid_btc=(.01,),waiting_seconds=(1,2),response_delay_seconds=.1),sink=rows.append)
        self.assertEqual(report["summary"]["cohorts_started"],0)
        self.assertEqual(report["summary"]["cohorts_excluded_at_cutoff"],1)
        self.assertEqual(rows[0]["reason"],"label_window_crosses_cutoff")

    def test_gtd_excludes_deadline_prints_but_later_horizon_includes_them(self):
        events=[t(100_000),t(500_000,"F",btc=.004),
                Trade(500_000,"F",100,.006,"buy","second",True),t(500_001,"F")]
        result=self.run_study(events)
        outcome=self.contract(result,.5)["outcomes"][0]
        self.assertFalse(outcome["completed"])
        self.assertEqual(outcome["target_fill_fraction"],0)
        self.assertTrue(self.contract(result,1)["outcomes"][0]["completed"])
        # Existing resting orders may consume distinct same-timestamp prints;
        # strict-later applies to order arrival, not each partial fill.

    def test_joint_confidence_counts_nonfills_and_preserves_partial_cash(self):
        report=self.run_study([t(100_000,btc=.005)])
        model=FrozenExecutionModel.from_dict(report["model"])
        forecast=model.forecast("F",30*DAY_US,3_000_000,.01,1,.95,1)
        self.assertFalse(forecast["available"])
        self.assertIsNone(forecast["budget_bps"])
        self.assertEqual(forecast["reason"],"joint_confidence_unattainable")
        actual=self.contract(report,1)["outcomes"][0]
        self.assertEqual(actual["status"],"source_only")
        self.assertEqual(actual["source_fill_fraction"],.5)
        self.assertEqual(actual["target_fill_fraction"],0)
        self.assertTrue(actual["censored"])
        json.dumps(report,allow_nan=False)

    def test_frozen_model_refuses_future_labels_and_falls_back_explicitly(self):
        report=self.run_study([t(100_000),t(200_000,"F")])
        model=FrozenExecutionModel.from_dict(report["model"])
        early=model.forecast("F",30*DAY_US,2_999_999,.01,1,.95,1)
        self.assertEqual(early["reason"],"calibration_labels_not_yet_available")
        late=model.forecast("G",30*DAY_US,3_000_000,.01,1,.95,1)
        self.assertTrue(late["available"])
        self.assertEqual(late["scope"],"maturity_bucket")
        self.assertEqual(late["samples"],1)
        self.assertEqual(late["all_outcome_probability"],1)
        self.assertEqual(late["budget_bps"],0)
        self.assertAlmostEqual(sum(x["weight"] for x in late["outcomes"]),1)
        candidates=select_execution_candidates(model,symbol="F",expiry_us=30*DAY_US,now_us=3_000_000,
                                               max_quantity_btc=.005,wait_seconds=1,min_samples=1)
        self.assertEqual(candidates,[])

    def test_deterministic_bounded_scenario_samples_keep_all_stratum_counts(self):
        report=self.run_study([t(100_000),t(200_000,"F",price=100.123)])
        row=self.contract(report,1)["outcomes"][0]
        first=_Group({"scope":"contract"},2)
        second=_Group({"scope":"contract"},2)
        for i in range(100):
            sample={**row,"decision_us":i,"completed":i<90,"status":"completed" if i<90 else "source_only"}
            first.add(sample);second.add(sample)
        saved=first.export()
        self.assertEqual(saved,second.export())
        self.assertEqual(saved["samples"],100)
        self.assertEqual(saved["completion_probability"],.9)
        self.assertLessEqual(len(saved["outcomes"]),4)
        self.assertIsNone(saved["joint_budget_quantiles_bps"]["p95"])
        self.assertEqual(saved["joint_budget_quantiles_bps"]["p90"],15)
        self.assertAlmostEqual(sum(x["weight"] for x in saved["outcomes"]),1)
        self.assertAlmostEqual(sum(x["weight"] for x in saved["outcomes"] if x["completed"]),.9)

    def test_negative_and_nonfinite_configuration_rejected(self):
        for config in ({"observation_delay_seconds":-1},{"quantity_grid_btc":(float("nan"),)},
                       {"waiting_seconds":(1,.5)},{"participation":0},{"samples_per_stratum":33}):
            with self.assertRaises(ValueError):StudyConfig(**config)

    def test_cohort_anchors_include_all_current_timestamp_observations(self):
        rows=[t(0,"F",price=90),t(0,price=100),t(100_000,price=100),t(200_000,"F",price=90)]
        result=runnerstudy(Store(rows),0,3_000_000,{"F":30*DAY_US},
                          StudyConfig(quantity_grid_btc=(.01,),waiting_seconds=(1,)))
        outcome=self.contract(result,1)["outcomes"][0]
        self.assertEqual(outcome["source_vwap_ratio"],1)
        self.assertEqual(outcome["target_vwap_ratio"],1)
        self.assertTrue(outcome["completed"])

    def test_excessive_grid_rejected_before_reading_tape(self):
        config=StudyConfig(quantity_grid_btc=(.001,.01),waiting_seconds=(3600,),cohort_interval_seconds=1)
        with self.assertRaisesRegex(ValueError,"concurrent"):
            runnerstudy(Store([]),0,DAY_US,{str(i):30*DAY_US for i in range(3)},config)

    def test_compact_checkpoint_round_trip_checksum_and_decompression_bound(self):
        model=FrozenExecutionModel.from_dict(self.run_study([t(100_000),t(200_000,"F")])["model"])
        checkpoint=model.snapshot()
        self.assertEqual(json.loads(json.dumps(model.to_dict())),FrozenExecutionModel.from_dict(checkpoint).to_dict())
        self.assertEqual(checkpoint,model.snapshot())
        self.assertLess(len(json.dumps(checkpoint)),len(json.dumps(model.to_dict())))
        with self.assertRaisesRegex(ValueError,"checksum"):
            FrozenExecutionModel.from_dict({**checkpoint,"uncompressed_sha256":"bad"})
        with patch("paired_execution_study.MAX_MODEL_JSON_BYTES", 100):
            with self.assertRaisesRegex(ValueError,"bound"):
                FrozenExecutionModel.from_dict(checkpoint)
            with self.assertRaisesRegex(ValueError,"bound"):
                model.snapshot()
        with self.assertRaises(ValueError):
            FrozenExecutionModel.from_dict({**checkpoint,"data":"not base64"})


if __name__ == "__main__":
    unittest.main()
