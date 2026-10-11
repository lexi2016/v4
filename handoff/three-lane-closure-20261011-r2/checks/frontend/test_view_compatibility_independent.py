"""Reviewer-only read ordering and omitted-view probes against real owner/store/API."""
from datetime import datetime, timezone

import pytest
import three_lane_announcement_original_fixture as original
from test_manager_three_lane_owner_readback_r2 import owner, EARLY, LATE


def test_explicit_dynamic_then_legacy_and_none_preserve_saved_cutoff(owner, monkeypatch):
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    monkeypatch.setattr(original, 'NOW', LATE)
    before = original._snapshot(owner.store.root)
    current = owner.get_workspace(original.TARGET, view='dynamic')
    omitted = owner.get_workspace(original.TARGET)
    explicit_none = owner.get_workspace(original.TARGET, view=None)
    assert current['read_context']['read_basis'] == 'RETROSPECTIVE_CURRENT_TIME'
    assert current['read_context']['as_of'] == '2026-10-11T12:00:00+08:00'
    for legacy in (omitted, explicit_none):
        assert legacy['read_context']['read_basis'] == 'SAVED_PLAN_CUTOFF'
        assert legacy['plan_context']['research_cutoff'] == saved['plan_context']['research_cutoff']
        assert legacy['input_identity'] == saved['input_identity']
        assert legacy['plan_product']['status'] == 'CURRENT'
    assert original._snapshot(owner.store.root) == before


def test_http_omitted_view_still_means_auto_historical_for_past_day(owner, monkeypatch):
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    monkeypatch.setattr(original, 'NOW', LATE)
    before = original._snapshot(owner.store.root)
    with original._client(owner) as client:
        response = client.get('/api/v4/manager/research/workspace', params={'date': original.TARGET})
    assert response.status_code == 200
    value = response.json()
    assert value['read_context']['mode'] == 'HISTORICAL_AS_OF'
    assert value['read_context']['as_of'] == saved['plan_context']['research_cutoff']
    assert original._snapshot(owner.store.root) == before


def test_omitted_view_keeps_exact_date_binding_requirement(owner, monkeypatch):
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    monkeypatch.setattr(original, 'NOW', LATE)
    before = original._snapshot(owner.store.root)
    value = owner.get_workspace(original.TARGET, announcement_date='20261006')
    assert value['date_bindings']['announcement_date'] == '20261006'
    assert value['read_context']['read_basis'] == 'CURRENT_OWNER_TIME'
    assert value['plan_context']['research_cutoff'] != saved['plan_context']['research_cutoff']
    assert value['plan_product']['consumed'] is False
    assert original._snapshot(owner.store.root) == before


def test_same_hk_day_explicit_dynamic_keeps_saved_cutoff(owner, monkeypatch):
    saved = owner.refresh_workspace_plan(original.TARGET, now=EARLY)
    monkeypatch.setattr(original, 'NOW', datetime(2026,10,8,15,59,tzinfo=timezone.utc))
    before = original._snapshot(owner.store.root)
    value = owner.get_workspace(original.TARGET, view='dynamic')
    assert value['read_context']['read_basis'] == 'SAVED_PLAN_CUTOFF'
    assert value['plan_context']['research_cutoff'] == saved['plan_context']['research_cutoff']
    assert original._snapshot(owner.store.root) == before
