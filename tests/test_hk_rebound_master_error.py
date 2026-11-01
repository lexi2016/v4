"""An exact-date master gap must stay a typed unknown across owner imports."""
from pathlib import Path

import pytest

from v4.manager_research import workspace_plan
from upstreams.v3_shared_data.shared_data.hk_security_master import HKSecurityMasterReadError
from v3_shared_data.shared_data.store import StoreError as LegacyStoreError


@pytest.mark.parametrize('exception', [
    HKSecurityMasterReadError('HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING', {'status':'MISSING'}),
    LegacyStoreError('legacy owner master unavailable'),
])
def test_rebound_missing_master_is_unknown(monkeypatch, exception):
    monkeypatch.setattr(workspace_plan, 'rebound_history_sessions', lambda date: {'panel_session':'20261030'})
    monkeypatch.setattr(workspace_plan, '_read_hk02_panel_witness', lambda root, day: ({'owner':'panel'}, []))
    def missing(*args):
        raise exception
    monkeypatch.setattr(workspace_plan, '_screen_security_master_witness', missing)
    result=workspace_plan.read_rebound_history(Path('/tmp'), '20261102', ['HK.00001'])
    assert result['status']=='CANNOT_CONFIRM'
    assert result['gaps']==['REBOUND_EXACT_SECURITY_MASTER_UNVERIFIED']
    assert result['symbols']=={} and result['source_files']==[]
    assert result['sessions']=={'panel_session':'20261030'}
