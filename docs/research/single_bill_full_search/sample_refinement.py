"""Refine trajectory counts for the longer cases that fit at 60k updates.

Same seed, 97-parameter model, optimizer and pre-existing nested trajectory
prefixes. Reuses holdouts as a diagnostic follow-up, not a fresh confirmation.
"""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from longer_timelines import PROTOCOL,Market,rollout,dataset,evaluation_set,fit

HERE=Path(__file__).resolve().parent
def main():
    PROTOCOL['updates']=60000
    base=json.loads((HERE/'longer_results/study.json').read_text())
    follow=json.loads((HERE/'longer_results/followup.json').read_text())
    selected=[r['T'] for r in follow['runs'] if r['confirmed']]
    result=dict(timelines=selected,trajectory_budgets=[4,16,64],updates=60000,
                seed=20261101,evaluation='Reused holdouts; adaptive simulation-budget diagnosis',runs=[])
    result['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    start=time.perf_counter();deadline=start+600
    for T in selected:
        env=Market(T);val=evaluation_set(env,'validation');test=evaluation_set(env,'test')
        rng=np.random.default_rng(20261101^12345);states=set();generated=0
        for count in [4,16,64]:
            while generated<count:
                states.update(s for s in rollout(env,rng) if env.split(s)=='train');generated+=1
            train=dataset(env,states)
            r=dict(T=T,trajectories=count,training_transitions=count*T,
                   training_labels=len(train['y']),**fit(env,train,val,test,20261101,deadline))
            original=next(r0 for r0 in base['runs'] if r0['T']==T and r0['seed']==20261101 and r0['trajectories']==count)
            at12k=next(x for x in r['curve'] if x['update']==12000)
            assert abs(at12k['train']['rmse_usd']-original['final_update_train']['rmse_usd'])<1e-9
            r['first_12000_updates_match_baseline']=True
            result['runs'].append(r);result['wall_seconds']=time.perf_counter()-start
            (HERE/'longer_results/refinement.json').write_text(json.dumps(result,indent=2,allow_nan=False))
            print(json.dumps(dict(T=T,trajectories=count,best_update=r['best_update'],
                                  train_rmse=r['train']['rmse_usd'],test_rmse=r['test']['rmse_usd'],
                                  sustained=r['sustained_validation_threshold_update'],confirmed=r['confirmed'],
                                  elapsed=result['wall_seconds'])),flush=True)
if __name__=='__main__':main()
