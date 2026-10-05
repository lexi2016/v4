"""Synthetic body -> unchanged Python producer -> TS/DOM regression fixture.

No network, stored market data, calendar reads, or real-security assertions.
Run from the app root. The workspace shell is synthetic; research_attention
is the actual output of sanitize_cards/build_research_attention, not a TS mock.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v4.manager_research.workspace_projection import FLAGS, digest
from v4.manager_research.workspace_semantics import sanitize_cards
from v4.manager_research.workspace_plan import temporal_role
from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.workspace import _research_relation_material_input

DATE = "20261002"
CONTEXT = dict(plan_trade_date=DATE, focus_window_start="2026-09-29T16:10:00+08:00",
               research_cutoff="2026-10-02T10:00:00+08:00")


def fixture(*, after_cutoff=False, title_only=False):
    body = "合成甲公司签署了设备供应合同，合同金额为人民币两亿元。"
    acquired = "2026-10-03T08:02:00+08:00" if after_cutoff else "2026-09-30T08:02:00+08:00"
    raw = dict(symbol="HK.01234", name="合成甲公司", market="HK",
        title="SYNTHETIC 公告标题：设备供应合同", source_url="https://fixture.invalid/announcement",
        source_kind="OFFICIAL_ANNOUNCEMENT", source_row={} if title_only else {"body_text": body},
        claim_type="SOURCE_STATEMENT", evidence_id="synthetic-body-evidence",
        published_at="2026-09-30T08:00:00+08:00", available_at=acquired, retrieved_at=acquired,
        source_refs=[dict(payload_sha256=digest(body), source_url="https://fixture.invalid/announcement",
                          retrieved_at=acquired)], **FLAGS)
    raw["temporal_role"] = temporal_role(raw, CONTEXT)
    before = deepcopy(raw)
    accepted, rejected = sanitize_cards([raw])
    material_input = _research_relation_material_input(pre_connect_cards=accepted,
        post_connect_cards=accepted, relation_cards=accepted, connect_scope={},
        connect_rejections=[], material_discovery={}, selection_materials=[],
        existing={}, announcement_inputs={})
    attention = build_research_attention(DATE, context=CONTEXT, market_screen={}, stocks=[],
        material_cards=accepted, themes=[], announcement_observation={},
        us_market=dict(status="CANNOT_CONFIRM", research_material_input=material_input,
                       gaps=["SYNTHETIC_US_NOT_PROVIDED"]))
    assert raw == before
    if after_cutoff or title_only:
        assert not attention["cards"]
    else:
        assert len(attention["cards"]) == 1
        evidence = attention["cards"][0]["evidence"][0]
        assert evidence["evidence_quote"] == "合成甲公司签署了设备供应合同"
        assert evidence["evidence_quote"] in body
        assert evidence["propositions"][0]["event_date_claim"] is None
    shell = dict(schema_version="v4.manager_research.workspace.v1",
        semantic_version="20260921.manager-semantic.r3.v1", target_trade_date=DATE,
        input_identity=digest(["SYNTHETIC_SHELL", after_cutoff, title_only]),
        stocks=[], focus_symbols=[], company_events=[], rejected_relations=rejected,
        briefing={}, themes=[], materials=[], gaps=["SYNTHETIC_FIXTURE_NOT_LIVE_DATA"],
        plan_context=deepcopy(CONTEXT),
        read_context=dict(mode="CURRENT_DYNAMIC_PREVIEW", status="VERIFIED_WITH_GAPS",
            as_of=CONTEXT["research_cutoff"], candidate_count_known=True,
            contract="20260923.workspace-history-read.r1"),
        lanes=[dict(lane=lane, owner="SYNTHETIC", state="UNVERIFIED", target_date=DATE,
                    stock_count=None, last_attempt_at=None, last_success_at=None, next_plan=None,
                    failure_reasons=[]) for lane in ("STAGE", "CATALYST", "CLOSE")],
        summary=dict(stock_count=0, relation_count=0, theme_count=0, reused_material_count=0,
                     formal_recommendation_count=0), research_attention=attention, **FLAGS)
    return shell


if __name__ == "__main__":
    print(json.dumps(dict(current=fixture(), after_cutoff=fixture(after_cutoff=True),
                         title_only=fixture(title_only=True)), ensure_ascii=False))
