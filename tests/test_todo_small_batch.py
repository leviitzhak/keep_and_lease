"""Regression coverage for backwards-compatible streamed replay CSV exports."""
import csv
import io
import json
import time
import unittest
from fastapi.testclient import TestClient
from server.app import create_app
from tests.test_server_api import FakeEngine


class ReplayCsvTests(unittest.TestCase):
    def test_new_columns_preserve_historical_unknowns_and_audit_rows(self):
        rows = [
            dict(cash_usd=125, futures_notional_usd=100, target_futures_notional_usd=110,
                 free_collateral_usd=25, collateralization_ratio=1.25, turnover_usd=900),
            dict(cash_usd=75, futures_notional_usd=-50),
            dict(cash_usd=75, futures_notional_usd=0),
            dict(cash_usd=75),
            dict(futures_notional_usd=50),
            dict(cash_usd=125, futures_notional_usd=100, target_futures_notional_usd=0,
                 free_collateral_usd=0, collateralization_ratio=0, turnover_usd=0),
        ]
        rows = [dict(row, date=f'2026-06-25T00:00:0{i}', units={'F': .5}, targets={'F': 1})
                for i, row in enumerate(rows)]

        class Engine(FakeEngine):
            def run_backtest_with_audit(self, parameters, audit, progress):
                writer = audit.writer('btc_trade_valuations')
                for row in rows:
                    writer.emit(row)
                return {'audit': audit.finish()}

        with TestClient(create_app(Engine())) as client:
            response = client.post('/api/v1/backtests', json={'parameters': {'weight_silver': 100}})
            self.assertEqual(response.status_code, 202, response.text)
            created = response.json()
            for _ in range(100):
                state = client.get(created['status_url']).json()
                if state['status'] in ('completed', 'failed'):
                    break
                time.sleep(.01)
            self.assertEqual(state['status'], 'completed', state)
            base = created['result_url'].removesuffix('/result')
            result = client.get(base + '/trade-valuations.csv')
            self.assertEqual(result.status_code, 200, result.text)
            reader = csv.DictReader(io.StringIO(result.text))
            actual = list(reader)
            self.assertEqual(reader.fieldnames[-4:], ['target_futures_notional_usd',
                'free_collateral_usd', 'collateralization_ratio', 'turnover_usd'])
            self.assertEqual(len(actual), len(rows))
            self.assertEqual([actual[0][f] for f in reader.fieldnames[-4:]], ['110','25','1.25','900'])
            self.assertEqual([actual[1][f] for f in reader.fieldnames[-4:]], ['','25','1.5',''])
            self.assertEqual([actual[2][f] for f in reader.fieldnames[-4:]], ['','75','',''])
            for i in (3,4):
                self.assertTrue(all(actual[i][f] == '' for f in reader.fieldnames[-4:]))
            self.assertEqual([actual[5][f] for f in reader.fieldnames[-4:]], ['0','0','0','0'])
            self.assertEqual(json.loads(actual[0]['units']), rows[0]['units'])
            raw = client.get(base+'/audit/btc_trade_valuations/0').json()['rows']
            self.assertEqual(raw, rows)


if __name__ == '__main__':
    unittest.main()
