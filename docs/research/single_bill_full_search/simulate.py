"""Four-decision, USD-only diagnostic. NumPy is the only dependency.

This is a new reduced experiment, not the old delayed 44-input BILL model.
All legal action continuations are enumerated. Network scores classify
branches; they never supply full-depth labels.
"""
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import numpy as np

ROOT = Path(__file__).resolve().parent
CFG = dict(T=4, depth_search=5, initial_usd=1000., initial_price=95.,
           slope=.5, face=100., maturity=10., spread=.25,
           trade_size=1., buy_offset=.25, sell_offset=.75, max_inventory=4,
           action_size=1, fee=0., seed=20261101, hidden=16,
           output_scale=.01, updates=12000, learning_rate=.003,
           positive_weight=1., loss_aversion=10., tail_last_interval=8)

def mid(t): return CFG['initial_price']+CFG['slope']*t
def utility(value):
    g=value/CFG['initial_usd']-1
    return CFG['positive_weight']*max(g,0)-CFG['loss_aversion']*max(-g,0)

TRADES=[]
for k in range(CFG['tail_last_interval']+1):
    for side, offset, sign in [('sell',.25,-1),('buy',.75,1)]:
        time=k+offset
        TRADES.append(dict(id=f'{side}-{k}', interval=k,time=time,side=side,
                           mid=mid(time),price=mid(time)+sign*CFG['spread'],
                           size=1,region='strategy' if k<CFG['T'] else 'closing tail'))

@dataclass(frozen=True)
class State:
    t:int
    cash:float
    q:int

def state_dict(s):
    return dict(**asdict(s),price=mid(s.t),economic_usd=s.cash+s.q*CFG['face'],
                pending_requests=0,live_orders=0)

def actions(s):
    out=['wait']
    if s.q<CFG['max_inventory'] and s.cash>=mid(s.t)+CFG['spread']:
        out.append('buy')
    if s.q>0: out.append('sell')
    return out

def transition(s,a):
    assert a in actions(s) and s.t<CFG['T']
    sign={'wait':0,'buy':1,'sell':-1}[a]
    limit=mid(s.t)+sign*CFG['spread'] if sign else None
    trade=None
    if sign:
        opposite='sell' if sign>0 else 'buy'
        trade=next(tr for tr in TRADES if tr['interval']==s.t and tr['side']==opposite)
        assert (trade['price']<limit if sign>0 else trade['price']>limit)
        assert trade['size']>=abs(sign)
    ns=State(s.t+1,round(s.cash-sign*(limit or 0),8),s.q+sign)
    assert ns.cash>=0 and 0<=ns.q<=CFG['max_inventory']
    return ns,dict(action=a,signed_quantity=sign,limit=limit,trade_id=trade['id'] if trade else '',
                   trade_price=trade['price'] if trade else None,
                   fill_price=limit,fill_time=trade['time'] if trade else None,
                   before=state_dict(s),after=state_dict(ns))

@lru_cache(None)
def close(s):
    cash=s.cash;q=s.q;trace=[]
    for tr in TRADES:
        if q==0:break
        if tr['time']>s.t and tr['side']=='buy':
            amount=min(q,tr['size'])
            cash+=amount*tr['price'];q-=amount
            trace.append(dict(trade_id=tr['id'],time=tr['time'],quantity=amount,
                              price=tr['price'],proceeds=amount*tr['price'],cash_after=cash))
    assert q==0, 'Incomplete closing must not become a zero label'
    # Independent closed-form check for this repeating, linearly rising tape.
    independent=s.cash+s.q*(mid(s.t)+.75*CFG['slope']+CFG['spread'])+CFG['slope']*s.q*(s.q-1)/2
    assert abs(cash-independent)<1e-9
    return dict(liquidation=cash,utility=utility(cash),trace=trace,
                close_time=trace[-1]['time'] if trace else s.t,
                economic_usd=s.cash+s.q*CFG['face'])

@lru_cache(None)
def enumerate_paths(s,end):
    assert s.t<=end<=CFG['T']
    if s.t==end:return [dict(steps=[],terminal=state_dict(s),**close(s))]
    out=[]
    for a in actions(s):
        ns,step=transition(s,a)
        for child in enumerate_paths(ns,end):
            out.append(dict(child,steps=[step]+child['steps']))
    return out

def best(s,end):
    # Stable tie-break: wait, then buy, then sell in depth-first enumeration.
    paths=enumerate_paths(s,end)
    return max(paths,key=lambda p:p['utility'])

@lru_cache(None)
def bellman(s,end):
    if s.t==end:return close(s)['utility']
    return max(bellman(transition(s,a)[0],end) for a in actions(s))

def features(s,end):
    return [(s.cash-CFG['initial_usd'])/400,s.q/4,s.t/4,(end-s.t)/4]

class Network:
    def __init__(self):
        rng=np.random.default_rng(CFG['seed'])
        self.p=[rng.normal(0,.35,(4,16)),rng.normal(0,.03,(16,)),
                rng.normal(0,.05,(16,)),np.zeros(1)]
    def forward(self,x):
        z=np.tanh(x@self.p[0]+self.p[1]);return z@self.p[2]+self.p[3][0],z
    def predict(self,x):
        return CFG['initial_usd']*(1+self.forward(np.asarray(x))[0]*CFG['output_scale'])
    def export(self):return {k:v.tolist() for k,v in zip(['W','b','w','c'],self.p)}

def classify(path,end,network):
    result=[]
    for step in path['steps']:
        s=State(**{k:step['before'][k] for k in ['t','cash','q']})
        aa=actions(s)
        scores=[float(network.predict(features(transition(s,a)[0],end))) for a in aa]
        greedy=aa[int(np.argmax(scores))]
        result.append(dict(step,greedy_action=greedy,
                           step_type='greedy' if step['action']==greedy else 'exploration',
                           candidate_scores=dict(zip(aa,scores))))
    return dict(path,steps=result,path=' / '.join(x['action'] for x in result))

def main():
    assert CFG['T']==4 and CFG['depth_search']>CFG['T'], 'This workbook fixture requires four steps and full-depth search'
    initial=Network();model=Network()
    root=State(0,1000.,0)
    levels={0:{root}}
    for t in range(CFG['T']):
        levels[t+1]={transition(s,a)[0] for s in levels[t] for a in actions(s)}
    labels=[]
    for t,states in levels.items():
        for s in sorted(states,key=lambda s:(s.q,s.cash)):
            for end in range(t,CFG['T']+1):
                p=best(s,end)
                assert abs(p['utility']-bellman(s,end))<1e-12
                labels.append(dict(id=f'R{len(labels)+1:03}',**state_dict(s),end=end,h=end-t,
                                   target=p['utility'],target_liquidation=p['liquidation'],
                                   best_path=' / '.join(x['action'] for x in p['steps']),
                                   features=features(s,end),initial_prediction=float(initial.predict(features(s,end))),
                                   paths_searched=len(enumerate_paths(s,end))))
    x=np.array([r['features'] for r in labels])
    y=(np.array([r['target_liquidation'] for r in labels])/CFG['initial_usd']-1)/CFG['output_scale']
    # Every horizon receives equal total weight, including the h=0 boundary.
    counts={h:sum(r['h']==h for r in labels) for h in range(5)}
    weights=np.array([1/(5*counts[r['h']]) for r in labels])
    curve=[];moment=[np.zeros_like(p) for p in model.p];variance=[np.zeros_like(p) for p in model.p]
    def metrics(update):
        predicted=model.predict(x);target=np.array([r['target_liquidation'] for r in labels])
        residual=predicted-target
        curve.append(dict(update=update,mse=float(np.mean(residual**2)),
                          balanced_mse=float(np.sum(weights*residual**2)),
                          rmse_usd=float(np.sqrt(np.mean(residual**2))),
                          max_abs_utility=max(abs(utility(float(a))-utility(float(b))) for a,b in zip(predicted,target))))
    metrics(0)
    gradient_error=0.
    for update in range(1,CFG['updates']+1):
        pred,z=model.forward(x);d=2*weights*(pred-y)
        dw=z.T@d;dc=np.array([d.sum()]);dz=d[:,None]*model.p[2][None,:]*(1-z*z)
        grads=[x.T@dz,dz.sum(0),dw,dc]
        if update==1:
            for pi,index in [(0,(0,0)),(1,(0,)),(2,(0,)),(3,(0,))]:
                old=model.p[pi][index];eps=1e-6
                model.p[pi][index]=old+eps;plus=np.sum(weights*(model.forward(x)[0]-y)**2)
                model.p[pi][index]=old-eps;minus=np.sum(weights*(model.forward(x)[0]-y)**2)
                model.p[pi][index]=old
                gradient_error=max(gradient_error,abs((plus-minus)/(2*eps)-grads[pi][index]))
            assert gradient_error<1e-7
        # A fixed Adam schedule, with a smaller final learning rate.
        rate=CFG['learning_rate']*(1 if update<=6000 else .2)
        for k,g in enumerate(grads):
            moment[k]=.9*moment[k]+.1*g;variance[k]=.999*variance[k]+.001*g*g
            model.p[k]-=rate*(moment[k]/(1-.9**update))/(np.sqrt(variance[k]/(1-.999**update))+1e-8)
        if update in [1,25,100,250,500,1000,2000,4000,6000,8000,10000,12000]:metrics(update)
    for r,p in zip(labels,model.predict(x)):
        r.update(final_prediction=float(p),sample_weight=1/(5*counts[r['h']]))
    # Receding full-depth search on the first 0..T trajectory, with frozen initial net.
    s=root;searches=[];trajectory=[]
    while s.t<CFG['T']:
        candidates=[classify(p,4,initial) for p in enumerate_paths(s,4)]
        winner=max(range(len(candidates)),key=lambda i:candidates[i]['utility'])
        for k,p in enumerate(candidates):p.update(id=f't{s.t}-{k+1:03}',kept=k==winner)
        chosen=candidates[winner];a=chosen['steps'][0]['action']
        searches.append(dict(t=s.t,root=state_dict(s),candidates=candidates,kept=chosen['id']))
        trajectory.append(dict(**state_dict(s),end=4,h=4-s.t,
                               initial_prediction=float(initial.predict(features(s,4))),
                               final_prediction=float(model.predict(features(s,4))),
                               target=chosen['utility'],target_liquidation=chosen['liquidation'],
                               current_close=close(s),action=a,kept=chosen['id']))
        s,_=transition(s,a)
    trajectory.append(dict(**state_dict(s),end=4,h=0,
                           initial_prediction=float(initial.predict(features(s,4))),
                           final_prediction=float(model.predict(features(s,4))),
                           target=close(s)['utility'],target_liquidation=close(s)['liquidation'],
                           current_close=close(s),action='terminal',kept=''))
    assert all(abs(r['target']-trajectory[-1]['target'])<1e-12 for r in trajectory)
    pairs=[]
    for t1 in range(4):
        r=trajectory[t1];s0=State(t1,r['cash'],r['q'])
        for end in range(t1+1,5):
            p=classify(best(s0,end),end,initial)
            states=[State(**{k:st['before'][k] for k in ['t','cash','q']}) for st in p['steps']]
            states.append(State(**{k:p['terminal'][k] for k in ['t','cash','q']}))
            for s in states:
                assert abs(best(s,end)['utility']-p['utility'])<1e-12
            pairs.append(dict(id=f'{t1}-{end}',t1=t1,t2=end,**p,
                              states=[dict(**state_dict(s),h=end-s.t,
                                           initial_prediction=float(initial.predict(features(s,end))),
                                           final_prediction=float(model.predict(features(s,end)))) for s in states]))
    checks=dict(reachable_states_by_time={t:len(v) for t,v in levels.items()},
                labels=len(labels),horizon_counts=counts,pairs=len(pairs),
                search_candidates=[len(s['candidates']) for s in searches],
                unique_trade_ids=len({tr['id'] for tr in TRADES})==len(TRADES),
                gradient_max_error=gradient_error,terminal_liquidation=trajectory[-1]['target_liquidation'],
                final_loss=curve[-1],independent_closing_checks=close.cache_info().currsize,
                all_targets_match_independent_bellman=True,
                all_selected_suffixes_share_terminal_target=True)
    print(json.dumps(curve[-1]))
    assert curve[-1]['rmse_usd']<.50
    result=dict(config=CFG,trades=TRADES,trajectory=trajectory,searches=searches,pairs=pairs,
                labels=labels,training_curve=curve,initial_network=initial.export(),
                final_network=model.export(),checks=checks,
                implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (ROOT/'data.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    (ROOT/'validation.json').write_text(json.dumps(checks,indent=2))
    print(json.dumps(checks,indent=2))

if __name__=='__main__':main()
