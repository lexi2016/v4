"""V4 r9 4-domain consolidation, 92 kept URLs, 6 pruned URLs, --step ingest & cold-start SSE replay tests."""
from __future__ import annotations

import json
from pathlib import Path
import re
import pytest
from fastapi.testclient import TestClient

from v4_core.api.app import create_app
from v4_core.config import V4Config
from v4_core.ingest.a_share_tdx import TDX_DAY_STRUCT
from v4_core.runner.cli import EmptyPipelineOutputError, run_pipeline
from v4_core.storage.db import V4Store, normalize_symbol
from v4_core.strategies.workbench_score import RULE_VERSION


def _cfg(tmp_path: Path) -> V4Config:
    cfg = V4Config(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data/v4.sqlite3",
        bars_dir=tmp_path / "data/bars",
        logs_dir=tmp_path / "logs",
        min_free_gib=0.01,
    )
    cfg.ensure_dirs()
    return cfg


KEPT_92_ROUTES = [
    # 看板 (31)
    ("GET", "/api/v4/research/a-share/company-materials"),
    ("GET", "/api/v4/research/a-share/daily-product"),
    ("GET", "/api/v4/research/a-share/event-cases"),
    ("GET", "/api/v4/research/a-share/history"),
    ("GET", "/api/v4/research/a-share/original-chart"),
    ("GET", "/api/v4/research/a-share/original-chart/{asset}"),
    ("GET", "/api/v4/research/a-share/top200-hit"),
    ("GET", "/api/v4/research/events"),
    ("GET", "/api/v4/research/latest-event"),
    ("GET", "/api/v4/research/single-stock-repair-sop"),
    ("GET", "/api/v4/research/workbench/classifications/{market}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/charts"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/company/{symbol}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/context"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/events"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/f10/{symbol}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/formula-daily-k/{symbol}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/observations"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/projections"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/single-research/{symbol}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/single-research/{symbol}/assets/{kind}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/skill-r2/assets/{symbol}/{kind}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/top200"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/v192"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/v192-assets/{symbol}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/v192-assets/{symbol}/{kind}"),
    ("GET", "/api/v4/research/workbench/days/{source_date}/versions"),
    ("GET", "/api/v4/research/workbench/history"),
    ("GET", "/api/v4/research/workbench/workflow-contract"),
    ("GET", "/api/v4/research/zero-to-history-high-position"),
    # 阶段选股 (11)
    ("GET", "/api/v4/manager/stage-selection"),
    ("GET", "/api/v4/meta/stages"),
    ("GET", "/api/v4/preselection-pools"),
    ("GET", "/api/v4/research/opening-observation"),
    ("GET", "/api/v4/research/selection"),
    ("GET", "/api/v4/research/selection/manager-decision"),
    ("GET", "/api/v4/stage-center/selection"),
    ("POST", "/api/v4/stage-center/selection/ensure"),
    ("GET", "/api/v4/workbench/stage"),
    ("GET", "/api/v4/workbench/stage-batch"),
    ("POST", "/api/v4/workbench/stage/ensure"),
    # 研报指挥台 (38)
    ("GET", "/api/v4/baimao/observations"),
    ("GET", "/api/v4/baimao/x/latest"),
    ("GET", "/api/v4/manager-workbench/announcement-flash"),
    ("POST", "/api/v4/manager-workbench/announcement-flash/resume"),
    ("POST", "/api/v4/manager-workbench/announcement-flash/update"),
    ("POST", "/api/v4/manager-workbench/announcement-flash/{job_id}/execute-preprocessed"),
    ("POST", "/api/v4/manager-workbench/announcement-flash/{job_id}/stop"),
    ("GET", "/api/v4/manager-workbench/days/{date}"),
    ("GET", "/api/v4/manager-workbench/days/{date}/recommendations/{lane}"),
    ("GET", "/api/v4/manager-workbench/history"),
    ("GET", "/api/v4/manager-workbench/hk-history"),
    ("GET", "/api/v4/manager-workbench/mapping-catalog"),
    ("GET", "/api/v4/manager-workbench/stocks/{symbol}"),
    ("GET", "/api/v4/manager/research/announcements"),
    ("GET", "/api/v4/manager/research/announcements/body"),
    ("POST", "/api/v4/manager/research/announcements/refresh"),
    ("POST", "/api/v4/manual-collection"),
    ("GET", "/api/v4/manual-collection/{job_id}"),
    ("GET", "/api/v4/research/articles"),
    ("GET", "/api/v4/research/articles/latest"),
    ("GET", "/api/v4/research/authoritative"),
    ("GET", "/api/v4/research/dates"),
    ("GET", "/api/v4/research/day"),
    ("GET", "/api/v4/research/evidence-search"),
    ("GET", "/api/v4/research/hourly"),
    ("GET", "/api/v4/research/hourly/latest"),
    ("GET", "/api/v4/research/lane"),
    ("GET", "/api/v4/research/machine-cards"),
    ("GET", "/api/v4/research/pdf-documents/{document_id}"),
    ("GET", "/api/v4/research/pdf-relations"),
    ("GET", "/api/v4/research/stage-report-evidence"),
    ("GET", "/api/v4/research/stock-clues"),
    ("GET", "/api/v4/research/us-market"),
    ("GET", "/api/v4/research/wechat/materials"),
    ("GET", "/api/v4/research/wechat/materials/mentions"),
    ("GET", "/api/v4/research/wechat/materials/{record_id}"),
    ("GET", "/api/v4/research/wechat/materials/{record_id}/artifacts/{artifact_id}"),
    ("GET", "/api/v4/research/wechat/materials/{record_id}/mentions"),
    # 复盘状态 (12)
    ("GET", "/api/v1/runs/date-list"),
    ("GET", "/api/v4/manager-workbench/reviews/{date}"),
    ("POST", "/api/v4/manager-workbench/runs"),
    ("GET", "/api/v4/manager-workbench/runs/{id}"),
    ("POST", "/api/v4/manager-workbench/runs/{id}/retry"),
    ("GET", "/api/v4/operations/sop"),
    ("GET", "/api/v4/review"),
    ("POST", "/api/v4/review/generate"),
    ("GET", "/api/v4/runtime-graph/frontend-build"),
    ("GET", "/api/v4/tasks/status"),
    ("GET", "/healthz"),
    ("GET", "/readyz"),
]

PRUNED_6_ROUTES = [
    ("POST", "/api/v4/manager-workbench/announcement-flash/recover-cached-product"),
    ("GET", "/api/v4/runtime-graph/authorities"),
    ("GET", "/api/v4/runtime-graph/events"),
    ("POST", "/api/v4/runtime-graph/repair"),
    ("GET", "/api/v4/runtime-graph/snapshot"),
    ("GET", "/api/v4/runtime-graph/status"),
]


def test_openapi_zero_v3_all_92_kept_urls_and_6_pruned_excluded(tmp_path: Path):
    assert len(KEPT_92_ROUTES) == 92
    assert len(PRUNED_6_ROUTES) == 6
    app = create_app(_cfg(tmp_path))
    openapi = app.openapi()
    paths = openapi["paths"]

    v3_paths = [p for p in paths if "/api/v3" in p or "/v3/" in p]
    assert v3_paths == [], f"Unexpected V3 routes in OpenAPI: {v3_paths}"

    for method, path in KEPT_92_ROUTES:
        assert path in paths, f"Missing kept route in OpenAPI: {method} {path}"
        assert method.lower() in paths[path], f"Missing HTTP method {method} for {path}"

    for method, path in PRUNED_6_ROUTES:
        assert path not in paths, f"Pruned route must not be registered: {method} {path}"


def test_all_19_previously_missing_frontend_routes_return_200_and_sz301252_name_resolved(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)

    # Seed security_master & stage selection with SZ.301252 -> 同星科技
    assert normalize_symbol("SZ.301252") == "301252.SZ"
    store.upsert_security_master([
        {"trade_date": "2026-11-24", "market": "A", "symbol": "301252.SZ", "display_name": "同星科技", "industry": "热管理"},
    ])
    store.upsert_stage_selections([
        {
            "trade_date": "2026-11-24",
            "stage": "09:30-09:35",
            "market": "A",
            "symbol": "SZ.301252",
            "rank": 1,
            "execution_ref": "v4core://2026-11-24/slot_3_intraday_stage/run1",
        }
    ])
    store.upsert_research_materials([
        {
            "record_id": "pdf-001",
            "source_type": "pdf",
            "trade_date": "2026-11-24",
            "symbol": "SZ.301252",
            "title": "同星科技深度研报",
        },
        {
            "record_id": "wx-001",
            "source_type": "wechat",
            "trade_date": "2026-11-24",
            "symbol": "301252.SZ",
            "title": "同星科技纪要",
        },
    ])

    client = TestClient(create_app(cfg))

    # Verify SZ.301252 resolves to 同星科技 (never null)
    stage_resp = client.get("/api/v4/workbench/stage", params={"date": "2026-11-24", "stage": "09:30-09:35", "market": "A"})
    assert stage_resp.status_code == 200
    stage_data = stage_resp.json()
    assert stage_data["rows"][0]["symbol"] == "SZ.301252"
    assert stage_data["rows"][0]["canonical_symbol"] == "301252.SZ"
    assert stage_data["rows"][0]["name"] == "同星科技"

    # Verify all 23 switched frontend target paths return HTTP 200
    probes = [
        ("GET", "/api/v4/research/dates", {}),
        ("GET", "/api/v4/research/us-market", {"research_date": "2026-11-24"}),
        ("GET", "/api/v4/research/selection/manager-decision", {"target_trade_date": "2026-11-24"}),
        ("GET", "/api/v4/preselection-pools", {"date": "2026-11-24"}),
        ("GET", "/api/v4/manager/stage-selection", {"date": "2026-11-24", "stage": "09:30-09:35"}),
        ("POST", "/api/v4/manual-collection", {}),
        ("GET", "/api/v4/workbench/stage", {"date": "2026-11-24"}),
        ("GET", "/api/v4/research/lane", {"research_date": "2026-11-24"}),
        ("GET", "/api/v4/research/pdf-documents/pdf-001", {"research_date": "2026-11-24"}),
        ("GET", "/api/v4/research/machine-cards", {"research_date": "2026-11-24"}),
        ("GET", "/api/v4/research/stock-clues", {"research_date": "2026-11-24"}),
        ("GET", "/api/v4/research/day", {"archive_date": "2026-11-24"}),
        ("GET", "/api/v4/review", {"date": "2026-11-24"}),
        ("POST", "/api/v4/review/generate", {}),
        ("GET", "/api/v4/tasks/status", {"date": "2026-11-24"}),
        ("GET", "/api/v4/research/selection", {"target_trade_date": "2026-11-24"}),
        ("GET", "/api/v4/research/wechat/materials", {"date": "2026-11-24"}),
        ("POST", "/api/v4/workbench/stage/ensure", {"date": "2026-11-24", "stage": "09:30-09:35"}),
        # Extra required UI shell & control routes
        ("GET", "/api/v1/runs/date-list", {}),
        ("GET", "/api/v4/runtime-graph/frontend-build", {}),
        ("GET", "/api/v4/research/single-stock-repair-sop", {}),
        ("GET", "/api/v4/research/workbench/workflow-contract", {"source_date": "2026-11-24"}),
        ("POST", "/api/v4/manager-workbench/announcement-flash/update", {}),
        ("POST", "/api/v4/manager-workbench/announcement-flash/resume", {}),
        ("POST", "/api/v4/manager-workbench/announcement-flash/job1/stop", {}),
        ("POST", "/api/v4/manager-workbench/announcement-flash/job1/execute-preprocessed", {}),
    ]
    for method, url, params in probes:
        resp = client.get(url, params=params) if method == "GET" else client.post(url, params=params, json={"date": "2026-11-24"})
        assert resp.status_code == 200, f"{method} {url} returned {resp.status_code}: {resp.text}"

    mc_job = client.post("/api/v4/manual-collection", json={"source": "ui"}).json()["job_id"]
    assert client.get(f"/api/v4/manual-collection/{mc_job}").status_code == 200

    # Display and ensure endpoints cannot create scheduler execution evidence.
    wf = client.get("/api/v4/research/workbench/workflow-contract", params={"source_date": "2026-11-24"}).json()
    assert wf["slot_count"] == 6
    assert all(row["execution_ref"] is None for row in wf["rows"])
    assert store.get_review_record("2026-11-24") is None


def test_next_day_ingest_step_and_full_all_pipeline_d24_to_d25(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)

    # Empty ingest fails closed
    with pytest.raises(EmptyPipelineOutputError):
        run_pipeline(cfg, "2026-11-25", "ingest")

    # Prefill D24 and build D24 QFQ snapshot
    store.upsert_daily_bars([
        {"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-24", "open": 22.0, "high": 22.5, "low": 21.8, "close": 22.35, "volume": 1000, "amount": 22350, "pre_close": 22.0},
    ])
    store.upsert_adj_factors([
        {"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-24", "adj_factor": 1.0},
    ])
    run_pipeline(cfg, "2026-11-24", "qfq")

    # Prepare D25 TDX .day file (2 bars: D24 + D25) + D25 adj_factor=2.0
    tdx_dir = tmp_path / "tdx" / "sz" / "lday"
    tdx_dir.mkdir(parents=True)
    day_bytes = (
        TDX_DAY_STRUCT.pack(20261124, 2200, 2250, 2180, 2235, 22350.0, 1000, 0)
        + TDX_DAY_STRUCT.pack(20261125, 1120, 1150, 1100, 1130, 22600.0, 2000, 0)
    )
    (tdx_dir / "sz000026.day").write_bytes(day_bytes)

    factors_file = tmp_path / "factors_d25.json"
    factors_file.write_text(
        json.dumps([{"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-25", "adj_factor": 2.0}]),
        encoding="utf-8",
    )
    store.upsert_workbench_selections([
        {"trade_date": "2026-11-25", "symbol": "000026.SZ", "selection_group": "192", "display_name": "飞亚达"},
    ])

    emitted: list[dict] = []
    res = run_pipeline(
        cfg,
        "2026-11-25",
        "all",
        tdx_dir=tmp_path / "tdx",
        factors_json=factors_file,
        sse_notifier=lambda dt, s: (emitted.append({"date": dt, "summary": s}) or True),
    )
    assert res["ingest"]["a_share_accepted"] == 1
    assert res["ingest"]["adj_factors_upserted"] == 1
    assert res["top200_count"] == 1
    assert res["workbench_count"] == 1
    assert res["sse_notified"] is True and len(emitted) == 1
    assert res["execution_ref"].startswith("v4core://2026-11-25/slot_4_a_share_daily/")

    # D24 QFQ snapshot remains strictly immutable
    d24_snap = store.get_date_bars("A", "2026-11-24", table="qfq_bars", asof_date="2026-11-24")
    assert d24_snap[0]["close"] == 22.35


def test_cold_start_sse_auto_replay_and_last_event_id_dedup(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)
    store.save_workbench_scores("2026-11-24", [{
        "trade_date": "2026-11-24",
        "symbol": "605577.SH",
        "selection_group": "both",
        "rule_version": RULE_VERSION,
        "score": 4.0,
        "action": "HOLD_OR_WATCH",
        "status": "READY",
        "detail_json": json.dumps({"display_name": "龙版传媒"}, ensure_ascii=False),
    }])

    # Brand new app (cold start, empty in-memory EventBus)
    client = TestClient(create_app(cfg))
    resp = client.get("/api/v4/research/workbench/days/2026-11-24/events", params={"once": "true"})
    assert resp.status_code == 200
    body = resp.text
    assert "event: workbench_completed" in body
    assert '"cold_start_replay": true' in body

    m = re.search(r"^id:\s*([0-9a-f]+)$", body, flags=re.MULTILINE)
    assert m is not None
    event_id = m.group(1)

    # Reconnecting with Last-Event-ID deduplicates cleanly
    resp_dedup = client.get(
        "/api/v4/research/workbench/days/2026-11-24/events",
        params={"once": "true"},
        headers={"Last-Event-ID": event_id},
    )
    assert resp_dedup.status_code == 200
    assert "event: workbench_completed" not in resp_dedup.text
    assert ": connected source_date=2026-11-24" in resp_dedup.text

    # Unmaterialized date must NOT emit workbench_completed
    resp_empty = client.get("/api/v4/research/workbench/days/2026-11-26/events", params={"once": "true"})
    assert resp_empty.status_code == 200
    assert "event: workbench_completed" not in resp_empty.text


def test_no_legacy_v3_route_or_module_references_in_v4_core_source():
    pkg_root = Path(__file__).resolve().parent.parent / "v4_core"
    for py_file in pkg_root.rglob("*.py"):
        if py_file.name == "safe_archive.py":
            continue  # safe_archive.py explicitly protects historical C-class roots by path string
        text = py_file.read_text(encoding="utf-8")
        assert "/api/v3" not in text, f"Legacy /api/v3 found in {py_file}"
        assert "v35_api" not in text, f"Legacy v35_api found in {py_file}"
