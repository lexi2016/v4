"""Portable integration probes; frozen role dependencies are supplied explicitly.

Run with P29_STAGE_APP_ROOT/P29_API_APP_ROOT pointing at the role releases being
integrated. Only the bounded source files come from this checkout. These probes
use synthetic lanes/stores, never a provider, persisted market data or the CLI;
the unchanged engine's upstream independent PASS is reused separately.
"""
from pathlib import Path
import os
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def probe(role, body):
    release = Path(os.environ[f"P29_{role.upper()}_APP_ROOT"]).resolve()
    assert (release / "stage_center/selection.py").is_file()
    bootstrap = f"""
import importlib.util, sys, types
from pathlib import Path
from unittest.mock import patch
root = Path({str(ROOT)!r})
release = Path({str(release)!r})
sys.path.insert(0, str(release))
# Do not execute this checkout's older package init or mix its dependencies.
for name in ('stage_center', 'ops', 'ops._run_stage_center_nodes_parts'):
    package = types.ModuleType(name)
    package.__path__ = [str(release / name.replace('.', '/'))]
    sys.modules[name] = package
def local(name):
    path = root / (name.replace('.', '/') + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    assert Path(module.__file__) == path
    return module
recovery = local('stage_center.snapshot_recovery')
supplement = local('stage_center.snapshot_selection')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(bootstrap) + textwrap.dedent(body)],
        cwd=ROOT, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("original", ["missing", "READY_EMPTY", "rows"])
def test_current_api_keeps_formal_precedence_and_hk_lane(original):
    probe("api", f"""
consumer = local('stage_center.consumer')
from copy import deepcopy
from tempfile import TemporaryDirectory
original = {original!r}
a = {{'market':'A_SHARE','status':'CANNOT_CONFIRM','rows':[],
     'selected_rows':None,'cannot_confirm':['ORIGINAL_INPUT_MISSING']}}
if original != 'missing':
    a.update(status='READY_EMPTY' if original == 'READY_EMPTY' else 'READY',
             selected_rows=0 if original == 'READY_EMPTY' else 10,
             rows=[] if original == 'READY_EMPTY' else [{{'code':'A.000001'}}],
             selection_manifest_receipt_verified=True)
hk = {{'market':'HK_CONNECT','status':'PARTIAL_WITH_ROWS','selected_rows':1,
      'rows':[{{'code':'HK.00001','action_level':'NO_BUY'}}],
      'cannot_confirm':['HK_ORIGINAL_GAP']}}
before_a, before_hk = deepcopy(a), deepcopy(hk)
selected = {{'mode':supplement.MODE,'selected_rows':10,
            'captured_at':'2026-10-29T15:19:00+08:00',
            'rows':[{{'code':'A.000002','news_quality_score':None,
                     'research_quality_score':None,'action_level':'WATCH_ONLY'}}]}}
with TemporaryDirectory() as directory, \
     patch.object(consumer.StageSelectionConsumer, '_market_from_store_or_backfill',
                  side_effect=lambda date,stage,market,**kw: deepcopy(a if market=='A_SHARE' else hk)), \
     patch.object(consumer, 'read_stage_execution', return_value={{'natural_verified':False,'original_receipt':'preserved'}}), \
     patch.object(supplement.SupplementStore, 'read', return_value=selected) as read:
    response = consumer.StageSelectionConsumer(Path(directory)).get('20261029','STAGE_0930_0935')
assert response['markets']['A_SHARE'] == before_a
assert response['markets']['HK_CONNECT'] == before_hk
assert response['execution_evidence']['natural_verified'] is False
assert response['write_performed'] is False
assert response['RESEARCH_ONLY'] is True
assert all(response[key] is False for key in ('production_allowed','buy_gate_updated','orders_sent'))
lane = response['snapshot_reselection']
if original == 'missing':
    assert read.call_count == 1 and lane['status'] == 'SELECTED_WATCH_ONLY'
    assert lane['markets']['A_SHARE']['rows'][0]['research_quality_score'] is None
    assert response['snapshot_recovery']['status'] == 'NOT_AVAILABLE'
else:
    read.assert_not_called()
    assert lane['status'] == 'FORMAL_RESULT_AVAILABLE' and lane['markets'] == {{}}
""")


def test_current_stage_hook_scores_saved_observation_without_provider():
    probe("stage", """
node_entry = local('ops._run_stage_center_nodes_parts.node_entry')
assert node_entry.__exit_code_body({}, 'SNAPSHOT_RESELECTION_READY') == 0
assert node_entry.__exit_code_body({}, 'PARTIAL_SNAPSHOT_RESELECTION') != 0
date, stage = '20261029', 'STAGE_0930_0935'
observation = {'trade_date':date,'stage_id':stage,'captured_at':'2026-10-29T15:19:00+08:00',
               'observation_id':'synthetic-observation','rows':[{'code':'A.000001'}]}
class Observations:
    def __init__(self, root): pass
    def read(self, date, stage): return observation
class Supplements:
    def __init__(self, root): pass
    def read(self, date, stage): raise FileNotFoundError('not yet scored')
    def publish(self, source, context, evaluated):
        assert source is observation
        assert context == {'synthetic':'context'}
        return {'selected_rows':10,'mode':supplement.MODE,'original_stage_formal_selected_rows':0}
with patch.object(supplement, 'ObservationStore', Observations), \
     patch.object(supplement, 'SupplementStore', Supplements), \
     patch.object(supplement, 'selection_available', return_value=False), \
     patch.object(supplement, 'context_for_snapshot', return_value={'synthetic':'context'}), \
     patch.object(recovery, 'recover', side_effect=AssertionError('saved observation must not collect')):
    result = recovery.after_natural_nodes({'selection_root':'unused-synthetic-root'}, date,
        [{'stage_id':stage,'node_id':stage}], stages=(stage,),
        wall=lambda: recovery.clock('2026-10-29T18:00:00+08:00'))
assert result['status'] == 'SNAPSHOT_RESELECTION_READY'
assert result['observation_delivery_status'] == 'EXISTING_OBSERVATIONS_REUSED'
assert result['provider_invocations'] == 0
assert result['snapshot_reselection']['selections'][0]['selected_rows'] == 10
assert result['snapshot_reselection']['natural_execution_verified'] is False
""")
