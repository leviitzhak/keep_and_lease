"""Full available Deribit BTC dated-futures archive, immutable resumable chunks."""
import argparse, gzip, hashlib, json, math, os, re, socket, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from download_extension import create_bytes, encode, digest
BUCKET = 'keep-and-lease-market-data'
PREFIX = 'btc/research/deribit-full-history-v1'
REQUEST = '.cloud-agent/requests/deribit-full-history.json'
SYMBOL = re.compile(r'^BTC-[0-9]{1,2}[A-Z]{3}[0-9]{2}$')
SHARDS = 8
CHUNK = 10000
PAGE = 1000
POLICY = 'archive-reconcile-v2'
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

def api(method, evidence=None, **params):
    if method not in ALLOWED:
        raise ValueError('Unsupported public endpoint')
    if method == 'get_instruments':
        if params.get('currency') != 'BTC' or params.get('kind') != 'future':
            raise ValueError('Only BTC futures are authorized')
    elif not SYMBOL.fullmatch(params.get('instrument_name', '')):
        raise ValueError('Only dated BTC instruments are authorized')
    params['include_old'] = 'true'
    for attempt in range(7):
        record = {'method': method, 'parameters': dict(params),
                  'retrieved_at': datetime.now(timezone.utc).isoformat()}
        try:
            url = 'https://history.deribit.com/api/v2/public/' + method + '?' + urllib.parse.urlencode(params)
            time.sleep(0.5)
            with urllib.request.urlopen(url, timeout=60) as f:
                result = json.load(f)
            record['response'] = result
            if 'error' in result:
                if result['error'].get('code') == 13888:
                    raise TimeoutError('Deribit archive timed_out (13888)')
                raise ValueError(str(result['error']))
            return result['result']
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            record['http_status'], record['error_body'] = e.code, body
            timed_out = 'timed_out' in body or '13888' in body
            if not timed_out and e.code not in (429, 500, 502, 503, 504):
                raise ValueError(f'Deribit HTTP {e.code}: {body[:500]}') from e
            if attempt == 6:
                raise
            if timed_out and params.get('count', 0) > 100:
                params['count'] = max(100, params['count'] // 2)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
            record['error'] = str(e)
            if attempt == 6:
                raise
            if params.get('count', 0) > 100:
                params['count'] = max(100, params['count'] // 2)
        finally:
            if evidence is not None:
                evidence.append(record)
        time.sleep(min(16, 2 ** attempt))


def numeric_flags(row):
    flags = []
    for field in ('price', 'amount', 'timestamp'):
        value = row.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            flags.append(f'invalid_{field}')
        elif not math.isfinite(value):
            raise ValueError(f'Non-finite JSON numeric value: {field}')
        elif value <= 0:
            flags.append(('zero_' if value == 0 else 'negative_') + field)
    return flags


def page_rows(result, symbol):
    by_seq, by_id = {}, {}
    for row in result['trades']:
        seq, identifier = row.get('trade_seq'), row.get('trade_id')
        if row.get('instrument_name') != symbol or type(seq) is not int or seq < 1 or not identifier:
            raise ValueError('Wrong instrument or invalid trade identity')
        if seq in by_seq and by_seq[seq] != row:
            raise ValueError(f'Conflicting sequence {symbol} {seq}')
        if identifier in by_id and by_id[identifier] != seq:
            raise ValueError(f'Conflicting trade ID {symbol} {identifier}')
        numeric_flags(row)
        by_seq[seq], by_id[identifier] = row, seq
    return [by_seq[k] for k in sorted(by_seq)]


def collect_chunk(symbol, start, end, responses):
    # API bounds are hints: older archives sometimes return shifted windows.
    # Advance by returned trade_seq, and never advance past an unresolved hole.
    captured, ids = {}, {}
    cursor, query_start, stalled, queries = start, start, 0, 0
    while cursor <= end:
        queries += 1
        if queries > 500:
            raise ValueError('Bounded chunk request budget exceeded')
        result = api('get_last_trades_by_instrument', evidence=responses,
                     instrument_name=symbol, start_seq=query_start,
                     count=PAGE, sorting='asc')
        rows = page_rows(result, symbol)
        for row in rows:
            seq, identifier = row['trade_seq'], row['trade_id']
            if start <= seq <= end:
                if seq in captured and captured[seq] != row:
                    raise ValueError(f'Conflicting overlap {symbol} {seq}')
                if identifier in ids and ids[identifier] != seq:
                    raise ValueError(f'Duplicate trade ID across pages: {identifier}')
                captured[seq], ids[identifier] = row, seq
        before = cursor
        while cursor <= end and cursor in captured:
            cursor += 1
        if cursor > before:
            query_start, stalled = cursor, 0
            continue
        stalled += 1
        if stalled >= 8:
            raise ValueError(f'Unresolved sequence gap: {symbol} {cursor}; retained response evidence')
        if not rows:
            query_start = max(1, query_start - PAGE * 2 ** (stalled - 1))
        elif rows[0]['trade_seq'] > cursor:
            query_start = max(1, query_start - max(rows[0]['trade_seq'] - cursor, 2 ** (stalled - 1)))
        elif rows[-1]['trade_seq'] < cursor:
            query_start += max(1, cursor - rows[0]['trade_seq'])
        else:
            # The page brackets a real/endpoint hole: seek from its left edge.
            query_start = max(1, cursor - PAGE // 2 * 2 ** (stalled - 1))
    return [captured[n] for n in range(start, end + 1)]


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
    rows = [r for r in page_rows(result, symbol) if start <= r['trade_seq'] <= end]
    if not rows or [r['trade_seq'] for r in rows] != list(range(start, start + len(rows))):
        raise ValueError(f'Sequence gap: {symbol} {start}')
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

def reconcile_plan(bucket, r, original):
    key = key_for(r['job_id'], 'plan-reconciled-v2.json')
    previous = get_json(bucket, key)
    if previous is not None:
        return previous
    def boundary(item):
        symbol = item['instrument']
        expiry = item['metadata']['expiration_timestamp']
        frozen_at = datetime.fromisoformat(item['snapshot_at']).timestamp() * 1000
        # Keep active contract cutoffs exactly as originally frozen.
        if expiry > frozen_at or item['last_available_seq'] is None:
            return dict(item)
        saved_key = key_for(r['job_id'], f'boundaries-v2/{symbol}.json')
        saved = get_json(bucket, saved_key)
        if saved is None:
            evidence = []
            result = api('get_last_trades_by_instrument', evidence=evidence,
                         instrument_name=symbol, count=PAGE, sorting='desc')
            rows = page_rows(result, symbol)
            if not rows:
                raise ValueError(f'Expired tail disappeared: {symbol}')
            high = max(item['last_available_seq'], max(row['trade_seq'] for row in rows))
            data = gzip.compress(encode(evidence), mtime=0)
            obj = create_bytes(bucket, f'{PREFIX}/objects/{digest(data)}/boundary-response.json.gz', data)
            saved = {'instrument': symbol, 'original_last_seq': item['last_available_seq'],
                     'last_seq': high, 'evidence': obj, 'policy': POLICY}
            create_bytes(bucket, saved_key, encode(saved))
        return dict(item, last_available_seq=saved['last_seq'], original_last_available_seq=item['last_available_seq'], boundary_receipt=saved_key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        instruments = list(pool.map(boundary, original['instruments']))
    result = dict(original, instruments=instruments, source_policy=POLICY,
                  original_plan_key=key_for(r['job_id'], 'plan.json'),
                  boundary_policy='Maximum of original frozen tail and a 1000-record descending tail sample, expired contracts only')
    create_bytes(bucket, key, encode(result))
    return result


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
    responses = []
    try:
        trades = collect_chunk(symbol, start, end, responses)
    except Exception as exc:
        if responses:
            data = gzip.compress(encode(responses), mtime=0)
            obj = create_bytes(bucket, f'{PREFIX}/failure-evidence/{digest(data)}.json.gz', data)
            exc.evidence_key = obj['key']
        raise
    anomalies = [{'trade_seq': t['trade_seq'], 'trade_id': t['trade_id'],
                  'flags': numeric_flags(t), 'eligible_for_execution': False}
                 for t in trades if numeric_flags(t)]
    objects = []
    for name, values in [('trades.jsonl.gz', trades), ('responses.jsonl.gz', responses), ('anomalies.jsonl.gz', anomalies)]:
        data = gzip.compress(b''.join(encode(v).replace(b'\n', b'') + b'\n' for v in values), mtime=0)
        objects.append(create_bytes(bucket, f'{PREFIX}/objects/{digest(data)}/{name}', data))
    receipt = {'schema_version': 1, 'status': 'COMPLETE', 'instrument': symbol,
               'first_seq': start, 'last_seq': end, 'rows': len(trades), 'objects': objects,
               'source_policy': POLICY, 'numeric_anomaly_rows': len(anomalies),
               'source_commit': os.environ.get('GITHUB_SHA'),
               'min_timestamp': min((t['timestamp'] for t in trades if isinstance(t.get('timestamp'), (int, float)) and t['timestamp'] > 0), default=None), 'max_timestamp': max((t['timestamp'] for t in trades if isinstance(t.get('timestamp'), (int, float)) and t['timestamp'] > 0), default=None),
               'timestamp_reversals': sum(b['timestamp'] < a['timestamp'] for a, b in zip(trades, trades[1:]) if isinstance(a.get('timestamp'), (int, float)) and isinstance(b.get('timestamp'), (int, float)))}
    create_bytes(bucket, key, encode(receipt))
    return key, len(trades), False

def download(bucket, r, shard):
    p = get_json(bucket, key_for(r['job_id'], 'plan-reconciled-v2.json'))
    if p is None:
        raise ValueError('Missing frozen plan')
    started = time.monotonic()
    completed, failed = [], []
    pending = False
    consecutive_operational_failures = 0
    for symbol, start, end, label in tasks(p, shard):
        if time.monotonic() - started > 300 * 60:
            pending = True
            break
        try:
            key, rows, reused = download_chunk(bucket, r, symbol, start, end, label)
            completed.append(key)
            consecutive_operational_failures = 0
            print(json.dumps({'stage': 'CHUNK_COMPLETE', 'instrument': symbol, 'first_seq': start, 'last_seq': end, 'reused': reused}), flush=True)
        except Exception as e:
            failed.append({'instrument': symbol, 'first_seq': start, 'last_seq': end, 'error': str(e)[:500], 'evidence_key': getattr(e, 'evidence_key', None)})
            print(json.dumps({'stage': 'CHUNK_FAILED', **failed[-1]}), flush=True)
            consecutive_operational_failures = 0 if isinstance(e, ValueError) else consecutive_operational_failures + 1
            if consecutive_operational_failures >= 10:
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
    p = get_json(bucket, key_for(r['job_id'], 'plan-reconciled-v2.json'))
    shards = [get_json(bucket, key_for(r['job_id'], f'completed/shard-{s}.json')) for s in range(SHARDS)]
    if p is None or any(s is None or s['status'] != 'COMPLETE' for s in shards):
        raise ValueError('At least one shard is incomplete')
    result = {'schema_version': 1, 'job_id': r['job_id'], 'status': 'COMPLETE_AVAILABLE_HISTORY',
              'plan_key': key_for(r['job_id'], 'plan-reconciled-v2.json'),
              'shard_keys': [key_for(r['job_id'], f'completed/shard-{s}.json') for s in range(SHARDS)],
              'instruments': len(p['instruments']),
              'prefix_unavailable': [i['instrument'] for i in p['instruments'] if i['prefix_unavailable']]}
    create_bytes(bucket, key_for(r['job_id'], 'manifest.json'), encode(result))

def preflight():
    raw, instruments = catalog()
    empty = []
    for info in instruments:
        symbol = info['instrument_name']
        result = api('get_last_trades_by_instrument', instrument_name=symbol, start_seq=1, count=2, sorting='asc')
        rows = result['trades']
        if rows:
            break
        empty.append(symbol)
    else:
        raise ValueError('Archive catalog returned no available trade histories')
    checked_rows(result, symbol, rows[0]['trade_seq'], rows[-1]['trade_seq'])
    print(json.dumps({'stage': 'PREFLIGHT_OK', 'instruments': len(instruments),
                      'oldest_available': symbol, 'empty_earlier_instruments': empty, 'earliest_creation': min(i['creation_timestamp'] for i in instruments),
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
            p = reconcile_plan(bucket, r, plan(bucket, r))
            print(json.dumps({'job_id': r['job_id'], 'stage': 'PLAN_READY', 'instruments': len(p['instruments']),
                              'storage': f"gs://{BUCKET}/{PREFIX}/jobs/{r['job_id']}/"}), flush=True)
        elif a.mode == 'download':
            if a.shard is None:
                parser.error('--shard required')
            download(bucket, r, a.shard)
        else:
            finish(bucket, r)
