import pytest

from scheduler_slice_harness import (
    LedgerBoundary, WorkloadExecutionError, catalog, load_dispatcher, request,
    success, workload,
)


OWNERS = ("actual_pool_scheduler", "canonical_reference")


@pytest.mark.parametrize("owner", OWNERS)
def test_failed_invocation_is_visible_without_changing_legacy_started_semantics(monkeypatch, tmp_path, owner):
    module = load_dispatcher(monkeypatch, owner)
    ledger = LedgerBoundary(tmp_path)

    def executor(work, req, decision):
        raise WorkloadExecutionError({"status": "FAILED", "failure_class": "UPSTREAM_NOT_READY",
                                      "first_gate": "HK_SECURITY_MASTER", "stderr": "exact date 20261008 missing"})

    receipt = module.dispatch_due(request(), catalog(), executor, ledger=ledger).to_dict()
    assert receipt["status"] == "FAILED"
    assert receipt["started_workload_ids"] == []
    assert receipt["invoked_workload_ids"] == ["preselection_pools"]
    assert receipt["succeeded_workload_ids"] == []
    assert receipt["retry_after"]
    assert receipt["workload_results"][0]["first_gate"] == "HK_SECURITY_MASTER"
    assert ledger.released == [("new-attempt", ("preselection_pools",))]
    assert ledger.receipts[0] == {"slot": "0925", "status": "SUCCEEDED", "run_id": "old-terminal"}


@pytest.mark.parametrize("owner", OWNERS)
def test_successful_and_duplicate_workloads_have_unambiguous_receipts(monkeypatch, tmp_path, owner):
    module = load_dispatcher(monkeypatch, owner)
    ledger = LedgerBoundary(tmp_path, settled=("already_settled",))
    receipt = module.dispatch_due(
        request(), catalog(workload(), workload("already_settled")),
        lambda *args: success(), ledger=ledger,
    ).to_dict()
    assert receipt["status"] == "DUPLICATE_WORKLOAD_SKIPPED"
    assert receipt["invoked_workload_ids"] == ["preselection_pools"]
    assert receipt["succeeded_workload_ids"] == ["preselection_pools"]
    assert receipt["started_workload_ids"] == ["preselection_pools"]
    assert ledger.released == []


@pytest.mark.parametrize("owner", OWNERS)
def test_dry_run_never_reports_executor_invocation(monkeypatch, owner):
    module = load_dispatcher(monkeypatch, owner)

    def unexpected_executor(*args):
        raise AssertionError("dry run called executor")

    receipt = module.dispatch_due(request(), catalog(), unexpected_executor, dry_run=True).to_dict()
    assert receipt["status"] == "DRY_RUN_SELECTED"
    assert receipt["invoked_workload_ids"] == []
    assert receipt["succeeded_workload_ids"] == []
