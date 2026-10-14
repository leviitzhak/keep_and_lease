"""Attribute fixed 2%/1% completed cycles to paired and unpaired intervals.

Only zero expense/surcharge base and delay sensitivities are eligible for this
simple exact decomposition. Sums are independent unit experiments, not returns.
"""
import argparse,gzip,json
from collections import Counter
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 scenarios=['base','one_ms_delays','two_second_delays'];out={s:Counter() for s in scenarios}
 for path in sorted(a.artifacts.rglob('*-fills.jsonl.gz')):
  pending={s:[] for s in scenarios}
  for line in gzip.open(path,'rt'):
   f=json.loads(line);s=f['scenario']
   if s not in out or f['high']!=.02 or f['low']!=.01:continue
   pending[s].append(f)
   if f['phase']!=3:continue
   cycle=pending[s];assert [x['phase'] for x in cycle]==[0,1,2,3]
   buy,entry,close,sell=cycle;q=10/buy['index']
   pre=q*(entry['index']-buy['index'])
   pair=q*(close['index']-entry['index'])+close['cash_usd']+close['fee_usd']
   post=q*(sell['index']-close['index'])
   fees=sum(x['fee_usd'] for x in cycle);net=sum(x['cash_usd'] for x in cycle)
   assert abs(net-(pre+pair+post-fees))<1e-8
   out[s].update(dict(completed_cycles=1,pre_short_proxy_gain_usd=pre,
       both_legs_open_gross_gain_usd=pair,post_short_close_proxy_gain_usd=post,
       fees_usd=fees,completed_net_usd=net));pending[s]=[]
 a.output.write_text(json.dumps({s:dict(v) for s,v in out.items()},indent=2)+'\n')

if __name__=='__main__':main()
