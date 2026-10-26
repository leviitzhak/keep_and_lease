"""Offline, bounded union of daily exports and native sequence-chunk objects.

Raw trades are deduplicated, never concatenated across overlapping archives.
The SQLite output is a reproducible local cache, not an execution/settlement claim.
No network, downloads, interpolation, or synthetic settlements are performed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from .data import FLAGS, sha
from .engine import Trade


@dataclass(frozen=True)
class Source:
    path: str
    uri: str
    sha256: str
    bytes: int
    rows: int
    instrument: str
    first_seq: int | None = None
    last_seq: int | None = None
    receipt_sha256: str | None = None


def daily_sources(root):
    root = Path(root)
    receipts = {r['sha256']: r for r in json.loads((root/'source_receipts.json').read_text())}
    result = []
    for row in json.loads((root/'input_coverage.json').read_text()):
        filename = Path(row['path']).name
        symbol = filename[11:-9]  # YYYY-MM-DD-SYMBOL.jsonl.gz
        r = receipts[row['sha256']]
        result.append(Source(str(root/'inputs'/filename), 'gs://keep-and-lease-market-data/'+r['key'],
                             row['sha256'], r['bytes'], row['raw_rows'], symbol))
    return result


def archive_inventory(metadata_root, cache_root):
    """Pin exported metadata; enumerate existing receipts without fetching them.

    cache_root mirrors GCS object keys. Missing receipts are an explicit blocker,
    not evidence of missing exchange data. Receipt object hashes authenticate raw
    data relative to that receipt; metadata completion names alone do not pin it.
    """
    root, cache = Path(metadata_root), Path(cache_root)
    export = json.loads((root/'export-receipt.json').read_text())
    pins = []
    for item in export['source_objects']:
        relative = item['key'].split('/jobs/'+export['job_id']+'/')[1]
        path = root/relative
        if path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('Archive metadata receipt mismatch')
        pins.append(dict(file=relative, sha256=item['sha256'], uri='gs://keep-and-lease-market-data/'+item['key']))
    plan = json.loads((root/'plan-reconciled-v2.json').read_text())
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest['status'] != 'COMPLETE_AVAILABLE_HISTORY' or plan['job_id'] != export['job_id']:
        raise ValueError('Incomplete archive metadata')
    expected = {}
    prefix = 'btc/research/deribit-full-history-v1/jobs/'+export['job_id']
    for item in plan['instruments']:
        lo, hi = item['first_available_seq'], item['last_available_seq']
        if lo is not None:
            for start in range(lo, hi+1, plan['chunk_size']):
                end = min(hi, start+plan['chunk_size']-1)
                key = f'{prefix}/receipts/{item["instrument"]}/{start:012d}-{end:012d}.json'
                expected[key] = (item['instrument'], start, end)
    actual = []
    for shard in sorted((root/'completed').glob('shard-*.json')):
        r = json.loads(shard.read_text())
        if r['status'] != 'COMPLETE' or r['failures'] or r['pending']:
            raise ValueError('Incomplete shard')
        actual.extend(r['receipt_keys'])
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError('Archive receipt coverage mismatch')
    sources, missing = [], []
    for key in sorted(actual):
        path = cache/key
        if not path.exists():
            missing.append(key)
            continue
        r = json.loads(path.read_text())
        symbol, lo, hi = expected[key]
        if (r['status'],r['instrument'],r['first_seq'],r['last_seq'],r['rows']) != ('COMPLETE',symbol,lo,hi,hi-lo+1):
            raise ValueError('Archive chunk receipt mismatch')
        objects = [o for o in r['objects'] if o['key'].endswith('/trades.jsonl.gz')]
        if len(objects) != 1:
            raise ValueError('Ambiguous raw trade object')
        obj = objects[0]
        sources.append(Source(str(cache/obj['key']), 'gs://keep-and-lease-market-data/'+obj['key'],
                              obj['sha256'], obj['bytes'], r['rows'], symbol, lo, hi, sha(path)))
    return sources, dict(status='RAW_RECEIPTS_MISSING' if missing else 'RECEIPTS_PRESENT_RAW_UNVERIFIED',
                         job=export['job_id'], metadata_pins=pins, instruments=plan['instruments'],
                         chunks=len(actual), missing_receipts=len(missing), missing_receipt_example=missing[:3],
                         expected_native_rows=sum(i['last_available_seq']-i['first_available_seq']+1
                                                  for i in plan['instruments'] if i['first_available_seq'] is not None),
                         prefix_unavailable=manifest['prefix_unavailable'])


def canonical(row):
    """Compare all execution-relevant native fields; retain original raw JSON too."""
    keys = ('instrument_name','timestamp','trade_seq','price','amount','direction','index_price')
    result = {k: row.get(k) for k in keys}
    for k in ('price','amount','index_price'):
        if isinstance(result[k],(int,float)):
            result[k]=float(result[k])
    result['trade_id'] = str(row['trade_id'])
    result.update({k: row.get(k) or None for k in FLAGS})
    return json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)


def build_union(sources, destination, *, row_cap=600000, byte_cap=12000000, seconds=180):
    """Fail atomically on conflicts, bounds, bad hashes, or native sequence gaps.

    Inter-object sequence gaps are reported and preserved. The bound is on rows
    ingested (including duplicates), rather than the smaller union size.
    """
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Refusing to replace an existing union')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix+'.tmp')
    if temp.exists():
        raise ValueError('Stale partial union exists')
    began = time.monotonic()
    db = sqlite3.connect(temp)
    rows = total_bytes = duplicate = 0
    try:
        db.executescript('''PRAGMA cache_size=-16384;
          CREATE TABLE sources (id INTEGER PRIMARY KEY, metadata TEXT NOT NULL);
          CREATE TABLE trades (symbol TEXT, id TEXT, seq INTEGER, ts INTEGER, identity TEXT, raw TEXT,
            valid INTEGER, PRIMARY KEY(symbol,id), UNIQUE(symbol,seq));
          CREATE TABLE origins (symbol TEXT, id TEXT, source INTEGER, PRIMARY KEY(symbol,id,source));''')
        for index, source in enumerate(sources):
            path = Path(source.path)
            total_bytes += source.bytes
            if total_bytes > byte_cap or source.bytes > 8000000 or source.rows > 100000:
                raise ValueError('Input byte/row cap')
            if path.stat().st_size != source.bytes or sha(path) != source.sha256:
                raise ValueError('Raw source hash/size mismatch')
            db.execute('INSERT INTO sources VALUES (?,?)', (index,json.dumps(asdict(source),sort_keys=True)))
            previous = None
            count = 0
            with gzip.open(path, 'rt') as file:
                for line in file:
                    rows += 1; count += 1
                    if rows > row_cap or time.monotonic()-began > seconds or len(line)>65536:
                        raise ValueError('Input row/time/record cap')
                    row = json.loads(line)
                    seq, ts = row['trade_seq'], row['timestamp']
                    if row['instrument_name'] != source.instrument or not isinstance(seq,int) or not isinstance(ts,int) or ts<=0:
                        raise ValueError('Invalid native identity/timestamp')
                    if previous is not None and seq != previous+1:
                        raise ValueError('Within-object sequence gap')
                    if count == 1 and source.first_seq is not None and seq != source.first_seq:
                        raise ValueError('Chunk first sequence mismatch')
                    previous = seq
                    identity = canonical(row)
                    key = (source.instrument,str(row['trade_id']))
                    old = db.execute('SELECT identity FROM trades WHERE symbol=? AND id=?',key).fetchone()
                    if old:
                        if old[0] != identity:
                            raise ValueError('Conflicting overlap for '+repr(key))
                        duplicate += 1
                    else:
                        valid = (row.get('direction') in ('buy','sell') and
                                 all(isinstance(row.get(k),(int,float)) and math.isfinite(row[k]) and row[k]>0
                                     for k in ('price','amount','index_price')) and not any(row.get(k) for k in FLAGS))
                        db.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?)',
                                   (*key,seq,ts,identity,json.dumps(row,sort_keys=True),int(valid)))
                    db.execute('INSERT OR IGNORE INTO origins VALUES (?,?,?)',(*key,index))
            if count != source.rows or (source.last_seq is not None and previous != source.last_seq):
                raise ValueError('Chunk row/last-sequence mismatch')
        gaps = [dict(symbol=s,previous_seq=a,next_seq=b) for s,a,b in db.execute('''
            SELECT symbol,previous,seq FROM (SELECT symbol,seq,LAG(seq) OVER(PARTITION BY symbol ORDER BY seq) previous
            FROM trades) WHERE previous IS NOT NULL AND seq>previous+1''')]
        coverage = [dict(symbol=s,rows=n,first_ms=a,last_ms=b,first_seq=lo,last_seq=hi)
                    for s,n,a,b,lo,hi in db.execute('SELECT symbol,COUNT(*),MIN(ts),MAX(ts),MIN(seq),MAX(seq) FROM trades GROUP BY symbol')]
        db.commit(); db.close(); temp.replace(destination)
    except Exception:
        db.close(); temp.unlink(missing_ok=True); raise
    return dict(status='AVAILABLE_LOCAL_SOURCES_UNIFIED', input_rows=rows, unique_rows=rows-duplicate,
                duplicate_rows=duplicate, compressed_bytes=total_bytes, sources=len(sources), coverage=coverage,
                sequence_gaps=gaps, seconds=time.monotonic()-began, database_sha256=sha(destination),
                source_payoff='inverse', amount_unit='USD notional', settlement_evidence='not supplied',
                mode='Raw archive union; linear replay remains a counterfactual experiment')


def iter_trades(database, start, end, *, prefix_anchors=None):
    """Causal normalized adapter: sequence-prefix availability, bounded window.

    Missing prefixes require a separately verified (previous_seq, max_timestamp)
    anchor. Backdated prints remain observable but cannot execute resting orders
    retroactively. Any internal gap blocks this strict replay adapter.
    """
    anchors = prefix_anchors or {}
    with sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro',uri=True) as db:
        for symbol,lo,hi,n in db.execute('SELECT symbol,MIN(seq),MAX(seq),COUNT(*) FROM trades GROUP BY symbol'):
            if n != hi-lo+1:
                raise ValueError('Unresolved sequence gap: '+symbol)
            if lo != 1 and (symbol not in anchors or anchors[symbol][0] != lo-1):
                raise ValueError('Verified prefix anchor required: '+symbol)
        db.execute('CREATE TEMP TABLE anchors(symbol TEXT PRIMARY KEY, timestamp INTEGER)')
        db.executemany('INSERT INTO anchors VALUES (?,?)',[(s,x[1]) for s,x in anchors.items()])
        query = '''SELECT raw,available,valid FROM (
          SELECT symbol,seq,raw,valid,MAX(COALESCE((SELECT timestamp FROM anchors WHERE anchors.symbol=trades.symbol),0),
          MAX(ts) OVER(PARTITION BY symbol ORDER BY seq ROWS UNBOUNDED PRECEDING)) available FROM trades
        ) WHERE available>=? AND available<? ORDER BY available,symbol,seq'''
        for raw,available,valid in db.execute(query,(start,end)):
            r = json.loads(raw)
            # Invalid numeric rows are preserved in raw union, not made market marks.
            if r.get('direction') not in ('buy','sell') or not all(isinstance(r.get(k),(int,float)) and r[k]>0 for k in ('price','amount','index_price')):
                continue
            yield Trade(available,r['instrument_name'],r['price'],r['amount'],r['direction'],str(r['trade_id']),
                        r['index_price'],executable=bool(valid) and available==r['timestamp'],source_time=r['timestamp'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--daily-root',required=True);p.add_argument('--metadata-root',required=True)
    p.add_argument('--archive-cache',required=True);p.add_argument('--database',required=True);p.add_argument('--report',required=True)
    args=p.parse_args()
    archive,inventory=archive_inventory(args.metadata_root,args.archive_cache)
    available=[s for s in archive if Path(s.path).exists()]
    result=build_union(daily_sources(args.daily_root)+available,args.database)
    result['archive_inventory']=inventory
    result['full_archive_union_complete']=not inventory['missing_receipts'] and len(available)==len(archive)
    result['missing_known_raw_objects']=len(archive)-len(available)
    result['raw_chunks_uninspected_missing_receipts']=inventory['missing_receipts']
    Path(args.report).parent.mkdir(parents=True,exist_ok=True)
    Path(args.report).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('archive_inventory','coverage')}))


if __name__=='__main__':main()
