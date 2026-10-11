"""Real owner/store/import/API with original synthetic source fixture inputs.

This is application integration, not live market, Mac deployment or natural-run
evidence. No application admission/receipt gate is replaced.
"""
from copy import deepcopy
from datetime import datetime, timezone
import types

import pytest

import three_lane_announcement_original_fixture as original
from test_manager_research_selection_ledger import _fixture as screen_fixture
from v4.manager_research import workspace as work
from v4.manager_research.workspace_daily_channels import build_daily_channels
from v4.manager_research.workspace_projection import FLAGS

EARLY = datetime(2026, 10, 8, 1, tzinfo=timezone.utc)
LATE = datetime(2026, 10, 11, 4, tzinfo=timezone.utc)


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setattr(original, 'NOW', EARLY)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return original.NOW.astimezone(tz) if tz else original.NOW.replace(tzinfo=None)
    monkeypatch.setattr(original.api, 'datetime', Clock)
    monkeypatch.setattr(original.consumer, '_now', lambda: original.NOW.isoformat())
    monkeypatch.setattr(work, '_now', lambda: original.NOW.isoformat())
    service = original._FixtureService(tmp_path/'original-owner-state')
    yield service
    service.close()


def lane(value, name):
    return next(row for row in value['daily_channels']['channels'] if row['channel']==name)


def test_full_registered_applicant_selection_cannot_project_to_valid_zero(owner, monkeypatch):
    # The immutable original fixture lacks an issuer argument. Change only its
    # two source-input constants BEFORE all evidence/hashes are constructed.
    generator = original._write_complete_evidence
    constants = generator.__code__.co_consts
    assert constants.count('HK.01234') == constants.count('01234') == 1
    code = generator.__code__.replace(co_consts=tuple(
        'H5354' if item in ('HK.01234','01234') else item for item in constants))
    assert code.co_code == generator.__code__.co_code
    replacement = types.FunctionType(code, generator.__globals__, generator.__name__,
        generator.__defaults__, generator.__closure__)
    replacement.__kwdefaults__ = generator.__kwdefaults__
    monkeypatch.setattr(original, '_write_complete_evidence', replacement)
    product, registered = original._fixture(owner)
    with original._client(owner) as client:
        imported = original._import(client, registered)
        assert imported['consumption_validation']['validation_status']=='VERIFIED'
        before = original._snapshot(owner.store.root)
        value = client.get('/api/v4/manager/research/workspace', params=dict(
            date=original.TARGET, view='dynamic', announcement_date='20261007')).json()
    consumed = value['announcement_reviewed_analysis']['products'][0]
    assert consumed['status']=='CONSUMED' and consumed['selected_stock_count']==1
    assert consumed['product_sha256']==product['sha256']
    result = lane(value, 'ANNOUNCEMENT')
    assert result['status']=='PARTIAL' and result['candidate_count'] is None
    assert result['unmapped_references'][0]['stock_code']=='H5354'
    assert result['unmapped_references'][0]['owner_import_receipt_sha256']==imported['consumption_validation']['owner_import_receipt_sha256']
    assert original._snapshot(owner.store.root)==before


def test_past_dynamic_uses_current_cutoff_but_history_and_saved_bytes_stay_fixed(owner, monkeypatch):
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    assert saved['plan_product']['consumed'] is True
    monkeypatch.setattr(original, 'NOW', LATE)
    product, registered = original._fixture(owner)
    with original._client(owner) as client:
        imported = original._import(client, registered)
        before = original._snapshot(owner.store.root)
        value = client.get('/api/v4/manager/research/workspace', params=dict(
            date=original.TARGET, view='dynamic')).json()
        historical = client.get('/api/v4/manager/research/workspace', params=dict(
            date=original.TARGET, view='historical')).json()
    assert value['read_context']['as_of']=='2026-10-11T12:00:00+08:00'
    assert value['read_context']['read_basis']=='RETROSPECTIVE_CURRENT_TIME'
    assert lane(value, 'ANNOUNCEMENT')['candidate_count']==1
    consumed = next(row for row in value['announcement_reviewed_analysis']['products']
        if row['product_sha256']==product['sha256'])
    assert consumed['status']=='CONSUMED'
    assert consumed['owner_import_receipt_sha256']==imported['consumption_validation']['owner_import_receipt_sha256']
    assert historical['read_context']['mode']=='HISTORICAL_AS_OF'
    assert historical['read_context']['as_of']==saved['plan_context']['research_cutoff']
    assert datetime.fromisoformat(historical['read_context']['as_of']) <= datetime.fromisoformat('2026-10-08T09:30:00+08:00')
    assert lane(historical, 'ANNOUNCEMENT')['candidate_count'] is None
    assert original._snapshot(owner.store.root)==before


def test_same_day_saved_cutoff_is_stable_for_dynamic_read(owner, monkeypatch):
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    monkeypatch.setattr(original, 'NOW', datetime(2026,10,8,1,10,tzinfo=timezone.utc))
    value = owner.get_workspace(original.TARGET, view='dynamic')
    assert value['plan_context']['research_cutoff']==saved['plan_context']['research_cutoff']
    assert value['plan_product']['status']=='CURRENT'


def test_legacy_internal_default_keeps_saved_cutoff_while_explicit_dynamic_advances(owner, monkeypatch):
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    monkeypatch.setattr(original, 'NOW', LATE)
    legacy = owner.get_workspace(original.TARGET)
    assert legacy['plan_product']['status']=='CURRENT'
    assert legacy['input_identity']==saved['input_identity']
    assert legacy['plan_context']['research_cutoff']==saved['plan_context']['research_cutoff']
    current = owner.get_workspace(original.TARGET, view='dynamic')
    assert current['read_context']['read_basis']=='RETROSPECTIVE_CURRENT_TIME'
    assert current['read_context']['as_of']=='2026-10-11T12:00:00+08:00'


def excluded_screen():
    screen, _ = screen_fixture()
    screen.update(target_trade_date=original.TARGET, verified_session='20261007',
        status='READY', strict=[], near=[], pending=[], cards=[], gaps=[])
    for row in screen['excluded']:
        row.update(target_monday=int(original.TARGET), verified_session=20261007)
    screen['coverage'].update(input_candidate_count=1, history_complete_count=1,
        history_pending_count=0, strict_count=0, near_candidate_count=0, selected_count=0,
        excluded_count=1, screen_unresolved_count=0, row_accounted_count=1)
    return screen


def test_original_plan_save_turns_fully_assessed_empty_replay_into_archived_zero(owner, monkeypatch):
    screen = excluded_screen()
    monkeypatch.setattr(work, 'read_rebound_screen', lambda *args, **kwargs:deepcopy(screen))
    preview = work.get_workspace(owner, original.TARGET, include_saved=False, now=EARLY)
    assert lane(preview,'OVERSOLD')['status']=='PARTIAL'
    assert lane(preview,'OVERSOLD')['candidate_count'] is None
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    result = lane(saved,'OVERSOLD')
    assert result['status']=='READY_EMPTY' and result['candidate_count']==0
    assert result['run_id']==saved['plan_product']['run_id']
    assert result['product_sha256']==saved['plan_product']['sha256']
    assert saved['market_screen']==preview['market_screen']
    assert saved['research_attention']['research_selection']['decision_identity']==preview['research_attention']['research_selection']['decision_identity']
    before = original._snapshot(owner.store.root)
    reread = owner.get_workspace(original.TARGET)
    assert lane(reread,'OVERSOLD')['status']=='READY_EMPTY'
    assert original._snapshot(owner.store.root)==before


def test_later_failed_attempt_does_not_erase_exact_saved_archive_identity(owner, monkeypatch):
    monkeypatch.setattr(work, 'read_rebound_screen', lambda *args, **kwargs:deepcopy(excluded_screen()))
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    # A sealed synthetic later failure journal exercises the original exact
    # attempt lookup independently of latest.json; no result is fabricated.
    failed = work.seal_attempt(dict(schema_version=work.ATTEMPT_SCHEMA,
        target_trade_date=original.TARGET, run_id='f'*32, owner='ManagerResearchJobService.refresh_workspace_plan',
        state='FAILED', execution_kind='MANUAL_REFRESH', started_at=EARLY.isoformat(),
        finished_at=EARLY.isoformat(), failure_reasons=['SYNTHETIC_LATER_ATTEMPT_FAILED'], **FLAGS))
    root = owner.store.root/'workspace_plan_runs'/original.TARGET
    owner.store._write_atomic(root/(failed['run_id']+'.json'), failed)
    owner.store._write_atomic(root/'latest.json', failed)
    before = original._snapshot(owner.store.root)
    value = owner.get_workspace(original.TARGET)
    assert value['workspace_plan_attempt']['run_id']==failed['run_id']
    assert value['workspace_plan_attempt']['state']=='FAILED'
    assert value['plan_product']['status']=='CURRENT'
    result = lane(value,'OVERSOLD')
    assert result['status']=='READY_EMPTY' and result['candidate_count']==0
    assert result['run_id']==saved['plan_product']['run_id']
    assert result['product_sha256']==saved['plan_product']['sha256']
    assert original._snapshot(owner.store.root)==before
