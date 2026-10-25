"""Independent bounded receipt, fill-volume, label and baseline audit."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from .data import load_archive,validate_splits


def read(path):
    path=Path(path)
    if path.suffix=='.gz':
        with gzip.open(path,'rb') as stream:raw=stream.read(16*1024*1024+1)
    else:raw=path.read_bytes()
    if len(raw)>16*1024*1024:raise ValueError('Audit input size cap')
    return json.loads(raw)


def audit(run, input_root):
    run=Path(run);config=read(run/'configuration.json');report=read(run/'report.json')
    ins,trades,seeds,manifest=load_archive(input_root,config['dates'])
    assert manifest==read(run/'data-manifest.json'),'Source manifest changed'
    validate_splits(read(run/'splits.json'))
    source={t.identifier:t for t in trades}
    episodes=[]
    for name in ('episodes-0.json.gz','episodes-1.json.gz','validation.json.gz','evaluation.json.gz'):
        episodes.extend(read(run/name))
    fills=0;matched={}
    for e in episodes:
        if not e['outcome']['done']:
            assert e['outcome']['truncated'];continue
        o=e['outcome'];usage={}
        if min(o['min_floor_headroom'].values()) < -1e-8 or o['min_funding_usd'] < -1e-8:
            assert o['failed'],'A constraint breach was hidden'
        assert e['goal']['horizon']==e['end']
        for f in e['fills']:
            t=source[f['source_id']];instrument=ins[f['symbol']]
            assert t.executable and t.time==f['time'] and t.price==f['source_price']
            assert (f['quantity']>0 and t.side=='sell' and t.price<f['price']) or (f['quantity']<0 and t.side=='buy' and t.price>f['price'])
            assert abs(instrument.round_quantity(f['quantity'])-f['quantity'])<1e-9
            usage[t.identifier]=usage.get(t.identifier,0.)+abs(f['quantity'])
            assert usage[t.identifier]<=instrument.print_capacity(t.amount,t.price)*config['participation']+1e-9
            fills+=1
        if e['split']=='test':
            key=(e['block'],e['seed'],e['delay_multiplier'])
            signature=(e['start'],e['end'],json.dumps(e['goal'],sort_keys=True))
            if key in matched:assert matched[key]==signature,'Unmatched baseline scenario'
            else:matched[key]=signature
    labels=0
    for stage in range(2):
        training=read(run/f'training-{stage}.json')
        for row in read(run/f'transitions-{stage}.json.gz'):
            assert row['continuation']==training['continuation']
            outcome=row['outcome'];assert outcome['done'] and not outcome['truncated']
            expected=min(outcome['growth'].values())-row['goal']['failure_penalty']*outcome['failed']
            assert abs(outcome['utility']-expected)<1e-10,'Utility must be computed per trajectory'
            for c in ('BTC','USD'):
                assert abs(outcome['growth'][c]-(outcome['holdings'][c]-row['goal']['initial'][c])/row['goal']['initial'][c])<1e-10
            assert row['remaining_ms']==row['goal']['horizon']-row['time']>0
            labels+=1
    assert report['resources']['recorded_decisions']<=20000
    assert report['resources']['optimizer_updates']<=2000
    assert report['resources']['training_seconds']<=1200 and report['resources']['pilot_seconds']<=3600
    return dict(status='PASS',verified_source_files=len(manifest['files']),verified_source_rows=manifest['raw_rows'],
                audited_episodes=len(episodes),audited_fills=fills,complete_training_labels=labels,
                matched_test_scenarios=len(matched),calibration_episodes=len(report['fixed_continuation_calibration']),
                calibration_note='Separate fixed-continuation diagnostics; not counted as audited fill tapes here',
                source_commit=report['identity']['source_commit'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',required=True);parser.add_argument('--input',required=True)
    args=parser.parse_args();result=audit(args.run,args.input)
    (Path(args.run)/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
