"""ACT-069A historical D-only runner and neutral zero-selection atlas export."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from research.act067b.semantic_shadow import as_date, read_json, sha256, through_sessions
from research.act069a.engine import EventEngine, Kind, identifier


CONTRACT = 'V4.1_STRUCTURE_IDENTITY_STATE_MACHINE_CONTRACT_V1_0.json'
CONTRACT_SHA = '3c5beebdc9ee120f452caf529b8d9e2f589a0fad50bf6dbd0e40af1ecea99bcd'
CSV = 'ACT069A_JUNDA_002865_EVENT_CHAIN_SHADOW_DONLY_20261127.csv'
ZIP = 'ACT069A_JUNDA_002865_FORMAL_ONLY_BLIND_PACKAGE_20261127.zip'
PDF = 'ACT069A_JUNDA_002865_FORMAL_ONLY_USER_ATLAS_DPLUS15_20261127.pdf'
MD = 'ACT069A_JUNDA_EVENT_CHAIN_SUMMARY_20261127.md'
GENERATION = 'ef7f12caa2f67a4a4f26d775d99735b5a9d2845d919087a689d99df6b6322329'
BASIS_FIELDS = ('price_basis','volume_basis','historical_pit')
BASELINE_FIELDS = tuple(f'{origin}_{method}_{layer}' for origin in ('v40_frozen','v40_replay')
                        for method in ('b1','b2','m25') for layer in ('raw','qualified'))
RAW_FROM_PRIOR = {'b1_f02_raw':'b1_raw','b2_b2_1006_raw':'B2_1006_SCREEN_raw',
                  'b2_b2_151_raw':'B2_151_PREV_VOL_X1_20_raw','b2_b2_f03_raw':'USER_FORMULA_B2_F03_raw'}
PATH_COLUMNS = ('b1_path','b2_path','strong_continuation_path','m25_path')


def dump(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def put_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def csv_rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def contract_at(output):
    path=output/CONTRACT
    if sha256(path)!=CONTRACT_SHA:
        raise ValueError('The frozen ACT-069A contract bytes differ')
    contract=read_json(path)
    if contract['new_numeric_thresholds'] or list(contract['proof_gate']['kinds'])!=[kind.value for kind in Kind]:
        raise ValueError('Contract and evidence implementation differ')
    return contract


def assert_pinned(contract,args):
    paths={
        'common_indicators_sha256':args.indicators,'historical_comparison_sha256':args.historical,
        'historical_chart_index_sha256':args.case_lock,'desk_case_identity_sha256':args.case_binding,
    }
    for key,path in paths.items():
        if sha256(path)!=contract['pinned_sources'][key]:
            raise ValueError(f'Input does not match the frozen SHA: {key}')


def historical_inputs(args,contract):
    assert_pinned(contract,args)
    rows=csv_rows(args.historical)
    cohort={as_date(row['date']):row for row in rows}
    if len(rows)!=344 or len(cohort)!=344 or min(cohort).isoformat()!='2017-10-19' or max(cohort).isoformat()!='2026-11-06':
        raise ValueError('Historical cohort diverges from the frozen 344 days')
    if sum(row['v40_frozen_date_present']=='TRUE' for row in rows)!=342:
        raise ValueError('Frozen V4.0 intersection changed')
    if any(row['ts_code']!='002865.SZ' or row['source_generation']!=GENERATION for row in rows):
        raise ValueError('Symbol or authority generation changed')
    binding=read_json(args.case_binding)
    locked={item['chart_id']:item for item in read_json(args.case_lock)['cases']}
    desk={}
    for case,item in binding['cases'].items():
        if (item['date'],item['td_idx'])!=(locked[case]['date'],locked[case]['td_idx']):
            raise ValueError(f'Case identity differs from blind lock: {case}')
        day=as_date(item['date'])
        if int(cohort[day]['stock_session_index'])!=item['td_idx']:
            raise ValueError(f'Case session-index mismatch: {case}')
        legacy=item['legacy_ACT067D_proxy_context']
        if any(cohort[day][field]!=value for field,value in legacy.items()):
            raise ValueError(f'Legacy case context differs from frozen historical export: {case}')
        desk[day]=(case,item)
    return cohort,desk


def parse_valid(value,block,day,proof_kinds):
    kind=block['type']
    if kind=='text':
        return value==block['constant']
    if kind=='enum':
        return value in block['values']
    if kind=='integer':
        return type(value) is int and value>=0
    if kind=='sha256':
        return isinstance(value,str) and bool(re.fullmatch('[0-9a-f]{64}',value))
    if kind in ('number','optional_number'):
        return (kind=='optional_number' and value=='') or (type(value) in (int,float) and math.isfinite(value))
    if kind in ('iso_date','optional_iso_date'):
        if kind=='optional_iso_date' and value=='':
            return True
        try:
            parsed=as_date(value)
            return parsed.isoformat()==value and parsed<=day
        except (ValueError,TypeError):
            return False
    if kind=='identifier_or_empty':
        return value=='' or identifier(value)
    if kind=='enum_set':
        return isinstance(value,list) and value==sorted(set(value)) and all(item in block['values'] for item in value)
    if kind=='trigger_reference_array':
        return isinstance(value,list) and all(
            isinstance(item,dict) and set(item)==set(block['item_schema']) and identifier(item['event_id']) and
            identifier(item['proof_id']) and item['method'] in ('B1','B2_D0','B2_RETEST','STRONG_CONTINUATION','M25') and
            item['decision_on']==day.isoformat() and parse_valid(item['observed_on'],{'type':'iso_date'},day,proof_kinds)
            for item in value)
    if kind=='proof_reference_array':
        return isinstance(value,list) and all(
            isinstance(ref,dict) and set(ref)==set(block['item_schema']) and identifier(ref['target_id']) and
            identifier(ref['source_id']) and identifier(ref['fact_id']) and ref['kind'] in proof_kinds and
            parse_valid(ref['source_sha256'],{'type':'sha256'},day,proof_kinds) and
            parse_valid(ref['known_on'],{'type':'iso_date'},day,proof_kinds) and
            parse_valid(ref['observed_on'],{'type':'iso_date'},day,proof_kinds) and ref['observed_on']<=ref['known_on'] for ref in value)
    raise ValueError(f'Unknown registered schema type: {kind}')


def validation(row,schema,proof_kinds):
    if set(row)!=set(schema):
        raise ValueError(f'CSV shape drift, missing={sorted(set(schema)-set(row))}, extra={sorted(set(row)-set(schema))}')
    day=as_date(row['date'])
    bad=[name for name,block in schema.items() if not parse_valid(row[name],block,day,proof_kinds)]
    if bad:
        raise ValueError(f'Unregistered CSV values on {day}: {bad}')


def frame_one(bar, prior, desk, state, day_index, contract):
    historical=contract['pinned_sources']
    ns,item=desk or ('',{})
    case=item.get('legacy_ACT067D_proxy_context',{})
    return {
        'ts_code':'002865.SZ','date':str(bar.day),'stock_session_index':day_index,'source_generation':GENERATION,
        'common_indicator_sha256':historical['common_indicators_sha256'],'historical_comparison_sha256':historical['historical_comparison_sha256'],
        'historical_case_binding_sha256':historical['desk_case_identity_sha256'],'structure_contract_sha256':CONTRACT_SHA,
        **{name:prior[name] for name in (*BASIS_FIELDS,'v40_frozen_date_present',*BASELINE_FIELDS)},
        'open_D':bar.open,'high_D':bar.high,'low_D':bar.low,'close_D':bar.close,'volume_D':bar.volume,
        'pct_D':bar.pct,'W_D':bar.w,'Y_D':bar.y,'BBI_D':bar.bbi,'J_D':bar.j,
        **state,
        'desk_case_id':ns,'desk_case_transition_oracle':item.get('regression_scenario_from_user','NOT_A_LOCKED_CASE'),
        'legacy_m25_phase_context_only':case.get('m25_phase',''),'legacy_m25_rebuild_context_only':case.get('m25_rebuild_shadow',''),
        'legacy_m25_D_context_date':case.get('m25_d_date',''),'legacy_m25_T_context_date':case.get('m25_t_date',''),
        'legacy_m25_C_context_date':case.get('m25_c_date',''),'legacy_m25_id_context_only':case.get('m25_damage_id',''),
        'formal_chart_id':'',
    }


def replay_historical(indicators,cohort,desk,contract):
    # Historical material proves bars, known RAW formulas and context only. Hence the structural registry is deliberately empty.
    engine=EventEngine(source_registry={})
    output={}
    for index,bar in enumerate(through_sessions(indicators,max(cohort))):
        state=engine.advance(bar)
        day=bar.day
        if day not in cohort:
            continue
        prior=cohort[day]
        if int(prior['stock_session_index'])!=index or any(state[key]!=prior[col] for key,col in RAW_FROM_PRIOR.items()):
            raise ValueError(f'Historical session-index or pinned RAW formula parity differs on {day}')
        output[day]=frame_one(bar,prior,desk.get(day),state,index,contract)
    if len(output)!=len(cohort):
        raise ValueError('D-only regression did not cover every cohort date')
    return output


def check_prefix(indicators,output):
    days=list(output)
    fixed=[days[i] for i in (10,len(days)//2,len(days)-10)]
    for cutoff in fixed:
        engine=EventEngine(source_registry={})
        count=0
        for bar in through_sessions(indicators,cutoff):
            state=engine.advance(bar)
            if bar.day in output:
                count+=1
                if any(output[bar.day][key]!=value for key,value in state.items()):
                    raise AssertionError(f'Historical D-only prefix mismatch at {bar.day}')
        if count!=days.index(cutoff)+1:
            raise AssertionError('Missing cohort days in prefix replay')
    return [str(day) for day in fixed]


def write_csv(path,rows,schema):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,tuple(schema))
        writer.writeheader()
        writer.writerows({name:dump(value) if isinstance(value,list) else value for name,value in row.items()} for row in rows)


def output_counts(output):
    fields=(*PATH_COLUMNS,'candle_shape_D','b1_f02_raw','b2_oral_raw','b2_b2_1006_raw','b2_b2_151_raw','b2_b2_f03_raw','b2_trend_raw',
            'b1_formal','b2_formal_D0','b2_formal_retest','strong_continuation_formal','m25_formal','formal_chart_eligible',
            'v40_frozen_b1_raw','v40_frozen_b1_qualified','v40_frozen_b2_raw','v40_frozen_b2_qualified','v40_frozen_m25_raw','v40_frozen_m25_qualified',
            'v40_replay_b1_raw','v40_replay_b1_qualified','v40_replay_b2_raw','v40_replay_b2_qualified','v40_replay_m25_raw','v40_replay_m25_qualified')
    return {name:dict(Counter(row[name] for row in output)) for name in fields}


def run(args):
    contract=contract_at(args.output)
    cohort,desk=historical_inputs(args,contract)
    output=replay_historical(args.indicators,cohort,desk,contract)
    schema=contract['csv_schema']
    for row in output.values():
        validation(row,schema,contract['proof_gate']['kinds'])
    eligible=[row for row in output.values() if row['formal_chart_eligible']=='TRUE']
    if eligible:
        # Never emit a neutral zero package if any actual formal date needs independent review projections.
        raise RuntimeError(f'Nonzero actual eligibility requires atlas handoff: {[row["date"] for row in eligible]}')
    prefix_days=check_prefix(args.indicators,output)
    csv_path=args.output/CSV
    write_csv(csv_path,output.values(),schema)
    records=[]  # Both user-facing artifacts consume precisely the filtered eligibility set above.
    manifest={'action':'ACT-069A','review_mode':'D_ONLY','selection':'FORMAL_TRUE_ONLY','contract_sha256':CONTRACT_SHA,
              'observed_signal_dates':len(output),'eligible_chart_count':len(eligible),'chart_count':len(records),
              'max_date_used':None,'charts':records,'reason':'NO_SOURCE_BOUND_FORMAL_TRUE_ELIGIBILITY',
              'post_D_data_used':False}
    zip_path=args.output/ZIP
    with ZipFile(zip_path,'w',compression=ZIP_DEFLATED) as archive:
        archive.writestr(ZipInfo('MANIFEST_SHA256.json'),json.dumps(manifest,indent=2)+'\n',compress_type=ZIP_DEFLATED)
    lock={'action':'ACT-069A','contract_sha256':CONTRACT_SHA,'formal_dates':[],
          'cohort_rows':len(output),'csv_sha256':sha256(csv_path),'blind_zip_sha256':sha256(zip_path)}
    put_json(args.evidence/'formal_case_lock.json',lock)
    put_json(args.evidence/'shadow_receipt.json',{
        'RESEARCH_ONLY':True,'S_FIT':0,'B_FIT':0,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
        'material_scope':'Junda 002865.SZ 344-day historical regression','frozen_at_utc':contract['frozen_at_utc'],
        'contract_sha256':CONTRACT_SHA,'new_numeric_thresholds':[],'registered_schema_fields':len(schema),
        'schema_errors':0,'unregistered_statuses':0,'original_historical_signal_days':len(output),
        'frozen_v40_shared_dates':sum(row['v40_frozen_date_present']=='TRUE' for row in output.values()),
        'literal_parity_checked_days':len(output),'source_bound_structural_fact_count':0,'eligible_formal_dates':[],
        'counts':output_counts(output.values()),'prefix_equivalence_D':prefix_days,
        'case_dates':{label:item['date'] for label,item in desk.values()},'source_hashes':contract['pinned_sources'],
        'artifacts':{CONTRACT:CONTRACT_SHA,CSV:lock['csv_sha256'],ZIP:lock['blind_zip_sha256']},
    })
    print(json.dumps({'rows':len(output),'eligible':len(eligible),'schema_fields':len(schema),
                      'prefix':prefix_days,'csv_sha256':lock['csv_sha256'],'zip_sha256':lock['blind_zip_sha256']}))


def atlas(args):
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas

    contract_at(args.output)
    lock=read_json(args.evidence/'formal_case_lock.json')
    if lock['formal_dates'] or lock['contract_sha256']!=CONTRACT_SHA or sha256(args.output/ZIP)!=lock['blind_zip_sha256']:
        raise ValueError('Zero-selection atlas requires matching, empty verified formal eligibility')
    with ZipFile(args.output/ZIP) as archive:
        if archive.namelist()!=['MANIFEST_SHA256.json'] or json.loads(archive.read('MANIFEST_SHA256.json'))['charts']:
            raise ValueError('Zero-selection blind package must have zero chart payload')
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    path=args.output/PDF
    page=Canvas(str(path),pagesize=(800,450),invariant=True,pageCompression=1)
    page.setTitle('ACT-069A 钧达股份 002865.SZ 用户复盘图册')
    page.setFillColor(HexColor('#f6f8fb'))
    page.rect(0,0,800,450,stroke=0,fill=1)

    def text(y,value,size=16,color='#14263d'):
        page.setFillColor(HexColor(color))
        page.setFont('STSong-Light',size)
        page.drawString(47,y,value)

    text(391,'ACT-069A  钧达股份 002865.SZ',27)
    text(355,'正式事件复盘图册 / 行政记录',18,'#435774')
    text(245,'入选 0 个正式事件',31)
    text(195,'本轮历史回归未得到经结构证据确认且可纳入图册的正式日期。')
    text(165,'图表 0 张 / D 后数据读取 0 次。')
    text(60,'RESEARCH_ONLY     S_FIT=0     B_FIT=0',12,'#435774')
    page.showPage()
    page.save()
    put_json(args.evidence/'atlas_receipt.json',{'sha256':sha256(path),'mode':'ZERO_FORMAL_SELECTION_ADMIN_NOTICE',
             'pages':1,'chart_panels':0,'post_D_reads':0,'lock_sha256':sha256(args.evidence/'formal_case_lock.json'),
             'formal_dates':[]})
    print(json.dumps({'pdf_sha256':sha256(path),'pages':1,'chart_panels':0,'post_D_reads':0}))


def summarize(args):
    contract_at(args.output)
    receipt=read_json(args.evidence/'shadow_receipt.json')
    atlas_r=read_json(args.evidence/'atlas_receipt.json')
    counts=receipt['counts']
    if atlas_r['formal_dates'] or atlas_r['post_D_reads'] or atlas_r['sha256']!=sha256(args.output/PDF):
        raise ValueError('Atlas identity or selection changed')
    dates={r['desk_case_id']:r for r in csv_rows(args.output/CSV) if r['desk_case_id']}
    text=['# ACT-069A｜钧达股份 002865.SZ 结构身份回归','',
          '2017-10-19 至 2026-11-06 的 344 个原始信号日，沿用 2316 个同源交易日，归档 V4.0 同日覆盖 342 日。合同先行冻结，本轮新增数值阈值为 0。历史 PIT 为 `CANNOT_CONFIRM`。','',
          '| 路径 | FORMAL | WATCH | UNKNOWN | INVALIDATED |','|---|---:|---:|---:|---:|']
    for title,name in zip(('#19 B1','#20 B2','强势中继','#25 灾后重建'),PATH_COLUMNS):
        values=' | '.join(str(counts[name].get(s,0)) for s in ('FORMAL','WATCH','UNKNOWN','INVALIDATED'))
        text.append(f'| {title} | {values} |')
    text+=['',
           f'F02 RAW 为 {counts["b1_f02_raw"].get("TRUE",0)} 日。#20 的 1006、151、F03 三个独立 RAW 分别为 {counts["b2_b2_1006_raw"].get("TRUE",0)}、{counts["b2_b2_151_raw"].get("TRUE",0)}、{counts["b2_b2_f03_raw"].get("TRUE",0)} 日，按原式逐日复核。口述规则未恢复，趋势轨保持占位。B2 单日必要条件中，{counts["b2_formal_D0"].get("FALSE",0)} 日实测未收阳，记录资格条件 FALSE，源证据层仍为 UNKNOWN。','',
           'B1 母事件身份、支撑和失效位固定，长链无第 16 日自动过期。B2 独立证明回踩或筑底、供给消化、发起与真实脱离，次日已证明的假突破只阻断未来派生。强势中继独立，B3 映射仅为假设。#25 要求原根、受损结构与独立风险全部有源，按 D<T<C 保留历史。15%–20% 仅作回撤描述。','',
           '| 案例 | 日期 | 案头条件和 ACT-069A 实跑边界 |','|---|---|---|']
    notes={'A01':'旧根缺证，实际重建 UNKNOWN。','A03':'无冻结案例断言，实际结构 UNKNOWN。',
           'A05':'仅在原根、受损结构及独立风险均获证后才可能转正式，实际重建 UNKNOWN。',
           'A07':'已证未收复时应 WATCH。旧代理提示不足，实际重建 UNKNOWN。',
           'A08':'完整复原和风险条件均需独立证实，实际重建 UNKNOWN。',
           'A09':f'实测 C={float(dates["A09"]["close_D"]):.3f}、O={float(dates["A09"]["open_D"]):.3f}，确为阳线。下行反抽缺源，实际 B2 UNKNOWN。',
           'A12':'测试后若有新的有效破坏，旧链 INVALIDATED。旧代理只显示 D 破坏，实际重建 UNKNOWN。'}
    for label,row in sorted(dates.items()):
        text.append(f'| {label} | {row["date"]} | {notes[label]} |')
    text+=['','实跑有源正式选择 0 个。ZIP 仅有空清单，PDF 仅有行政记录一页，右图及 D 后读取均为 0。研究限定于钧达 344 日，S_FIT=B_FIT=0。','',
           '**包外 SHA-256**','',*[f'- {name} `{sha256(args.output/file)}`' for name,file in (('合同',CONTRACT),('CSV',CSV),('ZIP',ZIP),('PDF',PDF))],'']
    (args.output/MD).write_text('\n'.join(text),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    for action in ('run','atlas','summary'):
        p=commands.add_parser(action)
        for field in ('output','evidence'):
            p.add_argument(f'--{field}',type=Path,required=True)
        if action=='run':
            for field in ('indicators','historical','case-lock','case-binding'):
                p.add_argument(f'--{field}',type=Path,required=True)
    args=parser.parse_args()
    {'run':run,'atlas':atlas,'summary':summarize}[args.command](args)


if __name__=='__main__':
    main()
