import io
import json
from datetime import date
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

import download_spot_history as mod


class SpotHistoryTests(unittest.TestCase):
    def test_existing_ninety_days_are_excluded_exactly(self):
        self.assertEqual(mod.missing_days(date(2026, 6, 5), date(2026, 9, 5)),
                         ['2026-06-05', '2026-09-04'])
        self.assertEqual(mod.missing_days(mod.EXISTING_START, mod.EXISTING_END), [])

    def test_shards_cover_all_dates_once(self):
        days = mod.missing_days(date(2017, 1, 1), date(2026, 10, 10))
        assigned = [d for s in range(mod.SHARDS) for d in days if mod.day_shard(d) == s]
        self.assertEqual(sorted(days), sorted(assigned))
        self.assertEqual(len(assigned), len(set(assigned)))

    def test_source_is_individual_trades_with_named_checksum(self):
        day = '2020-01-01'
        self.assertIn('/daily/trades/BTCUSDT/', mod.archive_url(day))
        sha = 'a' * 64
        self.assertEqual(mod.checksum_text(f'{sha}  BTCUSDT-trades-{day}.zip\n'.encode(), day), sha)
        for invalid in [f'{sha} other.zip', 'bad checksum', f'{sha} BTCUSDT-aggTrades-{day}.zip']:
            with self.assertRaises(ValueError):
                mod.checksum_text(invalid.encode(), day)

    def test_bounds_include_partial_day_and_ignore_future_expiry(self):
        p = {'instruments': [dict(first_available_seq=1,
             metadata={'creation_timestamp': 1577836800000, 'expiration_timestamp': 2524608000000},
             first_trade=[{'timestamp': 1577840400000}], last_trade=[{'timestamp': 1577923200000}],
             snapshot_at='2020-01-03T14:00:00+00:00')]}
        self.assertEqual(mod.plan_dates(p), (date(2020, 1, 1), date(2020, 1, 4)))

    def test_request_rejects_extra_network_or_storage_options(self):
        r = dict(schema_version=1, action='download-binance-spot-missing-history',
                 job_id='btc-spot-20261022-binance-full', sequence=1)
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'request.json'
            p.write_text(json.dumps(r))
            self.assertEqual(mod.request(p), r)
            r['url'] = 'https://example.org/'
            p.write_text(json.dumps(r))
            with self.assertRaises(ValueError):
                mod.request(p)

    def test_resume_detects_changed_object(self):
        blob = SimpleNamespace(size=123, metadata={'sha256': 'abc'}, generation=7, crc32c='xyz')
        rec = dict(bytes=123, sha256='abc', generation='7', crc32c='xyz')
        self.assertTrue(mod.object_matches(blob, rec))
        for field, value in [('bytes', 124), ('sha256', 'bad'), ('generation', '8'), ('crc32c', 'bad')]:
            self.assertFalse(mod.object_matches(blob, {**rec, field: value}))

    def test_verified_download_checks_bytes_before_publication(self):
        day, r = '2020-01-01', {'job_id': 'test'}
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr(f'BTCUSDT-trades-{day}.csv', '1,100,2,200,1577836800000,true,true\n')
        data = archive.getvalue()
        checksum = f'{mod.digest(data)} BTCUSDT-trades-{day}.zip'.encode()
        def opener(url, **kwargs):
            return io.BytesIO(checksum if url.endswith('.CHECKSUM') else data)
        with patch.object(mod, 'verify_receipt', return_value=None), \
             patch.object(mod.urllib.request, 'urlopen', side_effect=opener), \
             patch.object(mod, 'store_archive', return_value={'key': 'object'}) as upload, \
             patch.object(mod, 'create_json', side_effect=lambda b, k, v: v):
            record = mod.download_day(None, r, day, float('inf'))
            self.assertEqual(record['status'], 'VERIFIED_RAW_ARCHIVE')
            self.assertFalse(record['parsed'])
            upload.assert_called_once()
        bad_checksum = ('a' * 64 + f' BTCUSDT-trades-{day}.zip').encode()
        with patch.object(mod, 'verify_receipt', return_value=None), \
             patch.object(mod.urllib.request, 'urlopen', side_effect=[io.BytesIO(bad_checksum), io.BytesIO(data)]), \
             patch.object(mod, 'store_archive') as upload:
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                mod.download_day(None, r, day, float('inf'))
            upload.assert_not_called()

    def test_http_403_is_failure_and_404_is_gap(self):
        day, r = '2020-01-01', {'job_id': 'test'}
        for code in (403, 404):
            error = urllib.error.HTTPError(mod.archive_url(day), code, 'error', {}, None)
            with patch.object(mod, 'verify_receipt', return_value=None), \
                 patch.object(mod.urllib.request, 'urlopen', side_effect=error), \
                 patch.object(mod, 'create_json', side_effect=lambda b, k, v: v):
                if code == 403:
                    with self.assertRaises(urllib.error.HTTPError):
                        mod.download_day(None, r, day, float('inf'))
                else:
                    self.assertEqual(mod.download_day(None, r, day, float('inf'))['status'], 'SOURCE_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
