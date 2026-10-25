"""Frozen-scope reader regression tests: no financial truth or collector calls."""
import ast
import copy
import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping
import pytest
from fastapi import HTTPException

HERE = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('restore_helper', HERE / 'ops/restore_a_share_stage_history.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
sys.path.insert(0, str(helper.RUNTIME))


def function(source, exact_reader):
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                and n.name == '_read_exact_target_hk_override')
    module = ast.Module(body=[node], type_ignores=[])
    scope = {'Any': Any, 'Mapping': Mapping, 'HTTPException': HTTPException,
             'stage_workbench': exact_reader}
    exec(compile(module, '<actual-runtime-exact-target-reader>', 'exec'), scope)
    return scope['_read_exact_target_hk_override']


def payload():
    return {'markets': {'A_SHARE': {
        'selection_manifest_receipt_verified': True,
        'selected_rows': 10, 'rows': [{'code': 'SH.600001'}],
        'run_id': 'verified-a-run', 'selection_mode': 'BACKFILL'},
        'HK_CONNECT': {'rows': [{'code': 'HK.00001'}], 'run_id': 'stale-hk'}},
        'execution_evidence': {'markets': {'A_SHARE': {'proof': 'original-a'},
                                         'HK_CONNECT': {'proof': 'old-hk'}}}}


def reject(**kwargs):
    assert kwargs['market'] == 'HK_CONNECT'
    raise HTTPException(409, 'backfill selection safety or SHA binding is invalid')


def call(fn, p, day='20260929', stage='STAGE_1445_1500'):
    return fn(p, day, stage, 50, {'backfill_run_id': 'bound-hk'},
              source_label='EXACT_HK_BINDING', target_pool_sha256='a' * 64)


def test_reproduces_original_cross_market_409():
    original = function((helper.RUNTIME / 'apps/api/v35_api/app.py').read_text(), reject)
    with pytest.raises(HTTPException) as error:
        call(original, payload())
    assert error.value.status_code == 409


@pytest.mark.parametrize('day', ['20260929', '20260930'])
def test_two_targets_preserve_a_and_quarantine_hk(day):
    original = (helper.RUNTIME / 'apps/api/v35_api/app.py').read_text()
    fn = function(helper.patched_source(original), reject)
    p = payload()
    before = copy.deepcopy(p)
    result = call(fn, p, day)
    assert p == before
    assert result['markets']['A_SHARE'] == before['markets']['A_SHARE']
    assert result['execution_evidence']['markets']['A_SHARE'] == before['execution_evidence']['markets']['A_SHARE']
    hk = result['markets']['HK_CONNECT']
    assert hk['rows'] == [] and hk['status'] == 'CANNOT_CONFIRM'
    assert 'EXACT_TARGET_HK_BINDING_INVALID' in hk['cannot_confirm']
    assert hk['recovery_provenance']['http_status'] == 409
    assert result['execution_evidence']['natural_verified'] is False


@pytest.mark.parametrize('day,stage', [('20260928', 'STAGE_1445_1500'),
                                      ('20260929', 'STAGE_1300_1315')])
def test_unrelated_slots_keep_original_rejection(day, stage):
    fn = function(helper.patched_source((helper.RUNTIME / 'apps/api/v35_api/app.py').read_text()), reject)
    with pytest.raises(HTTPException):
        call(fn, payload(), day, stage)


def test_unverified_a_does_not_bypass_hk_failure():
    fn = function(helper.patched_source((helper.RUNTIME / 'apps/api/v35_api/app.py').read_text()), reject)
    p = payload()
    p['markets']['A_SHARE']['selection_manifest_receipt_verified'] = False
    with pytest.raises(HTTPException):
        call(fn, p)


def test_successful_hk_override_behavior_unchanged():
    original = (helper.RUNTIME / 'apps/api/v35_api/app.py').read_text()
    def valid(**kwargs):
        return {'selection_markets': {'HK_CONNECT': {'run_id': 'bound-hk', 'rows': []}}}
    before = call(function(original, valid), payload())
    after = call(function(helper.patched_source(original), valid), payload())
    assert after == before


def test_source_drift_fails_closed():
    with pytest.raises(ValueError, match='CALLSITE_DRIFT'):
        helper.patched_source('pass\n')

# Incremental22 scope. Run with -k incremental; prior accepted eight stay deselected.
_incremental_path = HERE / 'research/a_share_v4_stage_history_restore_20261025/incremental_r3.py'
_incremental_spec = importlib.util.spec_from_file_location('incremental_r3', _incremental_path)
incremental = importlib.util.module_from_spec(_incremental_spec)
_incremental_spec.loader.exec_module(incremental)
_INCREMENTAL_CASES = incremental.frozen_targets() + [
    ('20260929', 'STAGE_1445_1500'), ('20260930', 'STAGE_1445_1500')]


@pytest.fixture(scope='module')
def incremental_reader():
    return incremental.reader_namespace((incremental.OUT / 'candidate_r3b/app.py').read_text())


@pytest.mark.parametrize('day,stage', _INCREMENTAL_CASES)
def test_incremental_actual22_and_previous2_preserve_native_a(incremental_reader, day, stage):
    ns = incremental_reader
    expected = ns['shared_selection_consumer'].get(day, stage, markets=('A_SHARE',), allow_backfill=True)['markets']['A_SHARE']
    assert expected['selection_manifest_receipt_verified'] is True
    result = ns['stage_workbench'](date=day, stage=stage, limit=50, market=None, backfill_run_id=None)
    actual = result['selection_markets']['A_SHARE']
    for field in ['rows', 'run_id', 'artifact_id', 'selected_rows', 'algorithm_sha256',
                  'raw_artifact_sha256', 'selection_manifest_sha256',
                  'selection_receipt_sha256', 'selection_artifact_sha256',
                  'source_status', 'selection_status']:
        assert actual.get(field) == expected.get(field), (day, stage, field)
    assert len(actual['rows']) == actual['selected_rows'] == 10
    hk = result['selection_markets']['HK_CONNECT']
    assert hk['rows'] == [] and hk['status'] == 'CANNOT_CONFIRM'
    assert result['execution_evidence']['natural_verified'] is False


def test_incremental_direct_hk_guard_still_rejects(incremental_reader):
    ns = incremental_reader
    key = ('20260918', 'STAGE_0930_0935')
    binding = ns['_HK_R8_BINDING_BY_DATE_STAGE'].get(key) or ns['_HK_R9_BINDING_BY_DATE_STAGE'][key]
    with pytest.raises(HTTPException) as error:
        ns['stage_workbench'](date=key[0], stage=key[1], limit=50,
                              market='HK_CONNECT', backfill_run_id=binding['backfill_run_id'])
    assert error.value.status_code == 409
    assert error.value.detail == 'backfill selection safety or SHA binding is invalid'


def test_incremental_direct_approved_a_guard_still_rejects(incremental_reader):
    ns = incremental_reader
    with pytest.raises(HTTPException) as error:
        ns['stage_workbench'](date='20261009', stage='STAGE_0930_0935', limit=50,
                              market='A_SHARE', backfill_run_id='85e29661ecd848fe9b8344ea59279e86')
    assert error.value.status_code == 409
    assert error.value.detail == 'approved research read binding is unavailable or invalid'


def test_incremental_bad_ordinary_a_cannot_hide_approved_failure(incremental_reader):
    ns = incremental_reader
    original = ns['shared_selection_consumer']
    class BadA:
        def get(self, *args, **kwargs):
            return {'markets': {'A_SHARE': {'selection_manifest_receipt_verified': False,
                    'selected_rows': 10, 'rows': [{'code': 'SH.600001'}]}}}
    ns['shared_selection_consumer'] = BadA()
    try:
        with pytest.raises(HTTPException) as error:
            ns['stage_workbench'](date='20261009', stage='STAGE_0930_0935', limit=50,
                                  market=None, backfill_run_id=None)
        assert error.value.status_code == 409
    finally:
        ns['shared_selection_consumer'] = original


def test_incremental_unrelated_approved_error_is_not_swallowed(incremental_reader):
    ns = incremental_reader
    original = ns['approved_research_reader']
    class Rejected:
        def get(self, *args, **kwargs):
            raise ns['ResearchReadError']('UNRELATED_SHARED_GUARD')
    ns['approved_research_reader'] = Rejected()
    try:
        with pytest.raises(HTTPException) as error:
            ns['stage_workbench'](date='20260928', stage='STAGE_0925', limit=50,
                                  market=None, backfill_run_id=None)
        assert error.value.status_code == 409
    finally:
        ns['approved_research_reader'] = original


def test_incremental_day24_direct_hk_guard_still_rejects(incremental_reader):
    ns = incremental_reader
    with pytest.raises(HTTPException) as error:
        ns['stage_workbench'](date='20260924', stage='STAGE_0930_0935', limit=50,
                              market='HK_CONNECT', backfill_run_id='1d3ab9f9bd3a44c3811bf1fed2b74108')
    assert error.value.status_code == 409
    assert error.value.detail == 'backfill selection safety or SHA binding is invalid'
