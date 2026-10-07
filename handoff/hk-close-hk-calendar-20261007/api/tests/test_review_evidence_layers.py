from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from domains.review_evidence_layers import load_review_core_a_share_review


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_bundle(root: Path, trade_date: str = "20260821") -> tuple[dict, dict]:
    run_id = "rbv1-20260821-test000000000000000000"
    compatibility = {
        "schema_version": "review_core.v3_compatibility.v1",
        "trade_date": trade_date,
        "summary_cards": [{"trade_date": trade_date, "title": "看什么", "value": "保留富复盘"}],
        "market_rows": [{"trade_date": trade_date, "metric": "上涨", "value": 2412}],
        "prior_plan_rows": [{"trade_date": trade_date, "mapped_theme": "医药", "close_result": "部分兑现"}],
        "board_rows": [{"trade_date": trade_date, "section": "医药", "today_role": "主线"}],
        "anchor_rows": [{"trade_date": trade_date, "theme": "医药", "stocks": ["汉森制药"]}],
        "anchor_role_v3_rows": [{"trade_date": trade_date, "stock": "汉森制药", "role_type": "leader"}],
        "intraday_handoff_rows": [{"trade_date": trade_date, "theme": "医药", "morning_status": "承接"}],
        "catalyst_rows": [{"trade_date": trade_date, "direction": "医药", "quality": "metadata_only"}],
        "trigger_rows": [{"trade_date": trade_date, "condition": "医药", "need": "前排承接"}],
        "scenario_tree_rows": [{"trade_date": trade_date, "scenario": "符合预期"}],
        "video": {"trade_date": trade_date, "status": "DAILY_VIDEO_NOT_LOCKED", "target_trade_date": trade_date},
        "video_gap_rows": [],
        "source_status_rows": [{"trade_date": trade_date, "source": "TDX", "status": "READY"}],
        "formal_pool_validation": {"trade_date": trade_date, "status": "FORMAL_POOL_WEAK_REALIZATION"},
        "rule_adoption_rows": [{"trade_date": trade_date, "decision": "blocked"}],
        "video_learning_rows": [],
        "cannot_confirm_items": ["DAILY_VIDEO_NOT_LOCKED"],
        "mainlines": [], "core_stocks": [], "big_picture": [], "observation_pool": [],
        "next_day_trigger_tree": [], "next_day_trigger_tree_v2": [],
        "headline": "市场分歧", "market_regime": "分歧", "risk_tone": "保持观察",
        "display_status": "数据部分", "status": "FUPAN_PAGE_COMPLETED_DATA_PARTIAL",
        "source_refs": [], "safety_flags": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    independent = {
        "schema_version": "local_fupan_independent_review.v1",
        "review_date": trade_date,
        "video_input_count": 0,
        "video_augmented": False,
        "video_boundary": "VIDEO_ONLY_LAYER_7_ENHANCEMENT",
        "market_judgment": {"market_phase": "分歧", "conclusion": "分歧"},
        "board_conclusions": [], "stock_role_conclusions": [], "tomorrow_observation": [],
        "boundary": {"dev_used": False, "future_result_used": False, "holdout_used": False, "model_promoted": False, "not_buy_advice": True, "research_only": True, "target_video_used": False},
        "abstain": False, "abstain_reason": "",
    }
    bundle = {
        "schema_version": "review_core.review_bundle.v1", "trade_date": trade_date, "run_id": run_id,
        "status": "PARTIAL", "market_scope": "FULL_MARKET", "market_completeness": "FULL_MARKET_VERIFIED",
        "compatibility": compatibility, "independent_review": independent, "cannot_confirm": ["DAILY_VIDEO_NOT_LOCKED"],
        "source_refs": [], "video": compatibility["video"], "video_input_count": 0, "video_augmented": False,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "safety_flags": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    bundle_path = root / "review_bundle" / trade_date / "runs" / run_id / "review_bundle.json"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    bundle_sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "review_core.review_bundle.manifest.v1", "trade_date": trade_date,
        "run_id": run_id, "bundle_path": str(bundle_path.relative_to(root)),
        "bundle_schema_version": "review_core.review_bundle.v1", "bundle_sha256": bundle_sha,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "safety_flags": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    manifest_path = bundle_path.parent / "manifest.json"
    receipt_path = bundle_path.parent / "receipt.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    receipt = {
        "schema_version": "review_core.review_bundle.receipt.v1", "trade_date": trade_date,
        "run_id": run_id, "bundle_sha256": bundle_sha, "manifest_sha256": manifest_sha,
        "safety_flags": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    current = {
        "schema_version": "review_core.review_bundle.current.v1", "trade_date": trade_date, "run_id": run_id,
        "bundle_path": str(bundle_path.relative_to(root)), "run_path": str(bundle_path.parent.relative_to(root)),
        "manifest_path": str(manifest_path.relative_to(root)), "receipt_path": str(receipt_path.relative_to(root)),
        "bundle_sha256": bundle_sha,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "safety_flags": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    current_path = root / "review_bundle" / trade_date / "current.json"
    current_path.write_text(json.dumps(current, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return bundle, current


def _rewrite_bundle_chain(root: Path, bundle: dict, current: dict) -> None:
    """Rewrite a fixture bundle and its identity chain after a controlled mutation."""
    bundle_path = root / current["bundle_path"]
    manifest_path = root / current["manifest_path"]
    receipt_path = root / current["receipt_path"]
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    bundle_sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bundle_sha256"] = bundle_sha
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["bundle_sha256"] = bundle_sha
    receipt["manifest_sha256"] = manifest_sha
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    current.update(
        bundle_sha256=bundle_sha,
        manifest_sha256=manifest_sha,
        receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    )
    (root / "review_bundle" / current["trade_date"] / "current.json").write_text(
        json.dumps(current, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def test_review_core_bridge_keeps_exact_date_rich_rows_and_pointer_evidence(tmp_path: Path) -> None:
    bundle, current = _write_bundle(tmp_path)

    review = load_review_core_a_share_review("20260821", tmp_path)

    assert review["source_role"] == "REVIEW_CORE_BUNDLE_V1"
    assert review["source_run_id"] == current["run_id"]
    assert review["artifact_sha256"] == current["bundle_sha256"]
    for key in ("summary_cards", "market_rows", "prior_plan_rows", "board_rows", "anchor_rows", "anchor_role_v3_rows", "intraday_handoff_rows", "catalyst_rows", "trigger_rows", "scenario_tree_rows", "video", "video_gap_rows", "source_status_rows", "formal_pool_validation", "rule_adoption_rows", "video_learning_rows", "cannot_confirm_items"):
        assert key in review
    assert len(review["board_rows"]) == 1
    assert len(review["anchor_role_v3_rows"]) == 1
    assert review["production_allowed"] is False
    assert review["buy_gate_updated"] is False
    assert review["orders_sent"] is False


def test_review_core_bridge_preserves_headline_mainlines_and_independent_board_rows(tmp_path: Path) -> None:
    bundle, current = _write_bundle(tmp_path)
    compatibility = bundle["compatibility"]
    compatibility["headline"] = "真实完整复盘标题"
    compatibility["mainlines"] = [
        {"trade_date": "20260821", "section": f"主线-{index}"}
        for index in range(13)
    ]
    compatibility["board_rows"] = [
        {"trade_date": "20260821", "section": f"全板块-{index}"}
        for index in range(10)
    ]
    _rewrite_bundle_chain(tmp_path, bundle, current)

    review = load_review_core_a_share_review("20260821", tmp_path)

    assert review["headline"] == "真实完整复盘标题"
    assert len(review["mainlines"]) == 13
    assert len(review["board_rows"]) == 10
    assert review["mainlines"][0]["section"] == "主线-0"
    assert review["board_rows"][0]["section"] == "全板块-0"


@pytest.mark.parametrize(
    "video",
    [
        {"status": "READY"},
        {"status": "READY", "target_trade_date": "20260820", "trade_date": "20260820"},
        {
            "status": "READY",
            "target_trade_date": "20260821",
            "trade_date": "20260821",
            "artifact_refs": [{"kind": "video_session", "path": "review/2026-08-20/runs/old/video_session.json"}],
        },
    ],
)
def test_review_core_bridge_fail_closes_invalid_video_to_same_day_empty_state(tmp_path: Path, video: dict) -> None:
    bundle, current = _write_bundle(tmp_path)
    bundle["compatibility"]["video"] = video
    _rewrite_bundle_chain(tmp_path, bundle, current)

    review = load_review_core_a_share_review("20260821", tmp_path)
    projected = review["video"]

    assert projected["status"] == "CANNOT_CONFIRM"
    assert projected["date_scope"] == "DAILY_VIDEO_NOT_LOCKED"
    assert projected["target_trade_date"] == "20260821"
    assert projected["trade_date"] == "20260821"
    assert projected["artifact_refs"] == []
    assert review["cannot_confirm_items"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("board_rows", "not-a-list"),
        ("anchor_role_v3_rows", [{"trade_date": "20260821"}, "not-a-row"]),
        ("video_gap_rows", {"status": "bad"}),
        ("video", ["not-an-object"]),
    ],
)
def test_review_core_bridge_rejects_malformed_present_rich_fields(tmp_path: Path, field: str, value: object) -> None:
    bundle, current = _write_bundle(tmp_path)
    bundle["compatibility"][field] = value
    _rewrite_bundle_chain(tmp_path, bundle, current)

    with pytest.raises(ValueError, match="Review Core|video"):
        load_review_core_a_share_review("20260821", tmp_path)


@pytest.mark.parametrize(
    "location,value",
    [
        ("bundle.cannot_confirm", "not-a-string-list"),
        ("compatibility.summary", []),
        ("compatibility.market_summary", []),
    ],
)
def test_review_core_bridge_rejects_malformed_bundle_context_types(tmp_path: Path, location: str, value: object) -> None:
    bundle, current = _write_bundle(tmp_path)
    if location == "bundle.cannot_confirm":
        bundle["cannot_confirm"] = value
    else:
        bundle["compatibility"][location.split(".", 1)[1]] = value
    _rewrite_bundle_chain(tmp_path, bundle, current)

    with pytest.raises(ValueError, match="cannot_confirm|summary|market_summary"):
        load_review_core_a_share_review("20260821", tmp_path)


def test_review_core_bridge_rejects_malformed_safety_mapping(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    current_path = tmp_path / "review_bundle" / "20260821" / "current.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    current["safety_flags"] = "malformed"
    current_path.write_text(json.dumps(current), encoding="utf-8")

    with pytest.raises(ValueError, match="safety"):
        load_review_core_a_share_review("20260821", tmp_path)


def test_review_core_bridge_rejects_pointer_sha_mismatch_and_never_falls_back(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    current_path = tmp_path / "review_bundle" / "20260821" / "current.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    current["bundle_sha256"] = "0" * 64
    current_path.write_text(json.dumps(current), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA"):
        load_review_core_a_share_review("20260821", tmp_path)

    with pytest.raises((FileNotFoundError, ValueError)):
        load_review_core_a_share_review("20260820", tmp_path)


def test_review_core_bridge_rejects_manifest_identity_mismatch(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    manifest_path = next((tmp_path / "review_bundle" / "20260821" / "runs").glob("*/manifest.json"))
    current_path = tmp_path / "review_bundle" / "20260821" / "current.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = "wrong-run"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    current = json.loads(current_path.read_text(encoding="utf-8"))
    current["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    current_path.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest identity"):
        load_review_core_a_share_review("20260821", tmp_path)


def test_review_core_root_resolution_does_not_leak_tmp_fixtures(monkeypatch, tmp_path: Path) -> None:
    from domains.review_evidence_layers import _root_for

    monkeypatch.delenv("REVIEW_CORE_DATA_ROOT", raising=False)
    fixture = tmp_path / ".runtime" / "data"
    assert _root_for(fixture) == fixture.resolve()


def test_review_core_bridge_keeps_verified_video_when_asr_execution_path_has_another_date(tmp_path: Path) -> None:
    bundle, current = _write_bundle(tmp_path, trade_date="20260824")
    video = dict(bundle["compatibility"]["video"])
    video.update(
        {
            "status": "READY",
            "bv_id": "BV1gR8e6bETL",
            "asr_segment_count": 635,
            "artifact_refs": [
                {
                    "kind": "video_session",
                    "path": "review/20260824/runs/rcv1/video_session.json",
                },
                {
                    "kind": "asr_trace",
                    "path": "review/20260824/runs/rcv1/asr/trace_path",
                    "source_path": (
                        "/state/data/asr/cache/BV1gR8e6bETL/"
                        "funasr_seaco_run_manifest_20260826_015902.json"
                    ),
                },
            ],
        }
    )
    bundle["compatibility"]["video"] = video
    bundle["compatibility"]["cannot_confirm_items"] = []
    bundle["cannot_confirm"] = []
    bundle["video"] = video
    _rewrite_bundle_chain(tmp_path, bundle, current)

    review = load_review_core_a_share_review("20260824", tmp_path)

    assert review["video"]["status"] == "READY"
    assert review["video"]["bv_id"] == "BV1gR8e6bETL"
    assert review["video"]["asr_segment_count"] == 635
    assert not any("DAILY_VIDEO_NOT_LOCKED" in item for item in review["cannot_confirm_items"])


def test_review_core_bridge_rejects_cross_date_review_namespace_even_with_later_asr_path(tmp_path: Path) -> None:
    bundle, current = _write_bundle(tmp_path, trade_date="20260824")
    video = dict(bundle["compatibility"]["video"])
    video.update(
        {
            "status": "READY",
            "bv_id": "BV1gR8e6bETL",
            "asr_segment_count": 635,
            "artifact_refs": [
                {
                    "kind": "video_session",
                    "path": "review/20260820/runs/old/video_session.json",
                },
                {
                    "kind": "asr_trace",
                    "path": "review/20260824/runs/rcv1/asr/trace_path",
                    "source_path": "/state/data/asr/cache/funasr_run_manifest_20260826.json",
                },
            ],
        }
    )
    bundle["compatibility"]["video"] = video
    bundle["video"] = video
    _rewrite_bundle_chain(tmp_path, bundle, current)

    review = load_review_core_a_share_review("20260824", tmp_path)

    assert review["video"]["status"] == "CANNOT_CONFIRM"
    assert review["video"]["bv_id"] == ""
    assert review["video"]["artifact_refs"] == []


def test_review_core_root_resolution_honors_explicit_environment_root(monkeypatch, tmp_path: Path) -> None:
    from domains.review_evidence_layers import _root_for

    configured = tmp_path / "configured-review-core"
    monkeypatch.setenv("REVIEW_CORE_DATA_ROOT", str(configured))
    assert _root_for(tmp_path / "unrelated-runtime-data") == configured.resolve()


def test_review_core_root_resolution_maps_installed_v35_data_root() -> None:
    from domains.review_evidence_layers import _root_for

    home = Path.home()
    active = home / "Library" / "Application Support" / "com.lexi.v35.local" / "state" / "data"
    standard = home / "Library" / "Application Support" / "com.lexi.review-core.local" / "state" / "data"
    resolved = _root_for(active)
    assert resolved == (standard.resolve() if (standard / "review_bundle").is_dir() else active.resolve())


def test_review_router_does_not_fallback_when_review_core_current_is_damaged(tmp_path: Path) -> None:
    from apps.api.v35_api.review_router import create_review_router

    bundle, current = _write_bundle(tmp_path)
    (tmp_path / current["bundle_path"]).write_text("{}", encoding="utf-8")
    router = create_review_router(tmp_path)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/api/v3/review")

    payload = endpoint("20260821")

    assert payload["market_reviews"]["A"]["status"] == "NOT_MATERIALIZED"
    assert "REVIEW_CORE_BUNDLE_INVALID" in payload["market_reviews"]["A"]["cannot_confirm"][0]
    assert payload["market_reviews"]["HK"]["model_selection_review"]["status"] == "CANNOT_CONFIRM"


def test_review_router_projects_same_day_native_hk_artifact_with_full_provenance(tmp_path: Path) -> None:
    from apps.api.v35_api.review_router import create_review_router
    from domains.close_review import build_native_close_review
    from infrastructure.review_store import ReviewStore

    _write_bundle(tmp_path)
    native = build_native_close_review(
        "20260821",
        close_rows=[
            {
                "trade_date": "20260821",
                "code": "HK.00001",
                "name": "native-row",
                "close": 11.0,
                "pre_close": 10.0,
                "amount": 1.0,
            }
        ],
        model_rows=[],
        stage_rows={},
        close_source_sha256="a" * 64,
    )
    ReviewStore(tmp_path).import_reference(native)

    router = create_review_router(tmp_path)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/api/v3/review")
    payload = endpoint("20260821")
    hk_review = payload["market_reviews"]["HK"]["model_selection_review"]

    assert hk_review["source_merge_role"] == "V35_NATIVE_REVIEW_STORE"
    assert hk_review["artifact_role"] == "V3_5_NATIVE_CLOSE_MODEL"
    assert hk_review["source_sha256"] == "a" * 64
    assert hk_review["reference_snapshot"] is False


@pytest.mark.parametrize(
    "location,value",
    [
        ("bundle.cannot_confirm", "not-a-string-list"),
        ("compatibility.summary", []),
        ("compatibility.market_summary", []),
    ],
)
def test_review_router_fail_closes_malformed_bundle_context_types(tmp_path: Path, location: str, value: object) -> None:
    from apps.api.v35_api.review_router import create_review_router

    bundle, current = _write_bundle(tmp_path)
    if location == "bundle.cannot_confirm":
        bundle["cannot_confirm"] = value
    else:
        bundle["compatibility"][location.split(".", 1)[1]] = value
    _rewrite_bundle_chain(tmp_path, bundle, current)
    router = create_review_router(tmp_path)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/api/v3/review")

    payload = endpoint("20260821")

    assert payload["market_reviews"]["A"]["status"] == "NOT_MATERIALIZED"
    assert payload["market_reviews"]["HK"]["model_selection_review"]["status"] == "CANNOT_CONFIRM"
