from __future__ import annotations

import importlib

import pytest


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

        def get(self, trade_date, stage_id, *, markets):
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

        def get(self, trade_date, stage_id, *, markets):
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
