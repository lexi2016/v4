from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from contracts.research import validate_research_archive
from domains import research as research_domain
from domains.research import build_research_archive
from stage_center.acquisition import AcquisitionPlan, SourceResult
from stage_center.candidate_input import CandidateInput
from infrastructure.data_store import NativeDataStore, _sha256
from infrastructure.research_store import HourlyResearchStore
from stage_center.live_collectors import production_selection_builders
from stage_center.selection import SelectionStore
from ops.run_stage_center_nodes import NODE_IDS, main as node_main
from stage_center.research_context import ResearchContextError, load_research_context


V4_ROOT = Path(__file__).resolve().parents[1]


def _source(date: str, *, slot: str, with_stage_evidence: bool) -> dict:
    dashed = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    timeline = {
        "stock_code": "000001",
        "stock_name": "平安银行",
        "event_time": f"{dashed}T{slot[:2]}:{slot[2:]}:00+08:00",
        "source_published_at": f"{dashed}T08:31:00+08:00",
        "first_seen_at": f"{dashed}T08:32:00+08:00",
        "last_checked_at": f"{dashed}T{slot[:2]}:{slot[2:]}:00+08:00",
        "source_type": "hourly_research",
        "source_name": "小时研报",
        "source_title": f"银行跟踪 {slot}",
        "source_path": "v4/hourly/source.json",
        "url": "https://example.test/research",
        "theme": "银行",
        "catalyst": "业绩",
        "evidence_sentence": "只读研究证据",
        "evidence_level": "L2_MEDIUM",
        "confidence": "MEDIUM",
        "dedup_key": f"source-{slot}",
    }
    source = {
        "schema_version": "v3_research_lane.v2",
        "trade_date": date,
        "source_manifest": {
            "generated_at": f"{dashed}T{slot[:2]}:{slot[2:]}:00+08:00",
            "hourly_slot": slot,
            # These are source-side provenance fields.  The final hourly
            # payload/receipt SHA is verified independently by HourlyResearchStore.
            "manifest_sha256": "b" * 64,
            "receipt_sha256": "c" * 64,
        },
        "stock_research_timeline": [timeline],
        "stock_research_daily": [
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "first_seen_time": f"{dashed}T08:32:00+08:00",
                "last_seen_time": f"{dashed}T{slot[:2]}:{slot[2:]}:00+08:00",
                "research_score": 97,
                "research_status": "REPEATED",
                "evidence_count": 1,
                "source_count": 1,
                "strong_evidence_count": 0,
                "medium_evidence_count": 1,
                "weak_evidence_count": 0,
                "source_types": ["hourly_research"],
                "themes": ["银行"],
                "top_catalysts": ["业绩"],
            }
        ],
        "research_pool_bridge": [],
        "cannot_confirm": [],
    }
    if with_stage_evidence:
        timeline.update(
            {
                "is_new_since_last_slot": True,
                "is_recheck_duplicate": False,
                "evidence_id": "evidence-000001",
            }
        )
        source["research_items"] = [
            {
                "item_id": "item-000001",
                "raw_id": "raw-000001",
                "stock_code": "000001",
                "item_quality": "OK",
                "quality_score": 72.5,
                "quality_score_raw": "72.5",
                "is_new_since_last_slot": True,
                "is_recheck_duplicate": False,
                "source_path": "v4/hourly/source.json",
                "source_title": f"银行跟踪 {slot}",
                "url": "https://example.test/research",
                "cannot_confirm": [],
            }
        ]
    return source


def _write_morning(root: Path, date: str = "20260911") -> None:
    store = NativeDataStore(root)
    payload = {
        "schema_version": "v3_shared_data.morning_news.v1",
        "trade_date": date,
        "source_role": "JIUYANGONGSHE_MORNING_NEWS",
        "articles": [{"article_id": "article-1", "title": "早盘"}],
        "article_count": 1,
        "stock_mentions": [
            {
                "stock_code": "000001",
                "news_quality_score": 12.0,
                "intersection_summary": "早盘明确提及",
            }
        ],
        "mention_count": 1,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    payload_sha = _sha256(payload)
    manifest = {
        "schema_version": "v3_shared_data.morning_news_manifest.v1",
        "trade_date": date,
        "payload_sha256": payload_sha,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    receipt = {
        "schema_version": "v3_shared_data.morning_news_receipt.v1",
        "trade_date": date,
        "manifest_sha256": _sha256(manifest),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    payload_rel = f"morning_news/{date}.json"
    manifest_rel = f"morning_news/{date}.manifest.json"
    receipt_rel = f"morning_news/{date}.receipt.json"
    store._write(payload_rel, payload)
    store._write(manifest_rel, manifest)
    store._write(receipt_rel, receipt)
    store._write(
        "morning_news/latest.json",
        {
            "schema_version": "v3_shared_data.morning_news_latest.v1",
            "entries": {
                date: {
                    "payload_relative": payload_rel,
                    "manifest_relative": manifest_rel,
                    "receipt_relative": receipt_rel,
                    "payload_sha256": payload_sha,
                }
            },
        },
    )


def _write_separate_morning_root(hourly_root: Path, date: str = "20260911") -> Path:
    morning_root = hourly_root.parent / f"{hourly_root.name}-morning-news"
    _write_morning(morning_root, date)
    return morning_root


def _publish_slot(root: Path, date: str, slot: str, *, with_stage_evidence: bool) -> dict:
    source = _source(date, slot=slot, with_stage_evidence=with_stage_evidence)
    source_bytes = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    source_input_sha256 = hashlib.sha256(source_bytes).hexdigest()
    witness_path = (
        root / "research" / "hourly" / "source" / f"{source_input_sha256}.json"
    )
    witness_path.parent.mkdir(parents=True, exist_ok=True)
    witness_path.write_bytes(source_bytes)
    payload = build_research_archive(
        source, source_input_sha256=source_input_sha256
    )
    publication = HourlyResearchStore(root).publish(payload, slot=slot, mode="LIVE")
    return {"payload": payload, "publication": publication}


def _live_stage_fixture(root: Path) -> tuple[AcquisitionPlan, SourceResult, dict]:
    morning_root = _write_separate_morning_root(root)
    _publish_slot(root, "20260911", "0900", with_stage_evidence=True)
    candidate = CandidateInput(
        root=root,
        trade_date="20260911",
        current_relative="current.json",
        current_sha256="a" * 64,
        run_id="formal-marker-regression",
        codes=("A.000001",),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=(),
    )
    plan = AcquisitionPlan(
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        markets=("A_SHARE",),
        candidate_input=candidate,
        a_share_route="pytdx_hq_large_universe",
        hk_route="unused",
    )
    source = SourceResult(
        source_id="pytdx",
        status="READY",
        requested_rows=1,
        rows=(
            {
                "code": "A.000001",
                "name": "平安银行",
                "stock_name": "平安银行",
                # This is the stale marker observed in the reviewed probe.
                "formal_eligible": True,
                "formal_rank": "stale-rank",
                "pool_score": 88.0,
                "lane_evidence": ["A_SHARE_FORMAL_POOL"],
                "open_price": 10.0,
                "last_price": 10.5,
                "high_price": 10.6,
                "low_price": 9.9,
                "prev_close_price": 10.0,
                "turnover": 1_000_000.0,
                "bid_vol": 1.0,
                "ask_vol": 1.0,
                "update_time": "2026-09-11 09:35:00",
                "acquisition_rank": 1,
            },
        ),
    )
    raw = {
        "status": "READY",
        "artifact_sha256": "f" * 64,
        "requested_rows": 1,
        "missing_symbols": [],
        "cannot_confirm": [],
        "source_evidence": [],
        "cutoff_at": "09:35:05",
        "_v4_research_data_root": root,
        "_v4_morning_news_root": morning_root,
    }
    return plan, source, raw


def test_missing_hourly_source_witness_remains_cannot_confirm(tmp_path: Path) -> None:
    root = tmp_path / "v4-data"
    morning_root = _write_separate_morning_root(root)
    fixture = _publish_slot(root, "20260911", "0900", with_stage_evidence=True)
    source_sha = fixture["payload"]["source_input_sha256"]
    witness = root / "research" / "hourly" / "source" / f"{source_sha}.json"
    assert witness.is_file()
    witness.unlink()

    context = load_research_context(
        root, trade_date="20260911", stage_cutoff="09:35", morning_root=morning_root
    )
    assert (
        f"RESEARCH_SOURCE_WITNESS_MISSING:research/hourly/source/{source_sha}.json"
        in context.cannot_confirm
    )


def _formal_root(root: Path, code: str) -> Path:
    day = root / "formal_pools" / "20260911"
    day.mkdir(parents=True)
    csv_path = day / "formal_opening_pool_20260911.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("ts_code", "eligible_for_formal_pool", "rank", "score"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "ts_code": f"{code[-6:]}.SZ",
                "eligible_for_formal_pool": "true",
                "rank": "1",
                "score": "99.0",
            }
        )
    manifest = {
        "trade_date": "20260911",
        "status": "FORMAL_READY",
        "row_count": 1,
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    csv_path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    return root


def test_exact_cutoff_selects_verified_slot_and_preserves_provenance(tmp_path: Path) -> None:
    root = tmp_path / "v4-data"
    morning_root = _write_separate_morning_root(root)
    _publish_slot(root, "20260911", "0900", with_stage_evidence=True)
    _publish_slot(root, "20260911", "2300", with_stage_evidence=True)

    early = load_research_context(
        root, trade_date="20260911", stage_cutoff="09:35", morning_root=morning_root
    )
    late = load_research_context(
        root, trade_date="20260911", stage_cutoff="23:59", morning_root=morning_root
    )

    assert early.selected_slot == "0900"
    assert late.selected_slot == "2300"
    assert early.by_code["A.000001"].research_quality_score == 72.5
    assert early.by_code["A.000001"].research_delta_hits == 1
    assert early.by_code["A.000001"].news_quality_score == 12.0
    assert early.cannot_confirm == ()
    assert any(item.endswith("=0900") for item in early.source_evidence)
    assert any(item.startswith("v4_hourly_manifest_sha256=") for item in early.source_evidence)
    assert any(item.startswith("v4_hourly_receipt_sha256=") for item in early.source_evidence)
    assert validate_research_archive(early_payload := HourlyResearchStore(root).read_exact("20260911", "0900", mode="LIVE")) == "20260911"
    assert "stage_evidence_v1" in early_payload
    assert early_payload["stage_evidence_v1"]["items"][0]["item_quality"] == "OK"
    assert early_payload["stage_evidence_v1"]["items"][0]["quality_score_raw"] == "72.5"
    assert early_payload["stage_evidence_v1"]["evidence"][0]["is_new_since_last_slot"] is True


def test_exact_20260929_report_role_warnings_are_source_bound_and_non_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    date = "20260929"
    source = _source(date, slot="1400", with_stage_evidence=False)
    source["slot"] = "1400"
    receipt_path = (
        "research_module/runtime_outputs/zsxq_hourly/20260929/1400/"
        "v35_zsxq_hourly_status_20260929_1400.json"
    )
    source["source_manifest"].update(
        {
            "trade_date": date,
            "hourly_slot": "1400",
            "capture_origin": "ORIGINAL_SLOT",
            "original_time_capture": True,
            "natural_execution_verified": False,
            "generated_at": "2026-09-29T14:00:03+08:00",
            "published_at": "2026-09-29T14:00:03+08:00",
            "pit_cutoff": "2026-09-29T14:00:59+08:00",
            "source_receipts": [receipt_path],
        }
    )
    source["cannot_confirm"] = [{"reason": reason} for reason in ("gap-a", "gap-b", "gap-c")]
    warning_codes = ("002202", "600346", "600875", "601918")
    source["report_entity_audit"] = {
        "policy_version": "report_subject_scoring.v1",
        "affected_codes": list(warning_codes),
        "excluded_evidence_count": len(warning_codes),
        "historical_capture_reconstructed": False,
        "original_entities_retained": True,
        "score_weights_changed": False,
        "security_master_attested": False,
        "excluded_evidence": [
            {
                "entity_role": "TITLE_NAME_MARKET_UNCONFIRMED",
                "evidence_id": f"evidence-{index}",
                "research_subject_eligible": False,
                "source_path": receipt_path,
                "stock_code": code,
            }
            for index, code in enumerate(warning_codes)
        ],
    }
    source_bytes = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    source_sha = hashlib.sha256(source_bytes).hexdigest()

    baseline = build_research_archive(source, source_input_sha256=source_sha)
    monkeypatch.setattr(
        research_domain,
        "_V4_20260929_1400_REPORT_ROLE_WARNING_SOURCE_SHA256",
        source_sha,
    )
    payload = build_research_archive(source, source_input_sha256=source_sha)
    expected_warnings = [f"REPORT_ROLE_EVIDENCE_EXCLUDED:{code}" for code in warning_codes]
    assert set(expected_warnings).issubset(baseline["cannot_confirm"]) and set(payload["cannot_confirm"]) == set(baseline["cannot_confirm"])
    assert set(baseline["cannot_confirm"]).issubset(payload["cannot_confirm"])
    for key in ("articles", "stock_pool", "source_counts", "write_policy", "recommendation_status"):
        assert payload[key] == baseline[key]

    mismarked_source = deepcopy(source)
    mismarked_source["report_entity_audit"]["excluded_evidence"][0][
        "research_subject_eligible"
    ] = True
    with pytest.raises(ValueError, match="EXCLUDED_EVIDENCE_INVALID"):
        build_research_archive(mismarked_source, source_input_sha256=source_sha)

    root = tmp_path / "v4-data"
    witness = root / "research" / "hourly" / "source" / f"{source_sha}.json"
    witness.parent.mkdir(parents=True, exist_ok=True)
    witness.write_bytes(source_bytes)
    publication = HourlyResearchStore(root).publish(payload, slot="1400", mode="LIVE")
    assert publication["payload_path"] == "research/hourly/live/20260929/1400.json"
    morning_root = _write_separate_morning_root(root, date)
    context = load_research_context(
        root,
        trade_date=date,
        stage_cutoff="14:00:59",
        morning_root=morning_root,
    )
    assert context.selected_slot == "1400"
    assert all(
        f"v4_hourly_source_audit_warning={warning}" in context.source_evidence
        for warning in expected_warnings
    )
    assert "v4_hourly_source_audit_warning_scope=NON_BLOCKING_PROVENANCE_ONLY" in context.source_evidence
    assert not (set(context.cannot_confirm) & set(expected_warnings))
    assert "RESEARCH_STAGE_EVIDENCE_MISSING" in context.cannot_confirm
    assert "RESEARCH_ITEM_QUALITY_SCORE_MISSING:A.000001" in context.cannot_confirm
    assert "RESEARCH_DELTA_FLAGS_MISSING:A.000001" in context.cannot_confirm


def test_missing_item_quality_and_delta_do_not_alias_pool_score(tmp_path: Path) -> None:
    root = tmp_path / "v4-data"
    morning_root = _write_separate_morning_root(root)
    _publish_slot(root, "20260911", "0900", with_stage_evidence=False)

    context = load_research_context(
        root, trade_date="20260911", stage_cutoff="09:35", morning_root=morning_root
    )
    score = context.by_code["A.000001"]
    assert score.news_quality_score == 12.0
    assert score.research_quality_score is None
    assert score.research_delta_hits is None
    assert "RESEARCH_STAGE_EVIDENCE_MISSING" in context.cannot_confirm
    assert "RESEARCH_ITEM_QUALITY_SCORE_MISSING:A.000001" in context.cannot_confirm
    assert "RESEARCH_DELTA_FLAGS_MISSING:A.000001" in context.cannot_confirm
    assert score.source_health == "READY_WITH_GAPS"


def test_live_stage_keeps_missing_research_scalars_out_of_numeric_envelope(tmp_path: Path) -> None:
    root = tmp_path / "v4-data"
    morning_root = _write_separate_morning_root(root)
    _publish_slot(root, "20260911", "0900", with_stage_evidence=False)
    candidate = CandidateInput(
        root=root,
        trade_date="20260911",
        current_relative="current.json",
        current_sha256="a" * 64,
        run_id="candidate-run",
        codes=("A.000001",),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=(),
    )
    plan = AcquisitionPlan(
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        markets=("A_SHARE",),
        candidate_input=candidate,
        a_share_route="pytdx_hq_large_universe",
        hk_route="unused",
    )
    source = SourceResult(
        source_id="pytdx",
        status="READY",
        requested_rows=1,
        rows=(
            {
                "code": "A.000001",
                "name": "平安银行",
                "stock_name": "平安银行",
                "formal_eligible": False,
                "formal_rank": "",
                "open_price": 10.0,
                "last_price": 10.5,
                "high_price": 10.6,
                "low_price": 9.9,
                "prev_close_price": 10.0,
                "turnover": 1_000_000.0,
                "bid_vol": 1.0,
                "ask_vol": 1.0,
                "update_time": "2026-09-11 09:35:00",
                "acquisition_rank": 1,
            },
        ),
    )
    raw = {
        "status": "READY",
        "artifact_sha256": "f" * 64,
        "requested_rows": 1,
        "missing_symbols": [],
        "cannot_confirm": [],
        "source_evidence": [],
        "cutoff_at": "09:35:05",
        "_v4_research_data_root": root,
        "_v4_morning_news_root": morning_root,
    }
    envelope = production_selection_builders("STAGE_0930_0935")["A_SHARE"](
        source, plan, raw
    )
    assert envelope["source_status"] == "CANNOT_CONFIRM"
    assert envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert envelope["selection_status"] != "READY"
    assert envelope["rows"][0]["news_quality_score"] == 12.0
    assert envelope["rows"][0]["research_quality_score"] is None
    assert envelope["rows"][0]["research_delta_hits"] is None
    assert envelope["rows"][0]["research_bonus"] is None
    assert any(
        item.startswith("RESEARCH_ITEM_QUALITY_SCORE_MISSING:A.000001")
        for item in envelope["cannot_confirm"]
    )
    selection_store = SelectionStore(root / "selection")
    published = selection_store.publish(envelope, market="A_SHARE")
    readback = selection_store.read_verified("20260911", "STAGE_0930_0935", "A_SHARE")
    assert published["artifact_id"] == envelope["artifact_id"] == readback["artifact_id"]
    assert published["run_id"] == envelope["run_id"] == readback["run_id"]
    assert readback["selection_status"] == "PARTIAL_WITH_ROWS"
    assert readback["source_status"] == "CANNOT_CONFIRM"


def test_live_stage_does_not_trust_raw_formal_marker_without_overlay(tmp_path: Path) -> None:
    plan, source, raw = _live_stage_fixture(tmp_path / "v4-data")
    envelope = production_selection_builders("STAGE_0930_0935")["A_SHARE"](
        source, plan, raw
    )
    row = envelope["rows"][0]
    assert row["formal_eligible"] is False
    assert "A_SHARE_FORMAL_POOL" not in row["lane_evidence"]
    assert "STAGE_ACQUISITION_UNIVERSE" in row["lane_evidence"]
    assert envelope["source_status"] == "CANNOT_CONFIRM"
    assert envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert "FORMAL_OVERLAY_CANNOT_CONFIRM" in envelope["cannot_confirm"]


def test_live_stage_rejects_forged_private_formal_marker_without_attach(tmp_path: Path) -> None:
    plan, source, raw = _live_stage_fixture(tmp_path / "v4-data")
    forged_row = dict(source.rows[0])
    forged_row["_formal_authority_overlay_verified"] = True
    forged = SourceResult(
        source_id=source.source_id,
        status=source.status,
        rows=(forged_row,),
        requested_rows=source.requested_rows,
        cannot_confirm=source.cannot_confirm,
        source_evidence=source.source_evidence,
    )
    envelope = production_selection_builders("STAGE_0930_0935")["A_SHARE"](
        forged, plan, raw
    )
    assert envelope["source_status"] == "CANNOT_CONFIRM"
    assert envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert envelope["rows"][0]["formal_eligible"] is False
    assert "A_SHARE_FORMAL_POOL" not in envelope["rows"][0]["lane_evidence"]
    assert "FORMAL_OVERLAY_CANNOT_CONFIRM" in envelope["cannot_confirm"]


def test_live_stage_uses_only_verified_formal_overlay_membership(tmp_path: Path) -> None:
    from stage_center.runner import _attach_a_authority

    plan, source, raw = _live_stage_fixture(tmp_path / "v4-data")
    matched_source = _attach_a_authority(
        source,
        formal_root=_formal_root(tmp_path / "formal-match", "A.000001"),
        trade_date="20260911",
    )
    assert matched_source.rows[0]["_formal_authority_overlay_verified"] is True
    matched = production_selection_builders("STAGE_0930_0935")["A_SHARE"](
        matched_source, plan, raw
    )
    assert matched["source_status"] == "READY"
    assert matched["selection_status"] == "READY"
    assert matched["rows"][0]["formal_eligible"] is True
    assert "A_SHARE_FORMAL_POOL" in matched["rows"][0]["lane_evidence"]

    mismatched_source = _attach_a_authority(
        source,
        formal_root=_formal_root(tmp_path / "formal-mismatch", "A.000002"),
        trade_date="20260911",
    )
    assert mismatched_source.rows[0]["_formal_authority_overlay_verified"] is False
    mismatched = production_selection_builders("STAGE_0930_0935")["A_SHARE"](
        mismatched_source, plan, raw
    )
    assert mismatched["source_status"] == "CANNOT_CONFIRM"
    assert mismatched["selection_status"] == "PARTIAL_WITH_ROWS"
    assert mismatched["rows"][0]["formal_eligible"] is False
    assert "A_SHARE_FORMAL_POOL" not in mismatched["rows"][0]["lane_evidence"]


def test_missing_future_and_tampered_exact_inputs_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "v4-data"
    morning_root = _write_separate_morning_root(root)
    _publish_slot(root, "20260911", "0900", with_stage_evidence=False)

    with pytest.raises(ResearchContextError, match="before cutoff"):
        load_research_context(
            root, trade_date="20260911", stage_cutoff="08:30", morning_root=morning_root
        )
    with pytest.raises(ResearchContextError, match="exact-date"):
        load_research_context(
            root, trade_date="20260912", stage_cutoff="09:35", morning_root=morning_root
        )

    receipt_path = root / "receipts/research/hourly/live/20260911/0900.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["slot"] = "1000"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ResearchContextError, match="not verified|read failed"):
        load_research_context(
            root, trade_date="20260911", stage_cutoff="09:35", morning_root=morning_root
        )


def test_old_root_and_decorated_date_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResearchContextError, match="legacy"):
        load_research_context(tmp_path / "v3_system", trade_date="20260911", stage_cutoff="09:35")
    with pytest.raises(ResearchContextError, match="YYYYMMDD"):
        load_research_context(tmp_path, trade_date="x20260911", stage_cutoff="09:35")


def test_persistent_v4_node_entrypoint_checks_all_sixteen_nodes() -> None:
    assert len(NODE_IDS) == 16
    assert node_main(["--config", str(V4_ROOT / "stage_center_tick_config.json"), "--check"]) == 0


def test_v4_analyzer_is_pure_and_does_not_invent_stage_quality() -> None:
    from infrastructure.isolated_package_loader import load_isolated_package_module

    module = load_isolated_package_module(
        V4_ROOT / "upstreams",
        package_directory="shared_research",
        module_leaf="v3_zsxq_adapter",
        namespace_prefix="stage_context_test_analyzer",
    )
    result = module.analyze_recent_topics({"topics_brief": []})
    encoded = json.dumps(result, ensure_ascii=False)
    assert "quality_score" not in encoded
    assert "research_delta_hits" not in encoded
    assert "is_new_since_last_slot" not in encoded


def test_node_cli_check_is_reproducible_without_network() -> None:
    command = [
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python",
        "-B",
        str(V4_ROOT / "ops/run_stage_center_nodes.py"),
        "--config",
        str(V4_ROOT / "stage_center_tick_config.json"),
        "--check",
    ]
    completed = subprocess.run(
        command,
        cwd=V4_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(V4_ROOT), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
    )
    assert completed.returncode == 0
    output = json.loads(completed.stdout)
    assert output["status"] == "CHECK_OK"
    assert output["node_ids"] == list(NODE_IDS)
