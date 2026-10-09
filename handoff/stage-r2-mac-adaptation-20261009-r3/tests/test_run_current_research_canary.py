"""Real filesystem/owner tests; only the external PyTDX bridge is simulated."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path(os.environ.get("CANARY_TEST_PACKAGE", ROOT))
APP = Path(os.environ.get("CANARY_TEST_STAGE_APP", os.environ.get("STAGE_CHECK_APP", ROOT / "test_support/stage_base_app")))
SCRIPT = Path(os.environ.get("CANARY_TEST_DRIVER", ROOT / "tools/run_current_research_canary.py"))
HQ = "upstreams/v3_shared_data/scripts/live_acquisition/pytdx_hq.py"
DAY, STAGE = "20261009", "STAGE_0930_0935"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    return sha256(path.read_bytes()).hexdigest()


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()}


def tool():
    assert SCRIPT.is_file(), "current research canary driver is not implemented"
    spec = importlib.util.spec_from_file_location("canary_driver_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs(tmp_path):
    package, app, shared = (tmp_path / name for name in ("package", "prepared_app", "original_shared"))
    def synthetic_ignore(directory, names):
        ignored = {"__pycache__", ".pytest_cache"}
        if Path(directory) == APP:
            # This is a new synthetic source identity, not the prepared copy's
            # manifest or its convenience alias. Keep the real upstream tree.
            ignored.update({"CANARY_SOURCE_MANIFEST.json", "v3_shared_data"})
        return set(names) & ignored
    shutil.copytree(APP, app, symlinks=True, ignore=synthetic_ignore)
    shutil.copytree(app / "upstreams/v3_shared_data", shared)
    (shared / "scripts/live_acquisition/pytdx_hq.py").write_bytes(
        (PACKAGE / "before/stage" / HQ).read_bytes())
    (shared / "unchanged_dependency.py").write_bytes(b"PRESERVED = True\n")
    for ignored in (".git", ".venv", "__pycache__"):
        (shared / ignored).mkdir()
        (shared / ignored / "do_not_copy").write_text("unchanged original fixture")
    source_map = json.loads((PACKAGE / "SOURCE_MAP.json").read_text())
    # The synthetic Stage-only map below recalculates its own file identities;
    # it does not inherit the delivery's whole-package policy contract.
    source_map.pop("canary_source_policy_sha256", None)
    source_map["files"] = [row for row in source_map["files"] if row["group"] == "stage"]
    for row in source_map["files"]:
        source = app / row["relative_path"]
        # This is a synthetic package contract around the current full app.
        row["after_sha256"] = sha256(source.read_bytes()).hexdigest()
        after = package / row["after_path"]
        after.parent.mkdir(parents=True, exist_ok=True)
        after.write_bytes(source.read_bytes())
    write_json(package / "SOURCE_MAP.json", source_map)
    hk = tmp_path / "original_hk"
    rows = [{"code": f"HK.{index:05d}", "name": f"样本{index}", "lot_size": 100}
            for index in range(1, 13)]
    values = {"snapshot_rows_projected.json": rows, "receipt.json": {"opaque": "synthetic"},
              "reference_codes_20261008.json": [row["code"] for row in rows],
              "FINAL_RECEIPT.json": {"opaque_final": "synthetic"}}
    pin = {"schema_version": "v4.hk_current_day_research_pin.v1", "mode": "CURRENT_DAY_RESEARCH_ONLY",
           "market": "HK_CONNECT", "trade_date": DAY, "universe_as_of": "20261008",
           "captured_at": "2026-10-09T15:38:41+08:00", "stale_universe": True,
           "hk_connect_membership_status": "CANNOT_CONFIRM", "formal_d1_eligible": False,
           "formal_pit": False, "row_count": len(rows),
           "files": {name: write_json(hk / name, value) for name, value in values.items()},
           "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    write_json(package / "CURRENT_DAY_RESEARCH_PIN.json", pin)
    python_link = tmp_path / "lexical_venv/bin/python"
    python_link.parent.mkdir(parents=True)
    python_link.symlink_to(sys.executable)
    config = {"candidate_acquisition_root": str(tmp_path / "candidate"),
              "raw_root": str(tmp_path / "original_raw"),
              "selection_root": str(tmp_path / "original_selection"),
              "receipt_root": str(tmp_path / "original_receipts"),
              "shared_data_root": str(shared), "python_path": str(python_link),
              "v4_research_data_root": str(tmp_path / "hourly"),
              "v4_morning_news_root": str(tmp_path / "morning"),
              "api_token": "SYNTHETIC_SECRET_MUST_NOT_PRINT"}
    config_path = tmp_path / "current_tick_config.json"
    write_json(config_path, config)
    return dict(package=package, stage_app=app, config_path=config_path, hk_input=hk,
                output_root=tmp_path / "canary_output", stage_id=STAGE,
                _config=config, _rows=rows, _shared=shared)


def arguments(inputs):
    return {key: value for key, value in inputs.items() if not key.startswith("_")}


def originals(inputs):
    return {str(path): tree(path) if path.is_dir() else path.read_bytes()
            for path in (inputs["package"], inputs["stage_app"], inputs["hk_input"],
                         inputs["config_path"], inputs["_shared"])}


def test_preparation_verifies_copies_and_preserves_all_originals(inputs):
    before = originals(inputs)
    result = tool().run_canary(**arguments(inputs))
    assert result["status"] == "PREPARED", result
    assert result["executed"] is False
    assert result["input_bytes_unchanged"] is True
    output = inputs["output_root"]
    prepared = json.loads((output / "config.json").read_text())
    for name in ("candidate_acquisition_root", "v4_research_data_root", "v4_morning_news_root", "python_path", "api_token"):
        assert prepared[name] == inputs["_config"][name]
    for name, dirname in (("raw_root", "raw"), ("selection_root", "selection"), ("receipt_root", "receipts")):
        assert prepared[name] == str(output / dirname)
    assert prepared["hk_current_day_research_root"] == str(output / "hk_input")
    assert prepared["shared_data_root"] == str(output / "shared_data")
    assert (output / "shared_data/scripts/live_acquisition/pytdx_hq.py").read_bytes() == (inputs["stage_app"] / HQ).read_bytes()
    assert (output / "shared_data/unchanged_dependency.py").read_bytes() == b"PRESERVED = True\n"
    assert not any((output / "shared_data" / name).exists() for name in (".git", ".venv", "__pycache__"))
    assert (output / "hk_input/CURRENT_DAY_RESEARCH_PIN.json").read_bytes() == (inputs["package"] / "CURRENT_DAY_RESEARCH_PIN.json").read_bytes()
    assert originals(inputs) == before
    assert not (output / "result.json").exists()
    assert "SYNTHETIC_SECRET_MUST_NOT_PRINT" not in json.dumps(result)


def test_candidate_shared_after_root_is_used_directly(inputs):
    shared = inputs["stage_app"] / "upstreams/v3_shared_data"
    config = dict(inputs["_config"], shared_data_root=str(shared))
    write_json(inputs["config_path"], config)
    before = originals(inputs)
    result = tool().run_canary(**arguments(inputs))
    assert result["status"] == "PREPARED", result
    assert result["shared_source"]["copied"] is False
    assert result["shared_source"]["effective_root"] == str(shared)
    assert result["shared_source"]["effective_hq_sha256"] == sha256((shared / "scripts/live_acquisition/pytdx_hq.py").read_bytes()).hexdigest()
    assert not (inputs["output_root"] / "shared_data").exists()
    assert originals(inputs) == before


@pytest.mark.parametrize("changed", ["app", "package_after", "hk_file", "shared_hq", "pin_date"])
def test_sha_or_date_mismatch_fails_before_output_creation(inputs, changed):
    if changed == "app":
        path = inputs["stage_app"] / "stage_center/runner.py"
    elif changed == "package_after":
        path = inputs["package"] / "after/stage/stage_center/runner.py"
    elif changed == "hk_file":
        path = inputs["hk_input"] / "receipt.json"
    elif changed == "shared_hq":
        path = inputs["_shared"] / "scripts/live_acquisition/pytdx_hq.py"
    else:
        path = inputs["package"] / "CURRENT_DAY_RESEARCH_PIN.json"
        pin = json.loads(path.read_text()); pin["captured_at"] = "2026-10-08T15:38:41+08:00"
        write_json(path, pin)
        path = None
    if path is not None:
        path.write_bytes(path.read_bytes() + b" ")
    before = originals(inputs)
    result = tool().run_canary(**arguments(inputs))
    assert result["status"] == "PREFLIGHT_FAILED", result
    assert result["errors"]
    assert not inputs["output_root"].exists()
    assert originals(inputs) == before


@pytest.mark.parametrize("stage", ["STAGE_0925", "STAGE_1545_1555"])
def test_non_minute_stage_never_creates_output(inputs, stage):
    args = arguments(inputs); args["stage_id"] = stage
    result = tool().run_canary(**args)
    assert result["status"] == "PREFLIGHT_FAILED"
    assert not inputs["output_root"].exists()


def test_cli_prepare_does_not_emit_config_credentials(inputs):
    assert SCRIPT.is_file(), "current research canary driver is not implemented"
    args = [sys.executable, "-B", str(SCRIPT)]
    for key, value in arguments(inputs).items():
        option = "--config" if key == "config_path" else "--" + key.replace("_", "-")
        args += [option, str(value)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["status"] == "PREPARED"
    assert "SYNTHETIC_SECRET_MUST_NOT_PRINT" not in result.stdout + result.stderr


def bridge_hook(directory, rows):
    directory.mkdir()
    script = '''from types import SimpleNamespace
from stage_center import live_collectors as bridge
ROWS = REPLACE_ROWS
def load_bridge(root, name):
    if name != "scripts.live_acquisition.pytdx_exhq":
        raise AssertionError("unexpected external bridge")
    def collect(python_path, day, stage, codes, **kwargs):
        assert day == "20261009" and stage == "STAGE_0930_0935"
        assert len(codes) == 12
        return SimpleNamespace(status="READ_OK" if ROWS else "READ_FAILED", rows=ROWS,
            cannot_confirm=(), requested_rows=12, missing_symbols=(), source_evidence=("fixture=EXTERNAL_PYTDX_IO_ONLY",))
    return SimpleNamespace(collect_pytdx_exhq_minute=collect)
bridge._load_shared_module = load_bridge
'''
    (directory / "sitecustomize.py").write_text(script.replace("REPLACE_ROWS", repr(rows)))


@pytest.mark.parametrize("quote_count", [12, 0])
def test_execute_invokes_real_owner_and_reports_same_run_without_false_success(inputs, monkeypatch, quote_count):
    quotes = [{"batch_index": index, "code": row["code"], "name": row["name"],
               "update_time": "2026-10-09 09:35:00", "last_price": 10.0 + index,
               "open_price": 10.0, "high_price": 12.0 + index, "low_price": 9.0,
               "prev_close_price": 10.0, "turnover": 20000000.0 + index, "volume": 500.0,
               "bid_price": None, "ask_price": None, "bid_vol": None, "ask_vol": None,
               "window_start": "2026-10-09 09:30:00", "window_end": "2026-10-09 09:35:00",
               "bar_count": 5, "temporal_cutoff_safe": True}
              for index, row in enumerate(inputs["_rows"][:quote_count], 1)]
    hook = inputs["package"].parent / "external_io_fixture"
    bridge_hook(hook, quotes)
    monkeypatch.setenv("PYTHONPATH", str(hook))
    before = originals(inputs)
    result = tool().run_canary(**arguments(inputs), execute=True)
    expected = "RESEARCH_ROWS_WRITTEN" if quote_count else "EXECUTED_NO_HK_SELECTION"
    assert result["status"] == expected, result
    assert result["executed"] is True
    assert result["input_bytes_unchanged"] is True
    assert originals(inputs) == before
    owner = json.loads((inputs["output_root"] / "result.json").read_text())
    assert owner["execution_origin"] == "CURRENT_DAY_RESEARCH_REPLAY"
    assert owner["dispatch_mode"] == "RECOVERY"
    assert owner["natural_verified"] is False
    assert owner["RESEARCH_ONLY"] is True
    assert owner["mode"] == "BACKFILL"
    assert all(owner[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    paths = result["output_paths"]
    receipt = Path(paths["owner_receipt"])
    assert receipt.is_file() and json.loads(receipt.read_text())["receipt_history"] == owner["receipt_history"]
    archived = Path(paths["owner_history_receipt"])
    assert sha256(archived.read_bytes()).hexdigest() == owner["receipt_history"]["sha256"]
    assert json.loads(archived.read_text())["execution_origin"] == "CURRENT_DAY_RESEARCH_REPLAY"
    assert result["evaluated_at"].endswith("09:35:05+08:00")
    assert result["selected_rows"]["HK_CONNECT"] == (10 if quote_count else 0)
    if quote_count:
        bound = owner["selection_artifacts"]["HK_CONNECT"]
        artifact = Path(paths["selection_root"]) / bound["artifact_relative"]
        assert sha256(artifact.read_bytes()).hexdigest() == bound["artifact_bytes_sha256"]
