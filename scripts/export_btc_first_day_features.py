#!/usr/bin/env python3
"""Read the pinned first day of public market trades into 500-ms rolling inputs.

No portfolio, account results, writes to cloud storage or credential exports.
Only unchanged feature rows are compressed; as-of lookup reconstructs every
500-ms decision. Business lease/ranking formulas belong in the workbook.
"""
import argparse
from dataclasses import asdict
import gzip
import hashlib
import heapq
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from btc_trade_backtest import us_time
from paired_transfer_rates import CausalTreasuryRates
from rolling_lease_distribution import RollingLeaseDistributionWindow
from trade_data_store import ParquetTradeStore
from trade_ordering import OrderedTradeStore
from trade_replay import Trade
from scripts.build_lease_maturity_history import Inputs, RANGE_SHA

START, END = '2026-06-06T00:00:00', '2026-06-07T00:00:00'
COLUMNS = ['tick_500ms', 'current_price', 'current_source_offset_us', 'sample_count',
           'minimum_price', 'maximum_price', 'median_price', 'median_reciprocal_price', 'current_executable']


def feature_rows(events, seeds, symbols, start, end, window_seconds=5, delay_us=100000):
    window = RollingLeaseDistributionWindow(window_seconds)
    marks, previous = {}, {}
    tape = heapq.merge(seeds, events, key=lambda t:(t.us,t.symbol,t.sequence or 0))
    event = next(tape, None)
    for tick in range(1, (end-start)//500000+1):
        now = start+tick*500000
        while event is not None and event.us+delay_us <= now:
            source = event.us if event.reported_us is None else event.reported_us
            old = marks.get(event.symbol)
            if old is None or (source,event.us) >= (old[1],old[2]):
                marks[event.symbol] = (event.price,source,event.us,event.executable)
                window.observe(event.symbol,event.price,source,event.us+delay_us)
            event = next(tape, None)
        for symbol in symbols:
            mark = marks.get(symbol)
            stats = window.statistics(symbol,now)
            state = ([mark[0],mark[1]-start] if mark else [None,None])+[
                stats['count'] if stats else 0,
                *([stats[k] for k in ('minimum','maximum','median','median_reciprocal')] if stats else [None]*4),
                int(mark[3]) if mark else 0]
            if state != previous.get(symbol):
                previous[symbol] = state
                yield symbol, [tick,*state]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    inputs=Inputs('adc',budget=1024**3)
    write=lambda name,value:(args.output/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    start,end=us_time(START),us_time(END)
    with tempfile.TemporaryDirectory(prefix='first-day-market-') as tmp:
        tmp=Path(tmp)
        topfile=inputs.fetch(f'btc/trades/ranges/{RANGE_SHA}/manifest.json',RANGE_SHA,tmp/'range.json',cap=8*1024**2)
        top=json.loads(topfile.read_text())
        day=next(d for d in top['daily_datasets'] if us_time(d['start'])==start)
        assert us_time(day['end'])==end
        sha=day['manifest_sha256']; prefix=f'btc/trades/v1/{sha}/'
        data=tmp/'day';data.mkdir()
        childfile=inputs.fetch(prefix+'manifest.json',sha,data/'manifest.json',cap=8*1024**2)
        child=json.loads(childfile.read_text())
        for part in child['partitions']:
            destination=data/part['path'];destination.parent.mkdir(parents=True,exist_ok=True)
            inputs.fetch(prefix+part['path'],part['sha256'],destination)
        store=OrderedTradeStore(ParquetTradeStore(data),'sequence')
        symbols=['SPOT',*sorted(child['source_manifest']['futures'])]
        expiries={s:us_time(v['expiry']) for s,v in child['source_manifest']['futures'].items()}
        seeds=[]
        for s,v in child['source_manifest']['futures'].items():
            seed=v.get('seed')
            if seed:
                assert seed['timestamp']*1000 < start
                seeds.append(Trade(seed['timestamp']*1000,s,seed['price'],seed['amount']/seed['price'],seed['direction'],seed['trade_id'],
                    not any(seed.get(k) for k in ('block_trade_id','block_rfq_id','combo_id'))))
        seeds.sort(key=lambda t:(t.us,t.symbol))
        events=(t for t in store.trades(start_us=start,end_us=end) if t.symbol=='SPOT' or t.us<expiries[t.symbol])
        handles={s:gzip.open(args.output/(s+'.jsonl.gz'),'wt',compresslevel=6) for s in symbols}
        counts={s:0 for s in symbols}
        try:
            for symbol,row in feature_rows(events,seeds,symbols,start,end):
                handles[symbol].write(json.dumps(row,separators=(',',':'),allow_nan=False)+'\n')
                counts[symbol]+=1
        finally:
            for h in handles.values():h.close()
        rate=CausalTreasuryRates.from_root(ROOT).rate_at(start)
        write('metadata.json',dict(status='complete',start=START,end=END,interval_seconds=.5,
            ticks=172800,window_seconds=5,observation_delay_seconds=.1,median_weighting='observed_trades',
            columns=COLUMNS,feature_rows=counts,rate=rate.as_dict(),range_sha256=RANGE_SHA,daily_sha256=sha,
            source=child['source_manifest'],ordering=store.window_report(start,end),
            receipts=inputs.receipts,files={s:dict(sha256=hashlib.sha256((args.output/(s+'.jsonl.gz')).read_bytes()).hexdigest(),
                bytes=(args.output/(s+'.jsonl.gz')).stat().st_size) for s in symbols}))
        store.close()
    print(json.dumps(dict(status='complete',feature_rows=counts,read_bytes=inputs.bytes)),flush=True)


if __name__=='__main__':main()
