"""Current frozen POLICY compatibility; historical fixtures used calendar days,
quotes without instrument IDs, and permissive suspension/ETF assumptions.
These tests use certified synthetic facts only; no panel data is materialized.
"""
from copy import deepcopy
from decimal import Decimal
import pytest

from v4.manager_workbench.engines.strict_us_selection import (
    run_strict_us_selection, run_single_day_mapping,
)

SESSIONS = ('20260917 20260918 20260921 20260922 20260923 20260924 20260925 '
    '20260928 20260929 20260930 20261002 20261005 20261006 20261007 '
    '20261008 20261009 20261012 20261013 20261014 20261015 20261016').split()
CUTOFF = '2026-10-19T03:00:00+00:00'
SHA = 'a' * 64


def _context():
    return dict(target_date='20261019', phase='MANUAL', cutoff=CUTOFF,
        source_sessions=dict(us='20261016', hk_price='20261016'))


def _history(symbol='HK.00001', turnover=25_000_000):
    return dict(symbol=symbol,
        bars=[dict(date=day, close='100', amount=str(turnover)) for day in SESSIONS],
        history_holds={}, readiness=dict(schema_version='hk_panel_strict_readiness.v1',
            code=symbol, target_date='20261019', dependency_dates=SESSIONS,
            cutoff=CUTOFF, panel_sha256=SHA,
            field_readiness={f:'PASS' for f in ['price','amount','currency','adjustment','pit','eligibility','suspension']},
            evidence_refs=[dict(reference='synthetic-owner-proof', sha256=SHA)]))


def _relation(symbol='HK.00001', *, return_pct='1.5', us_symbol='NVDA'):
    value=Decimal(return_pct)
    return dict(symbol=symbol, us_symbol=us_symbol,
        relation_type='NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER',
        relation_status='REVIEWED', relation_current_validity='CURRENT_SUPPORTED',
        relation_direction='POSITIVE', publication_time_gaps=[], diagnostic_gaps=[],
        owner='US_QUOTE_OWNER', source_sha256=SHA, source_session='20261016',
        available_at='2026-10-18T21:00:00+00:00', evidence_ids=['verified-relation'],
        quote=dict(symbol=us_symbol, session_date='20261016', last=str(100+value),
            previous_close='100', change_pct=str(value)), relation_source_refs=[])


def _payload(codes=('HK.00001',), histories=None):
    return dict(monthly_membership=dict(codes=list(codes)), hk_history=dict(status='READY',
        rows=histories if histories is not None else [_history(c) for c in codes],
        close_sessions=SESSIONS, amount_sessions=SESSIONS[-20:], panel_sha256=SHA,
        panel_manifest_sha256=SHA, panel_available_at='2026-10-18T21:00:00+00:00'))


def _run(payload=None, relations=None, industries=(), context=None):
    return run_strict_us_selection(context or _context(),
        relation_rows=relations if relations is not None else [_relation()],
        industry_rows=list(industries), factor_summary={},
        payload=payload if payload is not None else _payload())


def _gate(result, name, symbol='HK.00001'):
    return next(g for d in result['strict_decisions'] if d['symbol']==symbol for g in d['gates'] if g['gate']==name)


def test_positive_a_path_selects_only_with_known_suspension():
    result=_run()
    assert result['state']=='READY' and result['evaluation_complete'] is True
    assert result['selected_count']==result['confirmed_selected_count']==1
    assert result['selected'][0]['symbol']=='HK.00001'
    payload=_payload()
    payload['hk_history']['rows'][0]['readiness']['field_readiness']['suspension']='PENDING'
    pending=_run(payload)
    assert pending['selected_count'] is None and pending['confirmed_selected_count']==0
    assert _gate(pending,'suspension')['state']=='PENDING'
    assert result['RESEARCH_ONLY'] is True
    assert all(result[k] is False for k in ['production_allowed','buy_gate_updated','orders_sent'])


def test_negative_primary_proxy_return_is_confirmed_zero():
    result=_run(relations=[_relation(return_pct='0.5')])
    assert result['state']=='READY' and result['evaluation_complete'] is True
    assert result['selected_count']==0 and result['rows'][0]['decision']=='REJECTED'
    assert _gate(result,'primary_return')['reasons']==['PRIMARY_US_RETURN_BELOW_1_PERCENT']


def test_missing_amount_field_is_unassessed_not_zero_or_a_candidate():
    payload=_payload()
    payload['hk_history']['rows'][0]['bars'][-1].pop('amount')
    result=_run(payload)
    assert result['state']=='CANNOT_CONFIRM' and result['evaluation_complete'] is False
    assert result['selected_count'] is None and result['confirmed_selected_count']==0
    assert result['rows'][0]['decision']=='PENDING'
    assert 'HK_AMOUNT_NONFINITE_OR_NEGATIVE' in result['gaps']


def test_secondary_individual_conflicts_but_sector_etf_is_context_only():
    industry=dict(symbol='HK.00001', proxy_paths=[dict(proxy_symbols=['FCG'],
        source_session='20261016', return_pct='-1.1', source_sha256=SHA,
        available_at='2026-10-18T21:00:00+00:00')])
    result=_run(industries=[industry])
    assert result['selected_count']==1
    assert _gate(result,'secondary_paths')['state']=='PASS'
    conflict=_run(relations=[_relation(us_symbol='AMD'),_relation(us_symbol='NVDA', return_pct='-1.1')])
    assert conflict['selected_count']==0
    assert _gate(conflict,'secondary_paths')['reasons']==['SECONDARY_INDIVIDUAL_CONFLICT']


def test_theme_cap_ranks_by_turnover_without_widening_scope():
    codes=[f'HK.{n:05d}' for n in range(1,5)]
    result=_run(_payload(codes, [_history(c, 20_000_000+n*1_000_000) for n,c in enumerate(codes,1)]),
        [_relation(c) for c in codes])
    assert result['counts']['candidate_count']==4
    assert [r['symbol'] for r in result['selected']]==codes[:0:-1]
    assert next(r for r in result['rows'] if r['symbol']==codes[0])['reasons']==['PRIMARY_THEME3_CAP']


def test_single_day_mapping_without_history_keeps_research_categories_and_pending_strict():
    codes=[f'HK.{n:05d}' for n in range(1,5)]
    relations=[_relation(codes[0]),_relation(codes[1],return_pct='-1.2'),
        _relation(codes[2],return_pct='0.5')]
    result=run_single_day_mapping(_context(),relation_rows=relations, industry_rows=[],
        factor_summary={},membership=dict(codes=codes))
    by_code={r['symbol']:r for r in result['rows']}
    assert {c:r['decision'] for c,r in by_code.items()}==dict(zip(codes,['BENEFIT','RISK','OBSERVATION','UNASSESSED']))
    assert result['strict_v1_status']=='EXECUTED' and result['evaluation_complete'] is False
    assert result['selected_count'] is None
    assert result['strict_selection']['counts']['candidate_count']==4
    # Research focus can trigger while independent strict financial proof is pending.
    assert result['strict_selection']['focus']['counts']['selected']==1
    assert result['confirmed_selected_count']==0
    assert result['RESEARCH_ONLY'] is True and result['production_allowed'] is False


def test_single_day_primary_is_fixed_before_returns_and_individual_conflicts_retained():
    result=run_single_day_mapping(_context(),relation_rows=[_relation(us_symbol='NVDA',return_pct='4'),
        _relation(us_symbol='AMD',return_pct='1.1')],industry_rows=[],factor_summary={},membership={})
    row=result['rows'][0]
    assert row['primary_us_symbol']=='AMD' and row['primary_signed_return_pct']=='1.1'
    assert [p['us_symbol'] for p in row['mapping_paths']]==['AMD','NVDA']
    assert row['strict_decision']=='PENDING'


def test_single_day_etf_only_has_no_primary_individual_trigger():
    industry=dict(symbol='HK.00001',proxy_paths=[dict(proxy_symbols=['XLE','FCG'])])
    result=run_single_day_mapping(_context(),relation_rows=[], industry_rows=[industry],
        factor_summary={},membership=dict(codes=['HK.00001']))
    assert result['rows'][0]['primary_proxy'] is None
    assert {p['role'] for p in result['rows'][0]['mapping_paths']}=={'SECTOR_CONTEXT'}
    focus=result['strict_selection']['focus']
    assert focus['counts']['selected']==0 and 'ETF_ONLY_BACKGROUND' in focus['decisions'][0]['reasons']


def test_single_day_catalog_placeholder_and_broad_path_remain_unassessed():
    placeholder=dict(symbol='HK.00027',us_symbol=None,relation_type='CATALOG_OBSERVATION_ONLY')
    industry=dict(symbol='HK.00027',proxy_paths=[dict(proxy_symbols=['XLY','XLP'])])
    result=run_single_day_mapping(_context(),relation_rows=[placeholder],industry_rows=[industry],
        factor_summary={},membership=dict(codes=['HK.00027']))
    assert len(result['rows'])==1
    assert result['rows'][0]['decision']=='UNASSESSED'
    assert len(result['rows'][0]['mapping_paths'])==3
    assert result['selected_count'] is None


def test_target_date_must_match_history_window_and_readiness():
    context=_context();context['target_date']='20261021'
    result=_run(context=context)
    assert result['state']=='CANNOT_CONFIRM' and result['selected_count'] is None
    assert _gate(result,'window')['state']=='PENDING'
    assert 'HK_FROZEN_SESSION_WINDOW_INVALID' in result['gaps']


@pytest.mark.parametrize('value',[None,True,'NaN','Infinity','invalid'])
def test_invalid_quote_cannot_be_confirmed_zero(value):
    relation=_relation();relation['quote']['change_pct']=value
    result=_run(relations=[relation])
    assert result['selected_count'] is None
    assert _gate(result,'primary_return')['state']=='PENDING'


def test_duplicate_identity_counts_once_and_conflicting_facts_stay_pending():
    relation=_relation()
    result=_run(relations=[relation,deepcopy(relation)])
    assert result['counts']['candidate_count']==1 and result['selected_count']==1
    assert len(result['candidates'][0]['paths'])==1
    conflict=_run(relations=[relation,_relation(return_pct='2')])
    assert conflict['counts']['candidate_count']==1 and conflict['selected_count'] is None
    assert 'DUPLICATE_MAPPING_PATH_CONFLICT' in conflict['candidates'][0]['reasons']


def test_rejected_row_with_pending_gate_is_not_complete_zero():
    payload=_payload();payload['hk_history']['rows'][0]['bars'][-1].pop('amount')
    result=_run(payload,[_relation(return_pct='0.5')])
    assert result['rows'][0]['decision']=='REJECTED' and result['counts']['pending']==0
    assert result['evaluation_complete'] is False and result['selected_count'] is None
    assert result['state']=='CANNOT_CONFIRM'


def test_empty_input_has_unknown_total_not_confirmed_zero():
    result=_run(payload={},relations=[])
    assert result['counts']['candidate_count']==0 and result['selected_count'] is None
    assert result['state']=='CANNOT_CONFIRM' and result['evaluation_complete'] is False


def test_legacy_projection_rejected_path_does_not_hide_pending_history():
    result=run_single_day_mapping(_context(),relation_rows=[_relation(return_pct='0.5')],
        industry_rows=[],factor_summary={},membership={})
    assert result['strict_selection']['counts']['pending']==0
    assert result['state']=='PARTIAL' and result['evaluation_complete'] is False
    assert result['selected_count'] is None and result['confirmed_selected_count']==0


@pytest.mark.parametrize(('field','value','gate'),[
    ('suspension','PENDING','suspension'),('pit','PENDING','pit'),
    ('eligibility','PENDING','eligibility'),('currency','PENDING','currency'),
])
def test_missing_certification_never_becomes_financial_selection(field,value,gate):
    payload=_payload()
    payload['hk_history']['rows'][0]['readiness']['field_readiness'][field]=value
    result=_run(payload)
    assert result['selected_count'] is None and _gate(result,gate)['state']=='PENDING'


def test_conflicting_duplicate_history_is_not_arbitrarily_chosen():
    payload=_payload()
    conflicting=deepcopy(payload['hk_history']['rows'][0]['bars'][-1])
    conflicting['close']='101'
    payload['hk_history']['rows'][0]['bars'].append(conflicting)
    result=_run(payload)
    assert result['selected_count'] is None
    assert 'HK_HISTORY_CONFLICTING_DUPLICATE_SESSION' in result['gaps']


def test_mixed_selected_and_pending_reports_confirmed_subset_and_unknown_total():
    codes=['HK.00001','HK.00002'];payload=_payload(codes)
    payload['hk_history']['rows'][1]['bars'][-1].pop('amount')
    result=_run(payload,[_relation(c) for c in codes])
    assert result['selected_count'] is None and result['confirmed_selected_count']==1
    assert [r['symbol'] for r in result['selected']]==['HK.00001']
    assert result['counts']['selected']==1 and result['counts']['pending']==1
