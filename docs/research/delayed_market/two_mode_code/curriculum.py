"""Declared pair-sampling curriculum for horizons above10.

Three length stages: ceil(T/4), ceil(T/2), T. At each stage, allocate25%
short roots (length1..min(10,max)),25%previous-range roots, and50%new-range
roots. Stage0 assigns the unused previous-range share to its new range.
Within a chosen length, t1 is uniform on0..T-length; t2=t1+length.
The last stage includes one explicit (0,T) training root. Every state inside
sampled trajectories is labeled. Longer roots therefore supply more examples.
"""
import math,json
from pathlib import Path
import numpy as np
import search
from fast_exact import FastPathSimulator

SPLITS={'train':[111,222,333,444],'validation':[555,666],'test':[777,888]}

def stage_caps(horizon):return sorted(set([math.ceil(horizon/4),math.ceil(horizon/2),horizon]))

def sample_pairs(horizon,stage,counts=None,seed=17017):
 counts=counts or {'train':128,'validation':32,'test':32}
 caps=stage_caps(horizon);maximum=caps[stage];previous=caps[stage-1] if stage else 0
 rng=np.random.default_rng(seed+stage);pairs=[]
 for split,seeds in SPLITS.items():
  count=counts[split];short_n=count//4;old_n=count//4 if stage else 0
  categories=['short']*short_n+['previous']*old_n+['frontier']*(count-short_n-old_n);rng.shuffle(categories);seen=set()
  for i,category in enumerate(categories):
   episode=seeds[i%len(seeds)]
   low,high=(1,min(10,maximum)) if category=='short' else (1,previous) if category=='previous' else (previous+1,maximum)
   for attempt in range(10000):
    length=int(rng.integers(low,high+1));start=int(rng.integers(0,horizon-length+1));identity=(episode,start,start+length)
    if identity not in seen:break
   else:raise RuntimeError('Requested curriculum count exceeds available unique pairs.')
   seen.add(identity);pairs.append(dict(id=stage*100000+len(pairs),split=split,episode=episode,time=start,end=start+length,length=length,component=category))
 if maximum==horizon:
  # Replace a frontier training draw; preserve exact short and previous shares.
  existing=next((i for i,p in enumerate(pairs) if p['split']=='train' and p['time']==0 and p['end']==horizon),None)
  index=existing if existing is not None else next(i for i,p in enumerate(pairs) if p['split']=='train' and p['component']=='frontier')
  if existing is None:pairs[index].update(episode=111,time=0,end=horizon,length=horizon)
  pairs[index]['component']='forced_full_horizon'
 return pairs

def build_roots(horizon,pairs,output):
 roots=[];states={};pair_starts={}
 for p in pairs:pair_starts.setdefault(p['episode'],set()).add(p['time'])
 for split,seeds in SPLITS.items():
  for seed in seeds:
   starts=pair_starts.get(seed,set())
   if not starts:continue
   s=FastPathSimulator(search.Config(horizon=horizon,tail_end=horizon+10,seed=seed));s.snapshot('before');rng=np.random.default_rng(seed)
   for t in range(max(starts)+1):
    if t in starts:states[(seed,t)]=s.clone()
    if t==max(starts):break
    actions=search.feasible_actions(s.observation());action=actions[int(rng.integers(1,len(actions)))] if t==0 else actions[int(rng.integers(len(actions)))]
    s,_=search.transition(s,action,'random',seed=int(rng.integers(2**31-1)))
 for p in pairs:roots.append(dict(**p,state=states[(p['episode'],p['time'])].clone()))
 output=Path(output);output.mkdir(parents=True,exist_ok=True);(output/'sampled_pairs.json').write_text(json.dumps(pairs,indent=2))
 return roots

def coverage(horizon,pairs):
 out={}
 for split in SPLITS:
  subset=[p for p in pairs if p['split']==split];lengths=[p['length'] for p in subset]
  out[split]=dict(roots=len(subset),min_length=min(lengths),max_length=max(lengths),mean_length=float(np.mean(lengths)),short_length_le10=sum(x<=10 for x in lengths),full_horizon_pairs=sum(p['time']==0 and p['end']==horizon for p in subset),distinct_starts=len({p['time'] for p in subset}),length_histogram={str(l):lengths.count(l) for l in sorted(set(lengths))},raw_all_timestep_examples=sum(l+1 for l in lengths))
 return out
