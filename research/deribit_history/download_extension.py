"""Fixed, resumable public-market downloads; no trading or application changes."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import argparse,csv,gzip,hashlib,json,os,shutil,sys,time,urllib.parse,urllib.request
from deribit_trade_ingest import download_future

BUCKET='keep-and-lease-market-data'
PREFIX='btc/research/deribit-history-extension-v1'
REQUEST='.cloud-agent/requests/deribit-history-extension.json'
ACTION='download-sep-dec-earlier-and-mar27-current'
JOBS={
 'earlier-sep26':('BTC-25SEP26','2026-03-06','2026-06-06'),
 'earlier-dec26':('BTC-25DEC26','2026-03-06','2026-06-06'),
 'missing-mar27':('BTC-26MAR27','2026-06-06','2026-09-04'),
}
FLAGS=('block_trade_id','block_rfq_id','combo_trade_id','combo_id','block_trade_leg_count')

def digest(b):return hashlib.sha256(b).hexdigest()
def encode(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def stamp(d):return int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()*1000)
def utc(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat(timespec='milliseconds')

def validate_request(path=REQUEST):
    r=json.loads(Path(path).read_text())
    if set(r)!={'schema_version','action','sequence'} or r['schema_version']!=1 or r['action']!=ACTION or type(r['sequence']) is not int or not 1<=r['sequence']<=10000:
        raise ValueError('Only the fixed authorized history-extension request is accepted')
    return r

def api(method,**params):
    allowed={'get_instrument','get_last_trades_by_instrument','get_last_trades_by_instrument_and_time'}
    if method not in allowed:raise ValueError('Unsupported endpoint')
    if params.get('instrument_name') not in {v[0] for v in JOBS.values()}:raise ValueError('Unsupported instrument')
    base='https://www.deribit.com/api/v2/public/' if method=='get_instrument' else 'https://history.deribit.com/api/v2/public/'
    url=base+method+'?'+urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            time.sleep(.35)
            with urllib.request.urlopen(url,timeout=60) as response:raw=response.read()
            obj=json.loads(raw)
            if 'error' in obj:raise ValueError(str(obj['error']))
            return obj['result']
        except Exception:
            if attempt==5:raise
            time.sleep(min(16,2**attempt))

def create_bytes(bucket,key,data):
    from google.api_core.exceptions import PreconditionFailed
    blob=bucket.blob(key)
    try:blob.upload_from_string(data,if_generation_match=0,checksum='crc32c',timeout=120)
    except PreconditionFailed:
        if blob.download_as_bytes(checksum='crc32c')!=data:raise ValueError('Immutable object conflict') from None
    check=blob.download_as_bytes(checksum='crc32c',timeout=120)
    if digest(check)!=digest(data):raise ValueError('Uploaded bytes differ')
    return {'key':key,'sha256':digest(data),'bytes':len(data)}

def save_file(bucket,path):
    b=path.read_bytes()
    return create_bytes(bucket,f'{PREFIX}/objects/{digest(b)}/{path.name}',b)

def existing_day(bucket,key,symbol,day):
    from google.api_core.exceptions import NotFound
    try:r=json.loads(bucket.blob(key).download_as_bytes(checksum='crc32c'))
    except NotFound:return None
    if r.get('status')!='COMPLETE' or r.get('instrument')!=symbol or r.get('date')!=day:raise ValueError('Mismatched daily receipt')
    for obj in r['objects']:
        b=bucket.blob(obj['key']).download_as_bytes(checksum='crc32c',timeout=120)
        if len(b)!=obj['bytes'] or digest(b)!=obj['sha256']:raise ValueError('Stored daily object hash mismatch')
    return r

def audit(path,symbol,lo,hi,meta):
    seen=set();previous=None;rows=eligible=0;times=[];amount=0;ids=[]
    with gzip.open(path,'rt') as f:
        for line in f:
            r=json.loads(line)
            if r['instrument_name']!=symbol or not lo<=r['timestamp']<hi:raise ValueError('Wrong instrument/day')
            if r['trade_id'] in seen:raise ValueError('Duplicate trade ID')
            seen.add(r['trade_id']);seq=r['trade_seq']
            if previous is not None and seq<=previous:raise ValueError('Nonincreasing sequence')
            previous=seq
            if any(not r[k]>0 for k in ('price','amount','index_price')):raise ValueError('Invalid price, amount or index')
            if r['amount']%10 or ('contracts' in r and abs(r['contracts']*10-r['amount'])>1e-8):raise ValueError('Native contract quantity mismatch')
            rows+=1;ids.append(seq)
            if not any(r.get(k) for k in FLAGS):eligible+=1;times.append(r['timestamp']);amount+=r['amount']
    if rows!=meta['rows']:raise ValueError('Raw count differs from ingestion metadata')
    times.sort()
    return {'raw_trades':rows,'ordinary_trades':eligible,'excluded_flagged':rows-eligible,'ordinary_usd_face':amount,
            'first_ordinary_trade_utc':utc(times[0]) if times else None,'last_ordinary_trade_utc':utc(times[-1]) if times else None,
            'longest_silence_seconds':max(b-a for a,b in zip([lo]+times,times+[hi]))/1000,
            'sequence_first':min(ids) if ids else None,'sequence_last':max(ids) if ids else None,
            'timestamp_reversals':meta['discrepancy']['counts'].get('timestamp_reversal',0),
            'max_reversal_ms':meta['discrepancy']['max_reversal_ms']}

def run(job):
    from google.cloud import storage
    request=validate_request();symbol,start,end=JOBS[job];bucket=storage.Client().bucket(BUCKET)
    info=api('get_instrument',instrument_name=symbol)
    if info['creation_timestamp']>stamp(start) or info['expiration_timestamp']<=stamp(end):raise ValueError('Instrument does not cover fixed period')
    work=Path('work/deribit-history')/job;work.mkdir(parents=True,exist_ok=True)
    artifact=Path('history-reports')/job;artifact.mkdir(parents=True,exist_ok=True)
    (artifact/'metadata.json').write_bytes(encode(info))
    metadata_object=save_file(bucket,artifact/'metadata.json')
    total=(date.fromisoformat(end)-date.fromisoformat(start)).days;receipts=[];failures=[]
    summary_file=os.environ.get('GITHUB_STEP_SUMMARY')
    def summary(text):
        if summary_file:
            with open(summary_file,'a') as f:f.write(text+'\n')
    summary(f'## {job}: {symbol}\n\n{start} through {end} exclusive — {total} days.\n')
    print(json.dumps({'stage':'STARTED','job':job,'instrument':symbol,'start':start,'end_exclusive':end,'total_days':total}),flush=True)
    for i in range(total):
        day=(date.fromisoformat(start)+timedelta(days=i)).isoformat();next_day=(date.fromisoformat(day)+timedelta(days=1)).isoformat()
        key=f'{PREFIX}/receipts/{job}/{day}.json';out=work/day;out.mkdir(exist_ok=True)
        try:
            r=existing_day(bucket,key,symbol,day);reused=r is not None
            if r is None:
                meta=download_future(api,symbol,{'expiration_timestamp':utc(info['expiration_timestamp'])},stamp(day),stamp(next_day),out)
                checked=audit(out/meta['path'],symbol,stamp(day),stamp(next_day),meta)
                objects=[save_file(bucket,p) for p in sorted(out.rglob('*')) if p.is_file() and p.suffix not in ('.sqlite','.part')]
                objects.append(metadata_object)
                r={'schema_version':1,'status':'COMPLETE','instrument':symbol,'date':day,'start':day,'end_exclusive':next_day,
                   'stats':checked,'objects':objects,'source_policy':meta['discrepancy'],'source_commit':os.environ.get('GITHUB_SHA'),
                   'expiry_utc':utc(info['expiration_timestamp']),'instrument_created_utc':utc(info['creation_timestamp'])}
                create_bytes(bucket,key,encode(r))
            receipts.append({'date':day,'receipt_key':key,'receipt_sha256':digest(encode(r)),'stats':r['stats']})
            p={'stage':'DAY_COMPLETE','job':job,'date':day,'completed_days':len(receipts),'total_days':total,'reused':reused,'raw_trades':r['stats']['raw_trades'],'ordinary_trades':r['stats']['ordinary_trades']}
            print(json.dumps(p),flush=True);summary(f'- {day}: {r["stats"]["raw_trades"]:,} trades; completed {len(receipts)}/{total}'+(' (reused)' if reused else ''))
            shutil.rmtree(out)
        except Exception as e:
            failures.append({'date':day,'error_type':type(e).__name__,'error':str(e)[:700]})
            print(json.dumps({'stage':'DAY_FAILED','job':job,**failures[-1]}),flush=True)
            summary(f'- {day}: **FAILED** ({type(e).__name__}); remaining days continue.')
        progress={'status':'IN_PROGRESS','job':job,'completed_days':len(receipts),'total_days':total,'failures':failures,'receipts':receipts}
        (artifact/'progress.json').write_bytes(encode(progress))
    result={'schema_version':1,'status':'COMPLETE' if not failures and len(receipts)==total else 'INCOMPLETE','job':job,'instrument':symbol,
            'start':start,'end_exclusive':end,'total_days':total,'completed_days':len(receipts),'failures':failures,'receipts':receipts,
            'total_raw_trades':sum(r['stats']['raw_trades'] for r in receipts),'total_ordinary_trades':sum(r['stats']['ordinary_trades'] for r in receipts),
            'raw_data_location':f'gs://{BUCKET}/{PREFIX}/','request':request,
            'limitations':['Trade history is not order-book depth.','Native index_price is retained per trade; no independent continuous spot/index tape.','Raw sequence and timestamps are preserved, including any anomalies.','Coverage uses the documented bounded sequence-envelope assumption.','This is raw research ingestion; no strategy run or GUI catalog deployment.']}
    (artifact/'summary.json').write_bytes(encode(result))
    if receipts:
        with (artifact/'daily_coverage.csv').open('w',newline='') as f:
            keys=['date']+list(receipts[0]['stats']);w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
            for r in receipts:w.writerow({'date':r['date'],**r['stats']})
    if result['status']=='COMPLETE':
        record=create_bytes(bucket,f'{PREFIX}/ranges/{job}/{digest(encode(result))}/manifest.json',encode(result))
        result['manifest_uri']=f'gs://{BUCKET}/'+record['key'];(artifact/'summary.json').write_bytes(encode(result))
        print(json.dumps({'stage':'READY','job':job,'completed_days':total,'manifest_uri':result['manifest_uri']}),flush=True)
        summary(f'\n**READY: {total}/{total} days validated and saved.**')
    else:
        summary(f'\n**INCOMPLETE: {len(receipts)}/{total} days. Rerun failed jobs to resume.**')
        raise RuntimeError(f'{len(failures)} incomplete daily downloads')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--validate-request',action='store_true');p.add_argument('--job',choices=JOBS);a=p.parse_args()
    if a.validate_request:validate_request();print('Fixed history request validated')
    elif a.job:run(a.job)
    else:p.error('Select --job or --validate-request')
