"""Daily minimum maturity separation from the saved completed-archive catalog.

Metadata feasibility only: no order-fill, liquidity or P&L inference. Run from
the repo root; writes JSON daily samples, Markdown monthly tables and a PNG.
"""
import calendar
import itertools
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DAY_MS = 86_400_000


def dt(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def add_months(t, n):
    month = t.year * 12 + t.month - 1 + n
    year, month = divmod(month, 12)
    month += 1
    return t.replace(year=year, month=month,
                     day=min(t.day, calendar.monthrange(year, month)[1]))


def minimum(candidates, now):
    """Adjacent expiries suffice: for each far expiry choose the closest near."""
    candidates = sorted(candidates, key=lambda x: (x['expiry_ms'], x['instrument']))
    if len({x['expiry_ms'] for x in candidates}) != len(candidates):
        raise ValueError('Distinct instruments with identical expiries require explicit deduplication')
    values = [(b['expiry_ms'] - a['expiry_ms'], b['expiry_ms'] - now,
               a['instrument'], b['instrument']) for a, b in zip(candidates, candidates[1:])]
    if not values:
        return None
    gap, remaining, a, b = min(values, key=lambda x: (x[0] / x[1], x[2], x[3]))
    return {'ratio': gap / remaining, 'pair': [a, b],
            'gap_days': gap / DAY_MS, 'far_days': remaining / DAY_MS,
            'passes_25pct': 4 * gap <= remaining}


def calculate(source):
    catalog = [dict(zip(source['columns'], row)) for row in source['instruments']]
    for x in catalog:
        x['snapshot_ms'] = int(datetime.fromisoformat(x['snapshot_at']).timestamp() * 1000)
        assert x['creation_ms'] < x['expiry_ms']
    start = dt(min(x['creation_ms'] for x in catalog)).replace(hour=0, minute=0, second=0, microsecond=0)
    # Use the start of the last snapshot date: every instrument's frozen cutoff
    # is later. Do not imply coverage of the partial download-snapshot day.
    end = min(dt(x['snapshot_ms']) for x in catalog).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    while start <= end:
        now = int(start.timestamp() * 1000)
        floor = int(add_months(start, 3).timestamp() * 1000)
        listed = [x for x in catalog if x['creation_ms'] <= now and x['expiry_ms'] >= floor]
        available = [x for x in listed if x['first_trade_ms'] is not None
                     and x['first_trade_ms'] <= now <= x['last_observed_trade_ms']]
        rows.append({'date': start.date().isoformat(), 'listed_count': len(listed),
                     'archive_count': len(available), 'listed': minimum(listed, now),
                     'archive': minimum(available, now)})
        start += timedelta(days=1)
    return catalog, rows


def summarize(rows, key='archive'):
    valid = [r for r in rows if r[key] is not None]
    return {'samples': len(rows), 'pair_samples': len(valid),
            'no_pair_samples': len(rows) - len(valid),
            'passing_samples': sum(r[key]['passes_25pct'] for r in valid),
            'minimum_pct': min((r[key]['ratio'] * 100 for r in valid), default=None),
            'maximum_pct': max((r[key]['ratio'] * 100 for r in valid), default=None)}


def passing_windows(catalog, final_sample):
    """Exact millisecond windows passing 25%, including between daily samples.

    Calendar addition is monotone within each UTC date. Check dates separately
    because clamping can repeat a target date at month-end.
    """
    cutoff = int(datetime.fromisoformat(final_sample).replace(tzinfo=timezone.utc).timestamp()*1000) + 1
    windows = []
    for a, b in itertools.combinations(catalog, 2):
        if a['first_trade_ms'] is None or b['first_trade_ms'] is None:
            continue
        near, far = sorted((a, b), key=lambda x: x['expiry_ms'])
        gap = far['expiry_ms'] - near['expiry_ms']
        if gap <= 0:
            continue
        lo = max(a['creation_ms'], b['creation_ms'], a['first_trade_ms'], b['first_trade_ms'])
        hi = min(a['last_observed_trade_ms']+1, b['last_observed_trade_ms']+1,
                 far['expiry_ms'] - 4*gap + 1, cutoff)
        if lo >= hi:
            continue
        day = dt(lo).replace(hour=0, minute=0, second=0, microsecond=0)
        expiry = dt(near['expiry_ms'])
        pieces = []
        while int(day.timestamp()*1000) < hi:
            start = int(day.timestamp()*1000)
            boundary = add_months(day, 3)
            if boundary.date() < expiry.date():
                end = start + DAY_MS
            elif boundary.date() == expiry.date():
                end = start + (near['expiry_ms'] % DAY_MS) + 1
            else:
                end = start
            left, right = max(start, lo), min(end, hi)
            if left < right:
                if pieces and pieces[-1][1] == left:
                    pieces[-1][1] = right
                else:
                    pieces.append([left, right])
            day += timedelta(days=1)
        for left, right in pieces:
            assert 4*gap <= far['expiry_ms']-left
            assert expiry >= add_months(dt(right-1),3)
            windows.append({'pair': [near['instrument'], far['instrument']],
                            'start_utc': dt(left).isoformat(timespec='milliseconds'),
                            'end_exclusive_utc': dt(right).isoformat(timespec='milliseconds'),
                            'duration_hours': (right-left)/3_600_000,
                            'minimum_ratio_pct': 100*gap/(far['expiry_ms']-left),
                            'start_ms': left, 'end_exclusive_ms': right})
    windows.sort(key=lambda x: (x['start_ms'], x['pair']))
    union = []
    for w in windows:
        lo, hi = w['start_ms'], w['end_exclusive_ms']
        if union and lo <= union[-1][1]:
            union[-1][1] = max(union[-1][1], hi)
        else:
            union.append([lo, hi])
    return {'qualifying_pair_windows': windows,
            'union_duration_hours': sum(b-a for a,b in union)/3_600_000,
            'note': 'Exact metadata eligibility at millisecond precision through the final daily sample; no liquidity inference.'}


def write_outputs(source, catalog, rows):
    months, years = defaultdict(list), defaultdict(list)
    for r in rows:
        months[r['date'][:7]].append(r)
        years[r['date'][:4]].append(r)
    stats = {'archive': summarize(rows), 'listed': summarize(rows, 'listed'),
             'by_year': {y: summarize(v) for y, v in years.items()},
             'intraday_25pct': passing_windows(catalog, rows[-1]['date'])}
    compact = {'schema_version': 1, 'sample_time': '00:00 UTC daily',
               'columns': ['date', 'listed_count', 'archive_count', 'listed_ratio',
                           'listed_pair', 'archive_ratio', 'archive_pair'],
               'rows': [[r['date'], r['listed_count'], r['archive_count'],
                         r['listed']['ratio'] if r['listed'] else None,
                         r['listed']['pair'] if r['listed'] else None,
                         r['archive']['ratio'] if r['archive'] else None,
                         r['archive']['pair'] if r['archive'] else None] for r in rows]}
    with (ROOT / 'btc-maturity-daily.json').open('w') as f:
        f.write(json.dumps({k:v for k,v in compact.items() if k != 'rows'},indent=2)[:-2]+',\n  "rows": [\n')
        f.write(',\n'.join('    '+json.dumps(r,separators=(',', ':')) for r in compact['rows']))
        f.write('\n  ]\n}\n')
    (ROOT / 'btc-maturity-summary.json').write_text(json.dumps(stats, indent=2)+'\n')
    out = ['# Minimum maturity separation through time', '',
           'Daily samples at 00:00 UTC, with both futures at least three calendar months from expiry.',
           'Each monthly row summarizes the daily minimum across archive-supported pairs; values are percentages.',
           'No-pair days are missing, not zero. This is maturity feasibility, not a fill or liquidity test.', '',
           '| Month | Smallest daily minimum | Largest daily minimum | Days with a pair | Days ≤25% |',
           '| --- | ---: | ---: | ---: | ---: |']
    for month, items in months.items():
        s = summarize(items)
        fmt = lambda x: '—' if x is None else f'{x:.3f}%'
        out.append(f"| {month} | {fmt(s['minimum_pct'])} | {fmt(s['maximum_pct'])} | {s['pair_samples']}/{s['samples']} | {s['passing_samples']} |")
    (ROOT / 'BTC_MATURITY_MONTHLY.md').write_text('\n'.join(out)+'\n')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
    fig, axes = plt.subplots(2, 1, figsize=(13, 7.5), layout='constrained', gridspec_kw={'height_ratios': [2, 1]})
    for ax, selected, title in [(axes[0], rows, 'Available archive: full historical span'),
                                 (axes[1], [r for r in rows if r['date'] >= '2026-01-01'], '2026 detail')]:
        dates = [datetime.fromisoformat(r['date']) for r in selected]
        values = [r['archive']['ratio']*100 if r['archive'] else float('nan') for r in selected]
        ax.plot(dates, values, color='#195da3', linewidth=1.25, label='Minimum across available pairs')
        ax.axhline(25, color='#b34c2e', linestyle='--', linewidth=1.2, label='Requested 25% ceiling')
        ax.set_title(title, loc='left', fontsize=13, weight='bold')
        ax.set_ylabel('Minimum ratio (%)')
        ax.grid(axis='y', alpha=.2)
        ax.spines[['top', 'right']].set_visible(False)
        if ax is axes[0]:
            ax.set_xlim(dates[0], dates[-1])
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.legend(loc='upper right', fontsize=10)
        else:
            ax.xaxis.set_major_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
    fig.suptitle('Minimum BTC futures maturity separation', fontsize=18, weight='bold', x=.05, ha='left')
    fig.supxlabel('Daily 00:00 UTC • ≥3 calendar months remaining • gaps mean fewer than two supported contracts', fontsize=10)
    fig.savefig(ROOT / 'btc-maturity-separation.png', dpi=160, facecolor='white')
    plt.close(fig)
    return stats


def verify(catalog, rows):
    """Check the optimized minimum against every pair, and calendar boundaries."""
    assert add_months(datetime(2024, 1, 31, tzinfo=timezone.utc), 3).day == 30
    assert add_months(datetime(2023, 11, 30, tzinfo=timezone.utc), 3).day == 29
    for r in rows:
        t = datetime.fromisoformat(r['date']).replace(tzinfo=timezone.utc)
        now, floor = int(t.timestamp()*1000), int(add_months(t,3).timestamp()*1000)
        candidates = [x for x in catalog if x['creation_ms'] <= now and x['expiry_ms'] >= floor
                      and x['first_trade_ms'] is not None and x['first_trade_ms'] <= now <= x['last_observed_trade_ms']]
        brute = min((abs(a['expiry_ms']-b['expiry_ms'])/(max(a['expiry_ms'],b['expiry_ms'])-now)
                     for a,b in itertools.combinations(candidates,2)), default=None)
        assert brute == (r['archive']['ratio'] if r['archive'] else None), r['date']


if __name__ == '__main__':
    source = json.loads((ROOT / 'btc-maturity-catalog.json').read_text())
    catalog, rows = calculate(source)
    verify(catalog, rows)
    stats = write_outputs(source, catalog, rows)
    print(json.dumps(stats, indent=2))
