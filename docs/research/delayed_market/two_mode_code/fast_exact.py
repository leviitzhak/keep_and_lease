"""Full-history, algorithm-preserving engineering for horizon experiments.

Only cloning and training audit retention change. No observations, candidates,
labels, RNG draws, neural equations, or optimizer operations are shortened.
Histories/queue payloads are append-only or read-only in this simulator and are
shared across clones; mutable order states, RNGs, and container tops are copied.
"""
import copy
import search

class FastPathSimulator(search.PathSimulator):
    def clone(self):
        c = copy.copy(self)
        for name in ['queue', 'state_history', 'market_history', 'private_history',
                     'command_history', 'delay_draws', 'prefix', 'audit', 'snapshots']:
            if hasattr(self,name): setattr(c,name,list(getattr(self,name)))
        c.rng = {k:copy.deepcopy(v) for k,v in self.rng.items()}
        c.exchange_orders = {k:copy.copy(v) for k,v in self.exchange_orders.items()}
        c.known_orders = {k:dict(v) for k,v in self.known_orders.items()}
        for name in ['pending_create','pending_cancel','latest_market','overrides']:
            setattr(c,name,copy.deepcopy(getattr(self,name)))
        c.decisions = set(self.decisions)
        return c

def assert_same(a,b):
    assert a.__dict__.keys()==b.__dict__.keys()
    for k in a.__dict__:
        if k=='rng':
            assert all(a.rng[c].getstate()==b.rng[c].getstate() for c in a.rng), k
        else: assert a.__dict__[k]==b.__dict__[k], k
