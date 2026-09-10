"""Bounded, auditable reconciliation of Deribit time/sequence history responses."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3

POLICY = 'sequence-envelope-v1'
PAGE = 900


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def download_future(api, symbol, info, lo, hi, out):
    """Retain raw sequence order; a separate converter sorts reported event time.

    Coverage is a validated contiguous sequence envelope anchored by both time
    endpoints, extended through a full neighboring sequence page. This is an
    explicit bounded-history assumption, not proof against arbitrary backdating.
    """
    out = Path(out)
    evidence = out / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    path = out / (symbol + '.jsonl.gz')
    meta_path = out / (symbol + '.meta.json')
    responses_path = evidence / (symbol + '-responses.jsonl.gz')
    ledger_path = evidence / (symbol + '-anomalies.jsonl.gz')
    db_path = out / (symbol + '.sqlite')
    # This database is only a reproducible download scratch index.
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.execute('PRAGMA cache_size=-8192')
    db.execute('CREATE TABLE trades(seq INTEGER PRIMARY KEY,id TEXT UNIQUE,ts INTEGER,raw TEXT,time_seen INTEGER,seq_seen INTEGER)')
    counts = {}
    max_reversal = 0
    requests = 0
    with gzip.open(responses_path, 'wt') as responses, gzip.open(ledger_path, 'wt') as ledger:
        def anomaly(kind, **details):
            value = dict(policy=POLICY, instrument=symbol, kind=kind, status='unresolved', **details)
            value['anomaly_id'] = hashlib.sha256(canonical(value).encode()).hexdigest()
            ledger.write(canonical(value)+'\n')
            counts[kind] = counts.get(kind, 0)+1

        def request(method, **params):
            nonlocal requests
            requests += 1
            if requests > 10000:
                raise ValueError('Bounded Deribit request budget exceeded')
            params = dict(instrument_name=symbol, **params)
            result = api(method, **params)
            responses.write(canonical(dict(method=method, parameters=params,
                retrieved_at=datetime.now(timezone.utc).isoformat(), result=result))+'\n')
            responses.flush()
            return result

        def add(row, origin):
            if row.get('instrument_name', symbol) != symbol:
                raise ValueError('Unexpected instrument in history response')
            seq, identifier, ts = int(row['trade_seq']), str(row['trade_id']), int(row['timestamp'])
            raw = canonical(row)
            previous = db.execute('SELECT raw FROM trades WHERE seq=? OR id=?', (seq,identifier)).fetchall()
            if previous:
                if len(previous) != 1 or previous[0][0] != raw:
                    anomaly('conflicting_record', record=row)
                    raise ValueError(f'Conflicting versions of {symbol} sequence {seq}')
                db.execute('UPDATE trades SET '+origin+'_seen=1 WHERE seq=?', (seq,))
            else:
                db.execute('INSERT INTO trades VALUES(?,?,?,?,?,?)',
                           (seq,identifier,ts,raw,int(origin=='time'),int(origin=='seq')))

        def time_query(a, b, direction):
            result = request('get_last_trades_by_instrument_and_time',
                             start_timestamp=a, end_timestamp=b, count=1000, sorting=direction)
            for row in result['trades']:
                add(row, 'time')
            return result['trades']

        seed_rows = request('get_last_trades_by_instrument_and_time', end_timestamp=lo-1,
                            count=1000, sorting='desc')['trades']
        seed_rows = [r for r in seed_rows if r['timestamp'] < lo]
        seed = max(seed_rows, key=lambda r:r['trade_seq'], default=None)
        first = time_query(lo, hi-1, 'asc')
        tail = time_query(lo, hi-1, 'desc')
        inside = [r for r in first+tail if lo <= r['timestamp'] < hi]
        anchors = [r['trade_seq'] for r in inside]
        if seed:
            anchors.append(seed['trade_seq']+1)
        if not anchors:
            raise ValueError('No sequence anchor; empty-day coverage requires investigation')
        lower, upper = max(1,min(anchors)-PAGE), max(anchors)
        # Backtrack if the lower neighboring page still contains this day's prints.
        while True:
            result = request('get_last_trades_by_instrument', start_seq=lower,
                             end_seq=lower+PAGE-1, count=1000, sorting='asc')
            rows = sorted((r for r in result['trades'] if lower <= r['trade_seq'] < lower+PAGE), key=lambda r:r['trade_seq'])
            if rows and [r['trade_seq'] for r in rows] != list(range(lower,rows[-1]['trade_seq']+1)):
                raise ValueError(f'Sequence gap at lower boundary: {symbol}')
            for row in rows: add(row, 'seq')
            if lower == 1 or not any(lo <= r['timestamp'] < hi for r in rows):
                break
            lower = max(1, lower-PAGE)
        cursor, last_seq = lower, None
        while True:
            result = request('get_last_trades_by_instrument', start_seq=cursor,
                             end_seq=cursor+PAGE-1, count=1000, sorting='asc')
            rows = sorted((r for r in result['trades'] if cursor <= r['trade_seq'] < cursor+PAGE), key=lambda r:r['trade_seq'])
            if not rows:
                if cursor <= upper:
                    raise ValueError(f'Empty sequence page before known tail: {symbol} {cursor} <= {upper}')
                # No history beyond this cursor; keep the empty response as evidence.
                break
            if [r['trade_seq'] for r in rows] != list(range(cursor,rows[-1]['trade_seq']+1)):
                raise ValueError(f'Sequence gap in {symbol} at {cursor}')
            for row in rows: add(row, 'seq')
            last_seq = rows[-1]['trade_seq']
            if cursor > upper and len(rows) == PAGE and not any(lo <= r['timestamp'] < hi for r in rows):
                break
            cursor = last_seq+1
        # All time-discovered records inside the day must also be covered by the
        # sequence envelope; endpoint extras are kept, but gaps are never waived.
        if db.execute('SELECT COUNT(*) FROM trades WHERE ts>=? AND ts<? AND seq_seen=0',(lo,hi)).fetchone()[0]:
            raise ValueError('Time endpoint found records outside verified sequence envelope')
        selected = db.execute('SELECT MIN(seq),MAX(seq),COUNT(*) FROM trades WHERE ts>=? AND ts<?',(lo,hi)).fetchone()
        expected_tail = max((r['trade_seq'] for r in tail if lo<=r['timestamp']<hi), default=None)
        if selected[1] != expected_tail:
            anomaly('tail_endpoint_disagreement', time_last_seq=expected_tail, union_last_seq=selected[1],
                    records=[json.loads(r[0]) for r in db.execute('SELECT raw FROM trades WHERE seq IN (?,?)',(expected_tail,selected[1]))])
        # Only compare time membership in the actually returned head/tail sequence
        # spans. The unqueried middle of the day is not an endpoint disagreement.
        spans = [(min(r['trade_seq'] for r in v),max(r['trade_seq'] for r in v)) for v in (first,tail) if v]
        for seq, ts, raw in db.execute('SELECT seq,ts,raw FROM trades WHERE seq_seen=1 AND time_seen=0 AND ts>=? AND ts<?',(lo,hi)):
            if any(a<=seq<=b for a,b in spans) or seq==selected[1] and seq!=expected_tail:
                anomaly('sequence_endpoint_only', record=json.loads(raw))
        previous = None
        raw_bytes = 0
        with gzip.open(path.with_suffix('.part'), 'wt') as stream:
            for seq, ts, raw in db.execute('SELECT seq,ts,raw FROM trades ORDER BY seq'):
                row = json.loads(raw)
                if previous and ts < previous['timestamp'] and (lo<=ts<hi or lo<=previous['timestamp']<hi):
                    reversal = previous['timestamp']-ts
                    max_reversal = max(max_reversal,reversal)
                    anomaly('timestamp_reversal', reversal_ms=reversal, previous=previous, record=row)
                previous = row
                if lo <= ts < hi:
                    stream.write(raw+'\n'); raw_bytes += len((raw+'\n').encode())
        path.with_suffix('.part').replace(path)
        # Prefer the most recent reported-time causal mark in the captured prefix.
        prior = db.execute('SELECT raw FROM trades WHERE ts<? ORDER BY ts DESC,seq DESC LIMIT 1',(lo,)).fetchone()
        if prior: seed = json.loads(prior[0])
        boundary = db.execute('SELECT MAX(ts) FROM trades WHERE seq<?',(selected[0],)).fetchone()[0]
        summary = dict(policy=POLICY, sequence_first=lower, sequence_last=last_seq,
                       selected_first_seq=selected[0], selected_last_seq=selected[1],
                       prefix_max_timestamp_ms=boundary, requests=requests,
                       counts=counts, max_reversal_ms=max_reversal,
                       coverage_assumption='Contiguous time-anchored sequence envelope with neighboring full-page guard; arbitrary backdating outside the envelope is not proven absent')
    last_ms = db.execute('SELECT MAX(ts) FROM trades WHERE ts>=? AND ts<?',(lo,hi)).fetchone()[0]
    db.close(); db_path.unlink()
    def file_meta(p):
        with p.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        return dict(path=str(p.relative_to(out)), sha256=digest, bytes=p.stat().st_size)
    meta = dict(path=path.name, sha256=file_meta(path)['sha256'], rows=selected[2],
                jsonl_bytes=raw_bytes,gzip_bytes=path.stat().st_size,seed=seed,
                start_ms=lo,end_ms=hi,expiry=info['expiration_timestamp'],
                last_seq=selected[1],verified_last_seq=selected[1],
                last_ms=last_ms,
                discrepancy=summary,evidence_files=[file_meta(responses_path),file_meta(ledger_path)])
    meta_path.write_text(json.dumps(meta,indent=2)+'\n')
    return meta
