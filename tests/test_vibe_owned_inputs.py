from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest

from domains.research_review_generation._owned_io import BoundaryError, directory, read_json, records, write_bytes
from domains.research_review_generation._snapshot import ReviewSnapshot
from domains.research_review_generation.owned_runtime import verify_owned_sources
from domains.research_review_generation.vibe_core import preflight, reflection_context
from vibe_ownership_fixtures import DATE, make_runtime, snapshot_payload


def test_one_snapshot_reused_by_preflight_and_consumers(tmp_path):
    runtime, raw = make_runtime(tmp_path)
    prepared = runtime.prepare(DATE, runtime.state_root / "reviews")
    snap = prepared.snapshot
    assert preflight.check(DATE, data=snap)["ok"]
    first = snap.get_emotion_metrics(DATE)
    first[1]["money_effect"]["sample"] = 999
    assert snap.get_emotion_metrics(DATE)[1]["money_effect"]["sample"] == 2
    assert snap.lookup_counts["is_settled"] == 1
    assert prepared.provenance["snapshot"]["disk_reads"] == 1
    assert prepared.provenance["authority_receipt_independently_verified"] is True


@pytest.mark.parametrize("case", ["date", "source_role", "asof", "timezone", "missing_source", "current_only", "unknown_as_ready", "calendar", "news_date"])
def test_bad_source_binding_fails_before_llm(tmp_path, case):
    def change(v):
        if case == "date": v["target_date"] = "2026-09-10"
        elif case == "source_role": v["source_role"] = "OTHER"
        elif case == "asof": v["data_as_of"] = "2026-09-12T15:05:00+08:00"
        elif case == "timezone": v["data_as_of"] = DATE + "T15:05:00"
        elif case == "missing_source": del v["sources"]["market_facts.breadth"]
        elif case == "current_only": v["sources"]["get_capital_data"]["temporal_basis"] = "CURRENT_ONLY"
        elif case == "unknown_as_ready": v["sources"]["market_facts.breadth"].update(status="CANNOT_CONFIRM", reason="no sample")
        elif case == "calendar": v["calendar"]["settled"] = False
        elif case == "news_date": v["news"]["query"] = "today"
    runtime, _ = make_runtime(tmp_path, change=change)
    with pytest.raises(BoundaryError): runtime.prepare(DATE, runtime.state_root / "reviews")
    assert runtime.quick._client.prompts == runtime.deep._client.prompts == []


def test_partial_optional_source_stays_unknown(tmp_path):
    def change(v):
        v["sources"]["market_facts.theme_tree"].update(status="CANNOT_CONFIRM", reason="fixture missing")
        v["functions"]["get_market_facts"][1]["theme_tree"] = {"available": False, "reason": "fixture missing"}
        v["sources"]["get_capital_data"].update(status="CANNOT_CONFIRM", reason="no historical close source")
    runtime, _ = make_runtime(tmp_path, change=change)
    p = runtime.prepare(DATE, runtime.state_root / "reviews")
    result = preflight.check(DATE, data=p.snapshot)
    assert result["ok"] and "资金面" in result["missing_optional"]
    assert p.snapshot.get_market_facts(DATE)[1]["theme_tree"]["available"] is False
    assert any("CANNOT_CONFIRM" in s for s in p.snapshot.warnings())


def test_missing_core_is_not_silently_replaced(tmp_path):
    def change(v): v["sources"]["get_sentiment_data"].update(status="CANNOT_CONFIRM", reason="no pool")
    runtime, _ = make_runtime(tmp_path, change=change)
    p = runtime.prepare(DATE, runtime.state_root / "reviews")
    assert not preflight.check(DATE, data=p.snapshot)["ok"]


def test_reflection_visibility_and_single_read(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    r = runtime.state_root / "reflections"
    future = {"prediction_date": DATE, "eval_date": "2026-09-12", "emotion_phase": "亢奋"}
    (r / f"{DATE}.json").write_text(json.dumps(future))
    (r / "2026-09-09.json").write_text('{broken')
    from vibe_ownership_fixtures import reseal_fixture
    runtime, _ = reseal_fixture(runtime, _)
    p = runtime.prepare(DATE, runtime.state_root / "reviews")
    context = reflection_context.get_past_context(p.reflections, as_of=DATE)
    assert "2026-09-10预测" in context and "亢奋" not in context
    assert reflection_context.latest_reflection(p.reflections, as_of=DATE)["prediction_date"] == "2026-09-10"
    assert len(p.provenance["reflection"]["before_manifest"]) == 3
    assert len(p.provenance["reflection"]["warnings"]) == 1


def test_input_sha_and_source_pin_drift_refused(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    with pytest.raises(BoundaryError, match="snapshot SHA"):
        replace(runtime, snapshot_sha256="0" * 64).prepare(DATE, runtime.state_root / "reviews")
    with pytest.raises(BoundaryError, match="manifest SHA"):
        verify_owned_sources("0" * 64)


def test_custom_pack_not_silently_defaulted(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    with pytest.raises(BoundaryError, match="custom prompt"):
        replace(runtime, pack=object()).prepare(DATE, runtime.state_root / "reviews")


def test_root_binding_refuses_directory_outside_state(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    with pytest.raises(BoundaryError): runtime.prepare(DATE, tmp_path / "unowned")
    assert not (tmp_path / "unowned").exists()


def test_symlink_input_and_reflection_refused(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    original = runtime.state_root / "inputs" / f"{DATE}.json"
    outside = tmp_path / "outside.json"
    original.rename(outside)
    original.symlink_to(outside)
    with pytest.raises((BoundaryError, OSError)): runtime.prepare(DATE, runtime.state_root / "reviews")


def test_no_clobber_and_traversal_on_directory_fd(tmp_path):
    root = tmp_path / "owned"
    with directory(root, create=True) as fd:
        write_bytes(fd, "one.json", b"{}", replace=False)
        with pytest.raises(BoundaryError): write_bytes(fd, "../outside.json", b"{}", replace=True)
        with pytest.raises(BoundaryError): write_bytes(fd, "one.json", b'{"changed":true}', replace=False)
        assert read_json(fd, "one.json")[0] == {}
    assert not (tmp_path / "outside.json").exists()


def test_cross_date_lookup_refused(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    p = runtime.prepare(DATE, runtime.state_root / "reviews")
    with pytest.raises(BoundaryError): p.snapshot.get_market_facts("2026-09-10")
    with pytest.raises(BoundaryError): p.snapshot.is_settled("2026-09-10")
    with pytest.raises(BoundaryError): p.snapshot.search("latest news")


def test_public_entry_refuses_outside_root_without_creating_it(tmp_path):
    from domains.research_review_generation.generation import GenerationRefused, run_generation
    runtime, _ = make_runtime(tmp_path)
    outside = tmp_path / "unowned"
    with pytest.raises(GenerationRefused):
        run_generation(DATE, review_root=outside, runtime=runtime)
    assert not outside.exists()
