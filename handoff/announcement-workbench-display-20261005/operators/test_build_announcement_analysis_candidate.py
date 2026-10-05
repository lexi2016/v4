from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


TASK = Path(__file__).resolve().parent
REVIEW = TASK / "review"
SCRIPT = TASK / "build_announcement_analysis_candidate.py"
CANDIDATE_ROOT = TASK / "r11_candidate_announcement_page_final2"
SOURCES_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_SELECTION_PATH_DIAG_20261005/announcement_understanding"
)
CANARY = TASK / "announcement_catalog_canary.json"
MOCK_LATEST = (
    REVIEW / "mock_api_state/workspace_announcements/20260930/"
    "eastmoney_date_catalog/20260929/latest.json"
)
SOURCE_CANDIDATE = TASK / "candidate_announcement_analysis_20260929_final.json"


def _state_root(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    latest = state / "workspace_announcements/20260930/eastmoney_date_catalog/20260929/latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_bytes(MOCK_LATEST.read_bytes())
    return state


def _run(state: Path, candidate: Path, receipt: Path) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--repo-root", str(CANDIDATE_ROOT),
        "--sources-root", str(SOURCES_ROOT),
        "--catalog-canary", str(CANARY),
        "--state-root", str(state),
        "--candidate-output", str(candidate),
        "--receipt-output", str(receipt),
    ]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(command, capture_output=True, text=True, env=env)


def test_candidate_output_inside_state_root_is_rejected_before_any_write(tmp_path: Path):
    state = _state_root(tmp_path)
    inside = state / "not-created/candidate.json"
    outside_receipt = tmp_path / "receipt.json"

    result = _run(state, inside, outside_receipt)

    assert result.returncode != 0
    assert "DRY_RUN_CANDIDATE_WITHIN_STATE_ROOT" in result.stderr
    assert not inside.parent.exists()
    assert not outside_receipt.exists()
    assert sorted(path.relative_to(state).as_posix() for path in state.rglob("*")) == [
        "workspace_announcements",
        "workspace_announcements/20260930",
        "workspace_announcements/20260930/eastmoney_date_catalog",
        "workspace_announcements/20260930/eastmoney_date_catalog/20260929",
        "workspace_announcements/20260930/eastmoney_date_catalog/20260929/latest.json",
    ]


def test_receipt_symlink_resolving_into_state_root_is_rejected(tmp_path: Path):
    state = _state_root(tmp_path)
    alias = tmp_path / "state-alias"
    alias.symlink_to(state, target_is_directory=True)
    outside_candidate = tmp_path / "candidate.json"
    inside_receipt = alias / "not-created/receipt.json"

    result = _run(state, outside_candidate, inside_receipt)

    assert result.returncode != 0
    assert "DRY_RUN_RECEIPT_WITHIN_STATE_ROOT" in result.stderr
    assert not inside_receipt.parent.exists()
    assert not outside_candidate.exists()


def test_identical_existing_product_compares_canonical_product_sha_not_raw_sha(tmp_path: Path):
    state = _state_root(tmp_path)
    target = state / "workspace_announcements/20260930/eastmoney_date_catalog/20260929/analysis.v1.json"
    target.write_bytes(SOURCE_CANDIDATE.read_bytes())
    candidate_file_sha = hashlib.sha256(SOURCE_CANDIDATE.read_bytes()).hexdigest()
    embedded_product_sha = json.loads(SOURCE_CANDIDATE.read_bytes())["sha256"]
    candidate_out = tmp_path / "review-candidate.json"
    receipt_out = tmp_path / "receipt.json"

    result = _run(state, candidate_out, receipt_out)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "DRY_RUN_READY"
    receipt = json.loads(receipt_out.read_bytes())
    assert receipt["derived_product_preexisted"] is True
    assert receipt["derived_product_prior_sha256"] == candidate_file_sha
    assert receipt["derived_product_prior_product_sha256"] == embedded_product_sha
    assert receipt["candidate_file_sha256"] == candidate_file_sha
    assert receipt["candidate_product_sha256"] == embedded_product_sha
    assert candidate_file_sha != embedded_product_sha
    assert target.read_bytes() == SOURCE_CANDIDATE.read_bytes()
