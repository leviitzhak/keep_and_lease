"""Bounded full retained archive study. Same command supports offline cache replay.

Network mode reads only the frozen completed BTC archive; no exchange calls,
orders, deployment, IAM changes, or writes to existing archive objects.
"""
from __future__ import annotations
import argparse, concurrent.futures, gzip, hashlib, json, math, os, platform
import resource, time
from collections import Counter
from pathlib import Path
from btc_prd_execution_calibration import Experiment, Trade, FACE, DAY, FLAGS, ms, stamp, minus_months, distribution

BUCKET='keep-and-lease-market-data'
PREFIX='btc/research/deribit-full-history-v1'
JOB=PREFIX+'/jobs/btc-full-20261009-archive'
PLAN=JOB+'/plan-reconciled-v2.json'


def encode(x): return json.dumps(x, separators=(',',':'), allow_nan=False).encode()
def sha(b): return hashlib.sha256(b).hexdigest()


class Archive:
    def __init__(self, root, offline=False):
        self.root=Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.counts=Counter(); self.bucket=None
        if not offline:
            from google.cloud import storage
            self.bucket=storage.Client(project='keep-and-lease').bucket(BUCKET)
    def get(self,key,expected=None):
        assert key.startswith(PREFIX+'/') and '..' not in key
        path=self.root/key
        if path.exists():
            b=path.read_bytes(); self.counts['cache_bytes_read']+=len(b)
        else:
            if self.bucket is None: raise FileNotFoundError(path)
            b=self.bucket.blob(key).download_as_bytes(checksum='crc32c')
            path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b)
            self.counts['download_bytes']+=len(b)
        if expected: assert sha(b)==expected,(key,'sha256')
        return b
    def json(self,key): return json.loads(self.get(key))


def eligible(item):
    return bool(item['first_trade']) and item['first_trade'][0]['timestamp'] < minus_months(item['metadata']['expiration_timestamp'],3)


def load_contract(a,item,end):
    symbol=item['instrument']; lo=item['first_available_seq']; hi=item['last_available_seq']
    keys=[f'{JOB}/receipts/{symbol}/{s:012d}-{min(s+9999,hi):012d}.json' for s in range(lo,hi+1,10000)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        receipts=list(pool.map(a.json,keys))
    counts=Counter(receipt_rows=sum(r['rows'] for r in receipts)); sources=[]
    relevant=[]
    for offset,(key,r) in enumerate(zip(keys,receipts)):
        assert r['status']=='COMPLETE' and r['instrument']==symbol
        assert r['rows']==r['last_seq']-r['first_seq']+1
        assert r['first_seq']==lo+10000*offset and r['last_seq']==min(lo+10000*(offset+1)-1,hi)
        if r['min_timestamp'] is not None and r['min_timestamp'] >= end:
            counts['rows_after_study_end_not_loaded']+=r['rows']; continue
        obj=next(o for o in r['objects'] if o['key'].endswith('/trades.jsonl.gz'))
        relevant.append((r,obj)); sources.append(dict(receipt=key,**obj))
    # Prefetch bounded objects concurrently; bytes remain in cache, not in a giant list.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for _ in pool.map(lambda ro:len(a.get(ro[1]['key'],ro[1]['sha256'])),relevant):pass
    rows=[]; last=-1; seen=set()
    prefix_max={}
    running=-1
    for receipt in receipts:
        prefix_max[receipt['first_seq']]=running
        running=max(running,receipt['max_timestamp'] or -1)
    for r,obj in relevant:
        last=max(last,prefix_max[r['first_seq']])
        data=a.get(obj['key'],obj['sha256']); assert len(data)==obj['bytes']
        n=0
        for line in gzip.decompress(data).splitlines():
            x=json.loads(line); n+=1; counts['raw_rows_loaded']+=1
            assert x['instrument_name']==symbol and x['trade_seq']==r['first_seq']+n-1
            t=x.get('timestamp')
            if not isinstance(t,(int,float)) or not math.isfinite(t) or t<=0:
                counts['invalid_timestamp']+=1;continue
            # Preserve sequence-prefix availability; never reorder a backdated print.
            if t<last:
                counts['backdated_excluded']+=1;continue
            last=t
            if t>=end:counts['rows_at_or_after_study_end']+=1;continue
            if any(x.get(k) for k in FLAGS):counts['flagged_excluded']+=1;continue
            if any(not isinstance(x.get(k),(int,float)) or not math.isfinite(x[k]) or x[k]<=0
                   for k in ('price','index_price','mark_price','amount')):
                counts['invalid_numeric_excluded']+=1;continue
            if x['direction'] not in ('buy','sell') or abs(x['amount']/FACE-round(x['amount']/FACE))>1e-8:
                counts['invalid_contract_or_direction_excluded']+=1;continue
            tid=str(x['trade_id']);assert tid not in seen,(symbol,tid);seen.add(tid)
            rows.append(Trade(int(t),x['price'],x['index_price'],x['mark_price'],x['amount'],x['direction'],tid))
        assert n==r['rows']
    counts['ordinary_rows']=len(rows)
    counts['compressed_trade_bytes']=sum(s['bytes'] for s in sources)
    return rows,dict(counts),sources


def fee_sensitivity(base,fills,future_bp,proxy_bp):
    """Fees cannot affect quotes or size in this explicitly unfunded unit probe."""
    r=dict(base); complete=r['completed_cycles']; new_fees=new_completed=0.
    for f in fills:
        old=f['fee_usd']; bp=future_bp if f['phase'] in (1,2) else proxy_bp
        # Recover traded notional independently of old fee (which may be zero).
        if f['phase'] in (1,2): notional=FACE/f['price']*f['index']
        elif f['phase']==0:notional=FACE
        else:notional=f['cash_usd']+old
        fee=notional*bp/10000;new_fees+=fee
        if f['cycle']<complete:new_completed+=fee
    old_total=r['total_transaction_fees_usd'];old_completed=r['completed_cycle_fees_usd']
    current_delta=(old_total-old_completed)-(new_fees-new_completed)
    r.update(future_fee_bp=future_bp,proxy_fee_bp=proxy_bp,
             fee_bp_each_leg=future_bp if future_bp==proxy_bp else None,
             total_transaction_fees_usd=new_fees,completed_cycle_fees_usd=new_completed,
             unfinished_cycle_fees_usd=new_fees-new_completed)
    for k in ('net_marked_usd_per_10_face',):r[k]+=old_total-new_fees
    for k in ('completed_net_usd','completed_cycle_realized_net_usd'):r[k]+=old_completed-new_completed
    for k in ('unfinished_net_marked_usd','unfinished_cycle_realized_net_usd'):r[k]+=current_delta
    r['fee_only_same_execution_path']=True
    assert abs(r['net_marked_usd_per_10_face']-r['completed_cycle_realized_net_usd']-r['unfinished_cycle_realized_net_usd']-r['unrealized_mark_net_usd'])<1e-8
    return r


def audit_fills(e,rows,result,maps=None):
    """Recompute realized cash, unit decay, marks, source limits and strict hits."""
    tape,observations=maps if maps is not None else ({r.id:r for r in rows},{r.t:r for r in rows})
    cash=fees=proxy=0.;entry=None;last=e.start;completed=[];cyclecash=0.;ids=set()
    for i,f in enumerate(e.fills):
        assert (f['cycle'],f['phase'])==(i//4,i%4)
        assert f['trade_id'] not in ids;ids.add(f['trade_id'])
        r=tape[f['trade_id']];o=observations[f['observed']];phase=f['phase']
        assert r.t==f['t'] and f['decision']-o.t==e.delay
        assert f['arrival']-f['decision']==e.delay and f['t']>f['arrival']
        assert f['observed']>=last
        proxy*=(1-e.expense)**((r.t-last)/(365*DAY))*math.exp(-e.surcharge*(r.t-last)/(365*DAY))
        if phase in (1,2):
            theoretical=o.index*(1+(e.expiry-f['decision'])/(365*DAY)*(e.proxy_apr+(e.high if phase==1 else e.low)))
            limit=(math.ceil(theoretical/e.tick-1e-12) if phase==1 else math.floor(theoretical/e.tick+1e-12))*e.tick
            assert abs(f['price']-limit)<1e-8
            assert r.price>limit if phase==1 else r.price<limit
            assert r.direction==('buy' if phase==1 else 'sell')
            assert math.floor(r.amount/FACE*e.participation+1e-12)>=1
            distance=max(0.,(limit-o.price)/o.price if phase==1 else (o.price-limit)/o.price)
            assert e.band is None or distance<=e.band
            fee=FACE/limit*r.index*e.future_fee
        else:
            assert f['price']==r.index
            fee=(FACE if phase==0 else proxy*r.index)*e.proxy_fee
        delta=-fee
        if phase==0:proxy=FACE/r.index;delta-=FACE
        elif phase==1:entry=f['price']
        elif phase==2:delta+=FACE*(1/f['price']-1/entry)*r.index;entry=None
        else:delta+=proxy*r.index;proxy=0.
        assert abs(delta-f['cash_usd'])<1e-9 and abs(fee-f['fee_usd'])<1e-9
        cash+=delta;cyclecash+=delta;fees+=fee;last=r.t
        if phase==3:completed.append(cyclecash);cyclecash=0.
    proxy*=(1-e.expense)**((e.end-last)/(365*DAY))*math.exp(-e.surcharge*(e.end-last)/(365*DAY))
    net=cash+proxy*result['final_index']
    if entry is not None:net+=FACE*(1/result['final_mark']-1/entry)*result['final_index']
    assert abs(net-result['net_marked_usd_per_10_face'])<1e-8
    assert abs(sum(completed)-result['completed_cycle_realized_net_usd'])<1e-8
    assert abs(fees-result['total_transaction_fees_usd'])<1e-8
    return len(e.fills)


def study(a,item,out):
    started=time.perf_counter();symbol=item['instrument'];meta=item['metadata'];expiry=meta['expiration_timestamp']
    assert meta['contract_size']==FACE and not meta.get('tick_size_steps')
    # Existing holdings may close after entry eligibility ends; stop before 60d.
    end=min(item['last_trade'][0]['timestamp']+1,expiry-60*DAY)
    rows,counts,sources=load_contract(a,item,end)
    if len(rows)<3:raise ValueError((symbol,'insufficient ordinary tape'))
    start=rows[0].t
    train_end=start+(min(minus_months(expiry,3),end)-start)//3
    d,_,_=distribution(rows,expiry,start,train_end)
    locations=sorted(set(round(d['quantiles'][str(q)]/.0025)*.0025 for q in (.25,.5,.75)))
    candidates=sorted(set([(round(l+gap,8),round(l,8)) for l in locations for gap in (.0025,.005,.01)]+[(.02,.01)]))
    runs=[];audited=0;replay_start=time.perf_counter()
    tape=[r for r in rows if train_end<=r.t<end]
    maps=({r.id:r for r in tape},{r.t:r for r in tape})
    scenarios=[('base',{}),('one_ms_delays',dict(delay=1)),('two_second_delays',dict(delay=2000)),
               ('always_posted',dict(band=None)),('proxy_cost',dict(proxy_expense=.0025,surcharge=.005))]
    with gzip.GzipFile(filename=str(out/(symbol+'-fills.jsonl.gz')),mode='wb',mtime=0) as audit:
        for h,l in candidates:
            for name,kw in scenarios:
                e=Experiment(expiry,train_end,end,h,l,tick=meta['tick_size'],**kw)
                r=e.run(tape);r.update(symbol=symbol,scenario=name,start=stamp(train_end),end=stamp(end))
                audited+=audit_fills(e,tape,r,maps);runs.append(r)
                for f in e.fills:audit.write(encode(dict(high=h,low=l,scenario=name,**f))+b'\n')
                if name=='base':
                    for label,future,proxy in [('no_fees',0,0),('maker_rebate_minus_1bp',-1,0),('maker_rebate_minus_0_2bp',-.2,0)]:
                        f=fee_sensitivity(r,e.fills,future,proxy);f['scenario']=label;runs.append(f)
    result=dict(schema_version=2,status='independent_unit_probes_not_funded_portfolio',symbol=symbol,
        expiry=stamp(expiry),first_observation=stamp(start),train_end=stamp(train_end),end=stamp(end),
        training=d,candidates=[dict(high=h,low=l) for h,l in candidates],counts=counts,sources=sources,runs=runs,
        audit=dict(status='PASS',fills=audited),
        metrics=dict(total_seconds=time.perf_counter()-started,replay_and_audit_seconds=time.perf_counter()-replay_start,
                     peak_process_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                     cpu=platform.processor(),python=platform.python_version()),
        source_sha256=sha(Path(__file__).read_bytes()),engine_sha256=sha((Path(__file__).parent/'btc_prd_execution_calibration.py').read_bytes()),
        limitations=['one $10 inverse short plus synthetic proxy per independent run; no shared capital',
                    'per-contract first third of entry-eligible calendar is training; remainder is held out',
                    'no full band, ladder sizing, native margin, roll, restart, book or forced deadline execution',
                    'open inventory is marked before 60d deadline, not assumed liquidated',
                    'synthetic proxy uses trade-attached index; expense/margin costs are modeling assumptions',
                    'historical metadata tick assumed throughout each contract; no historical tick-change schedule',
                    'negative fees conditional maker sensitivity; tape cannot prove post-only acceptance'])
    (out/(symbol+'.json')).write_bytes(encode(result)+b'\n')
    print(json.dumps(dict(symbol=symbol,status='PASS',rows=len(rows),runs=len(runs),seconds=result['metrics']['total_seconds'])),flush=True)
    return {k:v for k,v in result.items() if k not in ('sources','runs')}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache',type=Path,default=Path('archive-cache'));p.add_argument('--output',type=Path,default=Path('full-history-output'))
    p.add_argument('--offline',action='store_true');p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1)
    p.add_argument('--symbol');args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    a=Archive(args.cache,args.offline);plan=a.json(PLAN)
    assert plan['job_id']=='btc-full-20261009-archive' and plan['chunk_size']==10000
    manifest=a.json(JOB+'/manifest.json')
    assert manifest['status']=='COMPLETE_AVAILABLE_HISTORY'
    selected=[i for i in plan['instruments'] if eligible(i)]
    summaries=[]
    for n,item in enumerate(selected):
        if n%args.shards!=args.shard or (args.symbol and args.symbol!=item['instrument']):continue
        summaries.append(study(a,item,args.output))
    (args.output/'shard-summary.json').write_bytes(encode(dict(shard=args.shard,shards=args.shards,
        eligible_contracts=len(selected),plan_sha256=sha(encode(plan)),archive_io=dict(a.counts),summaries=summaries))+b'\n')

if __name__=='__main__':main()
