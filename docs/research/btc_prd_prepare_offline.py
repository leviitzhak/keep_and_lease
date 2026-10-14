"""Fetch the fixed research inputs once; execution replay then works offline.

Requires the owner's existing Google Application Default Credentials with read
access to the archive bucket. Does not grant IAM permissions or call Deribit.
"""
import argparse,concurrent.futures,json
from pathlib import Path
from btc_prd_full_history import Archive,PLAN,JOB,eligible,DAY

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,required=True);p.add_argument('--symbol');a=p.parse_args()
 archive=Archive(a.cache);plan=archive.json(PLAN);manifest=archive.json(JOB+'/manifest.json')
 assert manifest['status']=='COMPLETE_AVAILABLE_HISTORY'
 selected=[r for r in plan['instruments'] if eligible(r) and (not a.symbol or r['instrument']==a.symbol)]
 if not selected:raise ValueError('No eligible contract matched')
 for item in selected:
  end=min(item['last_trade'][0]['timestamp']+1,item['metadata']['expiration_timestamp']-60*DAY)
  hi=item['last_available_seq'];symbol=item['instrument'];keys=[f'{JOB}/receipts/{symbol}/{s:012d}-{min(s+9999,hi):012d}.json' for s in range(item['first_available_seq'],hi+1,10000)]
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:receipts=list(pool.map(archive.json,keys))
  objects=[next(o for o in r['objects'] if o['key'].endswith('/trades.jsonl.gz')) for r in receipts if r['min_timestamp'] is None or r['min_timestamp']<end]
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
   for _ in pool.map(lambda o:len(archive.get(o['key'],o['sha256'])),objects):pass
  print(json.dumps(dict(symbol=symbol,objects=len(objects),compressed_trade_bytes=sum(o['bytes'] for o in objects))),flush=True)
 (a.cache/'offline-download-receipt.json').write_text(json.dumps(dict(contracts=len(selected),io=dict(archive.counts),source=JOB),indent=2)+'\n')

if __name__=='__main__':main()
