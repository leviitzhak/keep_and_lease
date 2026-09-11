"""Diagnostic telemetry changes display data, not trading decisions or P&L."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_btc_trade_backtest import BtcTradeBacktestTests, FakeStore, payload
from tests.test_observed_execution import ObservedExecutionTests
from tests.test_server_api import FakeEngine
from fastapi.testclient import TestClient
from server.app import create_app
import silver_strategy_gui as gui
from trade_replay import TapeAccount, Trade

ROOT=Path(__file__).resolve().parents[1]

class SharedPlotTests(unittest.TestCase):
    def test_replay_plot_telemetry_reconciles_and_records_held_instruments(self):
        result, audit = BtcTradeBacktestTests().simulate()
        fields=result['fields']
        for row in result['series']:
            r=dict(zip(fields,row));capital=result['trade_replay']['capital_usd']
            self.assertAlmostEqual(r['spot_pnl_usd']+r['futures_pnl_usd'],r['market_pnl_usd'])
            self.assertAlmostEqual(capital+r['market_pnl_usd']+r['treasury_interest_usd']-r['fees_usd'],r['nav']*capital)
            self.assertAlmostEqual(r['reconstruction_error_usd'],0)
            self.assertGreater(r['treasury_accrual_index'],0)
            for h in r['held_futures']:
                self.assertGreater(h['quantity'],0);self.assertGreater(h['maturity_days'],0)
                self.assertAlmostEqual(h['premium_pct'],100*(h['price']/r['spot_price']-1))
        self.assertTrue(any(row[-1] for row in result['series']))
        self.assertEqual(len(audit['btc_trade_valuations']),result['summary']['observations'])
        json.dumps(result,allow_nan=False)

    def test_account_telemetry_survives_resume_and_expiry(self):
        a=TapeAccount(100);a.initialize_spot(Trade(0,'SPOT',100,1,'buy','s'))
        a.on_trade(Trade(1,'SPOT',101,1,'buy','s2'))
        b=TapeAccount.restore(json.loads(json.dumps(a.snapshot())))
        self.assertEqual(a.snapshot(),b.snapshot());self.assertEqual(b.plot_spot_pnl,1)
        b.units['F']=.5;b.marks['F']=Trade(1,'F',100,1,'buy','f')
        b.settle('F',2,102,'fixture');self.assertEqual(b.plot_futures_pnl,1)
        self.assertEqual(b.market_pnl,2)

    def test_future_prints_do_not_change_earlier_diagnostic_points(self):
        before,_=BtcTradeBacktestTests().simulate()
        store=FakeStore();from dataclasses import replace
        store.events=[replace(t,price=t.price*1.1) if t.us>store.start+1000000 else t for t in store.events]
        after,_=BtcTradeBacktestTests().simulate(store=store)
        early=lambda r:[row for row in r['series'] if row[0]<'2026-06-25T00:00:01.000000']
        self.assertEqual(early(before),early(after))

    def test_candle_plot_counters_use_every_actual_simulated_fill(self):
        fixture=ObservedExecutionTests();market=fixture.market()
        p=dict(min_days=1,futures_contract_type='regular',trading_calendar='all_days',
               execution_interval_seconds=60,enable_short_book='false',execution_model='observed',slv_expense=0,trading_fee_bps=2)
        result=gui.sleeve_result({'commodity_parameters':{'btc':p}},market,'btc')
        f=result['fields'];rows=result['_full_rows']
        expected=sum(abs(x['quantity_change'])*x.get('price',x.get('mark_price',0)) for r in rows for x in r['execution_audit']['fills'])
        self.assertAlmostEqual(result['series'][-1][f.index('plot_turnover_total')],expected)
        self.assertAlmostEqual(result['series'][-1][f.index('plot_cost_total')],sum(r['trading_cost_value'] for r in rows))
        self.assertTrue(all(r[f.index('plot_target_start')] is None for r in result['series']))

    def test_static_asset_route_is_installed_and_no_cache(self):
        with TestClient(create_app(FakeEngine())) as client:
            response=client.get('/shared-run-plots.js')
            self.assertEqual(response.status_code,200)
            self.assertIn('KeepLeasePlots',response.text)
            self.assertEqual(response.headers['cache-control'],'no-cache')

if __name__=='__main__':unittest.main()
