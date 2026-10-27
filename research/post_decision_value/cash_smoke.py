"""Bounded synthetic cash/futures collect-fit-improve-evaluate regression run.

No downloads. These compressed-time scenarios validate plumbing, not returns or
latency. Run: python -m research.post_decision_value.cash_smoke --output PATH
"""
import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from .accounting import Instrument, Goal, Ledger, Position
from .engine import Engine, Trade, Order, Instruction, Delays
from .cash_data import load_cash_bundle, attach_cash_blocks
from .model import ValueNetwork, fit, save_model, features, action_features
from .pilot import Budget, episode, aggregate, code_identity, write_json


def fixture_bundle(output):
    cash={s:Instrument(s,10**15,payoff=k,source_payoff=k,tick=tick,lot=lot,fee_bps=0,
                      underlying_per_unit=ratio) for s,k,tick,lot,ratio in
          [('S','spot',1,.001,1),('P','proxy',.01,1,.01)]}
    future={s:Instrument(s,1_000_000+10*86400000+offset,tick=1,lot=.001,fee_bps=0,source_payoff='linear')
            for s,offset in [('A',0),('B',86400000)]}
    blocks=[];tape=[]
    for day in range(6):
        start=1_000_000+day*86400000;s=f'T{day}'
        cash[s]=Instrument(s,start+1600,payoff='treasury',source_payoff='treasury',tick=.01,lot=1,fee_bps=0,
                           cashflows=((start+800,.2),(start+1600,100.)),listed_at=start-20000)
        prices={'S':100000.,'P':1000.,s:99.6,'A':104000.+day*50,'B':106000.+day*75}
        ftape=[];fseeds=[]
        for symbol,p in prices.items():
            ins=(cash|future)[symbol]
            seed=Trade(start-20000,symbol,p,10000.,'buy',f'{day}:{symbol}:seed',100000.,ins.source_payoff)
            (fseeds if ins.is_future else tape).append(seed)
            for n,t in enumerate(range(start+50,start+1800,100)):
                if t>=ins.expiry:continue
                side='sell' if n%2==0 else 'buy';delta=(-1 if side=='sell' else 1)
                price=p+delta*(150 if ins.is_future or ins.payoff=='spot' else 1.5 if ins.payoff=='proxy' else .6)
                row=Trade(t,symbol,price,10000.,side,f'{day}:{symbol}:{n}',100000.,ins.source_payoff)
                (ftape if ins.is_future else tape).append(row)
        blocks.append(dict(id=f'synthetic-day-{day}',split=('train' if day<2 else 'validation' if day<4 else 'test'),
                           start=start,end=start+1800,seeds=fseeds,tape=ftape))
    root=output/'cash-input';root.mkdir()
    body=gzip.compress(('\n'.join(json.dumps(asdict(t),sort_keys=True) for t in tape)+'\n').encode(),mtime=0)
    (root/'trades.jsonl.gz').write_bytes(body)
    write_json(root/'manifest.json',dict(schema_version=1,currency='USD',instruments=[asdict(i) for i in cash.values()],
        interpretation='Synthetic compressed-time fixtures; no historical observations, executions or settlements',
        objects=[dict(file='trades.jsonl.gz',kind='synthetic_fixture',source_uri='fixture://cash-smoke-v1',
                      bytes=len(body),sha256=hashlib.sha256(body).hexdigest())]))
    cash,tape,manifest=load_cash_bundle(root);attach_cash_blocks(blocks,cash,tape)
    write_json(output/'fixture-blocks.json.gz',[{**b,'seeds':[asdict(t) for t in b['seeds']],
                                               'tape':[asdict(t) for t in b['tape']]} for b in blocks])
    return cash|future,blocks,manifest


def carry_replay(proxy=False,grow_btc=False):
    """Three independently filling legs, coupons, redemption and explicit bridge."""
    asset=Instrument('P' if proxy else 'S',10**15,payoff='proxy' if proxy else 'spot',
        source_payoff='proxy' if proxy else 'spot',tick=.01 if proxy else 1,lot=1 if proxy else .001,
        fee_bps=0,underlying_per_unit=.01 if proxy else 1.)
    bill=Instrument('T',1000,payoff='treasury',source_payoff='treasury',tick=.01,lot=1,fee_bps=0,
                    cashflows=((900,5.),(1000,100.)))
    future=Instrument('F',1100,tick=1,lot=.000001,fee_bps=0,source_payoff='linear')
    ins={i.symbol:i for i in (asset,bill,future)};ledger=Ledger({'BTC':.99 if proxy else 1.,'USD':100000.})
    if proxy:ledger.positions['P']=Position(1.,1000.)
    goal=Goal({'BTC':1.,'USD':100000.},1300,1300,mode='gated_max')
    e=Engine(ins,ledger,goal,11,Delays(10,1,10,50,.25,.25),participation=1)
    prices={asset.symbol:1000. if proxy else 100000.,'T':100.,'F':104000.}
    e.seed_market([Trade(0,s,prices[s],100,'buy','seed-'+s,100000.,i.source_payoff) for s,i in ins.items()],100)
    action=Instruction('create',(Order('cash',asset.symbol,-1. if proxy else -.01,prices[asset.symbol],'carry',100),
                                 Order('future','F',.010096 if grow_btc else .01,104000.,'carry',100),Order('bill','T',10.,100.,created=100)))
    post=action_features(e.observe(),action,goal,ins);e.submit(action)
    e.add_tape([Trade(200,asset.symbol,prices[asset.symbol]+asset.tick,100,'buy','sell',100000.,asset.source_payoff),
                Trade(300,'F',103999.,100,'sell','long',100000.,'linear'),
                Trade(400,'T',99.,100,'sell','bill',100000.,'treasury')])
    e._event(1100,1,'settlement',('F',120000.,120000.,True))
    states=[]
    for t in (100,220,350,450,850,900,960,1000,1060,1100,1200,1300):
        e.advance(t);obs=e.observe()
        states.append(dict(time=t,observed_balances=obs.ledger.balances,observed_holdings=obs.ledger.holdings(ins),
                           pending=obs.pending,confirmed={k:asdict(v) for k,v in obs.confirmed.items()},
                           hidden_balances=e.hidden.ledger.balances.copy()))
    return dict(source='synthetic_fixture',proxy=proxy,grow_btc=grow_btc,goal=asdict(goal),instruments={s:asdict(i) for s,i in ins.items()},
                instruction=action.payload(),post_decision_features=post,states=states,fills=e.hidden.fills,outcome=e.outcome())


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1);torch.manual_seed(19);np.random.seed(19)
    ins,blocks,manifest=fixture_bundle(output)
    config=dict(initial_btc=1.,initial_usd=100000.,reference_btc=100000.,goal_mode='gated_max',feature_version=2,
        candidate_budget=96,cadence_ms=200,transition_cap=2000,event_cap=10000,pilot_seconds=240,
        optimizer_updates_per_stage=80,participation=.1,seeds=[11,29],delays=asdict(Delays(10,1,10,20,.25,.25)),
        action_space='grid',action_domain=dict(min_btc=.001,max_btc=.01,price_band_bps=25,max_new_orders=3,min_usd=100.,max_usd=1000.),
        search_evaluations=64,search_rounds=2,grid_random_points=2,cash_manifest_sha256=manifest['manifest_sha256'])
    identity=code_identity();identity.update(config_sha256=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),
        data_sha256=hashlib.sha256((output/'fixture-blocks.json.gz').read_bytes()).hexdigest(),source_kind='synthetic_fixture')
    write_json(output/'configuration.json',config);write_json(output/'data-manifest.json',manifest);write_json(output/'identity.json',identity)
    write_json(output/'splits.json',[{k:v for k,v in b.items() if k not in ('seeds','tape')} for b in blocks])
    budget=Budget(config);models=[];results=[];training=[]
    for stage,policy in enumerate(('exploratory_v1','collect_greedy_v1_eps015')):
        rows=[];episodes=[]
        for b in blocks[:2]:
            for seed in config['seeds']:
                records,result=episode(b,ins,seed,policy,config,budget,models[-1] if models else None,retain=True)
                if not result['outcome']['done']:raise RuntimeError('Synthetic smoke truncated')
                rows.extend(records);episodes.append(result)
        model=ValueNetwork(feature_version=2);opt,rng,info=fit(model,rows,updates=80,seed=19+stage,wall_seconds=60)
        budget.training(info);models.append(model);training.append(info);results.extend(episodes)
        write_json(output/f'transitions-{stage}.json.gz',rows);write_json(output/f'episodes-{stage}.json.gz',episodes)
        write_json(output/f'training-{stage}.json',info);save_model(output/f'model-{stage}.pt',model,opt,rng,identity)
        print(json.dumps(dict(stage=stage,rows=len(rows),loss=info['last_loss'],elapsed=time.monotonic()-budget.started)),flush=True)
    validation=[]
    for stage,model in enumerate(models):
        for b in blocks[2:4]:
            for seed in config['seeds']:
                _,r=episode(b,ins,seed,f'value_v{stage+1}',config,budget,model);validation.append(r)
    quality=lambda k:np.mean([r['outcome']['utility'] for r in validation if r['policy']==f'value_v{k+1}'])
    selected=max(range(2),key=quality);evaluation=[]
    for b in blocks[4:]:
        for seed in config['seeds']:
            for policy in ('hold','analytical',f'value_v{selected+1}'):
                _,r=episode(b,ins,seed,policy,config,budget,models[selected] if policy.startswith('value') else None)
                evaluation.append(r)
    results+=validation+evaluation
    if any(not r['outcome']['done'] for r in results):raise RuntimeError('Incomplete synthetic evaluation')
    carry=[carry_replay(False),carry_replay(True),carry_replay(False,True)];write_json(output/'carry-replays.json',carry)
    write_json(output/'validation.json.gz',validation);write_json(output/'evaluation.json.gz',evaluation)
    report=dict(source_kind='synthetic_fixture',interpretation='Compressed-time regression smoke; no historical profitability inference',
        selected_policy=f'value_v{selected+1}',parameters=sum(p.numel() for p in models[0].parameters()),training=training,
        summary=aggregate(results),carry_outcomes=[r['outcome'] for r in carry],
        resources=dict(seconds=time.monotonic()-budget.started,decisions=budget.transitions,events=budget.events,
                       optimizer_updates=budget.updates,training_seconds=budget.training_seconds,torch_threads=1),
        limitations=['Two synthetic held-out scenarios are not independent market evidence.',
                     'Treasury cash receipts are contractual projections, not observed settlements.',
                     'Proxy BTC/share is fixed; custody, tracking, redemptions and securities settlement lags are not modeled.',
                     'Zero trading fees and engineered compressed-time cashflows cannot estimate economic returns.'])
    write_json(output/'report.json',report);print(json.dumps({k:report[k] for k in ('selected_policy','parameters','resources','summary')}),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    run(parser.parse_args().output)


if __name__=='__main__':main()
