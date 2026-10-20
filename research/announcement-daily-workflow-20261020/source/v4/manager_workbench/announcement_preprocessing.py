"""Source-bound, zero-dispatch preprocessing report and bounded NEW-only manifest."""
from __future__ import annotations
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
from typing import Any

SCHEMA = 'v4.manager_workbench.announcement_preprocessing.v1'
MAX_ARTICLES, MAX_REQUESTS, MAX_PARTS = 8, 16, 6

def encoded(value: Any) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()

def source_identity(item: dict[str, Any]) -> tuple:
    member=item.get('membership_evidence') or {}
    return (item.get('article_id'),item.get('source_sha256'),item.get('body_sha256'),
            item.get('source_date'),member.get('symbol'))

def build_report(plan: dict[str, Any], *, job_id: str, capture: dict[str, Any],
                 ordinary: list[dict[str, Any]], long_specs: dict[str, Any],
                 preparation_pending: list[dict[str, Any]], blocked_article_ids: set[str],
                 workers: int = 1, history_context: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('PREPROCESSING_WORKERS_INVALID')
    items=plan['items']
    # Only immutable identity calculation may fan out; all ledger/publication
    # and queue mutations remain with the parent owner in source order.
    if workers == 1:
        identities=list(map(source_identity,items))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            identities=list(pool.map(source_identity,items))
    history_context = history_context or []
    processed = {(e.get('article_id'), e.get('body_sha256')) for e in history_context}
    standard={(p['article_id'],p.get('source_sha256'),p.get('body_sha256')):p for p in ordinary}
    long_versions={(spec['article']['article_id'],spec['article']['source_sha256'],spec['article']['body_sha256']):spec
                   for spec in long_specs.values() if 'article' in spec}
    pending={p.get('article_id') for p in preparation_pending}
    primary=Counter(); seen=set(); catalogue=[]; models=[]
    for item,identity in zip(items,identities):
        # Invalid/partial identities are never collapsed into one unknown row.
        exact=identity if all(isinstance(v,str) and v for v in identity) and re.fullmatch(r'HK\.\d{5}',identity[-1]) else ('INVALID',item['row_index'])
        duplicate=exact in seen
        seen.add(exact)
        status=item['processing_disposition']; aid=item['article_id']; route=item['route_group']
        if duplicate:
            disposition='EXACT_DUPLICATE'
        elif status=='OUTSIDE_WINDOW':disposition='OUTSIDE_WINDOW'
        elif item['membership_status']!='IN':disposition='MEMBERSHIP_'+item['membership_status']
        elif aid in blocked_article_ids:disposition='USER_STOPPED_EXCLUDED'
        elif status=='REUSED_SUCCESS':disposition='HISTORY_SUCCESS_REUSED'
        elif status=='REUSED_CLASSIFICATION':disposition='HISTORY_RULE_REUSED'
        elif status!='NEW_INPUT':disposition='OTHER_HISTORY_PRESERVED'
        elif (aid,item.get('body_sha256')) in processed:disposition='OTHER_HISTORY_PRESERVED'
        elif route=='A':disposition='RULE_ARCHIVED'
        elif route=='B':disposition='STRUCTURED_EXTRACTED'
        elif route=='D':disposition='SOURCE_GAP'
        elif (aid,item.get('source_sha256'),item.get('body_sha256')) in long_versions:disposition='MODEL_LONG'
        elif (aid,item.get('source_sha256'),item.get('body_sha256')) in standard:disposition='MODEL_ORDINARY'
        else:disposition='PREPARATION_PENDING'
        primary[disposition]+=1
        entry={'row_index':item['row_index'],'article_id':aid,'source_sha256':item.get('source_sha256'),
            'body_sha256':item.get('body_sha256'),'source_date':item.get('source_date'),
            'symbol':identity[-1],'primary_disposition':disposition,'route_group':route,
            'reason_codes':item['classification'].get('reason_codes',[])}
        if disposition.startswith('MODEL_'):
            parts=len((long_versions.get((aid,item.get('source_sha256'),item.get('body_sha256'))) or long_specs[aid])['plan']['parts']) if disposition=='MODEL_LONG' else 0
            entry.update(reader_requests=parts if parts else 1, synthesis_requests=1 if parts else 0,
                part_count=parts, expected_requests=parts+1 if parts else 1)
            models.append(entry)
        catalogue.append(entry)
    # Stable first ordinary article for the initial canary. Remaining candidates
    # alternate newest and oldest source dates so accumulated work is retained.
    ordinary_models=sorted((e for e in models if not e['part_count']),key=lambda e:(e['source_date'] or '',e['row_index']))
    first=ordinary_models[0] if ordinary_models else None
    rest=sorted((e for e in models if e is not first),key=lambda e:(e['source_date'] or '',e['row_index']))
    ordered=([first] if first else [])
    while rest:
        ordered.append(rest.pop())
        if rest:ordered.append(rest.pop(0))
    selected=[]; requests=0
    for entry in ordered:
        if len(selected)>=MAX_ARTICLES or entry['part_count']>MAX_PARTS or requests+entry['expected_requests']>MAX_REQUESTS:
            continue
        if not selected and entry['part_count']:
            continue  # First article must exercise the complete short path.
        selected.append(entry);requests+=entry['expected_requests']
    unique=len(items)-primary['EXACT_DUPLICATE']
    unique_dispositions={key:value for key,value in primary.items() if key!='EXACT_DUPLICATE'}
    if sum(unique_dispositions.values())!=unique or unique+primary['EXACT_DUPLICATE']!=len(items):
        raise ValueError('PREPROCESSING_ACCOUNTING_NOT_CLOSED')
    return {'schema':SCHEMA,'job_id':job_id,'target_date':plan['target_date'],'cutoff':plan['cutoff'],
        'source':capture.get('source'),'market':'HK_CONNECT','source_window':capture.get('window'),
        'capture_product':plan['capture_product'],'classification_plan_sha256':digest(plan),
        'membership_gate_sha256':plan['membership_gate_sha256'],'policy':plan['policy'],
        'processing_contract':plan['processing_contract'],
        'counts':{'raw_rows':len(items),'exact_duplicates':primary['EXACT_DUPLICATE'],'unique_articles':unique,
            'primary_dispositions':unique_dispositions,'model_required_articles':len(models),
            'model_ordinary_articles':primary['MODEL_ORDINARY'],'model_long_articles':primary['MODEL_LONG'],
            'reader_parts':sum(e['part_count'] for e in models),'syntheses':primary['MODEL_LONG'],
            'ordinary_requests':primary['MODEL_ORDINARY'],'expected_model_requests':sum(e['expected_requests'] for e in models),
            'workload_unknown_articles':primary['PREPARATION_PENDING'],
            'bounded_articles':len(selected),'bounded_model_requests':requests,'deferred_model_articles':len(models)-len(selected)},
        'history_context':history_context,'execution_scope':'NEW_ONLY_CANARY_20261020',
        'catalogue':catalogue,'execution_manifest':selected,'first_article_id':selected[0]['article_id'] if selected else None,
        'limits':{'max_articles':MAX_ARTICLES,'max_model_requests':MAX_REQUESTS,'max_reader_parts_per_article':MAX_PARTS},
        'accounting_closed':True,'model_requests':0,'queue_claims':0,'preprocessing_workers':workers,
        'rules_explanation':['A：完整正文命中已验收模板且无未知实质区域，程序性归档。',
            'B：完整已验收表格语法确定性提取事实；不是模型未入选。',
            'C：新增实质、混合或未知内容按完整证据分析；普通/长文分开计数。',
            'D：正文、来源、解析或历史完整性待补证；不按标题排除风险或重大内容。',
            '相同来源、正文、日期、发行人精确去重；历史处理优先保留，修订正文作为新版本。'],
        'safety':{'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}}

def execution_subset(report: dict[str, Any], phase: str) -> set[str]:
    if report.get('schema')!=SCHEMA or report.get('accounting_closed') is not True:
        raise ValueError('PREPROCESSING_REPORT_INVALID')
    manifest=report['execution_manifest']
    if (len(manifest)>MAX_ARTICLES or sum(e['expected_requests'] for e in manifest)>MAX_REQUESTS
            or any(e['part_count']>MAX_PARTS for e in manifest)):
        raise ValueError('PREPROCESSING_LIMITS_INVALID')
    if phase=='FIRST':return {report['first_article_id']} if report.get('first_article_id') else set()
    if phase=='CONTINUE':return {e['article_id'] for e in manifest}
    raise ValueError('PREPROCESSING_EXECUTION_PHASE_INVALID')
