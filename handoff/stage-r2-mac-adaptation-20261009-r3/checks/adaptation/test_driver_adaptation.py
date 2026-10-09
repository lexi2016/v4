"""Canary propagation of the bounded-copy and readonly-source preparation rules."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from test_prepare_adaptation import EXTERNAL, ROOT, TOOLS, digest, inventory, load_tool, policy_fixture, write_json


_spec = importlib.util.spec_from_file_location("legacy_driver_fixture", ROOT / "tests/test_run_current_research_canary.py")
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)
inputs = legacy.inputs


def bounded_candidate(inputs, *, links=True):
    package, app = inputs["package"], inputs["stage_app"]
    mapping = json.loads((package / "SOURCE_MAP.json").read_text())
    policy_fixture(package, mapping)
    if links:
        (app / "v3_shared_data").symlink_to("upstreams/v3_shared_data")
        (app / "upstreams/v3.5").symlink_to(EXTERNAL)
    destination = app.parent / "bounded_candidate"
    result = load_tool().prepare(package, "stage", app, destination)
    assert result["status"] == "CANARY_PREPARED", result
    inputs["stage_app"] = destination
    return destination


def test_driver_accepts_prepared_internal_link_and_records_source_runtime_difference(inputs):
    app = bounded_candidate(inputs)
    originals = legacy.originals(inputs)
    result = load_tool("run_current_research_canary").run_canary(**legacy.arguments(inputs))
    assert result["status"] == "PREPARED", result
    assert legacy.originals(inputs) == originals
    assert result["source_dependency_boundary"]["quarantined_links"][0]["link_text"] == EXTERNAL
    assert result["source_dependency_boundary"]["dynamic_dependency_status"] == "CANNOT_CONFIRM"
    assert result["source_dependency_boundary"]["configuration_and_environment_checked"] is True
    assert os.readlink(app / "v3_shared_data") == "upstreams/v3_shared_data"
    assert not os.path.lexists(app / "upstreams/v3.5")


def test_prepare_and_driver_share_identical_cache_and_venv_exclusions(inputs):
    app = inputs["stage_app"]
    for name in (".cache", "venv"):
        (app / name).mkdir()
        (app / name / "unrelated_runtime_link").symlink_to("/not_a_source_dependency")
    prepared = bounded_candidate(inputs)
    assert not (prepared / ".cache").exists()
    assert not (prepared / "venv").exists()
    result = load_tool("run_current_research_canary").run_canary(**legacy.arguments(inputs))
    assert result["status"] == "PREPARED", result


def test_driver_accepts_declared_shared_alias_without_following_arbitrary_links(inputs):
    app = bounded_candidate(inputs)
    config = dict(inputs["_config"], shared_data_root=str(app / "v3_shared_data"))
    write_json(inputs["config_path"], config)
    before = legacy.originals(inputs)
    result = load_tool("run_current_research_canary").run_canary(**legacy.arguments(inputs))
    assert result["status"] == "PREPARED", result
    assert result["shared_source"]["effective_root"] == str(app / "upstreams/v3_shared_data")
    assert result["shared_source"]["copied"] is False
    assert result["shared_source"]["lexical_original_root"] == str(app / "v3_shared_data")
    assert legacy.originals(inputs) == before


def test_driver_readonly_shared_copy_replacement_is_verified_in_real_nonroot_process(inputs):
    shared = inputs["_shared"]
    for directory, dirs, files in os.walk(shared):
        Path(directory).chmod(0o555)
        for name in files:
            (Path(directory) / name).chmod(0o444)
    before = {str(path): inventory(path) for path in (inputs["package"], inputs["stage_app"], inputs["hk_input"], shared)}
    bootstrap = r'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("real_nonroot_driver", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
result = module.run_canary(**json.loads(sys.argv[2]))
print(json.dumps({"uid": os.geteuid(), "result": result}))
'''
    prefix = ["unshare", "--user"] if os.geteuid() == 0 else []
    args = {key: str(value) for key, value in legacy.arguments(inputs).items()}
    child = subprocess.run([*prefix, sys.executable, "-B", "-c", bootstrap,
                            str(TOOLS / "run_current_research_canary.py"), json.dumps(args)], capture_output=True, text=True)
    assert child.returncode == 0, child.stderr
    payload = json.loads(child.stdout)
    assert payload["uid"] != 0
    result = payload["result"]
    assert result["status"] == "PREPARED", result
    assert result["shared_source"]["permissions_restored"] is True
    copied = inputs["output_root"] / "shared_data"
    assert stat.S_IMODE(copied.stat().st_mode) == 0o555
    assert stat.S_IMODE((copied / "scripts/live_acquisition/pytdx_hq.py").stat().st_mode) == 0o444
    assert {str(path): inventory(path) for path in (inputs["package"], inputs["stage_app"], inputs["hk_input"], shared)} == before


@pytest.mark.parametrize("key", ["candidate_acquisition_root", "v3_research_root", "v4_research_data_root", "a_research_panel_receipt_root"])
def test_driver_rejects_actual_config_dependency_on_quarantined_external_target(inputs, key):
    bounded_candidate(inputs, links=False)
    config = dict(inputs["_config"], **{key: EXTERNAL + "/data"})
    write_json(inputs["config_path"], config)
    result = load_tool("run_current_research_canary").run_canary(**legacy.arguments(inputs))
    assert result["status"] == "PREFLIGHT_FAILED", result
    assert any("QUARANTINED_RUNTIME_DEPENDENCY:" + key in error for error in result["errors"])
    assert not inputs["output_root"].exists()


@pytest.mark.parametrize("key", ["PYTHONPATH", "V3_SHARED_DATA_SOURCE_ROOT"])
def test_driver_checks_only_relevant_inherited_dependency_environment(inputs, monkeypatch, key):
    bounded_candidate(inputs, links=False)
    monkeypatch.setenv(key, EXTERNAL + "/hooks")
    result = load_tool("run_current_research_canary").run_canary(**legacy.arguments(inputs))
    assert result["status"] == "PREFLIGHT_FAILED", result
    assert any("QUARANTINED_RUNTIME_DEPENDENCY:" + key in error for error in result["errors"])
    assert not inputs["output_root"].exists()


def test_driver_guards_effective_output_roots_and_does_not_scan_unrelated_environment(inputs, monkeypatch):
    app = bounded_candidate(inputs)
    monkeypatch.setenv("UNRELATED_ARCHIVE_LOCATION", EXTERNAL)
    config = dict(inputs["_config"], raw_root=EXTERNAL, receipt_root=EXTERNAL, selection_root=EXTERNAL)
    write_json(inputs["config_path"], config)
    result = load_tool("run_current_research_canary").run_canary(**legacy.arguments(inputs))
    assert result["status"] == "PREPARED", result
    assert all(Path(value).is_relative_to(inputs["output_root"]) for key, value in result["output_paths"].items())


def test_driver_rejects_changed_preparation_manifest_even_if_mapped_after_bytes_match(inputs):
    app = bounded_candidate(inputs, links=False)
    path = app / "CANARY_SOURCE_MANIFEST.json"
    manifest = json.loads(path.read_text())
    manifest["candidate_tree_sha256"] = "0" * 64
    write_json(path, manifest)
    result = load_tool("run_current_research_canary").run_canary(**legacy.arguments(inputs))
    assert result["status"] == "PREFLIGHT_FAILED", result
    assert any("CANDIDATE_SOURCE_MANIFEST_MISMATCH" in error for error in result["errors"])
    assert not inputs["output_root"].exists()


def test_policy_candidate_cannot_drop_manifest_and_run_changed_unmapped_dependencies(inputs, monkeypatch):
    app = bounded_candidate(inputs)
    (app / "CANARY_SOURCE_MANIFEST.json").unlink()
    (app / "unreviewed_dependency.py").write_bytes(b"UNREVIEWED = True\n")
    quotes = [{"batch_index": index, "code": row["code"], "name": row["name"],
               "update_time": "2026-10-09 09:35:00", "last_price": 10.0 + index,
               "open_price": 10.0, "high_price": 12.0 + index, "low_price": 9.0,
               "prev_close_price": 10.0, "turnover": 20000000.0 + index, "volume": 500.0,
               "bid_price": None, "ask_price": None, "bid_vol": None, "ask_vol": None,
               "window_start": "2026-10-09 09:30:00", "window_end": "2026-10-09 09:35:00",
               "bar_count": 5, "temporal_cutoff_safe": True}
              for index, row in enumerate(inputs["_rows"], 1)]
    hook = app.parent / "external_io_fixture"
    legacy.bridge_hook(hook, quotes)
    monkeypatch.setenv("PYTHONPATH", str(hook))
    result = load_tool("run_current_research_canary").run_canary(**legacy.arguments(inputs), execute=True)
    assert result["status"] == "PREFLIGHT_FAILED", result
    assert result["executed"] is False
    assert "CANDIDATE_SOURCE_MANIFEST_REQUIRED" in result["errors"]
    assert not inputs["output_root"].exists()


def test_driver_executes_existing_owner_from_linked_candidate_and_keeps_research_contract(inputs, monkeypatch):
    bounded_candidate(inputs)
    legacy.test_execute_invokes_real_owner_and_reports_same_run_without_false_success(inputs, monkeypatch, 12)
