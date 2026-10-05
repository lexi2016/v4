"""Read-only M3/API fixtures and lifecycle contracts; no live service or UI claim."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from domains.daily_research_review import load_daily_research_review, GENERATOR_GAP
from ops import run_v35_macos_scheduler_daemon as daemon
from verification.scheduler_candidate.fixture_support import record_evidence


def review_fixture():
    receipt = {"status": "CANNOT_CONFIRM", "reason": "OFFLINE_FIXTURE_SOURCE_NOT_INCLUDED"}
    return {
        "schema_version": 1, "target_date": "2026-09-11", "trade_date": "2026-09-11",
        "data_as_of": "2026-09-11 17:25 CST", "generated_at": "2026-09-11 21:10 CST",
        "market_facts": {
            "breadth": {f"metric_{n}": {"value": n, "receipt": receipt} for n in range(14)},
            "feedback_matrix": {"details": [{"n": n, "receipt": receipt} for n in range(35)]},
            "loss_effect": {"available": False, "receipt": receipt},
            "theme_tree": {"themes": [{"tag": f"fixture-{n}", "receipt": receipt} for n in range(10)]},
            "event_ledger": {"events": [{"n": n} for n in range(19)],
                "loss_events": list(range(11)), "gain_events": list(range(5)), "split_events": list(range(3))},
        },
        "emotion_metrics": {name: {"available": False, "receipt": receipt}
                            for name in ("money_effect", "promotion", "ladder_gap")},
        "focus": {f"field_{n}": {"value": n, "receipt": receipt} for n in range(5)},
    }


def test_inprocess_m3_api_preserves_all_sections_receipts_and_generator_gap(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v35_api.review_router import create_review_router
    root = tmp_path / "dated-review-fixture"
    root.mkdir()
    source = review_fixture()
    path = root / "2026-09-11.json"
    raw = json.dumps(source).encode()
    path.write_bytes(raw)
    application = FastAPI()  # Only the read-only router, NOT the account app/lifespan.
    application.include_router(create_review_router(tmp_path / "empty-runtime-fixture", review_root=root))
    with TestClient(application) as client:
        response = client.get("/api/v3/review", params={"date": "20260911"})
    assert response.status_code == 200
    envelope = response.json()
    view = envelope["research_review"]
    assert view == load_daily_research_review("20260911", review_root=root)
    sections = (("market_facts", "breadth", "market_breadth"),
                ("market_facts", "feedback_matrix", "feedback_matrix"),
                ("market_facts", "loss_effect", "loss_effect"),
                ("market_facts", "theme_tree", "theme_tree"),
                ("market_facts", "event_ledger", "event_ledger"),
                ("emotion_metrics", "money_effect", "money_effect"),
                ("emotion_metrics", "promotion", "promotion"),
                ("emotion_metrics", "ladder_gap", "ladder_gap"))
    for parent, child, output in sections:
        assert view[output] == source[parent][child]
    assert view["focus"] == source["focus"]
    assert view["generation"]["owner"] == "CANNOT_CONFIRM"
    assert GENERATOR_GAP in view["cannot_confirm"]
    assert view["write_policy"] == "read_only"
    assert "market_reviews" in envelope  # Original A/H envelope still present.
    assert all(envelope[k] is False for k in ("orders_sent", "buy_gate_updated", "production_allowed"))
    assert view["artifact_sha256"] == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw
    record_evidence("m3-inprocess-api", {"fixture_only": True, "http_inprocess_status": 200,
        "live_api_verified": False, "ui_verified": False, "all_8_sections_equal": True,
        "row_counts": {"breadth_keys": 14, "feedback_details": 35, "themes": 10, "events": 19,
                       "loss_events": 11, "gain_events": 5, "split_events": 3, "focus": 5},
        "nested_receipts_preserved": True, "generator_owner": "CANNOT_CONFIRM",
        "original_A_H_envelope_retained": True, "artifact_sha256": view["artifact_sha256"], "writes": 0})


@pytest.mark.parametrize("defect", ["missing", "latest_only", "wrong_date", "bad_json"])
def test_m3_missing_or_wrong_artifact_stays_cannot_confirm(tmp_path, defect):
    source = review_fixture()
    if defect == "wrong_date":
        source["target_date"] = "2026-09-10"
    if defect != "missing":
        path = tmp_path / ("latest.json" if defect == "latest_only" else "2026-09-11.json")
        path.write_text("[" if defect == "bad_json" else json.dumps(source))
    result = load_daily_research_review("20260911", review_root=tmp_path)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["orders_sent"] is False


@pytest.mark.parametrize("case", ["missing_release", "mismatch_release", "unsafe", "repair"])
def test_existing_daemon_rejects_bad_identity_or_repair_without_dispatch(monkeypatch, case):
    monkeypatch.setenv("V35_RELEASE_ID", "fixture-release")
    argv = []
    if case == "missing_release":
        monkeypatch.delenv("V35_RELEASE_ID")
    elif case == "mismatch_release":
        argv = ["--release-id", "other-release"]
    elif case == "unsafe":
        monkeypatch.setenv("ORDERS_SENT", "true")
    else:
        argv = ["--repair-expected-old-input-sha256", "0" * 64]
    def never(*_args):
        raise AssertionError("invalid daemon config must not dispatch")
    assert daemon.run_daemon(argv, scheduler_main=never, install_signals=False) == 2
