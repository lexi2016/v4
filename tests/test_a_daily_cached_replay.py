from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from ops import research_panel_daily_source as source
from test_a_share_daily_zip_source import input_ref,TARGET


def test_past_session_reuses_bound_cache_without_backdating_or_fetch(tmp_path):
    expected=input_ref(tmp_path/'a_sync_authority/official_daily'/str(TARGET))
    result=source.acquire_daily_input(TARGET,tmp_path,
        fetch=lambda:pytest.fail('past-cache replay must never fetch'),
        now=datetime(2026,10,30,8,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert result==expected


def test_future_cache_is_not_accepted_before_its_session(tmp_path):
    input_ref(tmp_path/'a_sync_authority/official_daily/20261030',target=20261030,previous='20261029')
    with pytest.raises(source.QfqGateError,match='WAIT_WINDOW'):
        source.acquire_daily_input(20261030,tmp_path,fetch=lambda:pytest.fail('future fetch'),
            now=datetime(2026,10,29,17,tzinfo=ZoneInfo('Asia/Shanghai')))
