import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('cloud_btc_storage',Path(__file__).parents[1]/'scripts/cloud-btc-storage.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class CloudStorageVerificationTests(unittest.TestCase):
    def test_expected_events_pass_and_event_drift_fails(self):
        report=json.loads((module.BASELINES/'event-equivalence.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.json'
            path.write_text(json.dumps(report));module.verify_events(path)
            report['events']-=1;path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'events'):module.verify_events(path)
    def test_changed_financial_result_fails_before_audit_publication(self):
        report=json.loads((module.BASELINES/'run-one-dollar.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);report['fills']+=1
            (path/'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'Financial replay differs'):
                module.verify_replay(path,'run-one-dollar')
