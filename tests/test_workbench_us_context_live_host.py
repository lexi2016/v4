import ast
from hashlib import sha256
from pathlib import Path
import subprocess

import pytest

from ops import prepare_workbench_us_context_live_host as patch


BASELINE = '881bbb4392e36b7ddac5b893580b099074dbfc8a'
HOST_PATH = 'infrastructure/research_workbench_host.py'
OUTPUT_SHA256 = '9b427605cdbf0ef9a00f1309ebaad8273afebba577138207c16a262faedb9380'


def active_baseline():
    repo = Path(__file__).resolve().parents[1]
    return subprocess.check_output(['git', 'show', f'{BASELINE}:{HOST_PATH}'], cwd=repo)


def inspect(raw):
    module = ast.parse(raw)
    host, = (item for item in module.body if isinstance(item, ast.ClassDef) and item.name == 'ResearchWorkbenchHost')
    methods = {item.name: item for item in host.body if isinstance(item, ast.FunctionDef)}
    other = [item for item in host.body if not isinstance(item, ast.FunctionDef)]
    return [item for item in module.body if item is not host] + other, methods


def test_exact_active_host_changes_only_us_integration():
    active = active_baseline()
    result = patch.transplant(active, patch.REVIEWED_HOST.read_bytes())
    assert sha256(active).hexdigest() == patch.ACTIVE_HOST_SHA256
    assert sha256(result).hexdigest() == OUTPUT_SHA256
    assert patch.transplant(active, patch.REVIEWED_HOST.read_bytes()) == result

    originals, original_methods = inspect(active)
    definitions, methods = inspect(result)
    imports = [item for item in definitions
               if isinstance(item, ast.ImportFrom) and item.module == 'infrastructure.research_workbench_us_context']
    assert len(imports) == 1
    assert [alias.name for alias in imports[0].names] == ['standalone_benchmarks', 'us_context_dates']
    assert list(map(ast.dump, originals)) == [ast.dump(item) for item in definitions if item not in imports]
    assert set(methods) - set(original_methods) == {'_standalone_us_context'}
    assert {name for name in original_methods if ast.dump(original_methods[name]) != ast.dump(methods[name])} == {'source_context'}
    source = result.decode().splitlines()
    for method in ('workflow', 'versions'):
        node = methods[method]
        original = active.decode().splitlines()
        before = original_methods[method]
        assert source[node.lineno - 1:node.end_lineno] == original[before.lineno - 1:before.end_lineno]


def test_transplant_rejects_unknown_donor_or_target():
    reviewed = patch.REVIEWED_HOST.read_bytes()
    with pytest.raises(ValueError, match='LIVE_HOST_BASE_SHA_MISMATCH'):
        patch.transplant(b'wrong-base', reviewed)
    with pytest.raises(ValueError, match='LIVE_HOST_REVIEWED_SHA_MISMATCH'):
        patch.transplant(active_baseline(), b'wrong-donor')
