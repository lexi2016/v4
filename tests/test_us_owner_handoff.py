"""Focused acceptance tests for the prepared V4 US owner wrapper."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from contracts.runtime_tasks import DispatchMode
from infrastructure.scheduling.catalog import load_workload_catalog

import ops.run_us_market_slot as us_slot


ROOT = Path(__file__).resolve().parents[1]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _bind_current_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from infrastructure.scheduling import dispatcher

    entries = []
    for relative in dispatcher._RUNTIME_IDENTITY_FILES:
        path = ROOT / relative
        raw = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "kind": "file",
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "candidate": {
            "app_root": str(ROOT),
            "release_id": "US_OWNER_HANDOFF_TEST",
        },
        "application_inventory": {
            "entries": entries,
            "entry_count": len(entries),
            "aggregate_sha256": hashlib.sha256(_canonical(entries)).hexdigest(),
        },
    }
    manifest_path = tmp_path / "release-manifest.json"
    manifest_bytes = _canonical(manifest)
    manifest_path.write_bytes(manifest_bytes)
    monkeypatch.setenv("V35_APP_ROOT", str(ROOT))
    monkeypatch.setenv("V35_RELEASE_ID", "US_OWNER_HANDOFF_TEST")
    monkeypatch.setenv("V35_RELEASE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv(
        "V35_RELEASE_MANIFEST_SHA256",
        hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _success_executor(calls: list[str]):
    def execute(workload, _request, _decision):
        calls.append(workload.workload_id)
        return {
            "status": "SUCCEEDED",
            "workload_id": workload.workload_id,
            "modules": ["fixture.us_market_digest"],
            "exit_code": 0,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    return execute


def test_catalog_view_is_single_registered_us_workload_and_keeps_source_intact() -> None:
    source = load_workload_catalog()
    source_ids = tuple(workload.workload_id for workload in source.workloads)

    selected = us_slot.select_us_catalog(source)

    assert tuple(item.workload_id for item in selected.workloads) == (
        us_slot.US_MARKET_WORKLOAD_ID,
    )
    workload = selected.workloads[0]
    assert workload.owner_id == us_slot.US_MARKET_OWNER_ID
    assert workload.enabled is True
    assert workload.slots == us_slot.US_MARKET_SLOTS
    assert tuple(item.workload_id for item in source.workloads) == source_ids
    assert selected.source_payload == source.source_payload
    assert us_slot.select_us_workload(selected).target_date_role == "TARGET_DATE"


def test_only_us_is_selected_and_repeat_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_current_release(tmp_path, monkeypatch)
    calls: list[str] = []
    ledger_root = tmp_path / "dispatcher"

    first = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="2100",
        business_date="20260915",
        executor=_success_executor(calls),
    )

    assert first["status"] == "SUCCEEDED", first
    assert first["selected_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]
    assert first["started_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]
    assert calls == [us_slot.US_MARKET_WORKLOAD_ID]
    assert first["mode"] == DispatchMode.LIVE.value
    assert all(first[field] is False for field in (
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    ))

    repeated = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="2100",
        business_date="20260915",
        executor=_success_executor(calls),
    )

    assert repeated["status"] == "CONCURRENCY_SKIPPED", repeated
    assert repeated["selected_workload_ids"] == []
    assert repeated["started_workload_ids"] == []
    assert calls == [us_slot.US_MARKET_WORKLOAD_ID]
    receipt_files = tuple(ledger_root.rglob("*.dispatch-receipt.json"))
    assert len(receipt_files) == 1
    stored = json.loads(receipt_files[0].read_text(encoding="utf-8"))
    assert stored["selected_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]


def test_failed_us_dispatch_is_fail_closed_and_can_retry_its_released_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_current_release(tmp_path, monkeypatch)
    ledger_root = tmp_path / "dispatcher"

    def fail(_workload, _request, _decision):
        raise RuntimeError("fixture upstream unavailable")

    failed = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="0415",
        business_date="20260915",
        executor=fail,
    )

    assert failed["status"] == "FAILED", failed
    assert failed["selected_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]
    assert failed["started_workload_ids"] == []
    assert failed["workload_results"][0]["workload_id"] == us_slot.US_MARKET_WORKLOAD_ID
    assert all(failed[field] is False for field in (
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    ))
    assert not (ledger_root / "claims" / "live" / "20260915" / "0415" / "dispatch.claim.json").exists()

    calls: list[str] = []
    recovered = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="0415",
        business_date="20260915",
        executor=_success_executor(calls),
    )

    assert recovered["status"] == "SUCCEEDED", recovered
    assert recovered["started_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]
    assert calls == [us_slot.US_MARKET_WORKLOAD_ID]
    receipts = tuple(ledger_root.rglob("*.dispatch-receipt.json"))
    statuses = {
        json.loads(path.read_text(encoding="utf-8"))["status"] for path in receipts
    }
    assert statuses == {"FAILED", "SUCCEEDED"}
    assert len(receipts) == 2


def test_dry_run_selects_us_without_formal_ledger_or_executor_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_current_release(tmp_path, monkeypatch)
    calls: list[str] = []

    def should_not_execute(*_args):
        calls.append("executed")
        raise AssertionError("dry-run executed a workload")

    ledger_root = tmp_path / "dispatcher"
    result = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="0515",
        business_date="20260915",
        executor=should_not_execute,
        dry_run=True,
    )

    assert result["status"] == "DRY_RUN_SELECTED", result
    assert result["selected_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]
    assert result["started_workload_ids"] == []
    assert calls == []
    assert not tuple(path for path in ledger_root.iterdir() if path.name != "dry-run")
    assert tuple((ledger_root / "dry-run").rglob("*.dispatch-receipt.json"))


def test_only_original_us_slots_are_accepted_and_default_slot_uses_shanghai_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(ValueError, match="US_SLOT_NOT_ALLOWED"):
        us_slot.run_us_market_slot(
            data_root=tmp_path / "data",
            ledger_root=tmp_path / "dispatcher",
            slot="1400",
            business_date="20260915",
            executor=lambda *_args: None,
        )

    observed: dict[str, str] = {}

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 15, 4, 15, tzinfo=tz)

    def fake_run(**kwargs):
        observed["slot"] = kwargs["slot"]
        observed["business_date"] = kwargs["business_date"]
        return {
            "status": "DRY_RUN_SELECTED",
            "selected_workload_ids": [us_slot.US_MARKET_WORKLOAD_ID],
            "started_workload_ids": [],
        }

    monkeypatch.setattr(us_slot, "datetime", FixedDateTime)
    monkeypatch.setattr(us_slot, "run_us_market_slot", fake_run)
    code = us_slot.main(
        [
            "--data-root",
            str(tmp_path / "data"),
            "--ledger-root",
            str(tmp_path / "dispatcher"),
            "--dry-run",
        ]
    )

    assert code == 0
    assert observed == {"slot": "0415", "business_date": "20260915"}
    assert json.loads(capsys.readouterr().out)["status"] == "DRY_RUN_SELECTED"


def test_registered_owner_mismatch_or_disabled_workload_fails_closed() -> None:
    source = load_workload_catalog()
    original = us_slot.select_us_workload(source)

    bad_owner = replace(original, owner_id="legacy.owner")
    bad_owner_catalog = replace(
        source,
        workloads=tuple(
            bad_owner if item.workload_id == original.workload_id else item
            for item in source.workloads
        ),
    )
    with pytest.raises(ValueError, match="US_WORKLOAD_OWNER_MISMATCH"):
        us_slot.select_us_catalog(bad_owner_catalog)

    disabled = replace(original, enabled=False)
    disabled_catalog = replace(
        source,
        workloads=tuple(
            disabled if item.workload_id == original.workload_id else item
            for item in source.workloads
        ),
    )
    with pytest.raises(ValueError, match="US_WORKLOAD_DISABLED"):
        us_slot.select_us_catalog(disabled_catalog)


def test_main_rejects_non_natural_slot_with_json_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = us_slot.main(
        [
            "--slot",
            "1400",
            "--date",
            "20260915",
            "--data-root",
            str(tmp_path / "data"),
            "--ledger-root",
            str(tmp_path / "dispatcher"),
        ]
    )

    assert code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "FAILED"
    assert "US_SLOT_NOT_ALLOWED" in output["reason"]
    assert output["selected_workload_ids"] == []
