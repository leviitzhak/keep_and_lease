"""Bounded full-domain smoke training and CPU timing; not an annual study."""
import argparse
from dataclasses import asdict
import hashlib,json,random,statistics,time
from pathlib import Path
import torch
from .action_search import ActionDomain,SparseGridDomain,ValueActionSearch
from .accounting import Goal,Ledger
from .data import load_archive,split_blocks
from .engine import Engine,Delays,post_decision,Order
from .model import ValueNetwork,features,action_features,fit,save_model,load_model
from .pilot import Budget,episode,write_json,code_identity,aggregate


def benchmark(root,out,*,domain=None,evaluations=128,repeats=8):
    torch.set_num_threads(1)
    ins,trades,seeds,manifest=load_archive(root,['2026-06-06'])
    start=min(t.time for t in trades)//86400000*86400000+3600000
    goal=Goal({'BTC':1.,'USD':100000.},start+90*86400000,max(i.expiry for i in ins.values()))
    e=Engine(ins,Ledger(goal.initial.copy()),goal,11)
    prior=[t for t in trades if t.time<start-1000][-64:]
    e.seed_market(seeds+prior,start);obs=e.observe()
    folder=Path('docs/research/post_decision_value/pilot-v1');identity=json.loads((folder/'identity.json').read_text())
    model,_,_=load_model(folder/'model-0.pt',identity)
    domain=domain or ActionDomain();search=ValueActionSearch(domain,evaluations=evaluations)
    rows=[]
    for working in (False,True):
        state=e.observe()
        if working:
            for i,s in enumerate(ins):
                state.uncertain[f'working-{i}']=[Order(f'working-{i}',s,(1 if i==0 else -1)*.001,state.market[s]['price'])]
        timings=[];cpu_timings=[];accepted=[]
        for seed in range(-1,repeats):
            began=time.perf_counter();cpu_began=time.process_time()
            history_cache={}
            def score(actions):return model.predict([action_features(state,a,goal,ins) for a in actions],history_cache=history_cache)['objective']
            _,info=search.choose(state,goal,ins,score,rng=random.Random(seed))
            if seed<0:continue  # Kernel/allocation warmup is not annual steady-state cost.
            timings.append(time.perf_counter()-began);cpu_timings.append(time.process_time()-cpu_began);accepted.append(info['accepted'])
        mean=statistics.mean(timings)
        rows.append(dict(working_orders=working,history_events=len(state.history),repeats=repeats,mean_ms=1000*mean,
                         mean_cpu_ms=1000*statistics.mean(cpu_timings),median_ms=1000*statistics.median(timings),
                         min_ms=1000*min(timings),max_ms=1000*max(timings),accepted=accepted,
                         annual_500ms_serial_days=365*86400/.5*mean/86400,
                         annual_100ms_serial_days=365*86400/.1*mean/86400,
                         annual_500ms_cpu_days=730*statistics.mean(cpu_timings)))
    result=dict(torch=torch.__version__,threads=torch.get_num_threads(),network_parameters=sum(p.numel() for p in model.parameters()),
                architecture=model.configuration,domain=asdict(domain),search_evaluations=evaluations,search_rounds=4,
                single_order_domain_size=domain.single_order_count(obs,goal,ins),states=rows,
                checkpoint_sha256=hashlib.sha256((folder/'model-0.pt').read_bytes()).hexdigest(),source_manifest=manifest,
                interpretation='Timing only: fixed historical observable states, existing trained checkpoint, no executed trajectory or profitability claim. Serial annual figures are extrapolations.')
    write_json(out/'benchmark.json',result)
    return result


def smoke(root,out,*,action_space='full',evaluations=128):
    dates=[f'2026-06-{d:02d}' for d in range(6,12)]
    ins,trades,seeds,manifest=load_archive(root,dates)
    blocks=split_blocks(dates,trades,seeds,offset_minutes=60,duration_minutes=5)
    config=dict(initial_btc=1.,initial_usd=100000.,reference_btc=100000.,candidate_budget=96,cadence_ms=30000,
                action_space=action_space,action_domain=asdict(ActionDomain()),search_evaluations=evaluations,grid_random_points=2,
                transition_cap=1000,event_cap=30000,pilot_seconds=180,participation=.1,delays=asdict(Delays()),seeds=[11,29])
    budget=Budget(config);identity=code_identity();models=[];results=[];training=[]
    write_json(out/'configuration.json',config);write_json(out/'data-manifest.json',manifest);write_json(out/'identity.json',identity)
    write_json(out/'splits.json',[{k:v for k,v in b.items() if k not in ('tape','seeds')} for b in blocks])
    torch.manual_seed(19)
    for stage,policy in enumerate(('exploratory_v1','collect_greedy_v1_eps015')):
        records=[];episodes=[]
        for b in blocks:
            if b['split']!='train':continue
            for seed in config['seeds']:
                rs,result=episode(b,ins,seed,policy,config,budget,models[-1] if models else None,retain=True)
                records.extend(rs);episodes.append(result)
        if any(not e['outcome']['done'] for e in episodes):raise RuntimeError('Incomplete smoke collection')
        model=ValueNetwork();optimizer,rng,info=fit(model,records,updates=80,seed=19+stage,wall_seconds=120)
        budget.training(info);models.append(model);training.append(info);results.extend(episodes)
        save_model(out/f'model-{stage}.pt',model,optimizer,rng,identity)
        write_json(out/f'transitions-{stage}.json.gz',records);write_json(out/f'episodes-{stage}.json.gz',episodes)
    validation=[]
    for k,model in enumerate(models):
        for b in blocks:
            if b['split']=='validation':
                for seed in config['seeds']:
                    _,r=episode(b,ins,seed,f'value_v{k+1}',config,budget,model);validation.append(r)
    if any(not r['outcome']['done'] for r in validation):raise RuntimeError('Incomplete validation')
    selected=max(range(len(models)),key=lambda k:statistics.mean(r['outcome']['utility'] for r in validation if r['policy']==f'value_v{k+1}'))
    results.extend(validation);evaluation=[]
    for b in blocks:
        if b['split']=='test':
            for seed in config['seeds']:
                for policy in ('hold','analytical',f'value_v{selected+1}'):
                    _,r=episode(b,ins,seed,policy,config,budget,models[selected] if policy.startswith('value') else None);evaluation.append(r)
    if any(not r['outcome']['done'] for r in evaluation):raise RuntimeError('Incomplete evaluation')
    results.extend(evaluation)
    report=dict(status='COMPLETE_BOUNDED_SMOKE',selected_stage=selected,training=training,summary=aggregate(results),
                decisions=budget.transitions,optimizer_updates=budget.updates,seconds=time.monotonic()-budget.started,
                limitations=['Five-minute windows and 30-second decisions validate plumbing, not annual or subsecond profitability.',
                             'Only two training market days; repeated seeds are not independent market history.',
                             'Counterfactual linear futures on inverse-source tape; contractual endpoints, no settlement bridge.',
                             'Expanded-domain checkpoint requires substantially more diverse outcome training before substantive use.'])
    write_json(out/'validation.json.gz',validation);write_json(out/'evaluation.json.gz',evaluation);write_json(out/'report.json',report)
    print(json.dumps(report),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--output',required=True)
    p.add_argument('--benchmark-only',action='store_true')
    p.add_argument('--action-space',choices=('full','grid'),default='full')
    p.add_argument('--search-evaluations',type=int)
    args=p.parse_args();out=Path(args.output)
    if out.exists():raise ValueError('Immutable validation output already exists')
    out.mkdir(parents=True)
    try:
        evaluations=args.search_evaluations or (32 if args.action_space=='grid' else 128)
        domain=SparseGridDomain() if args.action_space=='grid' else ActionDomain()
        b=benchmark(args.root,out,domain=domain,evaluations=evaluations);print(json.dumps(dict(benchmark=b['states'],single_order_domain_size=b['single_order_domain_size'])),flush=True)
        if not args.benchmark_only:smoke(args.root,out,action_space=args.action_space,evaluations=evaluations)
    except Exception as e:
        write_json(out/'failure.json',dict(done=False,error=type(e).__name__,reason=str(e)));raise


if __name__=='__main__':main()
