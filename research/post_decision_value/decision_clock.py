"""Causal policy wakeups over exact exchange replay; no interpolated ticks."""
from dataclasses import asdict, dataclass
import json
import math


@dataclass(frozen=True)
class TriggerConfig:
    price_bps: float = 2.
    premium_bps: float = 2.
    min_gap_ms: int = 100
    max_wait_ms: int = 30000

    def __post_init__(self):
        if any(not math.isfinite(x) or x<=0 for x in (self.price_bps,self.premium_bps)):
            raise ValueError('Positive finite trigger thresholds required')
        if (type(self.min_gap_ms) is not int or type(self.max_wait_ms) is not int or
            not 0<self.min_gap_ms<=self.max_wait_ms):
            raise ValueError('Positive integer trigger intervals with min <= max required')


def snapshot(obs,instruments):
    prices={s:r['price'] for s,r in obs.market.items()}
    index=max(obs.market.values(),key=lambda r:r['received'])['index'] if obs.market else None
    premiums={}
    if index:
        for s,p in prices.items():
            ins=instruments[s]
            if ins.is_future:premiums[s]=p/index-1
            elif ins.payoff=='proxy':premiums[s]=p/(index*ins.underlying_per_unit)-1
            elif ins.payoff=='treasury':
                remaining=sum(v for date,v in ins.cashflows if ins.payment_id(date) not in obs.ledger.settled_ids)
                premiums[s]=remaining/p-1
    account=dict(ledger=asdict(obs.ledger),confirmed={s:asdict(o) for s,o in obs.confirmed.items()},
                 uncertain={s:[asdict(o) for o in variants] for s,variants in obs.uncertain.items()},
                 pending=obs.pending,group_fills=obs.group_fills,failure_observed=obs.failure_observed)
    return dict(time=obs.time,prices=prices,index=index,premiums=premiums,
                account=json.dumps(account,sort_keys=True,allow_nan=False))


class DecisionSchedule:
    """State is stored on Engine, so existing typed checkpoints preserve it.

    Call accept() immediately after submitting each yielded decision. Only the
    simulator driver looks at the event queue to advance time; trigger reasons
    depend exclusively on observations and previously known calendar dates.
    """
    def __init__(self,replay,end,*,mode='fixed',cadence_ms=500,trigger=None,budget=None):
        if mode not in ('fixed','event') or type(cadence_ms) is not int or cadence_ms<=0:
            raise ValueError('Invalid decision schedule')
        self.replay,self.end,self.mode,self.cadence_ms=replay,end,mode,cadence_ms
        self.trigger=TriggerConfig(**(trigger or {}));self.budget=budget
        config=dict(mode=mode,cadence_ms=cadence_ms if mode=='fixed' else None,trigger=asdict(self.trigger))
        state=getattr(replay,'decision_schedule',None)
        if state is not None and state['configuration']!=config:raise ValueError('Decision-clock resume configuration mismatch')
        self.state=state or dict(configuration=config,anchor=None)
        replay.decision_schedule=self.state

    def accept(self):
        self.state['anchor']=snapshot(self.replay.observe(),self.replay.instruments)

    def known_dates(self,obs):
        dates=[]
        for ins in self.replay.instruments.values():
            if ins.listed_at>obs.time:continue
            if ins.is_future or ins.payoff=='treasury':dates.append(ins.expiry)
            dates.extend(t for t,_ in ins.cashflows)
        dates.extend(f.date for f in obs.ledger.flows)
        dates.extend([self.replay.goal.horizon,self.replay.goal.target_deadline])
        return dates

    def reasons(self,obs):
        old=self.state['anchor']
        if old is None:return ['initial']
        new=snapshot(obs,self.replay.instruments);why=[]
        if new['account']!=old['account']:why.append('account_or_order_report')
        if set(new['prices'])!=set(old['prices']):why.append('observed_universe')
        if any(abs(math.log(p/old['prices'][s]))*10000>=self.trigger.price_bps for s,p in new['prices'].items() if s in old['prices']):
            why.append('price_change')
        if old['index'] and new['index'] and abs(math.log(new['index']/old['index']))*10000>=self.trigger.price_bps:
            why.append('index_change')
        if any(abs(p-old['premiums'][s])*10000>=self.trigger.premium_bps for s,p in new['premiums'].items() if s in old['premiums']):
            why.append('premium_change')
        if any(old['time']<t<=obs.time for t in self.known_dates(obs)):why.append('known_cashflow_or_deadline')
        if obs.time-old['time']>=self.trigger.max_wait_ms:why.append('heartbeat')
        return why

    def __iter__(self):
        e=self.replay;t=e.now
        if self.mode=='fixed' and self.state['anchor'] is not None:
            last=self.state['anchor']['time']
            t=last+max(1,math.ceil((t-last)/self.cadence_ms))*self.cadence_ms
        while t<self.end and not e.truncated:
            try:
                if self.budget:self.budget.check()
            except RuntimeError as error:
                e.truncated=True;e.hidden.failures.append(dict(time=t,reason=str(error)));return
            e.advance(t)
            if e.truncated:return
            obs=e.observe();old=self.state['anchor']
            reasons=['fixed_cadence'] if self.mode=='fixed' else self.reasons(obs)
            eligible=(self.mode=='fixed' or old is None or t-old['time']>=self.trigger.min_gap_ms)
            if reasons and eligible:
                yield t,reasons
                if self.state['anchor'] is old:raise RuntimeError('Decision must be accepted after submit')
                old=self.state['anchor']
            if self.mode=='fixed':
                t+=self.cadence_ms;continue
            # Quiet periods jump directly to real events or known timers. Hidden
            # messages/fills still execute but cannot by themselves wake policy.
            candidates=[self.end,old['time']+self.trigger.max_wait_ms]
            if reasons and not eligible:candidates.append(old['time']+self.trigger.min_gap_ms)
            candidates.extend(d for d in self.known_dates(e.observe()) if d>t)
            if e.hidden.queue:candidates.append(e.hidden.queue[0][0])
            t=min(candidates)
            if t<e.now:raise ValueError('Event queue went backwards')
