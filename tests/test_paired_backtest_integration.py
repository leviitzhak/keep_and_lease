"""End-to-end funded policy routing, audit, and restart acceptance checks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from backtest_audit import AuditCollection, MemoryAuditStore, read_chunk
import btc_trade_backtest as replay
from replay_checkpoints import DirectoryCheckpoints
from tests.test_btc_trade_backtest import FakeStore, payload
from trade_replay import Trade

ROOT = Path(__file__).resolve().parents[1]


def parameters():
    p = payload()
    p.update(trade_strategy='cost_aware_paired', backtest_end='2026-06-25T00:00:08',
             paired_max_unpaired_btc=1, paired_uncertainty_bps=0,
             paired_horizon_days='1,7,30', paired_max_quote_skew_seconds=1,
             paired_max_transfer_fraction=.25, paired_max_legging_seconds=30)
    p['commodity_parameters']['btc'].update(execution_delay_seconds=0,
                                           max_quote_age_seconds=2)
    return p


def scenario(midnight=False):
    p, store = parameters(), FakeStore()
    if midnight:
        p.update(backtest_start='2026-06-25T23:59:58', backtest_end='2026-06-26T00:00:06')
        store.source_manifest['end'] = '2026-06-27T00:00:00'
    start = replay.us_time(p['backtest_start'])
    store.source_manifest['futures']['F']['seed']['price'] = 90
    store.events = [Trade(start, 'SPOT', 100, 100, 'buy', 'initial')]
    for n in range(1, 80):
        # Both feeds and both trade directions remain observable; only subsequent
        # correctly sided prints may execute. An unchanged curve exposes churn.
        us = start+n*100_000
        store.events.extend([
            Trade(us, 'SPOT', 100, 100, 'sell' if n % 2 else 'buy', f's{n}'),
            Trade(us+1, 'F', 90, 100, 'buy' if n % 2 else 'sell', f'f{n}')])
    coverage = dict(replay.catalog(), end=store.source_manifest['end'])
    return p, store, coverage


def run_case(p, store, coverage, audit_store=None, journal=None, interrupt=False):
    audit = AuditCollection(audit_store or MemoryAuditStore())
    audit.checkpoints = journal
    def progress(stage, detail):
        if interrupt and stage == 'trade_checkpoint':
            raise RuntimeError('intentional checkpoint interruption')
    result = replay.run(p, ROOT, audit, progress, store=store, coverage=coverage)
    rows = {name: [row for chunk in info['chunks'] for row in read_chunk(audit.store, chunk)]
            for name, info in result['audit']['datasets'].items()}
    return result, rows, audit


class PairedBacktestIntegrationTests(unittest.TestCase):
    def test_requires_supported_data_and_rejects_invalid_configuration(self):
        for update in ({'btc_data_source':'minute'}, {'trade_strategy':'unknown'},
                       {'paired_max_transfer_fraction':0}, {'paired_horizon_days':'0,7'},
                       {'paired_spot_feed_delay_seconds':-1}, {'paired_max_rate_age_days':float('nan')}):
            p = parameters(); p.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                replay.validate(p)

    def test_funded_transfers_route_audit_and_reconcile(self):
        p, store, coverage = scenario()
        result, rows, _ = run_case(p, store, coverage)
        json.dumps(result, allow_nan=False)
        self.assertEqual(result['trade_replay']['strategy'], 'cost_aware_paired')
        self.assertIn('paired_transfer', result['trade_replay'])
        self.assertIn('treasury_rate_model', result['trade_replay'])
        self.assertGreater(result['trade_replay']['fills'], 0)
        self.assertEqual(result['trade_replay']['collateral_breach_count'], 0)
        self.assertLess(result['trade_replay']['max_nav_reconstruction_error_usd'], 1e-7)
        fills = [r for r in rows['btc_trade_events'] if r['kind'] == 'fill']
        self.assertTrue(fills)
        self.assertTrue(all(r.get('pair_id') for r in fills))
        for row in rows['btc_trade_valuations']:
            self.assertGreaterEqual(row['cash_usd'] + row.get('unsettled_pnl_usd', 0),
                                    row['futures_notional_usd'] - 1e-7)
            self.assertAlmostEqual(row['commodity_nav_btc'], row['nav_usd']/100)

    def test_legacy_remains_the_default(self):
        p = payload()
        self.assertNotIn('trade_strategy', p)
        self.assertIsNotNone(replay.validate(p))

    def test_costs_and_delays_persist_across_real_midnight_restart(self):
        p, store, coverage = scenario(midnight=True)
        p.update(paired_spot_feed_delay_seconds=.3, paired_futures_feed_delay_seconds=.4,
                 paired_response_delay_seconds=.7, paired_spot_fixed_fee_usd=.2,
                 paired_futures_min_fee_usd=.3)
        p['commodity_parameters']['btc']['trading_fee_bps'] = 1
        with tempfile.TemporaryDirectory() as root:
            uninterrupted_store, interrupted_store = MemoryAuditStore(), MemoryAuditStore()
            expected, rows, _ = run_case(p, store, coverage, uninterrupted_store,
                                         DirectoryCheckpoints(Path(root)/'full'))
            journal = DirectoryCheckpoints(Path(root)/'resume')
            with self.assertRaisesRegex(RuntimeError, 'intentional checkpoint'):
                run_case(p, store, coverage, interrupted_store, journal, True)
            self.assertIsNotNone(journal.latest())
            actual, resumed_rows, _ = run_case(p, store, coverage, interrupted_store, journal)
            self.assertEqual(actual['summary'], expected['summary'])
            self.assertEqual(actual['series'], expected['series'])
            self.assertEqual(resumed_rows, rows)
            self.assertEqual(actual['trade_replay']['paired_transfer'], expected['trade_replay']['paired_transfer'])

    def test_stale_rates_block_new_discretionary_transfers(self):
        p, store, coverage = scenario()
        p['paired_max_rate_age_days'] = .0001
        result, rows, _ = run_case(p, store, coverage)
        self.assertEqual(result['trade_replay']['fills'], 0)
        self.assertEqual(rows['btc_trade_valuations'][-1]['units']['SPOT'], 1000)

    def test_adaptive_latency_and_orders_resume_identically_across_midnight(self):
        p, store, coverage = scenario(midnight=True)
        p.update(paired_repricing_mode='adaptive',
                 paired_observation_delay_seconds=.1,
                 paired_decision_delay_seconds=.2,
                 paired_order_delay_seconds=.3,
                 paired_response_delay_seconds=.4)
        # The explicit delivery delay supersedes, rather than adds to, the
        # legacy delay. A replay restarted with queued work must be identical.
        p['commodity_parameters']['btc']['execution_delay_seconds'] = 4
        with tempfile.TemporaryDirectory() as root:
            full_store, resumed_store = MemoryAuditStore(), MemoryAuditStore()
            expected, expected_rows, _ = run_case(
                p, store, coverage, full_store, DirectoryCheckpoints(Path(root)/'full'))
            journal = DirectoryCheckpoints(Path(root)/'resume')
            with self.assertRaisesRegex(RuntimeError, 'intentional checkpoint'):
                run_case(p, store, coverage, resumed_store, journal, True)
            actual, actual_rows, _ = run_case(p, store, coverage, resumed_store, journal)
        self.assertEqual(actual['summary'], expected['summary'])
        self.assertEqual(actual['series'], expected['series'])
        self.assertEqual(actual_rows, expected_rows)
        self.assertEqual(actual['trade_replay']['paired_transfer'],
                         expected['trade_replay']['paired_transfer'])
        self.assertEqual(actual['trade_replay']['delay_seconds'], .3)
        self.assertGreater(actual['trade_replay']['fills'], 0)
        self.assertEqual(actual['trade_replay']['collateral_breach_count'], 0)
        self.assertLess(actual['trade_replay']['max_nav_reconstruction_error_usd'], 1e-7)


if __name__ == '__main__':
    unittest.main()
