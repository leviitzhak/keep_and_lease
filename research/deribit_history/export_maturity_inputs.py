"""Read-only export of the fixed completed BTC archive's public metadata.

No exchange requests, data downloads, GCS writes, credentials or account data
are included. The saved completion receipts remain the raw-integrity authority.
"""
import hashlib
import json
from pathlib import Path

JOB = 'btc-full-20261009-archive'
PREFIX = f'btc/research/deribit-full-history-v1/jobs/{JOB}'
REQUEST = Path('.cloud-agent/requests/deribit-maturity-inputs.json')
OUT = Path('maturity-inputs')


def main():
    from google.cloud import storage
    request = json.loads(REQUEST.read_text())
    if request == {'schema_version': 1, 'action': 'reconcile-existing-futures-union', 'sequence': 1}:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from research.post_decision_value.archive_union_worker import main as reconcile
        return reconcile(request_path=REQUEST, output=str(OUT))
    if request != {'schema_version': 1, 'job_id': JOB, 'action': 'export_metadata', 'sequence': 1}:
        raise ValueError('Only the fixed, read-only metadata export is supported')
    bucket = storage.Client().bucket('keep-and-lease-market-data')
    names = ['manifest.json', 'plan-reconciled-v2.json'] + [f'completed/shard-{s}.json' for s in range(8)]
    records, evidence = {}, []
    for name in names:
        blob = bucket.get_blob(f'{PREFIX}/{name}', timeout=60)
        if blob is None or blob.size > 10_000_000:
            raise ValueError(f'Missing or oversized metadata: {name}')
        data = blob.download_as_bytes(checksum='crc32c', timeout=60, if_generation_match=blob.generation)
        records[name] = json.loads(data)
        evidence.append({'key': blob.name, 'generation': str(blob.generation), 'bytes': len(data),
                         'sha256': hashlib.sha256(data).hexdigest()})
        destination = OUT / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    manifest, plan = records['manifest.json'], records['plan-reconciled-v2.json']
    if manifest['status'] != 'COMPLETE_AVAILABLE_HISTORY' or manifest['job_id'] != JOB or plan['job_id'] != JOB:
        raise ValueError('The fixed archive is not complete')
    expected = set()
    for item in plan['instruments']:
        lo, hi = item['first_available_seq'], item['last_available_seq']
        if lo is not None:
            for start in range(lo, hi + 1, plan['chunk_size']):
                end = min(start + plan['chunk_size'] - 1, hi)
                expected.add(f"{PREFIX}/receipts/{item['instrument']}/{start:012d}-{end:012d}.json")
    actual = []
    for s in range(8):
        shard = records[f'completed/shard-{s}.json']
        if (shard['job_id'], shard['shard'], shard['status'], shard['failures'], shard['pending']) != (JOB, s, 'COMPLETE', [], False):
            raise ValueError('Invalid shard completion')
        actual.extend(shard['receipt_keys'])
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('Completion receipts do not cover the frozen plan exactly')
    report = {'job_id': JOB, 'status': 'METADATA_EXPORTED', 'instruments': len(plan['instruments']),
              'completed_chunks': len(actual), 'source_objects': evidence,
              'scope': 'Metadata and completed-shard receipts only; raw hashes are not reverified by this export.'}
    (OUT / 'export-receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'source_objects'}))


if __name__ == '__main__':
    main()
