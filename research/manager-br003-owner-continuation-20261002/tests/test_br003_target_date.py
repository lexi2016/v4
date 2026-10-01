from copy import deepcopy
from unittest.mock import patch

import producer_cases as pc
import test_cross_boundary as tc
from test_cross_boundary import browser_page
from v4.manager_research import workspace as owner
from v4.manager_research.announcement_materials import mirror_material
from v4.manager_research.connect_selection import filter_cards
from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.workspace import get_workspace
from v4.manager_research.workspace_announcements import _project_eastmoney_hk
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.workspace_projection import build_workspace, digest, timestamp

TARGET = "20261002"
CAPTURE = "20260929"
CONTEXT = dict(
    plan_trade_date=TARGET,
    market_session=CAPTURE,
    research_cutoff="2026-10-02T09:28:00+08:00",
    focus_window_start="2026-09-29T16:10:00+08:00",
    source_dates=[CAPTURE],
)


def historical_workspace():
    pc.DAY = TARGET
    pc.CONTEXT = CONTEXT
    pc.IDENTITY = dict(
        status="OWNER_VERIFIED",
        source_date=CAPTURE,
        artifact_sha256="a" * 64,
        manifest_sha256="b" * 64,
        owner="SYNTHETIC_NATIVE_MASTER_BOUNDARY",
    )
    tc.DAY = TARGET

    raw = pc.raw_doc(text="本公司工业机器人订单增加。")
    product = dict(
        target_trade_date=CAPTURE,
        documents=[raw],
        context=dict(
            target_trade_date=CAPTURE,
            research_cutoff="2026-09-29T23:59:00+08:00",
        ),
        generated_at="2026-09-29T18:10:00+08:00",
    )
    docs, gaps = _project_eastmoney_hk(product, CONTEXT)
    assert not gaps and len(docs) == 1
    doc = docs[0]
    assert doc["target_trade_date"] == TARGET
    assert doc["capture_trade_date"] == CAPTURE

    capture = dict(
        source="EASTMONEY_HK",
        readback_status="VERIFIED",
        sha256="3" * 64,
        run_id="4" * 32,
        target_trade_date=CAPTURE,
    )
    material = mirror_material(doc, capture)
    assert material["capture_trade_date"] == CAPTURE

    identity = deepcopy(pc.IDENTITY)
    cards = project_material_discovery([material], pc.NAMES, identity, CONTEXT)
    scope = dict(
        status="OWNER_VERIFIED",
        codes=sorted(pc.NAMES),
        target_trade_date=TARGET,
        membership_semantics="TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2",
        source=dict(
            source_date=TARGET,
            market="HK_CONNECT",
            role="HK_CONNECT_FULL_MARKET_AUTHORITY",
            sha256="5" * 64,
        ),
        identity=digest([TARGET, sorted(pc.NAMES), "5" * 64]),
    )
    cards, _ = filter_cards(cards, scope, target_date=TARGET)

    lane = pc.observation([])
    us = pc.us_market()
    attention = build_research_attention(
        TARGET,
        context=CONTEXT,
        market_screen=None,
        stocks=[],
        material_cards=cards,
        themes=[],
        announcement_observation=lane,
        us_market=us,
    )
    value = build_workspace(
        TARGET,
        catalyst={"target_trade_date": TARGET, "status": "NOT_RUN"},
        plan_context=CONTEXT,
    )
    value.update(
        announcement_observation=lane,
        us_market_attention=us,
        research_attention=attention,
    )
    with patch.object(owner, "_compute_workspace", return_value=value):
        value = get_workspace(
            None,
            TARGET,
            include_saved=False,
            view="dynamic",
            now=timestamp(CONTEXT["research_cutoff"]),
        )

    row = next(
        evidence
        for card in value["research_attention"]["cards"]
        for evidence in card["evidence"]
        if evidence["evidence_lane"] == "COMPANY_MATERIAL"
    )
    assert row["owner_document"]["target_trade_date"] == TARGET
    assert row["owner_document"]["capture_trade_date"] == CAPTURE
    assert row["owner_capture"]["target_trade_date"] == CAPTURE
    return value, row


def test_history_capture_date_is_separate_from_consumer_target(browser_page):
    value, row = historical_workspace()
    visible = tc.render(browser_page, value)
    assert visible["ok"] is True
    assert row["owner_document"]["target_trade_date"] == TARGET
    assert row["owner_document"]["capture_trade_date"] == CAPTURE
    assert row["owner_capture"]["target_trade_date"] == CAPTURE


def test_wrong_owner_document_target_date_is_rejected(browser_page):
    value, row = historical_workspace()
    row["owner_document"]["target_trade_date"] = CAPTURE
    assert row["owner_document"]["capture_trade_date"] == CAPTURE
    assert row["owner_capture"]["target_trade_date"] == CAPTURE
    visible = tc.render(browser_page, value)
    assert visible["ok"] is False
