#!/usr/bin/env python3
"""Reverify two immutable datasets uploaded by recovery run 34242246481.

Uses existing ADC. Reads only content-addressed GCS objects; no exchange access.
Receipts are created only after raw/cloud event equivalence passes again.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trade_data_store import ParquetTradeStore, sha256

DATASETS = {
    '2026-08-26': '256bc2a8c341f374780c94e80a39530dbc05c73b84ba2bc9358510c80a50f567',
    '2026-08-28': '4b9ae1d3699a5f99ab164b7a2ee84e97abaa4d27ed9e7dadf0cc5eb1fbf30f8f',
}


def safe_path(raw, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Unsafe source path')
    return raw / path


def recover(day, output):
    digest = DATASETS[day]
    uri = 'gs://keep-and-lease-market-data/btc/trades/v1/' + digest
    store = ParquetTradeStore(uri)
    if hashlib.sha256(store.manifest_bytes).hexdigest() != digest:
        raise ValueError('Daily manifest checksum mismatch')
    from datetime import date, timedelta
    if (store.source_manifest['start'][:10] != day or
            store.source_manifest['end'][:10] != (date.fromisoformat(day) + timedelta(days=1)).isoformat()):
        raise ValueError('Unexpected daily coverage')
    raw = output / 'raw' / day
    raw.mkdir(parents=True, exist_ok=True)

    def restore(relative, expected):
        path = safe_path(raw, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or sha256(path) != expected:
            blob = store.gcs_bucket.blob('btc/raw/sha256/' + expected + '/' + path.name)
            blob.reload()
            blob.download_to_filename(str(path), if_generation_match=int(blob.generation), checksum='crc32c')
        if sha256(path) != expected:
            raise ValueError('Restored raw checksum mismatch: ' + relative)

    restore('manifest.json', store.manifest['source_manifest_sha256'])
    source = json.loads((raw / 'manifest.json').read_text())
    if source != store.source_manifest:
        raise ValueError('Raw source manifest differs from normalized source')
    for item in [source['spot'], *source['futures'].values(), *source.get('evidence_files', [])]:
        restore(item['path'], item['sha256'])
    evidence = output / 'evidence' / (day + '.json')
    subprocess.run([sys.executable, str(ROOT / 'scripts/retry-cloud-command.py'),
                    str(ROOT / 'scripts/check-btc-parquet-equivalence.py'),
                    '--data', str(raw), '--parquet', uri, '--output', str(evidence)], check=True)
    receipt = output / 'receipts' / (day + '.json')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(dict(uri=uri, manifest_sha256=digest)) + '\n')
    print(json.dumps(dict(recovered_day=day, uri=uri)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day', choices=DATASETS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    recover(args.day, args.output)
