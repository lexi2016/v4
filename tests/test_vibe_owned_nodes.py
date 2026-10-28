"""Actual owned node functions/serializer. This is NOT a LangGraph execution test."""
from __future__ import annotations
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import os
import sys

import pytest

from domains.daily_research_review import load_daily_research_review
from domains.research_review_generation.generation import GenerationRefused, run_generation
from domains.research_review_generation.owned_runtime import initial_state
from domains.research_review_generation.vibe_core import preflight, reflection_context, serializer
from domains.research_review_generation.vibe_core.roles import ROLES
from domains.research_review_generation.vibe_core.synthesizer import create_review_judge
from vibe_ownership_fixtures import ASOF, DATE, FixtureLlm, focus, make_runtime


def node_chain(runtime):
    prepared = runtime.prepare(DATE, runtime.state_root / "reviews")
    snap = prepared.snapshot
    check = preflight.check(DATE, data=snap)
    assert check["ok"]
    state = initial_state(DATE, prepared.reflections)
    for role in ROLES:
        state.update(role.factory(runtime.quick, data=snap, search=snap.search, pack=runtime.pack)(state))
    state.update(create_review_judge(runtime.deep, pack=runtime.pack)(state))
    payload = serializer.serialize(state, DATE, check["warnings"] + snap.warnings(), pack=runtime.pack,
        reflection_record=reflection_context.latest_reflection(prepared.reflections, as_of=DATE),
        data_as_of=snap.data_as_of, generated_at="2026-09-13T12:00:00+00:00")
    return prepared, state, payload


@pytest.mark.parametrize("verification,deep_calls", [(True, 1), (False, 2)])
def test_actual_nodes_preserve_prompt_and_conditional_extraction(tmp_path, verification, deep_calls):
    runtime, raw = make_runtime(tmp_path, verification=verification)
    before = {p.name: p.read_bytes() for p in (runtime.state_root / "reflections").iterdir()}
    home = os.environ.get("HOME")
    prepared, state, payload = node_chain(runtime)
    assert len(runtime.quick._client.prompts) == 5
    assert len(runtime.deep._client.prompts) == deep_calls
    assert prepared.snapshot.lookup_counts["is_settled"] == 1
    assert prepared.snapshot.lookup_counts["get_market_facts"] == 1
    assert prepared.snapshot.lookup_counts["news_snapshot_read"] == 1
    assert all(prepared.snapshot.lookup_counts[n] == 2 for n in raw["functions"] if n != "get_market_facts")
    assert "2026-09-10预测" in runtime.deep._client.prompts[0]
    assert raw["news"]["text"] in runtime.quick._client.prompts[2]
    assert payload["emotion_metrics"] == raw["functions"]["get_emotion_metrics"][1]
    assert payload["market_facts"] == raw["functions"]["get_market_facts"][1]
    assert len(payload["focus"]["verification_items"]) == 2
    assert payload["data_as_of"] == ASOF and payload["generated_at"] != payload["data_as_of"]
    assert [x["key"] for x in payload["analysts"]] == [x.key for x in ROLES]
    assert os.environ.get("HOME") == home
    assert not any(n == "duanxian" or n.startswith("duanxian.") for n in sys.modules)
    assert before == {p.name: p.read_bytes() for p in (runtime.state_root / "reflections").iterdir()}
    assert not (runtime.state_root / "reviews").exists()


def test_actual_nodes_to_existing_writer_to_exact_reader(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    prepared, state, payload = node_chain(runtime)
    root = runtime.state_root / "reviews"
    # Deliberately labelled INJECTED, never relabelled real-graph ownership.
    receipt = run_generation(DATE, review_root=root, backend=lambda _: payload)
    assert receipt["mode"] == "mock_or_injected_backend"
    raw = (root / f"{DATE}.json").read_bytes()
    result = load_daily_research_review(DATE, review_root=root)
    assert result["status"] == "READY"
    assert result["artifact_sha256"] == receipt["artifact_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["source_artifact_sha256"] == receipt["artifact_sha256"]
    assert result["generation_status"] == "EXTERNAL_SOURCE_READ_ONLY"  # consumer was not modified
    assert json.loads(raw)["data_as_of"] == ASOF
    assert not (root / "latest.json").exists()
    calls = (len(runtime.quick._client.prompts), len(runtime.deep._client.prompts))
    with pytest.raises(GenerationRefused):
        run_generation(DATE, review_root=root, backend=lambda _: node_chain(runtime)[2])
    assert calls == (len(runtime.quick._client.prompts), len(runtime.deep._client.prompts))


def test_structured_retry_and_text_fallback_counts_preserved(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.deep._client.responses = ["bad JSON one", "bad JSON two", "纯文本兜底" * 80]
    prepared, state, payload = node_chain(runtime)
    assert len(runtime.quick._client.prompts) == 5 and len(runtime.deep._client.prompts) == 3
    assert payload["focus"] is None
    assert serializer.usable(payload)


def test_reflection_scoreboard_uses_all_history_not_only_last_five():
    history = []
    for i in range(30):
        d = date(2026, 7, 1) + timedelta(days=i)
        history.append({"prediction_date": d.isoformat(), "eval_date": (d+timedelta(days=1)).isoformat(),
            "phase_eval": {"phase": "修复", "hit": True, "expected_direction": "up", "actual_direction": "up"}})
    old = reflection_context.scoreboard(history[:-1], as_of=DATE)["phase"]
    new = reflection_context.scoreboard(history, as_of=DATE)["phase"]
    assert old["decided"] == 29 and old["enough_samples"] is False
    assert new["decided"] == 30 and new["enough_samples"] is True
    text = reflection_context.get_past_context(history, as_of=DATE)
    assert "30/30" in text and text.count("预测→") == 5


def test_nested_unsafe_flags_cannot_be_published(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    _, _, payload = node_chain(runtime)
    payload["market_facts"]["audit"] = {"orders_sent": True}
    with pytest.raises(GenerationRefused):
        run_generation(DATE, review_root=runtime.state_root / "reviews", backend=lambda _: payload)
    assert not (runtime.state_root / "reviews" / f"{DATE}.json").exists()


def test_future_date_refuses_before_backend(tmp_path):
    called=[]
    tomorrow=(date.today()+timedelta(days=1)).isoformat()
    with pytest.raises(GenerationRefused):
        run_generation(tomorrow, review_root=tmp_path/"reviews", backend=lambda d: called.append(d))
    assert called == []


def test_extra_legacy_facts_are_not_reduced_to_eight_panel_sections(tmp_path):
    def change(v):
        facts=v["functions"]["get_market_facts"][1]
        for key in ("seal_quality", "theme_structure", "by_board", "stats_context", "day_diff", "trend"):
            facts[key]={"fixture_original_key":key, "available":False, "reason":"not a real sample"}
    runtime, raw = make_runtime(tmp_path, change=change)
    _, _, payload=node_chain(runtime)
    assert payload["market_facts"] == raw["functions"]["get_market_facts"][1]


def test_provenance_flags_cannot_bypass_writer_guard(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    _, _, payload=node_chain(runtime)
    with pytest.raises(GenerationRefused):
        run_generation(DATE, review_root=runtime.state_root/"reviews",
            backend=lambda _: (payload,{"nested":{"orders_sent":True}}))
    assert not (runtime.state_root/"reviews"/f"{DATE}.json").exists()
