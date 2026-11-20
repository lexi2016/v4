import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ROOT / 'docs/handoffs/formula_groups_daily_completion_20261118/overlays'
SYMBOL = '000610.SZ'


def _patched_host(tmp_path):
    binding = json.loads((OVERLAYS / 'API_WORKBENCH_BINDING.json').read_text())
    review_binding = json.loads((OVERLAYS / 'API_WORKBENCH_REVIEW_BINDING.json').read_text())
    source = Path(binding['source_path'])
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == binding['source_sha256']
    candidate = tmp_path / 'candidate'
    target = candidate / 'infrastructure/research_workbench_host.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    subprocess.run(['git','apply','--unidiff-zero',str(OVERLAYS/'api-workbench.patch')],
        cwd=candidate,check=True,capture_output=True,text=True)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == review_binding['required_preimage_after_base_patch_sha256']
    subprocess.run(['git','apply','--unidiff-zero',str(OVERLAYS/'api-workbench-review.patch')],
        cwd=candidate,check=True,capture_output=True,text=True)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == review_binding['result_sha256']
    api_app = source.parent.parent
    if str(api_app) not in sys.path:
        sys.path.insert(0,str(api_app))
    import infrastructure
    if str(source.parent) not in infrastructure.__path__:
        infrastructure.__path__.insert(0,str(source.parent))
    spec=importlib.util.spec_from_file_location('candidate_review_research_workbench_host',target)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def patched_host(tmp_path):
    return _patched_host(tmp_path)


def test_partial_d35c_marks_and_effective_supplement_status_survive_api_chart_read(
        tmp_path, patched_host, monkeypatch):
    product = dict(data_date='20261120',source_generation='a'*64,
        source_identity=dict(input_sha256='b'*64),manifest=dict(path='/products/20261120.json',sha256='c'*64),
        original_charts={})
    chart = dict(symbol=SYMBOL,rows=[dict(trade_date='20261120')])
    host=patched_host.ResearchWorkbenchHost.__new__(patched_host.ResearchWorkbenchHost)
    host._view=lambda *_:product
    host._observation_date=lambda _:'2026-11-23'
    host._formula_groups=lambda *_:(dict(artifact={'sha256':'d'*64}),
        [dict(symbol=SYMBOL,source_row={'symbol':SYMBOL})])
    bundle=dict(items={SYMBOL:dict(status='PARTIAL_WITH_UNKNOWN',unresolved_conditions=1,marks=[],lines={})})
    host._formula_group_binding=lambda *_:dict(d35c_marks=dict(path='/marks.json',sha256='e'*64),
        supplement_status='PARTIAL')
    host._quote_references=SimpleNamespace(read_daily_chart=lambda *_:dict(chart))
    seen={}
    monkeypatch.setattr(patched_host,'checked',lambda ref:bundle)
    def chart_original_marks(bound,*args):
        seen['item_status']=bound['items'][SYMBOL]['status']
        return dict(status='READY',marks=[],lines={'白线':[],'黄线':[]})
    monkeypatch.setitem(sys.modules,'infrastructure.research_workbench_d35c_marks',
        SimpleNamespace(chart_original_marks=chart_original_marks))
    host.chart_views=lambda *_:pytest.fail('partial confirmed marks must not fall back and disappear')

    value=host.formula_daily_chart('2026-11-20',SYMBOL)

    assert seen['item_status']=='READY'
    assert value['original_marks']['status']=='PARTIAL_WITH_UNKNOWN'
    assert set(value['original_marks']['lines'])=={'白线','黄线'}
    assert value['formula_group_supplement_status']=='PARTIAL'
