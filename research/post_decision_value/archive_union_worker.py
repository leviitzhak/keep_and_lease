"""Bounded logical union of existing frozen GCS data; no exchange downloads.

Only the ~90-day overlap is read again. All other native chunks remain referenced
through the already completed frozen archive and are hash-checked on later reads.
"""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time

BUCKET='keep-and-lease-market-data'
PREFIX='btc/research/deribit-full-history-v1/jobs/btc-full-20261009-archive'
OUTPUT='btc/research/unified-futures-v1'
REQUEST='.cloud-agent/requests/btc-unified-data.json'
INPUTS='docs/research/post_decision_value/union-inputs-v2.json'
FLAGS=('block_trade_id','block_rfq_id','combo_trade_id','combo_id','block_trade_leg_count')


def encode(x):return (json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(b):return hashlib.sha256(b).hexdigest()


def identity(r):
    value={k:r.get(k) for k in ('instrument_name','timestamp','trade_seq','direction','price','amount','index_price')}
    value['trade_id']=str(r['trade_id'])
    for k in ('price','amount','index_price'):
        if isinstance(value[k],(int,float)):value[k]=float(value[k])
    value.update({k:r.get(k) or None for k in FLAGS})
    return digest(encode(value))


def rows(data,symbol,lo,hi):
    seen=set();n=0
    for line in gzip.decompress(data).splitlines():
        r=json.loads(line)
        if r['instrument_name']!=symbol or r['trade_seq']!=lo+n or str(r['trade_id']) in seen:
            raise ValueError('Native identity/sequence mismatch')
        seen.add(str(r['trade_id']));n+=1
        yield r
    if n!=hi-lo+1:raise ValueError('Native chunk count mismatch')


def merge(inputs,get,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    database=output/'overlap.sqlite'
    if database.exists():raise ValueError('Existing partial overlap cache')
    expected={}
    metadata={}
    for item in inputs['metadata']:
        relative=item['key'].split(PREFIX+'/')[1]
        metadata[relative]=json.loads(get(item['key'],item['sha256'],item['bytes']))
    plan=metadata['plan-reconciled-v2.json'];archive=metadata['manifest.json']
    if archive['status']!='COMPLETE_AVAILABLE_HISTORY' or plan['job_id']!=inputs['archive_job']:
        raise ValueError('Archive not complete')
    count=0
    for item in plan['instruments']:
        lo,hi=item['first_available_seq'],item['last_available_seq']
        if lo is None:continue
        count+=hi-lo+1
        for first in range(lo,hi+1,plan['chunk_size']):
            last=min(first+plan['chunk_size']-1,hi)
            key=f'{PREFIX}/receipts/{item["instrument"]}/{first:012d}-{last:012d}.json'
            expected[key]=(item['instrument'],first,last)
    actual=[]
    for name,r in metadata.items():
        if name.startswith('completed/'):
            if r['status']!='COMPLETE' or r['failures'] or r['pending']:raise ValueError('Incomplete shard')
            actual.extend(r['receipt_keys'])
    if len(actual)!=len(set(actual)) or set(actual)!=set(expected):raise ValueError('Frozen archive coverage mismatch')
    db=sqlite3.connect(database)
    db.executescript('PRAGMA cache_size=-32768; CREATE TABLE daily(symbol TEXT,id TEXT,seq INTEGER,identity TEXT,matched INTEGER DEFAULT 0,PRIMARY KEY(symbol,id),UNIQUE(symbol,seq));')
    overlap=[];daily_count=0;overlap_rows=0
    try:
        # Retrieve at most eight small existing objects concurrently; no new data.
        for base in range(0,len(inputs['daily_objects']),8):
            batch=inputs['daily_objects'][base:base+8]
            with ThreadPoolExecutor(max_workers=8) as pool:
                data=list(pool.map(lambda s:get(s['key'],s['sha256'],s['bytes']),batch))
            for source,raw in zip(batch,data):
                n=0
                for r in rows(raw,source['symbol'],source['first_seq'],source['last_seq']):
                    db.execute('INSERT INTO daily(symbol,id,seq,identity) VALUES (?,?,?,?)',
                               (source['symbol'],str(r['trade_id']),r['trade_seq'],identity(r)))
                    n+=1
                if n!=source['rows']:raise ValueError('Daily count mismatch')
                daily_count+=n
        if daily_count!=inputs['expected_daily_rows']:raise ValueError('Total daily count mismatch')
        bounds={s:(lo,hi) for s,lo,hi in db.execute('SELECT symbol,MIN(seq),MAX(seq) FROM daily GROUP BY symbol')}
        selected=[key for key,(s,lo,hi) in expected.items() if s in bounds and hi>=bounds[s][0] and lo<=bounds[s][1]]
        if len(selected)>100:raise ValueError('Overlap receipt cap')
        for base in range(0,len(selected),8):
            keys=selected[base:base+8]
            with ThreadPoolExecutor(max_workers=8) as pool: receipt_bytes=list(pool.map(lambda k:get(k,None,None),keys))
            receipts=[json.loads(raw) for raw in receipt_bytes]
            objects=[]
            for key,r,receipt_raw in zip(keys,receipts,receipt_bytes):
                s,lo,hi=expected[key]
                if (r['status'],r['instrument'],r['first_seq'],r['last_seq'],r['rows'])!=('COMPLETE',s,lo,hi,hi-lo+1):raise ValueError('Overlap receipt mismatch')
                obj=[o for o in r['objects'] if o['key'].endswith('/trades.jsonl.gz')]
                if len(obj)!=1:raise ValueError('Ambiguous trade object')
                objects.append(obj[0])
                overlap.append(dict(receipt_key=key,receipt_sha256=digest(receipt_raw),instrument=s,first_seq=lo,last_seq=hi,trade_object=obj[0]))
            with ThreadPoolExecutor(max_workers=8) as pool: data=list(pool.map(lambda o:get(o['key'],o['sha256'],o['bytes']),objects))
            for key,raw in zip(keys,data):
                s,lo,hi=expected[key]
                for r in rows(raw,s,lo,hi):
                    overlap_rows+=1
                    if overlap_rows+daily_count>1200000:raise ValueError('Overlap row cap')
                    old=db.execute('SELECT seq,identity FROM daily WHERE symbol=? AND id=?',(s,str(r['trade_id']))).fetchone()
                    if old:
                        if old!=(r['trade_seq'],identity(r)):raise ValueError('Conflicting native overlap '+s+' '+str(r['trade_id']))
                        db.execute('UPDATE daily SET matched=1 WHERE symbol=? AND id=?',(s,str(r['trade_id'])))
        matched=db.execute('SELECT COUNT(*) FROM daily WHERE matched=1').fetchone()[0]
        if matched!=daily_count:raise ValueError(f'Daily records absent from canonical archive: {daily_count-matched}')
        db.commit()
    finally:
        db.close();database.unlink(missing_ok=True)
    manifest=dict(schema_version=1,status='COMPLETE_LOGICAL_UNION',venue='Deribit',source_payoff='inverse',native_amount_unit='USD notional',
                  archive_job=inputs['archive_job'],canonical_receipt_keys=sorted(expected),native_rows=count,
                  metadata_pins=inputs['metadata'],daily_sources=inputs['daily_objects'],overlap_receipts=overlap,
                  reconciliation=dict(daily_rows=daily_count,matched_identical=matched,overlay_rows=0,overlap_chunk_rows=overlap_rows,overlap_chunks=len(selected)),
                  prefix_unavailable=archive.get('prefix_unavailable',[]),
                  semantics='Use canonical archive once; daily objects are redundant provenance, never extra execution prints.',
                  verification='All daily records compared against verified overlapping native raw objects. Other raw chunks reuse the frozen archive completion evidence; not freshly rescanned.',
                  ordering='Preserve native sequence and timestamp; causal readers use prefix-max availability and explicit gaps, never concatenate timestamp partitions blindly.',
                  settlement_evidence='not included; trade union only',linear_replay='counterfactual on inverse-source trades')
    (output/'manifest.json').write_bytes(encode(manifest))
    return manifest


class CloudReader:
    def __init__(self,bucket):
        self.bucket=bucket;self.started=time.monotonic();self.bytes=0;self.calls=0;self.pins=[];self.lock=threading.Lock()
    def __call__(self,key,sha,size):
        if not key.startswith(('btc/trades/','btc/raw/','btc/research/deribit-history-extension-v1/','btc/research/deribit-full-history-v1/')) or '..' in key:raise ValueError('Unexpected source key')
        with self.lock:
            self.calls+=1
            if self.calls>450 or time.monotonic()-self.started>360:raise ValueError('Read/time cap')
        blob=self.bucket.get_blob(key,timeout=30)
        if blob is None or blob.size>8000000:raise ValueError('Missing/oversized existing object')
        with self.lock:
            self.bytes+=blob.size
            if self.bytes>64000000:raise ValueError('64 MB compressed read cap')
        data=blob.download_as_bytes(checksum='crc32c',if_generation_match=blob.generation,timeout=30)
        if (size is not None and len(data)!=size) or (sha is not None and digest(data)!=sha):raise ValueError('Source hash/size mismatch')
        with self.lock:self.pins.append(dict(key=key,sha256=digest(data),bytes=len(data),generation=str(blob.generation)))
        return data


def publish(bucket,key,data):
    from google.api_core.exceptions import PreconditionFailed
    blob=bucket.blob(key)
    try:blob.upload_from_string(data,if_generation_match=0,checksum='crc32c',timeout=30)
    except PreconditionFailed:
        if blob.download_as_bytes(timeout=30)!=data:raise ValueError('Immutable output conflict') from None
    if blob.download_as_bytes(checksum='crc32c',timeout=30)!=data:raise ValueError('Output verification failed')
    return dict(uri='gs://'+BUCKET+'/'+key,sha256=digest(data),bytes=len(data))


def main(request_path=REQUEST,output='unified-data-report'):
    request=json.loads(Path(request_path).read_text())
    if request!={'schema_version':1,'action':'reconcile-existing-futures-union','sequence':1}:raise ValueError('Only the fixed existing-data union is authorized')
    from google.cloud import storage
    bucket=storage.Client().bucket(BUCKET);reader=CloudReader(bucket)
    inputs=json.loads(Path(INPUTS).read_text());out=Path(output)
    manifest=merge(inputs,reader,out)
    # Pin the exact receipt bytes/generations retrieved, not reserialized hashes.
    manifest['read_object_pins']=sorted(reader.pins,key=lambda x:x['key'])
    manifest['input_descriptor_sha256']=digest(Path(INPUTS).read_bytes())
    raw=encode(manifest);(out/'manifest.json').write_bytes(raw)
    reference=publish(bucket,f'{OUTPUT}/objects/{digest(raw)}/manifest.json',raw)
    report=dict(status=manifest['status'],manifest=reference,reconciliation=manifest['reconciliation'],
                native_rows=manifest['native_rows'],canonical_chunks=len(manifest['canonical_receipt_keys']),
                source_objects_read=reader.calls,compressed_bytes_read=reader.bytes,seconds=time.monotonic()-reader.started,
                fresh_full_raw_scan=False,exchange_downloads=0,application_deployment=False)
    report_raw=encode(report);publish(bucket,f'{OUTPUT}/results/{digest(report_raw)}/report.json',report_raw)
    (out/'report.json').write_bytes(report_raw)
    print('UNION_RESULT '+json.dumps(report),flush=True)
    summary=__import__('os').environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a') as f:f.write('```json\n'+json.dumps(report,indent=2)+'\n```\n')


if __name__=='__main__':main()
