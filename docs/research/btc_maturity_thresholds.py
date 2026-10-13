"""Compare proposed ceilings using the already verified daily maturity series."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'btc-maturity-daily.json'


def main():
    data = SOURCE.read_bytes()
    source = json.loads(data)
    rows = [dict(zip(source['columns'], row)) for row in source['rows']]
    groups = {'full_catalog_span': rows,
              '2021_onward': [r for r in rows if r['date'] >= '2021-01-01']}
    groups.update({year: [r for r in rows if r['date'].startswith(year)]
                   for year in ('2024', '2025', '2026')})
    output = {'source_file': SOURCE.name,
              'source_sha256': hashlib.sha256(data).hexdigest(),
              'sample_time': '00:00 UTC daily; not exact intraday availability',
              'periods': {}}
    for name, group in groups.items():
        valid = [r for r in group if r['archive_ratio'] is not None]
        comparisons = []
        for ceiling in (0.25, 0.30, 1/3, 0.35):
            count = sum(r['archive_ratio'] <= ceiling for r in valid)
            comparisons.append({'ceiling': ceiling, 'qualifying_daily_samples': count,
                                'pct_all_samples': 100*count/len(group),
                                'pct_pair_present_samples': 100*count/len(valid) if valid else None})
        assert all(a['qualifying_daily_samples'] <= b['qualifying_daily_samples']
                   for a, b in zip(comparisons, comparisons[1:]))
        output['periods'][name] = {'start': group[0]['date'], 'end': group[-1]['date'],
                                   'samples': len(group), 'pair_present_samples': len(valid),
                                   'comparisons': comparisons}
    path = ROOT / 'btc-maturity-threshold-comparison.json'
    path.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
