"""Frozen policy behavior through the actual mapping entry, using certified fixtures."""
from copy import deepcopy
import hashlib,json
from datetime import datetime
import pytest
from v4.manager_workbench.engines.us_mapping import run_us_mapping
from v4.manager_workbench.engines.strict_us_selection import _expected_sessions
from v4.manager_workbench.engines.common import US_FACTOR_RULES_VERSION
from v4.manager_workbench.inputs.us_universe import LEGACY_US_SYMBOLS
from v4.manager_workbench.contracts import LaneResult, seal_snapshot, digest
from upstreams.v3_shared_data.shared_data.hk_panel_audit import strict_window_readiness

SHA='a'*64
CUTOFF='2026-10-23T06:00:00+08:00'


def fixture_batch(tmp_path,codes=('HK.00001',),*,returns='1.5',turnover=25_000_000):
    context=dict(market='HK_CONNECT',target_date='20261023',phase='RETROSPECTIVE',trigger='MANUAL',cutoff=CUTOFF,
        source_sessions=dict(us='20261022',hk_price='20261022'),rules_version=US_FACTOR_RULES_VERSION,
        scope_refs=dict(run_id='f'*32,requested_lanes=['US_MAPPING']))
    universe='us:LEGACY_US_UNIVERSE_V1:20261023'
    context['scope_refs']['US_MAPPING']=dict(universe_ref=universe,configured_symbols=list(LEGACY_US_SYMBOLS),
        universe_version='LEGACY_US_UNIVERSE_V1',source_session='20261022',verification='VERIFIED',sha256=SHA,calendar_verified=True)
    records=[]
    for us in LEGACY_US_SYMBOLS:
        value=returns if us=='NVDA' else '1.5'
        quote=dict(symbol=us,session_date='20261022',last=str(100+float(value)),previous_close='100',change_pct=value)
        relations=[]
        if us=='NVDA':
            for code in codes:
                relations.append(dict(target_symbol=code,target_name=code,relation_type='NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER',
                    status='REVIEWED',sha256=SHA,review_owner='reviewer',available_at='2026-10-22T16:00:00+08:00',
                    published_at='2026-10-21T16:00:00+08:00',current_validity='CURRENT_SUPPORTED',direction='POSITIVE',evidence_ids=['source'],
                    membership=dict(verification='VERIFIED',owner='membership',sha256=SHA,eligible=True,
                        effective_from='20261001',effective_through='20261031',available_at='2026-10-21T16:00:00+08:00')))
        records.append(dict(us_symbol=us,source_session='20261022',source_status='PRIORITY',owner='QUOTE_OWNER',
            source_sha256=SHA,available_at='2026-10-23T05:00:00+08:00',positive_change_required=True,
            quote=quote,evidence_ids=['source'],relations=relations))
    sessions=_expected_sessions(context)
    rows=[]
    for code in codes:
        bars=[dict(date=day,open=100.0,high=100.0,low=100.0,close=100.0,amount=float(turnover),suspended=False) for day in sessions]
        material_records=[dict(code=code,date=day,panel_sha256=SHA,available_at='2026-10-23T05:00:00+08:00',
            price_currency='HKD',amount_currency='HKD',amount_unit='HKD',adjustment='PIT_ADJUSTED',corporate_actions_complete=True,
            pit_available=True,eligible=True,suspended=False,listing_date='20000101') for day in [*sessions,context['target_date']]]
        material=dict(schema_version='hk_panel_strict_material.v1',market='HK',panel_sha256=SHA,records=material_records,
            research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
        path=tmp_path/(code+'.json');path.write_text(json.dumps(material,sort_keys=True));msha=hashlib.sha256(path.read_bytes()).hexdigest()
        proof=[dict(r,evidence_refs=[dict(reference=str(path),sha256=msha)]) for r in material_records]
        readiness=strict_window_readiness([dict(b,code_norm=code) for b in bars],code=code,sessions=sessions,cutoff=CUTOFF,
            panel_sha256=SHA,proof=proof,target_date=context['target_date'])
        assert readiness['status']=='PASS',readiness
        rows.append(dict(symbol=code,bars=bars,readiness=readiness))
    history=dict(status='READY',rows=rows,close_sessions=sessions,amount_sessions=sessions[-20:],panel_sha256=SHA,
        panel_manifest_sha256=SHA,panel_available_at='2026-10-23T05:00:00+08:00',panel_owner='certified_fixture')
    records[0]['us_factor_payload']=dict(strict_selection_payload=dict(monthly_membership=dict(codes=list(codes)),hk_history=history))
    return context,dict(context=context,lane='US_MAPPING',universe_ref=universe,records=records,run_id='f'*32,
        input_sha256=SHA,evidence_refs=[dict(evidence_id='source',owner='source',role='US_MAPPING_SOURCE',verification='VERIFIED',sha256=SHA,
            artifact_ref='fixture',available_at='2026-10-23T05:00:00+08:00')],scope_description='certified fixtures',coverage=dict(scope_count=33,observed_count=33),gaps=[])


def history(batch):return batch['records'][0]['us_factor_payload']['strict_selection_payload']['hk_history']
def source(batch,us='NVDA'):return next(r for r in batch['records'] if r['us_symbol']==us)
def decision(result,code='HK.00001'):return next(d for d in result['selection']['strict_decisions'] if d['symbol']==code)


def test_true_entry_certified_positive_propagates_to_merged_stock(tmp_path):
    from v4.manager_workbench.engines.core import merge_decisions
    c,b=fixture_batch(tmp_path);r=run_us_mapping(c,b);d=decision(r)
    assert d['decision']=='SELECTED' and all(g['state']=='PASS' for g in d['gates'])
    assert r['selection']['counts']['selected']==1
    lane=LaneResult.model_validate(r)
    merged=merge_decisions(c,[lane.model_dump(mode='json')])
    assert merged[0]['decision']=='SELECTED'
    assert lane.selection.strict_decisions[0].decision=='SELECTED'


def test_known_failure_has_precedence_and_retains_pending_proof_reasons(tmp_path):
    c,b=fixture_batch(tmp_path,returns='0.5');history(b)['rows'][0]['readiness']={}
    d=decision(run_us_mapping(c,b))
    assert d['state']=='REJECT' and d['decision']=='REJECTED'
    assert 'PRIMARY_US_RETURN_BELOW_1_PERCENT' in d['reasons']
    assert any('PROOF_PENDING' in r for r in d['reasons'])


@pytest.mark.parametrize('mutate',[
    lambda h:h['rows'][0].pop('readiness'),
    lambda h:h['rows'][0]['readiness'].update(target_date='20261022'),
    lambda h:h['rows'][0]['readiness'].update(panel_sha256='b'*64),
    lambda h:h['rows'][0]['readiness'].update(cutoff='2026-10-24T00:00:00+08:00'),
    lambda h:h.update(panel_available_at='2026-10-24T00:00:00+08:00'),
    lambda h:h['close_sessions'].__setitem__(0,'20260901'),
])
def test_missing_malformed_or_time_unsafe_proof_stays_pending(tmp_path,mutate):
    c,b=fixture_batch(tmp_path);mutate(history(b));d=decision(run_us_mapping(c,b));assert d['state']=='PENDING'


@pytest.mark.parametrize('field,reason',[('symbol','QUOTE_SYMBOL_MISMATCH'),('last','QUOTE_RETURN_MISMATCH')])
def test_quote_identity_or_arithmetic_cannot_select(tmp_path,field,reason):
    c,b=fixture_batch(tmp_path);source(b)['quote'][field]='AMD' if field=='symbol' else '999'
    d=decision(run_us_mapping(c,b));assert d['state']=='PENDING';assert reason in d['reasons']


@pytest.mark.parametrize('field',['eligibility','suspension'])
def test_known_target_rejection_survives_other_pending_gate(tmp_path,field):
    c,b=fixture_batch(tmp_path);ready=history(b)['rows'][0]['readiness'];ready['field_readiness'][field]='REJECT';ready['field_readiness']['currency']='PENDING';ready['status']='REJECT'
    d=decision(run_us_mapping(c,b));assert d['state']=='REJECT';assert any(g['state']=='PENDING' for g in d['gates'])


def test_identical_history_duplicates_merge_but_contradictions_pending(tmp_path):
    c,b=fixture_batch(tmp_path);bars=history(b)['rows'][0]['bars'];bars.append(deepcopy(bars[-1]));assert decision(run_us_mapping(c,b))['decision']=='SELECTED'
    bars[-1]['close']=999;d=decision(run_us_mapping(c,b));assert d['state']=='PENDING';assert 'HK_HISTORY_CONFLICTING_DUPLICATE_SESSION' in d['reasons']


def test_negative_etf_is_context_only_no_veto(tmp_path):
    c,b=fixture_batch(tmp_path);etf=source(b,'SOXX');etf['quote'].update(last='98',change_pct='-2');etf['relations']=deepcopy(source(b)['relations'])
    r=run_us_mapping(c,b);assert decision(r)['decision']=='SELECTED';paths=r['selection']['candidates'][0]['paths'];assert next(p for p in paths if p['us_symbol']=='SOXX')['role']=='SECTOR_CONTEXT'


def test_current_individual_secondary_negative_rejects_and_unknown_is_pending(tmp_path):
    c,b=fixture_batch(tmp_path);other=source(b,'AMD');other['relations']=deepcopy(source(b)['relations']);source(b)['quote'].update(last='98',change_pct='-2')
    r=run_us_mapping(c,b);assert decision(r)['state']=='REJECT';assert 'SECONDARY_INDIVIDUAL_CONFLICT' in decision(r)['reasons']
    # Primary is AMD by identity order, before its return is read.
    source(b)['quote'].update(last='102',change_pct='2');source(b)['relations'][0]['direction']=None
    assert decision(run_us_mapping(c,b))['state']=='PENDING'


def test_mapping_duplicate_conflict_isolated_while_unaffected_stock_selects(tmp_path):
    c,b=fixture_batch(tmp_path,codes=('HK.00001','HK.00002'));duplicate=deepcopy(source(b)['relations'][0]);duplicate['direction']='NEGATIVE';source(b)['relations'].append(duplicate)
    r=run_us_mapping(c,b);assert decision(r)['state']=='PENDING';assert decision(r,'HK.00002')['decision']=='SELECTED'
    assert 'DUPLICATE_MAPPING_PATH_CONFLICT' in decision(r)['reasons']


def test_business_peer_requires_separate_specific_relation_evidence(tmp_path):
    c,b=fixture_batch(tmp_path);source(b)['relations'][0]['relation_type']='BUSINESS_PEER'
    d=decision(run_us_mapping(c,b));assert d['state']=='PENDING';assert d['decision']!='SELECTED'


def test_numeric_threshold_boundaries_and_turnover(tmp_path):
    c,b=fixture_batch(tmp_path,returns='1',turnover=20_000_000);assert decision(run_us_mapping(c,b))['decision']=='SELECTED'
    for bar in history(b)['rows'][0]['bars']:bar['amount']=19_999_999
    d=decision(run_us_mapping(c,b));assert d['state']=='REJECT';assert 'TURNOVER20_MIN_FAILED' in d['reasons']


def test_caps_rank_complete_qualified_scope_and_preserve_stable_candidate_order(tmp_path):
    codes=tuple(f'HK.{i:05d}' for i in range(1,13));c,b=fixture_batch(tmp_path,codes=codes)
    rels=source(b)['relations']
    for i,relation in enumerate(rels):relation['primary_theme']=f'THEME{i//3}'
    r=run_us_mapping(c,b);assert r['selection']['counts']['selected']==10;assert r['selection']['counts']['qualified_not_selected']==2
    assert all(d['qualified'] and d['state']=='PASS' for d in r['selection']['strict_decisions'])
    assert r['selection']['candidates'][0]['symbol']=='HK.00001'
    source(b)['relations'].reverse();reverse=run_us_mapping(c,b);assert reverse['selection']==r['selection']
    for relation in source(b)['relations']:relation['primary_theme']='SAME'
    cap=run_us_mapping(c,b);assert cap['selection']['counts']['selected']==3
    assert sum('PRIMARY_THEME3_CAP' in d['reasons'] for d in cap['selection']['strict_decisions'])==9


@pytest.mark.parametrize('field',['currency','adjustment','pit','amount'])
def test_unproven_basis_cannot_manufacture_numeric_rejection(tmp_path,field):
    c,b=fixture_batch(tmp_path,turnover=1)
    ready=history(b)['rows'][0]['readiness'];ready['field_readiness'][field]='PENDING';ready['status']='PENDING'
    d=decision(run_us_mapping(c,b));states={g['gate']:g['state'] for g in d['gates']}
    if field in {'currency','pit','amount'}:assert states['turnover20_min']=='PENDING'
    if field in {'currency','adjustment','pit'}:assert states['close_ma20_min']=='PENDING'
    if field=='adjustment':assert d['state']=='REJECT'  # independently certified HKD amount failure
    else:assert d['state']=='PENDING'


def test_rejected_with_unknown_gate_and_empty_input_are_not_complete(tmp_path):
    c,b=fixture_batch(tmp_path,returns='0.5');history(b)['rows'][0]['readiness']={}
    selection=run_us_mapping(c,b)['selection']
    assert selection['counts']['rejected']==1 and selection['evaluation_complete'] is False
    assert 'STRICT_EVALUATION_INCOMPLETE' in selection['gaps']
    from v4.manager_workbench.engines.strict_us_selection import build_selection
    assert build_selection(c,[],{}).evaluation_complete is False


def test_named_legacy_research_hypothesis_kept_without_strict_promotion(tmp_path):
    c,b=fixture_batch(tmp_path)
    for key in ['current_validity','direction']:source(b)['relations'][0].pop(key)
    r=run_us_mapping(c,b);candidate=r['selection']['candidates'][0]
    assert candidate['research_state']=='dated_weak' and candidate['direction']=='POSITIVE'
    assert {'RELATION_CURRENT_VALIDITY_PENDING','RELATION_DIRECTION_PENDING'}<=set(candidate['reasons'])
    assert decision(r)['state']=='PENDING' and r['selection']['evaluation_complete'] is False


def test_source_current_enum_adaptation_is_exact_and_scope_preserving():
    from v4.manager_workbench.engines.us_mapping_consumption import _current_scope_class
    from v4.manager_workbench.engines.us_mapping_policy import CURRENT_RESEARCH_SCOPE_ALIASES,DATED_RESEARCH_SCOPE_ALIASES
    assert all(_current_scope_class(s)=='LIMITED_SCOPE_SUPPORTED_FOR_RESEARCH' for s in CURRENT_RESEARCH_SCOPE_ALIASES)
    assert all(_current_scope_class(s)=='DATED_OR_PENDING_SCOPE' for s in DATED_RESEARCH_SCOPE_ALIASES)
    assert _current_scope_class('ANY_FREE_TEXT_SUPPORTED')=='UNRECOGNIZED_CURRENT_APPLICABILITY'


def test_full_roster_hk_code_identity_survives_even_without_paths(tmp_path):
    c,b=fixture_batch(tmp_path)
    from v4.manager_workbench.engines.us_mapping_consumption import normalize_mapping_candidates
    candidates=normalize_mapping_candidates(c,relation_rows=[],identities=[dict(hk_code='00001',hk_name='one'),dict(hk_code='00002')])
    assert [x.symbol for x in candidates]==['HK.00001','HK.00002']
    assert all(x.research_state=='pending' and x.reasons==['NO_MAPPING_PATH'] for x in candidates)


def test_explicit_invalid_industry_pin_does_not_fall_back_to_template():
    from types import SimpleNamespace
    from v4.manager_workbench.inputs.source_bindings import hk_industry_classification
    config=SimpleNamespace(source_bindings={'hk_industry_classification':{'observed_policy_template':{'policy':'LATEST_OBSERVED'}}})
    ctx=SimpleNamespace(target_date='20261023',scope_refs={'owner_bindings':{'hk_industry_classification':None}})
    assert hk_industry_classification(config,ctx)==dict(status='UNAVAILABLE',gap='HK_INDUSTRY_CLASSIFICATION_EXPLICIT_PIN_INVALID')


@pytest.mark.parametrize('fault',[None,'scope','late','parent'])
def test_exact_parent_history_reconciliation_retains_scope_cutoff_and_sha_guards(tmp_path,monkeypatch,fault):
    from types import SimpleNamespace
    from v4.manager_workbench.inputs import source_bindings as sb
    from upstreams.v3_shared_data.shared_data import hk_daily_supplement as supplement
    config=SimpleNamespace(shared_root=tmp_path);ctx=SimpleNamespace(source_sessions={'hk_price':'20261022'},cutoff=CUTOFF)
    panel=dict(manifest_relative='panel.json',manifest_sha256='a'*64)
    master=dict(manifest_relative='master.json',manifest_sha256='b'*64)
    pi=dict(panel_manifest_sha256='a'*64)
    mi=dict(manifest_relative='master.json',manifest_sha256='b'*64,artifact_sha256='c'*64)
    def read(root,relative,expected=None):
        if relative=='panel.json':return dict(panel_sha256='d'*64),'a'*64
        if relative=='master.json':return dict(trade_date='20261022',artifact_sha256='x'*64 if fault=='parent' else 'c'*64),'b'*64
        return dict(raw_relative='raw.json',raw_sha256='e'*64,run_id='fixture',available_at='2026-10-23T05:00:00+08:00',capture_scope='FULL' if fault=='scope' else 'PANEL_GAPS'),'f'*64
    monkeypatch.setattr(sb,'read',read);monkeypatch.setattr(sb,'files',lambda *args:[])
    monkeypatch.setattr(supplement,'_read_panel_identity',lambda *a,**kw:pi)
    monkeypatch.setattr(supplement,'_read_master_identity',lambda *a:(mi,['HK.00001']))
    def checked(pin,**kw):
        assert kw==dict(target_date='20261022',cutoff=CUTOFF,expected_panel_sha='d'*64,expected_master_sha='c'*64,expected_codes=['HK.00001'],expected_panel_manifest_sha='a'*64,expected_master_manifest_sha='b'*64)
        return dict(panel_identity=pi,master_identity=mi,available_at='2026-10-24T05:00:00+08:00' if fault=='late' else '2026-10-23T05:00:00+08:00'),{}
    monkeypatch.setattr(supplement,'read_tdxpy_window_supplement',checked)
    configured=dict(source_local_path=str(tmp_path/'assets/hk_0_2/daily_supplements/tdxpy61'),manifest_relative='candidate.json',manifest_sha256='f'*64)
    if fault=='parent':
        with pytest.raises(ValueError,match='TDXPY_MASTER_PARENT_BINDING_MISMATCH'):sb._tdxpy_history_for_exact_parents(config,ctx,panel,master,configured)
    else:
        result=sb._tdxpy_history_for_exact_parents(config,ctx,panel,master,configured)
        assert (result is not None)==(fault is None)
