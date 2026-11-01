"""Bounded full-depth, all-horizon sample-size study for the single-BILL toy.

The exact planner shares equivalent (time, quantity, endpoint) subproblems.
Cash is affine and cannot bind in the declared domain. This is not a stochastic
market experiment, truncated search, or a simulation of every complete path.
"""
from dataclasses import dataclass
from pathlib import Path
import argparse
import csv
import hashlib
import json
import time
import numpy as np

HERE=Path(__file__).resolve().parent
PROTOCOL=dict(timelines=[8,16,32,64],trajectory_budgets=[4,16,64,256],
              seeds=[20261101,20261102,20261103],updates=12000,batch_size=256,
              checkpoint_every=500,learning_rate=.003,hidden=16,
              convergence_rmse_usd=.3531,sustained_checkpoints=3,
              evaluation_trajectories=512,max_evaluation_states=512,
              max_evaluation_labels=2048,wall_seconds=600,
              state_split='70% train / 15% validation / 15% test; all horizons of a state stay together')

@dataclass(frozen=True,order=True)
class State:
    t:int
    cash_ticks:int
    q:int

class Market:
    def __init__(self,T):
        if T not in (4,8,16,32,64,128):raise ValueError('Unsupported bounded timeline')
        self.T=T;self.scale=4*T;self.slope=2/T;self.cap=4
        self.initial=State(0,1000*self.scale,0)
        # A deliberately loose lower bound valid even under repeated losing trades.
        self.cash_lower_bound=1000-4*100-T*.5
        assert self.cash_lower_bound>100 and 97+self.slope*3.75+.25<100
        self.W=np.full((T+1,T+1,5),np.nan)
        self.oracle_edges=0;self.boundaries=0
        started=time.perf_counter()
        for end in range(T+1):
            for q in range(5):
                self.W[end,end,q]=self.close_increment(end,q);self.boundaries+=1
            for t in range(end-1,-1,-1):
                for q in range(5):
                    vals=[]
                    for a in self.actions_q(q):
                        vals.append(self.cash_delta(t,a)+self.W[end,t+1,q+a]);self.oracle_edges+=1
                    self.W[end,t,q]=max(vals)
        self.oracle_seconds=time.perf_counter()-started
    @staticmethod
    def actions_q(q):return [0]+([1] if q<4 else [])+([-1] if q>0 else [])
    def price(self,t):return 95+self.slope*t
    def delta_ticks(self,t,a):
        return -a*(380*self.T+8*t+a*self.T) if a else 0
    def cash_delta(self,t,a):return self.delta_ticks(t,a)/self.scale
    def step(self,s,a):
        assert a in self.actions_q(s.q) and s.t<self.T
        # Strict through-limit crossing; strategic fills are at the limit.
        if a:
            limit=self.price(s.t)+a*.25
            print_price=self.price(s.t+(.25 if a>0 else .75))-a*.25
            assert print_price<limit if a>0 else print_price>limit
        result=State(s.t+1,s.cash_ticks+self.delta_ticks(s.t,a),s.q+a)
        assert result.cash_ticks>=0
        return result
    def close_increment(self,t,q):
        # q distinct, sequential buy prints, all after the endpoint.
        return (q*(381*self.T+8*t+6)+4*q*(q-1))/self.scale
    def close(self,s):return s.cash_ticks/self.scale+self.close_increment(s.t,s.q)
    def exact(self,s,end):return s.cash_ticks/self.scale+self.W[end,s.t,s.q]
    def features(self,s,end):
        return [(s.cash_ticks/self.scale-1000)/400,s.q/4,s.t/self.T,(end-s.t)/self.T]
    def path_count(self):
        counts=[1,0,0,0,0]
        for _ in range(self.T):
            nxt=[0]*5
            for q,n in enumerate(counts):
                for a in self.actions_q(q):nxt[q+a]+=n
            counts=nxt
        return sum(counts)
    def split(self,s):
        if s==self.initial:return 'train'
        value=int.from_bytes(hashlib.blake2b(f'{self.T}:{s.t}:{s.cash_ticks}:{s.q}'.encode(),digest_size=8).digest(),'big')%100
        return 'train' if value<70 else 'validation' if value<85 else 'test'

class Net:
    def __init__(self,seed):
        rng=np.random.default_rng(seed)
        self.p=[rng.normal(0,.35,(4,16)),rng.normal(0,.03,16),rng.normal(0,.05,16),np.zeros(1)]
    def forward(self,x):
        z=np.tanh(x@self.p[0]+self.p[1]);return z@self.p[2]+self.p[3][0],z
    def predict(self,x):return 1000+10*self.forward(x)[0]
    def copy_params(self):return [p.copy() for p in self.p]

def rollout(env,rng):
    s=env.initial;path=[s]
    for _ in range(env.T):
        aa=env.actions_q(s.q);s=env.step(s,aa[int(rng.integers(len(aa)))]);path.append(s)
    return path

def dataset(env,states):
    records=[(s,e) for s in sorted(states) for e in range(s.t,env.T+1)]
    x=np.array([env.features(s,e) for s,e in records]);y=np.array([env.exact(s,e) for s,e in records])
    h=np.array([e-s.t for s,e in records]);groups=[np.flatnonzero(h==k) for k in range(env.T+1)]
    return dict(records=records,x=x,y=y,h=h,groups=groups,states=len(states))

def evaluation_set(env,which):
    rng=np.random.default_rng(70001+env.T);states=set()
    for _ in range(PROTOCOL['evaluation_trajectories']):
        states.update(s for s in rollout(env,rng) if env.split(s)==which)
    states=sorted(states)
    if len(states)>PROTOCOL['max_evaluation_states']:
        indices=rng.choice(len(states),PROTOCOL['max_evaluation_states'],replace=False)
        states=[states[i] for i in sorted(indices)]
    data=dataset(env,states)
    # Bound evaluation cost, preserving all available horizons and split identities.
    take=[];per=max(1,PROTOCOL['max_evaluation_labels']//env.T)
    for group in data['groups']:
        take.extend(rng.choice(group,min(per,len(group)),replace=False).tolist())
    take=np.array(sorted(take),dtype=int)
    records=[data['records'][i] for i in take]
    x=data['x'][take];y=data['y'][take];h=data['h'][take]
    return dict(records=records,x=x,y=y,h=h,groups=[np.flatnonzero(h==k) for k in range(env.T+1)],states=len(states))

def metrics(net,data):
    diff=net.predict(data['x'])-data['y']
    return dict(rmse_usd=float(np.sqrt(np.mean(diff*diff))),
                balanced_rmse_usd=float(np.sqrt(np.mean([np.mean(diff[g]**2) for g in data['groups'] if len(g)]))),
                max_abs_usd=float(np.max(abs(diff))))

def policy_metrics(net,env):
    regrets=[];full_path=[];transitions=0
    for end in range(1,env.T+1):
        s=env.initial
        while s.t<end:
            aa=env.actions_q(s.q);next_states=[env.step(s,a) for a in aa]
            pred=net.predict(np.array([env.features(ns,end) for ns in next_states]))
            idx=int(np.argmax(pred));s=next_states[idx];transitions+=len(aa)
            if end==env.T:full_path.append(aa[idx])
        regrets.append(env.exact(env.initial,end)-env.close(s))
    assert min(regrets)>-1e-8
    return dict(full_horizon_regret_usd=regrets[-1],mean_horizon_regret_usd=float(np.mean(regrets)),
                worst_horizon_regret_usd=max(regrets),full_horizon_actions=full_path,
                evaluation_candidate_transitions=transitions)

def fit(env,train,val,test,seed,deadline):
    net=Net(seed);rng=np.random.default_rng(seed^991)
    x=train['x'];target=(train['y']-1000)/10
    groups=train['groups'];n=len(x)
    assert all(len(g) for g in groups)
    full_weights=np.array([1/((env.T+1)*len(groups[h])) for h in train['h']])
    m=[np.zeros_like(p) for p in net.p];v=[np.zeros_like(p) for p in net.p]
    curve=[];best_loss=float('inf');best_params=None;best_update=0
    first_threshold=None;consecutive=0;sustained=None
    started=time.perf_counter()
    def measure(update):
        nonlocal best_loss,best_params,best_update,consecutive,first_threshold,sustained
        tm=metrics(net,train);vm=metrics(net,val)
        curve.append(dict(update=update,train=tm,validation=vm))
        if vm['rmse_usd']<best_loss:
            best_loss=vm['rmse_usd'];best_params=net.copy_params();best_update=update
        if vm['rmse_usd']<=PROTOCOL['convergence_rmse_usd']:
            if first_threshold is None:first_threshold=update
            consecutive+=1
            if consecutive>=PROTOCOL['sustained_checkpoints'] and sustained is None:sustained=update
        else:consecutive=0
    measure(0)
    for step in range(1,PROTOCOL['updates']+1):
        if step%500==0 and time.perf_counter()>deadline:raise TimeoutError('Declared study wall budget exhausted')
        if n<=PROTOCOL['batch_size']:
            xx=x;yy=target;ww=full_weights
        else:
            hs=rng.integers(env.T+1,size=PROTOCOL['batch_size'])
            ids=np.array([groups[h][int(rng.integers(len(groups[h])))] for h in hs])
            xx=x[ids];yy=target[ids];ww=1/PROTOCOL['batch_size']
        pred,z=net.forward(xx);d=2*ww*(pred-yy)
        dz=d[:,None]*net.p[2][None,:]*(1-z*z)
        grads=[xx.T@dz,dz.sum(0),z.T@d,np.array([d.sum()])]
        rate=PROTOCOL['learning_rate']*(1 if step<=6000 else .2)
        for k,g in enumerate(grads):
            m[k]=.9*m[k]+.1*g;v[k]=.999*v[k]+.001*g*g
            net.p[k]-=rate*(m[k]/(1-.9**step))/(np.sqrt(v[k]/(1-.999**step))+1e-8)
        if step%PROTOCOL['checkpoint_every']==0:measure(step)
    final_metrics=metrics(net,train)
    net.p=best_params
    # Test is evaluated once, after selecting a checkpoint using validation only.
    result=dict(best_update=best_update,first_validation_threshold_update=first_threshold,
                sustained_validation_threshold_update=sustained,train=metrics(net,train),
                validation=metrics(net,val),test=metrics(net,test),final_update_train=final_metrics,
                curve=curve,policy=policy_metrics(net,env),fit_seconds=time.perf_counter()-started,
                selected_parameters={k:p.tolist() for k,p in zip(['W','b','w','c'],net.p)})
    result['confirmed']=bool(sustained is not None and result['test']['rmse_usd']<=PROTOCOL['convergence_rmse_usd'])
    return result

def verify_original():
    original=json.loads((HERE/'data.json').read_text());env=Market(4)
    error=max(abs(env.exact(State(r['t'],round(r['cash']*16),r['q']),r['end'])-r['target_liquidation']) for r in original['labels'])
    assert error<1e-9 and env.path_count()==35
    assert abs(env.exact(env.initial,4)-1009.5)<1e-9
    return dict(original_labels=len(original['labels']),max_error=error,root_complete_paths=35)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=HERE/'longer_results');parser.add_argument('--timelines',type=int,nargs='+');args=parser.parse_args()
    if args.timelines:PROTOCOL['timelines']=args.timelines
    args.output.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter();deadline=start+PROTOCOL['wall_seconds']
    result=dict(protocol=PROTOCOL,original_check=verify_original(),markets=[],runs=[],status='running')
    result['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    def save():
        temp=args.output/'study.tmp';temp.write_text(json.dumps(result,indent=2,allow_nan=False));temp.replace(args.output/'study.json')
    save()
    try:
        for T in PROTOCOL['timelines']:
            env=Market(T);val=evaluation_set(env,'validation');test=evaluation_set(env,'test')
            assert {s for s,e in val['records']}.isdisjoint({s for s,e in test['records']})
            result['markets'].append(dict(T=T,slope=env.slope,maturity=2.5*T,oracle_edges=env.oracle_edges,
                oracle_boundaries=env.boundaries,oracle_seconds=env.oracle_seconds,
                root_complete_paths=str(env.path_count()),optimal_root_liquidation=env.exact(env.initial,T),
                validation_labels=len(val['y']),test_labels=len(test['y']),cash_lower_bound=env.cash_lower_bound))
            for seed in PROTOCOL['seeds']:
                rng=np.random.default_rng(seed^12345);states=set();generated=0
                for count in PROTOCOL['trajectory_budgets']:
                    while generated<count:
                        states.update(s for s in rollout(env,rng) if env.split(s)=='train');generated+=1
                    train=dataset(env,states)
                    assert all(env.split(s)=='train' for s,e in train['records'])
                    run=dict(T=T,seed=seed,trajectories=count,training_transitions=count*T,
                             unique_training_states=len(states),training_labels=len(train['y']),
                             exact_label_queries=len(train['y']),**fit(env,train,val,test,seed,deadline))
                    result['runs'].append(run);save()
                    print(json.dumps({k:run[k] for k in ['T','seed','trajectories','training_labels','best_update','confirmed']}|
                                     {'train_rmse':run['train']['rmse_usd'],'val_rmse':run['validation']['rmse_usd'],
                                      'test_rmse':run['test']['rmse_usd'],'regret':run['policy']['full_horizon_regret_usd'],
                                      'elapsed':round(time.perf_counter()-start,2)}),flush=True)
        result['status']='completed'
    except TimeoutError as exc:result['status']='budget_exhausted';result['reason']=str(exc)
    result['wall_seconds']=time.perf_counter()-start;save()
    fields=['T','seed','trajectories','training_transitions','unique_training_states','training_labels','best_update','first_validation_threshold_update','sustained_validation_threshold_update','confirmed','train_rmse','validation_rmse','test_rmse','full_horizon_regret_usd','mean_horizon_regret_usd','fit_seconds']
    with (args.output/'summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in result['runs']:
            flat={k:r.get(k) for k in fields};flat.update(train_rmse=r['train']['rmse_usd'],validation_rmse=r['validation']['rmse_usd'],test_rmse=r['test']['rmse_usd'],full_horizon_regret_usd=r['policy']['full_horizon_regret_usd'],mean_horizon_regret_usd=r['policy']['mean_horizon_regret_usd']);writer.writerow(flat)
    print(json.dumps(dict(status=result['status'],runs=len(result['runs']),wall_seconds=result['wall_seconds'])),flush=True)

if __name__=='__main__':main()
