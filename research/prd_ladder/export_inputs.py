"""Bounded export of the same immutable, verified public market-data inputs."""
from pathlib import Path
import hashlib,json,zipfile
import cloud_run

class ExportComplete(Exception):pass

def export(events,coverage,symbols,expiry,seeds,start,end,out,names=None):
    target=Path('ladder-inputs');target.mkdir(exist_ok=True)
    archive=target/'Dec26_Mar27_verified_inputs.zip'
    assert len(coverage)==180 and len(events)==462642
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for item in coverage:
            p=Path(item['path']);assert p.parent==Path('work/prd-ladder')
            assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
            z.write(p,'inputs/'+p.name)
        z.writestr('seeds.json',json.dumps(seeds))
        z.writestr('input_coverage.json',json.dumps(coverage))
        z.writestr('specification.json',json.dumps(dict(symbols=symbols,expiry=expiry,start=start,end=end)))
        z.write(Path(out)/'source_receipts.json','source_receipts.json')
    meta=dict(file=archive.name,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),bytes=archive.stat().st_size,
              files=len(coverage),ordinary_events=len(events))
    (target/'receipt.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta),flush=True)
    raise ExportComplete

if __name__=='__main__':
    request=json.loads(Path('.cloud-agent/requests/prd-input-export.json').read_text())
    assert request==dict(schema_version=1,action='export-verified-dec26-mar27-inputs')
    cloud_run.run_cases=export
    try:cloud_run.main()
    except ExportComplete:pass
