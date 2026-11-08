"""Sample-pair curriculum, full histories and all retained trajectory states."""
import argparse,json,time
from pathlib import Path
import numpy as np
import progressive,run,search
from curriculum import sample_pairs,stage_caps,build_roots,coverage
from network import Transformer
from exploration import ExplorationSchedule
from fast_exact import FastPathSimulator

def main(args):
 begin=time.monotonic();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 run.ROOT=out;run.HORIZON=args.horizon;run.PathSimulator=FastPathSimulator
 schedule=ExplorationSchedule();caps=stage_caps(args.horizon);rollouts=[4,6,8]
 config=dict(version='two_mode_curriculum_v2',delay_mode=progressive.DELAY_MODE,planning_samples=4,horizon=args.horizon,seed=17,pair_seed=17017,stage_max_lengths=caps,root_counts={'train':128,'validation':32,'test':32},pair_distribution='25% lengths1..min(10,stage_max),25% previous-stage range,50% new range; stage0 uses75% new range; uniform start conditional on length; one explicit full-horizon training pair in final stage',rollouts_by_stage=rollouts,epochs_per_stage=args.epochs,all_timesteps=True,full_history=True,exploration=schedule.to_dict())
 p=out/'run_config.json'
 if p.exists() and json.loads(p.read_text())!=config:raise RuntimeError('Incompatible saved curriculum config.')
 p.write_text(json.dumps(config,indent=2));model=Transformer(seed=17);model.save(out/'initial_transformer.npz');summaries=[]
 for stage,maximum in enumerate(caps):
  if (out/f'fit_stage{stage}.json').exists():
   model.load(out/f'weights_stage{stage}.npz');summaries.append(json.loads((out/f'fit_stage{stage}.json').read_text())['summary']);continue
  pairs=sample_pairs(args.horizon,stage);roots=build_roots(args.horizon,pairs,out/f'curriculum_stage{stage}')
  report=coverage(args.horizon,pairs);(out/f'curriculum_stage{stage}'/'coverage.json').write_text(json.dumps(report,indent=2));print('CURRICULUM_STAGE',stage,'max_length',maximum,json.dumps(report),flush=True)
  labels=progressive.generate(roots,model,stage,schedule,rollouts[stage],args.workers)
  summary,_=run.fit(model,labels,stage,args.epochs);summaries.append(summary);model.save(out/'trained_transformer.npz')
  run.write_json('progress.json',dict(horizon=args.horizon,completed_stages=stage+1,training=summaries,elapsed_seconds=time.monotonic()-begin));print('ROUND_COMPLETE',json.dumps(summary),flush=True)
 s=FastPathSimulator(run.configuration(seed=20261103));s.snapshot('before')
 greedy=search.rollout(s,args.horizon,model,280031254,greedy=True)
 planned=progressive.lean_trajectory(s,args.horizon,model,20261103,8,schedule,len(caps)-1)
 result=dict(configuration=config,training=summaries,greedy_liquidation=greedy['value'],search_assisted_liquidation=planned['value'],greedy_actions=[r['action'] for r in greedy['rows']],main_actions=[r['action'] for r in planned['rows']],elapsed_seconds=time.monotonic()-begin,parameters=model.parameter_count,convergence_claim=False,adversary='All still-pending communication events: original total-delay support, arrival strictly after now, completed events fixed.')
 run.save_gz('evaluation_paths.json.gz',dict(greedy_rows=greedy['rows'],main_rows=planned['rows']));run.write_json('results.json',result);print('COMPLETE',json.dumps(result),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--horizon',type=int,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--epochs',type=int,default=100);p.add_argument('--workers',type=int,default=4);main(p.parse_args())
