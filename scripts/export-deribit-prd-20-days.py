"""Bounded read-only export of 20 evenly spaced days in the pinned BTC range."""
import hashlib
import io
import json
import os
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.cloud import storage

ROOT = Path(__file__).resolve().parents[1]
RANGE_SHA = '52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912'
EXPECTED = {'schema_version': 1, 'action': 'read-deribit-20-full-days', 'sequence': 1}
AAD = b'deribit-prd-20-full-days-v1'


def main():
    req = ROOT / '.cloud-agent/requests'
    assert json.loads((req / 'deribit-prd-20-days.json').read_text()) == EXPECTED
    spec = json.loads((req / 'deribit-prd-source-spec.json').read_text())
    pub = serialization.load_pem_public_key(spec['recipient_public_key'].encode())
    assert isinstance(pub, rsa.RSAPublicKey) and pub.key_size >= 3072
    bucket = storage.Client(project='keep-and-lease').bucket('keep-and-lease-market-data')
    receipts, total = [], 0

    def read(name, digest, bound):
        nonlocal total
        assert len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
        blob = bucket.blob(name)
        blob.reload(timeout=60)
        assert 0 < blob.size < bound
        data = blob.download_as_bytes(if_generation_match=blob.generation, timeout=90)
        assert hashlib.sha256(data).hexdigest() == digest
        total += len(data)
        assert total < 160_000_000
        receipts.append(dict(object=name, generation=str(blob.generation), sha256=digest, bytes=len(data)))
        return data

    range_data = read(f'btc/trades/ranges/{RANGE_SHA}/manifest.json', RANGE_SHA, 4_000_000)
    manifest = json.loads(range_data)
    days = manifest['daily_datasets']
    assert len(days) == 90
    assert days[0]['start'].startswith('2026-06-06') and days[-1]['start'].startswith('2026-09-03')
    indices = [round(i * 89 / 19) for i in range(20)]
    assert len(set(indices)) == 20
    archive = io.BytesIO()
    selected = []
    with ZipFile(archive, 'w', ZIP_DEFLATED) as z:
        z.writestr('range-manifest.json', range_data)
        for i in indices:
            day = days[i]
            digest = day['manifest_sha256']
            daily_data = read(f'btc/trades/v1/{digest}/manifest.json', digest, 4_000_000)
            daily = json.loads(daily_data)
            source = daily['source_manifest']
            assert source['start'] == day['start'] and source['end'] == day['end']
            date = source['start'][:10]
            lo = datetime.fromisoformat(source['start'].replace('Z', '+00:00')).timestamp()
            hi = datetime.fromisoformat(source['end'].replace('Z', '+00:00')).timestamp()
            assert hi - lo == 86400 and lo % 86400 == 0
            assert 1 <= len(source['futures']) <= 30
            z.writestr(f'{date}/daily-manifest.json', daily_data)
            eligible = []
            for symbol, item in sorted(source['futures'].items()):
                name = item['path']
                assert name == symbol + '.jsonl.gz' and symbol.startswith('BTC-')
                data = read(f"btc/raw/sha256/{item['sha256']}/{name}", item['sha256'], 20_000_000)
                z.writestr(f'{date}/{name}', data)
                expiry = datetime.fromisoformat(item['expiry'].replace('Z', '+00:00')).timestamp()
                if expiry - lo >= 60 * 86400:
                    eligible.append(symbol)
            selected.append(dict(date=date, range_day_index=i, daily_sha256=digest,
                                 eligible_symbols=eligible, futures_count=len(source['futures'])))
        z.writestr('selection.json', json.dumps(selected, indent=2))
        z.writestr('receipt.json', json.dumps(receipts, indent=2))
    key, nonce = os.urandom(32), os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, archive.getvalue(), AAD)
    wrapped = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    out = ROOT / 'encrypted-deribit-20-days'
    out.mkdir(exist_ok=True)
    for i, offset in enumerate(range(0, len(ciphertext), 24_000_000)):
        (out / f'source-{i:03d}.enc').write_bytes(ciphertext[offset:offset + 24_000_000])
    (out / 'key.enc').write_bytes(wrapped)
    (out / 'nonce.bin').write_bytes(nonce)
    (out / 'receipt.json').write_text(json.dumps(dict(status='complete', days=20, objects=len(receipts),
        raw_bytes=total, ciphertext_sha256=hashlib.sha256(ciphertext).hexdigest(), aad=AAD.decode()), indent=2))
    print(f'Verified and encrypted 20 daily tapes ({total} source bytes).')


if __name__ == '__main__':
    main()
