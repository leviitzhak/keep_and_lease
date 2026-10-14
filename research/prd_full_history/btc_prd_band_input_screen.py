"""Read-only raw-data preflight; not the PRD portfolio strategy or a P&L replay.

Usage: python docs/research/btc_prd_band_input_screen.py --sep-dec ROOT
       --dec-mar ROOT --output REPORT.json

Uses previously downloaded data only. No exchange or network operations.
"""
import argparse
import calendar
import gzip
import hashlib
import heapq
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DAY = 86400000
YEAR = 365 * DAY
FLAGS = ('block_trade_id', 'block_rfq_id', 'combo_trade_id', 'combo_id',
         'block_trade_leg_count')


def ms(s):
    return int(datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp() * 1000)


def stamp(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).isoformat()


def minus_months(t, n):
    d = datetime.fromtimestamp(t / 1000, timezone.utc)
    month = d.year * 12 + d.month - 1 - n
    year, m = divmod(month, 12)
    return int(d.replace(year=year, month=m+1,
                         day=min(d.day, calendar.monthrange(year, m+1)[1]))
               .timestamp() * 1000)


def scan(files, symbol, expiry, start, end):
    """Count hypothetical standing-limit crossings, never label them fills.

    Each symbol is an independent experiment with zero-cost spot proxy APR.
    A trade-attached index observation reaches decisions after 500 ms; its
    replacement limit arrives 500 ms later. The limit uses maturity at decision.
    No same-arrival-timestamp fill; old quote stays effective through the tie.
    Predetermined GTD cancels at observation+30s+2*delay or 3-month cutoff.
    Limits are hypothetical: no inventory, capital or volume is consumed.
    """
    counts = Counter()
    hashes = []
    seen = set()
    queue = []
    active = None
    last_available = start - 1
    serial = 0
    delay = 500
    cutoff = minus_months(expiry, 3)
    first = last = None
    max_age = 0
    for path, expected in sorted(files, key=lambda x: x[0].name):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected, (path.name, 'hash mismatch')
        hashes.append(dict(file=path.name, sha256=digest))
        with gzip.open(path, 'rt') as f:
            for line in f:
                r = json.loads(line)
                assert r['instrument_name'] == symbol
                t = int(r['timestamp'])
                assert start <= t < end, (path.name, t)
                counts['raw_rows'] += 1
                key = str(r['trade_id'])
                assert key not in seen, (symbol, key, 'duplicate')
                seen.add(key)
                if any(r.get(k) for k in FLAGS):
                    counts['excluded_flagged'] += 1
                    continue
                counts['ordinary_rows'] += 1
                first = t if first is None else min(first, t)
                last = t if last is None else max(last, t)
                if t < last_available:
                    counts['timestamp_reversals'] += 1
                # Conservative sequence-prefix availability, preserving file order.
                available = max(t, last_available)
                last_available = available
                while queue and queue[0][0] < available:
                    _, _, active = heapq.heappop(queue)
                if available <= cutoff:
                    counts['rows_at_least_3_calendar_months'] += 1
                if active and available < active['expires'] and available > active['arrival']:
                    assert active['observed_available'] + 2 * delay < available
                    max_age = max(max_age, available - active['observed_available'])
                    p = float(r['price'])
                    if p > active['sell']:
                        counts['opening_sell_strict_through_prints'] += 1
                        counts['opening_sell_crossing_face_usd'] += float(r['amount'])
                    if p < active['buy']:
                        counts['closing_buy_strict_through_prints'] += 1
                        counts['closing_buy_crossing_face_usd'] += float(r['amount'])
                decision = available + delay
                arrival = decision + delay
                if decision <= cutoff and arrival < cutoff:
                    import math
                    spot = float(r['index_price'])
                    tau = (expiry - decision) / YEAR
                    quote = dict(
                        observed_available=available, arrival=arrival,
                        expires=min(available + 30000 + 2*delay, cutoff),
                        sell=math.ceil(spot*(1+tau*.02)/2.5 - 1e-10)*2.5,
                        buy=math.floor(spot*(1+tau*.01)/2.5 + 1e-10)*2.5)
                    serial += 1
                    heapq.heappush(queue, (arrival, serial, quote))
    return dict(symbol=symbol, expiry=stamp(expiry), counts=dict(counts),
                first_ordinary_trade=stamp(first), last_ordinary_trade=stamp(last),
                latest_3_month_decision=stamp(cutoff),
                maximum_reference_age_at_screen_ms=max_age, files=hashes)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sep-dec', type=Path, required=True)
    p.add_argument('--dec-mar', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    old = json.loads((a.sep_dec/'summary.json').read_text())
    new = json.loads((a.dec_mar/'specification.json').read_text())
    coverage = json.loads((a.dec_mar/'input_coverage.json').read_text())
    groups = [dict(name='Sep26_Dec26', start=ms(old['config']['start']),
                   end=ms(old['config']['end_exclusive']),
                   legs=[dict(symbol=r['instrument'], expiry=ms(r['expiry_utc']),
                              files=[(a.sep_dec/r['raw_path'], r['raw_sha256'])])
                         for r in old['instruments']]),
              dict(name='Dec26_Mar27', start=new['start'], end=new['end'],
                   legs=[dict(symbol=s, expiry=e,
                              files=[(a.dec_mar/'inputs'/Path(r['path']).name, r['sha256'])
                                     for r in coverage if s in r['path']])
                         for s, e in zip(new['symbols'], new['expiry'])])]
    results = []
    for g in groups:
        start, end = g['start'], g['end']
        expiries = [r['expiry'] for r in g['legs']]
        far, near = max(expiries), min(expiries)
        gap = far - near
        eligible_until = min(far - gap / .25, minus_months(near, 3))
        seconds = max(0, min(end, eligible_until) - start) / 1000
        rows = [scan(r['files'], r['symbol'], r['expiry'], start, end) for r in g['legs']]
        result = dict(name=g['name'], start=stamp(start), end_exclusive=stamp(end),
                      expiry_gap_days=gap/DAY,
                      separation_ratio_start=gap/(far-start),
                      separation_ratio_end_limit=gap/(far-end),
                      eligible_pair_seconds=seconds,
                      pair_eligibility_latest_time=stamp(eligible_until),
                      instrument_results=rows)
        results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k != 'instrument_results'}), flush=True)
        for r in rows:
            print(json.dumps(dict(symbol=r['symbol'], counts=r['counts'])), flush=True)
    report = dict(
        status='raw_data_preflight_only_not_portfolio_replay',
        method=dict(proxy_expense_ratio=0, proxy_mtm_surcharge_apr=0,
                    opening_prd=.02, closing_prd=.01, tick_size_usd=2.5,
                    observation_to_decision_ms=500, decision_to_market_ms=500,
                    quote_gtd_after_observation_ms=31000,
                    proxy_spot_reference='trade-attached index, per future independently',
                    counted_objects='hypothetical strict-through crossing prints, not fills',
                    warning='No capital, position size, paired completion, funding, fees or P&L simulated; independent opening and closing quote screens.'),
        datasets=results)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
