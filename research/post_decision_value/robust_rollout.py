"""Nonrecursive, complete-path sampled max-min collection.

The model/encoder/action provider consume ObservableState only. Hidden queues
are copied solely by the simulator driver. A controller's RNG is independent of
scenario randomness and is restarted identically in each uncertainty replica.
"""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import random
import time

from .decision_clock import DecisionSchedule
from .engine import Instruction
from .liquidation import ClosingRule, horizon_support, liquidate

TARGET_VERSION = 'sampled-maxmin-sequential-close-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class CampaignBudget:
    """One shared ledger for diagnostics, every branch, refits and evaluation."""
    def __init__(self, config):
        ceilings = dict(wall_seconds=240, fit_seconds=120, updates=1200,
                        decisions=20000, events_per_replay=30000,
                        input_rows=100000, compressed_bytes=8000000,
                        oracle_controllers=4096)
        if set(config) != set(ceilings) or any(not 0 < config[k] <= v for k, v in ceilings.items()):
            raise ValueError('Campaign limits must respect all research ceilings')
        self.limits = dict(config)
        self.started = time.monotonic()
        self.cpu_started = time.process_time()
        self.decisions = self.events = self.updates = self.oracle_controllers = 0
        self.fit_seconds = 0.
        self.fit_started = None
        self.inputs = {}

    def check(self):
        if time.monotonic() - self.started >= self.limits['wall_seconds']:
            raise RuntimeError('campaign_wall_cap')

    def decision(self):
        self.check()
        if self.decisions >= self.limits['decisions']:
            raise RuntimeError('campaign_decision_cap')
        self.decisions += 1

    def event(self, count=1):
        self.events += count
        self.check()

    def oracle(self):
        self.check()
        if self.oracle_controllers >= self.limits['oracle_controllers']:
            raise RuntimeError('oracle_enumeration_cap')
        self.oracle_controllers += 1

    def fit_check(self):
        self.check()
        elapsed = 0. if self.fit_started is None else time.monotonic()-self.fit_started
        if self.updates >= self.limits['updates'] or self.fit_seconds+elapsed >= self.limits['fit_seconds']:
            raise RuntimeError('campaign_fit_cap')

    @contextmanager
    def fitting(self):
        if self.fit_started is not None: raise ValueError('Nested fit phase')
        self.fit_check()
        self.fit_started = time.monotonic()
        try:
            yield
        finally:
            # Include normalization, validation metrics and checkpoint I/O,
            # even when a cap or failed gate interrupts the fit.
            self.fit_seconds += time.monotonic()-self.fit_started
            self.fit_started = None
            if self.fit_seconds > self.limits['fit_seconds']:
                raise RuntimeError('campaign_fit_cap')
            self.check()

    def summary(self):
        return dict(wall_seconds=time.monotonic()-self.started,
                    cpu_seconds=time.process_time()-self.cpu_started,
                    fitting_seconds=self.fit_seconds, optimizer_updates=self.updates,
                    decisions=self.decisions, exchange_report_closing_events=self.events,
                    oracle_controllers=self.oracle_controllers,
                    unique_input_rows=sum(v['rows'] for v in self.inputs.values()),
                    compressed_input_bytes=sum(v['bytes'] for v in self.inputs.values()))

    def input(self, scenario):
        import gzip
        payload = json.dumps([asdict(t) for t in scenario['trades']], sort_keys=True).encode()
        key = hashlib.sha256(payload).hexdigest()
        self.inputs[key] = dict(rows=len(scenario['trades']), bytes=len(gzip.compress(payload,mtime=0)))
        if sum(v['rows'] for v in self.inputs.values()) > self.limits['input_rows'] or sum(v['bytes'] for v in self.inputs.values()) > self.limits['compressed_bytes']:
            raise RuntimeError('campaign_input_cap')


@dataclass(frozen=True)
class Controller:
    seed: int
    epsilon: float = 0.

    def __post_init__(self):
        if not 0 <= self.epsilon <= 1:
            raise ValueError('Invalid controller exploration')


def reduce_matrix(outcomes):
    if not outcomes or not outcomes[0] or len({len(r) for r in outcomes}) != 1:
        raise ValueError('Equal nonzero K required for every controller')
    if any(not o.get('done') or o.get('truncated') for row in outcomes for o in row):
        return dict(done=False, target=None, reason='incomplete_replica', winner=None, worst=None)
    matrix = [[o['utility'] for o in row] for row in outcomes]
    minima = [min(row) for row in matrix]
    winner = max(range(len(minima)), key=lambda j: minima[j])
    worst = min(range(len(matrix[winner])), key=lambda k: matrix[winner][k])
    return dict(done=True, target=minima[winner], matrix=matrix, minima=minima,
                winner=winner, worst=worst, joint_outcome=outcomes[winner][worst],
                ties=[j for j, v in enumerate(minima) if v == minima[winner]])


def scenario_clone(parent, scenario):
    e = deepcopy(parent)
    e.event_trace = []
    # Preserve already sampled messages/reports and the clock anchor. Only
    # future tape is replaced; delayed observations of past trades survive.
    e.hidden.queue = [v for v in e.hidden.queue if v[3] != 'trade' and
                      not (v[3] == 'observation' and v[4].time > parent.now)]
    import heapq
    heapq.heapify(e.hidden.queue)
    e.seed = scenario['seed']
    e.add_tape([tr for tr in scenario['trades'] if tr.time > parent.now])
    return e


def rollout(parent, horizon, scenario, controller, model, encode, actions, config, budget,
            *, hold=False, retain_anchors=False):
    budget.check()
    budget.input(scenario)
    e = scenario_clone(parent, scenario)
    deadline = parent.now + horizon
    e.goal.horizon = deadline
    # Resolution, original benchmark, target deadline and all floors survive.
    if deadline > e.goal.resolution:
        raise ValueError('Horizon exceeds declared accounting resolution')
    rng = random.Random(controller.seed)
    trace, anchors = [], []
    processed = e.hidden.processed
    e.event_cap = min(e.event_cap, processed + budget.limits['events_per_replay'])
    schedule = DecisionSchedule(e, deadline, mode=config['clock']['mode'],
                                cadence_ms=config['clock']['cadence_ms'],
                                trigger=config['clock']['trigger'], budget=budget)
    charged = False
    try:
        for t, reasons in schedule:
            budget.decision()
            obs = e.observe()
            candidates, admission = actions(obs, e.goal, e.instruments)
            fs = [encode(obs, a, e.goal, e.instruments, deadline-t) for a in candidates]
            values = model.predict(fs) if not hold else [0.]*len(candidates)
            # Emergency responses cannot be suppressed by a model or a margin.
            if obs.failure_observed or all(a.kind == 'emergency' for a in candidates):
                selected = next((i for i, a in enumerate(candidates) if a.kind == 'emergency'), 0)
            elif hold:
                selected = next((i for i, a in enumerate(candidates) if a.kind == 'wait'), 0)
            elif rng.random() < controller.epsilon:
                selected = rng.randrange(len(candidates))
            else:
                best = max(values)
                selected = next(i for i, v in enumerate(values) if v >= best-config['tie_margin'])
            action = candidates[selected]
            e.submit(action)
            schedule.accept()
            trace.append(dict(time=t, remaining_ms=deadline-t, reasons=reasons,
                              instruction=action.payload(), predicted=float(values[selected]),
                              admission=admission, observable=asdict(obs),
                              clock_anchor=deepcopy(schedule.state['anchor'])))
            if retain_anchors:
                anchors.append(deepcopy(e))
        if not e.truncated:
            e.advance(deadline)
        budget.event(e.hidden.processed-processed)
        charged = True
        result = liquidate(e, scenario['trades'], scenario['label_end'],
                           ClosingRule(**config['closing']), budget)
        total_events = e.hidden.processed-processed + len(result['trace'])
        if total_events > budget.limits['events_per_replay']:
            result = dict(done=False, truncated=True, reason='replay_event_cap_including_tail')
    except RuntimeError as error:
        result = dict(done=False, truncated=True, reason=str(error))
    finally:
        if not charged:
            budget.events += e.hidden.processed-processed
    return dict(outcome=result, decisions=trace, fills=deepcopy(e.hidden.fills),
                events=e.event_trace,
                endpoint=deadline, controller=asdict(controller), scenario=scenario['id'],
                hidden_terminal=asdict(e.hidden.ledger),
                anchors=anchors, engine=e)


def collect_post_state(parent, horizons, scenarios, audit_scenarios, controllers,
                       model, encode, actions, config, budget, identity):
    """All horizons share this exact immediate post-state; no nested search."""
    records = []
    anchor = parent.now
    rule = ClosingRule(**config['closing'])
    observation = parent.observe()
    state_id = digest(asdict(observation))
    for h in horizons:
        base_only = not parent.hidden.ledger.positions and not parent.hidden.ledger.flows and not parent.hidden.ledger.debt_principal
        support = [horizon_support(anchor, h, s['decision_end'], s['label_end'], rule,
                                   base_only=base_only) for s in scenarios]
        record = dict(state_id=state_id, anchor=anchor, horizon_ms=h,
                      features=encode(observation, Instruction(), parent.goal, parent.instruments, h),
                      identity=identity, target_version=TARGET_VERSION,
                      support=[dict(scenario=s['id'], supported=v[0], reason=v[1]) for s, v in zip(scenarios, support)],
                      benchmark=asdict(parent.goal), controllers=[asdict(c) for c in controllers],
                      scenarios=[s['id'] for s in scenarios])
        if not all(v[0] for v in support):
            record.update(done=False, target=None, reason='unsupported_horizon')
            records.append(record)
            continue
        branches = []
        # Boundary has no controller search or model call, even with J > 1.
        for c in ([Controller(0)] if h == 0 else controllers):
            row = []
            for s in scenarios:
                branch = rollout(parent, h, s, c, model, encode, actions, config, budget)
                branch.pop('engine'); branch.pop('anchors')
                row.append(branch)
            branches.append(row)
        record.update(reduce_matrix([[b['outcome'] for b in row] for row in branches]))
        record['branches'] = branches
        record['winner_audit'] = []
        if record['done']:
            winner = Controller(0) if h == 0 else controllers[record['winner']]
            for s in audit_scenarios:
                audit = rollout(parent, h, s, winner, model, encode, actions, config, budget)
                audit.pop('engine'); audit.pop('anchors')
                record['winner_audit'].append(audit)
        records.append(record)
    return records
