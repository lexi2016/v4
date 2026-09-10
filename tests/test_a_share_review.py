from __future__ import annotations

import pytest

from contracts.a_share_review import A_SHARE_REVIEW_SCHEMA
from domains.a_share_review import build_a_share_review, validate_a_share_review
from domains.review_envelope import review_envelope
from infrastructure.data_store import _sha256
from ops.import_a_share_review_reference import normalize_a_share_review_reference


def _rows(count: int, *, trade_date: str = "20260730") -> list[dict[str, str]]:
    return [{"id": str(index), "trade_date": trade_date} for index in range(count)]


def _review() -> dict:
    return build_a_share_review(
        "20260730",
        big_picture=_rows(9),
        mainlines=[],
        core_stocks=[],
        observation_pool=_rows(12),
        trigger_rows=_rows(4),
        quality_gate_rows=_rows(7),
        source_sha256="a" * 64,
    )


def test_a_share_review_keeps_formal_core_and_observation_pool_distinct() -> None:
    review = _review()

    assert review["schema_version"] == A_SHARE_REVIEW_SCHEMA
    assert review["trade_date"] == "20260730"
    assert len(review["big_picture"]) == 9
    assert review["core_stocks"] == []
    assert len(review["observation_pool"]) == 12
    assert len(review["next_day_trigger_tree"]) == 4
    assert len(review["quality_gate"]) == 7
    assert review["production_allowed"] is False
    assert review["buy_gate_updated"] is False
    assert review["orders_sent"] is False


def test_a_share_review_rejects_invalid_source_sha_or_cross_date_rows() -> None:
    with pytest.raises(ValueError, match="SHA"):
        build_a_share_review(
            "20260730",
            big_picture=[], mainlines=[], core_stocks=[], observation_pool=[],
            trigger_rows=[], quality_gate_rows=[], source_sha256="not-a-sha",
        )
    with pytest.raises(ValueError, match="date"):
        build_a_share_review(
            "20260730",
            big_picture=[{"trade_date": "20260729"}], mainlines=[], core_stocks=[],
            observation_pool=[], trigger_rows=[], quality_gate_rows=[], source_sha256="a" * 64,
        )
    payload = _review()
    payload["big_picture"][0]["review_date"] = "20260729"
    with pytest.raises(ValueError, match="date"):
        validate_a_share_review(payload)


def test_review_envelope_exposes_one_canonical_a_review_and_legacy_projection() -> None:
    canonical = _review()
    canonical.update(
        {
            "summary_cards": _rows(2),
            "market_rows": _rows(3),
            "prior_plan_rows": _rows(4),
            "board_rows": _rows(5),
            "anchor_rows": _rows(6),
            "anchor_role_v3_rows": _rows(7),
            "intraday_handoff_rows": _rows(8),
            "catalyst_rows": _rows(9),
            "trigger_rows": _rows(10),
            "scenario_tree_rows": _rows(11),
            "video": {"status": "DAILY_VIDEO_NOT_LOCKED"},
            "video_gap_rows": _rows(12),
            "source_status_rows": _rows(13),
            "formal_pool_validation": {"status": "FORMAL_POOL_WEAK_REALIZATION"},
            "rule_adoption_rows": _rows(14),
            "video_learning_rows": _rows(15),
            "cannot_confirm_items": ["A_SPECIFIC_BOUNDARY"],
        }
    )
    hk = {"market": "HK", "model_selection_review": {"trade_date": "20260730"}}

    envelope = review_envelope("20260730", a_review=canonical, hk_review=hk)

    assert envelope["market_reviews"]["A"] == canonical
    assert envelope["market_reviews"]["HK"] == hk
    assert envelope["fupan_review_v3"]["first_screen_big_picture"] == canonical["big_picture"]
    assert envelope["fupan_review_v3"]["localized_role_rows"] == []
    assert envelope["fupan_review_v3"]["observation_pool"] == canonical["observation_pool"]
    for key in (
        "summary_cards", "market_rows", "prior_plan_rows", "board_rows", "anchor_rows",
        "anchor_role_v3_rows", "intraday_handoff_rows", "catalyst_rows", "trigger_rows",
        "scenario_tree_rows", "video", "video_gap_rows", "source_status_rows",
        "formal_pool_validation", "rule_adoption_rows", "video_learning_rows",
        "cannot_confirm_items",
    ):
        assert envelope["fupan_review_v3"][key] == canonical[key]


def test_review_envelope_keeps_missing_exact_date_typed_without_fallback() -> None:
    envelope = review_envelope("20260730", a_review=None, hk_review={"market": "HK"})

    assert envelope["market_reviews"]["A"]["status"] == "NOT_MATERIALIZED"
    assert envelope["market_reviews"]["A"]["trade_date"] == "20260730"


def test_exact_stage_review_rows_use_workbench_and_payload_sha(monkeypatch, tmp_path) -> None:
    from apps.api.v35_api import review_router

    trade_date = "20260824"
    monkeypatch.delenv("V35_STAGE_CENTER_SELECTION_ROOT", raising=False)
    payloads: dict[str, dict] = {}

    def read_workbench(self, selected_date: str, stage_id: str, limit: int = 10):
        payload = {
            "trade_date": selected_date,
            "stage": {"stage_id": stage_id, "status": "PARTIAL_WITH_WATCH_ROWS"},
            "response_source": "SHARED_STAGE_CENTER",
            "artifact_id": f"artifact-{stage_id}",
            "run_id": f"run-{stage_id}",
            "unified_rows": [
                {
                    "trade_date": selected_date,
                    "market": "A",
                    "symbol": "A.600001",
                    "trade_status": "WATCH_ONLY",
                },
                {
                    "trade_date": selected_date,
                    "market": "A",
                    "symbol": "A.600002",
                    "recommendation_status": "WATCH_ONLY",
                },
                {
                    "trade_date": selected_date,
                    "market": "A",
                    "symbol": "A.600003",
                    "recommendation_status": "BUY",
                    "trade_status": "WATCH_ONLY",
                    "formal_eligible": True,
                },
                {
                    "trade_date": "20260823",
                    "market": "A",
                    "symbol": "A.600004",
                    "trade_status": "WATCH_ONLY",
                },
                {
                    "trade_date": selected_date,
                    "target_trade_date": "20260823",
                    "market": "A",
                    "symbol": "A.600005",
                    "trade_status": "WATCH_ONLY",
                },
                {
                    "trade_date": selected_date,
                    "market": "HK",
                    "symbol": "HK.00001",
                    "recommendation_status": "WATCH_ONLY",
                },
            ],
        }
        payloads[stage_id] = payload
        assert limit == 50
        return payload

    monkeypatch.setattr(review_router.StageRunner, "read_workbench", read_workbench)

    rows, refs = review_router._read_exact_stage_review_rows(tmp_path, trade_date)

    assert len(rows) == 2 * len(review_router.FROZEN_STAGE_IDS)
    assert all(row["trade_date"] == trade_date for row in rows)
    assert all(row["recommendation_status"] == "WATCH_ONLY" for row in rows)
    assert all(row["role_type"] == "stage_validation_anchor" for row in rows)
    assert all(row["primary_role"] == "stage_validation_anchor" for row in rows)
    assert all(row["formal_eligible"] is False for row in rows)
    assert all(row["validation_scope"] == f"{trade_date} {row['stage_id']} exact-date stage evidence" for row in rows)
    assert all(row["cannot_confirm"] == "CANNOT_CONFIRM_FORMAL_REVIEW_BUNDLE" for row in rows)
    assert len(refs) == len(review_router.FROZEN_STAGE_IDS)
    assert refs[0]["source_role"] == "SHARED_STAGE_CENTER"
    assert refs[0]["response_source"] == "SHARED_STAGE_CENTER"
    assert refs[0]["artifact_id"] == "artifact-STAGE_0925"
    assert refs[0]["run_id"] == "run-STAGE_0925"
    assert refs[0]["artifact_sha256"] == _sha256(payloads["STAGE_0925"])
    assert "artifact_path" not in refs[0]
    assert "manifest_sha256" not in refs[0]
    assert "receipt_sha256" not in refs[0]


def test_exact_stage_review_rows_prefers_shared_stage_center(monkeypatch, tmp_path) -> None:
    import sys
    import types

    from apps.api.v35_api import review_router

    trade_date = "20260824"
    selection_root = tmp_path / "selection"
    selection_root.mkdir()
    payloads: dict[str, dict] = {}

    class FakeConsumer:
        def __init__(self, root):
            assert str(root) == str(selection_root)

        def get(self, selected_date: str, stage_id: str):
            payload = {
                "trade_date": selected_date,
                "stage_id": stage_id,
                "status": "PARTIAL_WITH_ROWS",
                "response_source": "SHARED_STAGE_CENTER",
                "artifact_id": f"bundle-{stage_id}",
                "run_id": f"shared-run-{stage_id}",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
                "markets": {
                    "A_SHARE": {
                        "artifact_id": f"a-artifact-{stage_id}",
                        "algorithm_id": "a-algorithm-v1",
                        "algorithm_sha256": "a" * 64,
                        "raw_artifact_sha256": "b" * 64,
                        "rows": [
                            {
                                "code": "A.600001",
                                "rank": 1,
                                "name": "共享观察",
                                "trade_status": "WATCH_ONLY",
                            },
                            {
                                "code": "A.600002",
                                "rank": 2,
                                "name": "恶意推荐",
                                "recommendation_status": "BUY",
                            },
                            {
                                "code": "A.600003",
                                "rank": 3,
                                "name": "形式可交易",
                                "trade_status": "WATCH_ONLY",
                                "formal_eligible": True,
                            },
                            {
                                "code": "A.600004",
                                "rank": 4,
                                "name": "跨日冲突",
                                "trade_status": "WATCH_ONLY",
                                "target_trade_date": "20260823",
                            },
                            {
                                "code": "A.600005",
                                "rank": 5,
                                "name": "交易日冲突",
                                "trade_status": "WATCH_ONLY",
                                "trade_date": "20260823",
                            },
                        ],
                    },
                    "HK_CONNECT": {"rows": []},
                },
            }
            payloads[stage_id] = payload
            return payload

        def ensure(self, *args, **kwargs):
            raise AssertionError("shared review must never call ensure")

    package = types.ModuleType("stage_center")
    package.__path__ = []
    consumer_module = types.ModuleType("stage_center.consumer")
    consumer_module.StageSelectionConsumer = FakeConsumer
    monkeypatch.setitem(sys.modules, "stage_center", package)
    monkeypatch.setitem(sys.modules, "stage_center.consumer", consumer_module)
    monkeypatch.setenv("V35_STAGE_CENTER_SELECTION_ROOT", str(selection_root))

    def forbidden_fallback(*args, **kwargs):
        raise AssertionError("shared stage center should take precedence")

    monkeypatch.setattr(review_router.StageRunner, "read_workbench", forbidden_fallback)

    rows, refs = review_router._read_exact_stage_review_rows(tmp_path, trade_date)

    assert len(rows) == len(review_router.FROZEN_STAGE_IDS)
    assert all(row["market"] == "A" for row in rows)
    assert all(row["trade_date"] == trade_date for row in rows)
    assert all(row["recommendation_status"] == "WATCH_ONLY" for row in rows)
    assert all(row["stage_id"] in review_router.FROZEN_STAGE_IDS for row in rows)
    assert all(row["role_type"] == "stage_validation_anchor" for row in rows)
    assert all(row["primary_role"] == "stage_validation_anchor" for row in rows)
    assert all(row["formal_eligible"] is False for row in rows)
    assert all(row["validation_scope"] == f"{trade_date} {row['stage_id']} exact-date stage evidence" for row in rows)
    assert all(row["cannot_confirm"] == "CANNOT_CONFIRM_FORMAL_REVIEW_BUNDLE" for row in rows)
    assert refs[0]["source_role"] == "SHARED_STAGE_CENTER"
    assert refs[0]["artifact_id"] == "bundle-STAGE_0925"
    assert refs[0]["algorithm_sha256"] == "a" * 64
    assert refs[0]["artifact_sha256"] == _sha256(payloads["STAGE_0925"])
    assert "manifest_sha256" not in refs[0]
    assert "receipt_sha256" not in refs[0]


def test_shared_stage_center_rejects_unsafe_payload_flags(monkeypatch, tmp_path) -> None:
    import sys
    import types

    from apps.api.v35_api import review_router

    trade_date = "20260824"
    selection_root = tmp_path / "selection"
    selection_root.mkdir()
    fallback_calls: list[str] = []

    class FakeConsumer:
        def __init__(self, root):
            assert str(root) == str(selection_root)

        def get(self, selected_date: str, stage_id: str):
            return {
                "trade_date": selected_date,
                "stage_id": stage_id,
                "status": "PARTIAL_WITH_ROWS",
                "response_source": "SHARED_STAGE_CENTER",
                "production_allowed": True,
                "buy_gate_updated": False,
                "orders_sent": False,
                "markets": {
                    "A_SHARE": {
                        "rows": [
                            {
                                "code": "A.600001",
                                "rank": 1,
                                "trade_status": "WATCH_ONLY",
                            }
                        ]
                    }
                },
            }

    package = types.ModuleType("stage_center")
    package.__path__ = []
    consumer_module = types.ModuleType("stage_center.consumer")
    consumer_module.StageSelectionConsumer = FakeConsumer
    monkeypatch.setitem(sys.modules, "stage_center", package)
    monkeypatch.setitem(sys.modules, "stage_center.consumer", consumer_module)
    monkeypatch.setenv("V35_STAGE_CENTER_SELECTION_ROOT", str(selection_root))

    def empty_fallback(self, selected_date: str, stage_id: str, limit: int = 10):
        fallback_calls.append(stage_id)
        raise ValueError("unsafe shared payload must not be projected")

    monkeypatch.setattr(review_router.StageRunner, "read_workbench", empty_fallback)

    rows, refs = review_router._read_exact_stage_review_rows(tmp_path, trade_date)

    assert rows == []
    assert refs == []
    assert fallback_calls == list(review_router.FROZEN_STAGE_IDS)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda review: review.update(production_allowed=True),
        lambda review: review.update(schema_version="invalid"),
        lambda review: review.update(source_sha256="invalid"),
    ],
)
def test_review_envelope_rejects_invalid_or_unsafe_canonical_a_review(mutation) -> None:
    canonical = _review()
    mutation(canonical)

    with pytest.raises(ValueError):
        review_envelope("20260730", a_review=canonical, hk_review={"market": "HK"})


@pytest.mark.parametrize(
    "source",
    [
        {"review_date": "20260730", "first_screen_big_picture": "not-a-list"},
        {"review_date": "20260730", "first_screen_big_picture": [{"title": "ok"}, "not-a-row"]},
    ],
)
def test_importer_rejects_malformed_present_row_collections(source: dict) -> None:
    with pytest.raises(ValueError, match="list|objects"):
        normalize_a_share_review_reference(source, "a" * 64)
