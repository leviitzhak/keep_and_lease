"""Independently reconcile saved orders, delayed arrivals, fills and holdings."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from research.post_decision_value.engine import Delays


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes())


def audit(root):
    root=Path(root);report=read(root/'report.json');config=read(root/'configuration.json')
    manifest=read(root/'data-manifest.json');frozen=read(root/'frozen-selection.json')
    assert len(manifest['files'])==180 and manifest['raw_rows']==486203
    split_dates=config['splits']
    assert max(split_dates['calibration'])<min(split_dates['validation'])
    assert max(split_dates['validation'])<min(split_dates['test'])
    assert set(split_dates['calibration']).isdisjoint(split_dates['test'])
    assert report['fallback_hold']==frozen['fallback_hold'] and report['selected']==frozen['selected']
    all_decisions=all_fills=all_events=0;matched={};scores=[]
    for name in report['episodes']:
        folder=root/'episodes'/name;result=read(folder/'result.json')
        assert result['identity']==report['identity']
        for filename,digest in result['artifacts'].items():
            assert hashlib.sha256((folder/filename).read_bytes()).hexdigest()==digest,filename
        fills=read(folder/'fills.json.gz');events=[];serial=0;fifo=0;decisions=0
        mult=result['delay_multiplier']
        delays=Delays(**{k:round(v*mult) if k in ('observation','decision','delivery','report') else v for k,v in config['delays'].items()})
        with gzip.open(folder/'decisions.jsonl.gz','rt') as stream:
            for line in stream:
                d=json.loads(line);decisions+=1;action=d['chosen'];t=d['time']
                assert result['start']<=t<result['end']
                assert (t-result['start'])%config['cadence_ms']==0
                if action['kind']=='wait':continue
                request=f'request-{serial}';serial+=1
                arrival=max(fifo,t+delays.draw(result['seed'],'decision',request,t)+delays.draw(result['seed'],'delivery',request,t));fifo=arrival
                events.append((arrival,0,serial,action))
        for i,f in enumerate(fills):events.append((f['time'],1,i,f))
        live={};btc=config['initial']['BTC'];usd=config['initial']['USD'];fees=0.;groups=defaultdict(float);peak_async=0.
        for t,kind,_,item in sorted(events):
            if kind==0:
                before=set(live)
                for target in item['targets']:live.pop(target,None)
                for order in item['orders']:
                    if item['kind']!='amend' or order['identifier'] in before:
                        live[order['identifier']]=order.copy()
            else:
                order=live[item['order']]
                assert order['symbol']==item['symbol'] and order['limit']==item['price']
                assert order['quantity']*item['quantity']>0
                assert t-order['created']==item['wait_ms']
                remainder=order['quantity']-item['quantity']
                assert abs(abs(remainder)-item['remaining'])<1e-9
                if abs(remainder)>1e-9:order['quantity']=remainder
                else:del live[item['order']]
                rate=manifest['instruments'][item['symbol']]['fee_bps']/10000
                fee=abs(item['quantity']*item['price'])*rate
                btc+=item['quantity'];usd-=item['quantity']*item['price']+fee;fees+=fee
                if item['group']:groups[item['group']]+=item['quantity']
                peak_async=max(peak_async,sum(abs(v) for v in groups.values()))
        outcome=result['outcome']
        assert outcome['done'] and not outcome['truncated']
        assert abs(btc-outcome['holdings']['BTC'])<1e-9
        assert abs(usd-outcome['holdings']['USD'])<1e-6
        assert abs(fees-outcome['fees']['USD'])<1e-8
        assert abs(peak_async-outcome['peak_async_btc'])<1e-9
        score=min(outcome['growth'].values())-int(outcome['failed'])
        assert abs(score-outcome['utility'])<1e-10
        assert bool(outcome['failures'])==outcome['failed']
        assert decisions==result['decisions']
        if result['hold']:assert not fills and outcome['holdings']==config['initial']
        if result['split']=='test':
            signature=(result['start'],result['end'],json.dumps(result['goal'],sort_keys=True))
            key=result['seed']
            if key in matched:assert matched[key]==signature
            else:matched[key]=signature
        all_decisions+=decisions;all_fills+=len(fills);all_events+=result['events']
        scores.append(dict(name=name,utility=score))
    assert all_decisions==report['resources']['decisions']<=20000
    assert all_events==report['resources']['events']
    assert report['resources']['seconds']<3600
    return dict(status='PASS',episodes=len(report['episodes']),decisions=all_decisions,
                fills=all_fills,events=all_events,matched_test_seeds=len(matched),
                checks=['artifact hashes','chronological splits','delayed message FIFO','cancel/amend/fill ordering',
                        'remaining order quantities','linear BTC/USD accounting from signed cashflows',
                        'fees','asynchronous exposure','per-trajectory objective and failure flags','matched baselines'],
                source_fill_audit='Each daily replay additionally checked raw source hash/side/price/lot/shared volume.',
                scope='No claim of observed settlement, depth, or native linear source data.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);args=p.parse_args()
    result=audit(args.run);Path(args.run,'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
