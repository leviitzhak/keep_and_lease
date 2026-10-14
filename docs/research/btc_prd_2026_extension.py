"""Reproduce requested comparisons on the previously frozen 2026 grid."""
import argparse,gzip,hashlib,json,time,resource,platform
from pathlib import Path
from btc_prd_execution_calibration import Experiment,Trade,FLAGS,ms,stamp
from btc_prd_full_history import audit_fills,fee_sensitivity

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=True);root=Path(__file__).parent
 grid=json.loads((root/'btc-prd-calibration-config.json').read_text())['candidates']
 coverage=json.loads((a.inputs/'input_coverage.json').read_text());spec=json.loads((a.inputs/'specification.json').read_text())
 start_clock=time.perf_counter();results=[];hashes=[];all_raw=all_rows=audited=0;replay_seconds=0
 scenarios=[('base',{}),('one_ms_delays',dict(delay=1)),('two_second_delays',dict(delay=2000)),('always_posted',dict(band=None)),('proxy_cost',dict(proxy_expense=.0025,surcharge=.005))]
 with gzip.GzipFile(filename=str(a.output/'btc-prd-2026-extension-fills.jsonl.gz'),mode='wb',mtime=0) as out:
  for symbol,expiry in zip(spec['symbols'],spec['expiry']):
   rows=[]
   for source in coverage:
    if symbol not in source['path']:continue
    path=a.inputs/'inputs'/Path(source['path']).name;b=path.read_bytes();assert hashlib.sha256(b).hexdigest()==source['sha256'];hashes.append(source)
    for line in gzip.decompress(b).splitlines():
     r=json.loads(line);all_raw+=1
     if any(r.get(k) for k in FLAGS):continue
     assert min(r['price'],r['index_price'],r['mark_price'],r['amount'])>0
     rows.append(Trade(r['timestamp'],r['price'],r['index_price'],r['mark_price'],r['amount'],r['direction'],str(r['trade_id'])))
   assert all(b.t>=a.t for a,b in zip(rows,rows[1:]));all_rows+=len(rows)
   for phase,start,end in [('validation',spec['start'],ms('2026-07-21T00:00:00Z')),('test',ms('2026-07-21T00:00:00Z'),spec['end'])]:
    tape=[r for r in rows if start<=r.t<end];maps=({r.id:r for r in tape},{r.t:r for r in tape})
    for c in grid:
     for name,kw in scenarios:
      e=Experiment(expiry,start,end,c['high'],c['low'],**kw);clock=time.perf_counter();r=e.run(tape);replay_seconds+=time.perf_counter()-clock
      audited+=audit_fills(e,tape,r,maps);r.update(symbol=symbol,phase=phase,scenario=name,start=stamp(start),end=stamp(end));results.append(r)
      for f in e.fills:out.write((json.dumps(dict(symbol=symbol,phase=phase,scenario=name,high=c['high'],low=c['low'],fill=f),separators=(',',':'))+'\n').encode())
      if name=='base':
       for label,f,p in [('no_fees',0,0),('maker_rebate_minus_1bp',-1,0),('maker_rebate_minus_0_2bp',-.2,0)]:
        r2=fee_sensitivity(r,e.fills,f,p);r2['scenario']=label;results.append(r2)
    print(json.dumps(dict(symbol=symbol,phase=phase,runs=len(results))),flush=True)
 report=dict(status='PASS_independent_unit_probes',runs=results,raw_rows=all_raw,ordinary_rows=all_rows,audited_fills=audited,source_hashes=hashes,
  benchmark=dict(total_seconds=time.perf_counter()-start_clock,replay_seconds=replay_seconds,peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,python=platform.python_version()),
  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),engine_sha256=hashlib.sha256((root/'btc_prd_execution_calibration.py').read_bytes()).hexdigest())
 (a.output/'btc-prd-2026-extension.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k not in ('runs','source_hashes')}),flush=True)

if __name__=='__main__':main()
