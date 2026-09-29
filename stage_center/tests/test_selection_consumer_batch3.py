from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import SelectionError, select_a_stage, select_hk_four_lane, publish_selection


def _a_row(code: str) -> dict[str, object]:
    return {
        "code": code,
        "first_open": 10.0,
        "last_close": 10.2,
        "high": 10.4,
        "low": 9.9,
        "amount": 1_000_000,
        "bar_count": 5,
        "expected_rows": 5,
        "formal_eligible": True,
    }


def _hk_row(code: str) -> dict[str, object]:
    return {
        "code": code,
        "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
        "platform_circular_market_cap_hkd_yi": 80.0,
        "offer_float_market_cap_hkd_yi": 15.0,
        "pct_chg": 4.0,
        "volume_ratio": 1.5,
        "turnover_hkd_yi": 0.2,
        "turnover_rate": 3.0,
        "stage_id": "STAGE_0930_0935",
    }


def _publish_both(root: Path) -> None:
    a = select_a_stage([_a_row("A.000001"), _a_row("A.000002")], "20260813", "STAGE_0930_0935", "a" * 64)
    hk = select_hk_four_lane([_hk_row("HK.00001")], "20260813", "STAGE_0930_0935", "b" * 64)
    publish_selection(root, a, market="A_SHARE")
    publish_selection(root, hk, market="HK_CONNECT")


def test_consumer_projects_verified_markets_without_writes(tmp_path: Path) -> None:
    _publish_both(tmp_path)
    before = {path.relative_to(tmp_path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*") if path.is_file()}
    response = StageSelectionConsumer(tmp_path).get("20260813", "STAGE_0930_0935")
    after = {path.relative_to(tmp_path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after
    assert response["response_source"] == "SHARED_STAGE_CENTER"
    assert response["write_performed"] is False
    assert response["status"] == "READY"
    assert response["artifact_id"]
    assert set(response["markets"]) == {"A_SHARE", "HK_CONNECT"}
    assert response["markets"]["A_SHARE"]["coverage_ratio"] == 1.0
    assert [row["code"] for row in response["markets"]["A_SHARE"]["rows"]] == ["A.000001", "A.000002"]
    assert response["markets"]["A_SHARE"]["rows"][0]["rank"] == 1
    assert [row["order"] for row in response["markets"]["A_SHARE"]["rows"]] == [1, 2]


def test_consumer_ensure_is_read_only_and_has_no_producer_path(tmp_path: Path) -> None:
    _publish_both(tmp_path)
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    response = StageSelectionConsumer(tmp_path).ensure("20260813", "STAGE_0930_0935")
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert before == after
    assert response["write_performed"] is False
    assert response["ensure_status"] == "READ_ONLY_VERIFIED"


def test_consumer_keeps_rows_when_one_verified_lane_cannot_confirm(tmp_path: Path) -> None:
    """A valid zero-row lane is partial evidence, not an invalid bundle."""
    a = select_a_stage(
        [_a_row(f"A.{index:06d}") for index in range(10)],
        "20260813",
        "STAGE_0930_0935",
        "a" * 64,
        requested_rows=10,
    )
    hk = select_hk_four_lane(
        [],
        "20260813",
        "STAGE_0930_0935",
        "b" * 64,
        source_status="CANNOT_CONFIRM",
        requested_rows=10,
        cannot_confirm=["HK exact-date input unavailable"],
    )
    publish_selection(tmp_path, a, market="A_SHARE")
    publish_selection(tmp_path, hk, market="HK_CONNECT")

    response = StageSelectionConsumer(tmp_path).get("20260813", "STAGE_0930_0935")

    assert response["status"] == "PARTIAL_WITH_ROWS"
    assert response["markets"]["A_SHARE"]["selected_rows"] == 10
    assert response["markets"]["HK_CONNECT"]["status"] == "CANNOT_CONFIRM"
    assert response["markets"]["HK_CONNECT"]["artifact_id"]
    assert response["cannot_confirm"] == []


@pytest.mark.parametrize("mutation", ["missing", "tamper"])
def test_consumer_missing_and_tamper_have_identical_cannot_confirm_response(tmp_path: Path, mutation: str) -> None:
    _publish_both(tmp_path)
    latest = json.loads((tmp_path / "selection_latest.json").read_text(encoding="utf-8"))
    entry = latest["entries"]["20260813/STAGE_0930_0935/HK_CONNECT"]
    artifact = tmp_path / entry["artifact_relative"]
    if mutation == "missing":
        artifact.unlink()
    else:
        artifact.write_bytes(artifact.read_bytes() + b"tamper\n")
    response = StageSelectionConsumer(tmp_path).get("20260813", "STAGE_0930_0935")
    assert response["status"] == "PARTIAL_WITH_ROWS"
    assert response["cannot_confirm"] == ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"]
    assert response["markets"]["HK_CONNECT"]["status"] == "CANNOT_CONFIRM"
    assert response["markets"]["HK_CONNECT"]["rows"] == []
    assert response["markets"]["A_SHARE"]["selected_rows"] == 2
    assert response["write_performed"] is False


def test_consumer_defaults_to_scheduled_market_and_rejects_unknown_stage(tmp_path: Path) -> None:
    _publish_both(tmp_path)
    response = StageSelectionConsumer(tmp_path).get("20260813", "STAGE_0930_0935", markets=("A_SHARE",))
    assert set(response["markets"]) == {"A_SHARE"}
    with pytest.raises(ValueError, match="unknown stage"):
        StageSelectionConsumer(tmp_path).get("20260813", "STAGE_UNKNOWN")


@pytest.mark.parametrize("field", ["code", "rank"])
def test_consumer_duplicate_row_identity_is_fail_closed(tmp_path: Path, field: str) -> None:
    _publish_both(tmp_path)
    latest = json.loads((tmp_path / "selection_latest.json").read_text(encoding="utf-8"))
    entry = latest["entries"]["20260813/STAGE_0930_0935/A_SHARE"]
    manifest = tmp_path / entry["artifact_relative"].replace("artifact.csv", "manifest.json")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    rows = payload["selection_envelope"]["rows"]
    rows[1][field] = rows[0][field]
    # Mutation is intentionally left un-rehashed: the bad lane must remain
    # CANNOT_CONFIRM without erasing verified rows from the sibling lane.
    manifest.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    response = StageSelectionConsumer(tmp_path).get("20260813", "STAGE_0930_0935")
    assert response["status"] == "PARTIAL_WITH_ROWS"
    assert response["cannot_confirm"] == ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"]
    assert response["markets"]["A_SHARE"]["status"] == "CANNOT_CONFIRM"
    assert response["markets"]["A_SHARE"]["rows"] == []
