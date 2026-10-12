"""Temp-state tests for the non-destructive current13 owner acceptance gate."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("issue35_phase4_canary_under_test",
    TOOLS / "issue35_phase4_canary.py")
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _state(tmp_path: Path, *, add_new_run: bool = False):
    root = tmp_path.resolve()
    target = "20261013"
    old_run = "d8a35106712a4387accf214c3ee3772d"
    new_run = "11111111111111111111111111111111"
    run_root = root / "workspace_plan_runs" / target
    plan_root = root / "workspace_plans" / target
    lock_root = root / ".locks"
    run_root.mkdir(parents=True)
    plan_root.mkdir(parents=True)
    lock_root.mkdir()
    (lock_root / f"{target}-workspace-plan-refresh.mutex").write_bytes(b"")
    run_raw = b"prior-run"
    product_raw = b"prior-product"
    for path, raw in ((run_root / f"{old_run}.json", run_raw),
                      (run_root / "latest.json", run_raw),
                      (plan_root / f"{old_run}.json", product_raw),
                      (plan_root / "latest.json", product_raw)):
        path.write_bytes(raw)
    paths = {
        "run_file": run_root / f"{old_run}.json",
        "run_latest": run_root / "latest.json",
        "product_file": plan_root / f"{old_run}.json",
        "product_latest": plan_root / "latest.json",
    }
    files = {key: {"path": str(path), "bytes": len(path.read_bytes()),
                   "sha256": _sha(path.read_bytes())} for key, path in paths.items()}
    preimage = {
        "target_trade_date": target,
        "prior_run_id": old_run,
        "prior_product_sha256": _sha(product_raw),
        "prior_input_identity": "0" * 64,
        "prior_state_files": files,
        "protected_dates_sha256": CANARY.common.protected_state_hashes(root),
    }
    if add_new_run:
        (run_root / f"{new_run}.json").write_bytes(b"new-run")
        (plan_root / f"{new_run}.json").write_bytes(b"new-product")
    return root, preimage, new_run


def test_current13_success_allows_one_new_version_and_preserves_old(tmp_path):
    root, preimage, new_run = _state(tmp_path, add_new_run=True)
    result = CANARY._verify_current13_success_write_set(
        root, "20261013", new_run, "1" * 64, preimage)
    assert result["status"] == "PASS_PRIOR_VERSION_PRESERVED"
    assert result["prior_version_files_preserved"] is True
    assert result["allowed_target_write_set"] == sorted([
        "latest.json", preimage["prior_run_id"] + ".json", new_run + ".json"])


def test_current13_failure_requires_exact_prior_latest_and_no_new_files(tmp_path):
    root, preimage, _ = _state(tmp_path)
    result = CANARY._assert_current13_failure_preserved(root, preimage)
    assert result["status"] == "PASS_PRIOR_LATEST_PRESERVED"
    (root / "workspace_plans/20261013/latest.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="CURRENT13_FAILURE_CHANGED_PRIOR_LATEST_OR_RUN"):
        CANARY._assert_current13_failure_preserved(root, preimage)


def test_current13_success_rejects_extra_target_state_file(tmp_path):
    root, preimage, new_run = _state(tmp_path, add_new_run=True)
    (root / "workspace_plan_runs/20261013/unexpected.json").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="CURRENT13_SUCCESS_RUN_WRITE_SET_MISMATCH"):
        CANARY._verify_current13_success_write_set(
            root, "20261013", new_run, "1" * 64, preimage)


def test_current13_prepost_gate_rejects_concurrent_latest_change(tmp_path):
    root, preimage, _ = _state(tmp_path)
    CANARY._assert_current13_preimage_unchanged(root, preimage)
    (root / "workspace_plan_runs/20261013/latest.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="CURRENT13_PREIMAGE_CHANGED_BEFORE_POST:run_latest"):
        CANARY._assert_current13_preimage_unchanged(root, preimage)
