"""Bounded cached-tape hold-policy clock comparison, not a training/backtest claim."""
import argparse
from dataclasses import asdict
import time
from .accounting import Goal,Ledger
from .engine import Engine,Delays,Instruction
from .decision_clock import DecisionSchedule
from .data import load_archive,utc_ms
from .pilot import Budget,code_identity,write_json


def run(root,output):
    instruments,trades,seeds,manifest=load_archive(root,['2026-06-06'])
    start=utc_ms('2026-06-06T01:00:00Z');end=start+120000
    prior={t.symbol:t for t in seeds if t.time<start-10000}
    for tr in trades:
        if tr.time<start-10000:prior[tr.symbol]=tr
    tape=[t for t in trades if start<=t.time<=end]
    config=dict(cadence_ms=500,trigger=dict(price_bps=2.,premium_bps=2.,min_gap_ms=100,max_wait_ms=30000),
                pilot_seconds=30,transition_cap=1000,seed=11,delays=asdict(Delays()))
    results=[]
    for mode in ('fixed','event'):
        e=Engine(instruments,Ledger({'BTC':1.,'USD':100000.}),Goal({'BTC':1.,'USD':100000.},end,max(i.expiry for i in instruments.values()),mode='weighted_growth'),11,Delays(),event_cap=10000)
        e.seed_market(prior.values(),start);e.add_tape(tape);budget=Budget(config)
        schedule=DecisionSchedule(e,end,mode=mode,cadence_ms=500,trigger=config['trigger'],budget=budget)
        began=time.perf_counter();cpu=time.process_time();audit=[]
        for t,why in schedule:
            e.submit(Instruction());schedule.accept();budget.transitions+=1;audit.append(dict(time=t,reasons=why))
        e.advance(end)
        results.append(dict(mode=mode,seconds=time.perf_counter()-began,cpu_seconds=time.process_time()-cpu,
                            decisions=len(audit),events=e.hidden.processed,audit=audit,outcome=e.outcome()))
    report=dict(identity=code_identity(),config=config,source=manifest,start=start,end=end,results=results,
                reduction_fraction=1-results[1]['decisions']/results[0]['decisions'],
                matching_hold_outcomes=results[0]['outcome']==results[1]['outcome'],
                limitations=['Two minutes of two-contract cached historical inverse prints, counterfactual linear mode.',
                             'Hold policy; no candidate search or neural inference timed. No speedup/return claim for learned policies.',
                             'All exact tape/report events processed; event clock only changes decision times.'])
    write_json(output,report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=run(a.input,a.output)
    print({k:r[k] for k in ('reduction_fraction','matching_hold_outcomes')})
    print([{k:v for k,v in x.items() if k not in ('audit','outcome')} for x in r['results']])
