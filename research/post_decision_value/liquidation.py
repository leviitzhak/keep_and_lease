"""Independent, bounded subsequent-print closing; never a policy input.

This intentionally does not call Engine.advance/outcome or the value model.
Orders, including messages in flight, are atomically cancelled on the copy.
Eligible opposite-side prints fill at their printed price, once per native lot,
with declared participation. This is a synthetic execution rule, not depth.
"""
from dataclasses import asdict, dataclass
import math

from .accounting import EPS


@dataclass(frozen=True)
class ClosingRule:
    tail_ms: int = 172800000
    max_trades: int = 1000
    participation: float = 1.
    version: str = 'subsequent-print-v1'

    def __post_init__(self):
        if self.tail_ms <= 0 or self.max_trades <= 0 or not 0 < self.participation <= 1:
            raise ValueError('Invalid bounded closing rule')


def liquidate(replay, trades, label_end, rule=None, budget=None):
    """Return complete joint USD/BTC outcome, or explicit right-censoring.

    All dated obligations must actually resolve inside the bounded tail. In
    particular an unresolved debt is not forgiven or treated as base-only cash.
    Ordinary execution/report delays are unchanged outside this label function.
    """
    rule = rule or ClosingRule()
    p = replay.hidden.ledger.clone()
    start = replay.now
    end = min(start + rule.tail_ms, label_end)
    failures = list(replay.hidden.failures)
    p.collateral = {'BTC': 0., 'USD': 0.}
    trace, scanned = [], 0
    reason = None
    if replay.truncated:
        reason = 'strategic_replay_incomplete'
    if label_end < start:
        reason = 'endpoint_outside_split'

    def unresolved():
        return bool(p.positions or p.flows or p.debt_principal > EPS)

    def check(t):
        if any(v < -EPS for v in replay.goal.headroom(p.holdings(replay.instruments)).values()):
            failures.append({'time': t, 'reason': 'closing_holding_floor'})
        if any(v < -EPS for v in p.balances.values()):
            failures.append({'time': t, 'reason': 'closing_funding'})

    # A dated payment at the endpoint belongs to strategic replay. Validate
    # that it has not accidentally been skipped; never backdate a receipt.
    if any(f.date <= start for f in p.flows):
        reason = 'unprocessed_endpoint_cashflow'
    dates = {f.date for f in p.flows if start < f.date <= end}
    for s in p.positions:
        ins = replay.instruments[s]
        dates.update(t for t, _ in ins.cashflows if start < t <= end)
        if ins.is_future and start < ins.expiry <= end:
            dates.add(ins.expiry)
        if ins.expiry <= start:
            reason = 'unresolved_expired_inventory'
    events = [(t, 0, '', None) for t in dates]
    events += [(v[0], -1, v[4]['symbol'], v[4]) for v in replay.hidden.queue
               if v[3] == 'funding' and start < v[0] <= end]
    seen = set()
    for tr in trades:
        if not start < tr.time <= end:
            continue
        key = (tr.symbol, tr.identifier)
        if key in seen:
            raise ValueError('Duplicate closing trade identity')
        seen.add(key)
        events.append((tr.time, 1, tr.identifier, tr))
    events.sort(key=lambda x: x[:3])
    for t, _, _, tr in events:
        if reason or not unresolved():
            break
        if budget:
            budget.check()
            budget.event()
        if isinstance(tr, dict):
            ins = replay.instruments[tr['symbol']]
            amount = p.pay_funding(ins, t, tr['rate'], tr['price'])
            trace.append(dict(time=t, kind='synthetic_funding', symbol=ins.symbol,
                              currency=ins.currency, amount=amount))
            check(t)
            continue
        if tr is None:
            for s in list(p.positions):
                ins = replay.instruments[s]
                if any(date == t for date, _ in ins.cashflows):
                    amount = p.pay_asset(ins, t)
                    trace.append(dict(time=t, kind='contractual_receipt', symbol=s, amount=amount))
                elif ins.is_future and ins.expiry == t:
                    reason = 'missing_futures_settlement_before_close'
            for flow in p.flows:
                if flow.date <= t:
                    trace.append(dict(time=t, kind='dated_obligation', flow=asdict(flow)))
            p.resolve_cashflows(t)
            check(t)
            continue
        scanned += 1
        if scanned > rule.max_trades:
            reason = 'closing_scan_cap'
            break
        pos = p.positions.get(tr.symbol)
        entry = dict(time=t, kind='print', trade_id=tr.identifier,
                     source_time=tr.source_time if tr.source_time is not None else t,
                     source_payoff=tr.source_payoff, symbol=tr.symbol,
                     price=tr.price, amount=tr.amount, side=tr.side,
                     executable=tr.executable, eligible=False, quantity=0.)
        trace.append(entry)
        if pos is None:
            continue
        ins = replay.instruments[tr.symbol]
        eligible = tr.executable and t < ins.expiry and (
            (pos.quantity > 0 and tr.side == 'buy') or
            (pos.quantity < 0 and tr.side == 'sell'))
        entry['eligible'] = eligible
        if not eligible:
            continue
        capacity = ins.print_capacity(tr.amount, tr.price, tr.source_payoff) * rule.participation
        quantity = -math.copysign(ins.round_quantity(min(abs(pos.quantity), capacity)), pos.quantity)
        if abs(quantity) <= EPS:
            continue
        before = p.balances.copy()
        p.fill(ins, quantity, tr.price)
        entry.update(quantity=quantity, fee=ins.fee(quantity, tr.price),
                     balances_before=before, balances_after=p.balances.copy())
        check(t)
    if not reason and unresolved():
        reason = 'right_censored_inventory_or_obligations'
    complete = reason is None
    result = dict(done=complete, truncated=not complete, reason=reason,
                  endpoint=start, label_end=label_end, tail_end=end, rule=asdict(rule),
                  duration_ignored=True, atomic_cancellation=True,
                  cancelled_live=list(replay.hidden.orders),
                  cancelled_pending=[x['id'] for x in replay.observable.pending],
                  reservations_released=dict(replay.observable.reserved),
                  trace=trace, scanned_trades=scanned, balances=p.balances.copy(),
                  remaining_positions={s: asdict(v) for s, v in p.positions.items()},
                  remaining_flows=[asdict(f) for f in p.flows], fees=p.fees.copy(),
                  projected_receipts=p.projected_receipts, failures=failures)
    if complete:
        result.update(replay.goal.outcome(p.balances, bool(failures)))
    # Missing ground truth has no utility field, and cannot be fitted as zero.
    return result


def horizon_support(anchor, horizon, decision_end, label_end, rule, *, base_only=False):
    if horizon < 0:
        return False, 'negative_horizon'
    endpoint = anchor + horizon
    if endpoint > decision_end or endpoint > label_end:
        return False, 'endpoint_outside_decision_window'
    if horizon == 0 and base_only:
        return True, 'settled_base_only'
    if endpoint + rule.tail_ms > label_end:
        return False, 'reserved_tail_exceeds_label_window'
    return True, 'allocated_tail_requires_actual_coverage'
