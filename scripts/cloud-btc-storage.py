#!/usr/bin/env python3
"""Bounded June 25 pilot publication/replay; invoked by the OIDC operator workflow."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/cloud-btc-storage'
EVIDENCE = WORK / 'evidence'
BUCKET = 'keep-and-lease-market-data'
DAY = '2026-06-25'
BASELINES = ROOT / 'docs/validation/btc-trade-parquet'


def run(script, *args):
    subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *map(str, args)],
                   cwd=ROOT, check=True)


def load(path):
    return json.loads(path.read_text())


def verify_events(path):
    actual, expected = load(path), load(BASELINES / 'event-equivalence.json')
    for key in ('status', 'events', 'event_stream_sha256'):
        if actual[key] != expected[key]:
            raise ValueError(f'Pilot event baseline differs: {key}')


def verify_replay(directory, name):
    actual, expected = load(directory / 'report.json'), load(BASELINES / (name + '.json'))
    measurements = {'audit_bytes', 'peak_rss_mib', 'wall_seconds', 'code_sha256',
                    'input_manifest_sha256', 'parquet_manifest_sha256'}
    if {k:v for k,v in actual.items() if k not in measurements} != {
            k:v for k,v in expected.items() if k not in measurements}:
        raise ValueError(f'Financial replay differs: {name}')
    with gzip.open(directory / 'audit.jsonl.gz', 'rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    baseline = next(x for x in load(BASELINES / 'replay-equivalence.json') if x['scenario'] == name)
    if digest != baseline['uncompressed_audit_sha256']:
        raise ValueError(f'Complete replay audit differs: {name}')
    return {'scenario': name, 'financial_summaries_identical': True,
            'complete_audit_identical': True, 'uncompressed_audit_sha256': digest,
            'report': actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'upload-verify'])
    args = parser.parse_args()
    raw, parquet = WORK / 'raw', WORK / 'parquet'
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if args.phase == 'prepare':
        run('refresh-btc-trade-pilot.py', '--date', DAY, '--output', raw)
        run('convert-btc-trade-parquet.py', '--data', raw, '--output', parquet)
        run('check-btc-parquet-equivalence.py', '--data', raw, '--parquet', parquet,
            '--output', EVIDENCE / 'local-events.json')
        verify_events(EVIDENCE / 'local-events.json')
        return
    verify_events(EVIDENCE / 'local-events.json')
    run('upload-btc-trade-parquet.py', '--data', raw, '--parquet', parquet,
        '--bucket', BUCKET, '--execute')
    manifest_hash = hashlib.sha256((parquet / 'manifest.json').read_bytes()).hexdigest()
    uri = f'gs://{BUCKET}/btc/trades/v1/{manifest_hash}'
    # All following market reads use GCS, not the local Parquet files.
    run('check-btc-parquet-equivalence.py', '--data', raw, '--parquet', uri,
        '--output', EVIDENCE / 'gcs-events.json')
    verify_events(EVIDENCE / 'gcs-events.json')
    verified = []
    for name, capital, participation in [('run-one-dollar',1,1), ('run-capacity',100000,0.1)]:
        directory = WORK / name
        run('check-btc-trade-pilot.py', '--parquet', uri, '--data', WORK / 'no-raw-inputs',
            '--output', directory, '--capital', capital, '--participation', participation)
        verified.append(verify_replay(directory, name))
    report = {'status':'passed', 'uri':uri, 'period_start':DAY+'T00:00:00Z',
              'period_end':'2026-06-26T00:00:00Z',
              'engine_commit':os.getenv('SOURCE_COMMIT'), 'replays':verified,
              'events':load(EVIDENCE / 'gcs-events.json')['events']}
    (EVIDENCE / 'gcs-validation.json').write_text(json.dumps(report, indent=2)+'\n')
    # Preserve full audits in GCS; artifacts contain compact reports only.
    from google.cloud import storage
    bucket = storage.Client().bucket(BUCKET)
    validation_prefix = f'btc/validation/{manifest_hash}/{os.environ["GITHUB_RUN_ID"]}'
    for name in ('run-one-dollar','run-capacity'):
        blob = bucket.blob(validation_prefix+'/'+name+'/audit.jsonl.gz', chunk_size=8*1024*1024)
        blob.upload_from_filename(str(WORK/name/'audit.jsonl.gz'), if_generation_match=0, checksum='crc32c')
    blob = bucket.blob(validation_prefix+'/gcs-validation.json')
    blob.upload_from_filename(str(EVIDENCE/'gcs-validation.json'), if_generation_match=0, checksum='crc32c')
    print('GCS pilot validation: '+json.dumps({'status':'passed','uri':uri,'events':report['events'],
          'validation_uri':f'gs://{BUCKET}/{validation_prefix}/gcs-validation.json'}))


if __name__ == '__main__':
    main()
