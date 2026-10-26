"""Bounded public settlement/rate acquisition; no credentials or spot-fill claims.

Raw responses, URLs, retrieval times and hashes are immutable per output cache.
Failures and unavailable dates remain explicit. Public settlement P&L aggregates
are never used as the simulated account's P&L. Treasury quotes are rate proxies.
"""
import argparse
from datetime import datetime, timezone, date, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE='https://www.deribit.com/api/v2/public/'
CUTOFF=1791590400000  # 2026-10-10 00:00 UTC, frozen archive boundary.
PLAN_SHA='6ae07e823797a84ac9b24a0387bb1658cc929cb8cc701816122f6a0a67b8f0e3'


def encode(x):return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def write(path,x):path.write_bytes(encode(x))
def sha(raw):return hashlib.sha256(raw).hexdigest()
def stamp():return datetime.now(timezone.utc).isoformat()


class PublicCache:
    def __init__(self,root,seconds=240,max_requests=80,max_bytes=24_000_000):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.start=time.monotonic();self.seconds=seconds;self.max_requests=max_requests;self.max_bytes=max_bytes
        self.requests=0;self.bytes=0;self.records=[]

    def get(self,url):
        key=sha(url.encode());receipt=self.root/(key+'.json');body=self.root/(key+'.gz')
        if receipt.exists():
            info=json.loads(receipt.read_bytes());raw=gzip.decompress(body.read_bytes())
            if info['url']!=url or info['sha256']!=sha(raw) or info['bytes']!=len(raw):raise ValueError('Corrupt immutable source cache')
            self.records.append(info);return raw
        if time.monotonic()-self.start>=self.seconds or self.requests>=self.max_requests or self.bytes>=self.max_bytes:
            raise RuntimeError('Bounded public acquisition budget exhausted')
        self.requests+=1
        req=urllib.request.Request(url,headers={'User-Agent':'keep-and-lease-research/1.0'})
        remaining=self.max_bytes-self.bytes
        with urllib.request.urlopen(req,timeout=min(15,max(1,self.seconds-(time.monotonic()-self.start)))) as r:
            raw=r.read(min(2_000_000,remaining)+1)
        self.bytes+=len(raw)
        if len(raw)>min(2_000_000,remaining):raise ValueError('Public response exceeds byte bound')
        info=dict(url=url,retrieved_at=stamp(),bytes=len(raw),sha256=sha(raw),body=body.name)
        body.write_bytes(gzip.compress(raw,mtime=0));write(receipt,info);self.records.append(info)
        return raw

    def rpc(self,method,**params):
        x=json.loads(self.get(BASE+method+'?'+urllib.parse.urlencode(params)))
        if 'error' in x:raise ValueError('Public API error: '+json.dumps(x['error']))
        return x['result']


def delivery_rows(pages):
    rows={}
    for page in pages:
        for r in page['data']:
            d=date.fromisoformat(r['date']);price=r['delivery_price']
            if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:raise ValueError('Invalid delivery price')
            if d.isoformat() in rows and rows[d.isoformat()]!=price:raise ValueError('Conflicting delivery prices')
            rows[d.isoformat()]=price
    return [dict(date=d,delivery_price=p) for d,p in sorted(rows.items())]


def treasury_rows(raw):
    root=ET.fromstring(raw);rows=[]
    for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
        properties=entry.find('.//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties')
        if properties is None:raise ValueError('Treasury properties missing')
        values={x.tag.split('}')[-1]:x.text for x in properties}
        raw_date=values.get('NEW_DATE') or values.get('INDEX_DATE') or values.get('QUOTE_DATE')
        if not raw_date:raise ValueError('Treasury observation date missing')
        d=date.fromisoformat(raw_date[:10]);rates={}
        for k,v in values.items():
            if not (k.startswith('ROUND_B1_') or k.startswith('CS_')) or not v:continue
            n=float(v)
            if not math.isfinite(n):raise ValueError('Invalid Treasury rate')
            rates[k]=n
        # Daily quotes have no archived dissemination timestamp here. The next
        # UTC day is an explicit conservative research availability convention.
        rows.append(dict(date=d.isoformat(),available_not_before=(d+timedelta(days=1)).isoformat(),rates_percent=rates,
                         security_metadata={k:v for k,v in values.items() if k.startswith(('CUSIP_','MATURITY_DATE_')) and v}))
    if not rows:raise ValueError('Empty Treasury feed')
    return rows


def settlement_rows(pages):
    rows={}
    for page in pages:
        for r in page['settlements']:
            if r['type']!='settlement' or r['timestamp']>CUTOFF:raise ValueError('Unexpected settlement scope')
            # Preserve dated futures only. Perpetual funding is a different model.
            if r['instrument_name']=='BTC-PERPETUAL':continue
            p=r.get('mark_price');index=r.get('index_price')
            if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (p,index)):raise ValueError('Invalid settlement mark/index')
            row={k:r[k] for k in ('instrument_name','timestamp','mark_price','index_price')}
            key=(row['instrument_name'],row['timestamp'])
            if key in rows and rows[key]!=row:raise ValueError('Conflicting settlement event')
            rows[key]=row
    return sorted(rows.values(),key=lambda r:(r['timestamp'],r['instrument_name']))


def collect(output,plan_path):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    raw=Path(plan_path).read_bytes()
    if sha(raw)!=PLAN_SHA:raise ValueError('Frozen futures plan hash mismatch')
    (out/'plan-reconciled-v2.json.gz').write_bytes(gzip.compress(raw,mtime=0))
    plan=json.loads(raw);cache=PublicCache(out/'raw');errors=[];delivery=[];settlement=[];rates=[]
    complete_delivery=False;complete_settlements=False
    offset=0;advertised_total=None
    for _ in range(80):
        try:
            page=cache.rpc('get_delivery_prices',index_name='btc_usd',count=1000,offset=offset)
            if advertised_total is not None and page['records_total']!=advertised_total:raise ValueError('Delivery source changed during pagination')
            advertised_total=page['records_total']
            delivery.append(page)
            offset+=len(page['data'])  # Servers may cap below the requested count.
            if offset>=advertised_total:
                if len(delivery_rows(delivery))!=advertised_total:raise ValueError('Delivery pagination overlap or missing rows')
                complete_delivery=True;break
            if not page['data']:raise ValueError('Empty delivery page before advertised end')
        except Exception as e:errors.append(dict(component='delivery',error=str(e)));break
    prices=delivery_rows(delivery);write(out/'delivery-prices.json',prices)
    print(json.dumps(dict(component='delivery',rows=len(prices),api_complete=complete_delivery)),flush=True)
    for year in range(2016,2027):
        try:
            url='https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?'+urllib.parse.urlencode(dict(data='daily_treasury_bill_rates',field_tdr_date_value=year))
            rows=treasury_rows(cache.get(url))
            if any(int(r['date'][:4])!=year for r in rows):raise ValueError('Treasury year mismatch')
            rates.extend(rows)
        except Exception as e:errors.append(dict(component='treasury',year=year,error=str(e)))
    write(out/'treasury-bill-rates.json',rates)
    print(json.dumps(dict(component='treasury',rows=len(rates))),flush=True)
    continuation=None;seen=set();oldest=None
    for page_number in range(56):
        try:
            params=dict(currency='BTC',type='settlement',count=1000,search_start_timestamp=CUTOFF)
            if continuation:params['continuation']=continuation
            page=cache.rpc('get_last_settlements_by_currency',**params)
            current=min((r['timestamp'] for r in page['settlements']),default=None)
            if oldest is not None and current is not None and current>=oldest:raise ValueError('Settlement pagination did not move backward')
            oldest=current;settlement.append(page)
            continuation=page.get('continuation')
            if continuation in (None,'','none','null'):complete_settlements=True;break
            if continuation in seen or not page['settlements']:raise ValueError('Settlement pagination made no progress')
            seen.add(continuation)
            if (page_number+1)%5==0:print(json.dumps(dict(component='settlement',pages=page_number+1)),flush=True)
        except Exception as e:errors.append(dict(component='settlement',page=page_number,error=str(e)));break
    marks=settlement_rows(settlement);write(out/'daily-settlements.json',marks)
    price_map={r['date']:r['delivery_price'] for r in prices}
    coverage=[]
    for item in plan['instruments']:
        expiry=item['metadata']['expiration_timestamp'];day=datetime.fromtimestamp(expiry/1000,timezone.utc).date().isoformat()
        symbol=item['instrument'];events=[r for r in marks if r['instrument_name']==symbol]
        created=item['metadata']['creation_timestamp'];first_day=(created//86400000)*86400000+8*3600000
        if first_day<=created:first_day+=86400000
        expected=set(range(first_day,min(expiry,CUTOFF),86400000))
        observed={r['timestamp']//86400000*86400000+8*3600000 for r in events}
        missing=sorted(expected-observed)
        coverage.append(dict(instrument=symbol,expiry_ms=expiry,delivery_price=price_map.get(day) if expiry<=CUTOFF else None,
                             expired_in_snapshot=expiry<=CUTOFF,daily_events=len(events),
                             expected_daily_events=len(expected),missing_daily_events=len(missing),first_missing_daily_ms=missing[:10],
                             first_daily_ms=events[0]['timestamp'] if events else None,last_daily_ms=events[-1]['timestamp'] if events else None))
    write(out/'coverage.json',coverage)
    report=dict(status='PUBLIC_INPUTS_DOWNLOADED' if not errors and complete_delivery and complete_settlements else 'PARTIAL_PUBLIC_INPUTS',
                created_at=stamp(),cutoff_ms=CUTOFF,plan_sha256=PLAN_SHA,delivery_api_complete=complete_delivery,
                daily_api_complete=complete_settlements,delivery_rows=len(prices),
                delivery_date_range=[prices[0]['date'],prices[-1]['date']] if prices else [],
                expired_contracts=sum(r['expired_in_snapshot'] for r in coverage),
                expired_contracts_with_delivery=sum(r['expired_in_snapshot'] and r['delivery_price'] is not None for r in coverage),
                daily_rows=len(marks),daily_instruments=len({r['instrument_name'] for r in marks}),treasury_rows=len(rates),
                requests=cache.requests,bytes=cache.bytes,seconds=time.monotonic()-cache.start,errors=errors,
                source_objects=len(cache.records),source_bytes=sum(r['bytes'] for r in cache.records),
                expired_contracts_with_complete_daily_schedule=sum(r['expired_in_snapshot'] and r['missing_daily_events']==0 for r in coverage),
                sources=cache.records,limits=dict(seconds=240,requests=80,bytes=24_000_000),
                interpretation=['Observed delivery indices and daily mark events, not spot execution prices.',
                                'Public platform-wide P&L is never assigned to the strategy.',
                                'Treasury indicative bid rates are not executable purchases or CUSIP cash flows.',
                                'Next-UTC-day availability of rate observations is a modeling convention, not verified publication time.',
                                'Account margin/credit/collateral terms and executable spot/FX bridges remain separate requirements.',
                                'API exhaustion does not establish complete coverage since contract listing; inspect coverage.json.'])
    write(out/'report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('sources','interpretation')}),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--plan',required=True)
    a=p.parse_args();collect(a.output,a.plan)
