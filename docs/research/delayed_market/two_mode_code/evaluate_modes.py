"""Cross trained checkpoints/controller modes on common held-out environments."""
import argparse,hashlib,json,time
from pathlib import Path
from unittest.mock import patch
import numpy as np
import search,pending_adversary as pa,stochastic_delays as sd
from network import Transformer
from fast_exact import FastPathSimulator
from simulator import diagnostic_policy

class ScenarioSimulator(FastPathSimulator):
    def _delay(self,channel,source_tick,event):
        if source_tick<0:d=1
        else:
            # Event-keyed uniforms, shared across policies despite draw counts.
            token=f'{self.config.seed}:{channel}:{source_tick}:{event}'.encode()
            u=int.from_bytes(hashlib.sha256(token).digest()[:8],'big')/2**64
            law=getattr(self.config,channel);d=law.values[-1];total=0
            for value,p in zip(law.values,law.probabilities):
                total+=p
                if u<total:d=value;break
        self.delay_draws.append(dict(channel=channel,source_time=source_tick/4,event=event,delay=d,arrival_time=source_tick/4+d,source='held-out event-keyed scenario'))
        return d

def evaluate(model,controller,environment,seed,horizon,frozen):
    s=ScenarioSimulator(search.Config(seed=seed,horizon=horizon,tail_end=horizon+10));s.snapshot('before')
    rows=[];rng=np.random.default_rng(800000+seed);model.cache.clear()
    for t in range(horizon):
        if controller in ('adversarial','stochastic'):
            _,r=(pa if controller=='adversarial' else sd).step(s,horizon,model,rng,force_greedy=True)
            action=search.feasible_actions(s.observation())[r['action_index']]
        else:action=search.Action() if controller=='wait' else diagnostic_policy(s.observation())
        if environment=='stochastic':s,_=search.transition(s,action,'random')
        else:
            # Use the normal simulator delay enumeration for this fixed teacher.
            s.__class__=FastPathSimulator
            with patch('search.feasible_actions',return_value=[action]):
                s,_=pa.step(s,horizon,frozen,np.random.default_rng(0),force_greedy=True)
        rows.append(action.label())
    return dict(seed=seed,value=search.liquidation(s,horizon),actions=rows)

def main(a):
    out=a.output;out.parent.mkdir(parents=True,exist_ok=True)
    frozen=Transformer(seed=17);result=dict(horizon=a.horizon,scenarios=list(range(81000,81000+a.scenarios)),frozen_adversary='fresh seed17',rows=[],checkpoint_hashes={},limitations=['Simulator-assisted planning with fixed realized hidden events; not an observation-only deployed policy.','Mean-value planning uses four conditional samples, not an exact expectation.','Common event-keyed scenarios share uniforms for matching event identities; changed actions can generate different events.','Frozen adversary minimizes successor value, not terminal payoff; no robust optimality certificate.','One training seed and one rising-price fixture.'])
    for spec in a.checkpoint:
        label,path=spec.split('=',1);model=Transformer();model.load(path)
        result['checkpoint_hashes'][label]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for controller in ('adversarial','stochastic'):
            for env in ('stochastic','frozen_adversary'):
                seeds=result['scenarios'] if env=='stochastic' else [81000]
                trials=[]
                for seed in seeds:
                    trials.append(evaluate(model,controller,env,seed,a.horizon,frozen))
                values=np.array([r['value'] for r in trials]);row=dict(checkpoint=label,controller=controller,environment=env,mean=float(values.mean()),minimum=float(values.min()),maximum=float(values.max()),standard_error=float(values.std(ddof=1)/len(values)**.5) if len(values)>1 else None,trials=trials)
                result['rows'].append(row);out.write_text(json.dumps(result,indent=2));print(label,controller,env,row['mean'],flush=True)
    model=Transformer()
    for controller in ('diagnostic','wait'):
        for env in ('stochastic','frozen_adversary'):
            seeds=result['scenarios'] if env=='stochastic' else [81000]
            trials=[evaluate(model,controller,env,seed,a.horizon,frozen) for seed in seeds]
            result['rows'].append(dict(checkpoint='comparator',controller=controller,environment=env,mean=float(np.mean([r['value'] for r in trials])),trials=trials))
    result['complete']=True;out.write_text(json.dumps(result,indent=2));print('COMPLETE',out,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',action='append',required=True);p.add_argument('--scenarios',type=int,default=32);p.add_argument('--horizon',type=int,default=10);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
