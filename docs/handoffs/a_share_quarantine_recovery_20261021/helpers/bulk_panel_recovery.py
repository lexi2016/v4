"""Original producer projections for admitted sources, then one paired merge.

No canonical/source/pointer writes. Reuses the accepted600228 repair tables.
The same canonical full partition only supplies existing defined fields.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import argparse, concurrent.futures, gc, hashlib, importlib.util, json, multiprocessing, os, resource, time
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
R = Path(__file__).resolve().parents[1]
E = 'A_SHARE_QUARANTINE_BULK_PANEL_RECOVERY_20261021_01'

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()
def save(p, x):
    with Path(p).open('x') as f: json.dump(x, f, ensure_ascii=False, indent=2, allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
def stat(p):
    s = Path(p).stat(); return {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size':s.st_size}
def base_module():
    p=R/'helpers/panel_candidate_600228.py';spec=importlib.util.spec_from_file_location('reused_panel_functions',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def stock_worker(task):
    cfg,target,root = task; root=Path(root); code=target['canonical_code']; stage=root/'stocks'/code
    stage.mkdir(mode=0o700,exist_ok=False);began=time.monotonic();result={'canonical_code':code,'input_class':target['input_class'],'status':'FAILED','formula_calls':0}
    try:
        if target.get('reuse_roles'):
            for x in target['reuse_bindings']: assert sha(x['path'])==x['sha256']
            result.update(status='REUSED_ACCEPTED_600228_PRODUCTS',roles=target['reuse_roles'])
        else:
            base=base_module();owner=base.owner_module(cfg,stage)
            for name in ('archive','native'):
                assert sha(target[name+'_path'])==target[name+'_sha256'], 'Frozen source drift:'+name
            archive=base.native(Path(target['archive_path']).read_bytes());native=base.native(Path(target['native_path']).read_bytes())
            first=target['repair_first_date'];last=cfg['target_date'];context=dict(archive)
            for d,b in native.items():
                if max(archive)<d<=last:context[d]=b
            context={d:b for d,b in context.items() if d<=last};candidate={d:b for d,b in context.items() if first<=d<=last}
            assert candidate and max(candidate)==last
            if target['input_class']=='SOURCE_RESTORE':assert candidate==native, 'Admitted candidate/context mismatch'
            context_path=stage/'full_context.day';context_path.open('xb').write(b''.join(context[d] for d in sorted(context)))
            candidate_path=stage/'panel_input_native.day';candidate_path.open('xb').write(b''.join(candidate[d] for d in sorted(candidate)))
            if target['input_class']=='PANEL_ONLY':
                sys.path.insert(0,cfg['worktree']);from ops import a_share_daily_sync as sync
                bars,reason=sync._local_history_status(candidate_path,last)
                violations=sync._local_field_signature_violations(candidate_path,symbol=code[:6],market=int(target['protocol_market']),run_id=E,recorded_at=cfg['recorded_at'])
                assert reason is None and not violations,'Panel-only canonical input rejected original guards'
            hist=owner.read_day_tail(code,context_path,tail_records=len(context));assert len(hist)==len(context)
            old={role:pq.read_table(root/'prefetch'/code/(role+'.parquet')) for role in ('legacy_selector','legacy_backtest')}
            log_stream=(stage/'runtime.log').open('x')
            class Log:
                def log(self,msg):log_stream.write(str(msg)+'\n');log_stream.flush()
            log=Log();selector=old['legacy_selector'];latest=max(map(int,selector['trade_date'].to_pylist()))
            static=owner.read_latest_static_map(root/'prefetch'/code/'legacy_selector.parquet',latest,owner.STATIC_MAP_CANDIDATES,log,active_ts_codes=[code])
            assert not (Path(cfg['tdx_root'])/'T0002/hq_cache/gbbq').exists(),'XDXR source presence drift'
            capture={};original=owner._compute_canonical_v192_formula
            def retain(frame):
                answer=original(frame);capture['full']=answer.copy();return answer
            owner._compute_canonical_v192_formula=retain
            try:
                generated=owner.compute_formula_features(hist,first-1,static,log,emit_all_rows=True,xdxr_events=owner.empty_xdxr_events())
                result['formula_calls']=1
            finally:owner._compute_canonical_v192_formula=original
            supplemental=[]
            for col in capture['full'].columns:
                if col not in generated:generated[col]=capture['full'][col].to_numpy();supplemental.append(col)
            assert owner.audit_pre_close_chain(generated)['status']=='PASS'
            selected=generated[generated['trade_date'].between(first,last)].copy().reset_index(drop=True)
            assert set(map(int,selected['trade_date']))==set(candidate)
            gate=owner.validate_new_selector_rows(selected,selector.schema,last);assert gate['status']=='PASS','Original critical formula gate rejects'
            roles={}
            for role,table in old.items():
                schema=table.schema;old_rows={int(x['trade_date']):x for x in table.to_pylist()};assert len(old_rows)==table.num_rows
                frame=selected.copy()
                if role=='legacy_selector':frame=owner.append_contract_provenance(frame,Path(cfg['panels'][role]['target_path']),owner.CONTRACT_PROVENANCE_FIELD_DEFAULTS['field_contract_version'])
                else:frame=owner.append_backtest_provenance_and_tradeability(frame,Path(cfg['panels'][role]['target_path']))
                missing=[f.name for f in schema if f.name not in frame]
                projected,alignment=owner.build_table_for_schema(frame,schema,'selector' if role=='legacy_selector' else 'backtest',policy=None)
                carry=set(missing)|(set(owner.STATIC_MAP_CANDIDATES)&set(schema.names));nulls={}
                for field in schema:
                    col=field.name
                    if col in cfg['unavailable_derived_columns']:values=[None]*len(frame)
                    elif col in carry:
                        values=[old_rows[int(d)].get(col) if int(d) in old_rows else frame.iloc[i][col]
                            if col in frame and col in owner.STATIC_MAP_CANDIDATES and col!='bars_since_list' else None for i,d in enumerate(frame['trade_date'])]
                    else:continue
                    values=[None if v is None or pd.isna(v) else v for v in values]
                    arr=pa.array(values,type=field.type);projected=projected.set_column(schema.get_field_index(col),field,arr)
                    if arr.null_count:nulls[col]=arr.null_count
                before=table.select(['ts_code','trade_date','close']).to_pandas();before['trade_date']=before['trade_date'].astype(int)
                boundary=owner.audit_increment_boundary(before[before['trade_date']<first],selected)
                assert boundary['status'] in ('PASS','PASS_WITH_XDXR_EXEMPTION'),'Repair-window boundary rejected'
                retire=sorted(d for d in old_rows if first<=d<=last and d not in candidate)
                for col in ('open','high','low','close','amount','volume' if role=='legacy_selector' else 'vol'):
                    expected=owner.coerce_series_to_arrow(selected[col].reset_index(drop=True),schema.field(col))
                    assert projected[col].combine_chunks().equals(expected),'Role raw projection mismatch:'+col
                out=stage/(role+'_repair.parquet');pq.write_table(projected,out)
                roles[role]={'role':role,'repair_table_path':str(out),'repair_table_sha256':sha(out),'repair_rows':projected.num_rows,
                    'retire_keys':[[code,d] for d in retire],'new_inserted_keys':len(set(candidate)-set(old_rows)),
                    'old_outside_window_rows':sum(d<first for d in old_rows),'unknown_null_counts':nulls,'boundary_gate':boundary,
                    'missing_definitions':missing,'alignment_policy_observed':alignment,'full_schema_ready':False}
            log_stream.close();result.update(status='STOCK_FORMULA_AND_REPAIR_TABLES_READY',roles=roles,formula_gate=gate,
                context_rows=len(context),context_first_date=min(context),repair_first_date=first,target_date=last,
                native_projection_path=str(candidate_path),native_projection_sha256=sha(candidate_path),canonical_supplemental_columns=supplemental)
    except Exception as exc:result.update(error_type=type(exc).__name__,error=repr(exc))
    result.update(elapsed_seconds=time.monotonic()-began,process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(stage/'CHECKPOINT.json',result);gc.collect();return result

def main():
    arg=argparse.ArgumentParser();arg.add_argument('phase',choices=('prefetch','canary','remaining','merge'));args=arg.parse_args()
    cfg=json.loads((R/'BULK_PANEL_RECOVERY_CONTRACT.json').read_text());gate=(R/'registry_receipts/BULK_PANEL_RECOVERY_REGISTRY_START.json').read_text()
    assert E in gate and 'RUN_STARTED' in gate
    for x in cfg['input_bindings']:assert sha(x['path'])==x['sha256'],'Frozen input drift'
    root=R/'bulk_panel_recovery'/E;targets=json.loads((R/'BULK_PANEL_RECOVERY_TARGETS.json').read_text())['targets'];base=base_module()
    for p in cfg['panels'].values():assert stat(p['target_path'])==p['stat'] and sha(p['pointer_path'])==p['pointer_sha256']
    began=time.monotonic()
    if args.phase=='prefetch':
        root.mkdir(mode=0o700,parents=True,exist_ok=False);(root/'prefetch').mkdir();(root/'stocks').mkdir()
        codes=[x['canonical_code'] for x in targets]
        for code in codes:(root/'prefetch'/code).mkdir()
        for role,p in cfg['panels'].items():
            table=ds.dataset(p['target_path'],format='parquet').to_table(filter=ds.field('ts_code').isin(codes))
            for code in codes:
                single=table.filter(pc.equal(table['ts_code'],code));assert single.num_rows,'Old stock missing'
                pq.write_table(single,root/'prefetch'/code/(role+'.parquet'))
            del table;gc.collect()
        result={'status':'PREFETCH_COMPLETE','target_count':len(codes),'source_count':354,'panel_only_count':12}
    elif args.phase in ('canary','remaining'):
        assert (root/'prefetch_RECEIPT.json').exists()
        if args.phase=='canary': chosen=[x for x in targets if x['canonical_code'] in cfg['canary_codes']];workers=1
        else:
            prior=json.loads((root/'canary_RECEIPT.json').read_text());assert prior['safe_to_continue']
            chosen=[x for x in targets if not (root/'stocks'/x['canonical_code']/'CHECKPOINT.json').exists()];workers=cfg['workers']
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
            rows=list(pool.map(stock_worker,[(cfg,t,str(root)) for t in chosen]))
        result={'status':'FEATURE_PHASE_COMPLETE','target_count':len(rows),'workers':workers,
                'status_counts':{s:sum(x['status']==s for x in rows) for s in sorted({x['status'] for x in rows})},
                'checkpoints':[{'path':str(root/'stocks'/x['canonical_code']/'CHECKPOINT.json'),'sha256':sha(root/'stocks'/x['canonical_code']/'CHECKPOINT.json')} for x in rows],
                'safe_to_continue':any(x['status']!='FAILED' for x in rows) and all(x['process_peak_rss_bytes']<cfg['max_worker_rss_bytes'] for x in rows)}
    else:
        assert (root/'remaining_RECEIPT.json').exists()
        completed=[json.loads(p.read_text()) for p in sorted((root/'stocks').glob('*/CHECKPOINT.json'))]
        good=[x for x in completed if x['status']!='FAILED'];assert good
        owner=base.owner_module(cfg,root)
        class Log:
            def log(self,msg):print(msg,flush=True)
        roles={}
        for role,p in cfg['panels'].items():
            pieces=[];retire=[]
            for x in good:
                item=x['roles'][role];assert sha(item['repair_table_path'])==item['repair_table_sha256']
                pieces.append(pq.read_table(item['repair_table_path']));retire.extend(tuple(k) for k in item['retire_keys'])
            new=pa.concat_tables(pieces);assert not new.select(['ts_code','trade_date']).to_pandas().duplicated().any()
            staged=root/(role+'_all_repair_rows.parquet');pq.write_table(new,staged)
            output=root/(role+'_UNPUBLISHED_candidate.parquet')
            wr=owner.write_appended_parquet(Path(p['target_path']),new,output,Log(),retire_keys=retire)
            affected={(str(x['ts_code']),int(x['trade_date'])) for x in new.select(['ts_code','trade_date']).to_pylist()}|set(retire)
            oldpf,outpf=pq.ParquetFile(p['target_path']),pq.ParquetFile(output);rg=0;retained=0
            for batch in oldpf.iter_batches(batch_size=65536):
                old=pa.Table.from_batches([batch],schema=oldpf.schema_arrow)
                keep=[(str(x['ts_code']),int(x['trade_date'])) not in affected for x in old.select(['ts_code','trade_date']).to_pylist()]
                expected=old if all(keep) else old.filter(pa.array(keep,type=pa.bool_()))
                if expected.num_rows:base.same_values(expected,outpf.read_row_group(rg));rg+=1;retained+=expected.num_rows
            # Explicit writer may split the combined replacement into several
            # rowgroups; compare the complete tail to the supplied exact table.
            tail=pa.concat_tables([outpf.read_row_group(i) for i in range(rg,outpf.metadata.num_row_groups)])
            base.same_values(new,tail);assert retained==wr['current_rows_retained']
            target_table=ds.dataset(output,format='parquet').to_table(columns=['ts_code','trade_date'],filter=ds.field('trade_date')==(str(cfg['target_date']) if pa.types.is_string(new.schema.field('trade_date').type) else cfg['target_date']))
            all_codes=target_table['ts_code'].to_pylist();assert len(all_codes)==len(set(all_codes))
            roles[role]={'candidate_path':str(output),'candidate_sha256':sha(output),'candidate_stat':stat(output),'writer':wr,
                'repair_table_path':str(staged),'repair_table_sha256':sha(staged),'retire_keys':[list(x) for x in retire],
                'unaffected_rows_all_fields_equal':retained,'mismatch_count':0,'observed_target_count':len(all_codes),'full_schema_ready':False}
            assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss<cfg['max_parent_rss_bytes']
            del oldpf,outpf,new,pieces,tail;gc.collect()
        result={'status':'PAIRED_UNPUBLISHED_BULK_PANEL_CANDIDATES_READY','roles':roles,'successful_codes':[x['canonical_code'] for x in good],
                'failed_codes':[{'canonical_code':x['canonical_code'],'input_class':x['input_class'],'error':x.get('error')} for x in completed if x['status']=='FAILED'],
                'source_restore_count':sum(x['input_class']=='SOURCE_RESTORE' for x in good),'panel_only_count':sum(x['input_class']=='PANEL_ONLY' for x in good)}
    for p in cfg['panels'].values():assert stat(p['target_path'])==p['stat']
    result.update(execution_id=E,phase=args.phase,elapsed_seconds=time.monotonic()-began,process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  canonical_writes=0,pointer_writes=0,network_calls=0,full_schema_ready=False)
    out=root/(args.phase+'_RECEIPT.json');save(out,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('checkpoints','roles','successful_codes')}))

if __name__=='__main__':main()
