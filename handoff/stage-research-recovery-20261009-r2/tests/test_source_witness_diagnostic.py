"""Read-only diagnostic behavior against explicitly marked offline fixtures."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from test_source_witness_projection import DAY, SLOT, publish_fixture


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "diagnose_source_witness.py"
APP = Path(os.environ["STAGE_CHECK_APP"]).resolve()


def read_tool():
    assert SCRIPT.is_file(), "the read-only source witness diagnostic tool is missing"
    spec = importlib.util.spec_from_file_location("source_witness_diagnostic_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(root):
    return {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_diagnostic_happy_path_matches_original_validator_without_writes(tmp_path):
    witness, _, paths = publish_fixture(tmp_path)
    before = snapshot(tmp_path)
    result = read_tool().diagnose(tmp_path, DAY, SLOT, stage_cutoff="09:35:00")
    assert result["status"] == "MATCH"
    assert result["original_validator_error"] is None
    assert result["witness_raw_sha256"] == result["receipt_source_input_sha256"] == paths["source_input_sha256"]
    assert result["archive_base_sha256"] == result["reprojected_base_sha256"]
    assert result["differences"] == []
    assert result["inputs_changed_during_read"] == []
    assert all(Path(value["path"]).is_file() and len(value["sha256"]) == 64 for value in result["runtime_modules"].values())
    assert snapshot(tmp_path) == before


def test_diagnostic_preserves_mismatch_and_identifies_exact_changed_field(tmp_path):
    publish_fixture(tmp_path, mutate_archive=lambda archive: archive["stock_pool"][0].update(research_score=98.0))
    before = snapshot(tmp_path)
    result = read_tool().diagnose(tmp_path, DAY, SLOT, stage_cutoff="09:35:00")
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["original_validator_error"] == "RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH"
    assert result["store_validation_error"] is None
    assert result["archive_base_sha256"] != result["reprojected_base_sha256"]
    difference = next(d for d in result["differences"] if d["path"] == "/stock_pool/0/research_score")
    assert difference["archive"] == 98.0
    assert difference["reprojected"] == 97.0
    assert snapshot(tmp_path) == before


def test_diagnostic_missing_witness_stays_missing(tmp_path):
    witness, _, _ = publish_fixture(tmp_path)
    witness.unlink()
    before = snapshot(tmp_path)
    result = read_tool().diagnose(tmp_path, DAY, SLOT)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["original_validator_error"].startswith("RESEARCH_SOURCE_WITNESS_MISSING:")
    assert result["witness_raw_sha256"] is None
    assert result["cutoff_basis"] == "SOURCE_SLOT_END_NOT_STAGE_ACCEPTANCE"
    assert snapshot(tmp_path) == before
    assert not witness.exists()


def test_diagnostic_reports_raw_sha_failure_without_repair(tmp_path):
    witness, _, _ = publish_fixture(tmp_path)
    witness.write_bytes(witness.read_bytes() + b" ")
    before = snapshot(tmp_path)
    result = read_tool().diagnose(tmp_path, DAY, SLOT, stage_cutoff="09:35:00")
    assert result["original_validator_error"] == "RESEARCH_SOURCE_WITNESS_SHA_MISMATCH"
    assert result["witness_raw_sha256"] != result["receipt_source_input_sha256"]
    assert result["status"] == "CANNOT_CONFIRM"
    assert snapshot(tmp_path) == before


def test_cli_is_read_only_json_and_nonzero_on_original_mismatch(tmp_path):
    publish_fixture(tmp_path, mutate_archive=lambda archive: archive["stock_pool"][0].update(research_score=98.0))
    before = snapshot(tmp_path)
    assert SCRIPT.is_file(), "the read-only source witness diagnostic tool is missing"
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--research-root", str(tmp_path),
                             "--trade-date", DAY, "--slot", SLOT, "--stage-cutoff", "09:35:00"],
                            env={**os.environ, "PYTHONPATH": str(APP), "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 3

    parsed = json.loads(result.stdout)
    assert parsed["original_validator_error"] == "RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH"
    assert result.stderr == ""
    assert snapshot(tmp_path) == before


def test_malformed_manifest_shape_still_returns_read_only_json(tmp_path):
    publish_fixture(tmp_path)
    (tmp_path / "manifest.json").write_text("[]\n")
    before = snapshot(tmp_path)
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--research-root", str(tmp_path),
                             "--trade-date", DAY, "--slot", SLOT],
                            env={**os.environ, "PYTHONPATH": str(APP), "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 3
    parsed = json.loads(result.stdout)
    assert parsed["status"] == "CANNOT_CONFIRM"
    assert parsed["write_performed"] is False
    assert parsed.get("store_validation_error") or parsed.get("input_error")
    assert snapshot(tmp_path) == before
