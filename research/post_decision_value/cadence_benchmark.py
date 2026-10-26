"""Bounded CPU benchmark, not a performance study or training run."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import resource
import statistics
import time

from .accounting import Goal, Ledger
from .analytical import analytical
from .analytical_study import PRESETS, write
from .data import load_archive, utc_ms
from .engine import CandidateGenerator, Engine


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();began=time.perf_counter()
    ins,tape,seeds,manifest=load_archive(args.root,['2026-06-06'])
    start=utc_ms('2026-06-06T00:00:00Z');end=start+120000
    goal=Goal({'BTC':1.,'USD':100000.},start+54*86400000,max(i.expiry for i in ins.values()))
    runs=[]
    for preset in (PRESETS[0],PRESETS[-1]):
        for interval in (500,100):
            engine=Engine(ins,Ledger(goal.initial.copy()),goal,11,event_cap=100000)
            engine.seed_market(seeds,start);engine.add_tape(tape)
            gen=CandidateGenerator(budget=96,quantities=preset['quantities'],offsets=preset['offsets'])
            timings=[];stages=[0.,0.,0.,0.];hist={};actions={}
            wall=time.perf_counter();cpu=time.process_time()
            for now in range(start,end,interval):
                if time.perf_counter()-began>180:raise RuntimeError('180-second benchmark cap')
                t0=time.perf_counter();engine.advance(now);obs=engine.observe();t1=time.perf_counter()
                candidates,audit=gen.generate(obs,goal,ins);t2=time.perf_counter()
                action=candidates[analytical(obs,candidates,goal,ins)];t3=time.perf_counter()
                engine.submit(action);t4=time.perf_counter()
                for i,d in enumerate((t1-t0,t2-t1,t3-t2,t4-t3)):stages[i]+=d
                timings.append((t4-t0)*1000)
                hist[len(candidates)]=hist.get(len(candidates),0)+1
                actions[action.kind]=actions.get(action.kind,0)+1
            engine.advance(end)
            elapsed=time.perf_counter()-wall;cpu_elapsed=time.process_time()-cpu
            runs.append(dict(preset=preset['name'],interval_ms=interval,simulated_seconds=120,
                             decisions=len(timings),wall_seconds=elapsed,cpu_seconds=cpu_elapsed,
                             mean_decision_ms=statistics.mean(timings),p50_ms=statistics.median(timings),
                             p95_ms=sorted(timings)[int(.95*len(timings))],
                             stage_seconds=dict(zip(('advance_observe','generate_filter','score','submit'),stages)),
                             accepted_candidate_counts=hist,selected_actions=actions,fills=len(engine.hidden.fills),
                             failures=bool(engine.hidden.failures),events=engine.hidden.processed,
                             extrapolated_90_day_cpu_hours=(90*86400000/interval)*cpu_elapsed/len(timings)/3600,
                             extrapolated_90_day_serial_wall_hours=(90*86400000/interval)*elapsed/len(timings)/3600))
    cpuinfo=Path('/proc/cpuinfo').read_text()
    result=dict(runs=runs,elapsed_seconds=time.perf_counter()-began,source_manifest=manifest,
                environment=dict(python=platform.python_version(),platform=platform.platform(),
                                 cpu_model=next(s.split(':',1)[1].strip() for s in cpuinfo.splitlines() if s.startswith('model name')),
                                 cpu_quota=Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
                                 memory_limit_bytes=Path('/sys/fs/cgroup/memory.max').read_text().strip(),
                                 peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024),
                limitations=['120-second early-window samples only; ledger/order complexity changes cost.',
                             'Single process; no GPU or neural inference measured.',
                             'Subsecond decisions use all exact recorded trade events, no interpolated prices.',
                             '90-day projections exclude collection/fitting/evaluation repetitions, long-ledger growth and I/O.'])
    write(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='source_manifest'}))


if __name__=='__main__':main()
