"""Monte Carlo expected successor values; independent simulator execution.

Planning samples pending delays conditional on nonarrival. The real queue keeps
its original assignments. Common planning draws across actions reduce variance;
they do not consume the execution RNG. No minimum over delays is taken.
"""
import copy,random
import numpy as np
import search
from network import predict
from pending_adversary import conditioned_random_pending

SAMPLES=4

def step(s,end,model,rng,force_greedy=False,exploration=.30,audit=False,exhaustive=False):
    if not 0 <= exploration <= 1: raise ValueError('invalid exploration')
    obs=s.observation(); actions=search.feasible_actions(obs)
    exploratory=not force_greedy and rng.random()<exploration
    scores=[]
    if exploratory:
        idx=int(rng.integers(len(actions)))
    else:
        plans=[]
        for j in range(SAMPLES):
            parent,_=conditioned_random_pending(s,rng)
            seed=int(rng.integers(2**31-1))
            plans.append((parent,seed))
        records=[]
        for a in actions:
            for parent,seed in plans:
                child,_=search.transition(parent,a,'random',seed=seed)
                records.append(search.record(child.observation(),end))
        scores=np.asarray(predict(model,records)).reshape(len(actions),SAMPLES).mean(axis=1).tolist()
        idx=int(np.argmax(scores))
    # Execute with the real queue/RNG, independently of the planning samples.
    child,post=search.transition(s,actions[idx],'random')
    info=dict(mode='exploratory' if exploratory else 'greedy',action=actions[idx].label(),action_index=idx,
        **search.action_dict(actions[idx]),next_value=None if exploratory else scores[idx],minimum=None,
        expected_action_values=scores,planning_samples=0 if exploratory else SAMPLES,
        pending_reselections=[],time=s.clock/4,end=end,
        exploration_probability=0. if force_greedy else exploration,
        new_delays=copy.deepcopy(child.delay_draws[len(s.delay_draws):]),
        received_before=obs,received_after_action=post['current'],received_next=child.observation(),
        delay_semantics='conditional_MC_planning_independent_simulator_execution')
    if audit:info.update(full_before=search.full_state(s),full_next=search.full_state(child))
    return child,info

def rollout_search(s,end,model,count=4,seed=0,audit=False,schedule=None,round_index=0):
    # Each candidate starts from an independent conditional planning world.
    paths=[]
    for j in range(count):
        candidate_seed=search.stable_seed(f'planning:{seed}:{j}')
        parent,_=conditioned_random_pending(s,np.random.default_rng(candidate_seed))
        parent.rng={ch:random.Random(candidate_seed+100003*(i+1)) for i,ch in enumerate(search.CHANNELS)}
        paths.append(search.rollout(parent,end,model,seed+101*j,greedy=j==0,audit=audit,schedule=schedule,round_index=round_index))
    winner=int(np.argmax([r['value'] for r in paths]));win=paths[winner]
    return dict(value=win['value'],winner=winner,rollouts=paths,next=win['first'].clone())

def install():
    search.step=step
    search.search=rollout_search
