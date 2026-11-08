"""Causal reselection of all still-pending communication delays.

State interpretation: already occurred exchange/receipt events are fixed.
For each action, an adversary may reselect total delays of queue events that
have not occurred, conditioned on arrival strictly after the current clock.
This is an adversarial simulator, not an observation-only deployment policy.
Future alternatives that cannot affect the immediate successor are grouped,
retaining the lexicographically first valid total delay. No history is dropped.
"""
import copy,itertools,heapq,random
import numpy as np
import search
from network import predict

ORIGINAL_STEP=search.step

def event_identity(event):
    tick,priority,serial,kind,p=event
    if kind=='trade':return None
    if kind=='command':return 'outbound',p['sent_tick'],f"{p['kind']}:cmd{p['command_id']}"
    if kind=='market':return 'market',p['source_tick'],p['trade_id']
    if kind=='private':
        channel='fill' if p['kind']=='fill' else 'ack'
        return channel,p['source_tick'],f"{p['kind']}:order{p['order_id']}:v{p['version']}"
    raise ValueError(kind)

def pending_choices(s,group_future=True):
    choices=[]
    draw_lookup={(r['channel'],round(r['source_time']*4),r['event']):i for i,r in enumerate(s.delay_draws)}
    for event in sorted(s.queue,key=lambda e:e[2]):
        identity=event_identity(event)
        if identity is None:continue
        channel,source,event_name=identity
        if source<0:continue # Historical source declares warmup delays fixed at1.
        assert event[0]>s.clock, 'A pending event must be strictly in the future.'
        law=getattr(s.config,channel)
        support=sorted(d for d in law.values if source+4*d>s.clock)
        if not support:raise AssertionError('No causally admissible pending delay.')
        options=support
        if group_future:
            immediate=[d for d in support if source+4*d<=s.clock+4]
            future=[d for d in support if source+4*d>s.clock+4]
            options=immediate+future[:1]
        choices.append(dict(serial=event[2],channel=channel,source_tick=source,event=event_name,draw_index=draw_lookup[identity],support=support,options=options,original_arrival_tick=event[0]))
    return choices

def assign_pending(s,choices,delays,source_label):
    c=s.clone();by_serial={x['serial']:(x,d) for x,d in zip(choices,delays)};queue=[];audit=[]
    for e in c.queue:
        if e[2] not in by_serial:queue.append(e);continue
        x,d=by_serial[e[2]];arrival=x['source_tick']+4*d
        assert arrival>s.clock
        queue.append((arrival,e[1],e[2],e[3],e[4]))
        old=c.delay_draws[x['draw_index']];updated=dict(old,delay=d,arrival_time=arrival/4,source=source_label)
        c.delay_draws[x['draw_index']]=updated
        audit.append(dict(event=x['event'],channel=x['channel'],source_time=x['source_tick']/4,old_arrival_time=e[0]/4,chosen_delay=d,chosen_arrival_time=arrival/4,admissible_delays=x['support']))
    c.queue=queue;heapq.heapify(c.queue);audit.sort(key=lambda r:(r['source_time'],r['event']))
    return c,audit

def conditioned_random_pending(s,rng):
    choices=pending_choices(s,False);delays=[]
    for x in choices:
        law=getattr(s.config,x['channel']);weights=np.array([law.probabilities[law.values.index(d)] for d in x['support']],dtype=float);weights/=weights.sum()
        delays.append(int(rng.choice(x['support'],p=weights)))
    return assign_pending(s,choices,delays,'pending conditional random draw')

def successors(s,a,exhaustive=False):
    choices=pending_choices(s,not exhaustive);groups=[]
    shortcut=search.equivalent_delay_histories(s)
    for delays in itertools.product(*(x['options'] for x in choices)):
        parent,pending=assign_pending(s,choices,delays,'pending adversarial minimum')
        children=search.enumerate_successors(parent,a) if exhaustive or not shortcut else [search.transition(parent,a,'first')]
        for child,post in children:groups.append((child,post,pending,tuple(delays)))
    return groups,choices

def step(s,end,model,rng,force_greedy=False,exploration=.30,audit=False,exhaustive=False):
    if not 0<=exploration<=1:raise ValueError('exploration must be in [0,1]')
    obs=s.observation();actions=search.feasible_actions(obs)
    mode='greedy' if force_greedy or rng.random()>=exploration else 'exploratory'
    if mode=='exploratory':
        idx=int(rng.integers(len(actions)));parent,pending=conditioned_random_pending(s,rng)
        child,post=search.transition(parent,actions[idx],'random',seed=int(rng.integers(2**31-1)))
        value=float(predict(model,[search.record(child.observation(),end)])[0])
        info=dict(mode=mode,action=actions[idx].label(),action_index=idx,**search.action_dict(actions[idx]),next_value=value,minimum=None,delay_candidates=None,delay_ties=None,selected_delay_index=None,action_rows=[],delay_rows=[],pending_reselections=pending)
    else:
        groups=[];choices=None
        for action in actions:
            group,choices=successors(s,action,exhaustive);groups.append(group)
        flat=[row for group in groups for row in group]
        observations=[row[0].observation() for row in flat];keys=[search.key(o) for o in observations];unique={}
        for k,o in zip(keys,observations):
            if k not in unique:unique[k]=search.record(o,end)
        values=dict(zip(unique,predict(model,list(unique.values()))));vv=np.array([values[k] for k in keys]);scores=[];offset=0
        for group in groups:scores.append(vv[offset:offset+len(group)]);offset+=len(group)
        minima=[float(v.min()) for v in scores];idx=int(np.argmax(minima));di=int(np.argmin(scores[idx]));child,post,pending,chosen=groups[idx][di]
        action_rows=[];delay_rows=[]
        if audit:
            for i,(action,group,vals) in enumerate(zip(actions,groups,scores)):
                action_rows.append(dict(action_index=i,action=action.label(),chosen=i==idx,minimum=minima[i],maximum=float(vals.max()),delay_candidates=len(group),delay_ties=int(sum(vals==minima[i])),selected_delay_index=int(np.argmin(vals))))
                for j,((c,p,pending_row,assignment),value) in enumerate(zip(group,vals)):
                    delay_rows.append(dict(action_index=i,delay_index=j,value=float(value),minimizer=bool(value==minima[i]),selected=i==idx and j==di,pending_reselections=pending_row,new_delays=c.delay_draws[len(s.delay_draws):]))
        info=dict(mode=mode,action=actions[idx].label(),action_index=idx,**search.action_dict(actions[idx]),next_value=minima[idx],minimum=minima[idx],delay_candidates=len(groups[idx]),delay_ties=int(sum(scores[idx]==minima[idx])),selected_delay_index=di,action_rows=action_rows,delay_rows=delay_rows,pending_reselections=pending,pending_event_count=len(choices),pending_grouped_assignments=int(np.prod([len(x['options']) for x in choices],dtype=np.int64)),pending_full_assignments=int(np.prod([len(x['support']) for x in choices],dtype=np.int64)),unique_successor_observations=len(unique),equivalent_new_delays=search.equivalent_delay_histories(s),equivalent_all_delays=False)
    info.update(time=s.clock/4,end=end,exploration_probability=0. if force_greedy else exploration,new_delays=copy.deepcopy(child.delay_draws[len(s.delay_draws):]),received_before=obs,received_after_action=post['current'],received_next=child.observation(),adversary_semantics='causal_reselection_of_still_pending_events_v1')
    if audit:info.update(full_before=search.full_state(s),full_next=search.full_state(child))
    return child,info

def install():search.step=step
