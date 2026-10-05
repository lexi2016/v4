from __future__ import annotations

import json
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from apps.api.v35_api.app import _APPROVED_STAGE_BACKFILLS, create_app
from stage_center.selection import SelectionStore


TRADE_DATE = "20260925"
STAGE_ID = "STAGE_0930_0935"
MARKET = "HK_CONNECT"
BACKFILL_RUN_ID = "55742332ec504f119a54c42ce9cad3cd"
SELECTION_RUN_ID = "run-00ed21b8213cc63c7c1bebc3"
RUNNER_RECEIPT_SHA256 = "57c0ebadf08e372f2165b624d54b9287737451a9545cc11a9c2015e42c51deae"


def _client(tmp_path: Path, *, runner_receipt: str = "valid") -> TestClient:
    candidate_root = Path(__file__).resolve().parents[2]
    selection_manifest = candidate_root / "evidence" / "day25_selection_manifest.json"
    envelope = json.loads(selection_manifest.read_text(encoding="utf-8"))["selection_envelope"]
    selection_root = tmp_path / "selection"
    SelectionStore(selection_root / "backfill" / BACKFILL_RUN_ID).publish(
        envelope, market=MARKET
    )
    if runner_receipt not in {"valid", "missing", "wrong_sha"}:
        raise ValueError("unknown runner receipt fixture variant")
    if runner_receipt != "missing":
        source_receipt = candidate_root / "evidence" / "day25_runner_receipt.json"
        receipt_path = (
            selection_root.parent
            / "receipts"
            / "backfill"
            / BACKFILL_RUN_ID
            / TRADE_DATE
            / STAGE_ID
            / "receipt.json"
        )
        receipt_path.parent.mkdir(parents=True)
        receipt_bytes = source_receipt.read_bytes()
        if runner_receipt == "wrong_sha":
            altered = json.loads(receipt_bytes)
            altered["fixture_mutation"] = "sha-mismatch"
            receipt_bytes = json.dumps(altered, ensure_ascii=False, sort_keys=True).encode("utf-8")
        receipt_path.write_bytes(receipt_bytes)
    app = create_app(
        data_root=tmp_path / "data",
        stage_center_selection_root=selection_root,
        manager_research_state_root=tmp_path / "manager-state",
        current_date="20261005",
    )
    return TestClient(app)


def test_exact_20260925_hk_0930_backfill_binding_is_read_only(tmp_path: Path) -> None:
    legacy_key = (
        "20260928",
        "STAGE_0930_0935",
        "HK_CONNECT",
        "hk_connect_historical_recovery_20260928_20260929_r1",
    )
    assert _APPROVED_STAGE_BACKFILLS[legacy_key]["date"] == "20260928"
    client = _client(tmp_path)

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": STAGE_ID,
            "limit": 50,
            "backfill_run_id": BACKFILL_RUN_ID,
            "market": MARKET,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trade_date"] == TRADE_DATE
    assert payload["stage"]["stage_id"] == STAGE_ID
    assert payload["mode"] == "BACKFILL"
    assert payload["backfill_run_id"] == BACKFILL_RUN_ID
    assert payload["market"] == MARKET
    assert payload["selection_mode"] == "HISTORICAL_BACKFILL_READ_ONLY"
    assert payload["response_source"] == "SHARED_STAGE_CENTER_BACKFILL"
    assert payload["RESEARCH_ONLY"] is True
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
    assert payload["write_performed"] is False
    assert payload["run_id"] == SELECTION_RUN_ID

    market = payload["markets"]["HK"]
    assert market["artifact_id"] == "selection-00ed21b8213cc63c7c1bebc3"
    assert market["raw_artifact_sha256"] == "02229d41078a562a3863124dc799c37c1c087759744d4254b640873c1b5adefd"
    assert market["algorithm_sha256"] == "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506"
    assert market["selection_status"] == "PARTIAL_WITH_ROWS"
    assert market["source_status"] == "PARTIAL_WITH_ROWS"
    assert market["selected_rows"] is None
    assert market["source_rows"] == 96
    assert market["observation_count"] == 10
    assert market["runner_receipt_verified"] is True
    assert market["runner_receipt_status"] == "VERIFIED"
    assert market["runner_receipt_sha256"] == RUNNER_RECEIPT_SHA256
    assert market["recovery_provenance"]["runner_receipt_verified"] is True
    assert market["recovery_provenance"]["runner_receipt_sha256"] == RUNNER_RECEIPT_SHA256
    execution_evidence = payload["execution_evidence"]
    assert execution_evidence["status"] == "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED"
    assert execution_evidence["receipt_sha256_binding"]["status"] == "VERIFIED"
    assert execution_evidence["receipt_sha256_binding"]["sha256"] == RUNNER_RECEIPT_SHA256
    assert execution_evidence["markets"][MARKET]["selection_binding"] == "BOUND_TO_VERIFIED_SELECTION"
    assert payload["execution_evidence"]["execution_verified"] is False
    assert payload["execution_evidence"]["natural_verified"] is False
    assert "NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING" not in execution_evidence["cannot_confirm"]
    assert payload["selected_hk_rows"] is None
    assert len(market["cannot_confirm"]) == 12
    assert len(payload["unified_rows"]) == 10
    assert all(row["market"] == "HK" for row in payload["unified_rows"])
    assert all(row["formal_eligible"] is False for row in payload["unified_rows"])
    assert all(row["action_level"] == "NO_BUY" for row in payload["unified_rows"])


def test_20260925_binding_rejects_another_run_id(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": STAGE_ID,
            "limit": 50,
            "backfill_run_id": "another-run",
            "market": MARKET,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "backfill selection identity is unavailable"


@pytest.mark.parametrize("runner_receipt", ["missing", "wrong_sha"])
def test_20260925_binding_rejects_unverified_runner_receipt(
    tmp_path: Path, runner_receipt: str
) -> None:
    client = _client(tmp_path, runner_receipt=runner_receipt)

    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": TRADE_DATE,
            "stage": STAGE_ID,
            "limit": 50,
            "backfill_run_id": BACKFILL_RUN_ID,
            "market": MARKET,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "backfill runner receipt identity is invalid"
