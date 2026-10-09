"""Execute supplied slot helper branches without inventing a live runtime.

Only the input/NOOP seams are injected. The tests assert that original owner
receipt routing preserves old selections and records actual invocation context.
They do not claim real acquisition, algorithm or Mac publication acceptance.
"""
from __future__ import annotations

import builtins
from datetime import datetime, timezone
import importlib.util
import sys
import types

import pytest

from test_owner_receipt_binding import SOURCE, candidate, load_receipts


class RunnerError(ValueError):
    pass


@pytest.fixture(params=["actual_stage", "canonical"])
def slot(request, tmp_path, monkeypatch):
    variant = request.param
    package = types.ModuleType("stage_center")
    package.__path__ = []
    parts = types.ModuleType("stage_center._runner_parts")
    parts.__path__ = []
    namespace = types.ModuleType("stage_center._runner_parts._namespace")
    namespace.read_global = lambda scope, name: scope.get(name, getattr(builtins, name, None))
    monkeypatch.setitem(sys.modules, "stage_center", package)
    monkeypatch.setitem(sys.modules, "stage_center._runner_parts", parts)
    monkeypatch.setitem(sys.modules, "stage_center._runner_parts._namespace", namespace)
    receipts = load_receipts(variant)
    monkeypatch.setitem(sys.modules, "stage_center._runner_parts.runner_receipts", receipts)
    spec = importlib.util.spec_from_file_location("stage_center._runner_parts.slot_execution", SOURCE / variant / "stage_center/_runner_parts/slot_execution.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    writes = []
    validated_candidate = candidate()
    selected = {"A_SHARE": {"market": "A_SHARE", "run_id": "old-original-run", "selected_rows": 10, "requested_rows": 216, "observed_rows": 206}}
    config = types.SimpleNamespace(candidate_acquisition_root=tmp_path / "candidate", hk_d1_root=None, injected_test_mode=True, preselection_source_root=None)
    runner = types.SimpleNamespace(
        config=config,
        _validate_hk_auction_root_binding=lambda stage: None,
        _existing_slot=lambda *args: ("VERIFIED", {"raw": {"receipt": {"bundle_id": "original-bundle"}}, "selections": selected}),
        _write_receipt=lambda payload, date, stage: writes.append((payload, date, stage)) or payload,
    )
    scope = {
        "_stage_markets_for_date": lambda *args: ("A_SHARE",),
        "_resolve_stage_market_scope": lambda *args, **kwargs: ("A_SHARE",),
        "read_candidate_input": lambda *args, **kwargs: validated_candidate,
        "CandidateInputError": RunnerError,
        "RunnerError": RunnerError,
        "RawStoreError": RunnerError,
        "SelectionError": RunnerError,
        "StageUniverseBinding": types.SimpleNamespace(ready=lambda **kwargs: types.SimpleNamespace(**kwargs)),
    }
    decision = types.SimpleNamespace(trade_date="20261009", stage_id="STAGE_0940_0945", status="DUE")

    def run():
        kwargs = {"historical_backfill": False, "backfill_run_id": None}
        if variant == "canonical":
            kwargs["historical_markets"] = None
        return module._StageCenterRunner__run_one_body(scope, runner, decision, **kwargs)

    return runner, scope, decision, writes, selected, run


def test_existing_selection_is_reused_and_new_time_only_describes_current_invocation(slot):
    _, _, _, writes, selected, run = slot
    before = datetime.now(timezone.utc)
    result = run()
    assert result["status"] == "NOOP_ALREADY_VERIFIED"
    assert result["markets"] == selected
    assert result["write_performed"] is False
    assert result["runner_clock_source"] == "OWNER_RUNNER_INVOCATION_UTC"
    assert before <= datetime.fromisoformat(result["runner_invoked_at"]) <= datetime.now(timezone.utc)
    assert result["input_bindings"]["A_SHARE"]["row_count"] == 216
    assert result["input_bindings"]["A_SHARE"]["binding_scope"] == "INPUT_VALIDATED_FOR_THIS_INVOCATION"
    assert result.get("natural_verified") is not True
    assert len(writes) == 1


def test_missing_real_candidate_keeps_original_failure_and_never_emits_a_trio(slot):
    _, scope, _, writes, _, run = slot

    def missing(*args, **kwargs):
        raise RunnerError("candidate current absent")

    scope["read_candidate_input"] = missing
    result = run()
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["first_failed_layer"] == "EXACT_SELECTION_INPUT_BINDING"
    assert result["markets"]["A_SHARE"]["cannot_confirm"] == ["candidate current absent"]
    assert result["input_bindings"] == {}
    assert result["write_performed"] is False
    assert len(writes) == 1


def test_two_slot_invocations_do_not_reuse_cached_input_context(slot):
    _, scope, _, writes, _, run = slot
    first = run()
    scope["read_candidate_input"] = lambda *args, **kwargs: candidate(run_id="new-candidate", current_sha256="e" * 64)
    second = run()
    assert first["input_bindings"]["A_SHARE"]["run_id"] == "candidate-real"
    assert second["input_bindings"]["A_SHARE"]["run_id"] == "new-candidate"
    assert first["input_bindings"]["A_SHARE"]["current_bytes_sha256"] == "0" * 64
    assert second["input_bindings"]["A_SHARE"]["current_bytes_sha256"] == "e" * 64
    assert len(writes) == 2
