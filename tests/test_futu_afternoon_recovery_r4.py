"""Hermetic regression checks for the bounded Futu afternoon recovery path."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import ops._run_stage_center_nodes_parts.stage_dispatch as dispatch
import ops.run_stage_center_nodes as entry
import stage_center._live_collectors_parts.hk_minute as hk_minute
import stage_center.live_collectors as live_collectors
from stage_center.acquisition import SourceResult
from stage_center.selection import select_hk_four_lane


DATE = "20261012"
STAGE_1300 = "STAGE_1300_1315"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SAFE = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def _frozen_1300_receipt() -> dict:
    return {
        "schema_version": "stage_center.runner.receipt.v1",
        "runner": "stage_center",
        "trade_date": DATE,
        "stage_id": STAGE_1300,
        "node_id": STAGE_1300,
        "status": "CANNOT_CONFIRM",
        "due_status": "LATE_CATCHUP_REPLAY",
        "dispatch_mode": "RECOVERY",
        "node_outcome": "TRANSIENT",
        "node_attempt_count": 3,
        "retry_exhausted": True,
        "write_performed": False,
        "candidate_current_sha256": "c26102284e3eca12614118c3481e139ad805d65719d300f23e30887a9bf548b9",
        "candidate_run_id": "20261012-a_share_stage_acquisition_universe_v3-8923902e3cc4",
        "execution_origin": "HK_ORIGINAL_BUDGET_RECOVERY",
        "execution_markets": ["HK_CONNECT"],
        "error": "prior-hk-source-error",
        "first_failed_layer": "PRIOR_HK_SOURCE_FAILURE",
        "markets": {
            "A_SHARE": {
                "market": "A_SHARE",
                "status": "PARTIAL_WITH_ROWS",
                "selection_status": "PARTIAL_WITH_ROWS",
                "selected_rows": 10,
                "run_id": "run-3b2d201a7635f0fab5ab4f6d",
                "artifact_id": "a-share-sentinel",
            },
            "HK_CONNECT": {
                "market": "HK_CONNECT",
                "selected_rows": 0,
                "write_performed": False,
                "cannot_confirm": [
                    "PyTDX ExHQ probe execution failed",
                    "PyTDX ExHQ probe returned an error",
                    "PyTDX ExHQ batch coverage incomplete: completed=0/100",
                ],
            },
        },
        **SAFE,
    }


def test_futu_dispatch_shape_is_exact_and_capped_to_original_three_attempts() -> None:
    receipt = _frozen_1300_receipt()
    kwargs = {
        "mode": "RECOVERY",
        "trade_date": DATE,
        "stage_id": STAGE_1300,
        "attempt_count": 3,
        "max_attempts": 3,
        "receipt_sha256": dispatch._HK_FUTU_1300_PRIOR_RECEIPT_SHA256,
        "dataset_sha256": dispatch._HK_FUTU_1300_DATASET_SHA256,
    }
    assert dispatch._same_day_hk_1300_futu_recovery_shape(receipt, **kwargs)
    assert not dispatch._same_day_hk_1300_futu_recovery_shape(receipt, **{**kwargs, "max_attempts": 4})
    assert not dispatch._same_day_hk_1300_futu_recovery_shape(receipt, **{**kwargs, "attempt_count": 4})
    assert not dispatch._same_day_hk_1300_futu_recovery_shape(receipt, **{**kwargs, "dataset_sha256": "0" * 64})
    unsafe = {**receipt, "orders_sent": True}
    assert not dispatch._same_day_hk_1300_futu_recovery_shape(unsafe, **kwargs)


def test_frozen_identity_reader_hashes_only_local_receipt_and_dataset(monkeypatch, tmp_path: Path) -> None:
    receipt_path = tmp_path / DATE / STAGE_1300 / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_bytes = b"synthetic receipt\n"
    dataset_bytes = b"synthetic after-fact bundle\n"
    receipt_path.write_bytes(receipt_bytes)
    dataset = tmp_path / "dataset.json"
    dataset.write_bytes(dataset_bytes)
    monkeypatch.setenv("V4_HK_FUTU_AFTERFACT_DATASET", str(dataset))
    receipt_sha, dataset_sha = dispatch._frozen_hk_futu_1300_hashes(
        {"receipt_root": tmp_path}, DATE, STAGE_1300, "RECOVERY"
    )
    assert receipt_sha == hashlib.sha256(receipt_bytes).hexdigest()
    assert dataset_sha == hashlib.sha256(dataset_bytes).hexdigest()
    assert dispatch._frozen_hk_futu_1300_hashes(
        {"receipt_root": tmp_path}, DATE, STAGE_1300, "NATURAL"
    ) == (None, None)


def test_afternoon_collector_uses_shared_futu_and_stage8_stays_replay_only(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("V4_HK_FUTU_AFTERFACT_DATASET", raising=False)
    calls: list[str] = []
    futu_result = object()
    replay_result = object()
    monkeypatch.setattr(live_collectors, "_shared_scripts_root", lambda value: Path(value))
    monkeypatch.setattr(live_collectors, "_scoped_process_runner", lambda _root, runner: runner)
    monkeypatch.setattr(live_collectors, "_load_shared_module", lambda *_args: SimpleNamespace(
        collect_futu_minute=lambda *_args, **_kwargs: calls.append("futu") or futu_result,
    ))
    monkeypatch.setattr(live_collectors, "_to_source", lambda value, **kwargs: (value, kwargs))
    monkeypatch.setattr(live_collectors, "_collect_hk_stage8_replay", lambda *_args, **_kwargs: calls.append("replay") or replay_result)

    plan = SimpleNamespace(trade_date=DATE, stage_id=STAGE_1300, same_day_late_observation_recovery=False)
    result = hk_minute._collect_hk_minute_body(
        vars(live_collectors), plan, codes=("HK.00001",), python_path="/fixture/python",
        shared_root=tmp_path, snapshot_root=None, process_runner=object(), replay_provider=None,
    )
    assert result[0] is futu_result
    assert result[1]["source_id"] == "futu"
    assert result[1]["route"] == "shared_futu_hkconnect_minute"
    assert calls == ["futu"]

    stage8 = SimpleNamespace(trade_date=DATE, stage_id="STAGE_1545_1555")
    replayed = hk_minute._collect_hk_minute_body(
        vars(live_collectors), stage8, codes=("HK.00001",), python_path="/fixture/python",
        shared_root=tmp_path, snapshot_root=None, process_runner=object(), replay_provider=object(),
    )
    assert replayed is replay_result
    assert calls == ["futu", "replay"]


def test_afterfact_reader_fails_closed_without_same_day_recovery_authority(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "synthetic.json"
    dataset.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("V4_HK_FUTU_AFTERFACT_DATASET", str(dataset))
    plan = SimpleNamespace(
        trade_date=DATE,
        stage_id=STAGE_1300,
        same_day_late_observation_recovery=False,
        historical_backfill=False,
    )
    source = hk_minute._load_futu_afterfact_source(plan, codes=tuple(f"HK.{i:05d}" for i in range(100)))
    assert isinstance(source, SourceResult)
    assert source.status == "CANNOT_CONFIRM"
    assert "FUTU_RT_DATA_AFTERFACT_SCOPE_MISMATCH" in source.cannot_confirm


def test_four_lane_selector_keeps_afterfact_rows_no_buy() -> None:
    envelope = select_hk_four_lane(
        [{"code": "HK.00001", "last_price": 10.0, "prev_close_price": 9.0}],
        DATE,
        STAGE_1300,
        "a" * 64,
        source_status="PARTIAL_WITH_ROWS",
        requested_rows=100,
        cannot_confirm=("FUTU_RT_DATA_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT",),
        source_evidence=("futu_afterfact_selection_action_boundary=NO_BUY",),
    )
    assert envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert envelope["rows"]
    assert all(row["action_level"] == "NO_BUY" for row in envelope["rows"])
    assert all(row["formal_eligible"] is False for row in envelope["rows"])


def test_dispatch_consumes_futu_allowance_before_one_hk_only_run_and_preserves_a_lane(monkeypatch, tmp_path: Path) -> None:
    receipt_root = tmp_path / "receipts"
    receipt_path = receipt_root / DATE / STAGE_1300 / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    original = _frozen_1300_receipt()
    original_bytes = (json.dumps(original, ensure_ascii=False, sort_keys=True) + "\n").encode()
    receipt_path.write_bytes(original_bytes)
    monkeypatch.setattr(dispatch, "_frozen_hk_futu_1300_hashes", lambda *_args: (
        dispatch._HK_FUTU_1300_PRIOR_RECEIPT_SHA256,
        dispatch._HK_FUTU_1300_DATASET_SHA256,
    ))
    monkeypatch.setattr(entry, "_calendar_gate", lambda trade_date, *, markets: {"status": "ELIGIBLE", "trade_date": trade_date})
    evaluated = datetime(2026, 10, 12, 13, 20, tzinfo=SHANGHAI)
    monkeypatch.setattr(entry, "_rearm_wall_now", lambda: evaluated + timedelta(seconds=1))

    class Deadline:
        def pending_receipt_marker(self, path): return path.with_name(path.name + ".pending")
        def before_receipt(self, payload): return dict(payload)
        def checkpoint(self, *_args, **_kwargs): pass
        def due(self, *_args, **_kwargs): pass
        def event(self, *_args, **_kwargs): pass
        def complete_receipt(self, _path, result, *, rewrite): return result

    monkeypatch.setattr(entry, "_deadline", Deadline())

    class FakeRunner:
        def __init__(self):
            self.config = SimpleNamespace(receipt_root=receipt_root)
            self.calls = []

        def _receipt_path(self, trade_date, stage_id):
            return receipt_root / trade_date / stage_id / "receipt.json"

        def due_decisions(self, trade_date, _evaluated_at, *, historical_backfill=False):
            return [SimpleNamespace(
                status="LATE_CATCHUP_REPLAY", trade_date=trade_date, stage_id=STAGE_1300,
                scheduled_at=datetime(2026, 10, 12, 13, 15, tzinfo=SHANGHAI),
            )]

        def _write_receipt(self, payload, trade_date, stage_id):
            result = {"schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center",
                      **entry._deadline.before_receipt(payload), **entry.SAFETY_FLAGS}
            path = self._receipt_path(trade_date, stage_id)
            path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            return result

        def _run_one(self, decision):
            self.calls.append(decision)
            assert decision.same_day_late_observation_recovery is True
            assert self._execution_scope.markets == ("HK_CONNECT",)
            return {
                "status": "PARTIAL_WITH_ROWS",
                "write_performed": True,
                "error": original["error"],
                "first_failed_layer": original["first_failed_layer"],
                "markets": {"HK_CONNECT": {
                    "market": "HK_CONNECT", "selection_status": "PARTIAL_WITH_ROWS",
                    "selected_rows": 1, "run_id": "hk-run", "raw_artifact_sha256": "a" * 64,
                    "source_evidence": [
                        "futu_observation_contract=HK_FUTU_RTDATA_AFTERFACT_RESEARCH_20261012_R1",
                        "futu_afterfact_temporal_cutoff_safe=false",
                    ],
                }},
            }

    runner = FakeRunner()
    config = {
        "receipt_root": receipt_root,
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 60,
        "safety": dict(SAFE),
    }
    result = entry._dispatch_stage(config, DATE, STAGE_1300, evaluated,
                                   mode="RECOVERY", runner=runner, precaptures=())
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["node_attempt_count"] == 4
    assert result["execution_markets"] == ["HK_CONNECT"]
    assert result["markets"]["A_SHARE"] == original["markets"]["A_SHARE"]
    assert result["error"] is None and result["first_failed_layer"] is None
    assert result["temporal_cutoff_safe"] is False
    assert result["execution_verified"] is False
    assert result["selection_action_boundary"] == "NO_BUY"
    assert result["retry_exhausted"] is False
    assert result["node_outcome"] == "SETTLED_PARTIAL"
    marker = receipt_path.parent / dispatch._HK_FUTU_1300_CONSUMPTION_MARKER
    grant = json.loads(marker.read_text(encoding="utf-8"))
    assert grant["consumed_before_runner"] is True
    assert grant["consumed_attempt_number"] == 4
    archived = receipt_path.parent / "attempt_evidence" / f"preserved-{hashlib.sha256(original_bytes).hexdigest()}" / "PRIOR_RECEIPT.json"
    assert archived.read_bytes() == original_bytes
    assert len(runner.calls) == 1

    second = entry._dispatch_stage(config, DATE, STAGE_1300, evaluated,
                                   mode="RECOVERY", runner=runner, precaptures=())
    assert second["status"] == "SKIPPED_FUTU_RECOVERY_CONSUMED"
    assert len(runner.calls) == 1
