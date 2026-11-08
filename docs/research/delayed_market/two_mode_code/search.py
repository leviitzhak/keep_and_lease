"""Single-path delay-minimizing steps and maximum-liquidation rollout search.

The simulator owns hidden delay assignments. The Transformer sees only received
history. Greedy ties use the lexicographically first delay vector (1, then 2, 3).
"""
import copy,hashlib,json,random
from dataclasses import asdict
import numpy as np
from simulator import Simulator,Config,Action,CHANNELS,feasible_actions,encode
from network import predict
from exploration import LEGACY_SCHEDULE

def key(obs):return json.dumps(obs,sort_keys=True,separators=(',',':'))
def stable_seed(s):return int(hashlib.sha256(str(s).encode()).hexdigest()[:12],16)%2147483647
def action_dict(a):return dict(kind=a.kind,quantity=a.quantity,limit_ticks=a.limit_ticks)

class NeedDelay(Exception):pass
class PathSimulator(Simulator):
    def _delay(self,channel,source_tick,event):
        if source_tick<0:d=1;source='fixed warmup'
        elif getattr(self,'delay_mode','random')=='enumerate':
            i=self.prefix_index
            if i>=len(self.prefix):raise NeedDelay()
            d=self.prefix[i];self.prefix_index+=1;source='enumerated'
        elif getattr(self,'delay_mode','random')=='first':d=min(getattr(self.config,channel).values);source='minimum-value tie: first vector'
        else:d=getattr(self.config,channel).draw(self.rng[channel]);source='random exploration'
        self.delay_draws.append(dict(channel=channel,source_time=source_tick/4,event=event,delay=d,arrival_time=source_tick/4+d,source=source))
        return d

def record(obs,end):
    x=encode(obs,end);T=obs['horizon_limit'];rows=[]
    def add(time,priority,typ,offset,features):
        r=np.zeros(60,np.float32);r[typ]=1;r[offset:offset+len(features)]=features;rows.append((time,priority,len(rows),r))
    ns=2*(T+1); nm=2*(T+3); npv=4*T+16
    states=x[3:3+ns*27].reshape(ns,27)
    for s in states:
        if s[0]:add(s[1]*T,5 if s[2] else 3,0,4,s)
    m0=3+ns*27;p0=m0+nm*8
    for m in x[m0:p0].reshape(nm,8):
        if m[0]:add(m[2]*T,2,1,31,m)
    for p in x[p0:].reshape(npv,14):
        if p[0]:add(p[2]*T,1,2,39,p)
    for c in obs['command_history']:
        add(c['time'],4,3,53,[c['time']/T,c.get('quantity',0)/obs['cap'],c.get('limit_ticks',0)/3200,c.get('command_id',0)/T,c.get('order_id',0)/T,int(c['kind']=='CREATE'),int(c['kind']=='CANCEL')])
    rows.sort(key=lambda z:z[:3]);tokens=np.stack([r[3] for r in rows]);v=obs['current'];m=v['latest_market']
    baseline=v['reported_cash']+v['reported_bills']*(m['mid_ticks']/32 if m else 0)
    return dict(tokens=tokens,control=np.array([v['time']/T,(end-v['time'])/T,obs['cap']/100],np.float32),baseline=baseline)

def liquidation(s,end,details=False):
    q=s.exchange_bills;cash=s.exchange_cash/32;legs=[];k=int(end)
    while q:
        time=k+.75;size=min(q,s.config.trade_size)
        price=(s.config.initial_mid_ticks+s.config.price_rise_ticks_per_quarter*round(4*time)+s.config.spread_ticks)/32
        legs.append(dict(time=time,quantity=size,price=price,proceeds=size*price));cash+=size*price;q-=size;k+=1
    return (cash,legs) if details else cash

def full_state(s):
    """Audit-only simulator state. Never passed to record()/network."""
    return dict(time=s.clock/4,received=s.observation(),exchange_cash=s.exchange_cash/32,exchange_bills=s.exchange_bills,
                active_order_id=s.active_order_id,exchange_orders={k:asdict(v) for k,v in s.exchange_orders.items()},
                pending_events=[list(e) for e in sorted(s.queue) if e[3]!='trade'],delay_assignments=copy.deepcopy(s.delay_draws))

def transition(s,a,mode='first',prefix=(),seed=None):
    c=s.clone();c.delay_mode=mode;c.prefix=list(prefix);c.prefix_index=0
    if seed is not None:c.rng={ch:random.Random(seed+100003*(i+1)) for i,ch in enumerate(CHANNELS)}
    c.submit(a);post=c.snapshot('after');c.advance_to(s.clock/4+1);c.snapshot('before');c.delay_mode='random'
    return c,post

def enumerate_successors(s,a):
    """Complete event-dependent tree of new 1/2/3 delays, in lexical order."""
    stack=[()];out=[]
    while stack:
        prefix=stack.pop()
        try:c,post=transition(s,a,'enumerate',prefix);out.append((c,post))
        except NeedDelay:stack.extend(prefix+(d,) for d in (3,2,1))
    return out

def equivalent_delay_histories(s):
    """Exact timing shortcut, not a sampled minimum.

    At an integer root, a new command cannot arrive before the next decision.
    Its earliest ack is another step later. New market/fill messages have at
    least one step latency and are generated strictly after the root. None can
    enter the immediate successor history. Previously queued arrivals are fixed.
    """
    if s.clock%4:return False
    if any(tuple(getattr(s.config,ch).values)!=(1,2,3) for ch in CHANNELS):return False
    return not any(e[3]=='trade' and e[0]%4==0 for e in s.queue if e[0]<=s.clock+4)

def step(s,end,model,rng,force_greedy=False,exploration=.30,audit=False,exhaustive=False):
    if not 0 <= exploration <= 1:raise ValueError('exploration must be in [0,1]')
    obs=s.observation();aa=feasible_actions(obs);mode='greedy' if force_greedy or rng.random()>=exploration else 'exploratory'
    if mode=='exploratory':
        idx=int(rng.integers(len(aa)));c,post=transition(s,aa[idx],'random',seed=int(rng.integers(2**31-1)))
        value=float(predict(model,[record(c.observation(),end)])[0])
        info=dict(mode=mode,action=aa[idx].label(),action_index=idx,**action_dict(aa[idx]),next_value=value,minimum=None,
                  delay_candidates=None,delay_ties=None,selected_delay_index=None,action_rows=[],delay_rows=[])
    else:
        compressed=equivalent_delay_histories(s) and not exhaustive
        groups=[[(transition(s,a,'first'))] if compressed else enumerate_successors(s,a) for a in aa]
        flat=[z for g in groups for z in g]
        # Equal observations get the exact same scalar, avoiding floating-point
        # batch-size artifacts that could otherwise break true delay ties.
        observations=[c.observation() for c,p in flat];keys=[key(o) for o in observations];unique={}
        for k,o in zip(keys,observations):
            if k not in unique:unique[k]=record(o,end)
        values=dict(zip(unique,predict(model,list(unique.values()))));vv=np.array([values[k] for k in keys]);scores=[];offset=0;mins=[]
        for g in groups:
            v=vv[offset:offset+len(g)];offset+=len(g);scores.append(v);mins.append(float(v.min()))
        idx=int(np.argmax(mins));di=int(np.argmin(scores[idx]));c,post=groups[idx][di]
        # Audits enumerate all assignments, verifying the exact compression claim.
        if audit and compressed:
            groups=[enumerate_successors(s,a) for a in aa]
            for i,g in enumerate(groups):
                assert all(key(x.observation())==key(g[0][0].observation()) for x,p in g)
                assert key(g[0][0].observation())==key(flat[i][0].observation())
            scores=[np.full(len(g),mins[i]) for i,g in enumerate(groups)];di=0
        ar=[];dr=[]
        if audit:
            for i,(a,g,vals) in enumerate(zip(aa,groups,scores)):
                ar.append(dict(action_index=i,action=a.label(),chosen=i==idx,minimum=mins[i],maximum=float(vals.max()),delay_candidates=len(g),delay_ties=int(sum(vals==mins[i])),selected_delay_index=int(np.argmin(vals))))
                for j,((child,p),v) in enumerate(zip(g,vals)):
                    dr.append(dict(action_index=i,delay_index=j,value=float(v),minimizer=bool(v==mins[i]),selected=i==idx and j==di,
                                   delays=child.delay_draws[len(s.delay_draws):],observation_hash=hashlib.sha256(key(child.observation()).encode()).hexdigest()))
        info=dict(mode=mode,action=aa[idx].label(),action_index=idx,**action_dict(aa[idx]),next_value=mins[idx],minimum=mins[idx],
                  delay_candidates=len(groups[idx]) if audit or not compressed else None,
                  delay_ties=int(sum(scores[idx]==mins[idx])) if audit or not compressed else None,
                  equivalent_all_delays=compressed,selected_delay_index=di,action_rows=ar,delay_rows=dr)
    info.update(time=s.clock/4,end=end,exploration_probability=0. if force_greedy else exploration,
                new_delays=copy.deepcopy(c.delay_draws[len(s.delay_draws):]),
                received_before=obs,received_after_action=post['current'],received_next=c.observation())
    if audit:info.update(full_before=full_state(s),full_next=full_state(c))
    return c,info

def rollout(s,end,model,seed,greedy=False,audit=False,schedule=None,round_index=0):
    c=s.clone();rng=np.random.default_rng(seed);rows=[];first=None
    schedule=schedule or LEGACY_SCHEDULE
    start=c.clock/4;steps=int(end-start)
    if steps < 1 or steps != end-start:raise ValueError('rollout needs a positive integer decision horizon')
    while c.clock/4<end:
        index=len(rows);epsilon=schedule.probability(round_index,index,steps)
        c,r=step(c,end,model,rng,greedy,exploration=epsilon,audit=audit)
        r.update(round_index=round_index,rollout_start=start,rollout_step=index,rollout_steps=steps,
                 scheduled_exploration=epsilon,forced_greedy=greedy)
        rows.append(r)
        if first is None:first=c.clone()
    val,legs=liquidation(c,end,True)
    return dict(value=val,rows=rows,first=first,terminal=c,legs=legs,greedy_only=greedy,seed=seed)

def search(s,end,model,count=4,seed=0,audit=False,schedule=None,round_index=0):
    rr=[rollout(s,end,model,seed+101*j,greedy=j==0,audit=False,schedule=schedule,round_index=round_index) for j in range(count)]
    winner=int(np.argmax([r['value'] for r in rr]));win=rr[winner]
    if audit:
        # Reproduce the winning path with exhaustive per-step delay audit.
        replay=rollout(s,end,model,seed+101*winner,greedy=winner==0,audit=True,schedule=schedule,round_index=round_index)
        assert replay['value']==win['value'] and full_state(replay['first'])==full_state(win['first'])
        rr[winner]=win=replay
    return dict(value=win['value'],winner=winner,rollouts=rr,next=win['first'].clone())

def trajectory(root,end,model,seed,count=4,audit=False,schedule=None,round_index=0):
    """Replan at every retained transition. No resampling of the winning first step."""
    s=root.clone();rows=[];queries=[];observations=[]
    while s.clock/4<end:
        observations.append(s.observation());t=int(s.clock/4)
        q=search(s,end,model,count,stable_seed(f'{seed}:{t}:{end}'),audit,schedule=schedule,round_index=round_index)
        row=q['rollouts'][q['winner']]['rows'][0]
        row.update(winner=q['winner'],best_rollout_value=q['value'],rollout_values=[r['value'] for r in q['rollouts']])
        rows.append(row);queries.append(q);s=q['next']
    observations.append(s.observation());val,legs=liquidation(s,end,True)
    return dict(rows=rows,queries=queries,observations=observations,terminal=s,value=val,legs=legs)
