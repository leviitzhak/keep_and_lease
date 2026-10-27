"""Integrity of the bounded learning experiment, independent of whether it passes."""
from datetime import datetime, timezone
import tempfile
import unittest

from research.post_decision_value.checkpoint import DirectoryCheckpoints, save_engine, restore_engine
from research.post_decision_value.engine import Instruction, Order, Trade
from research.post_decision_value.model import labels
from research.post_decision_value.treasury_sanity import collect, engine, scenarios, DAY, CONTINUATION


class TreasurySanityTests(unittest.TestCase):
    def test_whole_outcomes_fit_calendar_splits_and_fixture_ids_do_not_overlap(self):
        ids = set()
        for split, end_year in [('train', 2019), ('validation', 2020), ('test', 2021)]:
            cases = scenarios(split, 64)
            end = datetime(end_year, 1, 1, tzinfo=timezone.utc).timestamp()*1000
            self.assertEqual(cases, scenarios(split, 64))
            self.assertEqual({c['days'] for c in cases}, {28, 91, 182, 364})
            for case in cases:
                self.assertNotIn(case['id'], ids); ids.add(case['id'])
                self.assertLess(case['end'], end)
                self.assertEqual(case['maturity']-case['start'], case['days']*DAY)

    def test_funded_outcomes_are_complete_and_same_continuation(self):
        rows, audit = collect(scenarios('train', 4))
        self.assertEqual(len(rows), 13)  # Four choices x three funded cases, one wait.
        self.assertEqual(len(audit), 16)
        y, continuation = labels(rows)
        self.assertEqual(continuation, CONTINUATION)
        self.assertEqual(y.shape, (13, 5))
        for row in rows:
            self.assertFalse(row['outcome']['failed'])
            self.assertEqual(row['outcome']['growth']['BTC'], 0)
            if row['quantity']:
                self.assertEqual(row['outcome']['holding_status'], 'contractual/projected')
                self.assertEqual(len(row['fills']), 1)
                self.assertEqual(len(row['outcome']['projected_receipts']), 1)
            else:
                self.assertEqual(row['outcome']['utility'], 0)

    def test_predeclared_cases_have_distinct_optimal_actions(self):
        rows, audit = collect(scenarios('validation', 4))
        for category in ('profitable', 'overpriced', 'fee_erased', 'cash_constrained'):
            candidates = [r for r in rows if r['category']==category]
            best = max(candidates, key=lambda r:r['outcome']['utility'])
            self.assertEqual(best['quantity'], 60 if category=='profitable' else 0)
        self.assertEqual(sum(not a['accepted'] for a in audit), 3)

    def test_calendar_length_checkpoint_retains_maturity_receipt_and_delayed_reports(self):
        case = scenarios('test', 1)[0]; case['maturity'] = case['start']+364*DAY
        case['end'] = case['maturity']+2000
        e = engine(case)
        e.submit(Instruction('create', (Order('bill', 'BILL', 25, case['price']),)))
        e.add_tape([Trade(case['start']+1000, 'BILL', case['price']-.01, 1000,
                          'sell', 'fixture', 100000, 'treasury')])
        e.advance(case['start']+182*DAY)
        self.assertFalse(e.outcome()['done'])
        with tempfile.TemporaryDirectory() as directory:
            store = DirectoryCheckpoints(directory)
            save_engine(store, e.now, e, {'case': case})
            resumed = restore_engine(store, {'case': case})
            e.advance(case['end']); resumed.advance(case['end'])
            self.assertEqual(e.outcome(), resumed.outcome())
            self.assertEqual(e.hidden.fills, resumed.hidden.fills)
            self.assertEqual(e.observable.ledger, resumed.observable.ledger)


if __name__ == '__main__': unittest.main()
