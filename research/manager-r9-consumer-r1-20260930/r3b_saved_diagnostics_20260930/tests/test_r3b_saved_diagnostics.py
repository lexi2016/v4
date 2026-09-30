"""R3-B: real manager plan writer/store/readback, synthetic upstream data only.

No _read_plan/_readback_plan/refresh_workspace_plan/_compute_workspace or store
method is replaced. No real eligibility/announcement/provider/API claim.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from domains import manager_research_evidence as authority
from v4.manager_research import workspace as ws
from v4.manager_research import workspace_announcements as announcements
from v4.manager_research import us_market_bridge as us_bridge
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS, digest
from v4.manager_research.safety import assert_manager_safe_tree

DATE = '20260930'
SAVE_AT = datetime.fromisoformat('2026-09-30T08:00:00+08:00')
READ_AT = datetime.fromisoformat('2026-09-30T08:01:00+08:00')
OLD_PIN, NEW_PIN = '1' * 64, '2' * 64
ALLOWED, EXCLUDED = 'HK.01234', 'HK.05678'  # Synthetic, not real eligibility.


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('R3B_TEST_NETWORK_FORBIDDEN')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def case(tmp_path, monkeypatch):
    # Real original store in temporary on-disk storage, not an in-memory stand-in.
    state = tmp_path / 'manager_state'
    svc = SimpleNamespace(
        store=ManagerResearchStore(state),
        _catalyst_data_root=tmp_path / 'no_real_data',
        _workspace_ledger_root=None,
        _close_observation_reader=None,
        observation_reader=lambda day: dict(
            status='READY', target_trade_date=day,
            rows=[dict(symbol=ALLOWED, name='SYNTHETIC Allowed', market='HK_CONNECT'),
                  dict(symbol=EXCLUDED, name='SYNTHETIC Excluded', market='HK_CONNECT'),
                  dict(symbol='SH.600000', name='SYNTHETIC A', market='A')], **FLAGS),
        get_catalyst_observations=lambda day: dict(
            status='READY_EMPTY', target_trade_date=day, cards=[], **FLAGS),
    )
    # Synthetic leaf owner responses. The actual workspace orchestration, gates,
    # input hashes, diagnostics, writer, transaction, seal and reader run unchanged.
    monkeypatch.setattr(ws, '_materials', lambda *a: dict(materials=[], coverage={}, input_bindings=[], gaps=[]))
    monkeypatch.setattr(ws, '_discovery', lambda *a: dict(cards=[], gaps=[], status='READY_EMPTY', coverage={}))
    monkeypatch.setattr(ws, 'read_material_discovery', lambda *a, **k: dict(
        cards=[], gaps=[], status='READY_EMPTY', coverage={}, rejected_relations=[]))
    monkeypatch.setattr(ws, 'read_plan_quotes', lambda *a, **k: dict(quotes={}, verified=False, gaps=[]))
    monkeypatch.setattr(ws, 'read_rebound_screen', lambda *a: dict(
        status='READY', strict=[], near=[], cards=[], gaps=[], coverage={}))
    monkeypatch.setattr(ws, '_previous_observation', lambda *a: (None, None))
    monkeypatch.setattr(ws, '_stage_attempt', lambda *a: (None, ['STAGE_TARGET_EXECUTION_RECEIPT_NOT_FOUND']))
    monkeypatch.setattr(announcements, 'read', lambda *a: dict(
        status='NOT_RUN', official_documents=[], positive_observations=[], risk_alerts=[],
        clarifications=[], pending_review=[], coverage={}, gaps=[],
        eastmoney_hk_documents=[], eastmoney_hk_capture={}))
    monkeypatch.setattr(announcements, 'read_selection_inputs', lambda *a, **k: dict(
        materials=[], rejections=[], gaps=[], captures=[], status='READY_EMPTY',
        input_identity=digest(['SYNTHETIC_NO_ANNOUNCEMENTS']), **FLAGS))
    monkeypatch.setattr(us_bridge, 'project_us_market', lambda *a: dict(
        status='NOT_RUN', mapping_eligible=False,
        raw_industry_up=[], raw_individual_up=[], gaps=[], **FLAGS))
    # Only the test process clock is frozen, never an authority acquisition time.
    monkeypatch.setattr(ws, '_now', lambda: '2026-09-30T00:00:01.000000+00:00')
    root = tmp_path / 'synthetic_authority'
    root.mkdir()
    owner = tmp_path / 'synthetic_owner'
    owner.mkdir()
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_ROOT', str(root))
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_ROOT', str(owner))
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256', OLD_PIN)
    feed = dict(codes=[ALLOWED], artifact_sha='f' * 64,
                available_at='2026-09-30T00:00:00+00:00', failure=False, calls=[])

    def read_authority(data_root, day, **kwargs):
        assert data_root == root and day == DATE
        assert set(kwargs) <= {'authority_owner_root', 'authority_owner_sha256'}
        feed['calls'].append(deepcopy(kwargs))
        if feed['failure']:
            error = ValueError('HK_CONNECT_EXACT_UNIVERSE_MISSING')
            error.diagnostic = dict(code='HK_CONNECT_EXACT_UNIVERSE_MISSING',
                                    source_code_sha256=kwargs.get('authority_owner_sha256'))
            raise error
        return SimpleNamespace(codes=tuple(feed['codes']), source=dict(
            source_date=DATE, market='HK_CONNECT', role='HK_CONNECT_FULL_MARKET_AUTHORITY',
            sha256=feed['artifact_sha'], observed_at='2026-09-30T07:30:00+08:00',
            available_at=feed['available_at']))
    monkeypatch.setattr(authority, 'read_universe_evidence', read_authority)
    return SimpleNamespace(service=svc, feed=feed, state=state, owner=owner,
                           monkeypatch=monkeypatch, tmp_path=tmp_path)


def snapshot(case):
    return {p.relative_to(case.state).as_posix(): p.read_bytes()
            for p in case.state.rglob('*') if p.is_file()}


def save(case):
    out = ws.refresh_workspace_plan(case.service, DATE, now=SAVE_AT)
    product = ws._read_plan(case.service.store, DATE)
    assert product is not None and product['sha256'] == out['plan_product']['sha256']
    assert product['input_identity'] == product['workspace']['input_identity']
    assert (case.state / 'workspace_plans' / DATE / (product['run_id'] + '.json')).is_file()
    assert (case.state / 'workspace_plan_runs' / DATE / (product['run_id'] + '.json')).is_file()
    return out, product, snapshot(case)


def read(case, at=READ_AT, include_saved=True):
    # New store instance exercises disk readback rather than object reuse.
    case.service.store = ManagerResearchStore(case.state)
    return ws.get_workspace(case.service, DATE, include_saved=include_saved,
                            view='dynamic', now=at)


def binding(out):
    return out['selection_diagnostics']['membership'].get('authority_reader_binding')


def check_safe(out):
    assert all(out[key] is value for key, value in FLAGS.items())
    assert all(out['selection_diagnostics'][key] is value for key, value in FLAGS.items())
    assert_manager_safe_tree(out)
    assert {stock['symbol'] for stock in out['stocks']} <= {ALLOWED}
    assert EXCLUDED not in out['focus_symbols']
    for stock in out['stocks']:
        assert stock['plan']['qualified'] is False
        assert stock['plan']['production_allowed'] is False
    for candidate in out['selection_diagnostics']['candidates']:
        assert candidate['qualified'] is False and candidate['buy_allowed'] is False


def test_changed_pin_real_save_and_readback_updates_diagnostic_without_republishing(case):
    initial, saved, before = save(case)
    assert binding(initial)['source_code_sha256'] == OLD_PIN
    assert [stock['symbol'] for stock in initial['stocks']] == [ALLOWED]
    assert initial['summary']['formal_recommendation_count'] == 0
    case.monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256', NEW_PIN)
    current = read(case, include_saved=False)
    assert current['input_identity'] == saved['input_identity']
    assert current['selection_diagnostics']['membership']['identity'] == saved['workspace']['selection_diagnostics']['membership']['identity']
    got = read(case)
    assert binding(got)['source_code_sha256'] == NEW_PIN
    assert got['selection_diagnostics'] == current['selection_diagnostics']
    assert got['plan_product']['status'] == 'CURRENT' and got['plan_product']['consumed'] is True
    assert got['plan_product']['run_id'] == saved['run_id']
    assert got['plan_product']['sha256'] == saved['sha256']
    assert got['stocks'] == saved['workspace']['stocks']
    assert got['summary']['formal_recommendation_count'] == 0
    assert any(r['symbol'] == EXCLUDED and r['reason'] == 'NOT_IN_TARGET_HK_CONNECT_UNIVERSE'
               for r in got['connect_selection_rejections'])
    assert got['plan_context'] == saved['workspace']['plan_context']
    assert got['runtime_status_read_at'] == READ_AT.isoformat()
    assert snapshot(case) == before
    assert ws._read_plan(case.service.store, DATE)['workspace']['selection_diagnostics']['membership']['authority_reader_binding']['source_code_sha256'] == OLD_PIN
    check_safe(got)
    (case.tmp_path / 'changed_pin_witness.json').write_text(json.dumps(dict(
        evidence_kind='AUTHOR_SYNTHETIC_UPSTREAM_REAL_DISK_WRITER_READBACK',
        old_pin=OLD_PIN, new_pin=NEW_PIN, observed_pin=binding(got)['source_code_sha256'],
        saved_run_id=saved['run_id'], response_run_id=got['plan_product']['run_id'],
        stored_sha=saved['sha256'], response_stored_sha=got['plan_product']['sha256'],
        disk_unchanged=True, input_identity_unchanged=True,
        persisted_bytes_sha={p: sha(raw) for p, raw in before.items()},
        original_store=str(type(case.service.store)), live_api_verified=False,
    ), ensure_ascii=False, indent=2), encoding='utf-8')


def test_unchanged_binding_reuses_same_plan_but_reads_current_witness_clock(case):
    _, saved, before = save(case)
    case.feed['available_at'] = '2026-09-30T00:01:00+00:00'
    got = read(case)
    assert got['plan_product']['status'] == 'CURRENT' and got['plan_product']['consumed']
    assert got['plan_product']['run_id'] == saved['run_id']
    assert got['input_identity'] == saved['input_identity']
    assert binding(got)['source_code_sha256'] == OLD_PIN
    assert got['selection_diagnostics']['membership']['source']['available_at'] == case.feed['available_at']
    assert snapshot(case) == before
    check_safe(got)


def test_changed_owner_root_same_pin_does_not_show_saved_root(case):
    _, saved, before = save(case)
    other = case.tmp_path / 'synthetic_other_owner'
    other.mkdir()
    case.monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_ROOT', str(other))
    got = read(case)
    assert binding(got)['owner_root'] == str(other)
    assert got['plan_product']['consumed'] and got['input_identity'] == saved['input_identity']
    assert snapshot(case) == before


def test_switch_to_release_local_owner_removes_obsolete_explicit_diagnostic(case):
    _, saved, before = save(case)
    case.monkeypatch.delenv('V4_MANAGER_UNIVERSE_OWNER_ROOT')
    case.monkeypatch.delenv('V4_MANAGER_UNIVERSE_OWNER_SHA256')
    got = read(case)
    assert 'authority_reader_binding' not in got['selection_diagnostics']['membership']
    assert got['plan_product']['consumed'] and got['input_identity'] == saved['input_identity']
    assert snapshot(case) == before


def test_failed_authority_changed_pin_updates_current_failure_diagnostic(case):
    case.feed['failure'] = True
    _, saved, before = save(case)
    case.monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256', NEW_PIN)
    got = read(case)
    membership = got['selection_diagnostics']['membership']
    assert membership['status'] == 'CANNOT_CONFIRM'
    assert membership['authority_diagnostic']['source_code_sha256'] == NEW_PIN
    assert binding(got)['source_code_sha256'] == NEW_PIN
    assert got['input_identity'] == saved['input_identity'] and got['plan_product']['consumed']
    assert got['stocks'] == [] and got['selection_diagnostics']['candidate_count'] == 0
    assert snapshot(case) == before
    check_safe(got)


def test_diagnostic_overlay_is_a_deepcopy_and_not_a_stored_product_write(case):
    _, saved, before = save(case)
    current = read(case, include_saved=False)
    got = ws._readback_plan(case.service.store, DATE, current)
    got['selection_diagnostics']['membership']['codes'].append(EXCLUDED)
    binding(got)['source_code_sha256'] = '9' * 64
    assert current['selection_diagnostics']['membership']['codes'] == [ALLOWED]
    assert binding(current)['source_code_sha256'] == OLD_PIN
    assert snapshot(case) == before
    assert binding(read(case))['source_code_sha256'] == OLD_PIN
    check_safe(read(case))


def test_membership_change_still_invalidates_reuse_and_cannot_widen_pool(case):
    _, saved, before = save(case)
    # Empty authority is invalid: the original fail-closed behavior must remain.
    case.feed['codes'] = []
    case.feed['artifact_sha'] = 'e' * 64
    case.monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256', NEW_PIN)
    got = read(case)
    assert got['plan_product']['status'] == 'STALE_INPUTS_CHANGED'
    assert got['plan_product']['consumed'] is False
    assert got['stocks'] == [] and got['focus_symbols'] == []
    assert got['selection_diagnostics']['candidate_count'] == 0
    assert binding(got)['source_code_sha256'] == NEW_PIN
    assert snapshot(case) == before
    check_safe(got)


def test_tampered_saved_product_is_not_reused(case):
    _, saved, _ = save(case)
    path = case.state / 'workspace_plans' / DATE / 'latest.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['sha256'] = '0' * 64
    path.write_text(json.dumps(payload), encoding='utf-8')  # Corruption fixture only.
    before = snapshot(case)
    case.monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256', NEW_PIN)
    got = read(case)
    assert got['plan_product']['status'] == 'READBACK_FAILED'
    assert binding(got)['source_code_sha256'] == NEW_PIN
    assert snapshot(case) == before
    check_safe(got)


def test_earlier_cutoff_does_not_consume_later_saved_plan(case):
    _, saved, before = save(case)
    case.monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256', NEW_PIN)
    got = read(case, at=datetime.fromisoformat('2026-09-30T07:50:00+08:00'))
    assert got['plan_product']['status'] == 'PLAN_AFTER_READ_CUTOFF'
    assert got['plan_product']['consumed'] is False
    assert binding(got)['source_code_sha256'] == NEW_PIN
    assert snapshot(case) == before
    check_safe(got)


def test_no_saved_plan_returns_current_diagnostics_without_creating_one(case):
    before = snapshot(case)
    got = read(case)
    assert got['plan_product']['status'] == 'NOT_MATERIALIZED'
    assert got['plan_product']['consumed'] is False
    assert binding(got)['source_code_sha256'] == OLD_PIN
    assert snapshot(case) == before
    check_safe(got)
