import gzip
import math
import unittest

from fastapi.testclient import TestClient

import btc_trade_backtest as replay
from replay_checkpoints import decode, encode
from server.app import create_app
from server.strategy_catalog import install
from tests.test_btc_trade_backtest import payload
from tests.test_server_api import FakeEngine


class CurrentRuntimeImprovementsTests(unittest.TestCase):
    def test_checked_in_strategies_are_exposed_read_only(self):
        app = create_app(FakeEngine())
        install(app)
        with TestClient(app) as client:
            response = client.get('/api/v1/strategies')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        strategies = response.json()['strategies']
        names = {item['name'] for item in strategies}
        self.assertIn('full silver long gradual', names)
        self.assertIn('research-btc-long-gradual-500ms', names)
        self.assertTrue(all(isinstance(item['parameters'], dict) for item in strategies))

    def test_trade_replay_defaults_to_100k_and_3000_plot_points(self):
        parameters = payload()
        parameters.pop('trade_initial_capital_usd', None)
        parameters.pop('trade_plot_max_points', None)
        validated = replay.validate(parameters)
        self.assertEqual(validated[5], 100000)
        self.assertEqual(validated[6], 3000)

    def test_trade_plot_point_limit_is_bounded(self):
        for value in (499, 10001):
            parameters = payload()
            parameters['trade_plot_max_points'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                replay.validate(parameters)

    def test_checkpoint_infinity_sentinel_uses_strict_json_and_roundtrips(self):
        encoded = encode({'minimum': math.inf, 'negative': -math.inf, 'finite': 1.25})
        raw = gzip.decompress(encoded)
        self.assertNotIn(b'Infinity', raw)
        self.assertNotIn(b'NaN', raw)
        restored = decode(encoded)
        self.assertEqual(restored['minimum'], math.inf)
        self.assertEqual(restored['negative'], -math.inf)
        self.assertEqual(restored['finite'], 1.25)
        with self.assertRaisesRegex(ValueError, 'NaN'):
            encode({'invalid': math.nan})


if __name__ == '__main__':
    unittest.main()
