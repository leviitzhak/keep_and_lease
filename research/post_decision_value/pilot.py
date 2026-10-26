"""Bounded offline historical pilot. Run from repository root with python -m."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import time

import numpy as np
import torch

from .accounting import Goal, Ledger
from .engine import Engine, CandidateGenerator, Delays, Instruction, post_decision
from .data import load_archive, split_blocks
from .model import ValueNetwork, features, fit, save_model, load_model
from .analytical import analytical


def write_json(path, obj):
    data=json.dumps(obj,sort_keys=True,indent=2,allow_nan=False).encode()
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.gz':data=gzip.compress(data,mtime=0)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_bytes(data);tmp.replace(path)


def code_identity():
    digest=hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob('*.py')):
        digest.update(p.name.encode());digest.update(p.read_bytes())
    digest.update(Path('trade_ordering.py').read_bytes());digest.update(Path('replay_checkpoints.py').read_bytes())
    commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    return dict(source_commit=commit,source_sha256=digest.hexdigest(),simulator='post-decision-v1')


class Budget:
    def __init__(self, config):
        self.started=time.monotonic();self.transitions=0;self.events=0
        self.updates=0;self.training_seconds=0.;self.config=config
    def check(self):
        if time.monotonic()-self.started > self.config['pilot_seconds']:raise RuntimeError('pilot_wall_cap')
        if self.transitions>=self.config['transition_cap']:raise RuntimeError('transition_cap')
    def training(self,result):
        self.updates+=result['updates'];self.training_seconds+=result['seconds']
        if self.updates>2000 or self.training_seconds>1200:raise RuntimeError('training_cap')


def episode(block, instruments, seed, policy, config, budget, model=None, delay_multiplier=1., retain=False):
    initial=dict(BTC=config['initial_btc'],USD=config['initial_usd'])
    goal=Goal(initial,block['end'],max(i.expiry for i in instruments.values()),reference={'BTC':config['reference_btc'],'USD':1.})
    delays=Delays(**{k:(round(v*delay_multiplier) if k in ('observation','decision','delivery','report') else v) for k,v in config['delays'].items()})
    replay=Engine(instruments,Ledger(initial.copy()),goal,seed,delays,participation=config['participation'],event_cap=config['event_cap'])
    replay.seed_market(block['seeds'],block['start']);replay.add_tape(block['tape'])
    generator=CandidateGenerator(budget=config['candidate_budget'])
    rng=random.Random(seed)
    records=[];decision_audit=[];predictions=[];submitted_orders=set()
    continuation=policy if model is None else f'{policy}:{model.continuation}'
    for t in range(block['start'],block['end'],config['cadence_ms']):
        try:budget.check()
        except RuntimeError as e:
            replay.truncated=True;replay.hidden.failures.append(dict(time=t,reason=str(e)));break
        replay.advance(t)
        if replay.truncated:break
        obs=replay.observe();actions,audit=generator.generate(obs,goal,instruments)
        fs=[features(post_decision(obs,a,instruments),goal,instruments) for a in actions]
        predicted=None
        if policy=='hold':
            chosen=next((i for i,a in enumerate(actions) if a.kind=='wait'),0)
        elif policy=='analytical':chosen=analytical(obs,actions,goal,instruments)
        elif policy=='exploratory_v1':
            chosen=rng.randrange(len(actions)) if rng.random()<.5 else analytical(obs,actions,goal,instruments)
        else:
            predicted=model.predict(fs)
            chosen=int(np.argmax(predicted['objective']))
            if policy=='collect_greedy_v1_eps015' and rng.random()<.15:chosen=rng.randrange(len(actions))
        action=actions[chosen]
        replay.submit(action)
        submitted_orders.update(o.identifier for o in action.orders)
        budget.transitions+=1
        if retain:
            records.append(dict(features=fs[chosen],time=t,remaining_ms=goal.horizon-t,goal=asdict(goal),
                                instruction=action.payload(),continuation=continuation,
                                block=block['id'],seed=seed,source_ids=[v['identifier'] for v in obs.market.values()]))
        decision_audit.append(dict(time=t,selected=action.payload(),candidates=audit,
                                   predicted_score=float(predicted['objective'][chosen]) if predicted else None,
                                   continuation=predicted['continuation'] if predicted else continuation))
        if predicted:predictions.append(float(predicted['objective'][chosen]))
    if not replay.truncated:replay.advance(block['end'])
    outcome=replay.outcome();budget.events+=replay.hidden.processed
    packages={}
    for decision in decision_audit:
        action=decision["selected"]
        if action["kind"]=="create":
            for order in action["orders"]:
                if order["group"]:
                    packages.setdefault(order["group"],dict(created=decision["time"],orders={}))["orders"][order["identifier"]]=abs(order["quantity"])
    completion=[]
    for group, package in packages.items():
        fills=[f for f in replay.hidden.fills if f["group"]==group]
        done=all(sum(abs(f["quantity"]) for f in fills if f["order"]==oid)>=q-1e-9 for oid,q in package["orders"].items())
        completion.append(dict(group=group,status="full" if done else "partial" if fills else "none",
                               completion_ms=max(f["time"] for f in fills)-package["created"] if done else None))
    if outcome['done']:
        for r in records:r['outcome']=outcome
        filled_ids={f['order'] for f in replay.hidden.fills}
        outcome.update(package_completion=completion,no_fill_orders=len(submitted_orders-filled_ids),submitted_orders=len(submitted_orders),
                       terminal_prediction_error=float(np.mean(predictions)-outcome['utility']) if predictions else None)
    else:
        records=[]  # No fabricated terminal labels on runtime truncation.
    result=dict(block=block['id'],split=block['split'],seed=seed,policy=policy,delay_multiplier=delay_multiplier,
                start=block['start'],end=block['end'],goal=asdict(goal),outcome=outcome,
                decisions=decision_audit,fills=replay.hidden.fills)
    return records,result


def aggregate(results):
    groups={}
    for r in results:
        key=f"{r['split']}/{r['policy']}/delay={r['delay_multiplier']}"
        groups.setdefault(key,[]).append(r)
    summary={}
    for key,rs in groups.items():
        completed=[r for r in rs if r['outcome']['done']]
        if not completed:
            summary[key]=dict(episodes=len(rs),completed=0);continue
        os=[r['outcome'] for r in completed]
        # Independent uncertainty unit is market block, not replicated seeds.
        block_scores={}
        for r in completed:block_scores.setdefault(r['block'],[]).append(r['outcome']['utility'])
        means=[float(np.mean(v)) for v in block_scores.values()]
        summary[key]=dict(episodes=len(rs),completed=len(os),blocks=len(means),
                         mean_utility=float(np.mean([o['utility'] for o in os])),
                         mean_growth={c:float(np.mean([o['growth'][c] for o in os])) for c in ('BTC','USD')},
                         failed=sum(o['failed'] for o in os),fills=sum(o['fills'] for o in os),
                         fees_usd=sum(o['fees']['USD'] for o in os),
                         min_floor_headroom={c:min(o['min_floor_headroom'][c] for o in os) for c in ('BTC','USD')},
                         peak_async_btc=max(o['peak_async_btc'] for o in os),
                         block_mean_range=[min(means),max(means)],
                         block_standard_error=float(np.std(means,ddof=1)/math.sqrt(len(means))) if len(means)>1 else None,
                         prediction_mae=float(np.mean([abs(o['terminal_prediction_error']) for o in os if o['terminal_prediction_error'] is not None])) if any(o['terminal_prediction_error'] is not None for o in os) else None)
    return summary


def run(args):
    torch.set_num_threads(1);torch.manual_seed(19);np.random.seed(19)
    config=dict(initial_btc=1.,initial_usd=100000.,reference_btc=100000.,candidate_budget=96,cadence_ms=120000,
                transition_cap=20000,event_cap=30000,pilot_seconds=3600,optimizer_updates_per_stage=160,
                participation=.1,delays=asdict(Delays()),seeds=[11,29],
                dates=[f'2026-06-{d:02d}' for d in range(6,14)],episode_minutes=60,offset_minutes=60)
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    budget=Budget(config)
    instruments,trades,seeds,manifest=load_archive(args.input,config['dates'])
    blocks=split_blocks(config['dates'],trades,seeds,offset_minutes=config['offset_minutes'],duration_minutes=config['episode_minutes'])
    identity=code_identity()
    identity.update(config_sha256=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),
                    data_sha256=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest())
    if args.resume and (output/'identity.json').exists():
        prior=json.loads((output/'identity.json').read_text())
        if any(prior[k]!=identity[k] for k in ('source_sha256','config_sha256','data_sha256','simulator')):
            raise ValueError('Resume source/data/config identity mismatch')
        identity=prior
        if (output/'report.json').exists():
            return json.loads((output/'report.json').read_text())
    elif (output/'identity.json').exists():
        raise ValueError('Existing run is immutable: use --resume or a new output directory')
    write_json(output/'configuration.json',config);write_json(output/'data-manifest.json',manifest)
    write_json(output/'splits.json',[{k:v for k,v in b.items() if k not in ('seeds','tape')} for b in blocks])
    write_json(output/'identity.json',identity)
    models=[];training=[];all_results=[]
    for stage,policy in enumerate(('exploratory_v1','collect_greedy_v1_eps015')):
        checkpoint=output/f'model-{stage}.pt';dataset=output/f'transitions-{stage}.json.gz'
        if args.resume and checkpoint.exists():
            model,optimizer,rng=load_model(checkpoint,identity);models.append(model)
            training.append(json.loads((output/f'training-{stage}.json').read_text()))
            all_results.extend(json.loads(gzip.decompress((output/f'episodes-{stage}.json.gz').read_bytes())))
            budget.transitions+=sum(len(r['decisions']) for r in all_results) if stage==0 else sum(len(r['decisions']) for r in json.loads(gzip.decompress((output/f'episodes-{stage}.json.gz').read_bytes())))
            budget.training(training[-1])
            continue
        records=[];stage_results=[]
        for b in blocks:
            if b['split']!='train':continue
            for seed in config['seeds']:
                rows,result=episode(b,instruments,seed,policy,config,budget,models[-1] if models else None,retain=True)
                records.extend(rows);stage_results.append(result)
        write_json(dataset,records)
        model=ValueNetwork();optimizer,rng,info=fit(model,records,updates=config['optimizer_updates_per_stage'],seed=19+stage)
        budget.training(info);training.append(info);models.append(model)
        save_model(checkpoint,model,optimizer,rng,identity)
        write_json(output/f'training-{stage}.json',info);write_json(output/f'episodes-{stage}.json.gz',stage_results)
        all_results.extend(stage_results)
        print(json.dumps(dict(stage=stage,records=len(records),training=info)),flush=True)
    # Freeze candidates and both policies before validation. Validation chooses
    # stage by mean utility; test blocks play no role in that choice.
    validation=[]
    for i,model in enumerate(models):
        for b in blocks:
            if b['split']=='validation':
                for seed in config['seeds']:
                    _,result=episode(b,instruments,seed,f'value_v{i+1}',config,budget,model)
                    validation.append(result)
    def quality(i):
        outcomes=[r['outcome'] for r in validation if r['policy']==f'value_v{i+1}' and r['outcome']['done']]
        return float(np.mean([o['utility'] for o in outcomes])) if outcomes else -math.inf
    selected=max(range(len(models)),key=quality)
    all_results.extend(validation)
    evaluation=[]
    for b in blocks:
        if b['split']!='test':continue
        for delay in (1.,10.):
            for seed in config['seeds']:
                for policy in ('hold','analytical',f'value_v{selected+1}'):
                    _,result=episode(b,instruments,seed,policy,config,budget,models[selected] if policy.startswith('value') else None,delay_multiplier=delay)
                    evaluation.append(result)
    all_results.extend(evaluation)
    calibration=[]
    continuation_policy='exploratory_v1' if selected==0 else 'collect_greedy_v1_eps015'
    for b in blocks:
        if b['split']!='test':continue
        for seed in config['seeds']:
            rows,result=episode(b,instruments,seed,continuation_policy,config,budget,models[0] if selected else None,retain=True)
            if rows:
                prediction=models[selected].predict([r['features'] for r in rows])
                errors=prediction['objective']-result['outcome']['utility']
                holdings=np.array([result['outcome']['holdings'][c] for c in ('BTC','USD')])
                calibration.append(dict(block=b['id'],seed=seed,continuation=models[selected].continuation,
                                        score_mae=float(np.mean(np.abs(errors))),score_bias=float(np.mean(errors)),
                                        holdings_rmse=np.sqrt(np.mean((prediction['terminal_holdings']-holdings)**2,axis=0)).tolist()))
    write_json(output/'calibration.json',calibration)
    write_json(output/'evaluation.json.gz',evaluation)
    write_json(output/'validation.json.gz',validation)
    report=dict(identity=identity,fixed_continuation_calibration=calibration,selected_policy=f'value_v{selected+1}',training=training,summary=aggregate(all_results),
                resources=dict(recorded_decisions=budget.transitions,exchange_and_report_events=budget.events,
                               optimizer_updates=budget.updates,training_seconds=budget.training_seconds,pilot_seconds=time.monotonic()-budget.started),
                per_block=[{k:v for k,v in r.items() if k not in ('decisions','fills')} for r in all_results],
                interpretation='Counterfactual linear futures on verified historical inverse trade prints; contractual endpoint, no observed settlement tail',
                limitations=['Two held-out market days are a smoke test, not profitability evidence.',
                             'No spot execution, order-book depth, observed queue position or historical account margin schedule.',
                             'Trade participation, fees, ticks/lots, stress set and latency are explicit research assumptions.',
                             'Terminal predictions refer to their versioned training continuation; greedy improvement changes continuation and requires subsequent collection.',
                             'Prediction error against the improved policy is on-policy diagnostic, not unbiased fixed-continuation calibration.',
                             'Target-composition objective is configured and tested separately; primary pilot uses basket growth.',
                             'GCS source receipts verified from existing local export; live full-archive and extended spot inventory not refreshed.'])
    write_json(output/'report.json',report)
    print(json.dumps(dict(selected=report['selected_policy'],resources=report['resources'],summary=report['summary'])),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,help='Existing hash-receipted local export; no download')
    parser.add_argument('--output',required=True)
    parser.add_argument('--resume',action='store_true',help='Resume immutable completed training stages with identical code/data/config')
    args=parser.parse_args()
    try:run(args)
    except Exception as e:
        write_json(Path(args.output)/'failure.json',dict(done=False,truncated=True,error=type(e).__name__,reason=str(e)))
        raise

if __name__=='__main__':main()
