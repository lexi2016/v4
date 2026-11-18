import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import sys

import numpy as np
import pytest

from ops import research_panel_formula_groups_daily as groups


FLAGS = groups.FLAGS


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")) + "\n")


def _committed_pointer(root, source):
    day = root / source["source_date"]
    artifact = {
        "schema": "V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1",
        "source_date": source["source_date"],
        "observation_date": source["observation_date"],
        "generation": source["generation"],
        "input_sha256": source["input_sha256"],
        "numeric_manifest": source["numeric_manifest"],
        "selector_sha256": source["selector_sha256"],
        "formula_sha256": groups.FORMULA_SHA256,
        "group_counts": {"b23_entry": 2, "pb2_confirm": 1},
        "rows": [{"symbol": "000001.SZ", "groups": ["b23_entry"]}],
        **FLAGS,
    }
    artifact_bytes = (json.dumps(artifact, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")) + "\n").encode()
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    artifact_path = day / "artifacts" / f"{artifact_sha}.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(artifact_bytes)
    artifact_ref = {"path": str(artifact_path), "sha256": artifact_sha}
    receipt = {"status": "COMMITTED", "artifact": artifact_ref,
               "source_date": source["source_date"], "generation": source["generation"],
               "numeric_manifest": source["numeric_manifest"], **FLAGS}
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n").encode()
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_path = day / "receipts" / f"{receipt_sha}.json"
    receipt_path.parent.mkdir()
    receipt_path.write_bytes(receipt_bytes)
    _write_json(day / "latest.json", {
        "schema": "V4_WORKBENCH_MODULE_COMMIT_V1", "module": "formula_groups",
        "date": source["source_date"], "artifact": artifact_ref,
        "receipt": {"path": str(receipt_path), "sha256": receipt_sha}, **FLAGS,
    })


def _source():
    return {
        "source_date": "2026-11-18", "observation_date": "2026-11-19",
        "generation": "gen-a", "input_sha256": "input-a",
        "numeric_manifest": {"path": "/tmp/numeric.json", "sha256": "numeric-a"},
        "selector_sha256": "selector-a",
    }


def test_exact_committed_artifact_reuses_without_formula_projection(tmp_path):
    source = _source()
    _committed_pointer(tmp_path, source)

    before, committed = groups._current_pointer(tmp_path.resolve(), source)

    assert before != "ABSENT"
    assert committed is not None
    assert committed["artifact"]["sha256"]


def test_new_generation_does_not_reuse_previous_pointer(tmp_path):
    original = _source()
    _committed_pointer(tmp_path, original)
    revised = {**original, "generation": "gen-b", "input_sha256": "input-b"}

    before, committed = groups._current_pointer(tmp_path.resolve(), revised)

    assert before != "ABSENT"
    assert committed is None


def test_damaged_current_artifact_is_not_silently_replaced(tmp_path):
    source = _source()
    _committed_pointer(tmp_path, source)
    latest = tmp_path / source["source_date"] / "latest.json"
    pointer = json.loads(latest.read_text())
    artifact_path = pointer["artifact"]["path"]
    with open(artifact_path, "ab") as stream:
        stream.write(b"drift")

    with pytest.raises(ValueError, match="FORMULA_CURRENT_ARTIFACT_DRIFT"):
        groups._current_pointer(tmp_path.resolve(), source)


def test_broken_latest_symlink_is_not_treated_as_absent(tmp_path):
    source = _source()
    day = tmp_path / source["source_date"]
    day.mkdir()
    (day / "latest.json").symlink_to(day / "missing.json")

    with pytest.raises(ValueError, match="FORMULA_CURRENT_POINTER_INVALID"):
        groups._current_pointer(tmp_path.resolve(), source)


def test_worker_count_uses_cpu_and_live_memory_with_a_cap():
    assert groups.choose_workers(18, 128 * 1024**3) == 14
    assert groups.choose_workers(6, 16 * 1024**3) == 4
    assert groups.choose_workers(2, 128 * 1024**3) == 1
    assert groups.choose_workers(18, 0) == 1


def test_worker_count_uses_conservative_cpu_bound_when_memory_unknown(monkeypatch):
    monkeypatch.setattr(groups, "_available_memory_bytes", lambda: None)
    assert groups.choose_workers(18) == 4


def test_pinned_runtime_code_assets_match_declared_hashes():
    for name, expected in groups.ASSET_SHA256.items():
        assert hashlib.sha256((groups.PARTS / name).read_bytes()).hexdigest() == expected


def test_spawned_worker_imports_exact_project_and_date():
    prior_path = list(sys.path)
    prior_project = sys.modules.get("project")
    sys.path.insert(0, str(groups.PARTS))
    project = groups._load_module("project", groups.PROJECT_PATH)
    task = ("000001.SZ", None, "SZ", np.array([20261118]),
            np.full((1, 6), np.nan, dtype=np.float64))
    try:
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"),
                                 initializer=groups._setup_formula_worker,
                                 initargs=({}, 20261118)) as pool:
            status, _ = pool.submit(project.evaluate, task).result(timeout=30)
        assert status["status"] == "INVALID_BOUND_HISTORY"
        assert status["source_date"] == 20261118
    finally:
        sys.path[:] = prior_path
        if prior_project is None:
            sys.modules.pop("project", None)
        else:
            sys.modules["project"] = prior_project
