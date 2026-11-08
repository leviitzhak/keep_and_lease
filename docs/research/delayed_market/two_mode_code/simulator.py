"""Delayed market/private observations for the single-bill diagnostic.

The policy API receives a copied observation, never the exchange or event queue.
Times use quarter-step integers internally; prices/cash use 1/32 USD ticks.
This is the simulator/input stage. No max-min training results are claimed.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from collections import deque
from pathlib import Path
import copy, heapq, json, math, random
import numpy as np

TERMINAL={'FILLED','CANCELLED','REJECTED'}
STATUS={'SENT':0,'ACTIVE':1,'PARTIAL':2,'FILLED':3,'CANCELLED':4,'REJECTED':5}
REPORT_KIND={'create_ack':1,'fill':2,'cancel_ack':3,'reject':4}
CHANNELS=('outbound','market','ack','fill')

@dataclass(frozen=True)
class DelayLaw:
    values:tuple[int,...]=(1,2,3)
    probabilities:tuple[float,...]=(.6,.3,.1)
    def __post_init__(self):
        if len(self.values)!=len(self.probabilities) or not self.values:raise ValueError('Invalid delay law')
        if any(d<0 or not isinstance(d,int) for d in self.values):raise ValueError('Delays must be nonnegative integer steps')
        if any(p<0 for p in self.probabilities) or not math.isclose(sum(self.probabilities),1):raise ValueError('Probabilities must sum to one')
    def draw(self,rng):
        u=rng.random();total=0
        for d,p in zip(self.values,self.probabilities):
            total+=p
            if u<total:return d
        return self.values[-1]

@dataclass(frozen=True)
class Config:
    horizon:int=10
    cap:int=10
    initial_cash_ticks:int=32000
    initial_mid_ticks:int=3040
    price_rise_ticks_per_quarter:int=1
    face_ticks:int=3200
    spread_ticks:int=8
    trade_size:int=2
    seed:int=20261102
    warmup_steps:int=3
    tail_end:int=20
    outbound:DelayLaw=field(default_factory=DelayLaw)
    market:DelayLaw=field(default_factory=DelayLaw)
    ack:DelayLaw=field(default_factory=DelayLaw)
    fill:DelayLaw=field(default_factory=DelayLaw)

@dataclass(frozen=True)
class Action:
    kind:str='WAIT'
    quantity:int=0
    limit_ticks:int=0
    def label(self):
        if self.kind=='WAIT':return 'WAIT'
        if self.kind=='CANCEL':return 'SEND CANCEL'
        return f"SEND {'BUY' if self.quantity>0 else 'SELL'} {abs(self.quantity)} @ {self.limit_ticks/32:.5f}"

@dataclass
class ExchangeOrder:
    order_id:int
    side:int
    original:int
    remaining:int
    limit_ticks:int
    cumulative_filled:int=0
    cumulative_notional_ticks:int=0
    version:int=0
    status:str='ACTIVE'

class Simulator:
    def __init__(self,config=Config(),delay_overrides=None,intervals=None):
        self.config=config;self.clock=-4*config.warmup_steps;self.serial=0
        self.queue=[];self.exchange_cash=config.initial_cash_ticks;self.exchange_bills=0
        self.exchange_orders={};self.active_order_id=None
        self.reported_cash=config.initial_cash_ticks;self.reported_bills=0
        self.known_orders={};self.pending_create=None;self.pending_cancel=None
        self.next_order_id=1;self.next_command_id=1;self.latest_market=None
        self.market_history=[];self.private_history=[];self.state_history=[];self.command_history=[]
        self.audit=[];self.snapshots=[];self.delay_draws=[];self.decisions=set()
        self.rng={c:random.Random(config.seed+100003*(i+1)) for i,c in enumerate(CHANNELS)}
        self.overrides={c:deque((delay_overrides or {}).get(c,[])) for c in CHANNELS}
        use=range(-config.warmup_steps,config.tail_end+1) if intervals is None else intervals
        for k in use:
            for off,aggressor in [(1,-1),(3,1)]:
                tick=4*k+off;mid=config.initial_mid_ticks+config.price_rise_ticks_per_quarter*tick
                trade=dict(trade_id=f"{'buy' if aggressor>0 else 'sell'}-{k}",source_tick=tick,
                           price_ticks=mid+aggressor*config.spread_ticks,mid_ticks=mid,size=config.trade_size,aggressor=aggressor)
                self._push(tick,1,'trade',trade)
        self.advance_to(0)
    def _push(self,tick,priority,kind,payload):
        self.serial+=1;heapq.heappush(self.queue,(tick,priority,self.serial,kind,copy.deepcopy(payload)))
    def _delay(self,channel,source_tick,event):
        scripted=bool(self.overrides[channel])
        if scripted:d=self.overrides[channel].popleft()
        else:d=getattr(self.config,channel).draw(self.rng[channel])
        if d<0 or not isinstance(d,int):raise ValueError('Invalid scripted delay')
        self.delay_draws.append(dict(channel=channel,source_time=source_tick/4,delay=d,arrival_time=source_tick/4+d,event=event,source='scripted' if scripted else 'random'))
        return d
    def clone(self):return copy.deepcopy(self)
    def set_future_delays(self,channel,values):
        """Existing scheduled events remain unchanged; overrides affect new draws."""
        self.overrides[channel]=deque(values)
    def _log(self,kind,**payload):self.audit.append(dict(time=self.clock/4,kind=kind,**payload))
    def advance_to(self,time):
        target=round(time*4)
        if target<self.clock or abs(time*4-target)>1e-9:raise ValueError('Nonmonotone or non-quarter time')
        while self.queue and self.queue[0][0]<=target:
            tick,priority,serial,kind,payload=heapq.heappop(self.queue);self.clock=tick
            if kind=='command':self._command_arrives(payload)
            elif kind=='trade':self._trade(payload)
            elif kind=='private':self._receive_private(payload)
            elif kind=='market':self._receive_market(payload)
            else:raise AssertionError(kind)
            self._invariants()
        self.clock=target
    def _publish(self,o,kind,command_id=None):
        payload=dict(order_id=o.order_id,side=o.side,original=o.original,remaining=o.remaining,
                     limit_ticks=o.limit_ticks,cumulative_filled=o.cumulative_filled,
                     cumulative_notional_ticks=o.cumulative_notional_ticks,version=o.version,status=o.status,
                     kind=kind,command_id=command_id,source_tick=self.clock)
        channel='fill' if kind=='fill' else 'ack'
        d=self._delay(channel,self.clock,f'{kind}:order{o.order_id}:v{o.version}')
        self._push(self.clock+4*d,2,'private',payload)
        self._log('report_generated',report_kind=kind,order_id=o.order_id,source_version=o.version,receive_time=self.clock/4+d,
                  cumulative_filled=o.cumulative_filled,status=o.status)
    def _command_arrives(self,c):
        oid=c['order_id'];cmd=c['command_id']
        if c['kind']=='CREATE':
            side=1 if c['quantity']>0 else -1;q=abs(c['quantity']);limit=c['limit_ticks']
            allowed=self.active_order_id is None and ((self.exchange_cash>=q*limit and self.exchange_bills+q<=self.config.cap) if side>0 else self.exchange_bills>=q)
            o=ExchangeOrder(oid,side,q,q if allowed else 0,limit,version=1,status='ACTIVE' if allowed else 'REJECTED')
            self.exchange_orders[oid]=o
            if allowed:self.active_order_id=oid
            self._log('create_at_exchange',order_id=oid,quantity=c['quantity'],limit=limit/32,status=o.status)
            self._publish(o,'create_ack' if allowed else 'reject',cmd)
        else:
            o=self.exchange_orders[oid]
            if o.status not in TERMINAL:
                o.status='CANCELLED';o.remaining=0
                if self.active_order_id==oid:self.active_order_id=None
            o.version+=1
            self._log('cancel_at_exchange',order_id=oid,status=o.status,cumulative_filled=o.cumulative_filled)
            self._publish(o,'cancel_ack',cmd)
    def _trade(self,tr):
        self._log('market_trade',**{k:v for k,v in tr.items() if k!='source_tick'})
        if self.active_order_id is not None:
            o=self.exchange_orders[self.active_order_id]
            through=(o.side>0 and tr['aggressor']<0 and tr['price_ticks']<o.limit_ticks) or (o.side<0 and tr['aggressor']>0 and tr['price_ticks']>o.limit_ticks)
            if through:
                q=min(o.remaining,tr['size']);o.remaining-=q;o.cumulative_filled+=q;o.cumulative_notional_ticks+=q*o.limit_ticks
                self.exchange_cash-=o.side*q*o.limit_ticks;self.exchange_bills+=o.side*q;o.version+=1
                o.status='PARTIAL' if o.remaining else 'FILLED'
                self._log('fill_at_exchange',order_id=o.order_id,signed_qty=o.side*q,price=o.limit_ticks/32,trade_id=tr['trade_id'],
                          true_cash=self.exchange_cash/32,true_bills=self.exchange_bills,remaining=o.remaining)
                self._publish(o,'fill')
                if not o.remaining:self.active_order_id=None
        d=self._delay('market',self.clock,tr['trade_id']);self._push(self.clock+4*d,3,'market',tr)
    def _receive_market(self,tr):
        message=dict(tr,receive_tick=self.clock)
        fresh=self.latest_market is None or tr['source_tick']>self.latest_market['source_tick']
        message['advances_latest']=fresh;self.market_history.append(message)
        if fresh:self.latest_market=copy.deepcopy(message)
        self._log('market_received',trade_id=tr['trade_id'],source_time=tr['source_tick']/4,price=tr['price_ticks']/32,advances_latest=fresh)
    def _receive_private(self,p):
        o=self.known_orders[p['order_id']];applied=p['version']>o['version']
        dq=dn=0
        if applied:
            dq=p['cumulative_filled']-o['cumulative_filled'];dn=p['cumulative_notional_ticks']-o['cumulative_notional_ticks']
            assert dq>=0 and dn>=0
            self.reported_bills+=p['side']*dq;self.reported_cash-=p['side']*dn
            for key in ['remaining','cumulative_filled','cumulative_notional_ticks','version','status']:o[key]=p[key]
            o['last_source_tick']=p['source_tick'];o['last_receive_tick']=self.clock
        # A fill report also establishes that the new order reached the exchange.
        if self.pending_create and self.pending_create['order_id']==p['order_id']:self.pending_create=None
        if self.pending_cancel and self.pending_cancel['command_id']==p['command_id']:self.pending_cancel=None
        message=dict(p,receive_tick=self.clock,applied=applied,new_reported_qty=p['side']*dq,new_reported_cash=-p['side']*dn/32)
        self.private_history.append(message)
        self._log('private_received',order_id=p['order_id'],report_kind=p['kind'],source_time=p['source_tick']/4,
                  source_version=p['version'],applied=applied,new_reported_qty=p['side']*dq,new_reported_cash=-p['side']*dn/32,
                  reported_cash=self.reported_cash/32,reported_bills=self.reported_bills,status=p['status'])
    def _visible(self):
        open_orders=[o for o in self.known_orders.values() if o['status'] not in TERMINAL]
        assert len(open_orders)<=1
        o=open_orders[0] if open_orders else None
        reserve_cash=sum(z['remaining']*z['limit_ticks'] for z in open_orders if z['side']>0)
        reserve_bills=sum(z['remaining'] for z in open_orders if z['side']<0)
        committed_buys=sum(z['remaining'] for z in open_orders if z['side']>0)
        market=self.latest_market
        return dict(time=self.clock/4,reported_cash=self.reported_cash/32,reported_bills=self.reported_bills,
                    reserved_cash=reserve_cash/32,free_cash=(self.reported_cash-reserve_cash)/32,
                    reserved_bills=reserve_bills,free_bills=self.reported_bills-reserve_bills,
                    cap_available=self.config.cap-self.reported_bills-committed_buys,
                    latest_market=copy.deepcopy(market),current_order=copy.deepcopy(o),
                    known_orders=copy.deepcopy(self.known_orders),pending_create=copy.deepcopy(self.pending_create),pending_cancel=copy.deepcopy(self.pending_cancel))
    def observation(self):
        """All returned fields are either locally known or already received."""
        return dict(schema='received-history-v2',participant_id=0,horizon_limit=self.config.horizon,cap=self.config.cap,
                    initial_cash=self.config.initial_cash_ticks/32,face=self.config.face_ticks/32,
                    current=self._visible(),state_history=copy.deepcopy(self.state_history),
                    market_history=copy.deepcopy(self.market_history),private_history=copy.deepcopy(self.private_history),
                    command_history=copy.deepcopy(self.command_history))
    def snapshot(self,phase):
        if phase not in ('before','after','terminal'):raise ValueError(phase)
        v=self._visible();v['phase']=phase
        # Full state histories are the received states, not historical exchange truth.
        self.state_history.append(copy.deepcopy(v))
        actual=self.exchange_orders.get(self.active_order_id)
        audit=dict(**copy.deepcopy(v),true_cash=self.exchange_cash/32,true_bills=self.exchange_bills,
                   true_live_signed_qty=(actual.side*actual.remaining if actual else 0),true_live_limit=(actual.limit_ticks/32 if actual else None),
                   actual_mid=(self.config.initial_mid_ticks+self.config.price_rise_ticks_per_quarter*self.clock)/32,
                   delivered_market_count=len(self.market_history),delivered_private_count=len(self.private_history))
        self.snapshots.append(audit)
        return self.observation()
    def submit(self,a):
        if self.clock%4 or self.clock<0:raise ValueError('Decisions occur at integer nonnegative times')
        if self.clock in self.decisions:raise ValueError('Only one action per decision time')
        allowed=feasible_actions(self.observation())
        if a not in allowed:raise ValueError(f'Action not feasible from received information: {a}')
        self.decisions.add(self.clock)
        if a.kind=='WAIT':self.command_history.append(dict(time=self.clock/4,kind='WAIT'));return
        cmd=self.next_command_id;self.next_command_id+=1
        if a.kind=='CREATE':
            oid=self.next_order_id;self.next_order_id+=1
            o=dict(order_id=oid,side=1 if a.quantity>0 else -1,original=abs(a.quantity),remaining=abs(a.quantity),limit_ticks=a.limit_ticks,
                   cumulative_filled=0,cumulative_notional_ticks=0,version=0,status='SENT',sent_tick=self.clock,
                   last_source_tick=None,last_receive_tick=None)
            self.known_orders[oid]=o
            c=dict(kind='CREATE',order_id=oid,command_id=cmd,quantity=a.quantity,limit_ticks=a.limit_ticks,sent_tick=self.clock)
            self.pending_create=copy.deepcopy(c)
        else:
            oid=self._visible()['current_order']['order_id']
            c=dict(kind='CANCEL',order_id=oid,command_id=cmd,quantity=0,limit_ticks=0,sent_tick=self.clock)
            self.pending_cancel=copy.deepcopy(c)
        self.command_history.append(dict(time=self.clock/4,**copy.deepcopy(c)))
        d=self._delay('outbound',self.clock,f'{a.kind}:cmd{cmd}')
        self._push(self.clock+4*d,0,'command',c)
        self._log('command_sent',order_id=oid,command=a.kind,quantity=a.quantity,limit=a.limit_ticks/32,hidden_arrival=self.clock/4+d)
        # Supports the zero-delay counterfactual without delaying delivery a step.
        self.advance_to(self.clock/4)
    def _invariants(self):
        assert self.exchange_cash>=0 and 0<=self.exchange_bills<=self.config.cap
        v=self._visible()
        assert v['free_cash']>=0 and v['free_bills']>=0 and v['cap_available']>=0
        assert self.reported_cash>=0 and 0<=self.reported_bills<=self.config.cap
    def drain_reports(self):
        """Drain outstanding commands/reports and reports they cause; no liquidation."""
        while True:
            pending=[e[0] for e in self.queue if e[3] in ('command','private')]
            if not pending:return
            self.advance_to(max(pending)/4)

def feasible_actions(observation):
    """Pure function: no exchange holdings, future tape or pending message contents."""
    v=observation['current'];o=v['current_order'];out=[Action()]
    if v['pending_create'] or v['pending_cancel']:return out
    if o:
        if o['status'] in ('ACTIVE','PARTIAL'):out.append(Action('CANCEL'))
        return out
    market=v['latest_market']
    if market is None:return out
    # Use the last received reference price, never the current true midprice.
    buy=market['mid_ticks']+16;sell=market['mid_ticks']-8
    max_buy=min(v['cap_available'],int(round(v['free_cash']*32))//buy)
    out.extend(Action('CREATE',q,buy) for q in range(1,max_buy+1))
    out.extend(Action('CREATE',-q,sell) for q in range(1,v['free_bills']+1))
    return out

STATE_FEATURES=['mask','time','phase_after','reported_cash','reported_bills','reserved_cash','free_cash','reserved_bills','free_bills','cap_available',
                'received_mid','market_source_time','market_receive_time','market_age','order_id','original_signed_qty','remaining_signed_qty',
                'order_limit','reported_cumulative_fill','reported_status','order_sent_time','pending_create','pending_cancel','cancel_sent_time',
                'last_report_source','last_report_receive','reported_version']
MARKET_FEATURES=['mask','source_time','receive_time','received_mid','trade_price','trade_size','aggressor','advances_latest']
PRIVATE_FEATURES=['mask','source_time','receive_time','order_id','version','report_kind','side','original_qty','remaining_qty','limit',
                  'cumulative_fill','cumulative_notional','status','applied']

def encode(observation,end):
    """Fixed-size full-prefix encoding for this ten-step fixture, with masks.

    Every received event and before/after state is retained. Overflow raises,
    rather than silently truncating history. Empty slots are all zero.
    """
    T=observation['horizon_limit'];v=observation['current'];now=v['time'];cap=observation['cap'];cash0=observation['initial_cash']
    if not 0<=now<=end<=T:raise ValueError('Invalid current time or endpoint')
    states=copy.deepcopy(observation['state_history'])
    if not states or states[-1]['time']!=now or {k:states[-1][k] for k in v}!=v:
        states.append(dict(v,phase='before'))
    max_s=2*(T+1);max_m=2*(T+3);max_p=4*T+16
    mh=observation['market_history'];ph=observation['private_history']
    if len(states)>max_s or len(mh)>max_m or len(ph)>max_p:raise ValueError('History capacity exceeded; increase configured encoder capacity')
    ss=np.zeros((max_s,len(STATE_FEATURES)));mm=np.zeros((max_m,len(MARKET_FEATURES)));pp=np.zeros((max_p,len(PRIVATE_FEATURES)))
    for i,s in enumerate(states):
        assert s['time']<=now
        m=s['latest_market'];o=s['current_order'];pc=s['pending_cancel']
        ss[i]=[1,s['time']/T,int(s['phase']=='after'),s['reported_cash']/cash0,s['reported_bills']/cap,s['reserved_cash']/cash0,s['free_cash']/cash0,
               s['reserved_bills']/cap,s['free_bills']/cap,s['cap_available']/cap,
               m['mid_ticks']/3200 if m else 0,m['source_tick']/4/T if m else 0,m['receive_tick']/4/T if m else 0,
               (s['time']-m['source_tick']/4)/T if m else 0,o['order_id']/T if o else 0,o['side']*o['original']/cap if o else 0,
               o['side']*o['remaining']/cap if o else 0,o['limit_ticks']/3200 if o else 0,o['cumulative_filled']/cap if o else 0,
               STATUS[o['status']]/5 if o else 0,o['sent_tick']/4/T if o else 0,int(s['pending_create'] is not None),int(pc is not None),
               pc['sent_tick']/4/T if pc else 0,o['last_source_tick']/4/T if o and o['last_source_tick'] is not None else 0,
               o['last_receive_tick']/4/T if o and o['last_receive_tick'] is not None else 0,o['version']/(T+3) if o else 0]
    for i,m in enumerate(mh):
        assert m['source_tick']<=m['receive_tick']<=now*4
        mm[i]=[1,m['source_tick']/4/T,m['receive_tick']/4/T,m['mid_ticks']/3200,m['price_ticks']/3200,m['size']/cap,m['aggressor'],int(m['advances_latest'])]
    for i,p in enumerate(ph):
        assert p['source_tick']<=p['receive_tick']<=now*4
        pp[i]=[1,p['source_tick']/4/T,p['receive_tick']/4/T,p['order_id']/T,p['version']/(T+3),REPORT_KIND[p['kind']]/4,p['side'],
               p['original']/cap,p['remaining']/cap,p['limit_ticks']/3200,p['cumulative_filled']/cap,p['cumulative_notional_ticks']/(32*cash0),STATUS[p['status']]/5,int(p['applied'])]
    return np.concatenate(([now/T,(end-now)/T,cap/100],ss.ravel(),mm.ravel(),pp.ravel()))

class HistoryValueNetwork:
    """History-aware input adapter and fresh model; weights are NOT trained."""
    def __init__(self,input_size,hidden=32,seed=20261102):
        rng=np.random.default_rng(seed)
        self.W=rng.normal(0,.1,(input_size,hidden));self.b=np.zeros(hidden);self.w=rng.normal(0,.02,hidden);self.c=0.
    def predict(self,observation,end):
        x=encode(observation,end);v=observation['current'];m=v['latest_market']
        baseline=v['reported_cash']+v['reported_bills']*(m['mid_ticks']/32 if m else 0)
        return float(baseline+20*(np.tanh(x@self.W+self.b)@self.w+self.c))
    @property
    def parameter_count(self):return self.W.size+self.b.size+self.w.size+1

def diagnostic_policy(observation):
    """Simple fixture controller, not learned or claimed optimal."""
    aa=feasible_actions(observation);v=observation['current'];o=v['current_order']
    if o and observation['current']['time']-o['sent_tick']/4>=4:
        return next((a for a in aa if a.kind=='CANCEL'),Action())
    buys=[a for a in aa if a.kind=='CREATE' and a.quantity>0]
    return buys[-1] if buys else Action()

def run_episode(config=Config(),delay_overrides=None,policy=diagnostic_policy):
    sim=Simulator(config,delay_overrides);decisions=[];vectors=[]
    for t in range(config.horizon+1):
        sim.advance_to(t);obs=sim.snapshot('terminal' if t==config.horizon else 'before');vectors.append(encode(obs,config.horizon))
        if t==config.horizon:break
        action=policy(obs);decisions.append(dict(time=t,action=action.label(),feasible=len(feasible_actions(obs))))
        sim.submit(action);post=sim.snapshot('after');vectors.append(encode(post,config.horizon))
    return sim,decisions,np.stack(vectors)

def export(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    # Fixed override demonstrates actual fill before receipt, fill-before-ACK,
    # and out-of-order cumulative reports. Remaining delays use random laws.
    overrides={'outbound':[1,2,1], 'ack':[3,1,2], 'fill':[3,1,2,3,1,2]}
    sim,decisions,vectors=run_episode(delay_overrides=overrides)
    random_sim,random_decisions,random_vectors=run_episode()
    snap_at_end=sim.observation();net=HistoryValueNetwork(vectors.shape[1])
    np.savez_compressed(root/'history_inputs.npz',ordering_inputs=vectors,random_inputs=random_vectors)
    np.savez_compressed(root/'initial_history_network.npz',W=net.W,b=net.b,w=net.w,c=np.array([net.c]),trained=np.array([False]))
    data=dict(schema='delayed-observation-audit-v2',config=asdict(sim.config),scripted_audit_delays=overrides,
              decisions=decisions,snapshots=sim.snapshots,market_history=sim.market_history,private_history=sim.private_history,
              state_history=sim.state_history,command_history=sim.command_history,event_log=sim.audit,delay_draws=sim.delay_draws,
              encoder=dict(input_size=vectors.shape[1],snapshots=len(vectors),state_slots=22,state_features=STATE_FEATURES,
                           market_slots=26,market_features=MARKET_FEATURES,private_slots=56,private_features=PRIVATE_FEATURES,
                           network_hidden=32,network_parameters=net.parameter_count,trained=False),
              random_episode=dict(decisions=random_decisions,snapshots=random_sim.snapshots,market_history=random_sim.market_history,
                                  private_history=random_sim.private_history,event_log=random_sim.audit,delay_draws=random_sim.delay_draws),
              encoded_ordering_inputs=vectors.tolist(),
              status=dict(simulator='implemented and tested',history_inputs='implemented and tested',
                          max_min_exploration_training='next stage; not run',two_participants='following stage; not implemented'))
    (root/'audit.json').write_text(json.dumps(data,indent=2,allow_nan=False))
    return data

if __name__=='__main__':
    data=export(Path(__file__).resolve().parent)
    print(json.dumps(dict(input_size=data['encoder']['input_size'],network_parameters=data['encoder']['network_parameters'],
                         snapshots=len(data['snapshots']),market_received=len(data['market_history']),private_received=len(data['private_history']),decisions=data['decisions']),indent=2))
