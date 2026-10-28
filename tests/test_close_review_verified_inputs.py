from __future__ import annotations

import importlib
import hashlib
import json

import pytest


def test_legacy_consumer_provenance_is_recovered_from_same_verified_run(monkeypatch):
    producer = importlib.import_module("ops.build_close_review")
    class Store:
        def read_verified(self, date, stage, market):
            return {"run_id": "same-run", "source_evidence": ["futu_captured_at=2026-10-13T12:09:12+08:00"]}
    class Consumer:
        store = Store()
        def __init__(self, root): pass
        def get(self, date, stage, **kwargs):
            return {"trade_date": date, "stage_id": stage,
                    "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                    "markets": {"HK_CONNECT": {"run_id": "same-run", "status": "PARTIAL_WITH_ROWS",
                    "rows": [{"code": "HK.00001", "market": "HK"}], "source_rows": 100,
                    "requested_rows": 100, "cannot_confirm": ["FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE"]}}}
    monkeypatch.setattr(producer, "StageSelectionConsumer", Consumer)
    rows, evidence = producer._stage_rows_with_evidence("unused", "20261013")
    assert all(e["source_evidence"] and e["source_rows"] == 100 for e in evidence.values())
    assert all(e["status"] == "PARTIAL_WITH_ROWS" for e in evidence.values())
    monkeypatch.setattr(Store, "read_verified", lambda *args: {"run_id": "different-run"})
    rows, evidence = producer._stage_rows_with_evidence("unused", "20261013")
    assert all(value is None for value in rows.values())


@pytest.mark.parametrize("failure", [None, "csv_tamper", "wrong_date", "partial_csv", "wrong_selection", "source_gap"])
def test_auction_review_uses_verified_top20_denominator_only(tmp_path, failure):
    producer = importlib.import_module("ops.build_close_review")
    path = tmp_path / "auction.csv"
    count = 19 if failure == "partial_csv" else 20
    path.write_text("code\n" + "".join(f"HK.{i:05d}\n" for i in range(1, count + 1)))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".acceptance.json").write_text(json.dumps({
        "target_date": "20261012" if failure == "wrong_date" else "20261013",
        "status": "AUCTION_SECOND_FILTER_READY", "required_row_count": 20,
        "row_count": count, "csv_sha256": digest, "temporal_cutoff_safe": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }))
    evidence = {"status": "PARTIAL_WITH_ROWS", "source_status": "READY", "source_rows": 20, "requested_rows": 100,
                "cannot_confirm": ["REAL_GAP"] if failure == "source_gap" else [],
                "source_evidence": ["route=hk_connect_0915_0920_auction_second_filter",
                    f"second_filter_csv={path}", f"second_filter_csv_sha256={digest}"]}
    rows = [{"code": f"HK.{i:05d}"} for i in range(1, 11)]
    if failure == "csv_tamper": path.write_text(path.read_text() + "HK.00021\n")
    if failure == "wrong_selection": rows.reverse()
    producer._auction_review_input(evidence, rows, "20261013")
    assert evidence["status"] == "PARTIAL_WITH_ROWS"
    if failure is None:
        assert evidence["review_evidence_status"] == "READY"
        assert evidence["review_expected_rows"] == evidence["review_source_rows"] == 20
    else:
        assert "review_evidence_status" not in evidence


def _pool_payload(*, status="STRICT_0_2_READY", source_role="SHARED_VERIFIED_HK_0_2"):
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": "20260821",
        "pool_id": "hkconnect_d1_top100",
        "display_name": "HK D-1 Top100",
        "market": "HK",
        "status": status,
        "producer_id": "verified.fixture",
        "source_role": source_role,
        "source_path": "shared/hk.json",
        "source_sha256": "a" * 64,
        "rows": [
            {
                "market": "HK",
                "symbol": f"HK.{index:05d}",
                "stock_name": f"Stock {index}",
                "pool_rank": index,
                "target_date": "20260821",
            }
            for index in range(1, 101)
        ],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_close_review_helpers_require_exact_verified_pool_and_consume_stage_root(monkeypatch):
    producer = importlib.import_module("ops.build_close_review")

    assert len(producer._model_rows(_pool_payload(), "20260821")) == 100
    assert producer._model_rows(
        _pool_payload(status="CANNOT_CONFIRM"), "20260821"
    ) == []
    assert producer._model_rows(
        _pool_payload(source_role="RAW_SOURCE"), "20260821"
    ) == []

    calls = []

    class FakeConsumer:
        def __init__(self, root):
            calls.append(("root", root))

        def get(self, trade_date, stage_id, *, markets, allow_backfill):
            assert allow_backfill is True
            calls.append((trade_date, stage_id, markets))
            return {
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {
                    "HK_CONNECT": {
                        "rows": [{"market": "HK", "code": "HK.00001"}],
                        "status": "READY",
                    }
                },
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    monkeypatch.setattr(producer, "StageSelectionConsumer", FakeConsumer)
    stage_rows = producer._stage_rows("stage-root", "20260821")

    assert all(stage_rows[stage_id] == [{"market": "HK", "code": "HK.00001"}] for stage_id in producer._REVIEW_STAGE_IDS)
    assert calls[0] == ("root", "stage-root")
    assert all(call[2] == ("HK_CONNECT",) for call in calls[1:])

    class MissingConsumer:
        def __init__(self, _root):
            pass

        def get(self, trade_date, stage_id, *, markets, allow_backfill):
            assert allow_backfill is True
            return {
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {
                    "HK_CONNECT": {
                        "status": "CANNOT_CONFIRM",
                        "selection_status": "CANNOT_CONFIRM",
                        "rows": [],
                        "cannot_confirm": [
                            "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"
                        ],
                    }
                },
                "cannot_confirm": ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    monkeypatch.setattr(producer, "StageSelectionConsumer", MissingConsumer)
    missing_rows = producer._stage_rows("stage-root", "20260821")
    assert all(missing_rows[stage_id] is None for stage_id in producer._REVIEW_STAGE_IDS)


def test_missing_exact_pool_differs_from_corrupt_manifest(tmp_path, monkeypatch):
    producer = importlib.import_module("ops.build_close_review")
    monkeypatch.setattr(
        producer.CloseSnapshotStore,
        "read_snapshot",
        lambda _self, _trade_date: ({"rows": []}, "a" * 64),
    )

    def missing_exact_pool(_self, _trade_date, _pool_id):
        raise FileNotFoundError("hkconnect_d1_top100")

    monkeypatch.setattr(producer.PreselectionPoolStore, "read_pool", missing_exact_pool)
    missing = producer.build_close_review(tmp_path / "missing", "20260821")
    assert missing["review"]["models"]["0.2_prob_active"]["evidence_status"] == "MISSING"
    assert "MODEL_0_2_TOP100_NOT_READY:0/100" in missing["review"]["cannot_confirm"]

    def corrupt_manifest(_self, _trade_date, _pool_id):
        raise FileNotFoundError("preselection_pools/20260821/manifest.json")

    monkeypatch.setattr(producer.PreselectionPoolStore, "read_pool", corrupt_manifest)
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        producer.build_close_review(tmp_path / "corrupt", "20260821")


def test_close_review_executor_requires_and_passes_stage_selection_root(tmp_path):
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling.executor_registry import (
        FixedExecutorRegistry,
        WorkloadExecutionError,
    )

    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260821",
        slot="1608",
        mode=DispatchMode.LIVE,
    )
    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        stage_selection_root=tmp_path / "stage-selection",
        repo_root=tmp_path,
    )
    calls = []

    def fake_run(module, arguments, **_kwargs):
        calls.append((module, list(arguments)))
        return {
            "status": "SUCCEEDED",
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    registry._run = fake_run
    registry._hk_connect_close_review(request)
    builder_args = next(args for module, args in calls if module == "ops.build_close_review")
    assert builder_args[-2:] == ["--stage-selection-root", str(tmp_path / "stage-selection")]

    missing_root = FixedExecutorRegistry(data_root=tmp_path / "missing", repo_root=tmp_path)
    with pytest.raises(WorkloadExecutionError) as error:
        missing_root._hk_connect_close_review(request)
    assert "stage selection root not configured" in error.value.result["stderr"]
