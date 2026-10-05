#!/usr/bin/env python3
"""Fixed Oct 2025–Sep 2026 monthly lease screen; private cloud output only."""
from __future__ import annotations
import argparse
import base64
import contextlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
from types import SimpleNamespace
import pandas as pd
import databento_gold as gold

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cloud', ROOT / 'scripts/cloud-databento-research.py')
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)
START, END = '2025-10-01', '2026-10-01'
PREFIX = 'research/databento/monthly-2025-10-to-2026-09-v1'
MAX_COST_PER_ASSET = 1.0  # Three independent asset jobs; combined ceiling $3.
SPECS = {
    'gold': dict(root='1OZ', holding='IAU', snapshot_units=14903267.68/792900000, fee=.0025,
                 source='https://www.ishares.com/us/products/239561/ishares-gold-trust', launch='2025-01-13'),
    'sic': dict(root='SIC', holding='SLV', snapshot_units=493361870.50/546300000, fee=.005,
                source='https://www.ishares.com/us/products/239855/ishares-silver-trust-fund', launch='2026-02-09'),
    'mbt': dict(root='MBT', holding='IBIT', snapshot_units=805222.42840/1418840000, fee=.0025,
                source='https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf/latest-holdings.csv', launch='2021-05-03'),
}


def validate_request(r):
    if set(r) != {'schema_version','request_id','action','result_public_key_pem'}:
        raise ValueError('Only fixed-study action and encrypted return fields are accepted')
    # Reuse the recipient-key and request-ID validation; screen references are fixed here.
    cloud.validate_request({**r, 'action': 'estimate'})
    if r['action'] not in ('estimate','screen'):
        raise ValueError('Only estimate or screen is supported')
    return cloud.validate_request({**r, 'action': 'estimate'})


def monthly_choices(asset, volume, raw):
    """First available monthly volume ranking, using the preceding day's volume."""
    spec = SPECS[asset]
    result=[]
    for start in pd.date_range(START,END,freq='MS',inclusive='left',tz='UTC'):
        end=start+pd.offsets.MonthBegin(1)
        row={'month':start.strftime('%Y-%m'),'start':start.isoformat(),'end':end.isoformat()}
        if end <= pd.Timestamp(spec['launch'],tz='UTC'):
            result.append({**row,'status':'before_product_launch'});continue
        candidates=[]
        for rank in range(10):
            for mapping in volume.get('result',{}).get(f"{spec['root']}.v.{rank}",[]):
                day=max(start,pd.Timestamp(mapping['d0'],tz='UTC'))
                until=min(end,pd.Timestamp(mapping['d1'],tz='UTC'))
                if day>=until:continue
                for symbol_map in raw.get('result',{}).get(str(mapping['s']),[]):
                    at=max(day,pd.Timestamp(symbol_map['d0'],tz='UTC'))
                    if at>=min(until,pd.Timestamp(symbol_map['d1'],tz='UTC')):continue
                    symbol=symbol_map['s']
                    try:m=gold.market({'future_symbol':symbol})
                    except ValueError:continue
                    if not symbol.startswith(spec['root']):continue
                    maturity=pd.Timestamp(year=m['year'],month=m['month'],day=1,tz='UTC')
                    # Keep one contract throughout the month. Metals terminate in the
                    # preceding month; MBT terminates in its labeled month.
                    earliest=end if asset=='mbt' else end+pd.offsets.MonthBegin(1)
                    if maturity < earliest:continue
                    candidates.append((at,rank,symbol,str(mapping['s'])))
        if not candidates:
            result.append({**row,'status':'no_eligible_volume_ranked_contract'});continue
        day,rank,symbol,instrument=min(candidates)
        result.append({**row,'status':'selected','selection_date':day.date().isoformat(),
                       'analysis_start':day.isoformat(),'future_symbol':symbol,
                       'previous_day_volume_rank':rank+1,'instrument_id':instrument})
    return result


def discover(client, asset):
    spec=SPECS[asset]
    start=max(START,spec['launch'])
    volume=client.symbology.resolve(dataset='GLBX.MDP3',symbols=[f"{spec['root']}.v.{i}" for i in range(10)],
                                    stype_in='continuous',stype_out='instrument_id',start_date=start,end_date=END)
    ids=sorted({str(m['s']) for rows in volume['result'].values() for m in rows})
    raw=client.symbology.resolve(dataset='GLBX.MDP3',symbols=ids,stype_in='instrument_id',
                                 stype_out='raw_symbol',start_date=start,end_date=END) if ids else {'result':{}}
    return monthly_choices(asset,volume,raw),{'volume':volume,'raw':raw}


def configuration(asset,row):
    c=gold.config_at(gold.PRESETS[asset])
    c.update(start=row['analysis_start'],end=row['end'],future_symbol=row['future_symbol'])
    return c


def requests_for(c):
    rows=gold.requests_for(c,'preview')[:2]
    # A five-day definition window includes business days even at weekend/holiday month starts.
    rows.append({'name':'future-definition','request':dict(dataset='GLBX.MDP3',schema='definition',
        symbols=[c['future_symbol']],stype_in='raw_symbol',start=c['start'],
        end=min(pd.Timestamp(c['start'])+pd.Timedelta(days=5),pd.Timestamp(c['end'])).isoformat())})
    return rows


def references(asset,cash,mode='fee_backcast'):
    spec=SPECS[asset]
    days=pd.DataFrame({'available_at':pd.date_range(START,END,freq='D',inclusive='left',tz='UTC')})
    rows=pd.merge_asof(days,cash.sort_values('available_at'),on='available_at',direction='backward')
    age=(pd.Timestamp('2026-10-02',tz='UTC')-rows.available_at).dt.total_seconds()/(365*86400)
    rows['units_per_share']=spec['snapshot_units']*(age*spec['fee']).map(math.exp) if mode=='fee_backcast' else spec['snapshot_units']
    rows['source']=spec['source']
    if rows.usd_rate.isna().any():raise ValueError('Cash reference does not cover every study day')
    return rows


def import_september(bucket,asset,c,output,state):
    """Reuse paid BBO files when their full request matches this selected contract."""
    if c['start']!='2026-09-01T00:00:00+00:00' or asset not in ('sic','mbt') or state['streams']:return
    old_prefix=f'research/databento/september-2026-v1/cache/{asset}/'
    blobs=list(bucket.list_blobs(prefix=old_prefix+'states/'))
    if not blobs:return
    old=json.loads(max(blobs,key=lambda b:b.name).download_as_bytes())
    for item in requests_for(c)[:2]:
        row=old['streams'].get(item['name'])
        if not row or row['status']!='done':continue
        a,b=dict(row['request']),dict(item['request'])
        for v in (a,b):
            for key in ('start','end'):v[key]=pd.Timestamp(v[key]).isoformat()
        if a!=b:continue
        path=output/'raw'/f"{item['name']}.dbn.zst";path.parent.mkdir(parents=True,exist_ok=True)
        bucket.blob(old_prefix+f"raw/{row['sha256']}.dbn.zst").download_to_filename(path)
        if gold.digest(path)!=row['sha256']:raise ValueError('Imported cache checksum mismatch')
        state['streams'][item['name']]={**row,'request':item['request'],'estimated_usd':0.0,'reused_from':old_prefix}
    gold.save_json(output/'state.json',state)


def run(request,asset,work,report):
    import databento as db
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    from google.cloud import storage
    import requests
    credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    response=AuthorizedSession(credentials).get(f'https://secretmanager.googleapis.com/v1/projects/{cloud.PROJECT}/secrets/databento-api-key/versions/latest:access',timeout=30)
    response.raise_for_status();key=base64.b64decode(response.json()['payload']['data']).decode().strip()
    cloud.SENSITIVE_VALUES.append(key)
    if not key:raise ValueError('Secret is empty')
    report['secret_access']='verified'
    client=db.Historical(key)
    bucket=storage.Client(project=cloud.PROJECT,credentials=credentials).bucket(cloud.BUCKET)
    cloud.PREFIX=PREFIX
    report['stage']='contract_discovery'
    choices,mappings=discover(client,asset)
    report['selection']=choices
    report['selection_rule']='One fixed contract per month: earliest available previous-day volume ranking among ranks 1–10, excluding expiries in the observation month; exact vendor expiry validated before analysis.'
    contexts=[]
    cost_client=SimpleNamespace(metadata=SimpleNamespace(get_cost=lambda **kw:cloud.metadata_cost(client,**kw)))
    for row in choices:
        if row['status']!='selected':continue
        c=configuration(asset,row);output=work/asset/row['month']
        cache=cloud.Cache(bucket,f"{asset}/{row['month']}",output,gold)
        state=cache.restore(c);import_september(bucket,asset,c,output,state)
        report['stage']=f"estimate_{row['month']}"
        plan=gold.estimate(cost_client,requests_for(c),state,'preview')
        contexts.append((row,c,output,cache,state,plan))
    report['estimates']=[{'month':x[0]['month'],**x[5]} for x in contexts]
    total=sum(p['new_estimated_usd']+p['previous_reserved_estimated_usd'] for *_,p in contexts)
    report['cumulative_estimated_usd']=total;report['max_cost_usd']=MAX_COST_PER_ASSET
    if request['action']=='estimate':return
    gold.check_budget({'new_estimated_usd':total,'previous_reserved_estimated_usd':0},MAX_COST_PER_ASSET)
    cash_url='https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO&cosd=2025-09-22&coed=2026-09-30'
    response=requests.get(cash_url,timeout=30);response.raise_for_status()
    cash=pd.read_csv(io.StringIO(response.text));cash['usd_rate']=pd.to_numeric(cash.DGS3MO,errors='coerce')/100
    cash=cash.dropna(subset=['usd_rate']);cash['available_at']=pd.to_datetime(cash.observation_date,utc=True)+pd.Timedelta(days=1)
    cash=cash[['available_at','usd_rate']]
    refs=references(asset,cash)
    provenance={'mode':'fee_adjusted_snapshot_scenario','snapshot_date':'2026-10-02',**SPECS[asset],
        'formula':'q(t)=q(2026-10-02)*exp(sponsor_fee*(2026-10-02-t)/365 days)',
        'warning':'Retrospective fee-only reconstruction, not observed historical holdings. Daily fund fee sales, other costs and tracking effects are not reconstructed.',
        'cash_source':cash_url,'cash_convention':'Latest prior DGS3MO observation, available next UTC day; simple ACT/365 proxy.'}
    report['reference']=provenance;report['months']=[]
    for row,c,output,cache,state,plan in contexts:
        report['stage']=f"screen_{row['month']}"
        original=gold.save_json
        def durable(path,value):
            original(path,value)
            if Path(path)==output/'state.json':cache.checkpoint(path,value)
        gold.save_json=durable
        try:
            frames=gold.acquire_preview(client,plan,output,state)
            samples,summary=gold.analyze(frames,refs,provenance,c)
            flat_samples,flat_summary=gold.analyze(frames,references(asset,cash,'constant'),{**provenance,'mode':'constant_snapshot_scenario'},c)
            summary['constant_snapshot_sensitivity']=flat_summary['overall']
            summary['selection']=row
            summary['maturity_days']={k:float(v*365) for k,v in samples.maturity_years.agg(['min','median','max']).items()}
            summary['cash_rate_pct']={k:float(v*100) for k,v in samples.usd_rate.agg(['min','median','max']).items()}
            summary['break_even_cash_rate_pct']=float(samples.annualized_forward_premium_pct.median())
            gold.save_json(output/'lease-summary.json',summary)
            samples.to_csv(output/'lease-samples.csv.gz',index=False);refs.to_csv(output/'references-used.csv',index=False)
            for name in ('lease-summary.json','lease-samples.csv.gz','references-used.csv'):
                bucket.blob(f"{PREFIX}/runs/{request['request_id']}/{asset}/{row['month']}/{name}").upload_from_filename(output/name,if_generation_match=0)
            report['months'].append(summary)
        except Exception as exc:
            message=str(exc).replace(key,'[REDACTED]')[:1200]
            report['months'].append({'selection':row,'status':'failed','error_type':type(exc).__name__,'error':message,
                                     'acquisition_state':{n:r['status'] for n,r in state['streams'].items()}})
        finally:gold.save_json=original
    report['stage']='finished'
    report['status']='partial' if any(x.get('status')=='failed' for x in report['months']) else 'completed'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request',type=Path,required=True);p.add_argument('--asset',choices=SPECS,required=True)
    p.add_argument('--evidence',type=Path,default=Path('year-evidence'));p.add_argument('--work',type=Path,default=Path('work/year'))
    args=p.parse_args();request=json.loads(args.request.read_text());recipient=validate_request(request)
    report={'request_id':request['request_id'],'action':request['action'],'asset':args.asset,'source_commit':os.getenv('GITHUB_SHA'),'window':[START,END]}
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        try:run(request,args.asset,args.work,report);report.setdefault('status','completed')
        except Exception as exc:
            report.update(status='failed',error_type=type(exc).__name__)
            if type(exc).__name__.startswith('Bento') or isinstance(exc,ValueError):
                message=str(exc)
                for key in cloud.SENSITIVE_VALUES:message=message.replace(key,'[REDACTED]')
                report['error']=message[:1200]
    cloud.encrypt_result(report,recipient,args.evidence/'result.encrypted.json')
    print(f"Monthly {args.asset} {request['request_id']}: {report['status']}; encrypted evidence only.")
    return 0 if report['status']=='completed' else 1

if __name__=='__main__':raise SystemExit(main())
