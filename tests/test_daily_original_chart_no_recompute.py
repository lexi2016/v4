import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from ops import research_panel_daily_product as owner
from infrastructure.research_lane_source import ResearchLaneSource
from test_daily_original_chart_owner import owner_fixture, run_owner


def test_matching_numeric_and_chart_checkpoints_reuse_zero_compute_zero_render(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    first=run_owner(context,evaluate,png)
    calls.update(compute=0,render=0)
    second=run_owner(context,evaluate,lambda items:pytest.fail('matching chart must not render'))
    assert first==second and calls=={'compute':0,'render':0}
    assert ResearchLaneSource(tmp_path,a_share_daily_root=tmp_path).read_original_chart('20261029','600025.SH')['status']=='READY'


def test_legacy_numeric_cache_gap_does_not_silently_recompute(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    run_owner(context,evaluate,png,original_charts=False)
    calls['compute']=0
    run_owner(context,evaluate,lambda items:pytest.fail('no retained result must not render'))
    assert calls['compute']==0
    source=ResearchLaneSource(tmp_path,a_share_daily_root=tmp_path)
    with pytest.raises(ValueError,match='RETAINED_FULL_RESULT_MISSING_LEGACY_NUMERIC_CACHE_NO_RECOMPUTE'):
        source.read_original_chart('20261029','600025.SH')


def test_partial_render_retry_reuses_retained_full_result_without_engine(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    first=run_owner(context,evaluate,lambda items:{'600025.SH':'FIRST_RENDER_FAIL'})
    (context.root/'events/latest.json').unlink()
    calls.update(compute=0,render=0)
    second=run_owner(context,evaluate,png)
    assert first==second and calls=={'compute':0,'render':1}
    assert ResearchLaneSource(tmp_path,a_share_daily_root=tmp_path).read_original_chart('20261029','600025.SH')['status']=='READY'


def test_bad_optional_chart_binding_keeps_numeric_rows_readable(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    run_owner(context,evaluate,png)
    path=context.root/'index.json';index=json.loads(path.read_text())
    index['original_charts']['20261029']['numeric_manifest']={'path':'/wrong','sha256':'0'*64}
    path.write_text(json.dumps(index))
    source=ResearchLaneSource(tmp_path,a_share_daily_root=tmp_path)
    assert source.read_a_daily_product()['unique_count']==1
    with pytest.raises(ValueError,match='OWNER_BINDING_NOT_CONFIGURED'):
        source.read_original_chart('20261029','600025.SH')
