from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from domains.a_share_review import build_a_share_review
from infrastructure.a_share_review_store import AShareReviewStore
from infrastructure.data_store import _sha256


def _rows(count: int, trade_date: str = "20260730") -> list[dict[str, str]]:
    return [{"id": str(index), "trade_date": trade_date} for index in range(count)]


def _canonical_review() -> dict:
    return build_a_share_review(
        "20260730",
        big_picture=_rows(9),
        mainlines=[{"name": "mainline", "trade_date": "20260730"}],
        core_stocks=[],
        observation_pool=_rows(12),
        trigger_rows=_rows(4),
        quality_gate_rows=_rows(7),
        source_sha256="a" * 64,
        source_role="V3_5_NATIVE_CLOSE_MODEL",
    )


def test_review_endpoint_keeps_rich_exact_date_a_review_when_hk_is_unavailable(tmp_path) -> None:
    data_root = tmp_path / ".runtime" / "data"
    canonical = _canonical_review()
    AShareReviewStore(data_root).import_review(canonical)

    response = TestClient(create_app(data_root=data_root)).get("/api/v3/review?date=20260730")

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "20260730"
    assert payload["market_reviews"]["A"] == canonical
    assert payload["market_reviews"]["HK"]["model_selection_review"]["status"] == "REFERENCE_NOT_IMPORTED"
    assert payload["fupan_review_v3"]["observation_pool"] == canonical["observation_pool"]
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_review_endpoint_never_substitutes_an_earlier_a_review(tmp_path) -> None:
    data_root = tmp_path / ".runtime" / "data"
    earlier = _canonical_review()
    earlier["trade_date"] = "20260729"
    for field in ("big_picture", "mainlines", "core_stocks", "observation_pool", "next_day_trigger_tree", "quality_gate"):
        for row in earlier[field]:
            row["trade_date"] = "20260729"
    AShareReviewStore(data_root).import_review(earlier)

    response = TestClient(create_app(data_root=data_root)).get("/api/v3/review?date=20260730")

    assert response.status_code == 200
    assert response.json()["market_reviews"]["A"]["status"] == "NOT_MATERIALIZED"
    assert response.json()["market_reviews"]["A"]["trade_date"] == "20260730"


def test_review_endpoint_does_not_serve_legacy_final_api_oracle(tmp_path) -> None:
    data_root = tmp_path / ".runtime" / "data"
    oracle = _canonical_review()
    oracle["source_role"] = "LEGACY_FINAL_API_ORACLE"
    AShareReviewStore(data_root).import_review(oracle)

    response = TestClient(create_app(data_root=data_root)).get("/api/v3/review?date=20260730")

    assert response.status_code == 200
    assert response.json()["market_reviews"]["A"]["status"] == "NOT_MATERIALIZED"
    assert response.json()["market_reviews"]["A"]["model_review"]["status"] == "NOT_MATERIALIZED"


def test_review_endpoint_degrades_invalid_legacy_payload_without_500(tmp_path) -> None:
    """A legacy payload missing source_role must degrade to NOT_MATERIALIZED, not 500."""
    import json

    data_root = tmp_path / ".runtime" / "data"
    stale = _canonical_review()
    del stale["source_role"]
    store = AShareReviewStore(data_root)
    store._path("a_share_reviews/20260730.json").parent.mkdir(parents=True, exist_ok=True)
    store._path("receipts/a_share_reviews/20260730.json").parent.mkdir(parents=True, exist_ok=True)
    store._path("a_share_reviews/manifest.json").parent.mkdir(parents=True, exist_ok=True)
    store._path("a_share_reviews/20260730.json").write_text(
        json.dumps(stale, ensure_ascii=False), encoding="utf-8"
    )
    digest = _sha256(stale)
    store._path("receipts/a_share_reviews/20260730.json").write_text(
        json.dumps({
            "schema_version": "v3_import_receipt.v1",
            "payload_path": "a_share_reviews/20260730.json",
            "payload_sha256": digest,
            "source_sha256": stale["source_sha256"],
            "trade_date": "20260730",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    store._path("a_share_reviews/manifest.json").write_text(
        json.dumps({"a_share_reviews/20260730.json": digest}, ensure_ascii=False),
        encoding="utf-8",
    )

    response = TestClient(create_app(data_root=data_root)).get("/api/v3/review?date=20260730")

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "20260730"
    assert payload["market_reviews"]["A"]["status"] == "NOT_MATERIALIZED"
    assert payload["market_reviews"]["A"]["cannot_confirm"] == ["A_SHARE_REVIEW_NOT_MATERIALIZED"]
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_replace_review_preserves_audit_chain_and_updates_manifest(tmp_path) -> None:
    import json as _json

    from infrastructure.data_store import _sha256 as _s256

    data_root = tmp_path / ".runtime" / "data"
    store = AShareReviewStore(data_root)
    legacy = _canonical_review()
    del legacy["source_role"]
    store._path("a_share_reviews/20260730.json").parent.mkdir(parents=True, exist_ok=True)
    store._path("a_share_reviews/receipts/20260730.json").parent.mkdir(parents=True, exist_ok=True)
    store._path("a_share_reviews/manifest.json").parent.mkdir(parents=True, exist_ok=True)
    store._path("a_share_reviews/20260730.json").write_text(
        _json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
    )
    legacy_digest = _s256(legacy)
    store._path("a_share_reviews/receipts/20260730.json").write_text(
        _json.dumps({
            "schema_version": "v3_import_receipt.v1",
            "payload_path": "a_share_reviews/20260730.json",
            "payload_sha256": legacy_digest,
            "source_sha256": legacy["source_sha256"],
            "trade_date": "20260730",
        }, ensure_ascii=False), encoding="utf-8"
    )
    store._path("a_share_reviews/manifest.json").write_text(
        _json.dumps({"a_share_reviews/20260730.json": legacy_digest}, ensure_ascii=False),
        encoding="utf-8",
    )

    replacement = _canonical_review()  # has source_role=V3_5_NATIVE_CLOSE_MODEL
    result = store.replace_review(
        replacement,
        expected_sha256=legacy_digest,
        reason="replace invalid legacy review",
    )
    assert result["previous_sha256"] == legacy_digest
    assert result["sha256"] != legacy_digest
    assert store._path(result["supersession_receipt_path"]).is_file()
    assert store.read_review("20260730") == replacement
    manifest = _json.loads(store._path("a_share_reviews/manifest.json").read_text(encoding="utf-8"))
    assert manifest["a_share_reviews/20260730.json"] == result["sha256"]
