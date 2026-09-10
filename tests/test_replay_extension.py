import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backtest_audit import AuditCollection, MemoryAuditStore, read_chunk
from replay_checkpoints import DirectoryCheckpoints
from replay_extension import extend_checkpoint
from tests.test_trade_range_recovery import RecoveryTests, ROOT
import btc_trade_backtest as replay


class ExtensionTests(unittest.TestCase):
    def test_extended_financial_and_audit_rows_equal_uninterrupted(self):
        p, store, coverage = RecoveryTests().scenario()
        short = dict(p, backtest_end='2026-06-26T00:00:01')
        with tempfile.TemporaryDirectory() as root, \
             patch.object(replay.strategy, 'read_rates', return_value={}), \
             patch.object(replay.strategy, 'usd_rate', return_value=.05):
            parent_store = MemoryAuditStore()
            parent = AuditCollection(parent_store)
            parent.checkpoints = DirectoryCheckpoints(Path(root)/'parent')
            replay.run(short, ROOT, parent, store=store, coverage=coverage)
            before = dict(parent_store.objects)
            child = AuditCollection(MemoryAuditStore())
            child.checkpoints = DirectoryCheckpoints(Path(root)/'child')
            extend_checkpoint(parent.checkpoints.latest(), short, p, store.manifest_bytes, ROOT,
                              parent.store, child.store, child.checkpoints)
            extended = replay.run(p, ROOT, child, store=store, coverage=coverage)
            full = AuditCollection(MemoryAuditStore())
            full.checkpoints = DirectoryCheckpoints(Path(root)/'full')
            expected = replay.run(p, ROOT, full, store=store, coverage=coverage)
            self.assertEqual(extended['summary'], expected['summary'])
            for product in expected['audit']['datasets']:
                def rows(audit, result):
                    return [row for e in result['audit']['datasets'][product]['chunks']
                            for row in read_chunk(audit.store, e)]
                self.assertEqual(rows(child, extended), rows(full, expected))
            self.assertEqual(parent_store.objects, before)
            self.assertEqual(extended['trade_replay']['resumed_after_us'], replay.us_time('2026-06-26'))
            other = dict(p, execution_interval_seconds=1)
            with self.assertRaisesRegex(ValueError, 'Only the end'):
                extend_checkpoint(parent.checkpoints.latest(), short, other, store.manifest_bytes, ROOT,
                                  parent.store, MemoryAuditStore(), DirectoryCheckpoints(Path(root)/'wrong'))
            with self.assertRaisesRegex(ValueError, 'manifest differ'):
                extend_checkpoint(parent.checkpoints.latest(), short, p, b'changed', ROOT,
                                  parent.store, MemoryAuditStore(), DirectoryCheckpoints(Path(root)/'changed'))
