"""Exact v5 search/training protocol with horizon adapter and parallel roots.

Preserves all start/end roots, full observable histories, retained endpoints,
per-step replanning, whole winning transitions, seed17 initialization, Adam,
validation selection, split filtering, and original exploration schedules.
Engineering changes: safe append-only clone sharing, independent root workers,
root checkpoints, and no persistence of discarded inner search paths. Float32
numerics may depend on inference cache batching; short-horizon regression is
required. This is still the simulator-assisted v5 research rule, not a causal
observation-only live policy.
"""
from pathlib import Path
import argparse, gzip, json, multiprocessing as mp, time, hashlib, sys, os
import numpy as np
import run, search
import pending_adversary
DELAY_MODE=os.environ.get('KEEP_LEASE_DELAY_MODE','adversarial')
if DELAY_MODE not in ('adversarial','stochastic'): raise ValueError(DELAY_MODE)
if DELAY_MODE=='stochastic':
    import stochastic_delays
    stochastic_delays.install()
else: pending_adversary.install()
from network import Transformer, predict
from exploration import ExplorationSchedule
from fast_exact import FastPathSimulator

MODEL=None; STAGE=0; SCHEDULE=None; ROLLOUTS=4; JOB_DIR=None

def initialize(weights,stage,schedule,rollouts,job_dir):
    global MODEL,STAGE,SCHEDULE,ROLLOUTS,JOB_DIR
    MODEL=Transformer();MODEL.load(weights);STAGE=stage
    SCHEDULE=ExplorationSchedule(**schedule);ROLLOUTS=rollouts;JOB_DIR=Path(job_dir)

def lean_trajectory(root,end,model,seed,count,schedule,round_index):
    s=root.clone();observations=[];rows=[]
    while s.clock/4<end:
        observations.append(s.observation());t=int(s.clock/4)
        q=search.search(s,end,model,count,search.stable_seed(f'{seed}:{t}:{end}'),False,schedule,round_index)
        row=q['rollouts'][q['winner']]['rows'][0]
        row.update(winner=q['winner'],best_rollout_value=q['value'],rollout_values=[r['value'] for r in q['rollouts']])
        if DELAY_MODE=='stochastic':
            # Search selects an action, never the winning rollout's lucky world.
            action=search.feasible_actions(s.observation())[row['action_index']]
            old_draw_count=len(s.delay_draws)
            s,post=search.transition(s,action,'random')
            row=dict(row,received_next=s.observation(),received_after_action=post['current'],
                     new_delays=s.delay_draws[old_draw_count:],execution_independent_of_rollout=True)
        else: s=q['next']
        rows.append(row)
    observations.append(s.observation());value,legs=search.liquidation(s,end,True)
    return dict(observations=observations,rows=rows,value=value,legs=legs,terminal=s)

def job(root):
    path=JOB_DIR/f'root_{root["id"]:05d}.json.gz'
    if path.exists():return root['id'],0.,True
    started=time.monotonic();MODEL.cache.clear()
    tr=lean_trajectory(root['state'],root['end'],MODEL,search.stable_seed(f'train:{STAGE}:{root["id"]}'),ROLLOUTS,SCHEDULE,STAGE)
    records=[]
    for j,obs in enumerate(tr['observations']):
        records.append(dict(root_id=root['id'],split=root['split'],episode=root['episode'],time=int(obs['current']['time']),end=root['end'],target=tr['value'],observation=obs,action=tr['rows'][j]['action'] if j<len(tr['rows']) else 'terminal',main_final_value=tr['value']))
    trace=dict(root_id=root['id'],split=root['split'],start=root['time'],end=root['end'],value=tr['value'],rows=tr['rows'])
    payload=dict(records=records,trace=trace,seconds=time.monotonic()-started)
    blob=gzip.compress(json.dumps(payload,allow_nan=False).encode());tmp=path.with_suffix('.tmp');tmp.write_bytes(blob);tmp.replace(path)
    return root['id'],payload['seconds'],False

def generate(roots,model,stage,schedule,rollouts,workers):
    if (run.ROOT/f'labels_stage{stage}.json.gz').exists():return run.load_gz(f'labels_stage{stage}.json.gz')
    started=time.monotonic();folder=run.ROOT/f'root_checkpoints_stage{stage}';folder.mkdir(exist_ok=True)
    weights=run.ROOT/f'teacher_stage{stage}.npz';model.save(weights)
    with mp.get_context('spawn').Pool(workers,initialize,(str(weights),stage,schedule.to_dict(),rollouts,str(folder))) as pool:
        for i,(root_id,seconds,cached) in enumerate(pool.imap_unordered(job,roots,chunksize=1)):
            if i%10==0 or i+1==len(roots):print('TARGETS',stage,i+1,'/',len(roots),'last_root',root_id,'wall_seconds',round(time.monotonic()-started,1),flush=True)
    ownership={};out=[];traces=[];dropped={s:0 for s in ['train','validation','test']}
    # Root order is the original train -> validation -> test split order.
    for root in roots:
        with gzip.open(folder/f'root_{root["id"]:05d}.json.gz','rt') as f:z=json.load(f)
        traces.append(z['trace'])
        for r in z['records']:
            split=r['split'];k=search.key(r['observation'])+str(r['end'])
            if k in ownership and ownership[k]!=split:dropped[split]+=1;continue
            ownership[k]=split;r['id']=len(out);out.append(r)
    run.save_gz(f'labels_stage{stage}.json.gz',out);run.save_gz(f'trajectories_stage{stage}.json.gz',traces)
    run.write_json(f'dataset_stage{stage}.json',dict(root_count=len(roots),samples=len(out),counts={s:sum(r['split']==s for r in out) for s in dropped},cross_split_duplicates_dropped=dropped,terminal_samples=sum(r['time']==r['end'] for r in out),target_seconds=time.monotonic()-started,workers=workers,rollouts=rollouts))
    return out

def main(args):
    started=time.monotonic();run.ROOT=args.output.resolve();run.ROOT.mkdir(parents=True,exist_ok=True)
    run.HORIZON=args.horizon;run.PathSimulator=FastPathSimulator
    schedule=ExplorationSchedule();immutable=dict(horizon=args.horizon,seed=17,epochs=args.epochs,rollouts=args.rollouts,exploration=schedule.to_dict(),source='two-mode v2 all roots/full histories/all timesteps',delay_mode=DELAY_MODE,planning_samples=4)
    config=run.ROOT/'run_config.json'
    if config.exists() and json.loads(config.read_text())!=immutable:raise RuntimeError('Incompatible saved config; choose a fresh output directory.')
    run.write_json('run_config.json',immutable);roots=run.make_roots();model=Transformer(seed=17);model.save(run.ROOT/'initial_transformer.npz');summaries=[]
    for stage in range(args.rounds):
        if (run.ROOT/f'fit_stage{stage}.json').exists():
            fit=json.loads((run.ROOT/f'fit_stage{stage}.json').read_text());model.load(run.ROOT/f'weights_stage{stage}.npz');summaries.append(fit['summary']);continue
        labels=generate(roots,model,stage,schedule,args.rollouts,args.workers)
        summary,history=run.fit(model,labels,stage,args.epochs);summaries.append(summary)
        model.save(run.ROOT/'trained_transformer.npz')
        run.write_json('progress.json',dict(horizon=args.horizon,completed_rounds=stage+1,training=summaries,elapsed_seconds=time.monotonic()-started))
        print('ROUND_COMPLETE',json.dumps(summary),flush=True)
    model.save(run.ROOT/'trained_transformer.npz')
    s=FastPathSimulator(run.configuration(seed=20261103));s.snapshot('before')
    greedy=search.rollout(s,args.horizon,model,280031254,greedy=True)
    planned=lean_trajectory(s,args.horizon,model,20261103,8,schedule,args.rounds-1)
    result=dict(delay_mode=DELAY_MODE,horizon=args.horizon,training=summaries,greedy_liquidation=greedy['value'],search_assisted_liquidation=planned['value'],greedy_actions=[r['action'] for r in greedy['rows']],main_actions=[r['action'] for r in planned['rows']],elapsed_seconds=time.monotonic()-started,parameters=model.parameter_count,convergence_claim=False,information_boundary='Simulator-assisted research planner; adversarial mode reselects causal pending delays; stochastic mode uses conditional planning samples and independent execution. Already occurred events are fixed.',engineering=['Full histories retained','Every original root and retained trajectory endpoint retained','Independent roots in parallel','Safe append-only clone sharing','Discarded inner rollouts not persisted','Float32 cache batching regression tested separately'])
    run.save_gz('evaluation_paths.json.gz',dict(greedy_rows=greedy['rows'],main_rows=planned['rows']))
    run.write_json('results.json',result);print('COMPLETE',json.dumps(result),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--horizon',type=int,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--rounds',type=int,default=2);parser.add_argument('--epochs',type=int,default=100);parser.add_argument('--rollouts',type=int,default=4);parser.add_argument('--workers',type=int,default=4);args=parser.parse_args();main(args)
