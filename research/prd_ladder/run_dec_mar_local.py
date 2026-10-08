from pathlib import Path
import json,sys
from replay import load_rows
from run_policies import run_cases

if __name__=='__main__':
    root=Path(sys.argv[1]);out=Path(sys.argv[2]);names=sys.argv[3:] or None
    spec=json.loads((root/'specification.json').read_text());seeds=json.loads((root/'seeds.json').read_text())
    events,coverage=load_rows(sorted((root/'inputs').glob('*.jsonl.gz')),spec['symbols'],spec['start'],spec['end'])
    assert len(events)==462642
    print(json.dumps({'stage':'loaded_verified_dec_mar','events':len(events)}),flush=True)
    run_cases(events,coverage,spec['symbols'],spec['expiry'],seeds,spec['start'],spec['end'],out,names)
