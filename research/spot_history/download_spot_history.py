"""Resume checksum-verified Binance BTCUSDT raw trades around the existing 90 days."""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

BUCKET = 'keep-and-lease-market-data'
PREFIX = 'btc/research/binance-spot-full-history-v1'
FUTURES_PLAN = 'btc/research/deribit-full-history-v1/jobs/btc-full-20261009-archive/plan-reconciled-v2.json'
RANGE_SHA = '52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912'
RANGE_KEY = f'btc/trades/ranges/{RANGE_SHA}/manifest.json'
REQUEST = '.cloud-agent/requests/btc-spot-history.json'
EXISTING_START, EXISTING_END = date(2026, 6, 6), date(2026, 9, 4)
SHARDS = 8
WORK_SECONDS = 5 * 3600
MAX_ARCHIVE_BYTES = 8 * 1024**3
VERSION = 1


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def request(path=REQUEST):
    r = json.loads(Path(path).read_text())
    if (set(r) != {'schema_version', 'action', 'job_id', 'sequence'} or
            r['schema_version'] != 1 or r['action'] != 'download-binance-spot-missing-history' or
            not re.fullmatch(r'btc-spot-[0-9]{8}-[a-z0-9-]{1,40}', r['job_id']) or
            type(r['sequence']) is not int or not 1 <= r['sequence'] <= 10000):
        raise ValueError('Invalid bounded spot request')
    return r


def key(r, suffix):
    return f"{PREFIX}/jobs/{r['job_id']}/{suffix}"


def read_json(bucket, name):
    from google.api_core.exceptions import NotFound
    try:
        return json.loads(bucket.blob(name).download_as_bytes(checksum='crc32c', timeout=120))
    except NotFound:
        return None


def create_json(bucket, name, value):
    from google.api_core.exceptions import PreconditionFailed
    data = encode(value)
    blob = bucket.blob(name)
    try:
        blob.upload_from_string(data, content_type='application/json', checksum='crc32c',
                                if_generation_match=0, timeout=120)
    except PreconditionFailed:
        if blob.download_as_bytes(checksum='crc32c', timeout=120) != data:
            raise ValueError(f'Immutable record conflict: {name}') from None
    return value


def plan_dates(futures):
    starts, ends = [], []
    for item in futures['instruments']:
        if item['first_available_seq'] is None:
            continue
        starts.append(item['metadata']['creation_timestamp'])
        starts.extend(t['timestamp'] for t in item['first_trade'] if t['timestamp'] > 0)
        ends.extend(t['timestamp'] for t in item['last_trade'] if t['timestamp'] > 0)
        # Covers all frozen active tails and reconciled expired tails, including
        # partial current UTC days. It does not project to unobserved expiries.
        ends.append(int(datetime.fromisoformat(item['snapshot_at']).timestamp() * 1000))
    if not starts or not ends:
        raise ValueError('Empty futures scope')
    start = datetime.fromtimestamp(min(starts) / 1000, timezone.utc).date()
    end = datetime.fromtimestamp(max(ends) / 1000, timezone.utc).date() + timedelta(days=1)
    if not date(2010, 1, 1) <= start < end <= datetime.now(timezone.utc).date():
        raise ValueError('Unexpected futures time bounds')
    return start, end


def missing_days(start, end):
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days)
            if not EXISTING_START <= start + timedelta(days=i) < EXISTING_END]


def day_shard(day):
    return int(digest(day.encode())[:8], 16) % SHARDS


def archive_url(day):
    date.fromisoformat(day)
    return f'https://data.binance.vision/data/spot/daily/trades/BTCUSDT/BTCUSDT-trades-{day}.zip'


def checksum_text(raw, day):
    fields = raw.decode('ascii').strip().split()
    if (len(fields) != 2 or not re.fullmatch('[0-9a-fA-F]{64}', fields[0]) or
            fields[1].lstrip('*') != f'BTCUSDT-trades-{day}.zip'):
        raise ValueError('Unexpected Binance checksum document')
    return fields[0].lower()


def make_plan(bucket, r):
    previous = read_json(bucket, key(r, 'plan.json'))
    if previous is not None:
        if previous['job_id'] != r['job_id'] or previous['pipeline_version'] != VERSION:
            raise ValueError('Plan identity mismatch')
        return previous
    futures_blob = bucket.blob(FUTURES_PLAN)
    futures_bytes = futures_blob.download_as_bytes(checksum='crc32c', timeout=120)
    existing_bytes = bucket.blob(RANGE_KEY).download_as_bytes(checksum='crc32c', timeout=120)
    if digest(existing_bytes) != RANGE_SHA:
        raise ValueError('Existing 90-day manifest hash mismatch')
    existing = json.loads(existing_bytes)
    source = existing['source_manifest']
    if (source['start'][:10] != str(EXISTING_START) or source['end'][:10] != str(EXISTING_END) or
            len(existing['daily_datasets']) != 90):
        raise ValueError('Unexpected existing spot coverage')
    expected_days = [(EXISTING_START + timedelta(days=i)).isoformat() for i in range(90)]
    if [d['start'][:10] for d in existing['daily_datasets']] != expected_days:
        raise ValueError('Existing day manifest gaps')
    start, end = plan_dates(json.loads(futures_bytes))
    days = missing_days(start, end)
    p = dict(schema_version=1, pipeline_version=VERSION, job_id=r['job_id'],
             created_at=now(), source_commit=os.environ.get('GITHUB_SHA'),
             source='Binance public data / spot / trades / BTCUSDT',
             quote_currency='USDT', market='spot', data_type='individual_trades',
             start_utc=str(start), end_utc_exclusive=str(end), days=days,
             futures_plan_key=FUTURES_PLAN, futures_plan_sha256=digest(futures_bytes),
             reused_range_key=RANGE_KEY, reused_range_sha256=RANGE_SHA,
             reused_start=str(EXISTING_START), reused_end_exclusive=str(EXISTING_END),
             shards=SHARDS, scope='Whole UTC days covering frozen futures archive, excluding existing 90 days',
             validation='Published SHA256 and GCS CRC32C; raw ZIP, not parsed or replay-ready',
             limitations=['Missing source dates remain gaps; no venue substitution.',
                          'USDT/USD parity is an assumption for USD analysis.',
                          'Trade archives do not contain order-book depth.',
                          'Raw spot timestamps are milliseconds before 2025 and microseconds from 2025.'])
    create_json(bucket, key(r, 'inputs/futures-plan.json'), json.loads(futures_bytes))
    create_json(bucket, key(r, 'inputs/existing-range.json'), existing)
    return create_json(bucket, key(r, 'plan.json'), p)


def object_matches(blob, record):
    return (int(blob.size) == record['bytes'] and
            (blob.metadata or {}).get('sha256') == record['sha256'] and
            str(blob.generation) == str(record['generation']) and
            blob.crc32c == record['crc32c'])


def verify_receipt(bucket, r, day):
    saved = read_json(bucket, key(r, f'receipts/{day}.json'))
    if saved is None:
        return None
    if saved['day'] != day or saved['url'] != archive_url(day):
        raise ValueError('Receipt identity mismatch')
    if saved['status'] == 'SOURCE_UNAVAILABLE':
        if saved.get('http_status') != 404:
            raise ValueError('Invalid source-gap evidence')
        return saved
    if saved['status'] != 'VERIFIED_RAW_ARCHIVE':
        raise ValueError('Invalid receipt status')
    blob = bucket.blob(saved['object']['key'])
    blob.reload(timeout=120)
    if not object_matches(blob, saved['object']):
        raise ValueError('Stored archive metadata/generation mismatch')
    return saved


def store_archive(bucket, path, sha):
    from google.api_core.exceptions import PreconditionFailed
    name = f'{PREFIX}/objects/{sha}/{path.name}'
    blob = bucket.blob(name)
    blob.metadata = {'sha256': sha, 'source': 'data.binance.vision'}
    try:
        blob.upload_from_filename(str(path), content_type='application/zip',
                                  if_generation_match=0, checksum='crc32c', timeout=300)
    except PreconditionFailed:
        pass
    blob.reload(timeout=120)
    if int(blob.size) != path.stat().st_size or (blob.metadata or {}).get('sha256') != sha:
        raise ValueError('Stored archive hash metadata/size mismatch')
    return dict(key=name, sha256=sha, bytes=int(blob.size),
                generation=str(blob.generation), crc32c=blob.crc32c)


def download_day(bucket, r, day, deadline):
    saved = verify_receipt(bucket, r, day)
    if saved is not None:
        return saved
    url = archive_url(day)
    for attempt in range(4):
        if time.monotonic() >= deadline:
            raise TimeoutError('work_time_budget')
        try:
            with urllib.request.urlopen(url + '.CHECKSUM', timeout=90) as response:
                raw = response.read(8193)
            sha = checksum_text(raw, day)
            with tempfile.TemporaryDirectory(prefix='btc-spot-') as folder:
                path = Path(folder) / f'BTCUSDT-trades-{day}.zip'
                h, total = hashlib.sha256(), 0
                with urllib.request.urlopen(url, timeout=90) as response, path.open('wb') as stream:
                    while block := response.read(4 * 1024**2):
                        if time.monotonic() >= deadline:
                            raise TimeoutError('work_time_budget')
                        total += len(block)
                        if total > MAX_ARCHIVE_BYTES:
                            raise ValueError('Single archive exceeds bounded disk budget')
                        h.update(block)
                        stream.write(block)
                if h.hexdigest() != sha:
                    raise ValueError('Binance published checksum mismatch')
                # Inspect central directory without extracting multi-GB CSVs.
                with zipfile.ZipFile(path) as zipped:
                    member, = zipped.infolist()
                    if member.filename != path.stem + '.csv' or member.file_size <= 0:
                        raise ValueError('Unexpected or empty archive member')
                    csv_bytes, csv_crc32 = member.file_size, member.CRC
                obj = store_archive(bucket, path, sha)
            record = dict(status='VERIFIED_RAW_ARCHIVE', day=day, url=url,
                          checksum_url=url + '.CHECKSUM', checksum_document=raw.decode('ascii'),
                          retrieved_at=now(), object=obj, csv_bytes=csv_bytes, csv_crc32=csv_crc32,
                          parsed=False, source_commit=os.environ.get('GITHUB_SHA'))
            return create_json(bucket, key(r, f'receipts/{day}.json'), record)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return create_json(bucket, key(r, f'receipts/{day}.json'),
                                   dict(status='SOURCE_UNAVAILABLE', day=day, url=url,
                                        failed_url=error.url, http_status=404, checked_at=now()))
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise
        except (TimeoutError, urllib.error.URLError, ConnectionError):
            if time.monotonic() >= deadline:
                raise TimeoutError('work_time_budget') from None
        if attempt == 3:
            raise RuntimeError(f'Public download retry budget exhausted for {day}')
        time.sleep(min(8, 2 ** attempt))
    raise AssertionError('Unreachable')


def attempt_key(r, name):
    run = os.environ.get('GITHUB_RUN_ID', 'local')
    retry = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    return key(r, f"attempts/{r['sequence']}/{run}-{retry}/{name}.json")


def download(bucket, r, p, shard):
    deadline = time.monotonic() + WORK_SECONDS
    days = [d for d in p['days'] if day_shard(d) == shard]
    completed, missing, errors, status = 0, 0, [], 'COMPLETE'
    try:
        for day in days:
            if time.monotonic() >= deadline:
                status = 'PAUSED'
                break
            rec = download_day(bucket, r, day, deadline)
            completed += 1
            missing += rec['status'] == 'SOURCE_UNAVAILABLE'
            print(json.dumps(dict(day=day, status=rec['status'], completed=completed, total=len(days))), flush=True)
    except TimeoutError as error:
        if str(error) == 'work_time_budget':
            status = 'PAUSED'
        else:
            status = 'FAILED'
            errors.append(type(error).__name__ + ': ' + str(error))
    except Exception as error:
        status = 'FAILED'
        errors.append(type(error).__name__ + ': ' + str(error))
    report = dict(job_id=r['job_id'], shard=shard, status=status, completed=completed,
                  source_unavailable=missing, assigned=len(days), errors=errors, updated_at=now())
    create_json(bucket, attempt_key(r, f'shard-{shard}'), report)
    print(json.dumps(report), flush=True)
    if errors:
        raise RuntimeError('Shard failed; see durable attempt report')


def finish(bucket, r, p):
    records = {}
    for blob in bucket.list_blobs(prefix=key(r, 'receipts/')):
        rec = json.loads(blob.download_as_bytes(checksum='crc32c', timeout=120))
        if rec['day'] in records or rec['day'] not in p['days'] or rec['url'] != archive_url(rec['day']):
            raise ValueError('Unexpected receipt')
        if rec['status'] not in ('SOURCE_UNAVAILABLE', 'VERIFIED_RAW_ARCHIVE'):
            raise ValueError('Invalid receipt')
        records[rec['day']] = rec
    pending = [d for d in p['days'] if d not in records]
    gaps = sorted(d for d, rec in records.items() if rec['status'] == 'SOURCE_UNAVAILABLE')
    verified = sorted(d for d, rec in records.items() if rec['status'] == 'VERIFIED_RAW_ARCHIVE')
    status = 'PAUSED' if pending else ('COMPLETE_WITH_SOURCE_GAPS' if gaps else 'COMPLETE_RAW_ARCHIVE')
    reports = [read_json(bucket, attempt_key(r, f'shard-{i}')) for i in range(SHARDS)]
    if any(report is None or report['status'] == 'FAILED' for report in reports):
        status = 'FAILED_OR_INTERRUPTED'
    result = dict(job_id=r['job_id'], status=status, plan_key=key(r, 'plan.json'),
                  start_utc=p['start_utc'], end_utc_exclusive=p['end_utc_exclusive'],
                  reused_range_key=RANGE_KEY, verified_days=verified, source_unavailable_days=gaps,
                  pending_days=pending, raw_bytes=sum(records[d]['object']['bytes'] for d in verified),
                  receipts_prefix=key(r, 'receipts/'), parsed=False,
                  next_resume_sequence=r['sequence'] + 1, created_at=now())
    create_json(bucket, attempt_key(r, 'summary'), result)
    if not pending and status.startswith('COMPLETE'):
        previous = read_json(bucket, key(r, 'manifest.json'))
        if previous is None:
            create_json(bucket, key(r, 'manifest.json'), result)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['plan', 'download', 'finish'], required=True)
    parser.add_argument('--shard', type=int, choices=range(SHARDS))
    args = parser.parse_args()
    from google.cloud import storage
    r = request()
    bucket = storage.Client().bucket(BUCKET)
    if args.mode == 'plan':
        p = make_plan(bucket, r)
        print(json.dumps(dict(job_id=r['job_id'], start=p['start_utc'], end=p['end_utc_exclusive'],
                              missing_days=len(p['days']), storage=f'gs://{BUCKET}/' + key(r, ''))), flush=True)
        return
    p = read_json(bucket, key(r, 'plan.json'))
    if p is None or p['pipeline_version'] != VERSION or p['job_id'] != r['job_id']:
        raise ValueError('Missing or incompatible frozen plan')
    if args.mode == 'download':
        if args.shard is None:
            raise ValueError('Missing shard')
        download(bucket, r, p, args.shard)
    else:
        finish(bucket, r, p)


if __name__ == '__main__':
    main()
