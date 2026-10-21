"""Bounded saved-source OHLC counterfactual; never publishes any authority.

Original evaluator/formula/window and VOL/AMOUNT/date keys are immutable.
Only the nine dates listed by the earlier accepted diagnostic may change.
"""
import sys
sys.dont_write_bytecode = True
import argparse, csv, hashlib, importlib.util, json, math, os, resource, struct, time, zipfile
from pathlib import Path

S = Path(__file__).resolve().parents[1]
E = 'A_SHARE_THREE_MISSING_OHLC_DIAGNOSIS_20261022_01'
RAW = {'O':'open','H':'high','L':'low','C':'close','VOL':'volume','AMOUNT':'amount'}
OHLC = ('open','high','low','close')

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()
def stat(path):
    v=Path(path).stat();return {'inode':v.st_ino,'mtime_ns':v.st_mtime_ns,'size':v.st_size}
def save(path,value):
    with Path(path).open('x') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def scalar(value):
    v=float(value);return v if math.isfinite(v) else None
def native(data,cutoff):
    assert data and len(data)%32==0,'Native framing error'
    rows={};previous=0
    for offset in range(0,len(data),32):
        d=struct.unpack_from('<I',data,offset)[0]
        assert d>previous,'Native duplicate/order error'
        previous=d
        if d>int(cutoff):continue
        words=struct.unpack_from('<IIIIIfII',data,offset)
        rows[str(d)]={'OHLC':dict(zip(OHLC,[v/100 for v in words[1:5]])),
                      'raw_32b_sha256':hashlib.sha256(data[offset:offset+32]).hexdigest()}
    return rows
def raw_fingerprints(raw,dates):
    result={'dates':hashlib.sha256(('\n'.join(dates)+'\n').encode()).hexdigest()}
    for k,v in raw.items():
        result[k]=hashlib.sha256(str(v.dtype).encode()+str(v.shape).encode()+v.tobytes()).hexdigest()
    return result
def write_csv(path,rows):
    if not rows:return
    with Path(path).open('x',encoding='utf-8-sig',newline='')as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def branch_facts(trace,raw,dates):
    names=('JVAL','BKRSI','BKMJ','BKMR','BKUP','BKTURN','BKDAY','BKAMP','BKABSP','BKSTAR','BKGOOD','BKACT',
           'WHT0','YEL0','PCT0','PCT1','B1SIG','B2SIG','B3SIG','BRKPRE','TRUEBR','BKEXIST','BKRES','PRIMARY',
           'SECONDARY','BRICKPOOL','ENTRYPOOL','FRESH','CONT0','RISK0','B2ROLE','B3ROLE','XG')
    out={key:{'D':scalar(trace[key][-1]),'D_minus_1':scalar(trace[key][-2])}for key in names}
    finite=lambda x:math.isfinite(float(x))
    less=lambda a,b:finite(a) and finite(b) and float(a)<float(b)
    ge=lambda a,b:finite(a) and finite(b) and float(a)>=float(b)
    truth=lambda x:finite(x) and float(x)!=0
    parts={'BKUP':truth(trace['BKUP'][-1]),
        'RSI_growth_at_least_15':ge(trace['BKRSI'][-1]-15,trace['BKRSI'][-2]),
        'prior_RSI_below20':less(trace['BKRSI'][-2],20),
        'prior_J_below14':less(trace['JVAL'][-2],14),
        'BKDAY_below_BKAMP_plus0_5':less(trace['BKDAY'][-1],trace['BKAMP'][-1]+0.5),
        'absolute_move_branch':less(trace['BKABSP'][-1],2.3) or (truth(trace['BKSTAR'][-1]) and less(trace['BKABSP'][-1],4)),
        'BKGOOD':truth(trace['BKGOOD'][-1]),'BKACT':truth(trace['BKACT'][-1]),
        'close_at_least_yellow':ge(raw['C'][-1],trace['YEL0'][-1])}
    computed=(parts['BKUP'] and parts['RSI_growth_at_least_15'] and (parts['prior_RSI_below20'] or parts['prior_J_below14'])
        and parts['BKDAY_below_BKAMP_plus0_5'] and parts['absolute_move_branch'] and parts['BKGOOD'] and parts['BKACT'] and parts['close_at_least_yellow'])
    assert computed==truth(trace['BKTURN'][-1]),'Recorded BKTURN branch decomposition differs from original formula'
    return {'D':dates[-1],'D_minus_1':dates[-2],'recorded_vectors':out,'BKTURN_original_threshold_subbranches':parts,
            'BKTURN_reconstructed_from_recorded_vectors':computed,'thresholds_changed':False}

def stock(cfg,target,root):
    import numpy as np
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
    code=target['ts_code'];out=root/code;out.mkdir(mode=0o700,exist_ok=False);started=time.monotonic()
    result={'ts_code':code,'status':'RUNNING','formula_calls':0,'authority_writes':0,'pointer_writes':0,'network_calls':0}
    try:
        archive=cfg['archive'];assert stat(archive['path'])==archive['stat'],'Archive stat drift'
        with zipfile.ZipFile(archive['path'])as z:
            info=z.getinfo(target['archive_member']['member_name'])
            assert info.file_size==int(target['archive_member']['uncompressed_bytes'])
            payload=z.read(info)
        assert hashlib.sha256(payload).hexdigest()==target['archive_member']['uncompressed_member_sha256'],'Archive selected-member SHA drift'
        member_path=out/'archive_member.day';member_path.open('xb').write(payload)
        reference={'archive':native(payload,cfg['signal_date']),'windows':native(Path(target['windows']['path']).read_bytes(),cfg['signal_date']),
                   'accepted_snapshot':native(Path(target['accepted_native']['path']).read_bytes(),cfg['signal_date']),
                   'mac_native':native(Path(target['mac_native']['path']).read_bytes(),cfg['signal_date'])}
        panel=cfg['panel'];assert stat(panel['path'])==panel['stat'],'Certified baseline panel stat drift'
        table=ds.dataset(panel['path'],format='parquet').to_table(columns=['ts_code','trade_date',*RAW.values()],
            filter=(ds.field('ts_code')==code)&(ds.field('trade_date')>=cfg['history_start'])&(ds.field('trade_date')<=cfg['signal_date']))
        frame=table.to_pandas();frame['date8']=frame['trade_date'].astype(str).str.replace('-','',regex=False)
        assert not frame.duplicated(['ts_code','date8']).any();frame=frame.sort_values(['ts_code','date8']).reset_index(drop=True)
        dates=frame['date8'].to_list();assert dates and dates[-1]==cfg['signal_date']
        raw={k:frame[v].to_numpy(copy=True)for k,v in RAW.items()};before_print=raw_fingerprints(raw,dates)
        base_table=pa.Table.from_pandas(frame[['ts_code','trade_date',*RAW.values()]],preserve_index=False)
        pq.write_table(base_table,out/'BASELINE_INPUT.parquet')
        row_index={d:i for i,d in enumerate(dates)}
        comparisons=[];corrected={k:v.copy()for k,v in raw.items()};scope=[]
        for change in target['fixed_prior_mismatch_rows']:
            d=change['trade_date'];assert d in row_index
            values={name:source[d]['OHLC'] for name,source in reference.items()};i=row_index[d]
            consensus=values['archive']==values['windows']
            comparisons.append({'ts_code':code,'trade_date':d,'baseline_OHLC':{f:float(raw[k][i])for f,k in zip(OHLC,('O','H','L','C'))},
                **{name+'_OHLC':values[name]for name in reference},'archive_windows_exact_OHLC_agreement':consensus,
                'native_row_sha256':{name:reference[name][d]['raw_32b_sha256']for name in reference},
                'approved_changed_fields':change['different_OHLC_fields'],
                'baseline_matches_prior_fixed_row':all(raw[k][i]==float(change['local_'+f])for f,k in zip(OHLC,('O','H','L','C'))),
                'cached_windows_matches_prior_fixed_row':all(values['windows'][f]==float(change['windows_'+f])for f in OHLC)})
        control=[]
        if target['control_unchanged']:
            assert not scope
            for name in ('windows','archive','mac_native','accepted_snapshot'):
                overlaps=[d for d in dates if d in reference[name]]
                bad=[d for d in overlaps if any(float(raw[k][row_index[d]])!=reference[name][d]['OHLC'][f]for f,k in zip(OHLC,('O','H','L','C')))]
                control.append({'reference':name,'overlap_dates':len(overlaps),'different_OHLC_dates':bad})
        save(out/'SOURCE_PRICE_COMPARISON.json',{'fixed_rows':comparisons,'unchanged_control':control,
            'archive_member':target['archive_member'],'Windows_run_date_or_formula_body':'CANNOT_CONFIRM'})
        # Persist actual prices before any source-consensus assertion, so a
        # failed hypothesis remains inspectable instead of losing its evidence.
        assert all(x['archive_windows_exact_OHLC_agreement']for x in comparisons),'Archive/Windows source disagreement; no counterfactual permitted'
        assert all(x['baseline_matches_prior_fixed_row']and x['cached_windows_matches_prior_fixed_row']for x in comparisons),'Fixed baseline/Windows row changed'
        assert all(not x['different_OHLC_dates']for x in control),'Previously zero-OHLC-difference control changed; no control adjustment allowed'
        for change in target['fixed_prior_mismatch_rows']:
            d=change['trade_date'];i=row_index[d]
            for field in change['different_OHLC_fields'].split(','):
                key=dict(zip(OHLC,('O','H','L','C')))[field];corrected[key][i]=reference['archive'][d]['OHLC'][field];scope.append((d,key))
        after_print=raw_fingerprints(corrected,dates)
        assert before_print['dates']==after_print['dates'] and before_print['VOL']==after_print['VOL'] and before_print['AMOUNT']==after_print['AMOUNT']
        actual={(dates[i],key)for key in ('O','H','L','C')for i in np.flatnonzero(raw[key]!=corrected[key])}
        assert actual==set(scope),'Counterfactual changed unapproved cells or failed to change a listed mismatch'
        candidate=frame[['ts_code','trade_date',*RAW.values()]].copy()
        for key,col in RAW.items():candidate[col]=corrected[key]
        pq.write_table(pa.Table.from_pandas(candidate,preserve_index=False),out/'COUNTERFACTUAL_INPUT.parquet')
        evaluator=cfg['evaluator'];spec=importlib.util.spec_from_file_location('frozen_original255_three_'+code.replace('.','_'),evaluator['path'])
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        program=module.compile_original(cfg['formula']['path'])
        baseline=module.evaluate(program,raw,code);result['formula_calls']+=1
        expected=target['accepted_baseline_trace'];assert len(baseline)==len(expected['all_255_assignments'])==255
        for name,values in baseline.items():assert scalar(values[-1])==expected['all_255_assignments'][name],'Baseline255 parity failed:'+name
        assert len(dates)==expected['observed_history_bars'] and bool(baseline['XG'][-1])==expected['selected']
        np.savez_compressed(out/'BASELINE_ALL255_VECTORS.npz',**baseline)
        if target['control_unchanged']:
            assert before_print==after_print;counter=baseline;reused_control=True
        else:
            counter=module.evaluate(program,corrected,code);result['formula_calls']+=1;reused_control=False
            np.savez_compressed(out/'COUNTERFACTUAL_ALL255_VECTORS.npz',**counter)
        differences=[{'assignment':name,'baseline_D':scalar(baseline[name][-1]),'counterfactual_D':scalar(counter[name][-1]),
                      'D_changed':scalar(baseline[name][-1])!=scalar(counter[name][-1])}for name in baseline]
        write_csv(out/'LATEST255_COMPONENT_DIFF.csv',differences)
        save(out/'D_AND_PREVIOUS_BRANCH_FACTS.json',{'baseline':branch_facts(baseline,raw,dates),'counterfactual':branch_facts(counter,corrected,dates)})
        result.update(status='ISOLATED_ONE_VARIABLE_DIAGNOSTIC_COMPLETE',baseline_matches_actual33_latest255=True,
            history_bars=len(dates),history_start=cfg['history_start'],signal_date=cfg['signal_date'],
            fixed_mismatch_date_count=len(target['fixed_prior_mismatch_rows']),changed_OHLC_cells=len(actual),
            dates_VOL_AMOUNT_unchanged=True,raw_fingerprints={'baseline':before_print,'counterfactual':after_print},
            baseline_selected=bool(baseline['XG'][-1]),counterfactual_selected=bool(counter['XG'][-1]),
            baseline_XG=scalar(baseline['XG'][-1]),counterfactual_XG=scalar(counter['XG'][-1]),
            changed_latest_assignment_count=sum(x['D_changed']for x in differences),
            control_counterfactual_reused_exact_baseline_vectors=reused_control,
            latest_key_components={k:{'before':scalar(baseline[k][-1]),'after':scalar(counter[k][-1])}for k in ('ENTRYPOOL','FRESH','CONT0','RISK0','B2ROLE','B3ROLE','XG')})
    except BaseException as exc:
        result.update(status='DIAGNOSTIC_STOPPED',error_type=type(exc).__name__,error=str(exc))
    result.update(elapsed_seconds=time.monotonic()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  actual_artifacts=[{'path':str(p),'sha256':sha(p)}for p in sorted(out.iterdir())if p.is_file()],
                  windows_engine_parity='CANNOT_CONFIRM',full_schema_ready=False)
    save(out/'STOCK_RECEIPT.json',result)
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=('canary','remaining'));args=parser.parse_args()
    cp=S/'CONTRACT.json';cfg=json.loads(cp.read_text());start=json.loads(Path(cfg['registry_start_path']).read_text())
    assert start['execution_id']==E and start['event_type']=='RUN_STARTED' and start['contract_sha256']==sha(cp) and start['code_sha256']==sha(__file__)
    for item in cfg['input_bindings']:assert sha(item['path'])==item['sha256'],'Frozen input SHA drift:'+item['path']
    assert stat(cfg['archive']['path'])==cfg['archive']['stat'] and stat(cfg['panel']['path'])==cfg['panel']['stat']
    root=S/'runs'/E
    if args.phase=='canary':root.mkdir(parents=True,mode=0o700,exist_ok=False);chosen=[cfg['targets'][0]]
    else:
        previous=json.loads((root/'canary_RECEIPT.json').read_text());assert previous['safe_to_continue'];chosen=cfg['targets'][1:]
    began=time.monotonic();rows=[]
    for target in chosen:
        one=stock(cfg,target,root);rows.append(one)
        if one['status']!='ISOLATED_ONE_VARIABLE_DIAGNOSTIC_COMPLETE':break
    safe=(len(rows)==len(chosen) and all(x['status']=='ISOLATED_ONE_VARIABLE_DIAGNOSTIC_COMPLETE'for x in rows)
          and resource.getrusage(resource.RUSAGE_SELF).ru_maxrss<cfg['max_rss_bytes'])
    receipt={'execution_id':E,'phase':args.phase,'safe_to_continue':safe,'stock_results':rows,
             'elapsed_seconds':time.monotonic()-began,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             'authority_writes':0,'pointer_writes':0,'network_calls':0,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    save(root/(args.phase+'_RECEIPT.json'),receipt)
    print(json.dumps({k:v for k,v in receipt.items()if k!='stock_results'}))
    raise SystemExit(0 if safe else 1)

if __name__=='__main__':main()
