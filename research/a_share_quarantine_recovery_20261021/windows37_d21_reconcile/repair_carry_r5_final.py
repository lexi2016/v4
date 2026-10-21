"""Repair only same-key Arrow carry masks in saved two-stock products.

No formula, native, archive or market-source comparison is invoked. All defined
columns reuse the actual R3 projection; carried columns use original Arrow take.
"""
import sys
sys.dont_write_bytecode=True
import argparse,hashlib,importlib.util,json,os,resource,time
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
N=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021/windows37_d21_reconcile_20261022')
E='A_SHARE_WINDOWS37_D21_CARRY_MASK_REPAIR_20261022_R5_FINAL_01'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):
 with Path(p).open('x')as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def stat(p):
 s=Path(p).stat();return {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size':s.st_size}
def load(p,name):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def frozen(cfg):
 for x in cfg['input_bindings']:assert sha(x['path'])==x['sha256'],'Frozen saved input drift:'+x['path']
 for p in cfg['panels'].values():
  assert stat(p['path'])==p['stat']and sha(p['pointer_path'])==p['pointer_sha256']
  assert Path(p['pointer_path']).read_text(encoding='utf-8-sig').strip()==p['path']
def array_observation(array):
 arr=array.combine_chunks();dtype=str(arr.type);valid=pc.is_valid(arr).to_numpy(zero_copy_only=False)
 logical=arr.cast(arr.type.value_type) if pa.types.is_dictionary(arr.type) else arr
 nonnull=logical.filter(pc.is_valid(logical));h=hashlib.sha256(dtype.encode()+valid.tobytes())
 observation={'dtype':dtype,'length':len(arr),'null_count':arr.null_count,'valid_mask_sha256':hashlib.sha256(valid.tobytes()).hexdigest()}
 if pa.types.is_floating(nonnull.type)or pa.types.is_integer(nonnull.type)or pa.types.is_boolean(nonnull.type):
  values=nonnull.to_numpy(zero_copy_only=False);payload=values.tobytes();h.update(payload)
  observation['valid_value_bits_sha256']=hashlib.sha256(payload).hexdigest()
  if pa.types.is_floating(nonnull.type):
   nan=np.isnan(values);bits=values.view(np.uint64 if nonnull.type.bit_width==64 else np.uint32)
   observation.update(valid_nan_count=int(nan.sum()),valid_nan_payload_bits_sha256=hashlib.sha256(bits[nan].tobytes()).hexdigest())
 else:
  # Only the actual valid string/binary values; no IPC/schema metadata/layout.
  for value in nonnull.to_pylist():
   payload=value if isinstance(value,bytes)else value.encode('utf-8')if isinstance(value,str)else json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode('utf-8')
   h.update(len(payload).to_bytes(8,'little'));h.update(payload)
 observation['validity_and_valid_values_sha256']=h.hexdigest()
 observation['null_slot_value_payload']='UNSPECIFIED_BY_ARROW_NOT_A_VALUE_NOT_COMPARED'
 return observation

def array_digest(array):return array_observation(array)['validity_and_valid_values_sha256']
def keys(table):return [(str(r['ts_code']),int(r['trade_date']))for r in table.select(['ts_code','trade_date']).to_pylist()]
def patch(cfg,target,root,base):
 code=target['ts_code'];stage=root/code;stage.mkdir();roles={}
 for role,entry in target['roles'].items():
  original=pq.read_table(entry['original_stock_path']);prior=pq.read_table(entry['repair_table_path']);oldkeys=keys(original);newkeys=keys(prior)
  assert len(set(oldkeys))==len(oldkeys)and len(set(newkeys))==len(newkeys)
  index={key:i for i,key in enumerate(oldkeys)};assert all(k in index for k in newkeys)
  take=original.take(pa.array([index[k]for k in newkeys],type=pa.int64()))
  carry=[c for c in entry['same_key_preserved_columns']if c in prior.schema.names]
  fixed=prior
  for col in carry:
   assert take.schema.field(col)==prior.schema.field(col)
   fixed=fixed.set_column(prior.schema.get_field_index(col),prior.schema.field(col),take[col])
  noncarry=[c for c in prior.schema.names if c not in carry]
  base.same_values(prior.select(noncarry),fixed.select(noncarry))
  base.same_values(take.select(carry),fixed.select(carry))
  assert keys(fixed)==newkeys
  for col in carry:assert array_digest(fixed[col])==array_digest(take[col]),'Carry validity/NaN payload drift:'+col
  path=stage/(role+'_repair.parquet')
  reuse=cfg.get('reuse_partial_selector')if code=='920146.BJ'and role=='legacy_selector'else None
  if reuse:
   assert sha(reuse['path'])==reuse['sha256'];os.link(reuse['path'],path)
  else:pq.write_table(fixed,path)
  persisted=pq.read_table(path);base.same_values(fixed,persisted)
  observations={col:{'original':array_observation(take[col]),'persisted':array_observation(persisted[col])}for col in carry}
  save(stage/(role+'_CARRY_BIT_OBSERVATIONS.json'),observations)
  for col in carry:assert array_digest(persisted[col])==array_digest(take[col]),'Valid value/NaN payload or validity roundtrip drift:'+col
  vf=cfg['panels'][role]['volume_field'];d21=str(cfg['signal_date'])if pa.types.is_string(fixed.schema.field('trade_date').type)else cfg['signal_date']
  a=fixed.filter(pc.equal(fixed['trade_date'],d21));b=take.filter(pc.equal(take['trade_date'],d21))
  base.same_values(a.select(['open','high','low','close','amount',vf]),b.select(['open','high','low','close','amount',vf]))
  maskcounts={col:{'prior_nulls':prior[col].null_count,'original_nulls':take[col].null_count,'fixed_nulls':persisted[col].null_count}for col in carry}
  roles[role]={'repair_table_path':str(path),'repair_table_sha256':sha(path),'repair_rows':fixed.num_rows,
   'same_key_preserved_columns':carry,'carry_original_validity_and_valid_bit_sha256':{col:array_digest(take[col])for col in carry},
   'noncarry_prior_validity_and_valid_bit_sha256':{col:array_digest(prior[col])for col in noncarry},'carry_null_counts':maskcounts,
   'noncarry_values_unchanged':True,'D21_raw_exact_preserved':True,'retire_keys':[],'inserted_keys':0,'replaced_keys':fixed.num_rows,
   'prior_repair_table':{'path':entry['repair_table_path'],'sha256':entry['repair_table_sha256']},'formula_calls':0,'source_comparison_calls':0}
 result={'execution_id':E,'ts_code':code,'status':'SAVED_PRODUCTS_ARROW_CARRY_MASK_REPAIRED','roles':roles,
  'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'formula_calls':0,'source_comparison_calls':0,
  'native_writes':0,'authority_writes':0,'pointer_writes':0,'network_calls':0}
 save(stage/'CHECKPOINT.json',result);return result
def main():
 p=argparse.ArgumentParser();p.add_argument('phase',choices=('canary','remaining','merge'));args=p.parse_args()
 cfg=json.loads((N/'CARRY_R5_FINAL_CONTRACT.json').read_text());start=json.loads(Path(cfg['start_receipt']).read_text());assert start['execution_id']==E and start['event_type']=='RUN_STARTED'
 frozen(cfg);root=N/'runs'/E;began=time.monotonic();base=load(cfg['reused_helper_path'],'unchanged_original_recipe_for_masks')
 if args.phase=='canary':root.mkdir(parents=True,exist_ok=False);result=patch(cfg,cfg['targets'][0],root,base)
 elif args.phase=='remaining':
  assert json.loads((root/'canary_RECEIPT.json').read_text())['safe_to_continue'];result=patch(cfg,cfg['targets'][1],root,base)
 else:
  assert json.loads((root/'remaining_RECEIPT.json').read_text())['safe_to_continue']
  previous=load(cfg['prior_merge_helper_path'],'unchanged_exactkey_paired_merge');result=previous.merge(cfg,root,base)
 frozen(cfg);peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;assert peak<cfg['max_rss_bytes']
 result.update(execution_id=E,phase=args.phase,elapsed_seconds=time.monotonic()-began,peak_rss_bytes=peak,safe_to_continue=True,
               formula_calls=0,source_comparison_calls=0,native_writes=0,authority_writes=0,pointer_writes=0,network_calls=0)
 save(root/(args.phase+'_RECEIPT.json'),result)
 print(json.dumps({k:v for k,v in result.items()if k!='roles'},ensure_ascii=False))
if __name__=='__main__':main()
