"""Measure verified trade-tape workload; this does not simulate a market."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from btc_prd_band_input_screen import FLAGS, DAY, stamp


def nearest_rank(values, probability):
    import math
    ordered = sorted(values)
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads((args.inputs / 'specification.json').read_text())
    sources = json.loads((args.inputs / 'input_coverage.json').read_text())
    times, daily, seconds = defaultdict(list), Counter(), Counter()
    raw = excluded = 0
    source_hashes = []
    seen = set()
    for source in sources:
        path = args.inputs / 'inputs' / Path(source['path']).name
        payload = path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == source['sha256'], path
        source_hashes.append(source['sha256'])
        for line in gzip.decompress(payload).splitlines():
            row = json.loads(line)
            raw += 1
            if any(row.get(flag) for flag in FLAGS):
                excluded += 1
                continue
            symbol, ts = row['instrument_name'], row['timestamp']
            assert symbol in spec['symbols'] and isinstance(ts, int)
            assert spec['start'] <= ts < spec['end']
            assert min(row['price'], row['index_price'], row['amount']) > 0
            key = (symbol, row['trade_id'])
            assert key not in seen
            seen.add(key)
            times[symbol].append(ts)
            daily[ts // DAY] += 1
            seconds[ts // 1000] += 1
    instruments = {}
    for symbol, timestamps in sorted(times.items()):
        timestamps.sort()
        counts = Counter(timestamps)
        positive_gaps = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
        instruments[symbol] = {
            'ordinary_trades': len(timestamps),
            'distinct_exchange_milliseconds': len(counts),
            'trades_in_same_instrument_millisecond_batches': sum(n for n in counts.values() if n > 1),
            'max_trades_in_one_exchange_millisecond': max(counts.values()),
            'positive_interarrival_ms_p50': nearest_rank(positive_gaps, .5),
            'positive_interarrival_ms_p95': nearest_rank(positive_gaps, .95),
            'max_interarrival_ms': max(positive_gaps),
        }
    ordinary = sum(map(len, times.values()))
    assert ordinary + excluded == raw
    daily_counts = [daily[day] for day in range(spec['start'] // DAY, spec['end'] // DAY)]
    report = {
        'status': 'DESCRIPTIVE_TRADE_WORKLOAD_NOT_A_SIMULATOR_BENCHMARK',
        'start_utc': stamp(spec['start']), 'end_exclusive_utc': stamp(spec['end']),
        'calendar_days': (spec['end'] - spec['start']) / DAY,
        'verified_source_files': len(sources), 'raw_trades': raw,
        'excluded_flagged_trades': excluded, 'ordinary_trades': ordinary,
        'instruments': instruments,
        'ordinary_trades_per_day_mean': ordinary / ((spec['end'] - spec['start']) / DAY),
        'ordinary_trades_per_day_p95': nearest_rank(daily_counts, .95),
        'ordinary_trades_per_day_max': max(daily_counts),
        'ordinary_trades_in_busiest_second': max(seconds.values()),
        'all_to_all_individual_trade_deliveries': {str(n): n * ordinary for n in (10, 100, 1000)},
        'limitations': [
            'Delivery counts assume every agent subscribes to both instruments and every individual trade.',
            'These counts exclude book updates, agent wakeups, order commands, fills, cancellations and acknowledgments.',
            'Trade timestamps and identifiers do not identify cross-instrument matching-engine order or local receipt latency.',
            'No historical order book, queue positions or cancellation stream are present.',
        ],
        'source_manifest_sha256': hashlib.sha256((args.inputs / 'input_coverage.json').read_bytes()).hexdigest(),
        'sorted_source_hashes_sha256': hashlib.sha256('\n'.join(sorted(source_hashes)).encode()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
