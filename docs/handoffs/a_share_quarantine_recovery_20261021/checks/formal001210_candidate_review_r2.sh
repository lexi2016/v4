#!/bin/bash
set -euo pipefail
exec '/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python' -B - <<'PY'
from pathlib import Path
import ast,contextlib,gc,hashlib,importlib.util,io,json,resource,struct,sys,tempfile
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
R=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021');N=R/'windows37_d21_reconcile_20261022';Q=N/'formal001210_repair';V=R/'review/formal001210_repair'
E='A_SHARE_FORMAL001210_PANEL_AND_PUBLISH_INDEPENDENT_REVIEW_20261022_02'
def ck(v,s):
 if not v:raise AssertionError(s)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def stat(p):
 s=Path(p).stat();return {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size':s.st_size}
def module(p,name):
 sp=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(sp);sys.modules[name]=m;sp.loader.exec_module(m);return m
def memory():ck(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss<8*1024**3,'review RSS cap')
def signature(column):
 a=column.combine_chunks();valid=pc.is_valid(a).to_numpy(zero_copy_only=False);out={'dtype':str(a.type),'length':len(a),'null_count':int((~valid).sum()),'valid_mask_sha256':hashlib.sha256(valid.tobytes()).hexdigest()}
 if pa.types.is_floating(a.type):
  width=a.type.bit_width//8;v=np.frombuffer(a.buffers()[1],dtype='<f'+str(width),count=len(a),offset=a.offset*width)[valid] if valid.any() else np.array([],dtype='<f'+str(width));bits=v.view('<u'+str(width));nan=np.isnan(v)
  out.update(valid_value_bits_sha256=hashlib.sha256(v.tobytes()).hexdigest(),valid_nan_count=int(nan.sum()),valid_nan_payload_bits_sha256=hashlib.sha256(bits[nan].tobytes()).hexdigest())
 return out
pkg=read(V/'PACKAGE_R2.json');start=read(R/'registry_receipts/FORMAL001210_PANEL_AND_PUBLISH_REVIEW_R2_REGISTRY_START.json')
ck(pkg['execution_id']==start['execution_id']==E and start['event_type']=='RUN_STARTED' and sha(V/'PACKAGE_R2.json')==start['input_binding_sha256'] and sha(V/'COMMAND_R2.sh')==start['code_sha256'],'independent START identity')
bound={x['path']:x['sha256'] for x in pkg['inputs']};ck(len(bound)==len(pkg['inputs']),'unique bindings')
for p,h in bound.items():ck(sha(p)==h,'frozen drift:'+p)
c=read(Q/'CONTRACT.json');term=read(Q/'WRITER_TERMINAL.json');pub=read(Q/'PUBLISH_CONTRACT_R2.json');prepared=read(Path(pub['stage'])/'PREPARE_RECEIPT.json');root=Q/'runs'/c['execution_id'];target=c['targets'][0];code=target['ts_code'];stage=root/code;cp=read(stage/'CHECKPOINT.json');plan=read(cp['raw_plan_path']);merge=read(root/'merge_RECEIPT.json')
ck(code=='001210.SZ' and c['signal_date']==20261021 and term['exit_code']==0 and len(c['targets'])==1,'single frozen target')
ck(pub['required_review_receipt_path']==str(R/'review/FORMAL001210_PANEL_AND_PUBLISH_REVIEW_R2_RECEIPT_TRANSCRIPTION.json') and not Path(pub['publish_gate_path']).exists() and prepared['status']=='PAIR_PREPARED_NOT_PUBLISHED','new required review/prepare only')
base=module(c['reused_helper_path'],'reviewed_original_recipe_001210');equal=base.same_values
class Log:
 def log(self,x):pass
log=Log();calls=[0];projections={};keys={};data={}
expected_dir=V/'expected_r2';expected_dir.mkdir(exist_ok=False)
with tempfile.TemporaryDirectory(prefix='scratch_',dir=V) as tmp:
 sandbox=Path(tmp);ctx=stage/'full_original_context.day';raw=Path(target['native_path']).read_bytes();ck(sha(target['native_path'])==sha(target['accepted_snapshot_path'])==target['native_sha256'],'accepted source identity')
 ck(len(raw)%32==0,'native32B');records=[raw[i:i+32] for i in range(0,len(raw),32)];dates=[struct.unpack('<I',x[:4])[0] for x in records];ck(dates==sorted(set(dates)) and len(dates)==304 and dates[0]==20250718 and dates[-1]==20261021 and ctx.read_bytes()==raw and sha(ctx)==plan['context_sha256'],'exact304 full accepted context/no future')
 owner=base.owner_module(c,sandbox);hist=owner.read_day_tail(code,ctx,tail_records=304).sort_values('trade_date').reset_index(drop=True);ck(len(hist)==cp['context_rows']==304,'owner full context')
 for i,row in enumerate(records):
  v=struct.unpack('<5If2I',row);h=hist.iloc[i];ck(int(h['trade_date'])==v[0] and h['ts_code']==code and all(float(h[col])==v[j]/100 for col,j in [('open',1),('high',2),('low',3),('close',4)]) and float(h['amount'])==v[5] and float(h['vol'])==float(h['volume'])==v[6],'original source codec')
 olds={}
 for role,p in c['panels'].items():
  ck(stat(p['path'])==p['stat'] and sha(p['pointer_path'])==p['pointer_sha256'],'old authority FAST_BIND');olds[role]=pq.read_table(stage/(role+'_original_stock.parquet'));actual=ds.dataset(p['path'],format='parquet').to_table(filter=ds.field('ts_code')==code);equal(actual,olds[role]);ck(len(set(actual['trade_date'].to_pylist()))==actual.num_rows,'stock key uniqueness')
 latest=max(map(int,olds['legacy_selector']['trade_date'].to_pylist()));static=owner.read_latest_static_map(stage/'legacy_selector_original_stock.parquet',latest,owner.STATIC_MAP_CANDIDATES,log,active_ts_codes=[code]);capture={};original=owner._compute_canonical_v192_formula
 def record(frame):
  calls[0]+=1;ans=original(frame);capture['full']=ans.copy(deep=True);return ans
 owner._compute_canonical_v192_formula=record
 try:
  with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):generated=owner.compute_formula_features(hist,target['repair_first_date']-1,static,log,emit_all_rows=True,xdxr_events=owner.empty_xdxr_events())
 finally:owner._compute_canonical_v192_formula=original
 for col in capture['full']:
  if col not in generated:generated[col]=capture['full'][col].to_numpy()
 ck(calls[0]==1 and generated[['ts_code','trade_date']].astype(str).equals(hist[['ts_code','trade_date']].astype(str)) and owner.audit_pre_close_chain(generated)['status']=='PASS','one original canonical/full context keys')
 for role,old in olds.items():
  r=cp['roles'][role];repair=pq.read_table(r['repair_table_path']);schema=old.schema;vf=c['panels'][role]['volume_field'];before={int(x['trade_date']):x for x in old.to_pylist()};keys[role]=sorted(d for d in before if target['repair_first_date']<=d<=20261021);dd=keys[role];ck(len(dd)==60 and dd==plan['roles'][role]['repair_dates'],'exact60 existing keys')
  frame=generated[generated['trade_date'].isin(dd)].copy().reset_index(drop=True);ck(list(map(int,frame['trade_date']))==dd,'projection key order')
  if role=='legacy_selector':frame=owner.append_contract_provenance(frame,Path(c['panels'][role]['path']),owner.CONTRACT_PROVENANCE_FIELD_DEFAULTS['field_contract_version'])
  else:frame=owner.append_backtest_provenance_and_tradeability(frame,Path(c['panels'][role]['path']))
  carry=(set(schema.names)-set(frame.columns))|(set(owner.STATIC_MAP_CANDIDATES)&set(schema.names))|(set(c['unavailable_derived_columns'])&set(schema.names));index={int(d):i for i,d in enumerate(old['trade_date'].to_pylist())};taken=old.take(pa.array([index[d] for d in dd],type=pa.int64()));arrays=[taken[f.name].combine_chunks() if f.name in carry else owner.coerce_series_to_arrow(frame[f.name].reset_index(drop=True),f) for f in schema];projected=pa.Table.from_arrays(arrays,schema=schema);equal(projected,repair)
  ep=expected_dir/(role+'_independent_expected.parquet')
  with ep.open('xb') as f:pq.write_table(projected,f)
  checkpoint={'checkpoint':'EXPECTED_PROJECTION_VALUES_PASS','execution_id':E,'role':role,'scope':'original304 owner projection equals repair values; carry rawplan and streaming NOT_YET_VERIFIED','path':str(ep),'sha256':sha(ep),'input_binding_sha256':sha(V/'PACKAGE_R2.json'),'command_sha256':sha(V/'COMMAND_R2.sh')}
  with (expected_dir/(role+'_CHECKPOINT.json')).open('x') as f:json.dump(checkpoint,f,sort_keys=True);f.write('\n')
  print(json.dumps(checkpoint,sort_keys=True),flush=True)
  ck(carry==(set(r['same_key_preserved_columns'])&set(schema.names)),'carry definition')
  obs=read(stage/(role+'_CARRY_BIT_OBSERVATIONS.json'));sigs={}
  for col in sorted(carry):
   sig=signature(taken[col]);ck(sig==signature(repair[col]),'carry mask/VALIDbits:'+col);sigs[col]=sig
   for version in ['original','persisted']:ck(all(obs[col][version][k]==v for k,v in sig.items()),'saved carry observation:'+col)
  expected={};byhist={int(x['trade_date']):x for x in hist.to_dict('records')}
  for col in ['open','high','low','close','amount','volume']:
   name=vf if col=='volume' else col;vals=owner.coerce_series_to_arrow(pd.Series([byhist[d][name] for d in dd]),schema.field(name)).to_pylist()
   for d,v in zip(dd,vals):
    if before[d][name]!=v:expected[(d,name)]=(before[d][name],v)
   d21=pa.scalar('20261021' if pa.types.is_string(schema.field('trade_date').type) else 20261021,type=schema.field('trade_date').type);equal(taken.filter(pc.equal(taken['trade_date'],d21)).select([name]),repair.filter(pc.equal(repair['trade_date'],d21)).select([name]))
  approved={(int(d),vf if col=='volume' else col) for d,cols in target['allowed_raw_cells'].items() for col in cols};observed={(int(x['trade_date']),x['column']):(x['old'],x['accepted_native_owner_dtype']) for x in plan['roles'][role]['raw_changes']};ck(set(expected)==approved and expected==observed and len(expected)==20 and not plan['failures'],'exact20 approved rawcells')
  ck(r['replaced_keys']==repair.num_rows==60 and r['inserted_keys']==0 and r['retire_keys']==[],'row conservation');projections[role]=projected;data[role]={'existing_keys':60,'raw_cells':20,'carry_columns':len(carry),'expected_projection':{'path':r['repair_table_path'],'sha256':r['repair_table_sha256']},'carry_digest':hashlib.sha256(json.dumps(sigs,sort_keys=True).encode()).hexdigest()}
 print(json.dumps({'checkpoint':'STOCK_PROJECTION_PASS','execution_id':E,'stock':code,'context_bars':304,'new_canonical_calls':1,'roles':data},sort_keys=True),flush=True);del owner,hist,generated,olds,actual;gc.collect();memory()
 preservation={}
 for role,p in c['panels'].items():
  mr=merge['roles'][role];candidate=Path(mr['candidate_path']);ck(stat(candidate)==mr['candidate_stat'] and stat(p['path'])==p['stat'],'candidate FAST_BIND');equal(projections[role],pq.read_table(mr['repair_table_path']));oldpf=pq.ParquetFile(p['path']);newpf=pq.ParquetFile(candidate);ck(oldpf.schema_arrow.equals(newpf.schema_arrow,check_metadata=False) and oldpf.metadata.num_rows==newpf.metadata.num_rows,'unchanged schema/rows');rg=0;retained=0;replaced=0
  for batch in oldpf.iter_batches(batch_size=65536):
   t=pa.Table.from_batches([batch],schema=oldpf.schema_arrow);vals=pa.array([str(d) for d in keys[role]] if pa.types.is_string(t.schema.field('trade_date').type) else keys[role],type=t.schema.field('trade_date').type);mask=pc.and_(pc.equal(t['ts_code'],code),pc.is_in(t['trade_date'],value_set=vals));replaced+=pc.sum(pc.cast(mask,pa.int64())).as_py();keep=t.filter(pc.invert(mask))
   if keep.num_rows:equal(keep,newpf.read_row_group(rg));rg+=1;retained+=keep.num_rows
   memory()
  tail=pa.concat_tables([newpf.read_row_group(i) for i in range(rg,newpf.metadata.num_row_groups)]);equal(projections[role],tail);wr=mr['writer'];ck(replaced==wr['current_rows_replaced']==wr['new_rows_supplied']==60 and wr['current_rows_retired']==wr['new_rows_inserted']==0 and retained==wr['current_rows_retained']==mr['all_unaffected_fields_equal_rows'] and retained+60==wr['total_rows_expected']==newpf.metadata.num_rows,'wholepanel exact conservation')
  pp=pub['panels'][role];ck(pp['candidate_path']==str(candidate) and pp['candidate_stat']==mr['candidate_stat'] and pp['new_sha256']==mr['candidate_sha256'] and pp['old_path']==p['path'] and pp['old_sha256']==p['reported_certified_sha256'],'new publish old/new identity');ck(sha(pp['pointer_path'])==pp['old_pointer_sha256']==p['pointer_sha256'] and Path(pp['pointer_path']).read_text().strip()==pp['old_path'] and not Path(pp['new_path']).exists(),'unpublished real pointers');pre=prepared['pointer_preimages'][role];ck(sha(pre['path'])==pre['sha256']==pp['old_pointer_sha256'],'exact prepared preimage');preservation[role]={'unaffected_rows':retained,'replaced':60,'inserted':0,'retired':0};del oldpf,newpf,t,tail,keep;gc.collect();memory()
 print(json.dumps({'checkpoint':'DATA_SCOPE_PASS','execution_id':E,'roles':preservation,'new_canonical_calls':1,'old_scope_calls':0,'real_native_pointer_writes':0},sort_keys=True),flush=True)
 reuse=read(Q/'PUBLISH_LOGIC_REUSE.json');oldsource=Path(reuse['baseline_source']).read_text();newsource=Path(reuse['new_source']).read_text();expected=oldsource.replace("N=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021/windows37_d21_reconcile_20261022')","N=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021/windows37_d21_reconcile_20261022/formal001210_repair')").replace('A_SHARE_WINDOWS37_D21_PAIR_PUBLISH_20261022_R4_01','A_SHARE_FORMAL001210_PAIR_PUBLISH_20261022_01').replace('PUBLISH_CONTRACT_R4.json','PUBLISH_CONTRACT.json').replace("['920146.BJ','301087.SZ']","['001210.SZ']");ck(newsource==expected,'exact unchanged publisher logic metadata-only substitutions');ck(sha(reuse['baseline_source'])==reuse['baseline_sha256'] and sha(reuse['new_source'])==reuse['new_sha256'],'publisher source reuse identity')
 more=read(Q/'PUBLISH_R2_LOGIC_REUSE.json');prev=Path(more['prior_source']['path']).read_text();current=Path(more['new_source']['path']).read_text();ck(sha(more['prior_source']['path'])==more['prior_source']['sha256']==reuse['new_sha256'] and sha(more['new_source']['path'])==more['new_source']['sha256']==pub['helper_sha256'],'R2 publisher identity')
 oldtree=ast.parse(prev.replace('PUBLISH_CONTRACT.json','PUBLISH_CONTRACT_R2.json'));newtree=ast.parse(current)
 for name in ['gate','rollback','publish','frozen','prepare']:
  a=next(x for x in oldtree.body if isinstance(x,ast.FunctionDef) and x.name==name);b=next(x for x in newtree.body if isinstance(x,ast.FunctionDef) and x.name==name);ck(ast.dump(a)==ast.dump(b),'unchanged R2 transaction:'+name)
 ck(prepared['execution_id']==pub['execution_id'] and prepared['versioned_from_prior_prepare']==pub['prior_prepare_receipt'] and sha(pub['prior_prepare_receipt']['path'])==pub['prior_prepare_receipt']['sha256'] and prepared['dummy_tests_run']==0 and prepared['formula_calls']==0,'new actual metadata-only prepare')
 for obj in [c,term,pub]:ck(obj['research_only'] is True and obj['production_allowed'] is False and obj['buy_gate_updated'] is False and obj['orders_sent'] is False,'research boundary')
 ck(term['native_writes']==term['pointer_writes']==term['authority_writes']==term['network_calls']==0,'real mutation boundary');memory()
 print(json.dumps({'verdict':'REVIEWED/PASS','execution_id':E,'behavior_verified':'001210 only original304bar owner projection/20rawcells/60samekeys-perrole/VALIDcarrybits/allunaffected/newpublishbindings','publisher_logic':'exact unchanged R4 reused independent9tests','new_original_canonical_calls':1,'real_native_pointer_writes':0,'large_panel_hashes':0,'publish_permission':False,'cannot_confirm':['actualpublication/replay pending','full207/API/UI/Windowsengine parity','allA1020']},sort_keys=True),flush=True)
PY
