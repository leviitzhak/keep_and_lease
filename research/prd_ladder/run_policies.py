from pathlib import Path
import hashlib,json,sys,time,os,multiprocessing
from concurrent.futures import ProcessPoolExecutor
from policies import PolicyReplay,scenarios,save_policy
from replay import load_rows,ms

_INPUT=None
def one_case(item):
    events,coverage,symbols,expiry,seeds,start,end,out,code_hash=_INPUT
    name,kwargs=item;began=time.monotonic()
    r=PolicyReplay(symbols,expiry,seeds,start,end,participation=1.,opposite_aggressor=False,name=name,**kwargs)
    result=r.run(events);result['policy_source_sha256']=code_hash
    save_policy(out/name,r,result,coverage)
    brief=dict(case=name,seconds=round(time.monotonic()-began,2),fills=len(r.fills),
        gross_btc=result['final']['gross_btc'],backlog=result['final']['backlog_btc'],
        episodes=result['episode_outcomes'],mirror_diagnostic=result.get('ideal_mirror_lock_trade_through_events',0))
    print(json.dumps(brief),flush=True)
    return brief

def run_cases(events,coverage,symbols,expiry,seeds,start,end,out,names=None):
    global _INPUT
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    code_hash=hashlib.sha256(Path(__file__).with_name('policies.py').read_bytes()).hexdigest()
    _INPUT=(events,coverage,symbols,expiry,seeds,start,end,out,code_hash)
    selected=[x for x in scenarios() if not names or x[0] in names]
    workers=min(4,max(1,int(os.environ.get('PRD_CASE_WORKERS','2'))))
    if workers==1:
        for item in selected:one_case(item)
    else:
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('fork')) as pool:
            list(pool.map(one_case,selected))

if __name__=='__main__':
    root=Path(sys.argv[1]);out=Path(sys.argv[2]);names=sys.argv[3:] or None
    symbols=['BTC-25SEP26','BTC-25DEC26'];start=ms('2026-03-06');end=ms('2026-06-06')
    expiry=[ms('2026-09-25T08:00:00Z'),ms('2026-12-25T08:00:00Z')]
    seeds={s:json.loads((root/'seeds'/f'{s}.json').read_text()) for s in symbols}
    events,coverage=load_rows([root/'trades'/f'{s}.jsonl.gz' for s in symbols],symbols,start,end)
    print(json.dumps({'stage':'loaded','events':len(events)}),flush=True)
    run_cases(events,coverage,symbols,expiry,seeds,start,end,out,names)
