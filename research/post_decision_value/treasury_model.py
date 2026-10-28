"""Versioned Treasury-only scalar ablation; legacy Transformer is unchanged."""
import hashlib
import time

import numpy as np
import torch
from torch import nn

from .engine import post_decision
from .robust_rollout import TARGET_VERSION

FEATURE_VERSION = 'treasury-observable-v1'
DIAGNOSTIC_VERSION = 'diagnostic-hold-boundary-v1'
DAY = 86400000
FEATURE_NAMES = ('usd_growth', 'btc_growth', 'free_usd_fraction', 'inventory',
                 'pending_buy', 'pending_sell', 'pending_buy_price', 'pending_sell_price',
                 'received_price', 'fee_bps', 'remaining_days', 'maturity_days',
                 'crosses_maturity', 'boundary', 'pending_requests', 'cancel_pending',
                 'history_age_days', 'failure_observed', 'inventory_cost', 'usd_scale')


def encode(obs, action, goal, instruments, horizon):
    if set(instruments) != {'BILL'} or instruments['BILL'].payoff != 'treasury':
        raise ValueError('Treasury scalar encoder supports one BILL only')
    if goal.mode != 'weighted_growth' or goal.growth_weights != {'BTC': .5, 'USD': .5} or goal.loss_aversion != 10:
        raise ValueError('Unsupported objective for Treasury v1')
    if (goal.initial != {'BTC':1., 'USD':10000.} or goal.drawdown != .1 or
            goal.failure_penalty != 1. or goal.reference != {'BTC':100000., 'USD':1.} or
            goal.scales or goal.absolute_floors or obs.ledger.flows or obs.ledger.debt_principal):
        raise ValueError('Unsupported benchmark, constraints or liabilities for Treasury v1')
    x = post_decision(obs, action, instruments)
    ins = instruments['BILL']
    pos = x.ledger.positions.get('BILL')
    orders = [variants[-1] for variants in x.uncertain.values()]
    buy = [o for o in orders if o.quantity > 0]
    sell = [o for o in orders if o.quantity < 0]
    price = x.market['BILL']['price']
    bp = sum(o.quantity*o.limit for o in buy)/max(1., sum(o.quantity for o in buy)) if buy else 100.
    sp = sum(-o.quantity*o.limit for o in sell)/max(1., sum(-o.quantity for o in sell)) if sell else 100.
    maturity = max(0, ins.expiry-x.time)
    return [(x.ledger.balances['USD']/goal.scale('USD')-1)*100,
            (x.ledger.balances['BTC']/goal.scale('BTC')-1)*100,
            (x.ledger.balances['USD']-x.ledger.collateral['USD']-x.reserved['USD'])/goal.scale('USD'),
            (pos.quantity if pos else 0)/60,
            sum(o.quantity for o in buy)/60, sum(-o.quantity for o in sell)/60,
            (bp-100)/5, (sp-100)/5, (price-100)/5, ins.fee_bps/100,
            horizon/(28*DAY), maturity/(28*DAY), float(horizon >= maturity), float(horizon == 0),
            len(x.pending)/3, float(any(p['instruction']['kind'] in ('cancel', 'emergency') for p in x.pending)),
            min(2., (x.time-x.market['BILL']['received'])/(28*DAY)), float(x.failure_observed),
            ((pos.basis-100)/5 if pos else 0.), goal.scale('USD')/10000]


class TreasuryValue(nn.Module):
    def __init__(self, width=48):
        super().__init__()
        self.width = width
        self.net = nn.Sequential(nn.Linear(len(FEATURE_NAMES), width), nn.SiLU(),
                                 nn.Linear(width, width), nn.SiLU(), nn.Linear(width, 1))
        self.register_buffer('x_mean', torch.zeros(len(FEATURE_NAMES)))
        self.register_buffer('x_scale', torch.ones(len(FEATURE_NAMES)))
        self.register_buffer('y_mean', torch.tensor(0.))
        self.register_buffer('y_scale', torch.tensor(1.))
        self.identity = {}
        self.target_version = 'unfitted'
        self.label_identity = 'unfitted'

    def forward(self, x):
        return self.net((x-self.x_mean)/self.x_scale).squeeze(-1)

    def predict(self, fs):
        self.eval()
        with torch.no_grad():
            return (self(torch.tensor(fs, dtype=torch.float32))*self.y_scale+self.y_mean).numpy()

    def fingerprint(self):
        h = hashlib.sha256()
        for key, value in self.state_dict().items():
            h.update(key.encode()); h.update(value.detach().numpy().tobytes())
        return h.hexdigest()


def tensors(rows):
    if not rows or any(not r['done'] or r['target'] is None for r in rows):
        raise ValueError('Only complete max-min outcomes may be fitted')
    versions = {r['target_version'] for r in rows}
    if len({r['identity'] for r in rows}) != 1 or len(versions) != 1 or not versions <= {TARGET_VERSION, DIAGNOSTIC_VERSION}:
        raise ValueError('Mixed or legacy target identities')
    x = torch.tensor([r['features'] for r in rows], dtype=torch.float32)
    y = torch.tensor([r['target'] for r in rows], dtype=torch.float32)
    if not torch.isfinite(x).all() or not torch.isfinite(y).all():
        raise ValueError('Nonfinite features or labels')
    return x, y


def error(model, rows):
    x, y = tensors(rows)
    with torch.no_grad():
        predicted = model(x)*model.y_scale+model.y_mean
        residual = predicted-y
        return dict(loss=float(((residual/model.y_scale)**2).mean()),
                    mae=float(residual.abs().mean()), max_error=float(residual.abs().max()))


def fit_scalar(model, train, validation, updates, budget, *, optimizer=None,
               normalize=True, learning_rate=.003, callback=None):
    with budget.fitting():
        return _fit_scalar(model, train, validation, updates, budget, optimizer=optimizer,
                           normalize=normalize, learning_rate=learning_rate, callback=callback)


def _fit_scalar(model, train, validation, updates, budget, *, optimizer=None,
                normalize=True, learning_rate=.003, callback=None):
    x, y = tensors(train)
    if any(r['target_version'] != train[0]['target_version'] or r['identity'] != train[0]['identity'] for r in validation):
        raise ValueError('Validation must match the frozen training continuation')
    model.target_version = train[0]['target_version']
    model.label_identity = train[0]['identity']
    if normalize:
        model.x_mean.copy_(x.mean(0))
        # Stable unit scales for train-constant dimensions, never future moments.
        scale = x.std(0, unbiased=False)
        model.x_scale.copy_(torch.where(scale > .01, scale, torch.ones_like(scale)))
        model.y_mean.copy_(y.mean()); model.y_scale.copy_(y.std(unbiased=False).clamp_min(.001))
    target = (y-model.y_mean)/model.y_scale
    optimizer = optimizer or torch.optim.Adam(model.parameters(), lr=learning_rate)
    curve = []
    best = None
    best_loss = float('inf')
    for step in range(updates):
        budget.fit_check()
        optimizer.zero_grad()
        model.train()
        prediction = model(x)
        loss = ((prediction-target)**2).mean()
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite scalar regression')
        loss.backward()
        gradient = float(nn.utils.clip_grad_norm_(model.parameters(), 5.))
        optimizer.step()
        budget.updates += 1
        if (step+1) % 25 == 0 or step+1 == updates:
            tr, va = error(model, train), error(model, validation)
            with torch.no_grad():
                hidden = model.net[:2]((x-model.x_mean)/model.x_scale)
            curve.append(dict(updates=budget.updates, train=tr, validation=va,
                              gradient_norm=gradient, hidden_abs_max=float(hidden.abs().max()),
                              activation='SiLU', saturation_fraction=None))
            if va['loss'] < best_loss:
                import copy
                best_loss = va['loss']
                best = dict(state=copy.deepcopy(model.state_dict()),
                            optimizer=copy.deepcopy(optimizer.state_dict()),
                            torch_rng=torch.get_rng_state().clone(),updates=budget.updates)
            if callback:
                callback(model, optimizer, curve[-1])
    return optimizer, curve, best


def save_scalar(path, model, optimizer, identity):
    torch.save(dict(schema='treasury-scalar-checkpoint-v1', feature_version=FEATURE_VERSION,
                    target_version=model.target_version, label_identity=model.label_identity,
                    width=model.width, state=model.state_dict(),
                    optimizer=optimizer.state_dict() if optimizer else None,
                    torch_rng=torch.get_rng_state(), identity=identity), path)


def load_scalar(path, expected_identity=None):
    p = torch.load(path, map_location='cpu', weights_only=True)
    if p['schema'] != 'treasury-scalar-checkpoint-v1' or p['feature_version'] != FEATURE_VERSION or p['target_version'] not in (TARGET_VERSION, DIAGNOSTIC_VERSION, 'unfitted'):
        raise ValueError('Incompatible Treasury checkpoint semantics')
    if expected_identity is not None and p['identity'] != expected_identity:
        raise ValueError('Checkpoint identity mismatch')
    model = TreasuryValue(p['width']); model.load_state_dict(p['state']); model.identity = p['identity']
    model.target_version = p['target_version']; model.label_identity = p.get('label_identity','unspecified')
    optimizer = torch.optim.Adam(model.parameters(), lr=.003)
    if p['optimizer'] is not None:
        optimizer.load_state_dict(p['optimizer'])
    torch.set_rng_state(p['torch_rng'])
    return model, optimizer, p['identity']
