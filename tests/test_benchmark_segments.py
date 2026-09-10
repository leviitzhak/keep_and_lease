import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class SegmentTest(unittest.TestCase):
    def test_yield_is_continuation_not_a_completed_report(self):
        module = runpy.run_path(str(ROOT/'scripts/benchmark-btc-trade-range.py'))
        main = module['main']
        fake = Mock(manifest_bytes=b'fixture', source_manifest={
            'start':'2026-06-06T00:00:00', 'end':'2026-09-04T00:00:00'})
        def run(payload, root, audit, progress, **kwargs):
            audit.checkpoints.save(1, {'verified_cursor':1})
            progress('trade_checkpoint', 'saved')
            raise AssertionError('Should yield at saved checkpoint')
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(main.__globals__, ParquetTradeStore=lambda _: fake), \
             patch.object(main.__globals__['replay'], 'run', side_effect=run), \
             patch.object(main.__globals__['time'], 'monotonic', side_effect=[0, 20, 20]), \
             patch('sys.argv', ['benchmark','--dataset','fixture','--days','90',
                               '--output',directory,'--max-wall-seconds','10']):
            main()
            self.assertFalse((Path(directory)/'report.json').exists())
            self.assertEqual(json.loads((Path(directory)/'continuation.json').read_text())['status'],'checkpointed')
