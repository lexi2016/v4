"""Bounded owned-fixture tests of the explicit read-only A native close root."""
import ast
from pathlib import Path
import json
import runpy

import pytest

from apps.api.v4_api import review_router as router_module
from domains.a_share_review import build_a_share_review
from infrastructure.a_share_review_store import AShareReviewStore
from infrastructure.data_store import _sha256

OWNED = Path(__file__).resolve().parents[1]
API_APP = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/daily-r19-profile-20261029-r1-api/app')
DATE = '20261028'
FLAGS = ('production_allowed', 'buy_gate_updated', 'orders_sent')


def native_review(date=DATE, role='V3_5_NATIVE_CLOSE_MODEL'):
    return build_a_share_review(date, big_picture=[dict(trade_date=date, title='synthetic original close')],
        mainlines=[], core_stocks=[], observation_pool=[], trigger_rows=[], quality_gate_rows=[],
        source_sha256='a'*64, source_role=role, cannot_confirm=['SYNTHETIC_PARTIAL_CLOSE'])


@pytest.fixture
def isolated_readers(monkeypatch):
    calls = []
    monkeypatch.setattr(router_module, '_hk_securities_calendar_state', lambda date: router_module.TradingDayState.NON_TRADING_DAY)
    monkeypatch.setattr(router_module, 'review_core_a_share_bundle_required', lambda root,date: calls.append(('strict',root,date)) or False)
    monkeypatch.setattr(router_module, 'load_review_evidence_layers', lambda root,date,review: calls.append(('layers',root,date)) or {})
    monkeypatch.setattr(router_module, 'load_daily_research_review', lambda *args,**kwargs: dict(status='CANNOT_CONFIRM'))
    import domains.intraday_research
    monkeypatch.setattr(domains.intraday_research, 'read_intraday_day', lambda *args,**kwargs: dict(status='CANNOT_CONFIRM', slots=[]))
    return calls


def endpoint(data_root, *, a_close_root=None):
    router = router_module.create_review_router(data_root, a_close_root=a_close_root,
        review_root=data_root/'daily', intraday_root=data_root/'intraday', hk_close_root=data_root/'hk')
    return next(route.endpoint for route in router.routes if route.path == '/api/v4/review')


def test_explicit_native_root_does_not_rebind_strict_or_evidence_roots(tmp_path,monkeypatch,isolated_readers):
    main,close = tmp_path/'api',tmp_path/'original-close'
    original=native_review();AShareReviewStore(close).import_review(original)
    monkeypatch.setattr(router_module, '_read_exact_stage_review_rows', lambda *args: pytest.fail('native result must keep precedence over Stage fallback'))
    result=endpoint(main,a_close_root=close)(DATE)
    assert result['market_reviews']['A']==original
    assert all(root==main for _,root,_ in isolated_readers)
    assert all(result[key] is False for key in FLAGS)
    assert result['market_reviews']['A']['cannot_confirm']==['SYNTHETIC_PARTIAL_CLOSE']


def test_omitted_a_root_keeps_original_data_root_compatibility(tmp_path,isolated_readers):
    original=native_review();AShareReviewStore(tmp_path).import_review(original)
    assert endpoint(tmp_path)(DATE)['market_reviews']['A']==original


def test_strict_core_failure_does_not_fallback_to_native_other_root(tmp_path,monkeypatch,isolated_readers):
    main,close = tmp_path/'api',tmp_path/'original-close'
    AShareReviewStore(close).import_review(native_review())
    monkeypatch.setattr(router_module, 'review_core_a_share_bundle_required', lambda root,date: True)
    def broken(date,root):
        assert root==main
        raise ValueError('synthetic strict bundle SHA mismatch')
    monkeypatch.setattr(router_module, 'load_review_core_a_share_review', broken)
    monkeypatch.setattr(router_module, 'AShareReviewStore', lambda *args: pytest.fail('strict Core failure cannot consult native close fallback'))
    result=endpoint(main,a_close_root=close)(DATE)
    assert result['review_core_bundle']['status']=='CANNOT_CONFIRM'
    assert result['market_reviews']['A']['status']=='NOT_MATERIALIZED'
    assert 'REVIEW_CORE_BUNDLE_INVALID' in result['market_reviews']['A']['cannot_confirm'][0]


@pytest.mark.parametrize('fault',['wrong_date','wrong_role','sha_drift'])
def test_explicit_root_keeps_existing_date_role_sha_refusals(tmp_path,isolated_readers,fault):
    close=tmp_path/'close';main=tmp_path/'api'
    original=native_review('20261027' if fault=='wrong_date' else DATE,
        'LEGACY_FINAL_API_ORACLE' if fault=='wrong_role' else 'V3_5_NATIVE_CLOSE_MODEL')
    AShareReviewStore(close).import_review(original)
    if fault=='sha_drift':
        path=close/f'a_share_reviews/{DATE}.json'
        changed=json.loads(path.read_text());changed['headline']='synthetic corrupt bytes'
        path.write_text(json.dumps(changed))
    result=endpoint(main,a_close_root=close)(DATE)
    assert result['market_reviews']['A']['status']=='NOT_MATERIALIZED'
    assert all(result[key] is False for key in FLAGS)


def test_missing_native_close_still_reads_partial_stage_from_main_data_root(tmp_path,isolated_readers):
    helper=runpy.run_path(str(API_APP/'tests/test_review_partial_stage_surface.py'))['_publish_stage']
    from infrastructure.stage_store import StageStore
    main=tmp_path/'api';close=tmp_path/'empty-native-close'
    helper(StageStore(main),DATE,'STAGE_0930_0935',1)
    result=endpoint(main,a_close_root=close)(DATE)
    review=result['market_reviews']['A']
    assert review['status']=='PARTIAL_STAGE_EVIDENCE'
    assert len(review['stage_validation_rows'])==1
    assert all(root==main for _,root,_ in isolated_readers)
    assert not close.exists()


def test_app_uses_existing_server_bound_close_root_for_both_markets(monkeypatch,tmp_path):
    # Evaluate only the two real factory argument expressions; avoid unrelated
    # application startup, background executors or any live HTTP interaction.
    source=OWNED/'sources/api/apps/api/v4_api/app.py'
    tree=ast.parse(source.read_text())
    call=next(node for node in ast.walk(tree) if isinstance(node,ast.Call)
        and isinstance(node.func,ast.Name) and node.func.id=='create_review_router')
    expressions={kw.arg:kw.value for kw in call.keywords}
    import os
    for value in (None,str(tmp_path/'original-close')):
        if value is None:monkeypatch.delenv('V4_REVIEW_CORE_CLOSE_ROOT',raising=False)
        else:monkeypatch.setenv('V4_REVIEW_CORE_CLOSE_ROOT',value)
        for key in ('a_close_root','hk_close_root'):
            compiled=compile(ast.Expression(expressions[key]),str(source),'eval')
            assert eval(compiled,{'os':os})==value


def test_readonly_actual_original_close_can_be_projected_without_rebuild(tmp_path,isolated_readers):
    close=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
    original=AShareReviewStore(close).read_review(DATE)
    assert original is not None
    before=_sha256(original)
    assert before=='e3d7d5495d5402bac44af1471763901eede2ab39b9abd0630476736356043df2'
    result=endpoint(tmp_path/'isolated-api',a_close_root=close)(DATE)
    projected=result['market_reviews']['A']
    assert _sha256(projected)==before
    assert projected['source_role']=='V3_5_NATIVE_CLOSE_MODEL'
    assert projected['cannot_confirm']==original['cannot_confirm']
    assert all(projected[key] is False for key in FLAGS)
    assert _sha256(AShareReviewStore(close).read_review(DATE))==before
    (OWNED/'A_CLOSE_ACTUAL_CANDIDATE_READBACK.json').write_text(json.dumps(dict(
        mode='INPROCESS_CANDIDATE_READONLY_ORIGINAL_CLOSE_NOT_ACTIVE_API',trade_date=DATE,
        canonical_sha256=before,source_role=projected['source_role'],cannot_confirm=projected['cannot_confirm'],
        natural_verified=False,active_api_verified=False,producer_rerun=False,panel_rehashed=False,
        production_allowed=False,buy_gate_updated=False,orders_sent=False),ensure_ascii=False,indent=2)+'\n')
