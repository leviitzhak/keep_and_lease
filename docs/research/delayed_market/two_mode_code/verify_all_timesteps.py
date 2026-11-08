from pathlib import Path
import argparse,gzip,json,numpy as np

def main(root):
 reports=[]
 for folder in sorted(root.glob('root_checkpoints_stage*')):
  stage=int(folder.name.split('stage')[-1]);raw=0;endpoints=0;failures=[];files=sorted(folder.glob('*.json.gz'))
  for path in files:
   z=json.load(gzip.open(path,'rt'));tr=z['trace'];records=z['records']
   if [r['time'] for r in records]!=list(range(tr['start'],tr['end']+1)):failures.append(path.name+': time coverage')
   if any(r['target']!=tr['value'] for r in records):failures.append(path.name+': target')
   raw+=len(records);endpoints+=sum(r['time']==tr['end'] for r in records)
  metadata=root/f'dataset_stage{stage}.json';meta=json.loads(metadata.read_text()) if metadata.exists() else{}
  final_file=root/f'labels_stage{stage}.json.gz';retained=json.load(gzip.open(final_file,'rt')) if final_file.exists() else[]
  report=dict(stage=stage,roots_available=len(files),expected_roots=meta.get('root_count'),raw_all_timestep_records=raw,endpoints_before_split_filter=endpoints,retained_after_split_filter=len(retained),all_timesteps_verified=not failures,stage_targets_complete=bool(meta) and meta['root_count']==len(files),failures=failures)
  if meta and raw-len(retained)!=sum(meta['cross_split_duplicates_dropped'].values()):report['failures'].append('split filter count mismatch');report['all_timesteps_verified']=False
  reports.append(report)
 weights={}
 for path in sorted(root.glob('weights_stage*.npz')):
  data=np.load(path);weights[path.name]=dict(arrays=len(data.files),parameters=sum(data[k].size for k in data.files),all_finite=all(bool(np.isfinite(data[k]).all()) for k in data.files))
 result=dict(stages=reports,weights=weights);(root/'all_timestep_validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 assert all(r['all_timesteps_verified'] for r in reports)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('output',type=Path);main(p.parse_args().output)
