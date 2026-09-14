#!/usr/bin/env python3
"""Read-only, observation-level BTC lease/maturity history; never replays a portfolio.

Uses immutable public-market inputs in the project market-data bucket only.
Each ordinary futures trade is matched to the latest spot trade at/before its
reported timestamp; the maximum gap defaults to one second. Keeps exact source
prices/amounts and calculation components. No quote-depth executability claim.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backtest_silver_lease_strategy as strategy

BUCKET = 'keep-and-lease-market-data'
RANGE_SHA = '52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912'
DAY_US = 86_400_000_000
EPOCH = dt.datetime(1970, 1, 1)
COLUMNS = ['timestamp_us','symbol','price','native_quantity','quantity_currency',
           'quote_currency','side','trade_id','source_sequence','flags','source_file']


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def timestamp(value):
    day = dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if day.tzinfo:
        day = day.astimezone(dt.timezone.utc).replace(tzinfo=None)
    delta = day-EPOCH
    return (delta.days*86400+delta.seconds)*1_000_000+delta.microseconds


def iso(value):
    return (EPOCH+dt.timedelta(microseconds=int(value))).isoformat(timespec='microseconds')+'Z'


class Inputs:
    """No listing, results access, IAM edits, uploads, credentials in outputs."""
    def __init__(self, mode, directory=None, budget=16*1024**3):
        self.mode, self.directory, self.budget = mode, directory, budget
        self.bytes = 0
        self.receipts = {}
        if mode == 'adc':
            from google.cloud import storage
            self.bucket = storage.Client(project='keep-and-lease').bucket(BUCKET)

    def fetch(self, name, expected, target, cap=512*1024**2):
        if (not re.fullmatch(r'btc/trades/(?:ranges|v1)/[0-9a-f]{64}/[A-Za-z0-9_=./-]+',name)
                or '..' in name or not re.fullmatch('[0-9a-f]{64}',expected)):
            raise ValueError('Input outside fixed immutable market namespace')
        generation = None
        if self.mode == 'local':
            original = Path(self.directory)/name
            size = original.stat().st_size
        elif self.mode == 'adc':
            blob = self.bucket.blob(name); blob.reload(timeout=60)
            size, generation = int(blob.size), int(blob.generation)
        else:
            uri = f'gs://{BUCKET}/{name}'
            metadata = json.loads(subprocess.check_output([
                'gcloud','storage','objects','describe',uri,'--raw','--format=json'],timeout=90))
            size,generation = int(metadata['size']),str(metadata['generation'])
        if size > cap or self.bytes+size > self.budget:
            raise ValueError('Market input budget exceeded')
        target = Path(target)
        if target.exists():
            raise ValueError('Refusing to overwrite input')
        if self.mode == 'local':
            import shutil
            shutil.copyfile(original,target)
        elif self.mode == 'adc':
            blob.download_to_filename(str(target),if_generation_match=generation,timeout=180,checksum='crc32c')
        else:
            with target.open('xb') as f:
                subprocess.run(['gcloud','storage','cat',uri+'#'+generation],stdout=f,check=True,timeout=240)
        self.bytes += size
        if target.stat().st_size != size or digest(target) != expected:
            raise ValueError('Immutable market input size/hash mismatch')
        self.receipts[name] = dict(generation=generation,bytes=size,sha256=expected)
        return target


def batches(paths):
    last = None
    for path in paths:
        with pq.ParquetFile(path,pre_buffer=False,page_checksum_verification=True) as f:
            required = set(COLUMNS)
            if not required.issubset(f.schema_arrow.names):
                raise ValueError('Unsupported market schema')
            for b in f.iter_batches(batch_size=65536,columns=COLUMNS,use_threads=False):
                ts = b.column(0).to_numpy(zero_copy_only=False)
                if len(ts) and (np.any(ts[1:]<ts[:-1]) or last is not None and ts[0]<last):
                    raise ValueError('Unordered reported market timestamps')
                if len(ts): last=int(ts[-1])
                yield b


def spot_match(times, paths, carry=None):
    """Backward-only join, including equal timestamps and batch/day boundaries.

    Resolves all duplicate spot timestamps before choosing their last sequence
    record. At equal cross-venue timestamps no true arrival ordering is claimed.
    """
    times=np.asarray(times,dtype=np.int64)
    if np.any(times[1:]<times[:-1]): raise ValueError('Unordered futures timestamps')
    matches=[None]*len(times); pos=0; count=0
    for b in batches(paths):
        count+=len(b)
        ts=b.column(0).to_numpy(zero_copy_only=False)
        if not len(ts): continue
        stop=int(np.searchsorted(times,ts[-1],side='left'))
        if stop>pos:
            idx=np.searchsorted(ts,times[pos:stop],side='right')-1
            picked=b.take(pa.array(np.maximum(idx,0))).to_pylist()
            for k,record in enumerate(picked):
                matches[pos+k]=carry if idx[k]<0 else record
            pos=stop
        carry=b.slice(len(b)-1,1).to_pylist()[0]
    for i in range(pos,len(times)): matches[i]=carry
    return matches,carry,count


class Rates:
    def __init__(self,root):
        self.series = strategy.read_rates(root)
        self.rows={}
        for tenor,name in strategy.TENORS:
            records=self.series[tenor]
            available=[timestamp(strategy._rate_available_at(d,EPOCH).isoformat()) for d,r in records]
            self.rows[tenor]=(name,records,np.asarray(available,dtype=np.int64))

    def at(self,t,maturity):
        day=EPOCH+dt.timedelta(microseconds=int(t))
        rate=strategy.usd_rate(self.series,day,maturity)
        details=[]
        for tenor,r,w in strategy.usd_rate_components(self.series,day,maturity):
            name,records,available=self.rows[tenor]
            i=int(np.searchsorted(available,t,side='right'))-1
            if i<0 or not math.isclose(r,records[i][1],abs_tol=1e-15):
                raise ValueError('Rate component inconsistency')
            details.append(dict(series=name,tenor_days=tenor,
                observation=records[i][0].isoformat(),available_at_utc=iso(available[i]),
                yield_fraction=r,interpolation_weight=w))
        return rate,details


def calculate(future,spot,expiry,rates,max_gap_us):
    t=int(future['timestamp_us']); d=(expiry-t)/DAY_US
    if d<=0:return None,'expired'
    if int(future['flags'])!=0:return None,'block_or_combo'
    if spot is None:return None,'no_previous_spot'
    gap=t-int(spot['timestamp_us'])
    if gap<0:raise ValueError('Noncausal spot pair')
    if gap>max_gap_us:return None,'spot_gap_exceeded'
    if future['quote_currency']!='USD' or spot['quote_currency']!='USDT':
        raise ValueError('Unexpected price currency; no silent currency conversion')
    f,s=float(future['price']),float(spot['price'])
    if not all(math.isfinite(x) and x>0 for x in (f,s)): raise ValueError('Invalid prices')
    r,components=rates.at(t,d)
    if r is None:return None,'no_observable_yield'
    premium=f/s-1; annual=premium*365/d; lease=r-annual
    return dict(time_utc=iso(t),future_timestamp_us=t,spot_timestamp_us=int(spot['timestamp_us']),
        symbol=future['symbol'],expiry_utc=iso(expiry),maturity_days=d,
        future_price_source=str(future['price']),spot_price_source=str(spot['price']),
        futures_quote_currency=future['quote_currency'],spot_quote_currency=spot['quote_currency'],
        future_trade_id=future['trade_id'],spot_trade_id=spot['trade_id'],
        future_sequence=future['source_sequence'],spot_sequence=spot['source_sequence'],
        future_native_quantity=str(future['native_quantity']),future_quantity_currency=future['quantity_currency'],
        spot_native_quantity=str(spot['native_quantity']),spot_quantity_currency=spot['quantity_currency'],
        future_side=future['side'],spot_side=spot['side'],future_flags=int(future['flags']),
        future_source_file=future['source_file'],spot_source_file=spot['source_file'],
        timestamp_gap_seconds=gap/1e6,premium_fraction=premium,premium_bps=premium*10000,
        annualized_premium_fraction=annual,usd_rate_fraction=r,lease_fraction=lease,lease_pct=lease*100,
        treasury_components=json.dumps(components,separators=(',',':'),allow_nan=False)),None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest-sha',default=RANGE_SHA)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--io',choices=['adc','gcloud','local'],default='gcloud')
    p.add_argument('--local-market-root',type=Path)
    p.add_argument('--max-gap-seconds',type=float,default=1)
    p.add_argument('--max-read-gib',type=float,default=16)
    p.add_argument('--start',type=dt.date.fromisoformat)
    p.add_argument('--end',type=dt.date.fromisoformat,help='Exclusive UTC day')
    a=p.parse_args()
    if (not re.fullmatch('[0-9a-f]{64}',a.manifest_sha) or not math.isfinite(a.max_gap_seconds)
            or not 0<a.max_gap_seconds<=60 or not math.isfinite(a.max_read_gib) or a.max_read_gib<=0):
        p.error('Invalid manifest, timing window or read budget')
    a.output.mkdir(parents=True,exist_ok=False)
    output=a.output; (output/'calculations').mkdir(); (output/'manifests').mkdir()
    write=lambda name,value:(output/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    write('summary.json',dict(status='INCOMPLETE',mode='market-data observation scatter; not a backtest'))
    inputs=Inputs(a.io,a.local_market_root,int(a.max_read_gib*1024**3)); rates=Rates(ROOT)
    topname=f'btc/trades/ranges/{a.manifest_sha}/manifest.json'
    topfile=inputs.fetch(topname,a.manifest_sha,output/'manifests'/'range.json',cap=8*1024**2)
    top=json.loads(topfile.read_text()); days=top['daily_datasets']; source=top['source_manifest']
    expected=timestamp(source['start'])
    for day in days:
        lo,hi=timestamp(day['start']),timestamp(day['end'])
        if lo!=expected or hi-lo!=DAY_US or lo%DAY_US:raise ValueError('Noncontiguous UTC coverage')
        expected=hi
    if expected!=timestamp(source['end']):raise ValueError('Invalid range end')
    start=timestamp(a.start.isoformat()) if a.start else timestamp(source['start'])
    end=timestamp(a.end.isoformat()) if a.end else timestamp(source['end'])
    if not timestamp(source['start'])<=start<end<=timestamp(source['end']):raise ValueError('Selected range outside manifest')
    chosen=[d for d in days if start<=timestamp(d['start'])<end]
    expiries={s:timestamp(v['expiry']) for s,v in source['futures'].items()}
    write('contract_metadata.json',source['futures'])
    records=[]; carry=None; points=[]; symbols=sorted(expiries); codes={s:i for i,s in enumerate(symbols)}
    for n,day in enumerate(chosen):
        label=day['start'][:10]; h=day['manifest_sha256']; prefix='btc/trades/v1/'+h+'/'
        childfile=inputs.fetch(prefix+'manifest.json',h,output/'manifests'/f'{label}.json',cap=8*1024**2)
        child=json.loads(childfile.read_text())
        if child['source_manifest']['start']!=day['start'] or child['source_manifest']['end']!=day['end']:
            raise ValueError('Child coverage differs')
        if not carry and timestamp(day['start'])>timestamp(source['start']):
            # A selected subrange deliberately does not use an invented prior mark.
            # Only its first futures prints may be excluded until a spot print exists.
            pass
        with tempfile.TemporaryDirectory(prefix='lease-market-') as temp:
            spotpaths=[]; futpaths=[]; expected_spot=expected_futures=0
            for i,part in enumerate(child['partitions']):
                path=inputs.fetch(prefix+part['path'],part['sha256'],Path(temp)/f'{i}.parquet')
                if '/market=spot/' in part['path']:spotpaths.append(path);expected_spot+=part['rows']
                elif '/market=dated-futures/' in part['path']:futpaths.append(path);expected_futures+=part['rows']
                else:raise ValueError('Unexpected market partition')
            futures=[r for b in batches(futpaths) for r in b.to_pylist()]
            if len(futures)!=expected_futures:raise ValueError('Futures row-count mismatch')
            if len({(r['symbol'],r['trade_id']) for r in futures})!=len(futures):raise ValueError('Duplicate futures IDs')
            if any(not timestamp(day['start'])<=int(r['timestamp_us'])<timestamp(day['end']) for r in futures):
                raise ValueError('Future observation outside daily partition')
            matches,carry,spot_count=spot_match([r['timestamp_us'] for r in futures],spotpaths,carry)
            if spot_count!=expected_spot:raise ValueError('Spot row-count mismatch')
            counts=dict(date=label,futures_records=len(futures),spot_records=spot_count,paired=0,paired_10days=0,rejected={})
            target=output/'calculations'/f'{label}.csv.gz'; writer=None
            with gzip.open(target,'wt',newline='',compresslevel=3) as stream:
                for f,s in zip(futures,matches):
                    row,reason=calculate(f,s,expiries[f['symbol']],rates,round(a.max_gap_seconds*1e6))
                    if reason:counts['rejected'][reason]=counts['rejected'].get(reason,0)+1;continue
                    row['daily_manifest_sha256']=h
                    if writer is None:writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader()
                    writer.writerow(row)
                    points.append([row['future_timestamp_us']/1e6,row['maturity_days'],row['lease_pct'],row['premium_bps'],codes[row['symbol']]])
                    counts['paired']+=1;counts['paired_10days']+=row['maturity_days']>=10
            counts['calculation_sha256']=digest(target);records.append(counts)
            write('progress.json',dict(completed_days=len(records),total_days=len(chosen),days=records,bytes_read=inputs.bytes))
            print(f"Verified {label}: {counts['paired']:,} paired of {len(futures):,} futures observations ({n+1}/{len(chosen)})",flush=True)
    data=np.asarray(points,dtype=np.float64).reshape((-1,5))
    np.savez_compressed(output/'scatter_points.npz',data=data)
    summary=dict(status='COMPLETE',mode='reported-time market observations; no portfolio replay',
        source_manifest_sha256=a.manifest_sha,period=dict(start=iso(start),end_exclusive=iso(end)),
        color_time='reported futures observation timestamp UTC',max_gap_seconds=a.max_gap_seconds,
        join='latest spot at or before each distinct ordinary futures trade; no forward match or time interpolation',
        source_rows=sum(x['futures_records'] for x in records),points=len(points),points_min_10_days=int(np.sum(data[:,1]>=10)),
        symbols=symbols,point_columns=['unix_seconds','maturity_days','lease_pct','premium_bps','symbol_index'],days=records,
        input_bytes_read=inputs.bytes,input_receipts=inputs.receipts,
        rate_source_sha256={name+'.csv':digest(ROOT/(name+'.csv')) for _,name in strategy.TENORS},
        formula_source_sha256=digest(ROOT/'backtest_silver_lease_strategy.py'),script_sha256=digest(__file__),
        notes=['All accepted pairs retained, including negative rates and near-expiry values.',
               'Trade-print size is executed volume, not remaining order-book liquidity.',
               'USD futures price proxy / USDT-parity spot; no FX conversion.',
               'Reported timestamps are not an observation of true cross-venue arrival order.',
               'Block/combo, expired, unmatched and beyond-gap records are counted by reason.',
               'Every raw futures print is considered, unlike the prior day view drawn from saved decision references.',
               'At an equal timestamp the last spot source sequence is used; unknown sub-timestamp arrival order remains.',
               'Date-only Treasury observations become available on the next UTC midnight; only maturity interpolation.'])
    write('summary.json',summary)
    print(f"COMPLETE: {len(points):,} pairs across {len(chosen)} UTC days",flush=True)

if __name__=='__main__':main()
