"""Independent handler-to-dispatcher checks across explicit missing-runtime boundaries."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from scheduler_slice_harness import (
    LedgerBoundary, ProcessBoundary, catalog, load_dispatcher, load_preselection, request,
)


@pytest.mark.parametrize('owner', ['actual_pool_scheduler', 'canonical_reference'])
@pytest.mark.parametrize('prerequisite,first_gate', [
    ('scripts.update_hk_0_2_panel', 'HK_PRICE_PANEL'),
    ('ops.ensure_hk_security_master', 'HK_SECURITY_MASTER'),
])
def test_hk_prerequisite_failure_reaches_receipt_while_a_materializes(
    monkeypatch, tmp_path, owner, prerequisite, first_gate,
):
    _, handler = load_preselection(monkeypatch, owner)
    dispatcher = load_dispatcher(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path, failing_module=prerequisite)
    ledger = LedgerBoundary(tmp_path)
    receipt = dispatcher.dispatch_due(
        request(), catalog(), lambda work, req, decision: handler(boundary, req),
        ledger=ledger,
    ).to_dict()
    assert boundary.local_materialized.exists()
    assert not boundary.scored.exists()
    assert receipt['status'] == 'FAILED'
    assert receipt['failure_class'] == 'UPSTREAM_NOT_READY'
    assert receipt['retry_after']
    assert receipt['invoked_workload_ids'] == ['preselection_pools']
    assert receipt['started_workload_ids'] == receipt['succeeded_workload_ids'] == []
    assert receipt['workload_results'][0]['first_gate'] == first_gate
    assert receipt['workload_results'][0]['materializer_status'] == 'SUCCEEDED'
    assert ledger.released == [('new-attempt', ('preselection_pools',))]
    assert ledger.receipts[0] == {'slot': '0925', 'status': 'SUCCEEDED', 'run_id': 'old-terminal'}
    assert all(receipt[flag] is False for flag in ['production_allowed', 'buy_gate_updated', 'orders_sent'])
