"""Read only the authorized immutable Dec26/Mar27 data; run bounded research."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import date,timedelta
import base64,gzip,hashlib,io,json,os,zipfile
from replay import Replay,load_rows,save_run,ms,digest,eligible

BUCKET='keep-and-lease-market-data'
ROOT='btc/research/deribit-history-extension-v1'
RANGE='52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912'
MAR='8961a8ad2393dae09fa7d8ccb87d172ed2276c527b63c091f701f31eeab5ec12'
REQUEST='.cloud-agent/requests/prd-ladder-research.json'

def validate_request():
    r=json.loads(Path(REQUEST).read_text())
    assert set(r)=={'schema_version','action','sequence'}
    assert r['schema_version']==1 and r['action']=='replay-six-level-prd-0.6-btc'
    assert type(r['sequence']) is int and 1<=r['sequence']<=100

def main():
    validate_request()
    from google.cloud import storage
    bucket=storage.Client().bucket(BUCKET)
    receipts=[]
    def get(key,sha=None):
        b=bucket.blob(key).download_as_bytes(checksum='crc32c',timeout=120)
        if sha:assert digest(b)==sha
        receipts.append(dict(key=key,sha256=digest(b),bytes=len(b)))
        return b
    current=json.loads(get(f'btc/trades/ranges/{RANGE}/manifest.json',RANGE))
    mar=json.loads(get(f'{ROOT}/ranges/missing-mar27/{MAR}/manifest.json',MAR))
    assert mar['status']=='COMPLETE' and mar['completed_days']==90 and len(current['daily_datasets'])==90
    symbols=['BTC-25DEC26','BTC-26MAR27'];start=ms('2026-06-06');end=ms('2026-09-04')
    expiry=[ms('2026-12-25T08:00:00Z'),ms('2027-03-26T08:00:00Z')]
    seeds={symbols[0]:current['source_manifest']['futures'][symbols[0]]['seed']}
    work=Path('work/prd-ladder');work.mkdir(parents=True,exist_ok=True)
    def dec_day(day):
        m=json.loads(get(f'btc/trades/v1/{day["manifest_sha256"]}/manifest.json',day['manifest_sha256']))
        f=m['source_manifest']['futures'][symbols[0]]
        b=get(f'btc/raw/sha256/{f["sha256"]}/{symbols[0]}.jsonl.gz',f['sha256'])
        p=work/f'{day["start"][:10]}-{symbols[0]}.jsonl.gz';p.write_bytes(b)
        return p
    def mar_day(day):
        b=get(day['receipt_key'],day['receipt_sha256']);r=json.loads(b)
        assert r['status']=='COMPLETE' and r['instrument']==symbols[1]
        obj=next(x for x in r['objects'] if x['key'].endswith('/'+symbols[1]+'.jsonl.gz'))
        b=get(obj['key'],obj['sha256']);p=work/f'{day["date"]}-{symbols[1]}.jsonl.gz';p.write_bytes(b)
        if day['date']=='2026-06-06':
            obj=next(x for x in r['objects'] if x['key'].endswith('/'+symbols[1]+'.meta.json'))
            meta=json.loads(get(obj['key'],obj['sha256']));seeds[symbols[1]]=meta['seed']
        return p
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths=list(pool.map(dec_day,current['daily_datasets']))+list(pool.map(mar_day,mar['receipts']))
    print(json.dumps({'stage':'INPUTS_VERIFIED','files':len(paths),'ordinary_expected_mar':mar['total_ordinary_trades']}),flush=True)
    assert all(eligible(r) and r['timestamp']<start for r in seeds.values())
    events,coverage=load_rows(paths,symbols,start,end)
    assert sum(r['instrument_name']==symbols[1] for r in events)==155950
    out=Path('ladder-reports/dec_mar');out.mkdir(parents=True,exist_ok=True)
    (out/'source_receipts.json').write_text(json.dumps(receipts,indent=2)+'\n')
    (out/'seeds.json').write_text(json.dumps(seeds,indent=2)+'\n')
    for name,delay,participation,agg in [('base',500,1.,False),('opposite_aggressor',500,1.,True),('ten_percent_volume',500,.1,False),('one_second',1000,1.,False)]:
        replay=Replay(symbols,expiry,seeds,start,end,delay,participation,agg,name)
        result=replay.run(events);save_run(out/name,replay,result,coverage)
        print('RESULT '+json.dumps(result),flush=True)
    # Only research outputs are bundled, never auth files, environment or raw tokens.
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(out.parent)))
    blob=buf.getvalue();Path('ladder-reports/Dec26_Mar27_results.zip').write_bytes(blob)
    key=f'btc/research/prd-ladder-v1/results/{digest(blob)}/Dec26_Mar27_results.zip'
    bucket.blob(key).upload_from_string(blob,if_generation_match=0,checksum='crc32c')
    print('RESULT_BUNDLE_META '+json.dumps(dict(sha256=digest(blob),bytes=len(blob),key=key)),flush=True)
    # Connector-accessible copy, chunked to avoid long-line truncation.
    encoded=base64.b64encode(blob).decode()
    for i in range(0,len(encoded),6000):print(f'RESULT_BUNDLE_CHUNK {i//6000:05d} '+encoded[i:i+6000],flush=True)
    print('READY prd-ladder-six-level-0.6-btc',flush=True)

if __name__=='__main__':main()
