from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib.util
import json
import sys

import pytest

CASE=Path(__file__).resolve().parent
SCOPE=json.loads((CASE/'SCOPE.json').read_text())
SOURCE=Path(SCOPE['allowed_business_source'][0])
APP=SOURCE.parents[3]
sys.path.insert(0,str(APP))
REQUIRED={'apps.api.v35_api.runtime_graph_router','infrastructure.runtime_graph.service'}


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def facts(tmp_path):
    rows={}
    for index,name in enumerate([f'apps.api.v35_api.a_lazy_{i:03}' for i in range(100)]+sorted(REQUIRED)):
        file=tmp_path/(str(index)+'.py');file.write_text(name)
        rows[name]=SimpleNamespace(__file__=str(file))
    return rows


def test_saturated_cap_keeps_both_existing_required_modules(tmp_path,monkeypatch):
    rows=facts(tmp_path);old=load(CASE/'baseline_runtime_graph_router.py','r3_identity_before_priority')
    new=load(SOURCE,'r4_identity_priority')
    monkeypatch.setattr(old,'sys',SimpleNamespace(modules=rows));monkeypatch.setattr(new,'sys',SimpleNamespace(modules=rows))
    before=old._selected_imported_modules([tmp_path]);after=new._selected_imported_modules([tmp_path])
    assert not REQUIRED.intersection(r['module'] for r in before)
    assert len(after)==24
    assert {r['module'] for r in after[:2]}==REQUIRED
    for row in after:
        assert row['sha256']==hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()
    result={'candidate_source':str(SOURCE),'loaded_module_fact_count':len(rows),'r3_required_visible':[],
            'r4_required_visible':[r['module'] for r in after[:2]],'cap':24,'returned':len(after)}
    (CASE/'IDENTITY_SATURATION_REPRO.json').write_text(json.dumps(result,indent=2)+'\n')


@pytest.mark.parametrize('missing',[{'infrastructure.runtime_graph.service'},REQUIRED])
def test_absent_modules_are_not_imported_or_fabricated(tmp_path,monkeypatch,missing):
    rows=facts(tmp_path)
    for name in missing:rows.pop(name)
    original=set(rows)
    new=load(SOURCE,'r4_identity_absent_priority');monkeypatch.setattr(new,'sys',SimpleNamespace(modules=rows))
    after=new._selected_imported_modules([tmp_path])
    names={r['module'] for r in after}
    assert not names.intersection(missing)
    assert set(rows)==original and len(after)==24
    assert (REQUIRED-missing)<=names
