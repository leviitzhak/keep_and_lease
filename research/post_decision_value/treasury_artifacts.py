"""Small checksummed local research bundles, without provisioning or training."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def package(output, archive):
    output=Path(output);archive=Path(archive)
    files={str(p.relative_to(output)):dict(sha256=sha256(p),bytes=p.stat().st_size)
           for p in sorted(output.rglob('*')) if p.is_file() and p.name!='artifact-index.json'}
    (output/'artifact-index.json').write_text(json.dumps(dict(schema='treasury-artifacts-v1',files=files),indent=2))
    archive.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive,'w:gz') as tar:
        tar.add(output,arcname=output.name)
    receipt=dict(file=archive.name,sha256=sha256(archive),bytes=archive.stat().st_size)
    print(json.dumps(receipt));return receipt


def restore(archive, destination, expected_sha256):
    archive=Path(archive);destination=Path(destination)
    if sha256(archive)!=expected_sha256:raise ValueError('Archive checksum mismatch')
    destination.mkdir(parents=True,exist_ok=False)
    with tarfile.open(archive) as tar:
        members=tar.getmembers()
        if len(members)>500 or sum(m.size for m in members)>512*1024*1024:
            raise ValueError('Archive extraction cap')
        for m in members:
            path=Path(m.name)
            if path.is_absolute() or '..' in path.parts or not (m.isfile() or m.isdir()):
                raise ValueError('Unsafe archive member')
        tar.extractall(destination,filter='data')
    indices=list(destination.glob('*/artifact-index.json'))
    if len(indices)!=1:raise ValueError('Expected exactly one run manifest')
    root=indices[0].parent
    for name,entry in json.loads(indices[0].read_text())['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Unsafe manifest path')
        p=root/name
        if p.stat().st_size!=entry['bytes'] or sha256(p)!=entry['sha256']:
            raise ValueError('Artifact checksum mismatch: '+name)
    print(str(root));return root


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('package','restore'))
    p.add_argument('--output',required=True);p.add_argument('--archive',required=True);p.add_argument('--sha256')
    a=p.parse_args()
    if a.command=='package':package(a.output,a.archive)
    else:
        if not a.sha256:p.error('--sha256 is required for restore')
        restore(a.archive,a.output,a.sha256)


if __name__=='__main__':main()
