"""Offline temporary-state regressions for the versioned R6 canary contract."""
from __future__ import annotations

import fcntl
import ast
import importlib.util
import json
from pathlib import Path
import sys

import pytest


TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    "issue35_phase6_r6_canary_under_test", Path(__file__).with_name("issue35_phase6_r6_canary.py")
)
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


TARGET = "20261013"
TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE35_AUTOCONTINUE_MAC_20261011_R1")
ARCHIVED_ID = "d8a35106712a4387accf214c3ee3772d"
CURRENT_ID = "357d984e400541a48c41f65ec0018b62"
FRESH_ID = "11111111111111111111111111111111"
ARCHIVED_INPUT = "1" * 64
CURRENT_INPUT = "2" * 64
FRESH_INPUT = "3" * 64


def _attempt(run_id: str, input_identity: str, state: str = "PARTIAL") -> dict:
    value = {
        "schema_version": "manager_research.workspace_plan_attempt.v1",
        "target_trade_date": TARGET,
        "run_id": run_id,
        "input_identity": input_identity,
        "owner": CANARY.common.OWNER,
        "execution_kind": "MANUAL_REFRESH",
        "started_at": "2026-10-12T09:30:00+08:00",
        "finished_at": "2026-10-12T09:30:01+08:00",
        "last_success_at": "2026-10-12T09:30:01+08:00",
        "state": state,
        "failure_reasons": (["WORKSPACE_PLAN_REFRESH_FAILED:RuntimeError"] if state == "FAILED" else []),
        "summary": {"status": state},
        **CANARY.common.SAFETY,
    }
    if state != "FAILED":
        value["success_scope"] = "EXACT_DATE_RESEARCH_PLAN_NOT_FORMAL_RECOMMENDATION_OR_NATURAL_CAPTURE"
    value["sha256"] = CANARY.common.canonical_sha(value)
    return value


def _product_record(run_id: str, input_identity: str) -> dict:
    value = {
        "schema_version": "manager_research.workspace_plan.v1",
        "target_trade_date": TARGET,
        "run_id": run_id,
        "input_identity": input_identity,
        "owner": CANARY.common.OWNER,
        "execution_kind": "MANUAL_REFRESH",
        "generated_at": "2026-10-12T09:30:01+08:00",
        "plan_rows": [],
        **CANARY.common.SAFETY,
    }
    value["sha256"] = CANARY.common.canonical_sha(value)
    return value


def _raw(value: dict) -> bytes:
    return CANARY._json_bytes(value)


def _write_generation(run_root: Path, product_root: Path, run_id: str,
                      input_identity: str, *, state: str = "PARTIAL") -> tuple[dict, dict, bytes, bytes]:
    attempt = _attempt(run_id, input_identity, state)
    product = _product_record(run_id, input_identity)
    run_raw = _raw(attempt)
    product_raw = _raw(product)
    (run_root / f"{run_id}.json").write_bytes(run_raw)
    (product_root / f"{run_id}.json").write_bytes(product_raw)
    return attempt, product, run_raw, product_raw


@pytest.fixture
def two_generation_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path.resolve()
    monkeypatch.setattr(CANARY, "_R6_CURRENT13_ACCEPTANCE", {
        **CANARY._R6_CURRENT13_ACCEPTANCE, "state_root": str(root),
    })
    run_root = root / "workspace_plan_runs" / TARGET
    product_root = root / "workspace_plans" / TARGET
    run_root.mkdir(parents=True)
    product_root.mkdir(parents=True)
    lock_root = root / ".locks"
    lock_root.mkdir()
    (lock_root / f"{TARGET}-workspace-plan-refresh.mutex").write_bytes(b"")

    archived_attempt, archived_product, archived_run_raw, archived_product_raw = _write_generation(
        run_root, product_root, ARCHIVED_ID, ARCHIVED_INPUT
    )
    current_attempt, current_product, current_run_raw, current_product_raw = _write_generation(
        run_root, product_root, CURRENT_ID, CURRENT_INPUT
    )
    (run_root / "latest.json").write_bytes(current_run_raw)
    (product_root / "latest.json").write_bytes(current_product_raw)

    def file_pin(path: Path) -> dict:
        raw = path.read_bytes()
        return {"bytes": len(raw), "sha256": CANARY.common.sha256_bytes(raw)}

    receipt_pins = {
        "archived": {
            "run_id": ARCHIVED_ID, "product_sha256": archived_product["sha256"],
            "input_identity": ARCHIVED_INPUT, "state": "PARTIAL",
            "run_bytes": len(archived_run_raw), "run_sha256": CANARY.common.sha256_bytes(archived_run_raw),
            "product_bytes": len(archived_product_raw),
            "product_sha256_file": CANARY.common.sha256_bytes(archived_product_raw),
        },
        "current": {
            "run_id": CURRENT_ID, "product_sha256": current_product["sha256"],
            "input_identity": CURRENT_INPUT, "state": "PARTIAL",
            "run_bytes": len(current_run_raw), "run_sha256": CANARY.common.sha256_bytes(current_run_raw),
            "product_bytes": len(current_product_raw),
            "product_sha256_file": CANARY.common.sha256_bytes(current_product_raw),
        },
        "protected_dates_sha256": CANARY.common.protected_state_hashes(root),
    }
    snapshot = CANARY._capture_r6_state_preimage(root, TARGET, receipt_pins)
    return {
        "root": root, "run_root": run_root, "product_root": product_root,
        "receipt_pins": receipt_pins, "snapshot": snapshot,
        "archived_attempt": archived_attempt, "current_attempt": current_attempt,
        "current_product": current_product,
    }


def _owner_pair(*, outcome: str = "FRESH") -> tuple[dict, dict, dict]:
    run_id = CURRENT_ID if outcome == "REUSE" else FRESH_ID
    input_identity = CURRENT_INPUT if outcome == "REUSE" else FRESH_INPUT
    attempt = _attempt(run_id, input_identity)
    product_sha = _product_record(run_id, input_identity)["sha256"]

    def product(status: str) -> dict:
        return {
            "status": status, "consumed": True, "run_id": run_id,
            "sha256": product_sha, "original_owner": CANARY.common.OWNER,
            "execution_kind": "MANUAL_REFRESH",
            "input_identity_diagnostics": {
                "status": "MATCH", "current_input_identity": input_identity,
                "saved_input_identity": input_identity,
            },
            "run_readback": {
                "status": "VERIFIED", "target_trade_date": TARGET, "run_id": run_id,
                "artifact_sha256": product_sha, "input_identity": input_identity,
                "owner": CANARY.common.OWNER, "owner_attempt_run_id": run_id,
                "owner_attempt_sha256": attempt["sha256"], "owner_attempt_state": attempt["state"],
                "owner_finished_at": attempt["finished_at"],
            },
        }

    refresh_product = product("CURRENT" if outcome == "FRESH" else "ALREADY_MATERIALIZED")
    readback_product = product("CURRENT")
    persisted = None if outcome == "REUSE" else {
        "target_trade_date": TARGET, "run_id": run_id, "product_sha256": product_sha,
        "execution_kind": "MANUAL_REFRESH", "owner": CANARY.common.OWNER,
        **CANARY.common.SAFETY,
    }
    refresh = {
        "target_trade_date": TARGET, "formal_recommendation_count": 0,
        "store_latest_matches_http_plan_product": True, "plan_product": refresh_product,
        "input_identity": input_identity, "execution_kind": "MANUAL_REFRESH",
        "safety": dict(CANARY.common.SAFETY), "persisted_store": persisted,
        "workspace_plan_attempt": attempt, "workspace_plan_product_attempt": attempt,
    }
    readback = {
        "target_trade_date": TARGET, "plan_product": readback_product,
        "input_identity": input_identity, "execution_kind": "MANUAL_REFRESH",
        "safety": dict(CANARY.common.SAFETY),
        "workspace_plan_attempt": attempt, "workspace_plan_product_attempt": attempt,
    }
    return refresh, readback, attempt


def test_receipt_pins_bind_distinct_d8_archive_and_357_current():
    pins = CANARY._r6_receipt_pins()
    assert pins["archived"]["run_id"] == ARCHIVED_ID
    assert pins["current"]["run_id"] == CURRENT_ID
    assert pins["archived"]["run_id"] != pins["current"]["run_id"]
    assert pins["archived"]["product_sha256"] == "7ba36ad92af7cccaadbcdacca3a2eddc9488a80e28ddd9185ebba2e5afffc49c"
    assert pins["current"]["product_sha256"] == "ae8b8cfc4f1e44003aa75d803ca29fa6e1e088766ae98b5c0471884f699f22c3"


@pytest.mark.parametrize("field,bad_value", [
    ("release_root", "/tmp/not-the-r6-release"),
    ("app_root", "/tmp/not-the-r6-app"),
    ("manifest_sha256", "0" * 64),
    ("application_inventory_sha256", "1" * 64),
    ("release_id", "issue35-manager-autocontinue-20261012-r4b"),
])
def test_r6_preflight_rejects_wrong_release_path_or_identity(monkeypatch, field, bad_value):
    pins = CANARY._R6_CURRENT13_ACCEPTANCE
    release = {
        "release_root": Path(pins["release_root"]),
        "app_root": Path(pins["app_root"]),
        "manifest_sha256": pins["release_manifest_sha256"],
        "application_inventory_sha256": pins["application_inventory_sha256"],
        "manifest": {"candidate": {"release_id": pins["release_id"]}},
    }
    if field == "release_id":
        release["manifest"]["candidate"]["release_id"] = bad_value
    else:
        release[field] = Path(bad_value) if field in {"release_root", "app_root"} else bad_value
    monkeypatch.setattr(CANARY.common, "require_next_session", lambda *args: pytest.fail("calendar must not be read"))
    identity = {"release": release, "state_root": Path(pins["state_root"])}

    with pytest.raises(ValueError, match="R6_CURRENT13_REQUIRES_VERIFIED_R6_RELEASE"):
        CANARY._current13_existing_preimage(identity, TARGET, None)


def test_r6_preflight_rejects_wrong_target_or_state_root(monkeypatch, tmp_path):
    pins = CANARY._R6_CURRENT13_ACCEPTANCE
    release = {
        "release_root": Path(pins["release_root"]),
        "app_root": Path(pins["app_root"]),
        "manifest_sha256": pins["release_manifest_sha256"],
        "application_inventory_sha256": pins["application_inventory_sha256"],
        "manifest": {"candidate": {"release_id": pins["release_id"]}},
    }
    monkeypatch.setattr(CANARY.common, "require_next_session", lambda *args: None)
    with pytest.raises(ValueError, match="R6_CURRENT13_TARGET_NOT_PINNED"):
        CANARY._current13_existing_preimage({"release": release, "state_root": Path(pins["state_root"])},
                                             "20261012", None)
    with pytest.raises(ValueError, match="R6_MANAGER_STATE_ROOT_MISMATCH"):
        CANARY._current13_existing_preimage({"release": release, "state_root": tmp_path}, TARGET, None)


def test_r6_preimage_accepts_only_both_exact_generations_and_latest_357(two_generation_state):
    state = two_generation_state
    snapshot = state["snapshot"]
    assert snapshot["archived"]["run_id"] == ARCHIVED_ID
    assert snapshot["current"]["run_id"] == CURRENT_ID
    assert snapshot["state_files"]["current_run_latest"]["sha256"] == state["receipt_pins"]["current"]["run_sha256"]
    assert snapshot["state_files"]["current_product_latest"]["sha256"] == state["receipt_pins"]["current"]["product_sha256_file"]
    CANARY._assert_current13_preimage_unchanged(state["root"], snapshot)


@pytest.mark.parametrize("changed", ["d8_run", "d8_product", "357_run", "357_product", "run_latest", "product_latest"])
def test_r6_preimage_rejects_any_generation_or_latest_mismatch(two_generation_state, changed):
    state = two_generation_state
    paths = {
        "d8_run": state["run_root"] / f"{ARCHIVED_ID}.json",
        "d8_product": state["product_root"] / f"{ARCHIVED_ID}.json",
        "357_run": state["run_root"] / f"{CURRENT_ID}.json",
        "357_product": state["product_root"] / f"{CURRENT_ID}.json",
        "run_latest": state["run_root"] / "latest.json",
        "product_latest": state["product_root"] / "latest.json",
    }
    paths[changed].write_bytes(b"changed")
    with pytest.raises(ValueError):
        CANARY._capture_r6_state_preimage(state["root"], TARGET, state["receipt_pins"])


def test_r6_preimage_rejects_unexpected_third_generation(two_generation_state):
    state = two_generation_state
    (state["run_root"] / ("4" * 32 + ".json")).write_bytes(b"third generation")
    with pytest.raises(ValueError, match="R6_TWO_GENERATION_RUN_PREIMAGE_WRITE_SET_MISMATCH"):
        CANARY._capture_r6_state_preimage(state["root"], TARGET, state["receipt_pins"])


def test_changed_input_fresh_result_adds_only_one_exact_run_and_product(two_generation_state):
    state = two_generation_state
    attempt = _attempt(FRESH_ID, FRESH_INPUT)
    product = _product_record(FRESH_ID, FRESH_INPUT)
    run_raw, product_raw = _raw(attempt), _raw(product)
    (state["run_root"] / f"{FRESH_ID}.json").write_bytes(run_raw)
    (state["run_root"] / "latest.json").write_bytes(run_raw)
    (state["product_root"] / f"{FRESH_ID}.json").write_bytes(product_raw)
    (state["product_root"] / "latest.json").write_bytes(product_raw)

    result = CANARY._verify_current13_success_write_set(
        state["root"], TARGET, FRESH_ID, product["sha256"], FRESH_INPUT,
        attempt, "FRESH", state["snapshot"],
    )
    assert result["status"] == "PASS_R6_FRESH_MATERIALIZATION_PRIOR_GENERATIONS_PRESERVED"
    assert result["mode"] == "FRESH"
    assert result["archived_version_preserved"] is True
    assert result["r4b_current_version_preserved"] is True
    assert result["allowed_run_write_set"] == sorted({"latest.json", ARCHIVED_ID + ".json", CURRENT_ID + ".json", FRESH_ID + ".json"})
    assert result["allowed_product_write_set"] == result["allowed_run_write_set"]


def test_fresh_result_rejects_same_input_identity_and_extra_files(two_generation_state):
    state = two_generation_state
    attempt = _attempt(FRESH_ID, CURRENT_INPUT)
    product = _product_record(FRESH_ID, CURRENT_INPUT)
    run_raw, product_raw = _raw(attempt), _raw(product)
    (state["run_root"] / f"{FRESH_ID}.json").write_bytes(run_raw)
    (state["run_root"] / "latest.json").write_bytes(run_raw)
    (state["product_root"] / f"{FRESH_ID}.json").write_bytes(product_raw)
    (state["product_root"] / "latest.json").write_bytes(product_raw)
    with pytest.raises(ValueError, match="R6_FRESH_RESULT_DID_NOT_CHANGE_INPUT_IDENTITY"):
        CANARY._verify_current13_success_write_set(
            state["root"], TARGET, FRESH_ID, product["sha256"], CURRENT_INPUT,
            attempt, "FRESH", state["snapshot"],
        )

    (state["run_root"] / ("4" * 32 + ".json")).write_bytes(b"extra")
    with pytest.raises(ValueError, match="R6_FRESH_RUN_WRITE_SET_MISMATCH"):
        CANARY._verify_current13_success_write_set(
            state["root"], TARGET, FRESH_ID, product["sha256"], FRESH_INPUT,
            attempt, "FRESH", state["snapshot"],
        )


def test_same_input_reuse_is_only_current_357_with_no_materialization(two_generation_state):
    state = two_generation_state
    result = CANARY._verify_current13_success_write_set(
        state["root"], TARGET, CURRENT_ID, state["current_product"]["sha256"],
        CURRENT_INPUT, state["current_attempt"], "REUSE", state["snapshot"],
    )
    assert result["status"] == "PASS_R6_REUSE_NO_NEW_MATERIALIZATION"
    assert result["mode"] == "REUSE"
    assert result["latest_still_357"] is True
    assert result["new_files"] == []
    assert result["allowed_run_write_set"] == sorted({"latest.json", ARCHIVED_ID + ".json", CURRENT_ID + ".json"})


def test_reuse_rejects_noncurrent_identity_attempt_or_extra_file(two_generation_state):
    state = two_generation_state
    with pytest.raises(ValueError, match="R6_REUSE_IDENTITY_NOT_CURRENT_R4B_PRODUCT"):
        CANARY._verify_current13_success_write_set(
            state["root"], TARGET, CURRENT_ID, state["current_product"]["sha256"],
            FRESH_INPUT, state["current_attempt"], "REUSE", state["snapshot"],
        )

    (state["run_root"] / ("4" * 32 + ".json")).write_bytes(b"extra")
    with pytest.raises(ValueError, match="R6_REUSE_RUN_WRITE_SET_MISMATCH"):
        CANARY._verify_current13_success_write_set(
            state["root"], TARGET, CURRENT_ID, state["current_product"]["sha256"],
            CURRENT_INPUT, state["current_attempt"], "REUSE", state["snapshot"],
        )


def test_failed_attempt_journal_is_exact_and_keeps_357_product_latest(two_generation_state):
    state = two_generation_state
    failed = _attempt(FRESH_ID, FRESH_INPUT, "FAILED")
    failed_raw = _raw(failed)
    (state["run_root"] / f"{FRESH_ID}.json").write_bytes(failed_raw)
    (state["run_root"] / "latest.json").write_bytes(failed_raw)
    result = CANARY._assert_current13_failure_preserved(state["root"], state["snapshot"])
    assert result["status"] == "PASS_EXACT_FAILED_RUN_JOURNAL_PRIOR_PRODUCT_LATEST_PRESERVED"
    assert result["failed_run_id"] == FRESH_ID
    assert result["failed_state"] == "FAILED"
    assert result["canary_success"] is False
    assert result["prior_current_run_id_preserved"] == CURRENT_ID
    assert result["allowed_product_write_set"] == sorted({"latest.json", ARCHIVED_ID + ".json", CURRENT_ID + ".json"})


def test_failed_attempt_rejects_extra_product_or_changed_history(two_generation_state):
    state = two_generation_state
    failed_raw = _raw(_attempt(FRESH_ID, FRESH_INPUT, "FAILED"))
    (state["run_root"] / f"{FRESH_ID}.json").write_bytes(failed_raw)
    (state["run_root"] / "latest.json").write_bytes(failed_raw)
    (state["product_root"] / f"{FRESH_ID}.json").write_bytes(b"unexpected product")
    with pytest.raises(ValueError, match="R6_FAILURE_PRODUCT_WRITE_SET_MISMATCH"):
        CANARY._assert_current13_failure_preserved(state["root"], state["snapshot"])

    (state["product_root"] / f"{FRESH_ID}.json").unlink()
    (state["run_root"] / f"{ARCHIVED_ID}.json").write_bytes(b"archive changed")
    with pytest.raises(ValueError, match="R6_PRESERVED_HISTORY_MUTATED:archived_run"):
        CANARY._assert_current13_failure_preserved(state["root"], state["snapshot"])


def test_owner_post_get_and_terminal_attempt_must_match_for_fresh_and_reuse():
    for outcome in ("FRESH", "REUSE"):
        refresh, readback, attempt = _owner_pair(outcome=outcome)
        run_id, product_sha, identity, attempt_state = CANARY._validate_owner_pair(refresh, readback, TARGET)
        assert run_id == attempt["run_id"]
        assert product_sha == refresh["plan_product"]["sha256"]
        assert identity == attempt["input_identity"]
        assert attempt_state == "PARTIAL"


def test_owner_pair_rejects_mismatched_attempt_or_stale_diagnostics():
    refresh, readback, attempt = _owner_pair()
    mismatched = dict(attempt)
    mismatched["finished_at"] = "2026-10-12T09:30:02+08:00"
    mismatched["sha256"] = CANARY.common.canonical_sha({k: v for k, v in mismatched.items() if k != "sha256"})
    readback["workspace_plan_attempt"] = mismatched
    with pytest.raises(ValueError, match="CANARY_OWNER_READBACK_MISMATCH"):
        CANARY._validate_owner_pair(refresh, readback, TARGET)

    refresh, readback, _ = _owner_pair()
    readback["plan_product"]["input_identity_diagnostics"]["saved_input_identity"] = "4" * 64
    with pytest.raises(ValueError, match="CANARY_OWNER_PRODUCT_READBACK_IDENTITY_MISMATCH"):
        CANARY._validate_owner_pair(refresh, readback, TARGET)


def test_current13_prepost_gate_rejects_lock_race_and_protected_date_change(two_generation_state):
    state = two_generation_state
    lock_path = state["root"] / ".locks" / f"{TARGET}-workspace-plan-refresh.mutex"
    with lock_path.open("r+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(ValueError, match="R6_OWNER_LOCK_BUSY"):
                CANARY._assert_current13_preimage_unchanged(state["root"], state["snapshot"])
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    protected = state["root"] / "workspace_plans" / "20261009"
    protected.mkdir(parents=True)
    (protected / "preserve.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="R6_PROTECTED_DATES_PREIMAGE_MISMATCH"):
        CANARY._assert_current13_preimage_unchanged(state["root"], state["snapshot"])


def test_r6_adapter_keeps_original_cas_observer_reload_and_rollback_functions():
    original_path = TASK_ROOT / "E/tools/issue35_phase4_pair_publication_adapter_r4_observer.py"
    r6_path = Path(__file__).with_name("issue35_phase6_r6_publication_adapter.py")
    original_raw, r6_raw = original_path.read_bytes(), r6_path.read_bytes()
    assert CANARY.common.sha256_bytes(original_raw) == (
        "25c381c6921c00bf9877d0237e8e418bef4a6426d6546fc84a8d145c9e9b6d3c"
    )
    original_tree = ast.parse(original_raw)
    r6_tree = ast.parse(r6_raw)

    def function_node(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
        return next(node for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)

    for name in ("validate_scheduler_env_delta", "pair_state", "cas_replace", "guarded_recover",
                 "load_integrator", "load_observer",
                 "_observe_pair_service", "_observe_original_pair", "_launch_action",
                 "_wait_label", "execute_or_rollback", "self_test"):
        assert ast.dump(function_node(original_tree, name), include_attributes=False) == ast.dump(
            function_node(r6_tree, name), include_attributes=False
        ), name


def test_r6_canary_preserves_single_original_post_get_route_and_response_capture():
    original_path = TASK_ROOT / "E/tools/issue35_phase4_canary.py"
    r6_path = Path(__file__).with_name("issue35_phase6_r6_canary.py")
    original_tree = ast.parse(original_path.read_bytes())
    r6_tree = ast.parse(r6_path.read_bytes())

    def function_node(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
        return next(node for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)

    for name in ("_configure_runtime_environment", "_http_record", "_owner_app",
                 "_owner_response_projection", "_write_contract_projection_evidence",
                 "_projection_evidence_summary"):
        assert ast.dump(function_node(original_tree, name), include_attributes=False) == ast.dump(
            function_node(r6_tree, name), include_attributes=False
        ), name
    owner = function_node(r6_tree, "_execute_owner_canary")
    calls = [node for node in ast.walk(owner) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and isinstance(node.func.value, ast.Name) and node.func.value.id == "client"
             and node.func.attr in {"post", "get"}]
    assert [node.func.attr for node in calls] == ["post", "get"]


def test_r6_adapter_validates_exact_pending_transport_pins_and_uses_versioned_paths():
    adapter_path = Path(__file__).with_name("issue35_phase6_r6_publication_adapter.py")
    spec = importlib.util.spec_from_file_location("issue35_phase6_r6_adapter_under_test", adapter_path)
    assert spec is not None and spec.loader is not None
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    pins = adapter.verify_r6_transport_pins()

    assert pins["r6_transport"]["status"] == "READY_FOR_REVIEW_PENDING_R6_CANARY_AND_STAGE"
    assert pins["candidate"]["manifest_sha256"] == adapter.MANIFEST_SHA256
    assert pins["r6_transport"]["canary_wrapper"]["path"] == str(adapter.ORIGINAL_CANARY)
    assert pins["pending_stage"]["canary_sha256"].startswith("PENDING_")
    assert all(value.startswith("PENDING_") for value in adapter.EXISTING_STAGE_SHA256.values())
    assert adapter.DEFAULT_PAIR_DIR == TASK_ROOT / "E/staged_config/phase6-r6/after-canary/pair-r6"
    assert "issue35_phase4_pair_publication_adapter_r4_observer.py" not in adapter_path.read_text(encoding="utf-8")

