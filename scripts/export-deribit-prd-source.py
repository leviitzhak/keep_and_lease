"""Read-only, bounded June 6 Deribit tape export; only ciphertext leaves runner."""
import hashlib
import io
import json
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.cloud import storage

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / '.cloud-agent/requests'

def main():
    request = json.loads((REQUESTS / 'deribit-prd-source.json').read_text())
    assert request == {'schema_version': 1, 'action': 'read-deribit-2026-06-06', 'sequence': 1}
    spec = json.loads((REQUESTS / 'deribit-prd-source-spec.json').read_text())
    assert spec['date'] == '2026-06-06'
    expected = {'BTC-6JUN26', 'BTC-7JUN26', 'BTC-8JUN26', 'BTC-9JUN26',
                'BTC-10JUN26', 'BTC-12JUN26', 'BTC-19JUN26', 'BTC-26JUN26',
                'BTC-31JUL26', 'BTC-28AUG26', 'BTC-25SEP26', 'BTC-25DEC26'}
    assert set(spec['futures']) == expected
    pub = serialization.load_pem_public_key(spec.pop('recipient_public_key').encode())
    assert isinstance(pub, rsa.RSAPublicKey) and pub.key_size >= 3072
    bucket = storage.Client(project='keep-and-lease').bucket('keep-and-lease-market-data')
    receipt, total = [], 0
    archive = io.BytesIO()
    with ZipFile(archive, 'w', ZIP_DEFLATED) as z:
        z.writestr('metadata.json', json.dumps(spec, indent=2))
        for symbol, item in sorted(spec['futures'].items()):
            name, digest = item['path'], item['sha256']
            assert name == symbol + '.jsonl.gz'
            assert len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
            obj = f'btc/raw/sha256/{digest}/{name}'
            blob = bucket.blob(obj)
            blob.reload(timeout=60)
            assert 0 < blob.size < 8_000_000
            data = blob.download_as_bytes(if_generation_match=blob.generation, timeout=90)
            assert hashlib.sha256(data).hexdigest() == digest
            total += len(data)
            assert total < 24_000_000
            z.writestr(name, data)
            receipt.append({'object': obj, 'generation': str(blob.generation), 'sha256': digest, 'bytes': len(data)})
        z.writestr('receipt.json', json.dumps(receipt, indent=2))
    key, nonce = os.urandom(32), os.urandom(12)
    aad = b'deribit-prd-source-2026-06-06-v1'
    ciphertext = AESGCM(key).encrypt(nonce, archive.getvalue(), aad)
    wrapped = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    out = ROOT / 'encrypted-deribit-source'
    out.mkdir(exist_ok=True)
    (out / 'source.enc').write_bytes(ciphertext)
    (out / 'key.enc').write_bytes(wrapped)
    (out / 'nonce.bin').write_bytes(nonce)
    (out / 'receipt.json').write_text(json.dumps({'status': 'complete', 'files': len(receipt), 'raw_bytes': total, 'ciphertext_sha256': hashlib.sha256(ciphertext).hexdigest(), 'aad': aad.decode()}, indent=2))
    print(f'Verified and encrypted {len(receipt)} fixed source files ({total} bytes).')

if __name__ == '__main__':
    main()
