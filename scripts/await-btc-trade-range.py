#!/usr/bin/env python3
"""Wait for one approved ingestion run and resolve its verified range artifact.

Runs inside GitHub Actions using its bounded read-only Actions token. No cloud
credentials, market writes or arbitrary repository/URL inputs are accepted.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPOSITORY = 'leviitzhak/keep_and_lease'


def api(path):
    return subprocess.check_output(['gh', 'api', f'repos/{REPOSITORY}/'+path])


def resolve(run_id):
    deadline = time.monotonic()+4*3600
    while True:
        run = json.loads(api(f'actions/runs/{run_id}'))
        if (run['head_branch'] != 'agent/cloud-autonomous-access' or
                run['path'] not in ('.github/workflows/btc-trade-range.yml', '.github/workflows/btc-trade-recovery.yml')):
            raise ValueError('Unexpected ingestion workflow or branch')
        if run['status'] == 'completed':
            if run['conclusion'] != 'success':
                raise ValueError('Ingestion did not pass all 90 daily gates')
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('Ingestion is still running; rerun this waiting job later')
        print('Waiting for the approved 90-day ingestion run', run_id, flush=True)
        time.sleep(60)
    artifacts = json.loads(api(f'actions/runs/{run_id}/artifacts?per_page=100'))['artifacts']
    matches = [a for a in artifacts if a['name']=='btc-90day-manifest' and not a['expired']]
    if len(matches) != 1 or matches[0]['size_in_bytes'] > 4*1024*1024:
        raise ValueError('Missing or oversized verified range artifact')
    encoded = api(f"actions/artifacts/{matches[0]['id']}/zip")
    with zipfile.ZipFile(io.BytesIO(encoded)) as archive:
        if archive.namelist() != ['manifest.json']:
            raise ValueError('Unexpected range archive entries')
        with archive.open('manifest.json') as stream:
            manifest = stream.read(4*1024*1024+1)
    if len(manifest) > 4*1024*1024:
        raise ValueError('Range manifest exceeds its size limit')
    value = json.loads(manifest)
    source = value['source_manifest']
    if source['start'][:10] != '2026-06-06' or source['end'][:10] != '2026-09-04':
        raise ValueError('Ingestion artifact does not cover the approved period')
    from trade_data_store import ParquetTradeStore
    check = object.__new__(ParquetTradeStore)
    check.manifest, check.source_manifest = value, source
    check._validate_range()
    return hashlib.sha256(manifest).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', type=int, required=True)
    args = parser.parse_args()
    if args.run_id <= 0:
        raise ValueError('Invalid ingestion run ID')
    digest = resolve(args.run_id)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write('manifest='+digest+'\n')
    print('Verified complete 90-day range manifest:', digest)


if __name__ == '__main__':
    main()
