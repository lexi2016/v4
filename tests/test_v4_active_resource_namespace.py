"""The active namespace keeps its pinned package resources and historical contracts."""
import hashlib
import importlib
from pathlib import Path


def test_lifecycle_resource_loads_from_actual_active_module():
    history = importlib.import_module('apps.api.v4_api.a_share_panel_history')
    asset = Path(history.__file__).with_name('a_share_lifecycle_notes.json')
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == history.LIFECYCLE_NOTES_SHA256
    result = history._with_post_termination_rows({
        'ts_code': '832317.BJ', 'status': 'READY',
        'rows': [{'trade_date': '20220426', 'close': 1}], 'cannot_confirm': [],
    })
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['status_verification']['reason_code'] == 'POST_TERMINATION_SOURCE_ROWS_QUARANTINED'
    assert result['status_verification']['evidence_bound'] is True
    assert result['quarantined_original_rows'] == [{'trade_date': '20220426', 'close': 1}]


def test_runtime_graph_v4_modules_retain_historical_contracts():
    native = importlib.import_module('infrastructure.runtime_graph.v4_native_evidence')
    validators = importlib.import_module('infrastructure.runtime_graph.v4_validators')
    importlib.import_module('infrastructure.runtime_graph.collectors')
    importlib.import_module('infrastructure.runtime_graph.validators')
    assert 'v35_artifact' in native.V4_ARTIFACT_SOURCE_KINDS
    assert callable(validators.validate_v4_semantics)


def test_windows_launcher_text_contract_only():
    root = Path(__file__).resolve().parents[1]
    launcher = (root/'ops/launch_v4_dispatcher.ps1').read_text()
    assert '$env:V4_PYTHON_EXE' in launcher
    assert 'V35_' not in launcher
    assert "'-m', 'ops.run_dispatcher'" in launcher
