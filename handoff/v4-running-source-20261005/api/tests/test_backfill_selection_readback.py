from __future__ import annotations

import copy
import hashlib
import importlib
import json
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from stage_center.selection import SelectionStore


stage_api = importlib.import_module("apps.api.v35_api.app")


BACKFILL_RUN_ID = "a_share_historical_recovery_20260928_20260929_r3"
TRADE_DATE = "20260928"
STAGE_ID = "STAGE_0930_0935"


def _find_verification_fixtures_root() -> Path:
    for ancestor in Path(__file__).resolve().parents:
        fixtures_root = ancestor / "verification" / "fixtures"
        if (fixtures_root / "raw194_selection_envelope.json").is_file():
            return fixtures_root
    raise FileNotFoundError("read-only verification fixture root was not found")


VERIFICATION_FIXTURES_ROOT = _find_verification_fixtures_root()
FROZEN_ENVELOPE_PATH = VERIFICATION_FIXTURES_ROOT / "raw194_selection_envelope.json"
A_0925_MANIFEST_PATH = VERIFICATION_FIXTURES_ROOT / "a_share_stage_0925_selection_manifest.json"
HK_0930_MANIFEST_PATH = VERIFICATION_FIXTURES_ROOT / "hk_connect_stage_0930_selection_manifest.json"
A_1445_BACKFILL_RUN_ID = "a_share_historical_recovery_20260928_20260929_1445_witnessfix_r3"
def _find_recovery_root() -> Path:
    for ancestor in Path(__file__).resolve().parents:
        recovery_root = ancestor / "all_stage_recovery_20260928"
        if recovery_root.is_dir():
            return recovery_root
    raise FileNotFoundError("all_stage_recovery_20260928 evidence root was not found")


A_1445_SELECTION_ENVELOPE_PATH = (
    _find_recovery_root()
    / "A_SHARE"
    / "witness_fix"
    / "stage_result_1445_1500_r3"
    / "selection_envelope.json"
)


def _source_envelope() -> dict:
    return json.loads(FROZEN_ENVELOPE_PATH.read_text(encoding="utf-8"))


def _reviewed_manifest_envelope(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["selection_envelope"]


def _reviewed_a_1445_envelope() -> dict:
    # Use the exact independently reviewed stage envelope as immutable input.
    # SelectionStore writes only into pytest's temporary namespace.
    return json.loads(A_1445_SELECTION_ENVELOPE_PATH.read_text(encoding="utf-8"))


def _client(
    tmp_path: Path,
    *,
    include_reviewed_hk_backfill: bool = False,
    include_a_0925_backfill: bool = False,
    include_a_1445_backfill: bool = False,
    backfill_run_id: str = BACKFILL_RUN_ID,
    invalid_a_0925_source_sha: bool = False,
) -> tuple[TestClient, Path]:
    selection_root = tmp_path / "selection"
    backfill_root = selection_root / "backfill" / backfill_run_id
    SelectionStore(backfill_root).publish(_source_envelope(), market="A_SHARE")
    if include_a_0925_backfill:
        auction_envelope = _reviewed_manifest_envelope(A_0925_MANIFEST_PATH)
        if invalid_a_0925_source_sha:
            auction_envelope["raw_artifact_sha256"] = hashlib.sha256(b"unapproved-auction-source").hexdigest()
            auction_envelope.pop("run_id", None)
            auction_envelope.pop("artifact_id", None)
        SelectionStore(backfill_root).publish(auction_envelope, market="A_SHARE")
    if include_reviewed_hk_backfill:
        hk_envelope = _reviewed_manifest_envelope(HK_0930_MANIFEST_PATH)
        SelectionStore(backfill_root).publish(hk_envelope, market="HK_CONNECT")
    if include_a_1445_backfill:
        a_1445_root = selection_root / "backfill" / A_1445_BACKFILL_RUN_ID
        SelectionStore(a_1445_root).publish(_reviewed_a_1445_envelope(), market="A_SHARE")

    # A conflicting ordinary latest pointer proves that an explicit backfill
    # request reads the run-scoped child namespace, never the formal root.
    formal = copy.deepcopy(_source_envelope())
    formal.pop("run_id", None)
    formal.pop("artifact_id", None)
    formal["raw_artifact_sha256"] = hashlib.sha256(b"formal-latest-control").hexdigest()
    formal["source_evidence"] = [
        "FORMAL_LATEST_CONTROL_MUST_NOT_BE_READ",
        "formula=windows_v3_live_stage_quality_score",
    ]
    SelectionStore(selection_root).publish(formal, market="A_SHARE")

    app = create_app(
        data_root=tmp_path / "data",
        stage_center_selection_root=selection_root,
        manager_research_state_root=tmp_path / "manager-state",
        current_date=TRADE_DATE,
    )
    return TestClient(app), selection_root


def test_explicit_backfill_reads_exact_scoped_partial_watch_only_artifact(tmp_path: Path) -> None:
    client, selection_root = _client(tmp_path)
    latest = selection_root / "selection_latest.json"
    ordinary_latest_before = latest.read_bytes()

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": STAGE_ID,
            "backfill_run_id": BACKFILL_RUN_ID,
            "market": "A_SHARE",
            "limit": 50,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    market = payload["markets"]["A"]
    assert payload["trade_date"] == TRADE_DATE
    assert payload["stage"]["stage_id"] == STAGE_ID
    assert payload["mode"] == "BACKFILL"
    assert payload["backfill_run_id"] == BACKFILL_RUN_ID
    assert payload["selection_mode"] == "HISTORICAL_BACKFILL_READ_ONLY"
    assert payload["write_performed"] is False
    assert payload["RESEARCH_ONLY"] is True
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
    assert payload["execution_evidence"]["status"] == "EXECUTION_RECEIPT_ROOT_NOT_BOUND"
    assert "receipt_path" not in payload["execution_evidence"]
    assert market["selection_status"] == "PARTIAL_WITH_ROWS"
    assert market["source_status"] == "CANNOT_CONFIRM"
    assert len(market["rows"]) == 10
    assert all(row["trade_status"] == row["action_level"] == "WATCH_ONLY" for row in market["rows"])
    assert all(row["formal_eligible"] is False for row in market["rows"])
    assert "recovery_mode=HISTORICAL_BACKFILL" in market["source_evidence"]
    assert "actual_request_started_at=2026-09-29T01:55:22.910230+08:00" in market["source_evidence"]
    assert "actual_response_received_at=2026-09-29T01:55:27.982433+08:00" in market["source_evidence"]
    assert len(market["cannot_confirm"]) == 222
    assert "FORMAL_LATEST_CONTROL_MUST_NOT_BE_READ" not in market["source_evidence"]
    assert latest.read_bytes() == ordinary_latest_before


def test_backfill_identity_mismatch_never_falls_back_or_crosses_market(tmp_path: Path) -> None:
    client, _selection_root = _client(tmp_path)

    wrong_date = client.get(
        "/api/v3/workbench/stage",
        params={"date": "20260929", "stage": STAGE_ID, "backfill_run_id": BACKFILL_RUN_ID, "market": "A_SHARE"},
    )
    assert wrong_date.status_code == 404
    assert wrong_date.json()["detail"] == "backfill selection identity is unavailable"

    wrong_stage = client.get(
        "/api/v3/workbench/stage",
        params={"date": TRADE_DATE, "stage": "STAGE_0935_0940", "backfill_run_id": BACKFILL_RUN_ID, "market": "A_SHARE"},
    )
    assert wrong_stage.status_code == 409
    assert wrong_stage.json()["detail"] == "backfill selection identity is invalid"

    wrong_market = client.get(
        "/api/v3/workbench/stage",
        params={"date": TRADE_DATE, "stage": STAGE_ID, "backfill_run_id": BACKFILL_RUN_ID, "market": "HK_CONNECT"},
    )
    assert wrong_market.status_code == 404
    assert wrong_market.json()["detail"] == "backfill selection identity is unavailable"

    wrong_run = client.get(
        "/api/v3/workbench/stage",
        params={"date": TRADE_DATE, "stage": STAGE_ID, "backfill_run_id": "unapproved-run", "market": "A_SHARE"},
    )
    assert wrong_run.status_code == 404
    assert wrong_run.json()["detail"] == "backfill selection identity is unavailable"

    obsolete_link_run = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": STAGE_ID,
            "backfill_run_id": "20260928-a0935-recovery-20260929-r1",
            "market": "A_SHARE",
        },
    )
    assert obsolete_link_run.status_code == 404
    assert obsolete_link_run.json()["detail"] == "backfill selection identity is unavailable"


def test_explicit_hk_backfill_reads_only_the_scoped_hk_artifact(tmp_path: Path) -> None:
    run_id = "hk_connect_historical_recovery_20260928_20260929_r1"
    client, selection_root = _client(
        tmp_path,
        include_reviewed_hk_backfill=True,
        backfill_run_id=run_id,
    )
    latest = selection_root / "selection_latest.json"
    ordinary_latest_before = latest.read_bytes()

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": STAGE_ID,
            "backfill_run_id": run_id,
            "market": "HK_CONNECT",
            "limit": 50,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    hk = payload["markets"]["HK"]
    assert payload["trade_date"] == TRADE_DATE
    assert payload["stage"]["stage_id"] == STAGE_ID
    assert payload["mode"] == "BACKFILL"
    assert payload["backfill_run_id"] == run_id
    assert payload["market"] == "HK_CONNECT"
    assert payload["selection_mode"] == "HISTORICAL_BACKFILL_READ_ONLY"
    assert payload["write_performed"] is False
    assert payload["RESEARCH_ONLY"] is True
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
    assert hk["selection_status"] == "PARTIAL_WITH_ROWS"
    assert hk["source_status"] == "PARTIAL_WITH_ROWS"
    assert len(hk["rows"]) == 10
    assert Counter(row["trade_status"] for row in hk["rows"]) == {"NO_TRADE": 9, "WATCH_ONLY": 1}
    assert all(row["action_level"] == "NO_BUY" for row in hk["rows"])
    assert all(row["formal_eligible"] is False for row in hk["rows"])
    assert all(row["status"] == row["trade_status"] for row in hk["rows"])
    assert all(row["source_mode"] == "HK_CONNECT_FOUR_LANE" for row in hk["rows"])
    assert "due_status=HISTORICAL_BACKFILL" in hk["source_evidence"]
    assert "live_hkgainer_lane=NOT_ASSERTED" in hk["source_evidence"]
    assert latest.read_bytes() == ordinary_latest_before


def test_reviewed_a_0925_no_buy_null_prev_close_rows_remain_observation_only(tmp_path: Path) -> None:
    run_id = "a_share_historical_recovery_20260928_20260929_r3"
    client, _selection_root = _client(
        tmp_path,
        include_a_0925_backfill=True,
        backfill_run_id=run_id,
    )

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": "STAGE_0925",
            "backfill_run_id": run_id,
            "market": "A_SHARE",
            "limit": 50,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    market = payload["markets"]["A"]
    source_rows = _reviewed_manifest_envelope(A_0925_MANIFEST_PATH)["rows"]
    assert payload["market"] == "A_SHARE"
    assert payload["stage"]["stage_id"] == "STAGE_0925"
    assert payload["backfill_run_id"] == run_id
    assert market["selection_status"] == market["source_status"] == "PARTIAL_WITH_ROWS"
    assert market["selected_rows"] == payload["selected_a_rows"] == 10
    assert len(market["cannot_confirm"]) == 3
    assert all(
        row["trade_status"] == "WATCH_ONLY"
        and row["action_level"] == "NO_BUY"
        and row["formal_eligible"] is False
        and row["source_mode"] == "A_SHARE_AUCTION_TRANSACTION_STAGE_0925"
        and row["prev_close_price"] is None
        and row["current_change_pct"] is None
        and row["qmt_gap_pct"] is None
        for row in market["rows"]
    )
    expected_ranks_and_scores = [
        (row["code"], row.get("rank"), row.get("score", row.get("stage_score")))
        for row in source_rows
    ]
    projected_ranks_and_scores = [
        (row["code"], row.get("rank"), row.get("score", row.get("stage_score")))
        for row in market["rows"]
    ]
    assert projected_ranks_and_scores == expected_ranks_and_scores
    assert all(
        row["current_change_pct"] is None and row["qmt_gap_pct"] is None
        for row in payload["unified_rows"]
    )


def test_reviewed_a_0925_rejects_source_sha_drift(tmp_path: Path) -> None:
    run_id = "a_share_historical_recovery_20260928_20260929_r3"
    client, _selection_root = _client(
        tmp_path,
        include_a_0925_backfill=True,
        backfill_run_id=run_id,
        invalid_a_0925_source_sha=True,
    )

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": "STAGE_0925",
            "backfill_run_id": run_id,
            "market": "A_SHARE",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "backfill selection identity is invalid"


def test_reviewed_a_1445_witness_fix_uses_its_own_exact_run_namespace(tmp_path: Path) -> None:
    client, _selection_root = _client(tmp_path, include_a_1445_backfill=True)

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": "STAGE_1445_1500",
            "backfill_run_id": A_1445_BACKFILL_RUN_ID,
            "market": "A_SHARE",
            "limit": 50,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    market = payload["markets"]["A"]
    assert payload["trade_date"] == TRADE_DATE
    assert payload["stage"]["stage_id"] == "STAGE_1445_1500"
    assert payload["run_id"] == "run-62c7de976a7f879cd3615250"
    assert payload["backfill_run_id"] == A_1445_BACKFILL_RUN_ID
    assert market["artifact_id"] == "selection-62c7de976a7f879cd3615250"
    assert market["raw_artifact_sha256"] == "c0f2d34bf5d14dfcba325b1b6a61fd82009aa29c1375dbe126ea0fa8cd353ddc"
    assert market["selected_rows"] == 10
    assert len(market["cannot_confirm"]) == 302
    assert all(
        row["trade_status"] == row["action_level"] == "WATCH_ONLY"
        and row["formal_eligible"] is False
        for row in market["rows"]
    )


def test_reviewed_hk_no_buy_rows_keep_no_trade_status_and_require_exact_hk_evidence(tmp_path: Path) -> None:
    run_id = "hk_connect_historical_recovery_20260928_20260929_r1"
    client, _selection_root = _client(
        tmp_path,
        include_reviewed_hk_backfill=True,
        backfill_run_id=run_id,
    )

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": STAGE_ID,
            "backfill_run_id": run_id,
            "market": "HK_CONNECT",
            "limit": 50,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    hk = payload["markets"]["HK"]
    assert payload["market"] == "HK_CONNECT"
    assert payload["stage"]["stage_id"] == STAGE_ID
    assert payload["backfill_run_id"] == run_id
    assert hk["selection_status"] == hk["source_status"] == "PARTIAL_WITH_ROWS"
    assert hk["selected_rows"] == payload["selected_hk_rows"] == 10
    assert hk["cannot_confirm"] == ["HK_FUTU_HISTORICAL_ACTIVE_SNAPSHOT_UNAVAILABLE"]
    assert Counter(row["trade_status"] for row in hk["rows"]) == {"NO_TRADE": 9, "WATCH_ONLY": 1}
    assert all(
        row["action_level"] == "NO_BUY"
        and row["formal_eligible"] is False
        and row["status"] == row["trade_status"]
        and row["source_mode"] == "HK_CONNECT_FOUR_LANE"
        for row in hk["rows"]
    )
    assert "due_status=HISTORICAL_BACKFILL" in hk["source_evidence"]
    assert "hk_historical_active_snapshot=UNAVAILABLE_NO_ASOF_INTERFACE" in hk["source_evidence"]
    assert "live_hkgainer_lane=NOT_ASSERTED" in hk["source_evidence"]


def test_reviewed_hk_no_trade_status_cannot_be_rewritten_to_watch_only(tmp_path: Path, monkeypatch) -> None:
    run_id = "hk_connect_historical_recovery_20260928_20260929_r1"
    client, _selection_root = _client(
        tmp_path,
        include_reviewed_hk_backfill=True,
        backfill_run_id=run_id,
    )
    original_consumer = stage_api.StageSelectionConsumer

    class AlteredRowConsumer:
        def __init__(self, root: Path) -> None:
            self._consumer = original_consumer(root)

        def get(self, *args, **kwargs):
            payload = self._consumer.get(*args, **kwargs)
            row = payload["markets"]["HK_CONNECT"]["rows"][0]
            row["status"] = "WATCH_ONLY" if row["trade_status"] == "NO_TRADE" else "NO_TRADE"
            return payload

    monkeypatch.setattr(stage_api, "StageSelectionConsumer", AlteredRowConsumer)

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": STAGE_ID,
            "backfill_run_id": run_id,
            "market": "HK_CONNECT",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "backfill selection safety boundary is invalid"


def test_a_share_is_rejected_for_hk_only_stage(tmp_path: Path) -> None:
    client, _selection_root = _client(tmp_path)

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": "STAGE_1545_1555",
            "backfill_run_id": BACKFILL_RUN_ID,
            "market": "A_SHARE",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "backfill selection identity is unavailable"


def test_backfill_run_id_rejects_traversal_missing_and_symlinked_roots(tmp_path: Path) -> None:
    client, selection_root = _client(tmp_path)
    base = {"date": TRADE_DATE, "stage": STAGE_ID, "market": "A_SHARE"}

    traversal = client.get("/api/v3/workbench/stage", params={**base, "backfill_run_id": "../selection"})
    assert traversal.status_code == 422

    missing = client.get("/api/v3/workbench/stage", params={**base, "backfill_run_id": "missing-run"})
    assert missing.status_code == 404

    backfill_dir = selection_root / "backfill"
    target = tmp_path / "outside-run"
    target.mkdir()
    (backfill_dir / "symlink-run").symlink_to(target, target_is_directory=True)
    symlink = client.get("/api/v3/workbench/stage", params={**base, "backfill_run_id": "symlink-run"})
    assert symlink.status_code == 404
