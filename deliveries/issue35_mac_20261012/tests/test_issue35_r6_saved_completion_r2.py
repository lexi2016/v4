"""Temp-only atomic publication regressions for the Issue35 R6 saved completion."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R2 = _load_module(
    "issue35_r6_saved_completion_r2_under_test",
    Path(__file__).with_name("complete_issue35_r6_saved_canary_r2.py"),
)
BASE = _load_module(
    "issue35_r6_saved_completion_base_fixture",
    Path(__file__).with_name("test_issue35_r6_get_dto_saved_completion.py"),
)
CANARY = R2.CANARY
COMMON = R2.common
NOW = BASE.NOW


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(autouse=True)
def forbid_owner_execution(monkeypatch):
    monkeypatch.setattr(CANARY, "_execute_owner_canary",
                        lambda *args, **kwargs: pytest.fail("owner path must never execute"))


@pytest.fixture
def saved_execution(tmp_path: Path):
    fx = BASE.saved_execution.__wrapped__(tmp_path)
    task_root = fx["task_root"]
    for relative in (
        "PHASE6_SAVED_COMPLETION_ATOMIC_R2_SCOPE.md",
        "review/phase6-get-dto-saved-completion/independent-review.json",
    ):
        source = R2.TASK_ROOT / relative
        destination = task_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return fx


def _state_hashes(state_root: Path) -> dict[str, str]:
    return {
        str(path): _sha(path.read_bytes())
        for path in state_root.rglob("*") if path.is_file()
    }


def _private_publication(fx: dict) -> tuple[Path, Path]:
    private = list(fx["output_dir"].parent.glob(R2._r2_private_prefix(fx["output_dir"]) + "*"))
    assert len(private) == 1
    publish = private[0] / "publish"
    assert (publish / "plan-canary.json").is_file()
    return private[0], publish


def _private_complete_output_exists(fx: dict) -> bool:
    private = list(fx["output_dir"].parent.glob(R2._r2_private_prefix(fx["output_dir"]) + "*"))
    if len(private) != 1:
        return False
    publish = private[0] / "publish"
    return ((publish / "plan-canary.json").is_file()
            and (publish / "completion-receipt.json").is_file())


def _assert_candidate_consumer_accepts(fx: dict, canary_path: Path) -> None:
    raw = canary_path.read_bytes()
    release = fx["release"]
    release["contract"]._validate_plan_canary(
        {"path": str(canary_path), "sha256": _sha(raw)},
        app=release["app_root"], state=fx["state_root"],
        owner_identity={"app_root": release["app_root"], "files": release["binding_files"]},
    )


def _assert_failure_has_only_private_stage_accepted_canary(fx: dict) -> None:
    assert not fx["output_dir"].exists()
    _, publish = _private_publication(fx)
    assert (publish / "completion-receipt.json").is_file()
    _assert_candidate_consumer_accepts(fx, publish / "plan-canary.json")


def test_r2_success_publishes_complete_stage_accepted_directory_atomically(saved_execution, monkeypatch):
    fx = saved_execution
    before_state = _state_hashes(fx["state_root"])
    result = R2.complete_saved_execution(
        task_root=fx["task_root"], state_root=fx["state_root"],
        output_dir=fx["output_dir"], release=fx["release"], now=NOW,
        pins=fx["pins"], receipt_pins=fx["receipt_pins"],
    )
    expected_files = {
        "refresh.verified-projection.response.bin", "refresh.verified-projection.http-evidence.json",
        "readback.verified-projection.response.bin", "readback.verified-projection.http-evidence.json",
        "plan-canary.json", "completion-receipt.json",
    }
    assert result["status"] == "PASS_OFFLINE_SAVED_OWNER_READBACK_COMPLETION"
    assert {path.name for path in fx["output_dir"].iterdir()} == expected_files
    _assert_candidate_consumer_accepts(fx, fx["output_dir"] / "plan-canary.json")
    canary = json.loads((fx["output_dir"] / "plan-canary.json").read_bytes())
    receipt = json.loads((fx["output_dir"] / "completion-receipt.json").read_bytes())
    assert receipt["completed_canary"]["path"] == str(fx["output_dir"] / "plan-canary.json")
    assert receipt["atomic_publication"]["no_replace_flag"] == "RENAME_EXCL"
    assert result["support_dir"] == receipt["atomic_publication"]["persistent_projection_support_directory"]
    support = Path(result["support_dir"])
    assert support.is_dir()
    assert all(Path(ref["path"]).is_file() for ref in canary["owner_evidence"].values())
    assert before_state == _state_hashes(fx["state_root"])
    assert not list(fx["output_dir"].parent.glob(R2._r2_private_prefix(fx["output_dir"]) + "*/publish"))
    assert len(list(fx["output_dir"].parent.glob(R2._r2_private_prefix(fx["output_dir"]) + "*"))) == 1


@pytest.mark.parametrize("gate_name,error_code", [
    ("date", "TARGET_IS_NOT_NEXT_HK_SESSION_AT_CURRENT_CLOCK"),
    ("protected", "R6_COMPLETION_PROTECTED_DATES_CHANGED_DURING_WRITE"),
    ("current_state", "R6_COMPLETION_OWNER_STATE_CHANGED_DURING_WRITE"),
    ("mutex", "R6_COMPLETION_OWNER_LOCK_BUSY_AFTER_WRITE"),
])
def test_r2_late_gate_failure_keeps_stage_acceptable_canary_out_of_fixed_path(
        saved_execution, monkeypatch, gate_name: str, error_code: str):
    fx = saved_execution
    before_state = _state_hashes(fx["state_root"])
    stage_acceptance = {"passed": False}
    contract = fx["release"]["contract"]
    original_validator = contract._validate_plan_canary

    def record_stage_acceptance(*args, **kwargs):
        value = original_validator(*args, **kwargs)
        stage_acceptance["passed"] = True
        return value

    monkeypatch.setattr(contract, "_validate_plan_canary", record_stage_acceptance)
    if gate_name == "date":
        original_gate = COMMON.require_next_session

        def fail_date_after_package(*args, **kwargs):
            if _private_complete_output_exists(fx):
                assert stage_acceptance["passed"]
                raise ValueError(error_code)
            return original_gate(*args, **kwargs)

        monkeypatch.setattr(COMMON, "require_next_session", fail_date_after_package)
    elif gate_name == "protected":
        original_gate = COMMON.protected_state_hashes

        def change_protected_map_after_package(*args, **kwargs):
            actual = original_gate(*args, **kwargs)
            if _private_complete_output_exists(fx):
                assert stage_acceptance["passed"]
                return {"forced-drift": {"sha256": "f" * 64}}
            return actual

        monkeypatch.setattr(COMMON, "protected_state_hashes", change_protected_map_after_package)
    elif gate_name == "current_state":
        original_gate = R2._verify_current_fresh_state

        def change_current_state_after_package(*args, **kwargs):
            if _private_complete_output_exists(fx):
                assert stage_acceptance["passed"]
                raise ValueError(error_code)
            return original_gate(*args, **kwargs)

        monkeypatch.setattr(R2, "_verify_current_fresh_state", change_current_state_after_package)
    else:
        original_gate = CANARY._kernel_lock_is_free
        calls_after_package = {"count": 0}

        def busy_mutex_after_package(*args, **kwargs):
            if _private_complete_output_exists(fx):
                assert stage_acceptance["passed"]
                calls_after_package["count"] += 1
                # The first late probe belongs to the fresh-state verifier;
                # the second is the explicit final mutex gate before publish.
                if calls_after_package["count"] == 2:
                    return False
            return original_gate(*args, **kwargs)

        monkeypatch.setattr(CANARY, "_kernel_lock_is_free", busy_mutex_after_package)
    with pytest.raises(ValueError, match=error_code):
        R2.complete_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            output_dir=fx["output_dir"], release=fx["release"], now=NOW,
            pins=fx["pins"], receipt_pins=fx["receipt_pins"],
        )
    assert stage_acceptance["passed"] is True
    if gate_name == "mutex":
        assert calls_after_package["count"] == 2
    assert not fx["output_dir"].exists()
    assert not list(fx["output_dir"].parent.glob(R2._r2_private_prefix(fx["output_dir"]) + "*"))
    assert before_state == _state_hashes(fx["state_root"])


def test_r2_completion_receipt_size_failure_cleans_private_canary(saved_execution, monkeypatch):
    fx = saved_execution
    before_state = _state_hashes(fx["state_root"])
    original_json_bytes = R2._json_bytes

    def oversized_completion(value):
        if value.get("schema_version") == "issue35.phase6.execution03.offline_completion.r2.v1":
            _assert_candidate_consumer_accepts(
                fx, _private_publication(fx)[1] / "plan-canary.json",
            )
            return b"x" * (1024 * 1024 + 1)
        return original_json_bytes(value)

    monkeypatch.setattr(R2, "_json_bytes", oversized_completion)
    with pytest.raises(ValueError, match="R6_COMPLETION_RECEIPT_EXCEEDS_LIMIT"):
        R2.complete_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            output_dir=fx["output_dir"], release=fx["release"], now=NOW,
            pins=fx["pins"], receipt_pins=fx["receipt_pins"],
        )
    assert not fx["output_dir"].exists()
    assert not list(fx["output_dir"].parent.glob(R2._r2_private_prefix(fx["output_dir"]) + "*"))
    assert before_state == _state_hashes(fx["state_root"])


def test_r2_existing_output_is_never_overwritten(saved_execution):
    fx = saved_execution
    fx["output_dir"].mkdir()
    marker = fx["output_dir"] / "preserve-me.txt"
    marker.write_text("pre-existing", encoding="utf-8")
    with pytest.raises(FileExistsError, match="R6_COMPLETION_OUTPUT_ALREADY_EXISTS"):
        R2.complete_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            output_dir=fx["output_dir"], release=fx["release"], now=NOW,
            pins=fx["pins"], receipt_pins=fx["receipt_pins"],
        )
    assert marker.read_text(encoding="utf-8") == "pre-existing"


def test_r2_atomic_rename_excl_rejects_destination_race_and_cleans_private_work(saved_execution, monkeypatch):
    fx = saved_execution
    before_state = _state_hashes(fx["state_root"])
    original_rename = R2._rename_directory_exclusive

    def create_competing_destination(source: Path, destination: Path):
        destination.mkdir()
        (destination / "race-marker.txt").write_text("winner", encoding="utf-8")
        return original_rename(source, destination)

    monkeypatch.setattr(R2, "_rename_directory_exclusive", create_competing_destination)
    with pytest.raises(OSError):
        R2.complete_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            output_dir=fx["output_dir"], release=fx["release"], now=NOW,
            pins=fx["pins"], receipt_pins=fx["receipt_pins"],
        )
    assert (fx["output_dir"] / "race-marker.txt").read_text(encoding="utf-8") == "winner"
    assert not (fx["output_dir"] / "plan-canary.json").exists()
    assert not list(fx["output_dir"].parent.glob(R2._r2_private_prefix(fx["output_dir"]) + "*"))
    assert before_state == _state_hashes(fx["state_root"])


def test_r2_stale_private_workspace_is_refused_without_deletion(saved_execution):
    fx = saved_execution
    stale = fx["output_dir"].parent / (R2._r2_private_prefix(fx["output_dir"]) + "interrupted")
    stale.mkdir()
    marker = stale / "inspect.txt"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError, match="R6_COMPLETION_STALE_PRIVATE_WORKSPACE_REQUIRES_INSPECTION"):
        R2.complete_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            output_dir=fx["output_dir"], release=fx["release"], now=NOW,
            pins=fx["pins"], receipt_pins=fx["receipt_pins"],
        )
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_r2_imported_common_support_source_is_pinned(tmp_path: Path, monkeypatch):
    support_copy = tmp_path / "issue35_phase4_common.py"
    support_copy.write_bytes(Path(R2._COMMON_PATH).read_bytes() + b"\n# drift\n")
    monkeypatch.setattr(R2, "_COMMON_PATH", support_copy)
    with pytest.raises(ValueError, match="R6_COMPLETION_COMMON_SOURCE_SHA256_MISMATCH"):
        R2._verify_source_pins()


def test_r2_scope_and_formal_review_sources_are_pinned(saved_execution):
    fx = saved_execution
    (fx["task_root"] / "PHASE6_SAVED_COMPLETION_ATOMIC_R2_SCOPE.md").write_bytes(b"changed")
    with pytest.raises(ValueError, match="R6_ATOMIC_R2_SCOPE_SHA256_MISMATCH"):
        R2.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=NOW, pins=fx["pins"],
            receipt_pins=fx["receipt_pins"],
        )
