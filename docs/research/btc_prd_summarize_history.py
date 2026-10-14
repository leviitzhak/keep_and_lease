"""Validate and compact the eight full-history artifacts; no parameter selection."""
import argparse,gzip,hashlib,json,statistics
from collections import Counter,defaultdict
from pathlib import Path
from btc_prd_full_history import eligible

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 reports=[json.loads(p.read_text()) for p in sorted(a.artifacts.rglob('BTC-*.json'))]
 expected={r['instrument'] for r in json.loads(a.plan.read_text())['instruments'] if eligible(r)}
 assert {r['symbol'] for r in reports}==expected and len(reports)==len(expected)
 runs=[];counts=Counter();summaries=[];years=defaultdict(list)
 for r in reports:
  assert r['audit']['status']=='PASS'
  counts.update({k:v for k,v in r['counts'].items() if k!='final_mark_is_trade_price_fallback'})
  summaries.append({k:v for k,v in r.items() if k not in ('runs','sources','limitations')})
  years[r['train_end'][:4]].append(r)
  for run in r['runs']:
   assert abs(run['net_marked_usd_per_10_face']-run['completed_cycle_realized_net_usd']-run['unfinished_cycle_realized_net_usd']-run['unrealized_mark_net_usd'])<1e-8
   assert abs(run['completed_cycle_realized_net_usd']-sum(run[k] for k in ('completed_cycle_future_realized_usd','completed_cycle_proxy_price_gain_usd','completed_cycle_proxy_expense_effect_usd','completed_cycle_proxy_surcharge_effect_usd'))+run['completed_cycle_fees_usd'])<1e-8
   runs.append(run)
 base={(r['symbol'],r['high'],r['low']):r for r in runs if r['scenario']=='base'}
 delay_comparison={}
 for scenario in ('one_ms_delays','two_second_delays','always_posted'):
  c=Counter()
  for r in runs:
   if r['scenario']!=scenario:continue
   b=base[r['symbol'],r['high'],r['low']];d=r['completed_cycles']-b['completed_cycles']
   c['more_cycles' if d>0 else 'fewer_cycles' if d<0 else 'equal_cycles']+=1
  delay_comparison[scenario]=dict(c)
 delay_pnl_comparison={}
 for scenario in ('one_ms_delays','two_second_delays'):
  measures={}
  for label,metric in [('completed_realized','completed_cycle_realized_net_usd'),('marked_total','net_marked_usd_per_10_face')]:
   c=Counter()
   for r in runs:
    if r['scenario']!=scenario:continue
    delta=r[metric]-base[r['symbol'],r['high'],r['low']][metric]
    c['better' if delta>1e-9 else 'worse' if delta< -1e-9 else 'same']+=1
   measures[label]=dict(c)
  delay_pnl_comparison[scenario]=measures
 shard_summaries=[json.loads(p.read_text()) for p in a.artifacts.rglob('shard-summary.json')]
 assert len(shard_summaries)==8 and {r['shard'] for r in shard_summaries}==set(range(8))
 fixed=[]
 for scenario in sorted({r['scenario'] for r in runs}):
  rs=[r for r in runs if r['scenario']==scenario and r['high']==.02 and r['low']==.01]
  fixed.append(dict(scenario=scenario,runs=len(rs),completed_cycles=sum(r['completed_cycles'] for r in rs),
    contracts_with_completed_cycles=sum(r['completed_cycles']>0 for r in rs),
    contracts_ending_short=sum(r['remaining_short_face']>0 for r in rs),
    contracts_ending_proxy_only=sum(r['remaining_short_face']==0 and r['remaining_proxy_btc']>0 for r in rs),
    completed_cycle_realized_net_usd_sum=sum(r['completed_cycle_realized_net_usd'] for r in rs),
    unfinished_cycle_realized_net_usd_sum=sum(r['unfinished_cycle_realized_net_usd'] for r in rs),
    unrealized_mark_net_usd_sum=sum(r['unrealized_mark_net_usd'] for r in rs)))
 annual=[]
 for year,rr in sorted(years.items()):
  rs=[r for g in rr for r in g['runs'] if r['scenario']=='base' and r['high']==.02 and r['low']==.01]
  annual.append(dict(heldout_start_year=year,contracts=len(rr),median_training_prd=statistics.median(g['training']['quantiles']['0.5'] for g in rr),
   reference_cycles=sum(r['completed_cycles'] for r in rs),reference_contracts_with_cycles=sum(r['completed_cycles']>0 for r in rs)))
 result=dict(status='PASS',scope='full eligible proxy-future unit history, not funded portfolio',contracts=len(reports),runs=len(runs),
  execution_replays=sum(not r.get('fee_only_same_execution_path',False) for r in runs),
  audited_fills=sum(r['audit']['fills'] for r in reports),counts=dict(counts),
  first_observation=min(r['first_observation'] for r in reports),last_end=max(r['end'] for r in reports),
  first_heldout_start=min(r['train_end'] for r in reports),
  contracts_with_terminal_trade_mark=sum(r['counts']['final_mark_is_trade_price_fallback'] for r in reports),
  delay_comparison=delay_comparison,delay_pnl_comparison=delay_pnl_comparison,fixed_2_1=fixed,annual=annual,
  archive_cache_bytes_summed_over_8_shards=sum(int(p.read_text().split()[0]) for p in a.artifacts.rglob('cache-size.txt')),
  longest_shard_study_seconds=max(sum(r['metrics']['total_seconds'] for r in s['summaries']) for s in shard_summaries),
  artifact_result_bytes=sum(p.stat().st_size for p in a.artifacts.glob('shard-*/*') if p.is_file()),
  workflow_run='https://github.com/leviitzhak/keep_and_lease/actions/runs/38597440889',
  operator_commit='e0042cafebcbb6541916833697193786c3fe72ce',
  metrics=dict(total_contract_seconds=sum(r['metrics']['total_seconds'] for r in reports),
   total_replay_audit_seconds=sum(r['metrics']['replay_and_audit_seconds'] for r in reports),
   maximum_worker_rss_mib=max(r['metrics']['peak_process_rss_mib'] for r in reports),
   largest_contract_ordinary_rows=max(r['counts']['ordinary_rows'] for r in reports),
   required_compressed_trade_bytes=sum(r['counts']['compressed_trade_bytes'] for r in reports)),
  engine_sha256=sorted({r['engine_sha256'] for r in reports}),study_source_sha256=sorted({r['source_sha256'] for r in reports}),
  contract_summaries=summaries)
 (a.output/'btc-prd-full-history-summary.json').write_text(json.dumps(result,indent=2)+'\n')
 (a.output/'btc-prd-full-history-runs.json.gz').write_bytes(gzip.compress(json.dumps(runs,separators=(',',':')).encode(),mtime=0))
 sources={r['symbol']:r['sources'] for r in reports}
 (a.output/'btc-prd-full-history-sources.json.gz').write_bytes(gzip.compress(json.dumps(sources,separators=(',',':')).encode(),mtime=0))
 print(json.dumps({k:v for k,v in result.items() if k!='contract_summaries'},indent=2))

if __name__=='__main__':main()
