"""Fresh two-round training of the clarified single-trajectory algorithm."""
from pathlib import Path
import argparse,json,gzip,time,pickle
import numpy as np
from search import *
from network import Transformer,batch,predict
from exploration import ExplorationSchedule
ROOT=Path(__file__).resolve().parent
HORIZON=10
def configuration(**kwargs):return Config(horizon=HORIZON,tail_end=HORIZON+10,**kwargs)

def write_json(name,data):(ROOT/name).write_text(json.dumps(data,indent=2,allow_nan=False))
def save_gz(name,data):
    # Serialize and compress fully before replacing a checkpoint. This also
    # makes interrupted writes detectable before any later resume.
    blob=gzip.compress(json.dumps(data,allow_nan=False).encode())
    p=ROOT/name;tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_bytes(blob)
    assert gzip.decompress(tmp.read_bytes())==gzip.decompress(blob)
    tmp.replace(p)
def load_gz(name):
    with gzip.open(ROOT/name,'rt') as f:return json.load(f)

def make_roots():
    seeds={'train':[111,222,333,444],'validation':[555,666],'test':[777,888]};roots=[];owner={}
    for split,ss in seeds.items():
        for seed in ss:
            s=PathSimulator(configuration(seed=seed));s.snapshot('before');rng=np.random.default_rng(seed)
            for t in range(HORIZON):
                for end in range(t+1,HORIZON+1):
                    k=key(s.observation())+str(end)
                    if k not in owner:
                        owner[k]=split;roots.append(dict(id=len(roots),split=split,episode=seed,time=t,end=end,state=s.clone()))
                aa=feasible_actions(s.observation());a=aa[int(rng.integers(1,len(aa)))] if t==0 else aa[int(rng.integers(len(aa)))]
                s,_=transition(s,a,'random',seed=int(rng.integers(2**31-1)))
    (ROOT/'roots.pkl.gz').write_bytes(gzip.compress(pickle.dumps(roots)))
    print('ROOTS',len(roots),{x:sum(r['split']==x for r in roots) for x in seeds},flush=True)
    return roots

def labels(roots,teacher,stage,schedule):
    path=ROOT/f'labels_stage{stage}.json.gz'
    if path.exists():return load_gz(path.name)
    raw=[];traces=[];start=time.time()
    for i,root in enumerate(roots):
        tr=trajectory(root['state'],root['end'],teacher,stable_seed(f'train:{stage}:{root["id"]}'),count=4,schedule=schedule,round_index=stage)
        for j,obs in enumerate(tr['observations']):
            raw.append(dict(root_id=root['id'],split=root['split'],episode=root['episode'],time=int(obs['current']['time']),end=root['end'],target=tr['value'],observation=obs,
                            action=tr['rows'][j]['action'] if j<len(tr['rows']) else 'terminal',main_final_value=tr['value']))
        traces.append(dict(root_id=root['id'],split=root['split'],start=root['time'],end=root['end'],value=tr['value'],rows=tr['rows']))
        if i%10==0:print('TARGETS',stage,i+1,'/',len(roots),'seconds',round(time.time()-start,1),flush=True)
    # Keep every retained trajectory state, including its endpoint. Avoid exact
    # received-history/horizon leakage between episode splits; within a split,
    # independent trajectory outcomes remain separate Monte Carlo labels.
    ownership={};out=[];dropped={x:0 for x in ['train','validation','test']}
    for split in ['train','validation','test']:
        for r in raw:
            if r['split']!=split:continue
            k=key(r['observation'])+str(r['end'])
            if k in ownership and ownership[k]!=split:dropped[split]+=1;continue
            ownership[k]=split;r['id']=len(out);out.append(r)
    save_gz(path.name,out);save_gz(f'trajectories_stage{stage}.json.gz',traces)
    write_json(f'dataset_stage{stage}.json',dict(root_count=len(roots),samples=len(out),counts={x:sum(r['split']==x for r in out) for x in dropped},cross_split_duplicates_dropped=dropped,
        terminal_samples=sum(r['time']==r['end'] for r in out),target_seconds=time.time()-start))
    return out

def metrics(model,records):
    y=np.array([r['target'] for r in records]);p=predict(model,records);err=p-y
    return dict(rmse=float(np.sqrt(np.mean(err*err))),mae=float(np.mean(abs(err))),max_abs=float(max(abs(err))),n=len(records))

def fit(model,labels,stage,epochs=100):
    rr=[dict(**record(r['observation'],r['end']),target=r['target'],split=r['split'],id=r['id']) for r in labels]
    train=[r for r in rr if r['split']=='train'];val=[r for r in rr if r['split']=='validation'];test=[r for r in rr if r['split']=='test']
    history=[];rng=np.random.default_rng(900+stage);best=float('inf');best_epoch=0;best_weights=None
    model.adam_m={k:np.zeros_like(v) for k,v in model.p.items()};model.adam_v={k:np.zeros_like(v) for k,v in model.p.items()};model.step=0
    before=dict(train=metrics(model,train),validation=metrics(model,val),test=metrics(model,test),baseline_test=metrics(None,test));start=time.time()
    for epoch in range(epochs+1):
        if epoch:
            order=rng.permutation(len(train));lr=.001*(.35+.65*(1-epoch/epochs))
            for start_i in range(0,len(order),16):
                group=[train[i] for i in order[start_i:start_i+16]];x,mask,c=batch(group);y=np.array([(r['target']-r['baseline'])/20 for r in group],np.float32)
                model.update(x,mask,c,y,lr)
        if epoch%2==0:
            tr=metrics(model,train);va=metrics(model,val)
            history.append(dict(stage=stage,epoch=epoch,train_rmse=tr['rmse'],validation_rmse=va['rmse']))
            if va['rmse']<best:best=va['rmse'];best_epoch=epoch;best_weights={k:v.copy() for k,v in model.p.items()}
            if epoch%10==0:print('FIT',stage,epoch,'train',round(tr['rmse'],4),'val',round(va['rmse'],4),'seconds',round(time.time()-start,1),flush=True)
    model.p=best_weights;model.cache.clear();model.save(ROOT/f'weights_stage{stage}.npz')
    s=PathSimulator(configuration(seed=20261103));s.snapshot('before')
    greedy=rollout(s,HORIZON,model,280031254,greedy=True)
    result=dict(stage=stage,epochs=epochs,best_epoch=best_epoch,before=before,after=dict(train=metrics(model,train),validation=metrics(model,val),test=metrics(model,test)),
                greedy_liquidation=greedy['value'],greedy_actions=[r['action'] for r in greedy['rows']],seconds=time.time()-start)
    write_json(f'fit_stage{stage}.json',dict(summary=result,history=history));return result,history

def audit(model,schedule,round_index):
    s=PathSimulator(configuration(seed=20261103));s.snapshot('before');tr=trajectory(s,HORIZON,model,20261103,count=8,audit=True,schedule=schedule,round_index=round_index)
    for row in tr['rows']:row['network_value']=float(predict(model,[record(row['received_before'],HORIZON)])[0])
    queries=[]
    for t,q in enumerate(tr['queries']):
        rr=[]
        for j,r in enumerate(q['rollouts']):
            rr.append(dict(rollout=j,value=r['value'],selected=j==q['winner'],first_action=r['rows'][0]['action'],greedy_only=r['greedy_only'],seed=r['seed'],rows=r['rows'],
                           terminal_cash=r['terminal'].exchange_cash/32,terminal_bills=r['terminal'].exchange_bills,legs=r['legs']))
        queries.append(dict(time=t,end=HORIZON,winner=q['winner'],value=q['value'],rollouts=rr))
    greedy=rollout(s,HORIZON,model,280031254,greedy=True,audit=True,schedule=schedule,round_index=round_index)
    gr=dict(rows=greedy['rows'],value=greedy['value'],cash=greedy['terminal'].exchange_cash/32,bills=greedy['terminal'].exchange_bills,
            legs=greedy['legs'],terminal_state=full_state(greedy['terminal']))
    return dict(main=tr['rows'],queries=queries,greedy=gr,terminal_state=full_state(tr['terminal']),terminal_network_value=float(predict(model,[record(tr['terminal'].observation(),HORIZON)])[0]),main_liquidation=dict(value=tr['value'],cash=tr['terminal'].exchange_cash/32,bills=tr['terminal'].exchange_bills,legs=tr['legs']))

def main(schedule,rounds=2,epochs=100):
    started=time.time();roots=make_roots();model=Transformer(seed=17);model.save(ROOT/'initial_transformer.npz');summaries=[];hist=[]
    for stage in range(rounds):
        ll=labels(roots,model,stage,schedule)
        if (ROOT/f'fit_stage{stage}.json').exists():
            z=json.loads((ROOT/f'fit_stage{stage}.json').read_text());summary=z['summary'];history=z['history'];model.load(ROOT/f'weights_stage{stage}.npz')
        else:summary,history=fit(model,ll,stage,epochs)
        summaries.append(summary);hist.extend(history)
    model.save(ROOT/'trained_transformer.npz');print('AUDIT START',flush=True);result=audit(model,schedule,rounds-1)
    preds=predict(model,[record(r['observation'],r['end']) for r in ll]);targets=[dict(id=r['id'],split=r['split'],episode=r['episode'],root_id=r['root_id'],time=r['time'],end=r['end'],target=r['target'],prediction=float(p),baseline=record(r['observation'],r['end'])['baseline'],action=r['action']) for r,p in zip(ll,preds)]
    result.update(training=summaries,loss_history=hist,targets=targets,architecture=dict(parameters=model.parameter_count,layers=2,heads=4,d_model=64,ff=128,input_features=60),
                  exploration_schedule=schedule.table(rounds),configuration=dict(version=5,horizon=HORIZON,cap=10,delays=[1,2,3],probabilities=[.6,.3,.1],exploration=schedule.to_dict(),
                    exploration_action='uniform over feasible actions',training_rollouts=4,audit_rollouts=8,delay_support='exact, grouped by identical successor observation',
                    delay_tie_break='lexicographically first generated-delay vector, 1 before 2 before 3',action_tie_break='first feasible action: WAIT then ascending buy quantity then ascending sell quantity',
                    target='realized final liquidation of retained replanning trajectory for every visited history, including horizon zero',training_rounds=rounds,epochs=epochs,seed=17,
                    timeline_origin='each search root',single_step_rate='midpoint of round-scaled first and last probabilities, with floor',forced_greedy_rollout=0),elapsed_seconds=time.time()-started)
    write_json('results.json',result);print('COMPLETE',json.dumps(dict(parameters=model.parameter_count,training=summaries,liquidation=result['main_liquidation']['value'],seconds=time.time()-started)),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    operation=parser.add_mutually_exclusive_group()
    operation.add_argument('--fresh',action='store_true',help='Regenerate labels and retrain from the initialized Transformer.')
    operation.add_argument('--audit-only',action='store_true',help='Recreate the audit using existing trained weights and results.')
    parser.add_argument('--output-dir',type=Path,default=ROOT,help='Isolated checkpoint and result directory; defaults to this code directory.')
    parser.add_argument('--horizon',type=int,default=10)
    parser.add_argument('--rounds',type=int,default=2)
    parser.add_argument('--epochs',type=int,default=100)
    parser.add_argument('--exploration-mode',choices=['fixed','rounds','timeline','both'],default='both')
    parser.add_argument('--exploration-constant',type=float,default=.30)
    parser.add_argument('--exploration-first',type=float,default=.50)
    parser.add_argument('--exploration-last',type=float,default=.10)
    parser.add_argument('--exploration-round-decay',type=float,default=.50)
    parser.add_argument('--exploration-floor',type=float,default=.05)
    args=parser.parse_args()
    HORIZON=args.horizon
    if HORIZON < 1:parser.error('horizon must be positive')
    if args.rounds < 1 or args.epochs < 1:parser.error('rounds and epochs must be positive')
    ROOT=args.output_dir.resolve();ROOT.mkdir(parents=True,exist_ok=True)
    schedule=ExplorationSchedule(mode=args.exploration_mode,constant=args.exploration_constant,first=args.exploration_first,last=args.exploration_last,
                                 round_decay=args.exploration_round_decay,floor=args.exploration_floor)
    config=dict(version=5,horizon=HORIZON,rounds=args.rounds,epochs=args.epochs,exploration=schedule.to_dict(),seed=17)
    config_path=ROOT/'run_config.json'
    if config_path.exists() and not args.fresh and json.loads(config_path.read_text())!=config:
        parser.error('Existing run configuration differs. Use a new --output-dir or --fresh; checkpoints must not be mixed.')
    if not config_path.exists() and not args.fresh and any(ROOT.glob('fit_stage*.json')):
        parser.error('Checkpoints have no saved configuration. Use a new --output-dir or --fresh.')
    if args.audit_only:
        if not config_path.exists():parser.error('--audit-only requires the matching saved run_config.json')
        model=Transformer();model.load(ROOT/'trained_transformer.npz');data=json.loads((ROOT/'results.json').read_text());data.update(audit(model,schedule,args.rounds-1));write_json('results.json',data)
    else:
        if args.fresh:
            for pattern in ['labels_stage*.json.gz','trajectories_stage*.json.gz','dataset_stage*.json','fit_stage*.json','weights_stage*.npz','trained_transformer.npz','results.json']:
                for p in ROOT.glob(pattern):p.unlink()
        write_json('run_config.json',config)
        main(schedule,args.rounds,args.epochs)
