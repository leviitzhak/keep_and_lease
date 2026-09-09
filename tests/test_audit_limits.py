import os
import unittest
from unittest.mock import patch

import backtest_audit as audit
from server.audit_limits import configure_audit_limits


class AuditLimitTests(unittest.TestCase):
    def test_large_final_index_can_be_published_and_read_without_replaying(self):
        # Reproduce finalization with an index above the former 4 MiB limit.
        store = audit.MemoryAuditStore()
        collection = audit.AuditCollection(store, provenance={'fixture': 'x' * (4 * 1024 * 1024)})
        with patch.object(audit, 'MAX_MANIFEST_BYTES', 4 * 1024 * 1024):
            with self.assertRaisesRegex(ValueError, 'manifest exceeds'):
                collection.finish()
            with patch.dict(os.environ, KEEP_AND_LEASE_AUDIT_MANIFEST_MIB='32'):
                configure_audit_limits()
            result = collection.finish()
            self.assertEqual(audit.load_manifest(store), result)
            self.assertGreater(len(store.objects['manifest.json']), 4 * 1024 * 1024)
        with patch.object(audit, 'MAX_MANIFEST_BYTES', 4 * 1024 * 1024):
            with self.assertRaisesRegex(ValueError, 'manifest exceeds'):
                audit.load_manifest(store)

    def test_budget_remains_bounded(self):
        for value in ('0', '65', 'unlimited'):
            with patch.dict(os.environ, KEEP_AND_LEASE_AUDIT_MANIFEST_MIB=value):
                with self.assertRaises(ValueError): configure_audit_limits()
