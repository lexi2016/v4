from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import httpx
import pytest

from apps.api.v35_api.app import create_app
from infrastructure.preselection_pool_store import PreselectionPoolStore
from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import SelectionStore, publish_selection, select_a_stage, select_hk_four_lane


TRADE_DATE = "20260821"
STAGE_ID = "STAGE_0930_0935"
A_POOL_IDS = (
    "a_d1_premarket_pool",
    "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool",
)


def _a_source_row(code: str, name: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {
        "code": code,
        "first_open": 10.0,
        "last_close": 10.2,
        "high": 10.4,
        "low": 9.9,
        "amount": 1_000_000,
        "bar_count": 5,
        "expected_rows": 5,
    }
    if name is not None:
        row["name"] = name
    return row


def _hk_source_row(code: str = "HK.00001") -> dict[str, object]:
    return {
        "code": code,
        "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
        "platform_circular_market_cap_hkd_yi": 80.0,
        "offer_float_market_cap_hkd_yi": 15.0,
        "pct_chg": 4.0,
        "volume_ratio": 1.5,
        "turnover_hkd_yi": 0.2,
        "turnover_rate": 3.0,
        "stage_id": STAGE_ID,
    }


def _publish_a(root: Path, *, names: tuple[str | None, ...] = (None, None, None)) -> dict[str, Any]:
    rows = [_a_source_row(f"A.{index:06d}", name) for index, name in enumerate(names, start=1)]
    envelope = select_a_stage(rows, TRADE_DATE, STAGE_ID, "a" * 64)
    publish_selection(root, envelope, market="A_SHARE")
    return envelope


def _publish_hk(root: Path) -> None:
    envelope = select_hk_four_lane([_hk_source_row()], TRADE_DATE, STAGE_ID, "b" * 64)
    publish_selection(root, envelope, market="HK_CONNECT")


def _pool_row(code: str, name: str, *, target_date: str = TRADE_DATE) -> dict[str, object]:
    return {
        "symbol": code,
        "stock_code": code.removeprefix("A."),
        "stock_name": name,
        "name": name,
        "trade_date": TRADE_DATE,
        "target_date": target_date,
    }


def _pool_payload(
    pool_id: str,
    rows: list[Mapping[str, object]],
    *,
    trade_date: str = TRADE_DATE,
    source_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": "A",
        "status": "READY",
        "producer_id": "synthetic-name-authority-test",
        "source_role": "RAW_SOURCE",
        "source_path": "tests/synthetic-name-authority-source.json",
        "source_sha256": source_sha256 or hashlib.sha256(pool_id.encode()).hexdigest(),
        "rows": [dict(row) for row in rows],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _publish_pools(
    data_root: Path,
    *,
    names: tuple[str, ...] = ("甲公司", "乙公司", "丙公司"),
    pool_names: dict[str, tuple[str, ...]] | None = None,
    trade_date: str = TRADE_DATE,
    target_date: str = TRADE_DATE,
) -> dict[str, dict[str, object]]:
    store = PreselectionPoolStore(data_root)
    published: dict[str, dict[str, object]] = {}
    for pool_id in A_POOL_IDS:
        selected_names = (pool_names or {}).get(pool_id, names)
        rows = [
            _pool_row(f"A.{index:06d}", name, target_date=target_date)
            for index, name in enumerate(selected_names, start=1)
        ]
        payload = _pool_payload(pool_id, rows, trade_date=trade_date)
        store.materialize(payload)
        published[pool_id] = payload
    return published


def _consumer_fixture(
    tmp_path: Path,
    *,
    names: tuple[str | None, ...] = (None, None, None),
    pool_names: dict[str, tuple[str, ...]] | None = None,
    pool_trade_date: str = TRADE_DATE,
    pool_target_date: str = TRADE_DATE,
) -> tuple[StageSelectionConsumer, Path, Path, dict[str, Any]]:
    selection_root = tmp_path / "selection"
    data_root = tmp_path / "data"
    original = _publish_a(selection_root, names=names)
    _publish_pools(
        data_root,
        pool_names=pool_names,
        trade_date=pool_trade_date,
        target_date=pool_target_date,
    )
    consumer = StageSelectionConsumer(selection_root, a_name_pool_root=data_root)
    return consumer, selection_root, data_root, original


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_ready_overlay_fills_missing_names_only_and_preserves_selection_identity(tmp_path: Path) -> None:
    consumer, selection_root, _data_root, _original = _consumer_fixture(
        tmp_path, names=(None, "已有名", None)
    )
    before = _file_hashes(selection_root)
    verified = SelectionStore(selection_root).read_verified(TRADE_DATE, STAGE_ID, "A_SHARE")
    response = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))
    after = _file_hashes(selection_root)
    market = response["markets"]["A_SHARE"]

    assert before == after
    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["name_authority_source"] == "A_CANONICAL_PRESELECTION_POOLS"
    assert market["name_authority_pool_ids"] == list(A_POOL_IDS)
    assert market["name_authority_applied_count"] == 2
    assert market["name_authority_missing_count"] == 0
    assert market["name_authority_receipt_sha256"]
    assert market["name_authority_selector_sha256"]
    assert market["name_authority_source_sha256"]
    assert market["name_authority_selector_sha_source"] == "CANONICAL_PRESELECTION_POOL_ARTIFACTS"
    assert [row["name"] for row in market["rows"]] == ["甲公司", "已有名", "丙公司"]
    assert [row["stock_name"] for row in market["rows"]] == ["甲公司", "已有名", "丙公司"]
    assert market["artifact_id"] == verified["artifact_id"]
    assert market["run_id"] == verified["run_id"]
    assert market["algorithm_sha256"] == verified["algorithm_sha256"]
    assert market["raw_artifact_sha256"] == verified["raw_artifact_sha256"]
    assert market["selection_status"] == verified["selection_status"]
    assert [
        (row["code"], row["order"], row["rank"], row["score"], row["status"], row["formal_eligible"])
        for row in market["rows"]
    ] == [
        (row["code"], index, row["rank"], row["score"], row["status"], row["formal_eligible"])
        for index, row in enumerate(verified["rows"], start=1)
    ]


def test_authority_reads_all_four_pools_once_and_caches_exact_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer, _selection_root, _data_root, _original = _consumer_fixture(tmp_path)
    original_read_pool = PreselectionPoolStore.read_pool_snapshot
    calls: list[tuple[str, str]] = []

    def counted_read_pool(
        self: PreselectionPoolStore, trade_date: str, pool_id: str
    ) -> dict[str, Any]:
        calls.append((trade_date, pool_id))
        return original_read_pool(self, trade_date, pool_id)

    monkeypatch.setattr(PreselectionPoolStore, "read_pool_snapshot", counted_read_pool)
    first = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))
    second = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))

    assert first["markets"]["A_SHARE"]["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert second["markets"]["A_SHARE"]["rows"][0]["name"] == "甲公司"
    assert calls == [(TRADE_DATE, pool_id) for pool_id in A_POOL_IDS]


def test_authority_normalizes_code_forms_and_name_whitespace(tmp_path: Path) -> None:
    consumer, _selection_root, _data_root, _original = _consumer_fixture(
        tmp_path,
        pool_names={pool_id: ("新 希 望", "乙公司", "丙公司") for pool_id in A_POOL_IDS},
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["rows"][0]["name"] == "新希望"
    assert market["rows"][0]["stock_name"] == "新希望"


@pytest.mark.parametrize(
    "bad_aliases, expected_error",
    [
        (
            {"symbol": "A.000001", "stock_code": "000002", "ts_code": "000001.SZ"},
            "code alias conflict",
        ),
        ({"symbol": "garbage000001"}, "code alias is invalid"),
    ],
)
def test_authority_rejects_conflicting_or_embedded_code_aliases(
    tmp_path: Path, bad_aliases: dict[str, str], expected_error: str
) -> None:
    selection_root = tmp_path / "selection"
    data_root = tmp_path / "data"
    original = _publish_a(selection_root)
    store = PreselectionPoolStore(data_root)
    for pool_id in A_POOL_IDS:
        first_row = {
            "name": "污染名",
            "stock_name": "污染名",
            "trade_date": TRADE_DATE,
            "target_date": TRADE_DATE,
            **bad_aliases,
        }
        rows = [first_row, _pool_row("A.000002", "乙公司"), _pool_row("A.000003", "丙公司")]
        store.materialize(_pool_payload(pool_id, rows))

    consumer = StageSelectionConsumer(selection_root, a_name_pool_root=data_root)
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert expected_error in str(market["name_authority_error"])
    assert market["selection_status"] == original["selection_status"]
    assert all(row["name"] is None for row in market["rows"])


def test_missing_canonical_pool_is_isolated_without_changing_selection_fields(tmp_path: Path) -> None:
    consumer, selection_root, data_root, original = _consumer_fixture(tmp_path)
    before = _file_hashes(selection_root)
    (data_root / "preselection_pools" / TRADE_DATE / f"{A_POOL_IDS[-1]}.json").unlink()
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["name_authority_pool_status"] == "PARTIAL_SOURCE_SET"
    assert market["name_authority_verification_status"] == "CANNOT_CONFIRM"
    assert market["name_authority_pool_ids"] == list(A_POOL_IDS[:-1])
    assert market["name_authority_unverified_pool_ids"] == [A_POOL_IDS[-1]]
    missing_pool_audit = market["name_authority_pool_audit"][A_POOL_IDS[-1]]
    assert missing_pool_audit["status"] == "MISSING"
    assert missing_pool_audit["verification_status"] == "CANNOT_CONFIRM"
    assert market["name_authority_applied_count"] == 3
    assert market["name_authority_missing_count"] == 0
    missing_pool_summary = json.loads(
        str(market["name_authority_error"]).removeprefix("NAME_POOL_AUDIT:")
    )
    assert missing_pool_summary["verification_status"] == "CANNOT_CONFIRM"
    assert missing_pool_summary["unverified_pools"][A_POOL_IDS[-1]]["status"] == "MISSING"
    assert "POOL_ARTIFACT_MISSING" in str(market["name_authority_error"])
    assert market["selection_status"] == original["selection_status"]
    assert [(row["name"], row["stock_name"]) for row in market["rows"]] == [
        ("甲公司", "甲公司"), ("乙公司", "乙公司"), ("丙公司", "丙公司")
    ]
    assert _file_hashes(selection_root) == before


def test_wrong_pool_row_target_date_fails_closed(tmp_path: Path) -> None:
    consumer, _selection_root, _data_root, original = _consumer_fixture(
        tmp_path, pool_target_date="20260820"
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert "target_date mismatch" in str(market["name_authority_error"])
    assert market["selection_status"] == original["selection_status"]
    assert all(row["name"] is None for row in market["rows"])


def test_wrong_pool_date_is_not_used_as_requested_date(tmp_path: Path) -> None:
    consumer, _selection_root, _data_root, original = _consumer_fixture(
        tmp_path, pool_trade_date="20260820"
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["selection_status"] == original["selection_status"]
    assert all(row["name"] is None for row in market["rows"])


def test_pool_manifest_or_receipt_sha_mismatch_isolates_that_pool(tmp_path: Path) -> None:
    consumer, _selection_root, data_root, original = _consumer_fixture(tmp_path)
    artifact = data_root / "preselection_pools" / TRADE_DATE / f"{A_POOL_IDS[0]}.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["rows"][0]["stock_name"] = "篡改名称"
    artifact.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["name_authority_pool_status"] == "PARTIAL_SOURCE_SET"
    assert market["name_authority_verification_status"] == "CANNOT_CONFIRM"
    assert market["name_authority_pool_ids"] == list(A_POOL_IDS[1:])
    isolated_pool_audit = market["name_authority_pool_audit"][A_POOL_IDS[0]]
    assert isolated_pool_audit["status"] == "ISOLATED"
    assert isolated_pool_audit["verification_status"] == "CANNOT_CONFIRM"
    assert "ISOLATED" in str(market["name_authority_error"])
    assert market["name_authority_applied_count"] == 3
    assert market["selection_status"] == original["selection_status"]
    assert [row["name"] for row in market["rows"]] == ["甲公司", "乙公司", "丙公司"]


def test_pool_source_sha_mismatch_in_receipt_isolates_that_pool(tmp_path: Path) -> None:
    consumer, _selection_root, data_root, original = _consumer_fixture(tmp_path)
    receipt = data_root / "preselection_pools" / TRADE_DATE / "receipts" / f"{A_POOL_IDS[0]}.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["source_sha256"] = "f" * 64
    receipt.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["name_authority_pool_ids"] == list(A_POOL_IDS[1:])
    audit = json.loads(str(market["name_authority_error"]).removeprefix("NAME_POOL_AUDIT:"))
    assert "receipt" in audit["unverified_pools"][A_POOL_IDS[0]]["reason"]
    assert market["name_authority_applied_count"] == 3
    assert market["selection_status"] == original["selection_status"]
    assert [row["name"] for row in market["rows"]] == ["甲公司", "乙公司", "丙公司"]


def test_conflicting_canonical_name_is_isolated_to_its_code(tmp_path: Path) -> None:
    conflict = {pool_id: ("甲公司", "乙公司", "丙公司") for pool_id in A_POOL_IDS}
    conflict[A_POOL_IDS[-1]] = ("冲突名称", "乙公司", "丙公司")
    consumer, selection_root, _data_root, original = _consumer_fixture(tmp_path, pool_names=conflict)
    before = _file_hashes(selection_root)
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["name_authority_conflicted_codes"] == ["A.000001"]
    assert market["name_authority_applied_count"] == 2
    assert market["name_authority_missing_count"] == 1
    assert market["rows"][0]["name"] is None
    assert [row["name"] for row in market["rows"][1:]] == ["乙公司", "丙公司"]
    assert "A.000001" in str(market["name_authority_error"])
    assert market["selection_status"] == original["selection_status"]
    assert _file_hashes(selection_root) == before


def test_shared_manifest_error_rejects_all_name_projection(tmp_path: Path) -> None:
    consumer, selection_root, data_root, original = _consumer_fixture(tmp_path)
    manifest = data_root / "preselection_pools" / TRADE_DATE / "manifest.json"
    manifest.write_text("{broken", encoding="utf-8")
    before = _file_hashes(selection_root)

    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["name_authority_verification_status"] == "CANNOT_CONFIRM"
    assert market["name_authority_pool_ids"] == []
    assert market["name_authority_applied_count"] == 0
    assert "SHARED_PRESELECTION_ROOT_OR_MANIFEST_CANNOT_CONFIRM" in str(
        market["name_authority_error"]
    )
    assert all(row["name"] is None and row["stock_name"] is None for row in market["rows"])
    assert market["run_id"] == original["run_id"]
    assert _file_hashes(selection_root) == before


def test_missing_code_keeps_blank_name_and_records_not_found(tmp_path: Path) -> None:
    partial = {pool_id: ("甲公司",) for pool_id in A_POOL_IDS}
    consumer, _selection_root, _data_root, original = _consumer_fixture(tmp_path, pool_names=partial)
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["name_authority_applied_count"] == 1
    assert market["name_authority_missing_count"] == 2
    assert market["rows"][0]["name"] == "甲公司"
    assert market["rows"][1]["name"] is None
    assert "NAME_AUTHORITY_CODE_NOT_FOUND" in market["cannot_confirm"]
    assert market["selection_status"] == original["selection_status"]


def test_overlay_does_not_read_authority_when_no_name_is_missing(tmp_path: Path) -> None:
    consumer, _selection_root, data_root, _original = _consumer_fixture(
        tmp_path, names=("已有一", "已有二", "已有三")
    )
    (data_root / "preselection_pools" / TRADE_DATE).rename(data_root / "preselection_pools" / "removed")
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "NOT_NEEDED"
    assert market["name_authority_applied_count"] == 0
    assert market["name_authority_missing_count"] == 0
    assert [row["name"] for row in market["rows"]] == ["已有一", "已有二", "已有三"]


def test_hk_rows_are_not_name_overlaid(tmp_path: Path) -> None:
    consumer, selection_root, _data_root, _original = _consumer_fixture(tmp_path)
    _publish_hk(selection_root)
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("HK_CONNECT",))["markets"]["HK_CONNECT"]

    assert "name_authority_status" not in market
    assert market["rows"][0].get("name") is None
    assert market["rows"][0]["code"] == "HK.00001"


def test_create_app_shared_mode_uses_canonical_pool_root_and_preserves_safety_flags(tmp_path: Path) -> None:
    selection_root = tmp_path / "selection"
    data_root = tmp_path / "data"
    _publish_a(selection_root, names=(None, None, None))
    _publish_hk(selection_root)
    _publish_pools(data_root)
    app = create_app(
        data_root=data_root,
        stage_center_selection_root=selection_root,
        current_date=TRADE_DATE,
    )

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/api/v3/stage-center/selection",
                params={"date": TRADE_DATE, "stage": STAGE_ID},
            )

    response = asyncio.run(request())
    assert response.status_code == 200
    payload = response.json()
    assert payload["markets"]["A"]["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert payload["markets"]["A"]["name_authority_source"] == "A_CANONICAL_PRESELECTION_POOLS"
    assert payload["markets"]["A"]["rows"][0]["name"] == "甲公司"
    assert payload["markets"]["HK"]["rows"][0]["code"] == "HK.00001"
    assert payload["selection_mode"] == "SHARED_STAGE_CENTER_READ_ONLY"
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


@pytest.mark.parametrize("binding_mode", ["argument", "environment"])
def test_create_app_reads_name_overlay_from_preselection_owner_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_mode: str,
) -> None:
    selection_root = tmp_path / "selection"
    consumer_data_root = tmp_path / "consumer-data"
    pool_root = tmp_path / "preselection-owner"
    _publish_a(selection_root, names=(None, None, None))
    _publish_hk(selection_root)
    _publish_pools(pool_root)

    if binding_mode == "argument":
        monkeypatch.setenv("V35_PRESELECTION_SOURCE_ROOT", str(consumer_data_root))
        preselection_source_root = pool_root
    else:
        monkeypatch.setenv("V35_PRESELECTION_SOURCE_ROOT", str(pool_root))
        preselection_source_root = None

    app = create_app(
        data_root=consumer_data_root,
        stage_center_selection_root=selection_root,
        current_date=TRADE_DATE,
        preselection_source_root=preselection_source_root,
    )

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/api/v3/stage-center/selection",
                params={"date": TRADE_DATE, "stage": STAGE_ID},
            )

    response = asyncio.run(request())
    assert response.status_code == 200
    market = response.json()["markets"]["A"]
    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["name_authority_applied_count"] == 3
    assert [row["name"] for row in market["rows"]] == ["甲公司", "乙公司", "丙公司"]
    verified = SelectionStore(selection_root).read_verified(TRADE_DATE, STAGE_ID, "A_SHARE")
    assert [
        (row["code"], row["order"], row["rank"], row["score"])
        for row in market["rows"]
    ] == [
        (row["code"], index, row["rank"], row["score"])
        for index, row in enumerate(verified["rows"], start=1)
    ]


def test_missing_first_pool_does_not_block_names_from_remaining_valid_pool(
    tmp_path: Path,
) -> None:
    consumer, selection_root, data_root, _original = _consumer_fixture(tmp_path)
    first_pool_artifact = (
        data_root / "preselection_pools" / TRADE_DATE / f"{A_POOL_IDS[0]}.json"
    )
    first_pool_artifact.unlink()

    verified = SelectionStore(selection_root).read_verified(
        TRADE_DATE, STAGE_ID, "A_SHARE"
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["name_authority_applied_count"] == 3
    assert [row["name"] for row in market["rows"]] == ["甲公司", "乙公司", "丙公司"]
    assert market["name_authority_pool_ids"] == list(A_POOL_IDS[1:])
    audit = json.loads(str(market["name_authority_error"]).removeprefix("NAME_POOL_AUDIT:"))
    assert audit["unverified_pools"][A_POOL_IDS[0]]["reason"] == "POOL_ARTIFACT_MISSING"
    assert set(audit["trio_raw_sha256"]) == set(A_POOL_IDS[1:])
    assert set(audit["trio_raw_sha256"][A_POOL_IDS[1]]) == {
        "artifact", "manifest", "receipt"
    }
    assert market["artifact_id"] == verified["artifact_id"]
    assert market["run_id"] == verified["run_id"]
    assert market["algorithm_sha256"] == verified["algorithm_sha256"]
    assert market["raw_artifact_sha256"] == verified["raw_artifact_sha256"]
    assert [
        (row["code"], row["order"], row["rank"], row["score"], row["status"], row["formal_eligible"])
        for row in market["rows"]
    ] == [
        (row["code"], index, row["rank"], row["score"], row["status"], row["formal_eligible"])
        for index, row in enumerate(verified["rows"], start=1)
    ]
