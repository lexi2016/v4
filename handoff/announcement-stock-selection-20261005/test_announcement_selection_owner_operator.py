from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("prepare_announcement_selection_owner_operator.py")
SPEC = importlib.util.spec_from_file_location("announcement_selection_owner_operator", MODULE_PATH)
assert SPEC and SPEC.loader
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)


def _payloads(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    target = tmp_path / "owner" / "analysis.v1.json"
    target.parent.mkdir()
    candidate_path = task / "candidate.json"
    record = {"art_code": "AN-1", "factual_summary": "source fact"}
    manifest = {
        "target_trade_date": "20260930",
        "publication_date": "2026-09-29",
    }
    base = {
        "source_manifest": manifest,
        "source_manifest_sha256": "source-manifest-sha",
        "records": [record],
    }
    base["sha256"] = operator._product_sha(base)
    owner_bytes = (json.dumps(base, sort_keys=True) + "\n").encode()
    target.write_bytes(owner_bytes)

    extension = {
        "status": "VERIFIED",
        "base_product_sha256": base["sha256"],
        "article_count": 1,
        "article_decisions": [{"art_code": "AN-1"}],
    }
    extension["sha256"] = operator.canonical_sha(extension)
    candidate = dict(base)
    candidate["stock_selection"] = extension
    candidate["sha256"] = operator._product_sha(candidate)
    candidate_bytes = (json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n").encode()
    candidate_path.write_bytes(candidate_bytes)
    expected = {
        "owner_file_sha256": operator.raw_sha(owner_bytes),
        "owner_product_sha256": base["sha256"],
        "candidate_file_sha256": operator.raw_sha(candidate_bytes),
        "candidate_product_sha256": candidate["sha256"],
        "candidate_selection_sha256": extension["sha256"],
        "records_canonical_sha256": operator.canonical_sha([record]),
        "source_manifest_sha256": "source-manifest-sha",
        "target_trade_date": "20260930",
        "publication_date": "2026-09-29",
        "article_count": 1,
    }
    return task, target, candidate_path, owner_bytes, candidate_bytes, expected


def test_default_dry_run_checks_frozen_inputs_without_writing(tmp_path: Path):
    task, target, candidate, owner_bytes, candidate_bytes, expected = _payloads(tmp_path)
    result = operator.dry_run(target, candidate, expected)
    assert result["status"] == "DRY_RUN_READY"
    assert result["owner_state_write"] is False
    assert target.read_bytes() == owner_bytes
    assert candidate.read_bytes() == candidate_bytes
    assert not operator._backup_path(target, expected).exists()
    assert list(target.parent.glob(".*announcement-selection.lock")) == []


def test_apply_preserves_exact_backup_and_rollback_restores_original_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    task, target, candidate, owner_bytes, candidate_bytes, expected = _payloads(tmp_path)
    monkeypatch.setattr(operator, "OWNER_FILE", target)
    import_receipt = task / "import_receipt.json"
    rollback_receipt = task / "rollback_receipt.json"

    applied = operator.apply_import(target, candidate, import_receipt, expected)
    backup = operator._backup_path(target, expected)
    assert applied["status"] == "APPLIED"
    assert target.read_bytes() == candidate_bytes
    assert backup.read_bytes() == owner_bytes
    assert operator.raw_sha(backup.read_bytes()) == expected["owner_file_sha256"]

    rolled_back = operator.rollback_import(target, candidate, rollback_receipt, expected)
    assert rolled_back["status"] == "ROLLED_BACK"
    assert target.read_bytes() == owner_bytes
    assert backup.read_bytes() == owner_bytes
    assert json.loads(import_receipt.read_bytes())["owner_state_write"] is True
    assert json.loads(rollback_receipt.read_bytes())["backup_retained"] is True


def test_apply_refuses_unknown_owner_bytes_without_backup_or_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    task, target, candidate, _, _, expected = _payloads(tmp_path)
    monkeypatch.setattr(operator, "OWNER_FILE", target)
    target.write_bytes(target.read_bytes() + b" ")
    receipt = task / "import_receipt.json"

    with pytest.raises(operator.OperatorError, match="raw SHA changed"):
        operator.apply_import(target, candidate, receipt, expected)

    assert not operator._backup_path(target, expected).exists()
    assert not receipt.exists()
    assert target.read_bytes().endswith(b" ")


def test_rollback_refuses_unknown_installed_bytes_and_preserves_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    task, target, candidate, owner_bytes, _, expected = _payloads(tmp_path)
    monkeypatch.setattr(operator, "OWNER_FILE", target)
    operator.apply_import(target, candidate, task / "import_receipt.json", expected)
    backup = operator._backup_path(target, expected)
    backup_before = backup.read_bytes()
    target.write_bytes(target.read_bytes() + b"unknown")

    with pytest.raises(operator.OperatorError, match="not the exact candidate"):
        operator.rollback_import(target, candidate, task / "rollback_receipt.json", expected)

    assert backup.read_bytes() == backup_before == owner_bytes
    assert not (task / "rollback_receipt.json").exists()
