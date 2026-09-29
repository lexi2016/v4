"""Synthetic source/LLM boundaries. Never substitutes a graph or serializer."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from domains.research_review_generation._snapshot import FUNCTIONS, SECTIONS, SOURCE_ROLE
from domains.research_review_generation.owned_runtime import LlmIdentity, VibeRuntime
from domains.research_review_generation.vibe_core.prompts import RESEARCH_PACK

DATE = "2026-09-11"
ASOF = DATE + "T15:05:00+08:00"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def source(value, *, status="READY", reason=""):
    result = {"status": status, "source_id": "OFFLINE_FIXTURE_SYNTHETIC", "target_date": DATE,
              "data_as_of": ASOF, "source_sha256": digest(value), "temporal_basis": "TARGET_SESSION"}
    if reason:
        result["reason"] = reason
    return result


def snapshot_payload():
    metrics = {"money_effect": {"available": True, "sample": 2, "median": 0.5},
               "promotion": {"available": True, "overall": {"rate": 0.5}, "limit_up_count": 2},
               "ladder_gap": {"available": True, "continuous": True, "highest": 2}}
    facts = {"breadth": {"available": True, "up": 2, "down": 1},
             "feedback_matrix": {"available": True, "details": []},
             "loss_effect": {"available": True, "deep_loss_5_count": 0},
             "theme_tree": {"available": True, "themes": []},
             "event_ledger": {"available": True, "events": []}}
    values = {name: f"[合成离线样本 {DATE}] {name} 原始输入" for name in FUNCTIONS}
    values["get_emotion_metrics"] = [f"[合成离线样本 {DATE}] 派生指标", metrics]
    values["get_market_facts"] = [f"[合成离线样本 {DATE}] 市场事实", facts]
    sources = {name: source(value) for name, value in values.items()}
    for section in SECTIONS:
        parent, child = section.split(".")
        sources[section] = source(values["get_" + parent][1][child])
    news = {"query": f"{DATE} A股 今日 涨停 热门题材 板块 龙头 复盘", "text": "合成资讯，仅用于离线验证，不是行情。"}
    sources["news"] = source(news)
    return {"schema_version": "v4.vibe_review_inputs.v1", "source_role": SOURCE_ROLE,
            "trade_date": DATE, "target_date": DATE, "data_as_of": ASOF,
            "authority_id": "fixture-shared-authority", "authority_receipt_sha256": digest({"fixture": True, "date": DATE}),
            "calendar": {**source({"settled": True}), "settled": True},
            "functions": values, "sources": sources, "news": news,
            "provider_counts": {"kind": "fixture-reported-not-live", "physical_http_calls": 0}}


def focus(*, verification=True):
    return {"emotion_phase": "修复", "market_oneliner": "合成样本用于离线验证而非交易事实", "risk_alerts": ["仅为测试"],
            "focus_directions": [{"direction": "测试方向甲", "logic": "离线合成输入甲", "risk": "不可交易"},
                                 {"direction": "测试方向乙", "logic": "离线合成输入乙", "risk": "无真实行情"}],
            "verification_items": extract_items() if verification else []}


def extract_items():
    return [{"metric": "limit_up_count", "direction": "上升", "reason": "样本测试一"},
            {"metric": "highest_board", "direction": "持平", "reason": "样本测试二"}]


class FixtureLlm:
    def __init__(self, responses=None):
        self.model_name = "deepseek-flash"
        self.openai_api_base = "https://api.deepseek.com"
        self.temperature = 0.6
        self.request_timeout = 180
        self.max_retries = 2
        self.prompts = []
        self.responses = list(responses) if responses is not None else None

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if self.responses is None:
            return SimpleNamespace(content="[合成离线分析] " + "只描述输入样本，不是投资结论。" * 20)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else response)


def make_runtime(tmp_path: Path, *, verification=True, change=None):
    root = tmp_path / "v4-state"
    (root / "inputs").mkdir(parents=True)
    (root / "reflections").mkdir()
    raw = snapshot_payload()
    if change:
        change(raw)
    encoded = (json.dumps(raw, ensure_ascii=False, sort_keys=True) + "\n").encode()
    (root / "inputs" / f"{DATE}.json").write_bytes(encoded)
    history = {"prediction_date": "2026-09-10", "eval_date": DATE, "emotion_phase": "修复", "phase_eval": {
        "phase": "修复", "hit": True, "expected_direction": "up", "actual_direction": "up"}}
    (root / "reflections" / "2026-09-10.json").write_text(json.dumps(history, ensure_ascii=False))
    quick = FixtureLlm()
    deep = FixtureLlm([focus(verification=verification), {"items": extract_items()}])
    implementation = Path(__import__("domains.research_review_generation.owned_runtime", fromlist=["x"]).__file__).parent
    manifest_sha = hashlib.sha256((implementation / "OWNED_SOURCE_MANIFEST.json").read_bytes()).hexdigest()
    from domains.research_review_generation.model_provider import BoundLlm, read_profile
    profile_path = implementation.parents[1] / "contracts/vibe_runtime_profile.json"
    profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    profile_value = read_profile(profile_path, profile_sha)
    identity = LlmIdentity("deepseek-claude-code", "deepseek-flash", profile_sha)
    runtime = VibeRuntime(root, hashlib.sha256(encoded).hexdigest(), manifest_sha,
        BoundLlm(quick, identity, profile_value), BoundLlm(deep, identity, profile_value),
        identity, identity, RESEARCH_PACK)
    runtime, raw = reseal_fixture(runtime, raw)
    return runtime, raw


def reseal_fixture(runtime, raw):
    """Test writer pins complete synthetic evidence; never used by production."""
    from domains.research_review_generation._evidence import seal_snapshot, put_content
    from domains.research_review_generation._cache import encoded
    from domains.research_review_generation._owned_io import directory, records
    from infrastructure.owned_io import SafeRoot
    io = SafeRoot(runtime.state_root)
    raw_doc = {"schema":"v4.vibe_raw.v1", "review_target_date":DATE,
               "identity":{"provider":"SYNTHETIC_FIXTURE", "endpoint":"fixture", "session":DATE, "params":{}},
               "result":{"kind":"SDK_RETURN_JSON", "value":{"synthetic":True}}}
    ref = put_content(io, "raw", encoded(raw_doc))
    ref.update(session=DATE, kind="SDK_RETURN_JSON")
    with directory(runtime.state_root / "reflections") as fd:
        _, manifest, _ = records(fd)
    # Fixture construction may intentionally create a bad value/date/source. Leave
    # those shape failures to runtime.prepare, without pretending they are approved.
    path=runtime.state_root / "inputs" / f"{DATE}.json"
    path.unlink(missing_ok=True)
    try:
        sealed, input_sha = seal_snapshot(state_root=runtime.state_root, payload=raw,
            raw_refs=[ref], reflection_manifest=manifest,
            implementation_sha256=runtime.implementation_manifest_sha256)
    except Exception:
        # Only synthetically invalid fixtures reach this branch. They must still
        # fail prepare; there is no production fallback to unsealed inputs.
        data = encoded(raw);path.write_bytes(data)
        sealed, input_sha = raw, hashlib.sha256(data).hexdigest()
    return replace(runtime, snapshot_sha256=input_sha), sealed
