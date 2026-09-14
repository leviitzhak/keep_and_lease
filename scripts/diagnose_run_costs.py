#!/usr/bin/env python3
"""Read-only Keep & Lease trade-replay cost audit, run by the owner in Cloud Shell.

No GitHub actions, uploads, permission changes, tokens exported, or backtest reruns.
Requires Python 3.10+ and an authenticated gcloud CLI. Only local report files are
written. Default: inspect the first complete UTC day; use --day and --days to
select another period. All times below use half-open UTC days [00:00, 24:00).

Google CLI read operations:
https://docs.cloud.google.com/sdk/gcloud/reference/storage/objects/describe
https://docs.cloud.google.com/sdk/gcloud/reference/storage/cat
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import gzip
import hashlib
import heapq
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

UTC = dt.timezone.utc
EPOCH = dt.datetime(1970, 1, 1, tzinfo=UTC)
DAY_US = 86_400_000_000
MIB = 1024 * 1024
CHUNK_RE = re.compile(r'[a-z][a-z0-9_]*/[0-9]{6}\.jsonl\.gz\Z')


def us(value: str) -> int:
    d = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    delta = d.astimezone(UTC) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def iso(t: int) -> str:
    return (EPOCH + dt.timedelta(microseconds=t)).isoformat().replace('+00:00', 'Z')


def number(value: Any) -> float | None:
    if value is None or value == '':
        return None
    x = float(value)
    if not math.isfinite(x):
        raise ValueError('A stored numeric field is not finite')
    return x


def near(a: float, b: float, *, absolute: float = 1e-7) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=absolute)


class Reader:
    """Known run objects only. Downloads are capped; GCS generations are pinned."""
    def __init__(self, run_id: str, budget: int, local: Path | None = None):
        self.root = f'gs://keep-and-lease-results/jobs/{run_id}/'
        self.local, self.budget, self.bytes_read = local, budget, 0
        self.receipts: dict[str, dict] = {}
        self.cache: collections.OrderedDict[str, bytes] = collections.OrderedDict()
        if local is None and not shutil.which('gcloud'):
            raise RuntimeError('Run in authenticated Google Cloud Shell: gcloud is missing')

    @staticmethod
    def _command(args: list[str], output=None):
        p = subprocess.run(['gcloud', '--project=keep-and-lease', '--quiet', *args],
                           stdout=output if output is not None else subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=180, check=False)
        if p.returncode:
            # Do not print credentials or HTTP traces. The owner can run gcloud
            # storage objects describe manually when diagnosing their own access.
            raise RuntimeError('A read-only gcloud storage command failed. Check your '
                               'active Cloud Shell account and object access. No IAM was changed.')
        return p.stdout

    def get(self, name: str, *, cap: int = 64 * MIB) -> bytes:
        if name not in ('result.json.gz', 'audit/manifest.json') and not (
                name.startswith('audit/') and CHUNK_RE.fullmatch(name[6:])):
            raise ValueError('Unexpected run object path')
        if name in self.cache:
            self.cache.move_to_end(name)
            return self.cache[name]
        if self.local is not None:
            path = self.local / name
            size, generation = path.stat().st_size, 'local'
        else:
            metadata = json.loads(self._command(
                ['storage', 'objects', 'describe', self.root + name, '--raw', '--format=json']))
            size, generation = int(metadata['size']), str(metadata['generation'])
        if size > cap or self.bytes_read + size > self.budget:
            raise RuntimeError('Read budget exceeded. No partial report is certified. '
                               'Choose fewer days or explicitly raise --max-read-mib.')
        if self.local is not None:
            data = path.read_bytes()
        else:
            with tempfile.TemporaryFile() as stream:
                self._command(['storage', 'cat', self.root + name + '#' + generation], stream)
                stream.seek(0)
                data = stream.read(cap + 1)
        if len(data) != size or len(data) > cap:
            raise ValueError('Stored object length changed or exceeded limit')
        self.bytes_read += len(data)
        self.receipts[name] = {'generation': generation, 'bytes': len(data),
                               'sha256': hashlib.sha256(data).hexdigest()}
        # Cache at most four small chunks, not a full history or large result.
        if len(data) <= 16 * MIB and name.endswith('.jsonl.gz'):
            self.cache[name] = data
            while len(self.cache) > 4:
                self.cache.popitem(last=False)
        return data

    def chunk(self, entry: dict):
        name = entry['object']
        if not CHUNK_RE.fullmatch(name):
            raise ValueError('Audit manifest contains an unexpected object name')
        data = self.get('audit/' + name, cap=16 * MIB)
        if hashlib.sha256(data).hexdigest() != entry['compressed_sha256']:
            raise ValueError('Compressed audit checksum mismatch')
        if len(data) != int(entry['compressed_bytes']):
            raise ValueError('Compressed audit size mismatch')
        digest, count, size = hashlib.sha256(), 0, 0
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            while True:
                line = stream.readline(16 * MIB + 1)
                if not line:
                    break
                size += len(line)
                if size > 16 * MIB:
                    raise ValueError('Audit chunk expands beyond the 16 MiB bound')
                count += 1
                digest.update(line)
                yield json.loads(line)
        if (count != int(entry['rows']) or size != int(entry['uncompressed_bytes'])
                or digest.hexdigest() != entry['sha256']):
            raise ValueError('Audit row count, uncompressed size or checksum mismatch')


def result_json(data: bytes) -> dict:
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        raw = stream.read(256 * MIB + 1)
    if len(raw) > 256 * MIB:
        raise ValueError('Result expands beyond the 256 MiB diagnostic bound')
    return json.loads(raw)


def configured_fee(result: dict) -> float | None:
    p = dict(result.get('parameters') or {})
    nested = p.get('commodity_parameters', {})
    if isinstance(nested, str):
        nested = json.loads(nested)
    if isinstance(nested, dict):
        p.update(nested.get('btc') or {})
    original = result.get('parameters') or {}
    p.update({k[5:]: v for k, v in original.items() if k.startswith('btc__')})
    # Missing means unknown, not zero. The independent requested-rate check
    # remains available via --fee-bps even for old parameter documents.
    return number(p.get('trading_fee_bps'))


def anchors(reader: Reader, entries: list[dict], boundaries: list[int]) -> list[dict]:
    """Nearest valuation at/before each boundary, retaining actual timestamps."""
    if not entries:
        raise ValueError('The run has no stored valuation audit')
    picked: dict[int, dict] = {}
    for t in boundaries:
        candidates = [e for e in entries if us(e['start']) <= t]
        if not candidates:
            # No prior valuation at run initialization. The caller supplies an
            # explicit synthetic origin from the recorded initial holding.
            continue
        entry = max(candidates, key=lambda e: (us(e['start']), int(e['index'])))
        best = None
        for row in reader.chunk(entry):  # exhaust the chunk: verify whole checksum
            if int(row['us']) <= t and (best is None or row['us'] >= best['us']):
                best = row
        if best is None:
            raise ValueError('Manifest boundary metadata does not match valuation rows')
        picked[int(best['us'])] = best
    return [picked[t] for t in sorted(picked)]


def new_stats() -> dict:
    return {'fills': 0, 'buys': 0, 'sells': 0, 'buy_btc': 0.0, 'sell_btc': 0.0,
            'buy_notional_usd': 0.0, 'sell_notional_usd': 0.0,
            'traded_notional_usd': 0.0, 'recorded_fees_usd': 0.0,
            'expected_fees_usd': 0.0, 'fee_mismatches': 0,
            'max_single_fill_fee_error_usd': 0.0, 'direction_changes': 0,
            'direction_changes_within_60s': 0}


def add_fill(stats: dict, signed: float, price: float, fee: float,
             rate: float, reversal: bool, fast_reversal: bool):
    notional = abs(signed) * price
    expected = notional * rate / 10000
    stats['fills'] += 1
    side = 'buy' if signed > 0 else 'sell'
    stats[side + 's'] += 1
    stats[side + '_btc'] += abs(signed)
    stats[side + '_notional_usd'] += notional
    stats['traded_notional_usd'] += notional
    stats['recorded_fees_usd'] += fee
    stats['expected_fees_usd'] += expected
    stats['fee_mismatches'] += int(not near(fee, expected))
    stats['max_single_fill_fee_error_usd'] = max(
        stats['max_single_fill_fee_error_usd'], abs(fee - expected))
    stats['direction_changes'] += int(reversal)
    stats['direction_changes_within_60s'] += int(fast_reversal)


def analyse(event_rows, checkpoints: list[dict], lo: int, hi: int,
            fee_bps: float, sample_limit: int = 100) -> dict:
    """Read event audit once, reconcile boundary states, retain bounded examples."""
    baseline = checkpoints[0]
    first_us, last_us = int(baseline['us']), int(checkpoints[-1]['us'])
    units = dict(baseline['units'])
    base_fee = number(baseline.get('fees_usd'))
    base_turnover = number(baseline.get('turnover_usd'))
    cumulative_fee = cumulative_turnover = 0.0
    next_anchor = 1
    last_event_us = None
    previous_fill: dict[str, tuple[int, int]] = {}
    orders: dict[tuple[str, int], dict] = {}
    daily, instruments = {}, {}
    totals = new_stats()
    first_fills, largest_fills, reversals = [], [], []
    order_count = cancellations = settlements = 0
    unmatched_order_fills = invalid_orders = negative_holdings = 0
    cumulative_checks = []
    filled_index = 0

    def checkpoint(row):
        def check(stored, initial, accumulated):
            if stored is None or initial is None:
                return {'status': 'unavailable'}
            actual = float(stored) - initial
            return {'status': 'passed' if near(actual, accumulated) else 'FAILED',
                    'recorded_change': actual, 'sum_of_fills': accumulated,
                    'difference': actual - accumulated}
        expected_units = row.get('units', {})
        max_unit_error = max((abs(units.get(s, 0) - expected_units.get(s, 0))
                              for s in set(units) | set(expected_units)), default=0)
        cumulative_checks.append({
            'from': iso(first_us), 'to': iso(int(row['us'])),
            'interval_convention': '(from, to]; compared with inclusive valuation snapshots',
            'fee_counter': check(row.get('fees_usd'), base_fee, cumulative_fee),
            'turnover_counter': check(row.get('turnover_usd'), base_turnover, cumulative_turnover),
            'inventory': {'status': 'passed' if max_unit_error < 1e-9 else 'FAILED',
                          'max_quantity_difference_btc': max_unit_error}})

    for event in event_rows:
        t, kind = int(event['us']), event['kind']
        if last_event_us is not None and t < last_event_us:
            raise ValueError('Event audit is not chronological')
        last_event_us = t
        # Complete all equal-time events before checking inclusive snapshots.
        while next_anchor < len(checkpoints) and int(checkpoints[next_anchor]['us']) < t:
            checkpoint(checkpoints[next_anchor]); next_anchor += 1
        if t < first_us:
            continue
        symbol = event.get('symbol')
        if kind == 'order':
            delta = float(event['signed_btc'])
            key = (symbol, int(event['order_id']))
            orders[key] = {'delta': delta, 'filled': 0.0,
                           'target_from_order': units.get(symbol, 0.0) + delta}
            if lo <= t < hi:
                order_count += 1
        elif kind == 'order_end':
            orders.pop((symbol, int(event['order_id'])), None)
            if lo <= t < hi and float(event.get('remainder_btc') or 0) > 1e-14:
                cancellations += 1
        elif kind == 'settlement' and t > first_us:
            units[symbol] = 0.0
            if lo <= t < hi:
                settlements += 1
        elif kind == 'fill' and t > first_us:
            signed, price, fee = (float(event[k]) for k in ('signed_btc', 'price', 'fee_usd'))
            if not all(math.isfinite(x) for x in (signed, price, fee)) or price <= 0:
                raise ValueError('Malformed fill')
            before = units.get(symbol, 0.0)
            units[symbol] = before + signed
            cumulative_fee += fee
            cumulative_turnover += abs(signed) * price
            previous = previous_fill.get(symbol)
            sign = 1 if signed > 0 else -1
            reversal = previous is not None and previous[0] != sign
            seconds = (t - previous[1]) / 1e6 if previous else None
            fast = reversal and seconds <= 60
            order = orders.get((symbol, int(event['order_id'])))
            if order:
                order['filled'] += abs(signed)
            if lo <= t < hi:
                if units[symbol] < -1e-9:
                    negative_holdings += 1
                if order is None:
                    unmatched_order_fills += 1
                elif order['delta'] * signed < 0 or order['filled'] > abs(order['delta']) + 1e-9:
                    invalid_orders += 1
                day = iso(t)[:10]
                add_fill(totals, signed, price, fee, fee_bps, reversal, fast)
                add_fill(daily.setdefault(day, new_stats()), signed, price, fee, fee_bps, reversal, fast)
                add_fill(instruments.setdefault(symbol, new_stats()), signed, price, fee, fee_bps, reversal, fast)
                record = {'time_utc': iso(t), 'symbol': symbol, 'order_id': event['order_id'],
                          'quantity_before_btc': before, 'signed_fill_btc': signed,
                          'quantity_after_btc': units[symbol], 'price_usd': price,
                          'traded_notional_usd': abs(signed) * price, 'fee_usd': fee,
                          'target_reconstructed_from_order_btc': order['target_from_order'] if order else None,
                          'opposite_to_previous_fill': reversal,
                          'seconds_since_previous_fill': seconds}
                if len(first_fills) < sample_limit:
                    first_fills.append(record)
                if fast and len(reversals) < sample_limit:
                    reversals.append(record)
                filled_index += 1
                item = (abs(signed) * price, filled_index, record)
                if len(largest_fills) < sample_limit:
                    heapq.heappush(largest_fills, item)
                elif item[:2] > largest_fills[0][:2]:
                    heapq.heapreplace(largest_fills, item)
            previous_fill[symbol] = (sign, t)
        # A baseline includes all fills at its own timestamp; these are not
        # added again. The default complete-day window starts after baseline.
    while next_anchor < len(checkpoints):
        checkpoint(checkpoints[next_anchor]); next_anchor += 1
    # Include no-trade dates with zero fees; never confuse them with missing data.
    cursor = (lo // DAY_US) * DAY_US
    day_records = []
    while cursor < hi:
        a, b = max(cursor, lo), min(cursor + DAY_US, hi)
        d = daily.get(iso(cursor)[:10], new_stats())
        prior = [r for r in checkpoints if int(r['us']) <= a]
        opening = prior[-1] if prior else None
        nav = number(opening.get('nav_usd')) if opening else None
        d = dict(d, date_utc=iso(cursor)[:10], from_utc=iso(a), to_utc_exclusive=iso(b),
                 complete_utc_day=(b-a == DAY_US),
                 nav_reference_usd=nav,
                 nav_reference_time=iso(int(opening['us'])) if opening else None,
                 nav_reference_age_seconds=(a-int(opening['us']))/1e6 if opening else None,
                 fees_bps_of_reference_nav=10000*d['recorded_fees_usd']/nav if nav and nav > 0 else None,
                 turnover_times_reference_nav=d['traded_notional_usd']/nav if nav and nav > 0 else None)
        day_records.append(d)
        cursor += DAY_US
    for stats in [totals, *instruments.values(), *day_records]:
        stats['net_traded_btc'] = stats['buy_btc'] - stats['sell_btc']
    return {'totals': totals, 'days': day_records,
            'by_instrument': dict(sorted(instruments.items(), key=lambda kv: -kv[1]['recorded_fees_usd'])),
            'orders_submitted': order_count, 'cancelled_unfilled_remainders': cancellations,
            'settlements': settlements, 'fills_with_order_outside_inspection': unmatched_order_fills,
            'order_side_or_overfill_errors': invalid_orders,
            'negative_inventory_errors': negative_holdings,
            'boundary_reconciliations': cumulative_checks,
            'first_fills': first_fills,
            'largest_fills': [item[2] for item in sorted(largest_fills, reverse=True)],
            'first_rapid_direction_changes': reversals,
            'notes': [
                'Fees and turnover by date are summed from actual fills in half-open UTC days [00:00,24:00).',
                'Boundary checks independently compare cumulative counters and inventory over (anchor,anchor].',
                'NAV denominators use the recorded valuation at/before each boundary; its timestamp and age are shown. No interpolation.',
                'Order targets shown in examples are reconstructed from submitted deltas and inventory, not a separate replay of signals.',
                'A rapid direction change is an opposite-side fill in the same instrument within 60 seconds of its previous fill. It is an indicator, not proof of an unnecessary trade.',
                'Futures maturities are separate instruments: net exposure does not measure traded notional.',
                'Initial owned BTC and expiry settlement are not counted as fee-bearing fills unless the audit explicitly records them as fills.',
                'Correct fees do not establish that turnover is economically worthwhile.',
                'Only this selected period is audited; results do not certify uninspected days.'
            ]}


def run(args) -> dict:
    if not re.fullmatch(r'[0-9a-f]{32}', args.run_id):
        raise ValueError('Expected a 32-character lowercase saved-run ID')
    reader = Reader(args.run_id, args.max_read_mib*MIB, args.local_run_dir)
    result = result_json(reader.get('result.json.gz'))
    if result.get('result_kind') != 'btc_trade_replay':
        raise ValueError('This helper supports trade-tape replay, not daily/observed-candle results. '
                         'Use the application spreadsheet for that result type instead.')
    manifest_bytes = reader.get('audit/manifest.json')
    manifest = json.loads(manifest_bytes)
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported audit schema')
    datasets = manifest['datasets']
    valuation_entries = datasets['btc_trade_valuations']['chunks']
    event_entries = datasets['btc_trade_events']['chunks']
    summary = result['summary']
    origin, end = us(summary['start']), us(summary['end'])
    if args.day:
        day = us(args.day)
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.day):
            raise ValueError('--day must be YYYY-MM-DD')
    else:
        day = (origin // DAY_US + 1) * DAY_US
        if day + DAY_US > end:
            day = origin // DAY_US * DAY_US
    lo, hi = max(day, origin), min(day + args.days * DAY_US, end)
    if hi <= lo:
        raise ValueError('Selected UTC period does not overlap the stored run')
    boundaries = sorted({lo - 1, lo, hi} | set(range((lo//DAY_US+1)*DAY_US, hi, DAY_US)))
    checkpoints = anchors(reader, valuation_entries, boundaries)
    # For an initial partial day, initialize inventory from the actual first
    # initial_holding record rather than assuming all capital was cash.
    if not checkpoints or checkpoints[0]['us'] > lo:
        initial = None
        for row in reader.chunk(event_entries[0]):
            if row['kind'] == 'initial_holding':
                initial = row
        if initial is None or int(initial['us']) > lo:
            raise ValueError('No recorded initial holdings or valuation at the selected start')
        cap = float(result['trade_replay']['capital_usd'])
        checkpoints.insert(0, {'us': initial['us'], 'units': {'SPOT': float(initial['btc'])},
                              'fees_usd': 0.0, 'turnover_usd': 0.0, 'nav_usd': cap})
    start_scan = int(checkpoints[0]['us'])
    selected = [e for e in event_entries if us(e['end']) >= start_scan and us(e['start']) <= hi]
    # Conservative estimate includes boundary overlap and any already-read data.
    estimate = sum(int(e['compressed_bytes']) for e in selected)
    if reader.bytes_read + estimate > reader.budget:
        raise RuntimeError('Selected event chunks exceed the read budget; choose fewer days '
                           'or explicitly raise --max-read-mib.')
    print(f'Inspecting {iso(lo)} to {iso(hi)} (exclusive).', file=sys.stderr)
    print(f'Reading {len(selected)} event chunks; {estimate:,} compressed bytes in manifest. '
          'No strategy simulation is being run.', file=sys.stderr)
    def events():
        for n, entry in enumerate(selected, 1):
            for row in reader.chunk(entry):
                if start_scan <= int(row['us']) <= hi:
                    yield row
            if n % 10 == 0 or n == len(selected):
                print(f'Verified event chunks: {n}/{len(selected)}', file=sys.stderr)
    recorded_rate = configured_fee(result)
    if recorded_rate is not None and not near(recorded_rate, args.fee_bps):
        print(f'WARNING: stored effective fee is {recorded_rate:g} bps; requested test is '
              f'{args.fee_bps:g} bps. Both are recorded in the report.', file=sys.stderr)
    analysis = analyse(events(), checkpoints, lo, hi, args.fee_bps)
    checks = analysis['boundary_reconciliations']
    failed = (analysis['totals']['fee_mismatches'] > 0 or
              analysis['order_side_or_overfill_errors'] > 0 or
              analysis['negative_inventory_errors'] > 0 or
              any(x[k]['status'] == 'FAILED' for x in checks
                  for k in ('fee_counter', 'turnover_counter', 'inventory')))
    return {'run_id': args.run_id, 'mode': 'owner-run read-only audit; no remote writes',
            'selected_period': {'start': iso(lo), 'end_exclusive': iso(hi)},
            'run_period': {'start': summary['start'], 'end': summary['end']},
            'initial_capital_usd': result['trade_replay'].get('capital_usd'),
            'configured_fee_bps': recorded_rate, 'tested_fee_bps': args.fee_bps,
            'status': 'DISCREPANCY_FOUND' if failed else 'NO_DISCREPANCIES_IN_PERFORMED_CHECKS',
            'boundary_checks_performed': len(checks),
            'analysis': analysis, 'source_receipts': reader.receipts,
            'compressed_bytes_read': reader.bytes_read,
            'audit_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest()}


def text_report(report: dict) -> str:
    a = report['analysis']; t = a['totals']
    lines = [f"Run: {report['run_id']}", f"Status: {report['status']}",
             f"Selected period: {report['selected_period']}",
             f"Stored / tested fee bps: {report['configured_fee_bps']} / {report['tested_fee_bps']}",
             f"Actual fills: {t['fills']:,}",
             f"Gross filled notional USD: {t['traded_notional_usd']:,.6f}",
             f"Recorded fees USD: {t['recorded_fees_usd']:,.6f}",
             f"Expected fees USD: {t['expected_fees_usd']:,.6f}",
             f"Mismatched fill fees: {t['fee_mismatches']}",
             f"Boundary-state comparisons: {report['boundary_checks_performed']}", '',
             'BY UTC DAY (NAV reference time/age are in report.json)',
             'Date          Fees USD     Turnover USD    Fees bps/NAV   Turnover/NAV']
    fmt = lambda value: 'n/a' if value is None else f'{value:,.4f}'
    for d in a['days']:
        lines.append(f"{d['date_utc']} {d['recorded_fees_usd']:12,.4f} "
                     f"{d['traded_notional_usd']:16,.2f} "
                     f"{fmt(d['fees_bps_of_reference_nav']):>14} "
                     f"{fmt(d['turnover_times_reference_nav']):>14}")
    lines.extend(['', 'BY INSTRUMENT: fees USD / turnover USD / fills / rapid direction changes'])
    for s, d in a['by_instrument'].items():
        lines.append(f"{s}: {d['recorded_fees_usd']:,.4f} / {d['traded_notional_usd']:,.2f} / "
                     f"{d['fills']} / {d['direction_changes_within_60s']}")
    lines.extend(['', *a['notes']])
    return '\n'.join(lines) + '\n'


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--run-id', required=True, help='32-character saved-run ID to inspect')
    p.add_argument('--fee-bps', type=float, default=3.0, help='Independently test every fill against this fee')
    p.add_argument('--day', help='UTC date YYYY-MM-DD; default: first complete UTC day')
    p.add_argument('--days', type=int, default=1, help='Number of consecutive UTC days, 1 to 90')
    p.add_argument('--max-read-mib', type=int, default=512, help='Total compressed read budget')
    p.add_argument('--output', type=Path, default=Path('run-cost-diagnostics'))
    p.add_argument('--local-run-dir', type=Path, help='Optional offline job directory for tests/exported audits')
    args = p.parse_args()
    if not (math.isfinite(args.fee_bps) and args.fee_bps >= 0 and 1 <= args.days <= 90
            and 1 <= args.max_read_mib <= 16384):
        p.error('Invalid fee, day count or read budget')
    if args.output.exists():
        p.error('Output path already exists; choose another directory to preserve previous evidence')
    try:
        report = run(args)
        # Publish local report only after every selected chunk passes verification.
        args.output.mkdir(parents=True, mode=0o700)
        (args.output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        (args.output / 'report.txt').write_text(text_report(report))
        print(text_report(report))
        print(f'Local files: {args.output}/report.txt and report.json. Nothing was uploaded.')
        return 2 if report['status'] == 'DISCREPANCY_FOUND' else 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Diagnostic stopped: {exc}. No completed report has been certified.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
