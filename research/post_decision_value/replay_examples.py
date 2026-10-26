"""Re-execute three bounded historical prefixes and retain order/report timelines.

The original full-day tape is queued to preserve counter-keyed report delays.
Every regenerated decision and fill is compared with the published study.
"""
import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
import gzip
import json
from pathlib import Path
import time

from .accounting import Goal, Ledger
from .analytical import analytical
from .analytical_study import PRESETS, check_fills, write
from .data import load_archive, sha
from .engine import CandidateGenerator, Engine


def plain(value):
    return json.loads(json.dumps(value,default=lambda x:asdict(x) if is_dataclass(x) else list(x)))


class TracedEngine(Engine):
    def __init__(self,*args,**kwargs):
        self.trace=[]
        super().__init__(*args,**kwargs)

    def _event(self,t,priority,kind,payload):
        super()._event(t,priority,kind,payload)
        if kind in ('message','report'):
            self.trace.append(dict(time=t,event='exchange_message' if kind=='message' else 'received_'+payload['kind'],
                                   data=plain(payload)))

    def _report(self,payload,key):
        if payload['kind']=='fill':
            self.trace.append(dict(time=self.now,event='exchange_fill',data=plain(self.hidden.fills[-1]),
                                   contractual_holdings=self.hidden.ledger.holdings(self.instruments)))
        super()._report(payload,key)


def replay_example(root,study,name,hours=4):
    if not 0<hours<=6:
        raise ValueError('Examples are limited to six hours')
    folder=Path(study)/'episodes'/name
    result=json.loads((folder/'result.json').read_text())
    for file in ('decisions.jsonl.gz','fills.json.gz'):
        if sha(folder/file)!=result['artifacts'][file]:raise ValueError('Published artifact mismatch')
    start=result['start'];end=start+hours*3600000
    from datetime import datetime,timezone
    day=datetime.fromtimestamp(start/1000,timezone.utc).date().isoformat()
    instruments,tape,seeds,manifest=load_archive(root,[day])
    if any(s.time<start-86400000 for s in seeds):
        previous=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
        _,prior,_,_=load_archive(root,[previous])
        latest={s.symbol:s for s in seeds}
        for tr in prior:
            if tr.time<=start-1000:latest[tr.symbol]=tr
        seeds=list(latest.values())
    goal=Goal(**result['goal'])
    engine=TracedEngine(instruments,Ledger(goal.initial.copy()),goal,result['seed'],event_cap=100000)
    engine.seed_market(seeds,start);engine.add_tape(tape)
    preset=next(p for p in PRESETS if p['name']==result['preset'])
    generator=CandidateGenerator(budget=96,quantities=preset['quantities'],offsets=preset['offsets'])
    decisions=[json.loads(line) for line in gzip.open(folder/'decisions.jsonl.gz','rt')]
    for row in decisions:
        if row['time']>=end:break
        engine.advance(row['time']);obs=engine.observe()
        candidates,audit=generator.generate(obs,goal,instruments)
        action=candidates[analytical(obs,candidates,goal,instruments)]
        if plain(action)!=row['chosen'] or audit!=row['candidates']:
            # Audit payloads contain tuples before JSON serialization.
            if plain(action)!=row['chosen'] or plain(audit)!=row['candidates']:
                raise ValueError('Regenerated policy decision differs from published study')
        engine.trace.append(dict(time=engine.now,event='decision',data=plain(action),
                                 observable_holdings=obs.ledger.holdings(instruments),
                                 observed_market=plain(obs.market),confirmed=plain(obs.confirmed),
                                 pending=plain(obs.pending),proposed=len(audit),accepted=len(candidates)))
        engine.submit(action)
    engine.advance(end)
    if engine.truncated:raise ValueError('Example event cap exceeded')
    expected=[f for f in json.loads(gzip.decompress((folder/'fills.json.gz').read_bytes())) if f['time']<=end]
    if engine.hidden.fills!=expected:raise ValueError('Regenerated fills differ from published study')
    check_fills(engine.hidden.fills,{(t.symbol,t.identifier):t for t in tape},instruments,.1)
    order={'exchange_message':0,'exchange_fill':1,'received_ack':2,'received_fill':2,'decision':3}
    trace=sorted((r for r in engine.trace if start<=r['time']<=end),key=lambda r:(r['time'],order[r['event']]))
    return dict(name=name,start=start,end=end,seed=result['seed'],preset=preset,trace=trace,
                fills=engine.hidden.fills,final_contractual_holdings=engine.hidden.ledger.holdings(instruments),
                verification='PASS: regenerated decisions, candidate audits and exact fill prefix match saved study',
                source_manifest=manifest,source_result_sha256=sha(folder/'result.json'),
                limitation='Four-hour excerpt, not a terminal performance evaluation. Hypothetical linear orders on inverse-source trades; no realized settlement.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--study',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();started=time.monotonic()
    names=['calibration-original-s11-d1','test-original-s11-d1','test-small_tight-s11-d1']
    result=dict(examples=[replay_example(a.root,a.study,n) for n in names])
    result['seconds']=time.monotonic()-started
    write(a.output,result)
    print(json.dumps(dict(seconds=result['seconds'],examples=[dict(name=r['name'],events=len(r['trace']),fills=len(r['fills'])) for r in result['examples']])))


if __name__=='__main__':main()
