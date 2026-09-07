import unittest
from unittest.mock import patch
from datetime import datetime
import silver_strategy_gui as gui
from tests import test_streamed_backtest as fixtures


class BacktestPeriodTests(unittest.TestCase):
    def market(self):
        return fixtures.StreamedBacktestTests().market()

    def payload(self, **kwargs):
        return dict(weight_silver=0, weight_btc=100, min_days=1,
                    execution_interval_seconds=60,
                    commodity_parameters={'btc':{'futures_contract_type':'regular',
                    'execution_model':'legacy_close','slv_expense':0}}, **kwargs)

    def run_result(self, payload):
        with patch.object(gui,'MARKETS',{'btc':self.market()}):
            return gui.result(payload)

    def test_blank_bounds_preserve_results(self):
        before=self.run_result(self.payload())
        after=self.run_result(self.payload(backtest_start='',backtest_end=''))
        self.assertEqual(before['summary'],after['summary'])
        self.assertEqual(before['series'],after['series'])

    def test_period_is_fresh_computation_and_comparisons_are_bounded(self):
        payload=self.payload(backtest_start='2026-06-08T00:02:00Z',backtest_end='2026-06-08T00:06:00Z')
        calls=[]
        original=gui.run_backtest
        def traced(*args,**kwargs):
            calls.append(sorted(args[3]))
            return original(*args,**kwargs)
        with patch.object(gui,'run_backtest',side_effect=traced):
            result=self.run_result(payload)
        self.assertGreaterEqual(len(calls),2)
        for dates in calls:
            self.assertEqual(dates[0],datetime(2026,6,8,0,2))
            self.assertEqual(dates[-1],datetime(2026,6,8,0,6))
        self.assertEqual(result['summary']['observations'],4)
        self.assertEqual(result['backtest_period']['actual_start'],'2026-06-08T00:02:00')
        self.assertEqual(result['backtest_period']['actual_end'],'2026-06-08T00:06:00')
        fields=result['fields']; row=result['series'][0]
        self.assertEqual(row[fields.index('start_nav')],1)
        # A fresh period differs from retaining old NAV and just cropping output.
        whole=self.run_result(self.payload())
        old=whole['series'][2][fields.index('start_nav')]
        self.assertNotEqual(old,1)

    def test_causal_rate_history_and_market_are_preserved(self):
        market=self.market(); dates=set(market[3])
        start,end=gui.backtest_bounds(self.payload(backtest_start='2026-06-08T00:02',backtest_end='2026-06-08T00:06'))
        selected=gui.period_market(market,start,end)
        self.assertIs(selected[2],market[2])
        self.assertEqual(set(market[3]),dates)
        self.assertLess(market[2][91][0][0],start)

    def test_open_bounds_utc_offsets_and_invalid_periods(self):
        start,end=gui.backtest_bounds({'backtest_start':'2026-06-08T03:02:00+03:00'})
        self.assertEqual(start,datetime(2026,6,8,0,2));self.assertIsNone(end)
        for start,end in [('bad',''),('2026-06-09','2026-06-08'),('2026-06-08','2026-06-08')]:
            with self.assertRaises(ValueError):gui.backtest_bounds({'backtest_start':start,'backtest_end':end})
        with self.assertRaisesRegex(ValueError,'at least two'):
            self.run_result(self.payload(backtest_start='2030-01-01'))
