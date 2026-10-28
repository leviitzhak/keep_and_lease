"""Semantic tests; these do not launch the 500-update research campaign."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from research.post_decision_value.engine import Instruction
from research.post_decision_value.robust_rollout import CampaignBudget, digest
from research.post_decision_value.treasury_fixtures import DAY, action_provider, make_cases
from research.post_decision_value.treasury_model import load_scalar
from research.post_decision_value.treasury_small_diagnostic import (
    DEFAULT_CONFIG, FEATURE_NAMES, SmallHistoryValue, collect, encode, load_model,
    read, received_history, save_model, short_fixture, validate_config, verify, write_json)


class SmallTreasuryDiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.config = read(DEFAULT_CONFIG)
        self.case = make_cases('train', self.config)[0]

    def test_four_actual_causal_steps_preserve_purchase_price(self):
        engine = short_fixture(self.case, self.config)
        obs = engine.observe()
        self.assertEqual(len(obs.history), 4)
        self.assertEqual(len({r['time'] for r in obs.history}), 4)
        self.assertTrue(all(r['time'] < r['received'] <= obs.time for r in obs.history))
        self.assertEqual(obs.history[0]['price'], self.case['price'])
        self.assertEqual(obs.market['BILL']['price'], self.case['price'])
        actions, _ = action_provider(self.config)(obs, engine.goal, engine.instruments)
        limits = [o.limit for a in actions for o in a.orders]
        self.assertEqual(len(limits), 3)
        for limit in limits:
            self.assertAlmostEqual(limit, self.case['price'], places=10)
        fs = encode(obs, Instruction(), engine.goal, engine.instruments, 28*DAY)
        self.assertEqual(len(fs), 44)
        self.assertEqual([fs[20+i*6+5] for i in range(4)], [1.]*4)

    def test_truncation_uses_only_latest_four_received_steps(self):
        engine = short_fixture(self.case, self.config)
        obs = engine.observe()
        original = encode(obs, Instruction(), engine.goal, engine.instruments, 28*DAY)
        older = deepcopy(obs.history[0])
        older.update(time=older['time']-1000, received=older['received']-1000,
                     price=500., identifier='older-unselected')
        obs.history.insert(0, older)
        self.assertEqual(original, encode(obs, Instruction(), engine.goal, engine.instruments, 28*DAY))
        future = deepcopy(obs.history[-1])
        future['received'] = obs.time+1
        obs.history.append(future)
        with self.assertRaisesRegex(ValueError, 'future'):
            received_history(obs)

    def test_full_maturity_and_boundary_labels_preserved(self):
        budget = CampaignBudget(self.config['limits'])
        rows = collect([self.case], self.config, budget)
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r['done'] and r['history_steps']==4 for r in rows))
        self.assertTrue(all(r['accounting_balance_error']<=1e-8 for r in rows))
        holds = [r for r in rows if r['kind']=='hold']
        self.assertTrue(all(r['horizon_ms']>=28*DAY for r in holds))
        largest = next(r for r in holds if r['quantity']==60)
        self.assertEqual(sum(f['quantity'] for f in largest['replay']['fills']), 60)
        self.assertFalse(largest['replay']['hidden_terminal']['positions'])
        self.assertGreater(largest['target'], 0)
        self.assertLess(next(r for r in rows if r['kind']=='boundary' and r['quantity']==60)['target'], 0)

    def test_new_checkpoint_restores_and_legacy_loader_rejects(self):
        torch.manual_seed(42)
        model = SmallHistoryValue()
        self.assertEqual(sum(p.numel() for p in model.parameters()), 1705)
        self.assertEqual(model.x_mean.numel(), len(FEATURE_NAMES))
        features = [[0.]*len(FEATURE_NAMES), [0.1]*len(FEATURE_NAMES)]
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory)/'model.pt'
            save_model(checkpoint, model, None, {'fixture': 'unit'})
            restored = load_model(checkpoint, {'fixture': 'unit'})
            np.testing.assert_array_equal(model.predict(features), restored.predict(features))
            with self.assertRaisesRegex(ValueError, 'identity'):
                load_model(checkpoint, {'fixture': 'different'})
            with self.assertRaises(ValueError):
                load_scalar(checkpoint)

    def test_freeze_preserves_objective_and_small_update_limit(self):
        validate_config(self.config)
        wrong = deepcopy(self.config)
        wrong['objective']['lambda'] = 1
        with self.assertRaisesRegex(ValueError, 'objective'):
            validate_config(wrong)
        wrong = deepcopy(self.config)
        wrong['limits']['updates'] = 501
        with self.assertRaisesRegex(ValueError, 'cap'):
            validate_config(wrong)

    def test_verification_rejects_checkpoint_not_frozen_before_test(self):
        model = SmallHistoryValue()
        fixtures = {'train': [self.case]}
        identity = dict(configuration_sha256=digest(self.config), fixtures_sha256=digest(fixtures))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_json(output/'configuration.json', self.config)
            write_json(output/'identity.json', identity)
            write_json(output/'fixtures.json', fixtures)
            write_json(output/'frozen-selection.json', dict(identity=identity, model_sha256=model.fingerprint()))
            save_model(output/'selected-model.pt', model, None, identity)
            features = [[0.]*len(FEATURE_NAMES)]
            write_json(output/'inference-examples.json', dict(features=features, predictions=model.predict(features).tolist()))
            self.assertTrue(verify(output)['verified'])
            with torch.no_grad():
                model.net[0].weight[0, 0] += 0.1
            save_model(output/'selected-model.pt', model, None, identity)
            # Zero-valued inference sample cannot expose this changed weight;
            # exact selected model hash must still reject it.
            with self.assertRaisesRegex(ValueError, 'frozen validation selection'):
                verify(output)


if __name__ == '__main__':
    unittest.main()
