"""Full available Deribit BTC dated-futures archive, immutable resumable chunks."""
import argparse, gzip, hashlib, json, math, os, re, time, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from download_extension import create_bytes, encode, digest
BUCKET = 'keep-and-lease-market-data'
PREFIX = 'btc/research/deribit-full-history-v1'
REQUEST = '.cloud-agent/requests/deribit-full-history.json'
SYMBOL = re.compile(r'^BTC-[0-9]{1,2}[A-Z]{3}[0-9]{2}$')
SHARDS = 8
CHUNK = 10000
PAGE = 1000
ALLOWED = {'get_instruments', 'get_last_trades_by_instrument'}

def request():
    r = json.loads(Path(REQUEST).read_text())
    if set(r) != {'schema_version', 'action', 'job_id', 'sequence'}:
        raise ValueError('Unexpected request fields')
    if r['schema_version'] != 1 or r['action'] not in ('validate', 'download'):
        raise ValueError('Unsupported action')
    if not re.fullmatch(r'btc-full-[0-9]{8}-[a-z0-9-]{1,40}', r['job_id']):
        raise ValueError('Invalid fixed job identifier')
    if type(r['sequence']) is not int or not 1 <= r['sequence'] <= 10000:
        raise ValueError('Invalid request sequence')
    return r

def api(method, **params):
    if method not in ALLOWED:
        raise ValueError('Unsupported public endpoint')
    if method == 'get_instruments':
        if params.get('currency') != 'BTC' or params.get('kind') != 'future':
            raise ValueError('Only BTC futures are authorized')
    elif not SYMBOL.fullmatch(params.get('instrument_name', '')):
        raise ValueError('Only dated BTC instruments are authorized')
    url = 'https://history.deribit.com/api/v2/public/' + method + '?' + urllib.parse.urlencode(params)
    for attempt in range(7):
        try:
            time.sleep(0.5)
            with urllib.request.urlopen(url, timeout=60) as f:
                result = json.load(f)
            if 'error' in result:
                raise ValueError(str(result['error']))
            return result['result']
        except Exception:
            if attempt == 6:
                raise
            time.sleep(min(30, 2 ** attempt))

def catalog():
    raw = {flag: api('get_instruments', currency='BTC', kind='future', expired=flag)
           for flag in ('true', 'false')}
    merged = {}
    for rows in raw.values():
        for info in rows:
            name = info['instrument_name']
            if SYMBOL.fullmatch(name) and info.get('kind') == 'future':
                merged[name] = info
    if not merged:
        raise ValueError('Archive returned no dated BTC futures')
    # A recent-only catalog is not a full-history catalog. Fail closed.
    earliest = min(i['creation_timestamp'] for i in merged.values())
    if earliest >= 1577836800000:
        raise ValueError('Archive catalog does not include pre-2020 instruments; completeness cannot be established')
    return raw, sorted(merged.values(), key=lambda i: (i['creation_timestamp'], i['instrument_name']))

def get_json(bucket, key):
    from google.api_core.exceptions import NotFound
    try:
        return json.loads(bucket.blob(key).download_as_bytes(checksum='crc32c', timeout=120))
    except NotFound:
        return None

def key_for(job_id, name):
    return f'{PREFIX}/jobs/{job_id}/{name}'

def checked_rows(result, symbol, start, end):
    rows = result['trades']
    if not rows:
        raise ValueError(f'Empty page before frozen tail: {symbol} {start}')
    rows = sorted(rows, key=lambda x: x['trade_seq'])
    if [r['trade_seq'] for r in rows] != list(range(start, start + len(rows))):
        raise ValueError(f'Sequence gap or duplicate: {symbol} {start}')
    if rows[-1]['trade_seq'] > end:
        raise ValueError('Endpoint exceeded requested sequence range')
    ids = set()
    for r in rows:
        if r.get('instrument_name') != symbol or r['trade_id'] in ids:
            raise ValueError('Wrong instrument or duplicate trade ID')
        ids.add(r['trade_id'])
        if not all(math.isfinite(r[k]) and r[k] > 0 for k in ('price', 'amount', 'timestamp')):
            raise ValueError('Invalid trade numeric field')
    return rows

def verify_receipt(bucket, key, symbol, start, end):
    r = get_json(bucket, key)
    if r is None:
        return None
    if (r.get('status'), r.get('instrument'), r.get('first_seq'), r.get('last_seq')) != ('COMPLETE', symbol, start, end):
        raise ValueError('Receipt does not match planned chunk')
    if r.get('rows') != end - start + 1:
        raise ValueError('Receipt count mismatch')
    for obj in r['objects']:
        b = bucket.blob(obj['key']).download_as_bytes(checksum='crc32c', timeout=120)
        if len(b) != obj['bytes'] or digest(b) != obj['sha256']:
            raise ValueError('Persistent chunk hash mismatch')
    return r

def plan(bucket, r):
    key = key_for(r['job_id'], 'plan.json')
    previous = get_json(bucket, key)
    if previous:
        if previous.get('job_id') != r['job_id'] or previous.get('schema_version') != 1:
            raise ValueError('Plan mismatch')
        return previous
    raw, instruments = catalog()
    catalog_record = create_bytes(bucket, key_for(r['job_id'], f'catalogs/{digest(encode(raw))}.json'), encode(raw))
    entries = []
    for info in instruments:
        symbol = info['instrument_name']
        first = api('get_last_trades_by_instrument', instrument_name=symbol, start_seq=1, count=1, sorting='asc')['trades']
        tail = api('get_last_trades_by_instrument', instrument_name=symbol, count=1, sorting='desc')['trades']
        if bool(first) != bool(tail):
            raise ValueError('Inconsistent first/tail availability')
        if first and (first[0]['instrument_name'] != symbol or tail[0]['instrument_name'] != symbol):
            raise ValueError('Snapshot endpoint returned wrong instrument')
        lo = first[0]['trade_seq'] if first else None
        hi = tail[0]['trade_seq'] if tail else None
        if first and (lo < 1 or hi < lo):
            raise ValueError('Invalid sequence snapshot')
        entries.append({'instrument': symbol, 'metadata': info,
                        'first_available_seq': lo, 'last_available_seq': hi,
                        'first_trade': first, 'last_trade': tail,
                        'prefix_unavailable': bool(first and lo != 1),
                        'snapshot_at': datetime.now(timezone.utc).isoformat()})
    p = {'schema_version': 1, 'job_id': r['job_id'], 'status': 'PLANNED',
         'source_commit': os.environ.get('GITHUB_SHA'), 'shards': SHARDS, 'chunk_size': CHUNK, 'catalog_object': catalog_record,
         'instruments': entries, 'snapshot_completed_at': datetime.now(timezone.utc).isoformat(),
         'scope': 'All dated inverse BTC futures returned by Deribit historical archive; raw trades through each frozen last sequence',
         'limitations': ['Archive-reported availability, not proof of exchange-wide completeness.',
                         'Snapshot times differ by instrument; active instruments may have a partial current day.',
                         'No order-book history or independent continuous index tape.',
                         'Unavailable prefixes are explicitly recorded; gaps inside available history are fatal.']}
    create_bytes(bucket, key, encode(p))
    return p

def tasks(p, shard):
    for item in p['instruments']:
        lo, hi = item['first_available_seq'], item['last_available_seq']
        if lo is None:
            continue
        for start in range(lo, hi + 1, CHUNK):
            end = min(start + CHUNK - 1, hi)
            label = f"{item['instrument']}/{start:012d}-{end:012d}"
            if int(hashlib.sha256(label.encode()).hexdigest()[:8], 16) % SHARDS == shard:
                yield item['instrument'], start, end, label

def download_chunk(bucket, r, symbol, start, end, label):
    key = key_for(r['job_id'], f'receipts/{label}.json')
    old = verify_receipt(bucket, key, symbol, start, end)
    if old:
        return key, old['rows'], True
    cursor = start
    trades, responses, ids = [], [], set()
    while cursor <= end:
        result = api('get_last_trades_by_instrument', instrument_name=symbol,
                     start_seq=cursor, end_seq=min(cursor + PAGE - 1, end),
                     count=PAGE, sorting='asc')
        rows = checked_rows(result, symbol, cursor, min(cursor + PAGE - 1, end))
        for row in rows:
            if row['trade_id'] in ids:
                raise ValueError('Duplicate trade ID across pages')
            ids.add(row['trade_id'])
        responses.append({'start_seq': cursor, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'result': result})
        trades.extend(rows)
        cursor = rows[-1]['trade_seq'] + 1
    objects = []
    for name, values in [('trades.jsonl.gz', trades), ('responses.jsonl.gz', responses)]:
        data = gzip.compress(b''.join(encode(v).replace(b'\n', b'') + b'\n' for v in values), mtime=0)
        objects.append(create_bytes(bucket, f'{PREFIX}/objects/{digest(data)}/{name}', data))
    receipt = {'schema_version': 1, 'status': 'COMPLETE', 'instrument': symbol,
               'first_seq': start, 'last_seq': end, 'rows': len(trades), 'objects': objects,
               'min_timestamp': min(t['timestamp'] for t in trades), 'max_timestamp': max(t['timestamp'] for t in trades),
               'timestamp_reversals': sum(b['timestamp'] < a['timestamp'] for a, b in zip(trades, trades[1:]))}
    create_bytes(bucket, key, encode(receipt))
    return key, len(trades), False

def download(bucket, r, shard):
    p = get_json(bucket, key_for(r['job_id'], 'plan.json'))
    if p is None:
        raise ValueError('Missing frozen plan')
    started = time.monotonic()
    completed, failed = [], []
    pending = False
    for symbol, start, end, label in tasks(p, shard):
        if time.monotonic() - started > 300 * 60:
            pending = True
            break
        try:
            key, rows, reused = download_chunk(bucket, r, symbol, start, end, label)
            completed.append(key)
            print(json.dumps({'stage': 'CHUNK_COMPLETE', 'instrument': symbol, 'first_seq': start, 'last_seq': end, 'reused': reused}), flush=True)
        except Exception as e:
            failed.append({'instrument': symbol, 'first_seq': start, 'last_seq': end, 'error': str(e)[:500]})
            print(json.dumps({'stage': 'CHUNK_FAILED', **failed[-1]}), flush=True)
            if len(failed) >= 10:
                pending = True
                break
    report = {'job_id': r['job_id'], 'shard': shard, 'status': 'COMPLETE' if not failed and not pending else 'INCOMPLETE',
              'receipt_keys': completed, 'failures': failed, 'pending': pending}
    report_key = key_for(r['job_id'], f"attempts/{os.environ.get('GITHUB_RUN_ID', 'local')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}/shard-{shard}.json")
    create_bytes(bucket, report_key, encode(report))
    if report['status'] != 'COMPLETE':
        raise RuntimeError('Shard incomplete; rerun failed jobs to resume verified chunks')
    create_bytes(bucket, key_for(r['job_id'], f'completed/shard-{shard}.json'), encode(report))

def finish(bucket, r):
    p = get_json(bucket, key_for(r['job_id'], 'plan.json'))
    shards = [get_json(bucket, key_for(r['job_id'], f'completed/shard-{s}.json')) for s in range(SHARDS)]
    if p is None or any(s is None or s['status'] != 'COMPLETE' for s in shards):
        raise ValueError('At least one shard is incomplete')
    result = {'schema_version': 1, 'job_id': r['job_id'], 'status': 'COMPLETE_AVAILABLE_HISTORY',
              'plan_key': key_for(r['job_id'], 'plan.json'),
              'shard_keys': [key_for(r['job_id'], f'completed/shard-{s}.json') for s in range(SHARDS)],
              'instruments': len(p['instruments']),
              'prefix_unavailable': [i['instrument'] for i in p['instruments'] if i['prefix_unavailable']]}
    create_bytes(bucket, key_for(r['job_id'], 'manifest.json'), encode(result))

def preflight():
    raw, instruments = catalog()
    symbol = instruments[0]['instrument_name']
    result = api('get_last_trades_by_instrument', instrument_name=symbol, start_seq=1, count=2, sorting='asc')
    rows = result['trades']
    if not rows:
        raise ValueError('Oldest catalog instrument returned no archive data')
    checked_rows(result, symbol, rows[0]['trade_seq'], rows[-1]['trade_seq'])
    print(json.dumps({'stage': 'PREFLIGHT_OK', 'instruments': len(instruments),
                      'oldest': symbol, 'earliest_creation': min(i['creation_timestamp'] for i in instruments),
                      'first_available_trade': rows[0]['timestamp']}), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['validate', 'plan', 'download', 'finish'], required=True)
    parser.add_argument('--shard', type=int, choices=range(SHARDS))
    a = parser.parse_args()
    r = request()
    if a.mode == 'validate':
        preflight()
        from google.cloud import storage
        probe = create_bytes(storage.Client().bucket(BUCKET), key_for(r['job_id'], 'preflight-storage.json'), encode({'job_id': r['job_id'], 'check': 'immutable-write-read'}))
        print(json.dumps({'stage': 'STORAGE_OK', 'key': probe['key']}), flush=True)
    else:
        if r['action'] != 'download':
            raise ValueError('Download has not been requested')
        from google.cloud import storage
        bucket = storage.Client().bucket(BUCKET)
        if a.mode == 'plan':
            p = plan(bucket, r)
            print(json.dumps({'job_id': r['job_id'], 'stage': 'PLAN_READY', 'instruments': len(p['instruments']),
                              'storage': f"gs://{BUCKET}/{PREFIX}/jobs/{r['job_id']}/"}), flush=True)
        elif a.mode == 'download':
            if a.shard is None:
                parser.error('--shard required')
            download(bucket, r, a.shard)
        else:
            finish(bucket, r)
