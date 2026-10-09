import pytest

from scheduler_slice_harness import ProcessBoundary, load_preselection, request


OWNERS = ("actual_pool_scheduler", "canonical_reference")


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("prerequisite", ("scripts.update_hk_0_2_panel", "ops.ensure_hk_security_master"))
def test_failed_hk_prerequisite_prevents_scoring_but_preserves_a_materialization(monkeypatch, tmp_path, owner, prerequisite):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path, failing_module=prerequisite)
    result = handler(boundary, request())

    assert not boundary.scored.exists(), "HK scoring must wait for both verified prerequisites"
    assert boundary.local_materialized.exists(), "the independent A/local materializer must continue"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert result["a_selector_status"] in {"READY", "SUCCEEDED"}


@pytest.mark.parametrize("owner", OWNERS)
def test_missing_exact_master_is_retryable_and_cannot_settle_as_success(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path, failing_module="ops.ensure_hk_security_master")
    result = handler(boundary, request())

    assert result["status"] == "FAILED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["first_gate"] == "HK_SECURITY_MASTER"
    assert result["materializer_status"] == "SUCCEEDED"
    assert "20261008" in result["stderr"]
    assert any("EXACT_INPUT_MISSING" in lane.get("stderr", "") for lane in result["hk_lane_degradations"])


@pytest.mark.parametrize("owner", OWNERS)
def test_successful_preparation_keeps_dates_and_original_owner_order(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path)
    result = handler(boundary, request())

    assert result["status"] == "SUCCEEDED"
    modules = [module for module, _ in boundary.calls]
    assert modules.index("scripts.update_hk_0_2_panel") < modules.index("ops.ensure_hk_security_master") < modules.index("scripts.materialize_hk_0_2")
    scoring_arguments = dict(zip(boundary.calls[modules.index("scripts.materialize_hk_0_2")][1][::2], boundary.calls[modules.index("scripts.materialize_hk_0_2")][1][1::2]))
    assert scoring_arguments["--signal-date"] == "20261008"
    assert scoring_arguments["--target-date"] == "20261009"
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))


@pytest.mark.parametrize("owner", OWNERS)
def test_optional_a_review_gap_does_not_fail_preselection(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path, optional_failure=True)
    result = handler(boundary, request())

    assert result["status"] == "SUCCEEDED"
    assert result["optional_d1_review_lane"]["status"] == "CANNOT_CONFIRM"
    assert boundary.scored.exists()


@pytest.mark.parametrize("owner", OWNERS)
def test_executor_requires_paired_exact_date_preparation_contract(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path)
    handler(boundary, request())
    arguments = next(args for module, args in boundary.calls if module == "ops.ensure_hk_security_master")
    assert "--prepare-exact-date" in arguments
    assert "--reuse-only" not in arguments


@pytest.mark.parametrize("owner", OWNERS)
def test_blank_child_failure_class_does_not_erase_retryable_hk_gate(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path, failing_module="ops.ensure_hk_security_master")
    run = boundary._run

    def child_with_blank_class(module, arguments, **kwargs):
        result = run(module, arguments, **kwargs)
        result["failure_class"] = ""
        return result

    boundary._run = child_with_blank_class
    result = handler(boundary, request())
    assert result["failure_class"] == "UPSTREAM_NOT_READY"


@pytest.mark.parametrize("owner", OWNERS)
def test_terminal_hk_child_failure_is_not_reclassified_as_retryable(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path, failing_module="ops.ensure_hk_security_master")
    run = boundary._run

    def unsafe_child(module, arguments, **kwargs):
        result = run(module, arguments, **kwargs)
        if module == "ops.ensure_hk_security_master":
            result["failure_class"] = "SAFETY"
        return result

    boundary._run = unsafe_child
    result = handler(boundary, request())
    assert result["status"] == "FAILED"
    assert result["failure_class"] == "SAFETY"
