from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

import infrastructure.owned_path as owned_path
from domains.a_share_review import build_a_share_review
from infrastructure.a_share_review_store import AShareReviewStore
from infrastructure.data_store import _sha256
from infrastructure.owned_path import resolve_owned_path
from ops.import_a_share_review_reference import import_reference_file, normalize_a_share_review_reference


def _payload(trade_date: str = "20260730") -> dict:
    rows = lambda count: [{"id": str(index), "trade_date": trade_date} for index in range(count)]
    return build_a_share_review(
        trade_date,
        big_picture=rows(9), mainlines=[], core_stocks=[], observation_pool=rows(12),
        trigger_rows=rows(4), quality_gate_rows=rows(7), source_sha256="b" * 64,
    )


def test_store_is_exact_date_idempotent_and_validates_manifest_sha(tmp_path: Path) -> None:
    store = AShareReviewStore(tmp_path / ".runtime" / "data")
    first = store.import_review(_payload())
    second = store.import_review(_payload())

    assert second == first
    assert first["payload_path"] == "a_share_reviews/20260730.json"
    assert store.read_review("20260730")["observation_pool"]

    payload_path = store.root / first["payload_path"]
    tampered = json.loads(payload_path.read_text(encoding="utf-8"))
    tampered["headline"] = "tampered"
    payload_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA"):
        store.read_review("20260730")


@pytest.mark.parametrize(
    "missing_relative",
    [
        "a_share_reviews/20260730.json",
        "a_share_reviews/receipts/20260730.json",
        "a_share_reviews/manifest.json",
    ],
)
def test_store_returns_not_materialized_only_when_all_evidence_is_absent(
    tmp_path: Path, missing_relative: str
) -> None:
    store = AShareReviewStore(tmp_path / ".runtime" / "data")

    assert store.read_review("20260730") is None
    store.import_review(_payload())
    (store.root / missing_relative).unlink()

    with pytest.raises(ValueError, match="evidence|SHA"):
        store.read_review("20260730")


def test_store_ignores_other_dates_in_global_manifest_for_unmaterialized_date(tmp_path: Path) -> None:
    store = AShareReviewStore(tmp_path / ".runtime" / "data")
    store._write("a_share_reviews/manifest.json", {"a_share_reviews/20260729.json": "a" * 64})

    assert store.read_review("20260730") is None


@pytest.mark.parametrize(
    "directory_relative",
    [
        "a_share_reviews/20260730.json",
        "a_share_reviews/receipts/20260730.json",
        "a_share_reviews/manifest.json",
    ],
)
def test_store_fails_closed_when_evidence_path_is_a_directory(
    tmp_path: Path, directory_relative: str
) -> None:
    store = AShareReviewStore(tmp_path / ".runtime" / "data")
    (store.root / directory_relative).mkdir(parents=True)

    with pytest.raises(ValueError, match="evidence|manifest"):
        store.read_review("20260730")


def test_store_fails_closed_when_manifest_claims_missing_target_payload(tmp_path: Path) -> None:
    store = AShareReviewStore(tmp_path / ".runtime" / "data")
    store._write("a_share_reviews/manifest.json", {"a_share_reviews/20260730.json": "a" * 64})

    with pytest.raises(ValueError, match="evidence|SHA"):
        store.read_review("20260730")


@pytest.mark.parametrize("with_receipt", [False, True])
def test_store_recovers_matching_crash_before_manifest_write(
    tmp_path: Path, with_receipt: bool
) -> None:
    store = AShareReviewStore(tmp_path / ".runtime" / "data")
    payload = _payload()
    payload_path, receipt_path, _ = store._paths("20260730")
    store._write(payload_path, payload)
    if with_receipt:
        store._write(receipt_path, {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": payload_path,
            "payload_sha256": _sha256(payload),
            "source_sha256": payload["source_sha256"],
            "trade_date": "20260730",
        })

    result = store.import_review(payload)

    assert result["payload_path"] == payload_path
    assert store.read_review("20260730") == payload


def test_store_rejects_crash_recovery_when_payload_or_receipt_does_not_match(tmp_path: Path) -> None:
    store = AShareReviewStore(tmp_path / ".runtime" / "data")
    payload = _payload()
    payload_path, receipt_path, _ = store._paths("20260730")
    mismatched_payload = _payload()
    mismatched_payload["headline"] = "different"
    store._write(payload_path, mismatched_payload)

    with pytest.raises(ValueError, match="interrupted|SHA"):
        store.import_review(payload)

    store = AShareReviewStore(tmp_path / "other" / ".runtime" / "data")
    payload_path, receipt_path, _ = store._paths("20260730")
    store._write(payload_path, payload)
    store._write(receipt_path, {"wrong": "receipt"})
    with pytest.raises(ValueError, match="interrupted|SHA"):
        store.import_review(payload)


def test_store_rejects_cross_date_before_any_write(tmp_path: Path) -> None:
    root = tmp_path / ".runtime" / "data"
    payload = _payload()
    payload["observation_pool"][0]["trade_date"] = "20260729"

    with pytest.raises(ValueError, match="date"):
        AShareReviewStore(root).import_review(payload)

    assert not root.exists()


def test_store_rejects_manifest_directory_before_payload_or_receipt_write(tmp_path: Path) -> None:
    store = AShareReviewStore(tmp_path / ".runtime" / "data")
    manifest_path = store.root / "a_share_reviews" / "manifest.json"
    manifest_path.mkdir(parents=True)

    with pytest.raises(ValueError, match="manifest"):
        store.import_review(_payload())

    assert not (store.root / "a_share_reviews" / "20260730.json").exists()
    assert not (store.root / "a_share_reviews" / "receipts" / "20260730.json").exists()


@pytest.mark.parametrize("relative", ["/absolute.json", "\\absolute.json", "../escape.json", "C:/absolute.json"])
def test_owned_path_rejects_absolute_and_parent_destinations_before_write(tmp_path: Path, relative: str) -> None:
    root = tmp_path / ".runtime" / "data"

    with pytest.raises(ValueError, match="owned"):
        resolve_owned_path(root, relative)

    assert not root.exists()


def test_owned_path_rejects_symlink_escape_before_any_write(tmp_path: Path) -> None:
    root = tmp_path / ".runtime" / "data"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir(parents=True)
    try:
        (root / "a_share_reviews").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")

    with pytest.raises(ValueError, match="reparse|owned"):
        resolve_owned_path(root, "a_share_reviews/20260730.json")

    assert list(outside.iterdir()) == []


def test_owned_path_rejects_windows_reparse_ancestor_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / ".runtime" / "data"
    reparse_ancestor = root / "a_share_reviews"
    reparse_ancestor.mkdir(parents=True)
    monkeypatch.setattr(owned_path, "_is_reparse_point", lambda path: path == reparse_ancestor)

    with pytest.raises(ValueError, match="reparse"):
        resolve_owned_path(root, "a_share_reviews/20260730.json")


def test_importer_accepts_explicit_external_input_and_legacy_field_names(tmp_path: Path) -> None:
    source = tmp_path / "external-export.json"
    source.write_text(json.dumps({
        "review_date": "20260730",
        "first_screen_big_picture": [{"title": str(index)} for index in range(9)],
        "next_day_trigger_tree_v2": [{"direction": str(index)} for index in range(4)],
        "human_video_gap_scorecard": [{"item": str(index)} for index in range(7)],
        "localized_role_rows": [],
        "observation_pool": [{"code": str(index)} for index in range(12)],
    }, ensure_ascii=False), encoding="utf-8")
    normalized = normalize_a_share_review_reference(json.loads(source.read_text(encoding="utf-8")), "c" * 64)
    store = AShareReviewStore(tmp_path / ".runtime" / "data")

    result = import_reference_file(store, source)

    assert result["payload_path"] == "a_share_reviews/20260730.json"
    assert len(normalized["big_picture"]) == 9
    assert len(store.read_review("20260730")["observation_pool"]) == 12


def test_receipt_keeps_distinct_payload_and_raw_source_sha_without_mutating_input(tmp_path: Path) -> None:
    source = tmp_path / "external-export.json"
    raw_bytes = (
        b"\xef\xbb\xbf  {\n"
        b'  "review_date": "20260730",\n'
        b'  "first_screen_big_picture": [],\n'
        b'  "next_day_trigger_tree_v2": [],\n'
        b'  "human_video_gap_scorecard": [],\n'
        b'  "localized_role_rows": [],\n'
        b'  "observation_pool": []\n'
        b"}\n"
    )
    source.write_bytes(raw_bytes)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    store = AShareReviewStore(tmp_path / ".runtime" / "data")

    result = import_reference_file(store, source)

    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    receipt = json.loads((store.root / result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["payload_sha256"] == result["sha256"]
    assert receipt["source_sha256"] == hashlib.sha256(raw_bytes).hexdigest()
    assert receipt["payload_sha256"] != receipt["source_sha256"]
