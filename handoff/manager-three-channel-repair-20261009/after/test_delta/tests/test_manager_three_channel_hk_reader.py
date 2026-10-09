"""Synthetic regressions for the 20261009 exact-date HK reader repair.

All artifacts below are invented test data under pytest temporary roots. These
tests do not reproduce a historical latest.json, attest market units, collect
quotes, or publish any business state.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
import pytest

from upstreams.v3_shared_data.shared_data import hk_security_master as owner
from upstreams.v3_shared_data.shared_data.hashing import canonical_bytes, sha256_json
from upstreams.v3_shared_data.shared_data.store import StoreError
from v4.manager_research import workspace_plan
from v4.manager_research.workspace_projection import build_workspace


DAY = "20261008"
TARGET = "20261009"
CUTOFF = "2026-10-09T08:00:00+08:00"
CODE = "HK.90001"
FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
COUNT_FIELDS = (
    "input_candidate_count", "history_complete_count", "history_pending_count",
    "strict_count", "near_candidate_count", "near_count", "selected_count",
    "panel_row_count", "panel_code_count",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _files(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): _sha(path.read_bytes())
            for path in root.rglob("*") if path.is_file()}


def _publish_master(root: Path, day: str = DAY, *, name: str = "Synthetic issuer A",
                    captured_at: str = "2026-10-08T18:01:00+08:00") -> dict:
    return owner.publish_hk_security_master(
        root, trade_date=day,
        rows=[{"code": CODE, "name": name, "outstanding_shares": 1000,
               "circular_market_val": 100000, "listing_date": "2010-01-01",
               "lot_size": 100, "sec_status": "NORMAL"}],
        universe_codes_sha256=sha256_json([CODE]), captured_at=captured_at,
    )


def _master_paths(root: Path, day: str = DAY) -> tuple[Path, Path, Path]:
    asset = root / "assets/hk_security_master"
    latest = json.loads((asset / "latest.json").read_bytes())
    entry = latest["entries"][day]
    manifest_path = asset / entry["manifest_relative"]
    manifest = json.loads(manifest_path.read_bytes())
    return manifest_path, asset / entry["receipt_relative"], asset / manifest["artifact_relative"]


def _panel(root: Path) -> None:
    sessions = workspace_plan.rebound_history_sessions(DAY)
    rows = [{
        "trade_date_compact": day, "code_norm": CODE, "name": "Synthetic panel issuer",
        "open": 99.0, "high": 100.0, "low": 98.0, "close": 99.0,
        "amount": 10.0, "trade": 100.0, "pre_close": 99.0,
    } for day in sessions["prior60"]]
    rows.append({
        "trade_date_compact": DAY, "code_norm": CODE, "name": "Synthetic panel issuer",
        "open": 80.0, "high": 80.0, "low": 79.0, "close": 80.0,
        "amount": 10.0, "trade": 150.0, "pre_close": 99.0,
    })
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_parquet(buffer, index=False)
    raw = buffer.getvalue()
    digest = _sha(raw)
    asset = root / "assets/hk_0_2"
    relative = f"panels/{DAY}-{digest[:12]}/hkconnect_vipdoc_daily_panel.parquet"
    path = asset / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    manifest = {
        "asset_schema_version": "v3_shared_data.hk_0_2_panel_asset.v2",
        "source_contract": "tdx_vipdoc_71_day+verified_zero_trade_repairs",
        "panel_relative": relative, "panel_sha256": digest, "panel_max_date": DAY,
        "panel_code_count": 1, "panel_rows": len(rows), "research_only": True,
        "manifest_prepared_at": "2026-10-08T18:00:00+08:00", **FLAGS,
    }
    manifest_path = path.parent / "manifest.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    (asset / "panel_latest.json").write_bytes(canonical_bytes({
        "manifest_relative": manifest_path.relative_to(asset).as_posix()}))


def _screen(root: Path) -> dict:
    return workspace_plan.read_rebound_screen(root, workspace_plan.plan_context(
        TARGET, now=datetime.fromisoformat(CUTOFF)))


def test_missing_exact_index_key_is_distinct_from_invalid_metadata_and_does_not_write(tmp_path):
    _publish_master(tmp_path, TARGET)
    latest_path = tmp_path / "assets/hk_security_master/latest.json"
    before = _files(tmp_path)

    with pytest.raises(StoreError) as caught:
        owner.load_verified_hk_security_master(tmp_path, DAY)

    assert getattr(caught.value, "reason_code", None) == "HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING"
    diagnostic = caught.value.diagnostic
    assert diagnostic == {
        "status": "MISSING", "reason_code": "HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING",
        "requested_trade_date": DAY, "validation_stage": "INDEX_LOOKUP",
        "latest_json_sha256": _sha(latest_path.read_bytes()), "entry_count": 1,
        "latest_entry_date": TARGET, "requested_entry_present": False,
    }
    assert _files(tmp_path) == before


def test_real_screen_preserves_exact_missing_reason_and_unknown_counts(tmp_path):
    _panel(tmp_path)
    _publish_master(tmp_path, TARGET)
    before = _files(tmp_path)

    screen = _screen(tmp_path)

    assert screen["status"] == "CANNOT_CONFIRM"
    assert screen["verified_session"] == DAY
    assert screen["main_screen_ready"] is False
    assert screen["gaps"] == [
        "SCREEN_SECURITY_MASTER_READ_FAILED:HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING"]
    diagnostic = screen["data_context"]["security_master_read"]
    assert diagnostic["requested_trade_date"] == DAY
    assert diagnostic["requested_entry_present"] is False
    assert diagnostic["validation_stage"] == "INDEX_LOOKUP"
    assert str(tmp_path) not in json.dumps(diagnostic)
    assert screen["coverage"]["counts_known"] is False
    assert all(screen["coverage"][field] is None for field in COUNT_FIELDS)
    assert screen["cards"] == screen["strict"] == screen["near"] == screen["pending"] == []
    assert screen["input_identity"] is None
    assert all(screen[key] is value for key, value in FLAGS.items())
    projected = build_workspace(TARGET, market_screen=screen,
        catalyst={"status": "NOT_MATERIALIZED", "target_trade_date": TARGET, "cards": []})
    assert projected["summary"]["market_screen_strict_count"] is None
    assert _files(tmp_path) == before


def test_exact_valid_master_reaches_real_screen_without_inventing_volume_unit_proof(tmp_path):
    _panel(tmp_path)
    published = _publish_master(tmp_path)
    # A later entry can coexist with the exact requested one; it is not a fallback.
    _publish_master(tmp_path, TARGET, name="Synthetic later issuer")
    before = _files(tmp_path)

    screen = _screen(tmp_path)

    assert screen["status"] == "READY_WITH_GAPS", screen["gaps"]
    assert screen["main_screen_ready"] is True
    assert screen["verified_session"] == DAY
    assert screen["authority"]["security_master"]["run_id"] == published["run_id"]
    assert screen["data_context"]["security_master_read"]["status"] == "VERIFIED"
    assert screen["data_context"]["security_master_read"]["requested_trade_date"] == DAY
    assert screen["data_context"]["security_master_read"]["requested_entry_present"] is True
    assert screen["coverage"]["counts_known"] is True
    assert screen["coverage"]["input_candidate_count"] == 1
    assert screen["coverage"]["history_pending_count"] == 1
    assert screen["coverage"]["selected_count"] == 0
    assert screen["cards"] == screen["strict"] == screen["near"] == []
    row = screen["pending"][0]
    assert row["name"] == "Synthetic issuer A"
    assert row["history_numeric_status"] == "KNOWN"
    assert row["volume_unit_status"] == "NOT_PROVEN"
    assert row["volume_flag_5d_ge_1_5"] is None
    assert row["oversold_flag"] is True
    assert all(screen[key] is value for key, value in FLAGS.items())
    assert _files(tmp_path) == before


def test_witness_keeps_one_verified_run_when_same_date_index_advances(tmp_path, monkeypatch):
    _publish_master(tmp_path)
    latest_path = tmp_path / "assets/hk_security_master/latest.json"
    first_index = latest_path.read_bytes()
    manifest_path, _, artifact_path = _master_paths(tmp_path)
    first_manifest = manifest_path.read_bytes()
    first_artifact = artifact_path.read_bytes()
    _publish_master(tmp_path, name="Synthetic issuer B")
    second_index = latest_path.read_bytes()
    latest_path.write_bytes(first_index)
    original_open = Path.open
    index_reads = 0

    def moving_index(path, mode="r", *args, **kwargs):
        nonlocal index_reads
        if path == latest_path and "r" in mode:
            index_reads += 1
            raw = first_index if index_reads == 1 else second_index
            return io.BytesIO(raw) if "b" in mode else io.StringIO(raw.decode("utf-8"))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", moving_index)
    witness, manifest = workspace_plan._screen_security_master_witness(tmp_path, DAY)

    assert witness["manifest_sha256"] == _sha(first_manifest)
    assert witness["artifact_sha256"] == _sha(first_artifact)
    assert witness["manifest_path"] == str(manifest_path)
    assert witness["run_id"] == manifest["run_id"]
    assert witness["names"][CODE]["name"] == "Synthetic issuer A"


def test_screen_witness_uses_supplied_upstream_owner_not_shadow_reader(tmp_path, monkeypatch):
    from v3_shared_data.shared_data import hk_security_master as shadow
    _publish_master(tmp_path)
    expected = Path(__file__).resolve().parents[1] / "upstreams/v3_shared_data/shared_data/hk_security_master.py"
    assert Path(owner.__file__).resolve() == expected

    def wrong_owner(*args, **kwargs):
        raise AssertionError("the shadow package is not the supplied authoritative reader")

    monkeypatch.setattr(shadow, "load_verified_hk_security_master", wrong_owner)
    witness, manifest = workspace_plan._screen_security_master_witness(tmp_path, DAY)
    assert witness["run_id"] == manifest["run_id"]
    assert witness["names"][CODE]["name"] == "Synthetic issuer A"


@pytest.mark.parametrize(("mutation", "reason"), [
    ("index_schema", "HK_SECURITY_MASTER_INDEX_SCHEMA_INVALID"),
    ("entry_shape", "HK_SECURITY_MASTER_ENTRY_INVALID"),
    ("receipt_date", "HK_SECURITY_MASTER_IDENTITY_OR_SAFETY_INVALID"),
    ("safety", "HK_SECURITY_MASTER_IDENTITY_OR_SAFETY_INVALID"),
    ("artifact_checksum", "HK_SECURITY_MASTER_ARTIFACT_CHECKSUM_MISMATCH"),
    ("manifest_checksum", "HK_SECURITY_MASTER_MANIFEST_CHECKSUM_MISMATCH"),
])
def test_invalid_exact_input_stays_invalid_with_bounded_reason(tmp_path, mutation, reason):
    _publish_master(tmp_path)
    asset = tmp_path / "assets/hk_security_master"
    manifest_path, receipt_path, artifact_path = _master_paths(tmp_path)
    if mutation in {"index_schema", "entry_shape"}:
        index = json.loads((asset / "latest.json").read_bytes())
        if mutation == "index_schema":
            index["schema_version"] = "synthetic-wrong-schema"
        else:
            index["entries"][DAY] = []
        (asset / "latest.json").write_bytes(canonical_bytes(index))
    elif mutation in {"receipt_date", "safety"}:
        receipt = json.loads(receipt_path.read_bytes())
        receipt["trade_date" if mutation == "receipt_date" else "orders_sent"] = (
            TARGET if mutation == "receipt_date" else True)
        receipt_path.write_bytes(canonical_bytes(receipt))
    elif mutation == "artifact_checksum":
        artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")
    else:
        manifest = json.loads(manifest_path.read_bytes())
        manifest["captured_at"] = "2026-10-08T18:02:00+08:00"
        manifest_path.write_bytes(canonical_bytes(manifest))
    before = _files(tmp_path)

    with pytest.raises(StoreError) as caught:
        owner.load_verified_hk_security_master(tmp_path, DAY)

    assert getattr(caught.value, "reason_code", None) == reason
    assert caught.value.diagnostic["status"] == "INVALID"
    assert str(tmp_path) not in str(caught.value)
    assert _files(tmp_path) == before


def test_valid_master_after_cutoff_still_cannot_enter_screen(tmp_path):
    _panel(tmp_path)
    _publish_master(tmp_path, captured_at="2026-10-09T08:01:00+08:00")

    screen = _screen(tmp_path)

    assert screen["status"] == "CANNOT_CONFIRM"
    assert screen["main_screen_ready"] is False
    assert screen["gaps"] == ["SCREEN_SECURITY_MASTER_AFTER_CUTOFF_OR_UNVERIFIED"]
    assert screen["coverage"]["counts_known"] is False
    assert all(screen["coverage"][field] is None for field in COUNT_FIELDS)
    assert screen["cards"] == []
