"""User-visible funded transfer audit, with no fabricated legacy pairings."""
import io
import json
import unittest
import zipfile
from xml.etree import ElementTree as ET

from backtest_audit import AuditCollection, MemoryAuditStore
from server.replay_exports import replay_workbook


START = '2026-06-25T00:00:00.000000'
END = '2026-06-25T00:00:10.000000'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def exported(events, *, paired=True):
    store = MemoryAuditStore()
    audit = AuditCollection(store)
    audit.writer('btc_trade_valuations').emit(dict(
        date=END, nav_usd=105, cash_usd=40, direct_btc_value_usd=60,
        unsettled_pnl_usd=5, free_cash_usd=10, posted_cash_usd=30,
        pending_variation_usd=0, reserved_cash_usd=3, available_cash_usd=7,
        commodity_nav_btc=1.05, treasury_value_usd=0, liabilities_usd=0,
        units={'SPOT': .6, 'F': .3}, targets=None, starting_nav=1,
        mark_us={'SPOT': 0, 'F': 0}, mark_ids={'SPOT': 's', 'F': 'f'},
        direct_nav=1, fees_usd=2, return_fraction=.05,
        reconstruction_error_usd=0, futures_notional_usd=30))
    for row in events:
        audit.writer('btc_trade_events').emit(row)
    manifest = audit.finish()
    result = dict(parameters={'trade_strategy': 'cost_aware_paired'} if paired else {},
                  trade_replay={'capital_usd': 100, 'end_mark_age_seconds': {'F': 0}},
                  summary={'start': START, 'end': END})
    data = b''.join(replay_workbook(store, manifest, result, START, END))
    output = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        self_test = archive.testzip()
        if self_test is not None:
            raise AssertionError(self_test)
        names = [s.attrib['name'] for s in ET.fromstring(archive.read('xl/workbook.xml')).findall('m:sheets/m:sheet', NS)]
        for index, name in enumerate(names, 1):
            sheet = ET.fromstring(archive.read(f'xl/worksheets/sheet{index}.xml'))
            rows = []
            for row in sheet.findall('m:sheetData/m:row', NS):
                values = []
                for cell in row.findall('m:c', NS):
                    text = cell.find('m:is/m:t', NS)
                    number = cell.find('m:v', NS)
                    values.append(text.text if text is not None else float(number.text) if number is not None else None)
                rows.append(values)
            output[name] = [dict(zip(rows[0], row)) for row in rows[1:]]
    return output


def decision(accepted=True):
    return dict(accepted=accepted, reason='net_gain_exceeds_buffer' if accepted else 'keep_net_gain_below_buffer',
                source_symbol='SPOT', target_symbol='F', source_quantity_btc=.3,
                target_quantity_btc=.29, source_cash_usd=0, entry_cost_usd=.1,
                horizon_us=86400_000_000, keep_btc=.3, swap_btc=.31,
                edge_btc=.01, required_edge_btc=.001, source_fraction=.25,
                diagnostics=dict(initial_capital_usd=30, cash_reserve_usd=.5,
                                 source_sale_limit=99, target_buy_limit=101,
                                 keep={'interest_usd': 0, 'funding_feasible': True},
                                 swap={'interest_usd': .2, 'funding_feasible': True},
                                 alternatives=[dict(source_fraction=.125, horizon_us=3600_000_000,
                                                    keep_btc=.15, swap_btc=.149, edge_btc=-.001,
                                                    required_edge_btc=.0005, reason='keep_net_gain_below_buffer'),
                                               dict(source_fraction=.25, horizon_us=86400_000_000,
                                                    keep_btc=.3, swap_btc=.31, edge_btc=.01,
                                                    required_edge_btc=.001, reason='net_gain_exceeds_buffer')]))


class PairedExportTests(unittest.TestCase):
    def test_keep_forecasts_failed_pairs_funding_and_exact_raw_evidence_are_visible(self):
        frozen = decision()
        events = [
            dict(date=START, kind='paired_decision', decision_id='decision-1', selected=False,
                 decision=decision(False)),
            dict(date=START, kind='paired_decision', decision_id='decision-2', selected=True,
                 pair_id='pair-1', decision=frozen),
            dict(date=START, kind='paired_transfer', pair_id='pair-1', status='pending',
                 source_symbol='SPOT', target_symbol='F', source_quantity_btc=.3,
                 target_quantity_btc=.29, decision=frozen),
            dict(date='2026-06-25T00:00:01.000000', kind='fill', pair_id='pair-1',
                 role='source', signed_btc=-.1, price=99, fee_usd=.1,
                 reserved_usd=9.8, unpaired_btc=.1, trade_id='12345678901234567890'),
            dict(date=END, kind='paired_transfer_result', pair_id='pair-1', status='timed_out',
                 reason='legging_timeout', source_filled_btc=.1, target_filled_btc=0,
                 matched_source_btc=0, unpaired_btc=.1, fees_usd=.1, reserved_usd=9.8,
                 max_unpaired_btc=.1, max_legging_seconds=9, decision=frozen),
        ]
        sheets = exported(events)
        self.assertEqual(sheets['Valuations'][0]['Direct BTC value USD'], 60)
        self.assertEqual(sheets['Valuations'][0]['unsettled_pnl_usd'], 5)
        self.assertEqual(sheets['Valuations'][0]['reserved_cash_usd'], 3)
        self.assertEqual(sheets['Transfer decisions'][0]['accepted'], 'False')
        selected = sheets['Transfer decisions'][1]
        self.assertEqual(selected['keep_btc'], .3)
        self.assertEqual(selected['swap_btc'], .31)
        self.assertEqual(selected['horizon_us'], 86400_000_000)
        self.assertEqual(selected['diagnostics.cash_reserve_usd'], .5)
        self.assertEqual(len(sheets['Horizon alternatives']), 4)
        self.assertEqual(sheets['Horizon alternatives'][0]['reason'], 'keep_net_gain_below_buffer')
        failed = sheets['Paired transfers'][-1]
        self.assertEqual(failed['status'], 'timed_out')
        self.assertEqual(failed['unpaired_btc'], .1)
        self.assertEqual(failed['target_filled_btc'], 0)
        self.assertEqual(failed['reserved_usd'], 9.8)
        for expected, actual in zip(events, sheets['Events']):
            self.assertEqual(json.loads(actual['Complete event record']), expected)
        self.assertEqual(sheets['Events'][3]['trade_id'], '12345678901234567890')
        self.assertEqual(sheets['Events'][3]['pair_id'], 'pair-1')

    def test_legacy_fills_remain_unpaired_and_events_outside_period_are_excluded(self):
        events = [dict(date=START, kind='fill', symbol='SPOT', signed_btc=-.3, price=100),
                  dict(date=START, kind='fill', symbol='F', signed_btc=.3, price=100),
                  dict(date='2026-06-25T00:00:11.000000', kind='fill', symbol='SPOT', signed_btc=.1)]
        sheets = exported(events, paired=False)
        self.assertEqual(list(sheets), ['Overview', 'Valuations', 'Events', 'Parameters'])
        self.assertEqual(len(sheets['Events']), 2)
        for row in sheets['Events']:
            self.assertNotIn('pair_id', row)
            self.assertNotIn('pair_id', json.loads(row['Complete event record']))

    def test_missing_stored_pair_or_funding_fields_are_blank_not_invented(self):
        sheets = exported([dict(date=START, kind='fill', symbol='SPOT', signed_btc=-.3)])
        self.assertIsNone(sheets['Events'][0]['pair_id'])
        self.assertIsNone(sheets['Events'][0]['reserved_usd'])
        self.assertEqual(sheets['Paired transfers'], [])
        self.assertEqual(sheets['Transfer decisions'], [])


if __name__ == '__main__':
    unittest.main()
