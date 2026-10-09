"""A successful scorer must not hide an explicit required local-HK rejection."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from scheduler_slice_harness import ProcessBoundary, load_preselection, request


@pytest.mark.parametrize('owner', ['actual_pool_scheduler', 'canonical_reference'])
def test_explicit_local_hk_gate_rejection_cannot_settle_success(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path)
    run = boundary._run

    def rejected_local_hk(module, arguments, **kwargs):
        result = run(module, arguments, **kwargs)
        if module == 'ops.materialize_scheduled_preselection':
            payload = result['_authoritative_payload']
            payload['formal_pool_gate']['required']['hkconnect_d1_top100']['ready'] = False
            result['stdout'] = json.dumps(payload)
        return result

    boundary._run = rejected_local_hk
    result = handler(boundary, request())
    assert boundary.scored.exists(), 'All producer steps succeeded in this probe'
    assert boundary.local_materialized.exists(), 'Independent A/local work must remain available'
    assert result['status'] == 'FAILED', 'Explicit local HK rejection must not settle a required HK workload'
    assert result['hk_lane_status'] == 'CANNOT_CONFIRM'
