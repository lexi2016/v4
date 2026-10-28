from copy import deepcopy
import pytest
from v4.manager_workbench.announcement_preprocessing import build_report,execution_subset


def _plan():
    def item(i,route='C',status='NEW_INPUT',member='IN'):
        return {'row_index':i,'article_id':f'A{i}','source_sha256':str(i)*64,'body_sha256':str(i+1)*64,
            'source_date':'2026-10-20','membership_evidence':{'symbol':'HK.00001'},'membership_status':member,
            'route_group':route,'processing_disposition':status,'classification':{'reason_codes':[route]}}
    rows=[item(0,'A'),item(1,'B'),item(2),item(3),item(4,'D'),item(5,status='REUSED_SUCCESS'),
          item(6,status='HISTORICAL_INCOMPATIBLE_PRESERVED'),item(7,member='OUT'),item(8,member='UNKNOWN'),
          item(9,status='OUTSIDE_WINDOW'),item(10),item(11),item(12)]
    duplicate=deepcopy(rows[0]);duplicate['row_index']=13;rows.append(duplicate)
    return {'items':rows,'target_date':'20261020','cutoff':'2026-10-20T12:00:00+08:00',
        'capture_product':{'sha256':'a'*64},'membership_gate_sha256':'b'*64,'policy':{'version':'frozen'},'processing_contract':{}}


def _payload(plan, aid):
    entry=next(e for e in plan['items'] if e['article_id']==aid)
    return {key:entry[key] for key in ('article_id','source_sha256','body_sha256')}


def test_complete_denominator_routes_history_dedup_and_model_workload_are_separate_from_canary():
    plan=_plan();ordinary=[_payload(plan,aid) for aid in ['A2','A10','A11']]
    report=build_report(plan,job_id='a'*32,capture={'source':'EASTMONEY_HK'},ordinary=ordinary,
        long_specs={'A3':{'article':_payload(plan,'A3'),'plan':{'parts':[{},{}]}}},preparation_pending=[{'article_id':'A12'}],
        blocked_article_ids={'A11'},history_context=[{'article_id':'A10','body_sha256':plan['items'][10]['body_sha256']}])
    counts=report['counts']
    assert counts['raw_rows']==14 and counts['exact_duplicates']==1 and counts['unique_articles']==13
    assert sum(counts['primary_dispositions'].values())==counts['unique_articles']==13
    assert 'EXACT_DUPLICATE' not in counts['primary_dispositions']
    assert counts['model_required_articles']==counts['model_ordinary_articles']+counts['model_long_articles']==2
    assert counts['reader_parts']==2 and counts['syntheses']==1 and counts['expected_model_requests']==4
    assert counts['workload_unknown_articles']==1
    assert counts['primary_dispositions']['OTHER_HISTORY_PRESERVED']==2
    assert report['model_requests']==report['queue_claims']==0
    assert execution_subset(report,'FIRST')=={'A2'}


def test_canary_budget_is_not_total_model_denominator_and_long_over_six_parts_is_deferred():
    plan=_plan();plan['items']=[deepcopy(plan['items'][2]) for _ in range(25)]
    for i,item in enumerate(plan['items']):item.update(row_index=i,article_id=f'NEW{i}',body_sha256=f'{i:064x}')
    ordinary=[_payload(plan,f'NEW{i}') for i in range(24)]
    report=build_report(plan,job_id='a'*32,capture={},ordinary=ordinary,
        long_specs={'NEW24':{'article':_payload(plan,'NEW24'),'plan':{'parts':[{}]*7}}},preparation_pending=[],blocked_article_ids=set())
    c=report['counts'];assert c['model_required_articles']==25 and c['bounded_articles']==8
    assert c['expected_model_requests']==32 and c['bounded_model_requests']==8 and c['deferred_model_articles']==17
    assert 'NEW24' not in execution_subset(report,'CONTINUE')
    assert build_report(plan,job_id='a'*32,capture={},ordinary=ordinary,
        long_specs={'NEW24':{'article':_payload(plan,'NEW24'),'plan':{'parts':[{}]*7}}},preparation_pending=[],blocked_article_ids=set(),workers=2)['catalogue']==report['catalogue']


def test_cross_issuer_or_revised_body_is_not_deduplicated_and_unbound_identity_is_not_collapsed():
    plan=_plan();a=deepcopy(plan['items'][2]);b=deepcopy(a);b['row_index']=99;b['membership_evidence']['symbol']='HK.00002'
    c=deepcopy(a);c['row_index']=100;c['body_sha256']='f'*64
    d=deepcopy(a);d['row_index']=101;d['membership_evidence']['symbol']=None
    e=deepcopy(d);e['row_index']=102
    plan['items']=[a,b,c,d,e]
    result=build_report(plan,job_id='a'*32,capture={},ordinary=[],long_specs={},preparation_pending=[],blocked_article_ids=set())
    assert result['counts']['exact_duplicates']==0
