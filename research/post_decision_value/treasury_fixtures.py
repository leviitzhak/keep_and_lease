"""Tiny declared Treasury tapes; dates are coordinates, never historical data."""
from dataclasses import asdict
from datetime import datetime, timezone
import random

from .accounting import Goal, Instrument, Ledger
from .decision_clock import DecisionSchedule
from .engine import Delays, Engine, Instruction, Order, Trade, admissible
from .robust_rollout import digest

DAY = 86400000
CATEGORIES = ('profitable', 'overpriced', 'fee_erased', 'cash_constrained')


def make_cases(split, config):
    rng = random.Random(config['splits'][split]['seed'])
    year = config['splits'][split]['year']
    base = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp()*1000)+10000
    cases = []
    for n in range(config['splits'][split]['count']):
        category = CATEGORIES[n % 4]
        price = round(rng.uniform(96.5, 98.5), 2)
        fee = rng.choice([0., 5., 10.])
        if category == 'overpriced':
            price = round(rng.uniform(100.3, 101.5), 2)
        if category == 'fee_erased':
            price, fee = round(rng.uniform(99.88, 99.97), 2), 60.
        start = base+n*35*DAY
        maturity = start+28*DAY
        cases.append(dict(id=f'treasury-maxmin-v1-{split}-{n}', split=split, category=category,
                          start=start, maturity=maturity, decision_end=maturity+2000,
                          label_end=maturity+2000+config['closing']['tail_ms'],
                          price=price, fee_bps=fee, usd=10000., seed=rng.randrange(2**30)))
    return cases


def fixture_engine(case, config):
    ins = Instrument('BILL', case['maturity'], payoff='treasury', source_payoff='treasury',
                     tick=.01, lot=1, fee_bps=case['fee_bps'],
                     cashflows=((case['maturity'], 100.),), listed_at=case['start']-DAY)
    initial = dict(BTC=1., USD=case['usd'])
    ledger = Ledger(initial.copy())
    if case['category'] == 'cash_constrained':
        ledger.pledge('USD', case['usd']-1)
    goal = Goal(initial, case['decision_end'], case['label_end'], mode='weighted_growth')
    e = Engine({'BILL': ins}, ledger, goal, case['seed'], Delays(**config['delays']),
               participation=1., event_cap=config['limits']['events_per_replay'])
    e.seed_market([Trade(case['start']-1000, 'BILL', case['price'], 1000., 'buy',
                        'seed', 100000., 'treasury')], case['start'])
    return e


def scenario_set(case, seeds, config, tag):
    result = []
    for k, seed in enumerate(seeds):
        # Identical market tape across K: ONLY future message/report jitter is
        # reseeded. This deliberately does not pretend to sample market returns.
        tape = [Trade(case['start']+1000, 'BILL', case['price']-.01, 30., 'sell',
                      'entry-partial', 100000., 'treasury'),
                Trade(case['start']+DAY, 'BILL', case['price']-.01, 60., 'sell',
                      'entry-second', 100000., 'treasury')]
        # Daily bids provide bounded, split-contained closing support, without
        # manufacturing quotes. They can also fill a posted strategic sale.
        tape += [Trade(case['start']+d*DAY+2000, 'BILL', case['price']-.20, 1000.,
                       'buy', f'close-{d}', 100000., 'treasury') for d in range(29)]
        tape.sort(key=lambda tr: (tr.time, tr.identifier))
        result.append(dict(id=f'{case["id"]}:{tag}:{seed}', seed=seed, trades=tape,
                           decision_end=case['decision_end'], label_end=case['label_end'],
                           tape_sha256=digest([asdict(t) for t in tape]),
                           law=config['scenario_law']))
    return result


def action_provider(config):
    def actions(obs, goal, instruments):
        ins = instruments['BILL']
        candidates = [Instruction()]
        ids = tuple(sorted(obs.uncertain))
        if ids:
            candidates.append(Instruction('cancel', targets=ids))
        else:
            pos = obs.ledger.positions.get('BILL')
            owned = pos.quantity if pos else 0.
            for q in config['quantities']:
                if owned+q <= config['inventory_cap']:
                    for offset in config['price_offsets']:
                        price = ins.round_price(obs.history[0]['price']+offset, 1)
                        candidates.append(Instruction('create', (Order(f'bill-{obs.submitted}', 'BILL', q, price, created=obs.time),)))
        accepted, audit = [], []
        for a in candidates:
            ok, reason = admissible(obs, a, goal, instruments)
            audit.append(dict(instruction=a.payload(), accepted=ok, reason=reason))
            if ok:
                accepted.append(a)
        if not accepted or obs.failure_observed:
            accepted = [Instruction('emergency', targets=ids)]
        return accepted, audit
    return actions


def accept_anchor(e, action, config):
    e.submit(action)
    schedule = DecisionSchedule(e, e.goal.horizon, mode=config['clock']['mode'],
                                cadence_ms=config['clock']['cadence_ms'],
                                trigger=config['clock']['trigger'])
    schedule.accept()
    return e


def hold_reference(case, quantity, horizon, *, inventory=False):
    """Independent cash arithmetic, no ledger/engine/liquidator/model calls.

    Support: initial fixture, posted price equals seed price, then hold; or an
    already owned quantity bought at that price. The two prints supply 30+60
    units. Closing sells at the first subsequent daily bid, or redeems once.
    """
    if horizon < 0:
        raise ValueError('Unsupported reference horizon')
    q = quantity if inventory else min(quantity, (30 if horizon >= 1000 else 0) + (60 if horizon >= DAY else 0))
    paid = q*case['price']*(1+case['fee_bps']/10000)
    matured = horizon >= 28*DAY
    proceeds = q*(100 if matured else (case['price']-.20)*(1-case['fee_bps']/10000))
    usd = case['usd']-paid+proceeds
    growth = (usd-case['usd'])/case['usd']
    utility = .5*max(0., growth)-10*max(0., -growth)
    return dict(utility=utility, balances=dict(BTC=1., USD=usd), quantity=q,
                growth=dict(BTC=0., USD=growth), failed=False)


def finite_toy_optimum(case, horizon, config, budget):
    """Enumerate all causal two-opportunity quantity controllers in this toy.

    First observable history is common to K. First capacity is always 30 and
    reports arrive before the second opportunity, so its received fill is a
    sufficient observation. A controller chooses q1 then q2 conditional on that
    fill. Unchosen information-set entries cannot change its value. No adversary
    is reselected at the second stage: every controller is scored on full paths.

    Scope excludes off-grid limits, selling, amendments and other market laws.
    Fixed posted limit is the initial price; no orders can fill after day 1.
    The sampled collector has the same purchase/cancel domain; cancellation can
    only reduce these fills. With constant entry cost and exit below entry, no
    intermediate policy can improve on the enumerated endpoints (0 or 60 units).
    """
    candidates = []
    qs = [0] if case['category'] == 'cash_constrained' else [0]+config['quantities']
    for q1 in qs:
        filled1 = min(q1, 30) if horizon >= 1000 else 0
        for q2 in qs:
            budget.oracle()
            # Outstanding q1 is retained; q2 can be posted only if it is filled.
            if q1 > filled1 and q2:
                continue
            if filled1+q2 > config['inventory_cap']:
                continue
            total = filled1
            if horizon >= DAY:
                total += min(60, q1-filled1+q2)
            value = hold_reference(case, total, horizon, inventory=True)
            candidates.append(dict(q1=q1, q2_after_received_fill=q2, **value))
    # At H=0 no decisions/fills; at very short horizons there is no receipt.
    best = max(candidates, key=lambda c: c['utility'])
    return dict(value=best['utility'], witness=best, controllers=candidates,
                scope='two fixed-price purchase opportunities, constant cost, 60-unit cap; full declared delay support',
                exact=True)


def replay_reference(case, branch):
    """Recompute a complete fixture outcome from signed fills and dated terms.

    Independent of Engine/Ledger/Goal/liquidate. This audits the SAME realized
    causal controller, rather than optimizing its decisions with future prices.
    """
    outcome = branch['outcome']
    if not outcome['done']:
        return None
    fee = case['fee_bps']/10000
    usd, quantity = case['usd'], 0.
    for fill in branch['fills']:
        q, price = fill['quantity'], fill['price']
        usd -= q*price+abs(q*price)*fee
        quantity += q
    # A strategic maturity payment occurs once, before the endpoint. Future
    # tail receipts are represented separately and cannot pay sold quantities.
    if branch['endpoint'] >= case['maturity']:
        usd += quantity*100; quantity = 0.
    for event in outcome['trace']:
        if event['kind'] == 'contractual_receipt':
            usd += quantity*100; quantity = 0.
        elif event['kind'] == 'print' and event['quantity']:
            q, price = event['quantity'], event['price']
            usd -= q*price+abs(q*price)*fee
            quantity += q
    if abs(quantity) > 1e-9:
        raise AssertionError('Reference inventory unresolved')
    g = (usd-case['usd'])/case['usd']
    utility = .5*max(0.,g)-10*max(0.,-g)-float(outcome['failed'])
    return dict(utility=utility, balances=dict(BTC=1.,USD=usd),growth=dict(BTC=0.,USD=g))
