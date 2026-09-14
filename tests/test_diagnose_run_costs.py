"""Offline regression tests for the owner-run diagnostic; no cloud access."""
import argparse
import contextlib
import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'diagnose_run_costs.py'
SPEC = importlib.util.spec_from_file_location('run_cost_diagnostic', SCRIPT)
diag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diag)
RUN = 'a' * 32


def fixture(root):
    """One complete UTC day with a spot sale and partial future fills."""
    lo, hi = diag.us('2026-06-07'), diag.us('2026-06-08')
    origin = lo - 1_000_000
    events = [
        dict(kind='initial_holding', us=origin, btc=1, price=100000),
        dict(kind='order', us=lo+1, symbol='SPOT', order_id=1, signed_btc=-.2),
        dict(kind='fill', us=lo+2, symbol='SPOT', order_id=1, signed_btc=-.2,
             price=100000, fee_usd=6),
        dict(kind='order', us=lo+3, symbol='FUT', order_id=2, signed_btc=.1),
        dict(kind='fill', us=lo+4, symbol='FUT', order_id=2, signed_btc=.05,
             price=100000, fee_usd=1.5),
        dict(kind='order_end', us=lo+5, symbol='FUT', order_id=2, remainder_btc=.05),
        dict(kind='order', us=lo+6, symbol='FUT', order_id=3, signed_btc=.05),
        dict(kind='fill', us=lo+7, symbol='FUT', order_id=3, signed_btc=.05,
             price=100000, fee_usd=1.5),
    ]
    valuations = [
        dict(us=origin, units={'SPOT': 1}, fees_usd=0, turnover_usd=0, nav_usd=100000),
        dict(us=lo, units={'SPOT': 1}, fees_usd=0, turnover_usd=0, nav_usd=100000),
        dict(us=hi, units={'SPOT': .8, 'FUT': .1}, fees_usd=9,
             turnover_usd=30000, nav_usd=99991),
    ]
    datasets = {}
    for name, rows in [('btc_trade_events', events), ('btc_trade_valuations', valuations)]:
        for row in rows:
            row['date'] = diag.iso(row['us'])
        raw = b''.join((json.dumps(row)+'\n').encode() for row in rows)
        data = gzip.compress(raw, mtime=0)
        relative = f'{name}/000000.jsonl.gz'
        path = root / 'audit' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entry = dict(object=relative, index=0, rows=len(rows), start=rows[0]['date'],
                     end=rows[-1]['date'], compressed_bytes=len(data),
                     uncompressed_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                     compressed_sha256=hashlib.sha256(data).hexdigest())
        datasets[name] = dict(rows=len(rows), chunks=[entry])
    (root/'audit/manifest.json').write_text(json.dumps(dict(schema_version=1, datasets=datasets)))
    result = dict(result_kind='btc_trade_replay', parameters={'trading_fee_bps': 3},
                  summary={'start': diag.iso(origin), 'end': diag.iso(hi)},
                  trade_replay={'capital_usd': 100000})
    (root/'result.json.gz').write_bytes(gzip.compress(json.dumps(result).encode()))
    return events, valuations, lo, hi


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events, self.valuations, self.lo, self.hi = fixture(self.root)

    def analysis(self, events=None, valuations=None):
        return diag.analyse(events if events is not None else self.events,
                            valuations if valuations is not None else self.valuations,
                            self.lo, self.hi, 3)

    def test_partial_fills_and_replacement_charge_only_filled_deltas(self):
        a = self.analysis()
        self.assertEqual(a['totals']['fills'], 3)
        self.assertEqual(a['totals']['recorded_fees_usd'], 9)
        self.assertEqual(a['totals']['expected_fees_usd'], 9)
        self.assertEqual(a['totals']['traded_notional_usd'], 30000)
        self.assertEqual(a['cancelled_unfilled_remainders'], 1)
        self.assertEqual(a['order_side_or_overfill_errors'], 0)
        self.assertEqual(a['first_fills'][-1]['quantity_after_btc'], .1)
        self.assertEqual(a['first_fills'][-1]['target_reconstructed_from_order_btc'], .1)
        self.assertTrue(all(check['inventory']['status'] == 'passed'
                            for check in a['boundary_reconciliations']))

    def test_incorrect_fee_is_detected(self):
        events = copy.deepcopy(self.events)
        events[2]['fee_usd'] = 7
        a = self.analysis(events)
        self.assertEqual(a['totals']['fee_mismatches'], 1)
        self.assertEqual(a['boundary_reconciliations'][-1]['fee_counter']['status'], 'FAILED')

    def test_missing_historical_turnover_is_not_zero(self):
        valuations = copy.deepcopy(self.valuations)
        for row in valuations:
            row.pop('turnover_usd')
        a = self.analysis(valuations=valuations)
        self.assertEqual(a['boundary_reconciliations'][-1]['turnover_counter']['status'], 'unavailable')

    def test_daily_dollars_and_bps_are_distinct(self):
        day = self.analysis()['days'][0]
        self.assertTrue(day['complete_utc_day'])
        self.assertEqual(day['recorded_fees_usd'], 9)
        self.assertAlmostEqual(day['fees_bps_of_reference_nav'], .9)
        self.assertAlmostEqual(day['turnover_times_reference_nav'], .3)

    def test_corrupt_audit_checksum_is_rejected(self):
        manifest = json.loads((self.root/'audit/manifest.json').read_text())
        entry = manifest['datasets']['btc_trade_events']['chunks'][0]
        entry['compressed_sha256'] = '0'*64
        reader = diag.Reader(RUN, diag.MIB, self.root)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            list(reader.chunk(entry))

    def test_reader_rejects_paths_outside_known_run_objects(self):
        reader = diag.Reader(RUN, diag.MIB, self.root)
        with self.assertRaisesRegex(ValueError, 'Unexpected run object'):
            reader.get('../../credentials.json')

    def test_offline_end_to_end_has_no_remote_commands(self):
        args = argparse.Namespace(run_id=RUN, max_read_mib=1, local_run_dir=self.root,
                                  day=None, days=1, fee_bps=3)
        with patch.object(diag.Reader, '_command', side_effect=AssertionError('No remote reads')):
            with contextlib.redirect_stderr(io.StringIO()):
                report = diag.run(args)
        self.assertEqual(report['status'], 'NO_DISCREPANCIES_IN_PERFORMED_CHECKS')
        self.assertEqual(report['analysis']['totals']['recorded_fees_usd'], 9)
        self.assertEqual(report['selected_period']['start'], '2026-06-07T00:00:00Z')
        self.assertGreater(report['boundary_checks_performed'], 0)

    def test_cli_writes_plain_local_reports_and_preserves_previous_output(self):
        out = self.root/'report-output'
        cmd = [sys.executable, str(SCRIPT), '--run-id', RUN, '--local-run-dir', str(self.root),
               '--output', str(out)]
        first = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((out/'report.txt').is_file())
        original = (out/'report.json').read_bytes()
        self.assertEqual(json.loads(original)['tested_fee_bps'], 3)
        second = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((out/'report.json').read_bytes(), original)

    def test_run_id_is_explicitly_required(self):
        done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True,
                              text=True, timeout=10)
        self.assertEqual(done.returncode, 2)
        self.assertIn('--run-id', done.stderr)


if __name__ == '__main__':
    unittest.main()
