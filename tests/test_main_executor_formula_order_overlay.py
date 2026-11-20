import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ROOT / 'docs/handoffs/formula_groups_daily_completion_20261118/overlays'


class Top200OwnerError(RuntimeError):
    pass


def _patched_daily_method(tmp_path, monkeypatch):
    binding=json.loads((OVERLAYS/'MAIN_EXECUTOR_TOP200_FIRST_BINDING.json').read_text())
    source=Path(binding['runtime_source_path'])
    source_bytes=source.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest()==binding['preimage_sha256']
    target=tmp_path/'infrastructure/scheduling/executor_registry.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(source_bytes)
    subprocess.run(['git','apply','--unidiff-zero',str(OVERLAYS/'main-executor-top200-first.patch')],
        cwd=tmp_path,check=True,capture_output=True,text=True)
    patched_bytes=target.read_bytes()
    assert hashlib.sha256(patched_bytes).hexdigest()==binding['postimage_sha256']
    tree=ast.parse(patched_bytes.decode())
    function=next(node for node in ast.walk(tree)
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=='_run_a_daily')
    namespace={'os':os,'Path':Path,'WorkloadExecutionError':Top200OwnerError}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(target),'exec'),namespace)
    return namespace['_run_a_daily']


@pytest.fixture
def daily_method(tmp_path,monkeypatch):
    return _patched_daily_method(tmp_path,monkeypatch)


def _run(daily_method, monkeypatch, *, top200_error=None):
    order=[]
    def governed_product(*args):
        order.append('top200')
        if top200_error is not None:
            raise top200_error
        return dict(status='COMPLETE')
    monkeypatch.setitem(sys.modules,'ops.research_panel_top200',
        SimpleNamespace(complete_daily_derivatives=object()))
    monkeypatch.setitem(sys.modules,'ops.research_storage_governance',
        SimpleNamespace(governed_product=governed_product))
    monkeypatch.setitem(sys.modules,'ops.research_panel_formula_groups_daily',
        SimpleNamespace(complete_daily_formula_groups=lambda day:
            order.append('formula') or dict(status='COMPLETE',data_date=day)))
    monkeypatch.setenv('V4_A_SHARE_DAILY_PRODUCT_ROOT','/products')
    monkeypatch.setenv('V4_RESEARCH_PANEL_A_DATA_ROOT','/data')
    monkeypatch.setenv('V4_RESEARCH_PANEL_RECEIPT_ROOT','/receipts')
    monkeypatch.setenv('V4_WORKBENCH_CLASSIFICATION_ROOT','/classifications')
    executor=SimpleNamespace(_run_a_daily_source=lambda request:dict(status='SUCCEEDED'))
    request=SimpleNamespace(mode=SimpleNamespace(value='LIVE'),slot='1540',business_date='20261120')
    return executor,request,order


def test_normal_daily_dispatch_commits_top200_before_formula_f10(daily_method,monkeypatch):
    executor,request,order=_run(daily_method,monkeypatch)

    result=daily_method(executor,request)

    assert order==['top200','formula']
    assert result['daily_derivatives']['status']=='COMPLETE'
    assert result['formula_groups']['status']=='COMPLETE'


def test_top200_exception_still_attempts_formula_and_reraises_original_error(
        daily_method,monkeypatch):
    error=Top200OwnerError('TOP200_OWNER_FAILED')
    executor,request,order=_run(daily_method,monkeypatch,top200_error=error)

    with pytest.raises(Top200OwnerError) as caught:
        daily_method(executor,request)

    assert caught.value is error
    assert order==['top200','formula']
