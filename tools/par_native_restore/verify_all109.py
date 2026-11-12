"""Original full-prefix vs genuine daily candidate: explicit inputs, exact bits.

Synthetic mode is a software canary, not authentic Par data certification.
Input mode requires controller-provided authenticated normalized Par rows/context.
"""
import argparse,hashlib,json,math,sys,time
from collections import Counter
from datetime import date,timedelta
from pathlib import Path
from recovery import Kernel
from native_state import encode,decode,digest


def synthetic(symbol,n,offset=0,invalid=False):
    rows=[];previous=None
    for i in range(n):
        c=10.1+offset+math.sin(i*.37)*2+i*.003
        r=dict(symbol=symbol,event_date=(date(2020,1,1)+timedelta(days=i)).strftime('%Y%m%d'),open=c+math.sin(i*.81)*.4,high=c+.7,low=c-.6,close=c,volume=100000.+(math.sin(i*.7)+1)*100000.,pre_close=previous,pct_chg=None if previous is None else (c/previous-1)*100,raw_row_index=i)
        if invalid and i==1:r['volume']=0.
        rows.append(r);previous=c
    return dict(rows=rows,context=dict(symbol=symbol,currency='CNY',asof=rows[-1]['event_date'],prefix_complete=True),source_binding=dict(source_prefix_sha256=digest(rows),source_reference='SYNTHETIC_ONLY:'+symbol,source_basis='SYNTHETIC_NOT_PAR_SOURCE'),kind='SYNTHETIC')


def validate(kernel,doc,days):
    rows=doc['rows'];context=doc['context'];split=len(rows)-days
    if split<1:raise ValueError('VALIDATION_HISTORY_LENGTH')
    started=time.monotonic();_,state=kernel.initialize(rows[:split],{**context,'asof':rows[split-1]['event_date']},doc['source_binding'])
    per_field={name:dict(exact_payloads=0,value_differences=0,status_differences=0,reason_differences=0,both_unknown=0) for name in kernel.schema}
    internal_differences=[];days_report=[];diffs=[]
    for index in range(split,len(rows)):
        state=decode(encode(state));result,state,audit=kernel.step(state,rows[index])
        oracle,reference=kernel.initialize(rows[:index+1],{**context,'asof':rows[index]['event_date']},doc['source_binding'])
        for name in kernel.schema:
            actual=result['fields'][name];expected=oracle['fields'][name];f=per_field[name]
            if encode(actual)==encode(expected):f['exact_payloads']+=1
            else:
                for key,counter in [('value','value_differences'),('status','status_differences'),('reason','reason_differences')]:
                    if encode(actual.get(key))!=encode(expected.get(key)):f[counter]+=1
                diffs.append(dict(symbol=context['symbol'],date=rows[index]['event_date'],field=name,actual=actual,expected=expected))
            if actual['value'] is None and expected['value'] is None:f['both_unknown']+=1
        checks={}
        for key in ('foundation','n_score','native_latest'):
            checks[key]=encode(state['component109'][key])==encode(reference['component109'][key])
            if not checks[key]:internal_differences.append(dict(date=rows[index]['event_date'],component=key))
        checks['native_primitive_state']=encode(state['native_state']['accumulators'])==encode(reference['native_state']['accumulators']) and encode(state['native_state']['sequences'])==encode(reference['native_state']['sequences'])
        if not checks['native_primitive_state']:internal_differences.append(dict(date=rows[index]['event_date'],component='native_primitive_state'))
        checks['complete_row']=encode(result)==encode(oracle)
        if not checks['complete_row']:internal_differences.append(dict(date=rows[index]['event_date'],component='complete_row_diagnostics'))
        days_report.append(dict(date=rows[index]['event_date'],checks=checks,execution=audit))
    return dict(source_binding=doc['source_binding'],symbol=context['symbol'],kind=doc['kind'],rows=len(rows),initialization_rows=split,consecutive_days=days,status='PASS' if not diffs and not internal_differences else 'FAIL',per_field=per_field,differences=diffs,internal_differences=internal_differences,days=days_report,counters=state['counters'],seconds=time.monotonic()-started),state


def main(a):
    kernel=Kernel(a.par,a.latest,a.dependencies)
    docs=[json.loads(p.read_bytes()) for p in a.inputs] if a.inputs else [synthetic('300750.SZ',145),synthetic('301683.SZ',125,15),synthetic('301716.SZ',25,30),synthetic('000001.SZ',35,3,True)]
    if a.inputs:
        for doc in docs:
            binding=doc['source_binding']
            if binding.get('normalized_rows_sha256')!=digest(doc['rows']):raise ValueError('NORMALIZED_INPUT_BINDING')
            if binding.get('physical_asof')!=doc['rows'][-1]['event_date'] or doc['context']['asof']!=binding['physical_asof']:raise ValueError('PHYSICAL_ASOF_BINDING')
            if binding.get('source_basis')!=doc['context'].get('basis'):raise ValueError('SOURCE_BASIS_BINDING')
            if not binding.get('source_refs'):raise ValueError('ACTUAL_SOURCE_REFERENCES_REQUIRED')
            for ref in binding['source_refs']:
                if hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('ACTUAL_SOURCE_BYTES_SHA')
    reports=[]
    for doc in docs:
        try:
            report,state=validate(kernel,doc,a.days);reports.append(report)
            if a.inputs and report['status']=='PASS':
                target=a.states/(doc['context']['symbol']+'_'+state['asof']+'.recovered.bin');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(encode(state))
                report['new_recovery_state']=dict(path=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),product_kind='NEW_RECOVERY_PRODUCT_NOT_HISTORIC_ORIGINAL')
        except Exception as error:
            reports.append(dict(symbol=doc['context']['symbol'],status='ERROR',error_type=type(error).__name__,error=str(error)))
        print(json.dumps({k:v for k,v in reports[-1].items() if k not in ('per_field','days','differences')},ensure_ascii=False),flush=True)
    a.output.mkdir(parents=True,exist_ok=True)
    result=dict(schema='par109.recovery.oracle.v1',status='PASS' if all(r['status']=='PASS' for r in reports) else 'FAIL',scope='ACTUAL_BOUND_PAR_SOURCE' if a.inputs else 'SYNTHETIC_SOFTWARE_CANARY_ONLY',code_binding=kernel.code_binding,reports=reports,production_allowed=False)
    (a.output/('ACTUAL_PAR109_ORACLE.json' if a.inputs else 'SYNTHETIC_PAR109_ORACLE.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if result['status']!='PASS':raise SystemExit(1)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--par',type=Path,required=True);p.add_argument('--latest',type=Path,required=True);p.add_argument('--dependencies',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--states',type=Path);p.add_argument('--inputs',type=Path,nargs='*');p.add_argument('--days',type=int,default=3);a=p.parse_args();
    if a.inputs and a.states is None:p.error('--states is required with actual --inputs')
    main(a)
