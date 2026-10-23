"""Frozen local D22 reader, canary gate and bounded ten-route OR recall executor."""
from __future__ import annotations
import sys
sys.dont_write_bytecode=True
import argparse,csv,hashlib,importlib.util,json,multiprocessing,os,resource,time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import formula_kernel as kernel

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def stat(p):
    x=Path(p).stat();return dict(inode=x.st_ino,mtime_ns=x.st_mtime_ns,size_bytes=x.st_size)
def fence(event,args):
    if event.startswith(('socket.connect','socket.bind','sqlite3.connect')):raise RuntimeError('FORBIDDEN_MARKET_PROVIDER')
def universe(c):
    with Path(c['universe_path']).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==5812 and len({r['ts_code'] for r in rows})==5812
    return sorted([r for r in rows if r['trade_date']==c['signal_date']],key=lambda r:r['ts_code']),sorted([r for r in rows if r['trade_date']!=c['signal_date']],key=lambda r:r['ts_code'])
def read_inputs(c,codes):
    import pyarrow.dataset as ds
    import pyarrow as pa
    b=json.loads(Path(c['mac_binding_path']).read_text());p=Path(b['selector']['target_path']);assert stat(p)==b['selector']['target_stat'],'PANEL_DRIFT'
    # Full available prefix through the signal cutoff, with no future/amount/label columns.
    predicate=ds.field('ts_code').isin(codes)&(ds.field('trade_date')<=c['signal_date'])
    batches=[];n=0
    for batch in ds.dataset(str(p),format='parquet').scanner(columns=['ts_code','trade_date','close','high','low','volume'],filter=predicate,batch_size=65536,use_threads=False).to_batches():
        n+=batch.num_rows;assert n<=c['max_input_rows'],'ROW_BOUND';batches.append(batch)
    frame=pa.Table.from_batches(batches).to_pandas();del batches
    frame=frame.sort_values(['ts_code','trade_date']);assert not frame.duplicated(['ts_code','trade_date']).any(),'DUPLICATE_KEYS'
    samples={}
    for code,stock in frame.groupby('ts_code',sort=False):
        dates=stock['trade_date'].astype(str).tolist();assert dates[-1]==c['signal_date'],'STALE_CURRENT_CODE:'+code
        samples[code]=dict(code=code,dates=dates,raw={k:stock[v].to_numpy(dtype=float,copy=True) for k,v in [('C','close'),('H','high'),('L','low'),('VOL','volume')]})
    assert set(samples)==set(codes),'INPUT_CODE_COVERAGE';assert stat(p)==b['selector']['target_stat'],'PANEL_CHANGED';return samples
def serializable_sample(s):return dict(code=s['code'],dates=s['dates'],raw={k:[float(x) if np.isfinite(x) else None for x in v] for k,v in s['raw'].items()})
def input_identity(s):return kernel.canonical_sha(serializable_sample(s))
def evaluate_chunk(samples):
    sys.addaudithook(fence);out=[]
    for s in samples:
        try:
            row=kernel.evaluate_stock(s['code'],s['dates'],s['raw']);row['row_identity_sha256']=input_identity(s)
        except Exception as exc:
            row=dict(code=s['code'],signal_date='20261022',history_rows=len(s['dates']),history_start=s['dates'][0],history_end=s['dates'][-1],candidate='UNKNOWN',execution_status='FAILED',hit_rules=[],unknown_rules=list(kernel.RULES),rules=[dict(rule_id=x,source_name=kernel.RULES[x],status='DATA_UNAVAILABLE',value=None,reason='EXECUTION_ERROR:'+type(exc).__name__+':'+str(exc),evidence={}) for x in kernel.RULES],error_type=type(exc).__name__,error=str(exc),row_identity_sha256=input_identity(s),indicators={},risks={})
        out.append(row)
    return out
def csv_write(p,fields,rows):
    with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def write_outputs(c,rows,today,stale,out,elapsed):
    names={r['ts_code']:r['name'] for r in today};rows=sorted(rows,key=lambda r:r['code']);assert len(rows)==len(today) and len({r['code'] for r in rows})==len(today)
    with (out/'ALL_STOCK_RESULTS.jsonl').open('w') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    long=[];union=[];counts={rid:Counter() for rid in kernel.RULES}
    for row in rows:
        code=row['code'];name=names[code]
        for rule in row['rules']:
            counts[rule['rule_id']][rule['status']]+=1;long.append(dict(code=code,name=name,signal_date=c['signal_date'],selection_date=c['selection_date'],rule_id=rule['rule_id'],status=rule['status'],reason=rule['reason'] or '',stock_execution_status=row['execution_status'],candidate=row['candidate'],history_rows=row['history_rows'],row_identity_sha256=row['row_identity_sha256'],indicators=json.dumps(row['indicators'],ensure_ascii=False),rule_evidence=json.dumps(rule['evidence'],ensure_ascii=False)))
        if row['candidate']=='YES':union.append(dict(code=code,name=name,signal_date=c['signal_date'],selection_date=c['selection_date'],hit_rules='|'.join(row['hit_rules']),unknown_rules='|'.join(row['unknown_rules']),execution_status=row['execution_status'],history_start=row['history_start'],history_rows=row['history_rows'],row_identity_sha256=row['row_identity_sha256'],risks=json.dumps(row['risks'],ensure_ascii=False),price_basis='RAW_UNADJUSTED'))
    csv_write(out/'SIGNAL_CANDIDATES.csv',list(long[0]),long)
    fields=['code','name','signal_date','selection_date','hit_rules','unknown_rules','execution_status','history_start','history_rows','row_identity_sha256','risks','price_basis']
    csv_write(out/'UNION_CANDIDATES.csv',fields,union)
    for rid in kernel.RULES:csv_write(out/(rid+'_CANDIDATES.csv'),fields,[r for r in union if rid in r['hit_rules'].split('|')])
    coverage=[dict(rule_id=rid,TRIGGERED=counts[rid]['TRIGGERED'],NOT_TRIGGERED=counts[rid]['NOT_TRIGGERED'],DATA_UNAVAILABLE=counts[rid]['DATA_UNAVAILABLE']) for rid in kernel.RULES]
    csv_write(out/'RULE_COVERAGE.csv',list(coverage[0]),coverage)
    csv_write(out/'SOURCE_STALE_EXCLUDED.csv',list(stale[0]),stale)
    errors=[dict(code=r['code'],execution_status=r['execution_status'],unknown_rules=r['unknown_rules'],raw_invalid_counts=r.get('raw_invalid_counts'),error=r.get('error')) for r in rows if r['execution_status']!='COMPLETE'];save(out/'COVERAGE_ERRORS.json',errors)
    states=Counter(r['execution_status'] for r in rows);candidates=Counter(r['candidate'] for r in rows)
    assert 5812==len(stale)+len(rows) and len(rows)==sum(states.values()) and all(sum(v.values())==len(rows) for v in counts.values())
    summary=dict(status='FULL_RESULT_PENDING_INDEPENDENT_READBACK',execution_id=c['execution_id'],signal_asof=c['signal_date'],selection_date=c['selection_date'],source_members=5812,pre_scan_excluded=len(stale),scan_requested=len(rows),COMPLETE=states['COMPLETE'],PARTIAL=states['PARTIAL'],FAILED=states['FAILED'],NOT_SCANNED=0,candidate_YES=candidates['YES'],candidate_NO=candidates['NO'],candidate_UNKNOWN=candidates['UNKNOWN'],rule_coverage=coverage,union_count=len(union),multi_label_count=sum(len(r['hit_rules'].split('|'))>1 for r in union),elapsed_seconds=elapsed,rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,price_basis='RAW_UNADJUSTED',numerical_identity='FORMULA_FILE_REPLICA_NOT_LIVE_PLATFORM_PARITY',source_panel_sha_policy='Reuse original same-turn full SHA with unchanged inode/mtime/size; no new full-file certification',top_code_examples=union[:10],research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,second_screen_executed=False)
    save(out/'RESULT_RECEIPT.json',summary)
    report=['十类宽进初选（formula_file_replica；非live Futu数值认证）',f"信号20261022，选股展示20261023，RAW_UNADJUSTED。完整初选 {len(union)} 只，按代码排列，不表示买入顺序。",f"请求{len(rows)}；COMPLETE {states['COMPLETE']} / PARTIAL {states['PARTIAL']} / FAILED {states['FAILED']}；318来源陈旧单列。",'未知不当未命中；任一已知命中即可入池，风险不提前删除；无共振、TopN或标签数门。','本次未执行第二层当日筛选、回测、训练、V4页面或交易。']
    (out/'REPORT.md').write_text('\n\n'.join(report)+'\n');return summary

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--contract',required=True);args=parser.parse_args();cp=Path(args.contract);c=json.loads(cp.read_text());out=Path(c['output_directory']);out.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    sys.path.insert(0,c['registrar_directory']);from mac_registry import register
    register(cp,'RUN_STARTED',c['stage_prefix']+'_STARTED',decision='RUNNING')
    try:
        for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'SOURCE_DRIFT:'+p
        sys.addaudithook(fence);today,stale=universe(c);assert len(today)==5494 and len(stale)==318
        if c['mode']=='canary':
            codes=['600000.SH','000001.SZ','920000.BJ']
            if c.get('reuse_canary_input'):
                prior=Path(c['reuse_canary_input']);assert sha(prior)==c['reuse_canary_input_sha256']
                b=json.loads(Path(c['mac_binding_path']).read_text());assert stat(b['selector']['target_path'])==b['selector']['target_stat'],'REUSE_PANEL_DRIFT'
                samples={s['code']:dict(code=s['code'],dates=s['dates'],raw={k:np.asarray(v,dtype=float) for k,v in s['raw'].items()}) for s in json.loads(prior.read_text())};assert set(samples)==set(codes)
            else:samples=read_inputs(c,codes)
            serialized=[serializable_sample(samples[x]) for x in codes];save(out/'LOCAL_CANARY_INPUT.json',serialized)
            save(out/'CANARY_INPUT_MANIFEST.json',dict(owner_binding_sha256=sha(c['mac_binding_path']),source_panel=json.loads(Path(c['mac_binding_path']).read_text())['selector'],signal_asof=c['signal_date'],selection_date=c['selection_date'],samples=[dict(code=s['code'],sha256=input_identity(s),history_start=s['dates'][0],history_rows=len(s['dates']),last_date=s['dates'][-1]) for s in samples.values()]))
            register(cp,'CHECKPOINT',c['stage_prefix']+'_INPUT_BOUND',[out/'CANARY_INPUT_MANIFEST.json'],dict(real_symbols=3),decision='INPUT_BOUND_BEFORE_CANARY')
            import test_canary
            receipt=test_canary.run([samples[x] for x in codes]);receipt.update(elapsed_seconds=time.monotonic()-start,rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,local_input_sha256=sha(out/'LOCAL_CANARY_INPUT.json'),input_manifest_sha256=sha(out/'CANARY_INPUT_MANIFEST.json'));save(out/'CANARY_RECEIPT.json',receipt)
            terminal=register(cp,'TERMINAL',c['stage_prefix']+'_TERMINAL',[out/'CANARY_RECEIPT.json',out/'CANARY_INPUT_MANIFEST.json'],dict(real_symbols=3,true_routes=len(receipt['true_fixtures'])),decision='CANARY_READY_FOR_INDEPENDENT_REVIEW');print(json.dumps(receipt,ensure_ascii=False),flush=True)
        elif c['mode']=='full':
            gate=Path(c['independent_canary_receipt']);assert sha(gate)==c['independent_canary_receipt_sha256'];accepted=json.loads(gate.read_text());assert accepted['status']=='PASS_TEN_ROUTE_CANARY_ONLY','INDEPENDENT_CANARY_PASS_REQUIRED'
            samples=read_inputs(c,[r['ts_code'] for r in today]);chunks=[today[i:i+c['chunk_size']] for i in range(0,len(today),c['chunk_size'])];partdir=out/'parts';partdir.mkdir(exist_ok=True);rows=[];parts=[]
            # At most two independent symbol chunks resident in workers; parent alone persists and registers.
            with ProcessPoolExecutor(max_workers=c['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
                pending=[]
                for i,chunk in enumerate(chunks):
                    pending.append((i,pool.submit(evaluate_chunk,[samples[r['ts_code']] for r in chunk])))
                    if len(pending)<c['workers'] and i+1<len(chunks):continue
                    while pending:
                        index,future=pending.pop(0);part=future.result();path=partdir/(str(index).zfill(3)+'.jsonl')
                        with path.open('w') as f:
                            for r in part:f.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n')
                        rows.extend(part);parts.append(dict(path=str(path),sha256=sha(path),rows=len(part)));register(cp,'CHECKPOINT',c['stage_prefix']+'_CHUNK_'+str(index),[path],dict(completed=len(rows)),decision='RUNNING');print(json.dumps(dict(event='CHUNK_COMPLETE',completed=len(rows),part=index)),flush=True)
            summary=write_outputs(c,rows,today,stale,out,time.monotonic()-start);save(out/'PARTS.json',parts);save(out/'ARTIFACT_MANIFEST.json',dict(files={str(p):sha(p) for p in out.iterdir() if p.is_file() and p.name!='ARTIFACT_MANIFEST.json'},parts=parts));terminal=register(cp,'TERMINAL',c['stage_prefix']+'_TERMINAL',[out/'RESULT_RECEIPT.json',out/'ARTIFACT_MANIFEST.json'],summary,decision='DIRECTION_ONLY_PENDING_INDEPENDENT_READBACK');print(json.dumps(summary,ensure_ascii=False),flush=True)
        else:raise ValueError('UNKNOWN_MODE')
        save(out/'REGISTRY_TERMINAL.json',terminal)
    except BaseException as exc:
        save(out/'FAILURE.json',dict(type=type(exc).__name__,error=str(exc)));register(cp,'TERMINAL',c['stage_prefix']+'_FAILED',[out/'FAILURE.json'],decision='CANNOT_CONFIRM');raise

if __name__=='__main__':main()
