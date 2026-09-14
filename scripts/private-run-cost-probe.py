"""One-run read-only probe. No private plaintext, tokens, or error messages leave the runner."""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.cloud import storage

TARGET = '8c9f5fe0e4fbde424ea82205b16c2ed2466be8ddee75024e8ed98d258b255564'
KEY = b'''-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEA4ehbQKaHLKPB0nWHuIeV
pGuJ8+GLl/YDCessWU1U1KwtLwy/OqtCKLr0l/r98aAmLcYyd8H7FgZTUao2FS/V
vHAAtxXC6BsQ4p9KCbMWYtAqEdZd+6aM9Yt8hdVmiawhhqx5jG8mZqRsGjBrHdU4
LMrMjH/m2HA4Ty0gSSNfSJ4tZU0egT0XjJD4T6wFOBEYsD8L6Z6ApbEKefgzI9n6
Y4EXw8tzWRm5EcViFoPCo6tifrzfpXNDHOL3d6GNumPyCwEgJ8RzPX1kbTgY1DvI
CVbfS/KWZSBQjaFKVgJRu+8DfcvPmHy3JX4140r5zbK8g4jUbkmPKrJcAQmrlR86
roK6vvFQpgkpHtb8xOLXJQxN6I56YArtpTQwNcfyM87tyVSrhu6OBobcaOuAkuog
NpgLzDCE0qLHMPeRmee0RfH8ablE5GujQTqe/QmYq0jNTQLBFQbPbc0AjB83H87j
Z9aNdwVGbhtqFJNooVFqAfYb1r8GhGUge49UqDKTtYoBAgMBAAE=
-----END PUBLIC KEY-----
'''

def probe():
    client = storage.Client(project='keep-and-lease')
    bucket = client.bucket('keep-and-lease-results')
    # Resolve only job directory names, not the contents or parameters of other runs.
    # A hash keeps the selected private run identifier out of public source/logs.
    folders = client.list_blobs(bucket, prefix='jobs/', delimiter='/', max_results=2000, timeout=30)
    found = None
    for page in folders.pages:
        for prefix in page.prefixes:
            candidate = prefix.removeprefix('jobs/').removesuffix('/')
            if hashlib.sha256(candidate.encode()).hexdigest() == TARGET:
                found = candidate
                break
        if found:
            break
    if found is None:
        return {'status': 'not_found_in_bounded_directory_listing'}
    result = {'status': 'found', 'job_id': found, 'objects': {}}
    for suffix in ['result.json.gz', 'audit/manifest.json']:
        blob = bucket.blob('jobs/' + found + '/' + suffix)
        try:
            blob.reload(timeout=30)
            if blob.size > 64 * 1024 * 1024:
                result['objects'][suffix] = {'status': 'over_probe_size_limit', 'bytes': blob.size}
                continue
            data = blob.download_as_bytes(if_generation_match=blob.generation, timeout=60)
            if suffix.endswith('.gz'):
                data = gzip.decompress(data)
            result['objects'][suffix] = json.loads(data)
        except Exception as exc:
            result['objects'][suffix] = {'error_type': type(exc).__name__}
    return result

try:
    request = json.loads(Path('.cloud-agent/requests/private-run-cost-probe.json').read_text())
    assert request == {'schema_version': 1, 'action': 'read-selected-saved-result-encrypted', 'sequence': 1}
    report = probe()
except Exception as exc:
    report = {'status': 'read_failed', 'error_type': type(exc).__name__}

public = serialization.load_pem_public_key(KEY)
secret, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
context = b'keep-and-lease-private-run-probe-v1'
plaintext = gzip.compress(json.dumps(report, separators=(',', ':'), allow_nan=False).encode())
body = AESGCM(secret).encrypt(nonce, plaintext, context)
wrapped = public.encrypt(secret, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=context))
output = Path('private-probe-output'); output.mkdir(exist_ok=True)
encode = lambda value: base64.b64encode(value).decode()
(output/'report.encrypted.json').write_text(json.dumps({'version': 1, 'wrapped_key': encode(wrapped), 'nonce': encode(nonce), 'ciphertext': encode(body)}))
print('Encrypted read-only probe artifact prepared; no private result or credentials logged.')
