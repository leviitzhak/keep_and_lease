#!/usr/bin/env python3
"""Restore only successful bounded BTC day receipts from approved operator runs."""
import argparse
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

REPOSITORY='leviitzhak/keep_and_lease'
ALLOWED_WORKFLOWS={'.github/workflows/btc-trade-range.yml','.github/workflows/btc-trade-recovery.yml'}
DAYS={(date(2026,6,6)+timedelta(days=i)).isoformat() for i in range(90)}


def api(path):
    return subprocess.check_output(['gh','api',f'repos/{REPOSITORY}/'+path])


def restore(run_ids, output):
    if not 1<=len(run_ids)<=5 or len(set(run_ids))!=len(run_ids) or any(type(i) is not int or i<=0 for i in run_ids):
        raise ValueError('Require one to five distinct approved source run IDs')
    output=Path(output)
    restored=set()
    for run_id in run_ids:
        run=json.loads(api(f'actions/runs/{run_id}'))
        if run['head_branch']!='agent/cloud-autonomous-access' or run['path'] not in ALLOWED_WORKFLOWS or run['status']!='completed':
            raise ValueError('Source must be a completed bounded operator ingestion/recovery run')
        artifacts=json.loads(api(f'actions/runs/{run_id}/artifacts?per_page=100'))
        if artifacts['total_count']>100: raise ValueError('Unexpected artifact count')
        for artifact in artifacts['artifacts']:
            name=artifact['name']
            if not name.startswith('btc-day-'):continue
            day=name.removeprefix('btc-day-')
            if day not in DAYS or artifact['expired'] or artifact['size_in_bytes']>8*1024*1024:
                raise ValueError('Invalid or expired completed daily artifact')
            data=api(f"actions/artifacts/{artifact['id']}/zip")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries=[v for v in archive.infolist() if not v.is_dir()]
                allowed={f'receipts/{day}.json',f'evidence/{day}.json'}
                if any(v.filename not in allowed for v in entries) or len({v.filename for v in entries})!=len(entries):
                    raise ValueError('Unexpected daily artifact entries')
                if f'receipts/{day}.json' not in {v.filename for v in entries}:
                    raise ValueError('Completed artifact lacks receipt')
                for entry in entries:
                    with archive.open(entry) as stream: encoded=stream.read(4*1024*1024+1)
                    if len(encoded)>4*1024*1024:raise ValueError('Oversized daily evidence')
                    if entry.filename.startswith('receipts/'):
                        item=json.loads(encoded);digest=item['manifest_sha256']
                        if not re.fullmatch('[0-9a-f]{64}',digest) or item['uri']!='gs://keep-and-lease-market-data/btc/trades/v1/'+digest:
                            raise ValueError('Daily receipt points outside the approved immutable prefix')
                    path=output/entry.filename;path.parent.mkdir(parents=True,exist_ok=True)
                    if path.exists() and path.read_bytes()!=encoded:
                        raise ValueError('Conflicting reused daily receipt/evidence')
                    path.write_bytes(encoded)
                restored.add(day)
    return sorted(restored)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-ids',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--plan',action='store_true')
    args=p.parse_args();days=restore(json.loads(args.run_ids),args.output)
    if args.plan:
        missing=sorted(DAYS-set(days))
        if not missing:raise ValueError('No failed days remain to recover')
        matrix=[dict(start=d,end=(date.fromisoformat(d)+timedelta(days=1)).isoformat()) for d in missing]
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('days='+json.dumps(matrix)+'\n')
    print(json.dumps(dict(restored_days=len(days),missing_days=sorted(DAYS-set(days)))))


if __name__=='__main__':main()
