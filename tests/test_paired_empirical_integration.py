"""Causal calibration, durable restart, and exported evidence through replay."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from backtest_audit import MemoryAuditStore
import btc_trade_backtest as replay
from replay_checkpoints import DirectoryCheckpoints
from server.replay_exports import replay_workbook
from tests.test_btc_trade_backtest import FakeStore
from tests.test_paired_backtest_integration import parameters, run_case
from trade_replay import Trade


def fixture(cross_hour=False):
    p, store = parameters(), FakeStore()
    start = store.start + (3598 if cross_hour else 120) * 1_000_000
    end = start + 8_000_000
    p.update(backtest_start=replay.iso_time(start), backtest_end=replay.iso_time(end),
        paired_repricing_mode="empirical", paired_calibration_days=120/86400,
        paired_execution_min_samples=1, paired_execution_size_grid_btc="0.001",
        paired_waiting_seconds=1, paired_study_max_horizon_seconds=2,
        paired_observation_delay_seconds=.1, paired_decision_delay_seconds=.1,
        paired_order_delay_seconds=.1, paired_max_unpaired_btc=.01)
    store.source_manifest["futures"]["F"]["seed"]["price"] = 90
    store.events = []
    for i in range(1, 1291):
        us = start - 120_000_000 + i*100_000
        store.events.extend([
            Trade(us, "SPOT", 100, 100, "sell" if i % 2 else "buy", f"s{i}"),
            Trade(us+1, "F", 90, 100, "buy", f"f{i}")])
    return p, store, replay.catalog()


class EmpiricalReplayIntegrationTests(unittest.TestCase):
    def test_rejects_calibration_outside_available_history(self):
        p = parameters()
        p.update(paired_repricing_mode="empirical", paired_calibration_days=10)
        with self.assertRaisesRegex(ValueError, "calibration days before"):
            replay.validate(p)

    def test_calibration_precedes_opening_and_future_prices_cannot_change_model(self):
        p, store, coverage = fixture()
        result, rows, _ = run_case(p, store, coverage)
        study = result["trade_replay"]["execution_study"]
        cutoff = replay.us_time(p["backtest_start"])
        self.assertEqual(study["label_cutoff_us"], cutoff)
        self.assertGreater(study["labels"], 0)
        self.assertTrue(all(row["us"] <= cutoff for row in rows["btc_execution_study"]))
        self.assertGreaterEqual(rows["btc_trade_events"][0]["us"], cutoff)
        later = copy.deepcopy(store)
        from dataclasses import replace
        later.events = [replace(t, price=t.price*1.1) if t.us >= cutoff else t for t in later.events]
        changed, _, _ = run_case(p, later, coverage)
        self.assertEqual(changed["trade_replay"]["execution_study"], study)
        json.dumps(result, allow_nan=False)

    def test_checkpoint_restores_frozen_model_without_recalibrating(self):
        p, store, coverage = fixture(cross_hour=True)
        with tempfile.TemporaryDirectory() as root:
            full = MemoryAuditStore()
            expected, expected_rows, _ = run_case(p, store, coverage, full,
                DirectoryCheckpoints(Path(root)/"full"))
            interrupted = MemoryAuditStore()
            journal = DirectoryCheckpoints(Path(root)/"resume")
            with self.assertRaisesRegex(RuntimeError, "intentional checkpoint"):
                run_case(p, store, coverage, interrupted, journal, True)
            self.assertIsNotNone(journal.latest())
            with patch.object(replay, "calibrate_execution", side_effect=AssertionError("unexpected refit")):
                actual, actual_rows, _ = run_case(p, store, coverage, interrupted, journal)
        self.assertEqual(actual["summary"], expected["summary"])
        self.assertEqual(actual["trade_replay"]["execution_study"], expected["trade_replay"]["execution_study"])
        self.assertEqual(actual["trade_replay"]["paired_transfer"], expected["trade_replay"]["paired_transfer"])
        self.assertEqual(actual_rows, expected_rows)

    def test_workbook_distinguishes_historical_calibration_from_scored_outcomes(self):
        p, store, coverage = fixture()
        result, _, audit = run_case(p, store, coverage)
        content = b"".join(replay_workbook(audit.store, result["audit"], result,
            result["summary"]["start"], result["summary"]["end"]))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            workbook = archive.read("xl/workbook.xml").decode()
            self.assertIn('name="Execution study"', workbook)
            self.assertIn('name="Execution outcomes"', workbook)
            overview = archive.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn("preceding the scored portfolio", overview)


if __name__ == "__main__":
    unittest.main()
