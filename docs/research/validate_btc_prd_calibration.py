"""Independent raw-tape/price/latency/cash audit of saved calibration fills."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
from btc_prd_execution_calibration import load, FACE, TICK, YEAR, ms


def validate(old,new,output):
    groups,receipts=load(old,new)
    report=json.loads((output/'btc-prd-execution-calibration.json').read_text())
    assert receipts==report['source_hashes']
    tape={}
    observations={}
    expiries={}
    for g in groups:
        expiries[g['symbol']]=g['expiry']
        for r in g['rows']:
            tape[g['symbol'],r.id]=r
            observations[g['symbol'],r.t]=r  # deterministic last in timestamp batch
    audits=defaultdict(list)
    data=(output/'btc-prd-calibration-fills.jsonl.gz').read_bytes()
    for line in gzip.decompress(data).splitlines():
        f=json.loads(line)
        audits[f['symbol'],f['sample'],f['high'],f['low'],f['scenario']].append(f)
    count=0
    for run in report['runs']:
        key=(run['symbol'],run['phase'],run['high'],run['low'],run['scenario'])
        fills=audits.pop(key,[])
        cash,proxy,entry,fees=0.,0.,None,0.
        last=ms(run['start'])
        ids=set()
        e,c=run['proxy_expense'],run['proxy_liquidity_surcharge']
        a=e/(1-e)+c
        for i,f in enumerate(fills):
            assert f['phase']==i%4 and f['cycle']==i//4
            assert f['trade_id'] not in ids, 'one print used twice in one experiment'
            ids.add(f['trade_id'])
            assert f['decision']-f['observed']==run['delay_ms_each']
            assert f['arrival']-f['decision']==run['delay_ms_each']
            assert f['t']>f['arrival'] and f['observed']>=last
            r=tape[f['symbol'],f['trade_id']]
            observed=observations[f['symbol'],f['observed']]
            assert r.t==f['t'] and r.index==f['index']
            proxy*=(1-e)**((r.t-last)/YEAR)*math.exp(-c*(r.t-last)/YEAR)
            phase=f['phase']
            if phase in (1,2):
                rate=a+(run['high'] if phase==1 else run['low'])
                theoretical=observed.index*(1+(expiries[f['symbol']]-f['decision'])/YEAR*rate)
                expected=(math.ceil(theoretical/TICK-1e-12) if phase==1 else
                          math.floor(theoretical/TICK+1e-12))*TICK
                assert expected==f['price']
                assert (r.price>f['price'] if phase==1 else r.price<f['price'])
                assert r.direction==('buy' if phase==1 else 'sell')
                assert math.floor(r.amount/FACE*run['participation']+1e-12)>=1
                distance=max(0.,(expected-observed.price)/observed.price if phase==1 else
                             (observed.price-expected)/observed.price)
                assert run['posting_band'] is None or distance<=run['posting_band']
                fee=FACE/f['price']*r.index*run.get('future_fee_bp',run['fee_bp_each_leg'])/10000
            else:
                assert f['price']==r.index
                fee=(FACE if phase==0 else proxy*r.index)*run.get('proxy_fee_bp',run['fee_bp_each_leg'])/10000
            delta=-fee
            if phase==0:
                assert proxy==0 and entry is None
                proxy=FACE/r.index
                delta-=FACE
            elif phase==1:
                assert entry is None and proxy>0
                entry=f['price']
            elif phase==2:
                assert entry is not None
                delta+=FACE*(1/f['price']-1/entry)*r.index
                entry=None
            else:
                assert entry is None
                delta+=proxy*r.index
                proxy=0.
            assert abs(delta-f['cash_usd'])<1e-10
            assert abs(fee-f['fee_usd'])<1e-10
            cash+=delta
            fees+=fee
            last=r.t
            count+=1
        end=ms(run['end'])
        proxy*=(1-e)**((end-last)/YEAR)*math.exp(-c*(end-last)/YEAR)
        net=cash+proxy*run['final_index']
        if entry is not None:
            net+=FACE*(1/run['final_mark']-1/entry)*run['final_index']
        assert abs(net-run['net_marked_usd_per_10_face'])<1e-8
        assert abs(fees-run['total_transaction_fees_usd'])<1e-8
        assert abs(proxy-run['remaining_proxy_btc'])<1e-12
        assert (FACE if entry is not None else 0)==run['remaining_short_face']
        assert len(fills)//4==run['completed_cycles']
    assert not audits
    result=dict(status='PASS',runs=len(report['runs']),fills=count,raw_files=len(receipts),
                raw_rows=sum(g['counts']['raw'] for g in groups),
                ordinary_rows=sum(len(g['rows']) for g in groups),
                checks=['source compressed-file hashes','unique per-run tape use',
                        'two latency legs and no same-time fills','actual aggressive direction',
                        'strict-through limit fills','per-print participation budget',
                        'source-observation limit and posting distance','four-phase causal lifecycle',
                        'native inverse short P&L','proxy decay and transaction fees',
                        'unfinished position mark and complete cash reconciliation'],
                fills_gzip_sha256=hashlib.sha256(data).hexdigest(),
                report_sha256=hashlib.sha256((output/'btc-prd-execution-calibration.json').read_bytes()).hexdigest(),
                limitations='Unit experiments only; no portfolio capacity, margin, live queue, roll or restart certification.')
    (output/'btc-prd-calibration-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sep-dec',type=Path,required=True)
    p.add_argument('--dec-mar',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    validate(a.sep_dec,a.dec_mar,a.output)
