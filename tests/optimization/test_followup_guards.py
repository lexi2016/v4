"""Follow-up failures found by the broad regression and fresh code review."""
from __future__ import annotations
import errno
import importlib
from pathlib import Path
import pytest
from infrastructure import interprocess_lock
from infrastructure.data_store import NativeDataStore

def test_catalog_contract_rejects_nested_trade_state(tmp_path):
    catalog = {
        'schema_version': 'v3_trade_calendar.v1',
        'system_date': '20260908',
        'stage_dates': [],
        'future_target_dates': [],
        'materialized_rows': {},
        'metadata': {'orders_sent': True},
    }
    with pytest.raises(ValueError):
        NativeDataStore(tmp_path).import_catalog(catalog)

def test_unknown_pid_probe_failure_does_not_authorize_reclaim(monkeypatch):

    def unknown(*args):
        raise OSError(errno.EIO, 'unclassified process inspection failure')
    monkeypatch.setattr(interprocess_lock.os, 'kill', unknown)
    assert interprocess_lock._pid_is_alive(12345) is True

def test_boolean_pid_is_not_a_legacy_owner():
    assert interprocess_lock._decode_owner(interprocess_lock._owner_bytes(True, 'token')) is None

def test_projection_modules_are_independent_of_orchestrator():
    from v4.manager_research import service
    package = Path(service.__file__).parent
    assert (package / 'financial_projection.py').is_file()
    assert (package / 'catalyst_projection.py').is_file()
    finance = importlib.import_module('v4.manager_research.financial_projection')
    catalyst = importlib.import_module('v4.manager_research.catalyst_projection')
    assert service._build_research_sections is finance._build_research_sections
    assert service._project_cached_catalysts is catalyst._project_cached_catalysts
    for module in (finance, catalyst):
        text = Path(module.__file__).read_text()
        assert 'from .service import' not in text
