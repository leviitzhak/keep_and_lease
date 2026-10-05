"""Monthly selection, historical normalization and date-specific contract checks."""
import importlib.util
from pathlib import Path
import sys
import unittest
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import databento_year as year
import databento_gold as gold

class MonthlyTests(unittest.TestCase):
    def test_selects_month_start_volume_rank_and_excludes_month_expiry(self):
        volume={'result':{'MBT.v.0':[{'d0':'2025-10-01','d1':'2025-10-20','s':'1'},
                                   {'d0':'2025-10-20','d1':'2025-11-01','s':'2'}],
                          'MBT.v.1':[{'d0':'2025-10-01','d1':'2025-11-01','s':'2'}]}}
        raw={'result':{'1':[{'d0':'2025-10-01','d1':'2025-11-01','s':'MBTV5'}],
                       '2':[{'d0':'2025-10-01','d1':'2025-11-01','s':'MBTX5'}]}}
        r=year.monthly_choices('mbt',volume,raw)[0]
        self.assertEqual(r['future_symbol'],'MBTX5')
        self.assertEqual(r['previous_day_volume_rank'],2)
        self.assertEqual(r['selection_date'],'2025-10-01')

    def test_metal_expiry_precedes_labeled_month_and_prelaunch_is_missing(self):
        volume={'result':{'SIC.v.0':[{'d0':'2026-02-10','d1':'2026-03-01','s':'1'}],
                          'SIC.v.1':[{'d0':'2026-02-10','d1':'2026-03-01','s':'2'}]}}
        raw={'result':{'1':[{'d0':'2026-02-09','d1':'2026-03-01','s':'SICH6'}],
                       '2':[{'d0':'2026-02-09','d1':'2026-03-01','s':'SICK6'}]}}
        choices=year.monthly_choices('sic',volume,raw)
        self.assertEqual([x['status'] for x in choices[:4]],['before_product_launch']*4)
        self.assertEqual(choices[4]['future_symbol'],'SICK6')
        self.assertEqual(choices[4]['analysis_start'],'2026-02-10T00:00:00+00:00')

    def test_fee_reconstruction_and_cash_are_dated(self):
        cash=pd.DataFrame({'available_at':pd.to_datetime(['2025-09-30','2025-10-03'],utc=True),'usd_rate':[.04,.03]})
        refs=year.references('sic',cash)
        self.assertEqual(refs.iloc[0].usd_rate,.04)
        self.assertEqual(refs.iloc[2].usd_rate,.03)
        self.assertGreater(refs.iloc[0].units_per_share,refs.iloc[-1].units_per_share)
        self.assertAlmostEqual(refs.iloc[0].units_per_share/refs.iloc[-1].units_per_share,
                               __import__('math').exp(.005*364/365))
        flat=year.references('sic',cash,'constant')
        self.assertEqual(flat.units_per_share.nunique(),1)

    def test_generalized_year_and_january_metal_expiry(self):
        c=gold.config_at(gold.PRESETS['gold']);c.update(future_symbol='1OZG6',start='2025-12-01T00:00:00Z',end='2026-01-01T00:00:00Z')
        self.assertEqual(gold.market(c)['month'],2)
        self.assertEqual(gold.holding_setting(c,'dataset'),'XNAS.ITCH')
        frame=pd.DataFrame({'raw_symbol':['1OZG6'],'maturity_year':[2026],'maturity_month':[2],'expiration':[pd.Timestamp('2026-01-28T18:30:00Z')]})
        self.assertEqual(gold.expiry_from_definitions(frame,c),frame.expiration.iloc[0])
        frame['maturity_year']=2025
        with self.assertRaisesRegex(ValueError,'February 2026'):gold.expiry_from_definitions(frame,c)

    def test_definition_window_spans_weekend_and_prices_span_month(self):
        c=gold.config_at(gold.PRESETS['mbt']);c.update(start='2025-11-01T00:00:00Z',end='2025-12-01T00:00:00Z',future_symbol='MBTZ5')
        r=year.requests_for(c)
        self.assertEqual(len(r),3)
        self.assertEqual(pd.Timestamp(r[-1]['request']['end']),pd.Timestamp('2025-11-06T00:00:00Z'))
        self.assertEqual(r[0]['request']['end'],c['end'])

if __name__=='__main__':unittest.main()
