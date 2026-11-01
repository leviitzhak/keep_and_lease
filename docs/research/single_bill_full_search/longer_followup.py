"""Extend optimization to 60k updates on the identical 256-trajectory datasets.

This diagnosis adds no distinct training trajectories and keeps architecture,
initialization, sampling and learning rates unchanged. It reuses the holdouts;
it is not a new untouched confirmation experiment.
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
    start=time.perf_counter();deadline=start+600
    baseline=json.loads((HERE/'longer_results/study.json').read_text())
    output=dict(purpose='Longer optimization, identical 256-trajectory data and 97-parameter architecture',
                updates=60000,seed=20261101,trajectories=256,new_distinct_training_trajectories=0,
                evaluation='Same validation and test states reused for diagnosis; not a fresh test',runs=[])
    output['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for T in [8,16,32,64]:
        env=Market(T);rng=np.random.default_rng(20261101^12345);states=set()
        for _ in range(256):states.update(s for s in rollout(env,rng) if env.split(s)=='train')
        train=dataset(env,states);val=evaluation_set(env,'validation');test=evaluation_set(env,'test')
        r=dict(T=T,training_labels=len(train['y']),**fit(env,train,val,test,20261101,deadline))
        prior=next(x for x in baseline['runs'] if x['T']==T and x['seed']==20261101 and x['trajectories']==256)
        at12k=next(x for x in r['curve'] if x['update']==12000)
        for metric in ['rmse_usd','balanced_rmse_usd','max_abs_usd']:
            assert abs(at12k['train'][metric]-prior['final_update_train'][metric])<1e-9
        r['first_12000_updates_match_baseline']=True
        output['runs'].append(r);output['wall_seconds']=time.perf_counter()-start
        (HERE/'longer_results/followup.json').write_text(json.dumps(output,indent=2,allow_nan=False))
        print(json.dumps(dict(T=T,best_update=r['best_update'],train_rmse=r['train']['rmse_usd'],
                              val_rmse=r['validation']['rmse_usd'],test_rmse=r['test']['rmse_usd'],
                              sustained=r['sustained_validation_threshold_update'],confirmed=r['confirmed'],
                              regret=r['policy']['full_horizon_regret_usd'],elapsed=output['wall_seconds'])),flush=True)

if __name__=='__main__':main()
