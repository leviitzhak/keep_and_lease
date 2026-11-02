"""Scaling checks against independent cashflows and the original small planner."""
import unittest
import numpy as np
from longer_timelines import Market, State, dataset, rollout
from timeline_1024 import ScaledMarket, LazyLabels


class ScalingTests(unittest.TestCase):
    def test_vectorized_planner_matches_original(self):
        for T in [4, 8, 16, 32, 64, 128]:
            np.testing.assert_allclose(ScaledMarket(T).W, Market(T).W, rtol=0, atol=1e-10, equal_nan=True)

    def test_every_1024_planner_entry_against_cashflows(self):
        env = ScaledMarket(1024)
        # Independent optimal policy: buy missing units as early as possible.
        for end in range(1025):
            t = np.arange(end+1)[:, None]; q = np.arange(5)[None, :]
            n = np.minimum(end-t, 4-q); final = q+n
            paid = n*(95+2*t/1024+.25)+(2/1024)*n*(n-1)/2
            proceeds = final*(95+2*(end+.75)/1024+.25)+(2/1024)*final*(final-1)/2
            np.testing.assert_allclose(env.W[end, :end+1], proceeds-paid, rtol=0, atol=1e-10)
        self.assertEqual(env.oracle_edges, 6822400)
        self.assertEqual(env.boundaries, 5125)
        self.assertAlmostEqual(env.exact(env.initial, 1024), 1008.005859375)

    def test_lazy_labels_equal_dense_all_horizons(self):
        env = ScaledMarket(16); rng = np.random.default_rng(21); states = set()
        for _ in range(8): states.update(rollout(env, rng))
        lazy = LazyLabels(env, states); dense = dataset(env, states)
        self.assertEqual(lazy.label_count, len(dense['y']))
        for h in range(17):
            ids = np.arange(lazy.counts[h]); rows = lazy.make(ids, np.full(len(ids), h))
            g = dense['groups'][h]
            np.testing.assert_array_equal(rows['x'], dense['x'][g])
            np.testing.assert_array_equal(rows['y'], dense['y'][g])

    def test_funding_and_closing_tail(self):
        env = ScaledMarket(1024); self.assertEqual(env.cash_lower_bound, 356)
        s = env.initial
        for t in range(1024):
            s = env.step(s, 1 if t%2 == 0 else -1)
            self.assertGreaterEqual(s.cash_ticks/env.scale, env.cash_lower_bound)
        for q in range(5):
            s = State(1024, 600*env.scale, q)
            expected = 600+sum(95+2*(1024+j+.75)/1024+.25 for j in range(q))
            self.assertAlmostEqual(env.close(s), expected)

    def test_split_identity_and_uniform_horizon_sampler(self):
        env = ScaledMarket(32); rng = np.random.default_rng(12); states = set()
        for _ in range(16): states.update(rollout(env, rng))
        groups = {split: {s for s in states if env.split(s) == split} for split in ['train','validation','test']}
        self.assertTrue(groups['train'].isdisjoint(groups['validation']|groups['test']))
        lazy = LazyLabels(env, groups['train']); rows = lazy.sample(rng, 33000)
        counts = np.bincount(rows['h'], minlength=33)
        self.assertTrue(np.all((counts > 850) & (counts < 1150)))
        self.assertTrue(all(env.split(lazy.states[i]) == 'train' for i in rows['ids']))


if __name__ == '__main__': unittest.main()
