"""Offline causal pairing, complete coverage and calculation contracts."""
import importlib.util
import json
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pyarrow as pa

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_lease_maturity_history as h


def record(t,price='100',symbol='SPOT',seq=1):
    return dict(timestamp_us=t,symbol=symbol,price=Decimal(price),native_quantity=Decimal('1'),
        quantity_currency='BTC' if symbol=='SPOT' else 'USD',quote_currency='USDT' if symbol=='SPOT' else 'USD',
        side='buy',trade_id=str(seq),source_sequence=seq,flags=0,source_file='test')


def batch(rows):
    return pa.RecordBatch.from_pylist(rows).select(h.COLUMNS)


class PairTests(unittest.TestCase):
    def match(self,times,rows,carry=None):
        with patch.object(h,'batches',return_value=iter([batch(r) for r in rows])):
            return h.spot_match(times,[],carry)

    def test_no_future_observation_used(self):
        matched,_,_=self.match([5,10,15,21],[[record(10,seq=10),record(20,seq=20)]])
        self.assertEqual([m['timestamp_us'] if m else None for m in matched],[None,10,10,20])

    def test_duplicates_at_batch_boundary_use_final_sequence(self):
        matched,_,_=self.match([10,15,20],[[record(10,seq=1)],[record(10,seq=2),record(20,seq=3)]])
        self.assertEqual([m['source_sequence'] for m in matched],[2,2,3])

    def test_prior_day_carry_is_preserved(self):
        matched,carry,n=self.match([1,20],[[record(10),record(30,seq=2)]],record(-1))
        self.assertEqual(matched[0]['timestamp_us'],-1);self.assertEqual(carry['timestamp_us'],30);self.assertEqual(n,2)

    def test_no_spot_does_not_fabricate(self):
        m,_,_=self.match([10],[]);self.assertEqual(m,[None])

    def test_every_future_record_including_equal_times_gets_match(self):
        m,_,_=self.match([10,10,10],[[record(9),record(11,seq=2)]])
        self.assertEqual(len(m),3);self.assertTrue(all(x['timestamp_us']==9 for x in m))

    def test_unsorted_future_queries_rejected(self):
        with self.assertRaises(ValueError):self.match([20,10],[])


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.t=h.timestamp('2026-06-07T12:00:00Z')
        self.rates=h.Rates(ROOT)
        self.f=record(self.t,'101','BTC-TEST')
        self.s=record(self.t-1_000_000,'100')
        self.exp=self.t+30*h.DAY_US

    def test_formula_uses_unrounded_prices_and_original_usd_rate(self):
        row,reason=h.calculate(self.f,self.s,self.exp,self.rates,1_000_000)
        self.assertIsNone(reason);self.assertAlmostEqual(row['premium_fraction'],.01)
        self.assertAlmostEqual(row['lease_fraction'],row['usd_rate_fraction']-.01*365/30)
        self.assertEqual(row['future_price_source'],'101');self.assertEqual(row['spot_price_source'],'100')
        parts=json.loads(row['treasury_components']);self.assertAlmostEqual(sum(p['interpolation_weight'] for p in parts),1)
        self.assertTrue(all(h.timestamp(p['available_at_utc'])<=self.t for p in parts))

    def test_strict_gap_boundary(self):
        self.assertIsNotNone(h.calculate(self.f,self.s,self.exp,self.rates,1_000_000)[0])
        self.assertEqual(h.calculate(self.f,self.s,self.exp,self.rates,999_999)[1],'spot_gap_exceeded')

    def test_future_spot_rejected(self):
        self.s['timestamp_us']=self.t+1
        with self.assertRaises(ValueError):h.calculate(self.f,self.s,self.exp,self.rates,1_000_000)

    def test_negative_lease_kept(self):
        r,_=h.calculate(self.f,self.s,self.exp,self.rates,1_000_000);self.assertLess(r['lease_pct'],0)

    def test_expired_contract_excluded(self):
        self.assertEqual(h.calculate(self.f,self.s,self.t,self.rates,1_000_000)[1],'expired')

    def test_block_trade_not_quote_evidence(self):
        self.f['flags']=1
        self.assertEqual(h.calculate(self.f,self.s,self.exp,self.rates,1_000_000)[1],'block_or_combo')

    def test_missing_spot(self):
        self.assertEqual(h.calculate(self.f,None,self.exp,self.rates,1_000_000)[1],'no_previous_spot')

    def test_wrong_currency_rejected(self):
        self.s['quote_currency']='EUR'
        with self.assertRaises(ValueError):h.calculate(self.f,self.s,self.exp,self.rates,1_000_000)

    def test_subsecond_expiry_maturity_preserved(self):
        r,_=h.calculate(self.f,self.s,self.t+500_000,self.rates,1_000_000)
        self.assertEqual(r['maturity_days'],.5/86400)

    def test_treasury_maturity_weights(self):
        r,_=h.calculate(self.f,self.s,self.t+150*h.DAY_US,self.rates,1_000_000)
        self.assertEqual(len(json.loads(r['treasury_components'])),2)

    def test_input_path_cannot_read_results_or_escape_market(self):
        inp=h.Inputs('local',ROOT)
        for name in ['jobs/private/result.json.gz','btc/trades/v1/'+'0'*64+'/../secret']:
            with self.assertRaises(ValueError):inp.fetch(name,'0'*64,'not-written')

if __name__=='__main__':unittest.main()
