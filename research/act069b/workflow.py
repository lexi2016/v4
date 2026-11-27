"""Frozen ACT-069B ledger export and exact prefix replay for 钧达股份."""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from io import StringIO
import json
from pathlib import Path
import re

from research.act069b.adapter import Adapter, EXTERNAL_GAPS, iso, sha256, through_bars


CONTRACT='adapter_contract.json'
CONTRACT_SHA='e4a18f7cd883edec170a9ec335c76e9035665d8871b39982e0d940c57bcee7e7'
LEDGER='ACT069B_JUNDA_002865_PRIMITIVE_EVIDENCE_LEDGER_DONLY_20261127.csv'
DAY='ACT069B_JUNDA_002865_DAY_VS_CHAIN_STATUS_20261127.csv'
SUMMARY='ACT069B_EVIDENCE_ADAPTER_SUMMARY_20261127.md'
PATH_KEYS=('event_chain_state_b1','event_chain_state_b2','event_chain_state_strong_continuation','event_chain_state_m25')


def read_json(path):
    return json.loads(path.read_bytes())


def put_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def load_contract(evidence):
    path=evidence/CONTRACT
    if sha256(path)!=CONTRACT_SHA:
        raise ValueError('Frozen adapter contract bytes differ')
    contract=read_json(path)
    if contract['new_thresholds'] or not contract['before_execution']:
        raise ValueError('Adapter contract scope differs')
    return contract


def register_sources(root,contract):
    paths={name:root/info['local'] for name,info in contract['sources'].items()}
    for name,path in paths.items():
        if sha256(path)!=contract['sources'][name]['sha256']:
            raise ValueError(f'Authority byte identity mismatch: {name}')
    boundary=read_json(paths['contract'])
    if boundary['proof_gate']['new_historical_authoritative_proofs_bound'] is not False:
        raise ValueError('Reconcile changed structural authority before adapter replay')
    return paths


def cohort_through(path,cutoff,contract):
    rows={}
    previous=None
    with path.open(encoding='utf-8-sig',newline='') as handle:
        for row in csv.DictReader(handle):
            day=iso(row['date'])
            if day>cutoff or (previous is not None and day<=previous):
                raise ValueError('ACT069A cohort changed or out of order')
            if (row['ts_code']!=contract['symbol'] or row['source_generation']!=contract['source_generation']
                or row['price_basis']!=contract['price_basis'] or row['volume_basis']!=contract['volume_basis']
                or row['common_indicator_sha256']!=contract['sources']['bars']['sha256'] or row['historical_pit']!='CANNOT_CONFIRM'):
                raise ValueError(f'Unbound symbol, generation or basis on {day}')
            if row['structure_proof_status']!='UNBOUND' or json.loads(row['source_bound_proofs']) or json.loads(row['formal_trigger_events']):
                raise ValueError(f'Unexpected structural fact cannot be silently bound on {day}')
            rows[day]=row
            if day==cutoff:
                return rows
            previous=day
    raise ValueError(f'Pinned cohort cutoff absent: {cutoff}')


def replay(paths,cutoff,contract):
    keys=cohort_through(paths['prior'],cutoff,contract)
    adapter=Adapter(contract,source_registry={})
    facts=[]
    days=[]
    for bar in through_bars(paths['bars'],cutoff):
        adapter.advance(bar)
        if bar.day in keys:
            snapshot=adapter.snapshot()
            days.append(adapter.compare_day_chain(keys[bar.day],snapshot))
            facts.extend(snapshot)
    if len(days)!=len(keys):
        raise ValueError('Not every pinned cohort date replayed')
    return facts,days,len(adapter.bars)


def validate(facts,days,contract):
    field_names=contract['ledger_fields']
    names=contract['primitive_fact_names']
    domains=contract['domains']
    template=[(pid,name) for pid,items in names.items() for name in items]
    facts_per_day=len(template)
    if len(facts)!=len(days)*facts_per_day:
        raise ValueError('Ledger fact counts do not match its frozen layout')
    for index,day in enumerate(days):
        section=facts[index*facts_per_day:(index+1)*facts_per_day]
        if set(day)!=set(contract['day_fields']) or [(r['primitive_id'],r['fact_name']) for r in section]!=template:
            raise ValueError('Frozen fact names/order or day schema differs')
        if any(day[field] not in domains['event_chain_state'] for field in PATH_KEYS):
            raise ValueError('Unregistered event chain state')
        if (day['day_eligibility_method']!='B2_D0' or day['candle_direction'] not in domains['candle_direction']
            or day['day_eligibility'] not in domains['day_eligibility'] or day['day_eligibility_reason'] not in domains['day_eligibility_reason']
            or day['external_gaps']!='|'.join(EXTERNAL_GAPS)
            or any(day[f'pending_{pid.lower()}'] not in domains['pending'] for pid in names)):
            raise ValueError('Unregistered day status')
        for row in section:
            if (list(row)!=field_names or row['signal_date']!=day['signal_date'] or not row['fact_value']
                or not iso(row['occurred_date'])<=iso(row['first_knowable_date'])<=iso(row['signal_date'])
                or not re.search(r'@sha256:[0-9a-f]{64}#',row['source_locator'])
                or row['handoff_status'] not in domains['handoff_status'] or row['gap_reason'] not in domains['gap_reason']
                or bool(row['gap_reason'])!=(row['handoff_status']=='MISSING_SOURCE')):
                raise ValueError(f'Inconsistent registered ledger row: {row["signal_date"]}/{row["fact_name"]}')
            if row['handoff_status']=='MISSING_SOURCE' and row['fact_value'] not in ('UNKNOWN','CANNOT_CONFIRM'):
                raise ValueError('Missing source presented as definite evidence')


def csv_bytes(rows,fields):
    handle=StringIO(newline='')
    writer=csv.DictWriter(handle,fields)
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode('utf-8-sig')


def prefix_checks(paths,full_facts,full_days,contract):
    checkpoints=[]
    for index in (10,len(full_days)//2,len(full_days)-10):
        cutoff=full_days[index]['signal_date']
        before,days,bars=replay(paths,iso(cutoff),contract)
        exp_facts=[r for r in full_facts if r['signal_date']<=cutoff]
        exp_days=full_days[:index+1]
        got=(csv_bytes(before,contract['ledger_fields']),csv_bytes(days,contract['day_fields']))
        want=(csv_bytes(exp_facts,contract['ledger_fields']),csv_bytes(exp_days,contract['day_fields']))
        if got!=want:
            raise AssertionError(f'Exact serialized prefix regression on {cutoff}')
        checkpoints.append({'cutoff':cutoff,'stock_sessions':bars,'signal_days':len(days),
                            'ledger_prefix_sha256':hashlib.sha256(got[0]).hexdigest(),
                            'day_prefix_sha256':hashlib.sha256(got[1]).hexdigest()})
    return checkpoints


def summary(path,report):
    missing=report['per_primitive_status']
    p_gaps='，'.join(f'{primitive} {counts.get("MISSING_SOURCE",0):,}' for primitive,counts in missing.items())
    external=sum(report['gap_reason_counts'][reason] for reason in EXTERNAL_GAPS)
    lines=['# ACT-069B｜钧达股份 002865.SZ 原语证据账本','',
           '冻结样本为 2017-10-19 至 2026-11-06 的 344 个信号日。按 2,316 个同代股票交易日顺序回放。仅使用冻结 ACT-069A 合同、逐日 CSV 与同代 D-only 行情。当前 QFQ 代次的历史 PIT 保留 `CANNOT_CONFIRM`。','',
           '| 核对项 | 实测 |','|---|---:|',
           f'| 逐日／账本行数 | {report["day_rows"]}／{report["ledger_rows"]} |',
           f'| D-only 客观观察／来源缺口／已绑定结构原语 | {report["handoff_status_counts"].get("OBSERVED_D_ONLY",0)}／{report["handoff_status_counts"].get("MISSING_SOURCE",0)}／{report["handoff_status_counts"].get("REGISTERED_SOURCE",0)} |',
           f'| `occurred_date <= first_knowable_date <= D` | {report["ledger_rows"]:,}/{report["ledger_rows"]:,}（100%） |',
           '| B2 日级必要条件 FALSE／资格 UNKNOWN | 86／258 |',
           '| B1、B2、强势中继、#25 的来源链状态 | 各 344 UNKNOWN |','',
           '86 日由 84 根阴线和 2 根平线独立复算，反映 B2 D0 的非阳线必要条件，链状态仍沿用 ACT-069A。P3 的锚定失效和 P5 的结构否决需要同一条独立授权的终止证据，本轮仍为 UNKNOWN。','',
           'P1 留存逐日 OHLCV、前一股票交易日和量价变化，关键 K 与转折缺来源。P2/P3 缺已登记支撑区和失效证据，P4 缺已登记区段。P5 将当日有行情、结构否决与官方 ST、停牌、历史 PIT、外部风险证据分别记录。ST、停牌和外部风险为 UNKNOWN，历史 PIT 为 CANNOT_CONFIRM。缺口行的日期为当日评估截点。','',
           f'各类交接缺口行数为 {p_gaps}。P3 的锚定失效和 P5 的结构否决对应同一授权终止来源。P5 另有 {external:,} 行外部证据及历史 PIT 缺口。','',
           f'按字段逐行验证且前缀字节一致的截点为 {"、".join(c["cutoff"] for c in report["prefixes"])}。每个快照只计算 ≤D 证据，D+15 读取 0。新增数值阈值 0，S_FIT=B_FIT=0。研究限定于钧达这 344 个信号日。','',
           '**包外 SHA-256**','',f'- 原语账本 `{report["sha256"][LEDGER]}`',f'- 日级与链状态 `{report["sha256"][DAY]}`',
           f'- 数据合同 `{CONTRACT_SHA}`','- 源码提交 `SOURCE_COMMIT_SLOT`','']
    path.write_text('\n'.join(lines),encoding='utf-8')


def run(args):
    contract=load_contract(args.evidence)
    inputs=register_sources(args.artifacts,contract)
    facts,days,bars=replay(inputs,iso(contract['max_D']),contract)
    validate(facts,days,contract)
    if (len(days)!=contract['signal_days'] or bars!=contract['sessions'] or days[0]['signal_date']!=contract['first_signal_D']
        or days[-1]['signal_date']!=contract['max_D']):
        raise ValueError('Exact cohort or coverage diverges from frozen source')
    shape=Counter(day['candle_direction'] for day in days)
    day_states=Counter(day['day_eligibility'] for day in days)
    inherited={key:dict(Counter(day[key] for day in days)) for key in PATH_KEYS}
    statuses=Counter(row['handoff_status'] for row in facts)
    if shape!={'BEARISH':84,'FLAT':2,'BULLISH':258} or day_states!={'FALSE':86,'UNKNOWN':258}:
        raise ValueError('Frozen independent day eligibility oracle mismatch')
    if any(state!={'UNKNOWN':344} for state in inherited.values()) or statuses.get('REGISTERED_SOURCE',0):
        raise ValueError('Unsupported historical proof or path promotion')
    prefixes=prefix_checks(inputs,facts,days,contract)
    payloads={LEDGER:csv_bytes(facts,contract['ledger_fields']),DAY:csv_bytes(days,contract['day_fields'])}
    for name,body in payloads.items():
        target=args.output/name
        target.write_bytes(body)
        if target.read_bytes()!=body:
            raise IOError(f'Publication readback differs: {name}')
    result={'status':'WRITER_VERIFIED_PENDING_INDEPENDENT_REVIEW','freeze_sha256':CONTRACT_SHA,'frozen_at_utc':contract['frozen_at_utc'],
            'RESEARCH_ONLY':True,'S_FIT':0,'B_FIT':0,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
            'new_thresholds':[],'post_D_reads':0,'first_signal_D':days[0]['signal_date'],'last_signal_D':days[-1]['signal_date'],
            'source_generation':contract['source_generation'],'sources':contract['sources'],'market_price_volume_basis':[contract['price_basis'],contract['volume_basis']],
            'historical_pit':'CANNOT_CONFIRM','stock_sessions':bars,'day_rows':len(days),'ledger_rows':len(facts),
            'ledger_fields':contract['ledger_fields'],'day_fields':contract['day_fields'],'domains':contract['domains'],
            'fact_schema':contract['primitive_fact_names'],'unregistered_rows':0,'pinned_D_index_OHLCV_shape_and_eligibility_verified':len(days),
            'handoff_status_counts':dict(statuses),'gap_reason_counts':dict(Counter(row['gap_reason'] for row in facts if row['gap_reason'])),
            'per_primitive_status':{pid:dict(Counter(r['handoff_status'] for r in facts if r['primitive_id']==pid)) for pid in contract['primitive_fact_names']},
            'candle_shape_counts':dict(shape),'day_eligibility_counts':dict(day_states),'method_chain_counts':inherited,
            'pending_by_primitive':{pid:dict(Counter(row[f'pending_{pid.lower()}'] for row in days)) for pid in contract['primitive_fact_names']},
            'prefixes':prefixes,'sha256':{name:sha256(args.output/name) for name in payloads}}
    summary(args.output/SUMMARY,result)
    if (args.output/SUMMARY).read_text().count('SOURCE_COMMIT_SLOT')!=1:
        raise ValueError('Summary must contain exactly one source commit binding slot')
    result['sha256'][SUMMARY]=sha256(args.output/SUMMARY)
    put_json(args.evidence/'adapter_receipt.json',result)
    print(json.dumps({key:result[key] for key in ('day_rows','ledger_rows','handoff_status_counts','day_eligibility_counts','prefixes','sha256')},ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('artifacts','output','evidence'):
        p.add_argument(f'--{name}',required=True,type=Path)
    run(p.parse_args())


if __name__=='__main__':
    main()
