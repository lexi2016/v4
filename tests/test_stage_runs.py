from __future__ import annotations

import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from contracts.stages import FROZEN_STAGE_IDS
from domains.stages import StageRunner, _project_watch_only
from infrastructure.stage_store import StageStore
from ops.import_stage_input import import_stage_input


def _input(date: str, stage_id: str) -> dict:
    return {
        "schema_version": "v3_5.stage_input.v1",
        "trade_date": date,
        "stage_id": stage_id,
        "cutoff_reached": True,
        "market_status": {"A": "READY", "HK": "READY"},
        "rows": {
            "A": [
                {
                    "symbol": "A.000001",
                    "open_price": 11,
                    "last_price": 11,
                    "prev_close_price": 10,
                    "turnover": 200_000_000,
                    "pool_score": 100,
                    "recommendation_status": "WATCH_ONLY",
                }
            ],
            "HK": [
                {
                    "symbol": "HK.00001",
                    "pct_chg": 12,
                    "turnover_hkd_yi": 0.5,
                    "circular_market_cap_hkd_yi": 80,
                    "recommendation_status": "WATCH_ONLY",
                }
            ],
        },
        "source_evidence": [{"path": "imports/frozen-stage.json", "sha256": "a" * 64}],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }


def test_all_eight_stages_publish_verified_compatible_workbenches(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    runner = StageRunner(store)

    for stage_id in FROZEN_STAGE_IDS:
        store.import_input(_input("20260730", stage_id))
        result = runner.ensure("20260730", stage_id)
        assert result["ok"] is True
        assert result["ensure_status"] == "STAGE_RUN_COMPLETE"
        workbench = runner.read_workbench("20260730", stage_id, limit=1)
        assert workbench["schema_version"] == "v3_stage_workbench.v2"
        assert workbench["stage"]["stage_id"] == stage_id
        assert workbench["selected_total_rows"] == 2
        assert len(workbench["unified_rows"]) == 2
        assert {row["market"] for row in workbench["unified_rows"]} == {"A", "HK"}
        assert {row["recommendation_status"] for row in workbench["unified_rows"]} == {"WATCH_ONLY"}
        assert workbench["selection_mode"] == "V3_5_NATIVE_STAGE_SCORE_V1"
        assert workbench["stage_groups"][0]["rows"][0]["stage_score"] > 0
        assert workbench["stage_groups"][1]["rows"][0]["stage_rtdata_score"] > 0
        assert workbench["production_allowed"] is False
        assert workbench["buy_gate_updated"] is False
        assert workbench["orders_sent"] is False
        assert not str(workbench).lower().find("v3_system") >= 0


def test_stage_projection_preserves_legacy_top50_a_and_top10_hk_boundaries(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    payload = _input("20260730", "STAGE_1445_1500")
    payload["rows"]["A"] = [
        {
            **payload["rows"]["A"][0],
            "symbol": f"A.{index:06d}",
            "turnover": 100_000_000 + index,
        }
        for index in range(60)
    ]
    payload["rows"]["HK"] = [
        {
            **payload["rows"]["HK"][0],
            "symbol": f"HK.{index:05d}",
            "pct_chg": index,
        }
        for index in range(12)
    ]
    store.import_input(payload)

    StageRunner(store).ensure("20260730", "STAGE_1445_1500")
    workbench = StageRunner(store).read_workbench(
        "20260730",
        "STAGE_1445_1500",
        limit=50,
    )

    assert workbench["selected_a_rows"] == 50
    assert workbench["selected_hk_rows"] == 10


def test_native_0925_keeps_native_truth_and_isolates_legacy_reference_diagnostic(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    payload = _input("20260730", "STAGE_0925")
    payload["market_status"]["A"] = "CANNOT_CONFIRM"
    payload["rows"]["A"] = []
    payload["source_summary"] = {
        "requested_A": 147,
        "requested_HK": 100,
        "cannot_confirm": ["PYTDX_MINUTE_REPLAY_HAS_NO_CALL_AUCTION_EVIDENCE"],
    }
    store.import_input(payload)
    runner = StageRunner(store)
    runner.ensure("20260730", "STAGE_0925")
    native = runner.read_workbench("20260730", "STAGE_0925")
    reference = deepcopy(native)
    reference["markets"]["A"]["source_rows"] = 1
    reference["stage"]["display_status"] = "Legacy market source hit 1/3."
    store.import_reference_workbench(reference)

    workbench = runner.read_workbench("20260730", "STAGE_0925")

    assert workbench["selection_mode"] == "V3_5_NATIVE_STAGE_SCORE_V1"
    assert workbench["selected_a_rows"] == 0
    assert workbench["selected_hk_rows"] == 1
    assert workbench["markets"]["A"] == {
        "label": "A股",
        "candidate_count": 0,
        "source_rows": 0,
        "requested_rows": 147,
        "source_status": "CANNOT_CONFIRM",
        "data_level": "WATCH_ONLY",
    }
    assert "upstream pool 147" in workbench["stage"]["display_status"]
    assert "same-cutoff 09:25 evidence 0" in workbench["stage"]["display_status"]
    assert "candidate 0" in workbench["stage"]["display_status"]
    assert "selected 0" in workbench["stage"]["display_status"]
    assert "Legacy market source hit 1/3." not in workbench["stage"]["display_status"]
    assert workbench["legacy_reference_diagnostic"] == {
        "reference_available": True,
        "a_source_rows": 1,
    }


@pytest.mark.parametrize(
    ("cutoff_reached", "market_status", "expected_status"),
    [
        (False, {"A": "READY", "HK": "READY"}, "PENDING_CUTOFF_NOT_REACHED"),
        (True, {"A": "CLOSED", "HK": "CLOSED"}, "MARKET_CLOSED_NO_BUY"),
    ],
)
def test_native_0925_preserves_pending_and_closed_status_when_reference_exists(
    tmp_path,
    cutoff_reached,
    market_status,
    expected_status,
) -> None:
    store = StageStore(tmp_path / "data")
    payload = _input("20260730", "STAGE_0925")
    payload["cutoff_reached"] = cutoff_reached
    payload["market_status"] = market_status
    store.import_input(payload)
    runner = StageRunner(store)
    runner.ensure("20260730", "STAGE_0925")
    native = runner.read_workbench("20260730", "STAGE_0925")
    reference = deepcopy(native)
    reference["markets"]["A"]["source_rows"] = 1
    store.import_reference_workbench(reference)

    workbench = runner.read_workbench("20260730", "STAGE_0925")

    assert native["stage"]["status"] == expected_status
    assert workbench["stage"] == native["stage"]


@pytest.mark.parametrize(
    "malformed_reference",
    [
        {"markets": None},
        {"markets": {"A": None}},
        {"markets": {"A": {"source_rows": "1/3"}}},
    ],
)
def test_native_0925_handles_malformed_reference_as_invalid_diagnostic(
    tmp_path,
    monkeypatch,
    malformed_reference,
) -> None:
    store = StageStore(tmp_path / "data")
    payload = _input("20260730", "STAGE_0925")
    payload["market_status"]["A"] = "CANNOT_CONFIRM"
    payload["rows"]["A"] = []
    payload["source_summary"] = {
        "requested_A": 147,
        "cannot_confirm": ["PYTDX_MINUTE_REPLAY_HAS_NO_CALL_AUCTION_EVIDENCE"],
    }
    store.import_input(payload)
    runner = StageRunner(store)
    runner.ensure("20260730", "STAGE_0925")
    monkeypatch.setattr(
        store,
        "read_reference_workbench",
        lambda _trade_date, _stage_id: deepcopy(malformed_reference),
    )

    workbench = runner.read_workbench("20260730", "STAGE_0925")

    assert workbench["markets"]["A"]["requested_rows"] == 147
    assert workbench["markets"]["A"]["source_rows"] == 0
    assert workbench["markets"]["A"]["candidate_count"] == 0
    assert workbench["selected_a_rows"] == 0
    assert workbench["legacy_reference_diagnostic"] == {
        "reference_available": False,
        "status": "INVALID_REFERENCE",
    }


def test_post_open_native_materialization_is_not_overridden_by_migrated_reference(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    store.import_input(_input("20260730", "STAGE_0930_0935"))
    runner = StageRunner(store)
    runner.ensure("20260730", "STAGE_0930_0935")
    native = runner.read_workbench("20260730", "STAGE_0930_0935")
    reference = deepcopy(native)
    reference_a = next(row for row in reference["unified_rows"] if row["market"] == "A")
    reference_a.update({
        "current_change_pct": 4.113,
        "support_primary_price": 22.72,
        "pressure_price": 24.83,
        "invalidation_price": 22.72,
        "next_validation_time": "09:40",
    })
    reference["selection_mode"] = "MIGRATED_REFERENCE_WORKBENCH"
    store.import_reference_workbench(reference)

    workbench = runner.read_workbench("20260730", "STAGE_0930_0935")
    selected_a = next(row for row in workbench["unified_rows"] if row["market"] == "A")

    assert workbench["selection_mode"] == "V3_5_NATIVE_STAGE_SCORE_V1"
    assert workbench["response_source"] == "V3_5_NATIVE_STAGE_SNAPSHOT"
    assert workbench.get("reference_snapshot") is not True
    assert selected_a.get("support_primary_price") != 22.72
    assert workbench["production_allowed"] is False
    assert workbench["orders_sent"] is False


def test_post_open_migrated_reference_cannot_hide_native_a_share_rows(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    store.import_input(_input("20260730", "STAGE_1445_1500"))
    runner = StageRunner(store)
    runner.ensure("20260730", "STAGE_1445_1500")
    reference = deepcopy(runner.read_workbench("20260730", "STAGE_1445_1500"))
    reference["unified_rows"] = [
        row for row in reference["unified_rows"] if row["market"] != "A"
    ]
    reference["selected_a_rows"] = 0
    reference["selected_total_rows"] = reference["selected_hk_rows"]
    reference["markets"]["A"]["candidate_count"] = 0
    reference["selection_mode"] = "MIGRATED_REFERENCE_WORKBENCH"
    store.import_reference_workbench(reference)

    workbench = runner.read_workbench("20260730", "STAGE_1445_1500")

    assert workbench["selection_mode"] == "V3_5_NATIVE_STAGE_SCORE_V1"
    assert workbench["response_source"] == "V3_5_NATIVE_STAGE_SNAPSHOT"
    assert workbench["selected_a_rows"] == 1
    assert any(row["market"] == "A" for row in workbench["unified_rows"])


def test_stage_api_is_idempotent_but_failed_refresh_cannot_reuse_import(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    client = TestClient(create_app(data_root=store.root))
    missing = client.get(
        "/api/v3/workbench/stage",
        params={"date": "20260730", "stage": "STAGE_0925"},
    ).json()
    assert missing["ok"] is False
    assert missing["stage"]["status"] == "DATA_BLOCKED_INPUT_MISSING"
    assert missing["sidebar"]["cannot_confirm_items"]

    store.import_input(_input("20260730", "STAGE_0925"))
    first = client.post(
        "/api/v3/workbench/stage/ensure",
        params={"date": "20260730", "stage": "STAGE_0925"},
    ).json()
    second = client.post(
        "/api/v3/workbench/stage/ensure",
        params={"date": "20260730", "stage": "STAGE_0925"},
    ).json()
    forced = client.post(
        "/api/v3/workbench/stage/ensure",
        params={"date": "20260730", "stage": "STAGE_0925", "force": "true"},
    ).json()
    assert first["ensure_status"] == "STAGE_RUN_COMPLETE"
    assert second["ensure_status"] == "ALREADY_COMPLETE"
    # The API has a producer but no refreshable canonical pool in this
    # fixture. An explicit refresh must fail closed, not reuse imported input.
    assert forced["ensure_status"] == "STAGE_INPUT_REFRESH_BLOCKED"
    assert forced["ok"] is False
    assert first["run_id"] == second["run_id"]
    assert store.read_latest("20260730", "STAGE_0925")["run_id"] == first["run_id"]


def test_concurrent_duplicate_stage_run_publishes_one_verified_run(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    store.import_input(_input("20260730", "STAGE_0930_0935"))
    runner = StageRunner(store)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: runner.ensure("20260730", "STAGE_0930_0935"), range(4)))

    statuses = [result["ensure_status"] for result in results]
    assert statuses.count("STAGE_RUN_COMPLETE") == 1
    assert statuses.count("ALREADY_COMPLETE") == 3
    assert runner.read_workbench("20260730", "STAGE_0930_0935")["selected_total_rows"] == 2


def test_failed_projector_writes_failure_receipt_and_retry_recovers(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    store.import_input(_input("20260730", "STAGE_0935_0940"))

    def fail(_payload):
        raise RuntimeError("injected stage failure")

    failed = StageRunner(store, projector=fail).ensure("20260730", "STAGE_0935_0940")
    assert failed["ok"] is False
    assert failed["ensure_status"] == "STAGE_RUN_FAILED"
    assert store.read_latest("20260730", "STAGE_0935_0940") is None
    failure_path = store.root / failed["failure_receipt_path"]
    assert failure_path.is_file()
    assert json.loads(failure_path.read_text(encoding="utf-8"))["error_type"] == "RuntimeError"

    recovered = StageRunner(store).ensure("20260730", "STAGE_0935_0940")
    assert recovered["ensure_status"] == "STAGE_RUN_COMPLETE"
    assert StageRunner(store).read_workbench("20260730", "STAGE_0935_0940")["ok"] is True


def test_tampered_stage_artifact_fails_closed(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    store.import_input(_input("20260730", "STAGE_0940_0945"))
    result = StageRunner(store).ensure("20260730", "STAGE_0940_0945")
    artifact = store.root / result["artifact_path"]
    artifact.write_text("{}", encoding="utf-8")

    blocked = StageRunner(store).read_workbench("20260730", "STAGE_0940_0945")
    assert blocked["ok"] is False
    assert blocked["stage"]["status"] == "DATA_BLOCKED_ARTIFACT_INVALID"
    repaired = StageRunner(store).ensure("20260730", "STAGE_0940_0945", force=True)
    assert repaired["ensure_status"] == "FORCED_REMATERIALIZED"
    assert StageRunner(store).read_workbench("20260730", "STAGE_0940_0945")["ok"] is True


def test_stage_input_import_is_offline_idempotent_and_rejects_unsafe_rows(tmp_path) -> None:
    source = tmp_path / "stage.json"
    source.write_text(json.dumps(_input("20260730", "STAGE_0945_1030")), encoding="utf-8")
    first = import_stage_input(source, tmp_path / "data")
    assert import_stage_input(source, tmp_path / "data") == first
    with pytest.raises(ValueError, match="local"):
        import_stage_input("https://example.com/stage.json", tmp_path / "data")

    unsafe = _input("20260730", "STAGE_1300_1315")
    unsafe["rows"]["HK"][0]["meta"] = {"orders_sent": 1}
    with pytest.raises(ValueError):
        StageStore(tmp_path / "unsafe").import_input(unsafe)
    assert not (tmp_path / "unsafe").exists()


def test_projector_cannot_hide_an_unsafe_row_outside_the_unified_projection(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    store.import_input(_input("20260730", "STAGE_1445_1500"))

    def unsafe_group(payload):
        output = _project_watch_only(payload)
        output["stage_groups"][0]["rows"][0]["recommendation_status"] = "BUY"
        return output

    result = StageRunner(store, projector=unsafe_group).ensure("20260730", "STAGE_1445_1500")
    assert result["ensure_status"] == "STAGE_RUN_FAILED"
    assert store.read_latest("20260730", "STAGE_1445_1500") is None


def test_ensure_can_materialize_missing_input_through_the_native_producer(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    calls = []

    class Producer:
        def produce(self, trade_date, stage_id):
            calls.append((trade_date, stage_id))
            store.import_input(_input(trade_date, stage_id))

    runner = StageRunner(store, input_producer=Producer())
    result = runner.ensure("20260730", "STAGE_1545_1555")

    assert calls == [("20260730", "STAGE_1545_1555")]
    assert result["ensure_status"] == "STAGE_RUN_COMPLETE"


def test_ensure_reports_native_input_production_failure_without_a_partial_run(tmp_path) -> None:
    store = StageStore(tmp_path / "data")

    class Producer:
        def produce(self, trade_date, stage_id):
            raise ValueError("canonical pool missing")

    result = StageRunner(store, input_producer=Producer()).ensure("20260730", "STAGE_0925")

    assert result["ok"] is False
    assert result["ensure_status"] == "STAGE_INPUT_PRODUCTION_BLOCKED"
    assert "canonical pool missing" in result["cannot_confirm"][0]
    assert store.read_latest("20260730", "STAGE_0925") is None


def test_force_refreshes_stage_input_before_rematerializing(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    store.import_input(_input("20260730", "STAGE_1300_1315"))
    calls = []

    class RefreshingProducer:
        def produce(self, trade_date, stage_id):
            raise AssertionError("produce is not used when the input exists")

        def refresh(self, trade_date, stage_id):
            calls.append((trade_date, stage_id))

    result = StageRunner(
        store,
        input_producer=RefreshingProducer(),
    ).ensure("20260730", "STAGE_1300_1315", force=True)

    assert calls == [("20260730", "STAGE_1300_1315")]
    assert result["ensure_status"] == "FORCED_REMATERIALIZED"
