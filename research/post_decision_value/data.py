"""Bounded, offline, hash-reconciled source reads. No download side effects."""
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from trade_ordering import sorted_raw_futures
from .engine import Trade
from .accounting import Instrument

FLAGS = ('block_trade_id', 'block_rfq_id', 'combo_trade_id', 'combo_id', 'block_trade_leg_count')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_ms(text):
    return int(datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()*1000)


def load_archive(root, dates, *, byte_cap=8_000_000, row_cap=100000):
    root = Path(root)
    meta = json.loads((root/'specification.json').read_text())
    coverage = {Path(r['path']).name: r for r in json.loads((root/'input_coverage.json').read_text())}
    receipts = {r['sha256']: r for r in json.loads((root/'source_receipts.json').read_text())}
    instruments = {s: Instrument(s, t) for s, t in zip(meta['symbols'], meta['expiry'])}
    files, trades, bytes_read, rows = [], [], 0, 0
    for date in dates:
        for symbol in instruments:
            path = root/'inputs'/f'{date}-{symbol}.jsonl.gz'
            if not path.exists():
                raise ValueError(f'Missing source {path.name}')
            expected = coverage[path.name]
            n = path.stat().st_size
            bytes_read += n
            if bytes_read > byte_cap:
                raise ValueError('Bounded compressed input byte cap')
            digest = sha(path)
            if digest != expected['sha256'] or digest not in receipts or n != receipts[digest]['bytes']:
                raise ValueError('Source receipt/hash/size mismatch')
            ordinary, raw_count, first, last = 0, 0, None, None
            # Existing repo sequence validation and deterministic timestamp ordering.
            for raw in sorted_raw_futures(path):
                rows += 1
                if rows > row_cap:
                    raise ValueError('Bounded input row cap')
                r = json.loads(raw)
                if r['instrument_name'] != symbol:
                    raise ValueError('Instrument identity mismatch')
                first = r['timestamp'] if first is None else min(first, r['timestamp'])
                last = r['timestamp'] if last is None else max(last, r['timestamp'])
                raw_count += 1
                valid = not any(r.get(f) for f in FLAGS)
                ordinary += valid
                if r['direction'] not in ('buy', 'sell') or min(r['price'], r['index_price'], r['amount']) <= 0:
                    raise ValueError('Missing native trade fields')
                trades.append(Trade(r['timestamp'], symbol, r['price'], r['amount'], r['direction'],
                                    str(r['trade_id']), r['index_price'], executable=valid, source_time=r['timestamp']))
            if raw_count != expected['raw_rows'] or ordinary != expected['ordinary_rows']:
                raise ValueError('Source row-count mismatch')
            files.append(dict(file=path.name, sha256=digest, bytes=n, raw_rows=raw_count,
                              ordinary_rows=ordinary, first_ms=first, last_ms=last,
                              source_uri='gs://keep-and-lease-market-data/'+receipts[digest]['key']))
    raw_seeds = json.loads((root/'seeds.json').read_text())
    seeds = [Trade(r['timestamp'], s, r['price'], r['amount'], r['direction'], str(r['trade_id']), r['index_price']) for s, r in raw_seeds.items()]
    manifest = dict(files=files, metadata={n: sha(root/n) for n in ('specification.json','seeds.json','source_receipts.json','input_coverage.json')},
                    instruments={s: asdict(i) for s,i in instruments.items()}, native_amount='USD notional',
                    hypothetical_linear_capacity='native USD amount / print price', source_payoff='inverse',
                    mode='counterfactual linear on inverse-source tape', ordering='timestamp then symbol then trade id; sequence verified per daily object',
                    no_quote_depth=True, spot_execution='disabled', settlement_evidence='not present',
                    bytes_read=bytes_read, raw_rows=rows, coverage_claim='Only the explicitly listed cached objects were verified; no fresh full-archive inventory')
    return instruments, sorted(trades, key=lambda t: (t.time, t.symbol, int(t.identifier))), seeds, manifest


def split_blocks(dates, trades, seeds, *, offset_minutes=60, duration_minutes=60):
    if len(dates) < 6 or dates != sorted(set(dates)):
        raise ValueError('At least six distinct chronological blocks required')
    blocks = []
    n = len(dates)
    for k, date in enumerate(dates):
        start = utc_ms(date+'T00:00:00Z') + offset_minutes*60000
        end = start + duration_minutes*60000
        prior = {s.symbol: s for s in seeds if s.time < start-10000}
        for tr in trades:
            if tr.time < start-10000:
                prior[tr.symbol] = tr
        tape = [t for t in trades if start <= t.time <= end]
        if not tape or len(prior) != 2:
            raise ValueError('Incomplete decision support/seeds')
        split = 'train' if k < n-4 else 'validation' if k < n-2 else 'test'
        blocks.append(dict(id=date, start=start, end=end, label_end=end, split=split, seeds=list(prior.values()), tape=tape))
    validate_splits(blocks)
    return blocks


def validate_splits(blocks):
    seen = set()
    previous_end = -1
    order = {'train':0, 'validation':1, 'test':2}
    previous_split = -1
    for block in sorted(blocks, key=lambda b:b['start']):
        if block['id'] in seen or block['start'] <= previous_end or block['label_end'] < block['end']:
            raise ValueError('Duplicate block or overlapping label tail')
        if order[block['split']] < previous_split:
            raise ValueError('Nonchronological split')
        seen.add(block['id'])
        previous_end, previous_split = block['label_end'], order[block['split']]
