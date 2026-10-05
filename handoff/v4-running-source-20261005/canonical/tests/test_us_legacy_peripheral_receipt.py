"""Strict read/CAS compatibility for the pre-R2 US close receipt shape."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest

from infrastructure.data_store import _sha256
from infrastructure.research_peripheral_store import ResearchPeripheralStore


TRADE_DATE = "20261001"
SOURCE = "external_finance"
PAYLOAD_SHA256 = "044954de73a3922092d9a3888dfd51fc053f468bd138c7e30f7867605b3f62ae"
LEGACY_RECEIPT_SHA256 = "14ae27ca7e98d2bf5f7b5e154ba9a9bdf8ef54596d9b1efc707f30bbbb77ce4a"
PAYLOAD_RELATIVE = "research/peripherals/20261001/external_finance.json"
RECEIPT_RELATIVE = "receipts/research/peripherals/20261001/external_finance.json"
FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def _seed_legacy_store(root: Path) -> tuple[ResearchPeripheralStore, dict[str, Any]]:
    payload_bytes = (FIXTURE_ROOT / "us_external_finance_20261001.json").read_bytes()
    receipt_bytes = (
        FIXTURE_ROOT / "us_external_finance_20261001_legacy_receipt.json"
    ).read_bytes()
    assert hashlib.sha256(payload_bytes).hexdigest() == PAYLOAD_SHA256
    assert hashlib.sha256(receipt_bytes).hexdigest() == LEGACY_RECEIPT_SHA256

    payload = json.loads(payload_bytes)
    assert _sha256(payload) == PAYLOAD_SHA256
    store = ResearchPeripheralStore(root)
    payload_path = root / PAYLOAD_RELATIVE
    receipt_path = root / RECEIPT_RELATIVE
    manifest_path = root / "research/peripherals/manifest.json"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(payload_bytes)
    receipt_path.write_bytes(receipt_bytes)
    manifest_path.write_text(
        json.dumps({PAYLOAD_RELATIVE: PAYLOAD_SHA256}, sort_keys=True),
        encoding="utf-8",
    )
    return store, payload


def _assert_original_snapshot(payload: dict[str, Any]) -> None:
    snapshot = payload["market_snapshot"]
    assert payload["trade_date"] == TRADE_DATE
    assert payload["source"] == SOURCE
    assert payload["fetched_at"] == "2026-10-01T20:15:01Z"
    assert payload["status"] == "CANNOT_CONFIRM"
    assert snapshot["status"] == "CANNOT_CONFIRM"
    assert snapshot["captured_at"] == "2026-10-01T20:15:01Z"
    assert snapshot["source_response_sha256"] == (
        "dba3ff8a8e6d6413281efe646d25db946ae7a5392e946e8139c0819892fb0bd9"
    )
    assert len(snapshot["quotes"]) == 33
    assert len(snapshot["rows"]) == 24


def test_read_and_idempotent_publish_accept_only_exact_legacy_receipt(tmp_path: Path) -> None:
    store, original = _seed_legacy_store(tmp_path / "data")
    payload_path = tmp_path / "data" / PAYLOAD_RELATIVE
    receipt_path = tmp_path / "data" / RECEIPT_RELATIVE
    before_payload = payload_path.read_bytes()
    before_receipt = receipt_path.read_bytes()

    result = store.read_exact(TRADE_DATE, SOURCE)

    assert result == original
    _assert_original_snapshot(result)
    assert store.publish(original)["payload_sha256"] == PAYLOAD_SHA256
    assert payload_path.read_bytes() == before_payload
    assert receipt_path.read_bytes() == before_receipt


def test_cas_replace_accepts_legacy_receipt_and_archives_exact_old_payload(
    tmp_path: Path,
) -> None:
    store, original = _seed_legacy_store(tmp_path / "data")
    replacement = deepcopy(original)
    replacement["cannot_confirm"] = sorted(
        {*replacement["cannot_confirm"], "ISOLATED_CAS_TEST"}
    )

    result = store.replace(
        replacement,
        expected_sha256=PAYLOAD_SHA256,
        reason="isolated legacy receipt CAS regression",
    )

    assert result["replaced"] is True
    supersession = store._read(result["supersession_receipt_path"])
    assert supersession["previous_payload_sha256"] == PAYLOAD_SHA256
    archived = store._read(result["previous_payload_path"])
    assert archived == original
    _assert_original_snapshot(archived)
    assert store.read_exact(TRADE_DATE, SOURCE) == replacement


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda receipt: (
                receipt.__setitem__("market_snapshot_captured_at", "2026-10-02T00:00:00Z"),
                receipt.__setitem__(
                    "market_snapshot_source_response_sha256",
                    "dba3ff8a8e6d6413281efe646d25db946ae7a5392e946e8139c0819892fb0bd9",
                ),
            ),
            id="explicit-derived-field-conflict",
        ),
        pytest.param(
            lambda receipt: receipt.pop("feed_receipts"),
            id="additional-field-missing",
        ),
        pytest.param(
            lambda receipt: (
                receipt.__setitem__("market_snapshot_captured_at", "2026-10-01T20:15:01Z"),
                receipt.pop("market_snapshot_source_response_sha256", None),
            ),
            id="only-one-derived-field-missing",
        ),
        pytest.param(
            lambda receipt: receipt.__setitem__("unexpected_field", "not-legacy"),
            id="unexpected-field",
        ),
        pytest.param(
            lambda receipt: receipt.__setitem__("payload_sha256", "0" * 64),
            id="payload-sha-mismatch",
        ),
    ],
)
def test_read_rejects_any_receipt_difference_beyond_both_derived_fields(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], Any]
) -> None:
    store, _original = _seed_legacy_store(tmp_path / "data")
    receipt_path = tmp_path / "data" / RECEIPT_RELATIVE
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    mutate(receipt)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="research peripheral manifest or receipt mismatch"):
        store.read_exact(TRADE_DATE, SOURCE)
