"""Activation gate: requires the REAL installed LangGraph; missing dependency FAILS.

Only LLM responses and the shared input snapshot are synthetic. No graph/node/
serializer/entry function is mocked, patched or skipped.
"""
import hashlib
import json
from pathlib import Path

import pytest

from domains.daily_research_review import load_daily_research_review
from domains.research_review_generation.generation import run_generation
from vibe_ownership_fixtures import ASOF, DATE, make_runtime


@pytest.mark.parametrize("verification,deep_calls", [(True, 1), (False, 2)])
def test_public_entry_runs_real_graph_then_exact_reader(tmp_path, verification, deep_calls):
    runtime, raw = make_runtime(tmp_path, verification=verification)
    root = runtime.state_root / "reviews"
    receipt = run_generation(DATE, review_root=root, runtime=runtime)
    artifact=(root/f"{DATE}.json").read_bytes()
    payload=json.loads(artifact)
    lineage=payload["v4_generation"]["source_provenance"]
    assert lineage["graph"]["implementation"].startswith("langgraph.")
    assert lineage["graph"]["recursion_limit"] == 50
    assert lineage["llm_invoke_counts"] == {"quick_invoke":5, "deep_invoke":deep_calls}
    assert lineage["snapshot"]["live_market_calls_in_generator"] == 0
    assert lineage["snapshot"]["live_news_calls_in_generator"] == 0
    assert lineage["snapshot"]["lookup_counts"]["is_settled"] == 1
    assert lineage["reflection"]["unchanged"] is True
    assert payload["target_date"] == payload["trade_date"] == DATE
    assert payload["data_as_of"] == ASOF
    assert payload["source_lineage"] == raw["sources"]
    envelope=load_daily_research_review(DATE, review_root=root)
    assert envelope["status"] == "READY"
    assert receipt["artifact_sha256"] == envelope["artifact_sha256"] == hashlib.sha256(artifact).hexdigest()
    assert receipt["mode"] == "v4_owned_graph_candidate"
    assert not (root/"latest.json").exists()
    (tmp_path/"real_graph_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
