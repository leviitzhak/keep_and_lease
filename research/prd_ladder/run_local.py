from pathlib import Path
import json,sys
from replay import Replay,load_rows,save_run,ms

root=Path(sys.argv[1]);out=Path(sys.argv[2])
symbols=['BTC-25SEP26','BTC-25DEC26']
start=ms('2026-03-06');end=ms('2026-06-06')
expiry=[ms('2026-09-25T08:00:00Z'),ms('2026-12-25T08:00:00Z')]
seeds={s:json.loads((root/'seeds'/f'{s}.json').read_text()) for s in symbols}
events,coverage=load_rows([root/'trades'/f'{s}.jsonl.gz' for s in symbols],symbols,start,end)
for name,delay,participation,agg in [('base',500,1.,False),('opposite_aggressor',500,1.,True),('ten_percent_volume',500,.1,False),('one_second',1000,1.,False),('ten_ms',10,1.,False)]:
    r=Replay(symbols,expiry,seeds,start,end,delay,participation,agg,name)
    result=r.run(events);save_run(out/name,r,result,coverage)
    print(json.dumps(result),flush=True)
