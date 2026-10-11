from __future__ import annotations

from datetime import datetime
import re
from types import SimpleNamespace

from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.us_mapping_research import (
    build_daily_run,
    persist_daily_run,
    read_workspace_mapping,
)
from v4.manager_research.workspace_projection import HK


def _bridge(target_date: str, cutoff: str, positive_symbols: tuple[str, ...]):
    from v4.manager_research.us_market_bridge import _configured_symbol_metadata

    session = "20261008" if target_date == "20261009" else "20261009"
    payload_sha = "a" * 64
    rows = []
    for symbol, metadata in _configured_symbol_metadata().items():
        rows.append({
            **metadata,
            "symbol": symbol,
            "quote_status": "VERIFIED",
            "direction": "UP" if symbol in positive_symbols else "FLAT",
            "quote_evidence": {
                "session_date": session, "session_time": "16:00:00", "change_pct": 1.0,
                "provider": "TEST_FIXTURE", "source_payload_sha256": payload_sha,
            },
            "relation_assessment_status": "NOT_EVALUATED",
            "relation_count": None,
            "relations": [],
            "relation_gaps": ["TEST_FIXTURE"],
            "target_date_eligibility": "CANNOT_CONFIRM",
            "RESEARCH_ONLY": True, "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False,
        })
    return {
        "schema_version": "v4.manager_research.us_market_bridge.v1",
        "target_trade_date": target_date,
        "research_cutoff": cutoff,
        "status": "READY",
        "expected_us_session": session,
        "coverage_scope": "FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET",
        "coverage": {
            "requested_symbol_count": 33, "available_symbol_count": 33,
            "assessed_symbol_count": 33, "unassessed_symbol_count": 0,
        },
        "source_identity": {
            "status": "VERIFIED", "payload_sha256": payload_sha,
            "receipt_sha256": "b" * 64, "manifest_sha256": "c" * 64,
        },
        "raw_industry_up": [],
        "raw_individual_up": [
            {"symbol": symbol, "change_pct": 2.5, "session_date": session,
             "session_time": "16:00:00", "provider": "TEST_FIXTURE"}
            for symbol in positive_symbols
        ],
        "symbol_assessments": rows,
        "gaps": [],
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }


def _service(tmp_path):
    return SimpleNamespace(
        store=ManagerResearchStore(tmp_path / "manager-state"),
        _workspace_us_market_reader=object(),
    )


def _current_bridge(monkeypatch, target_date: str, cutoff: str, positive_symbols: tuple[str, ...]):
    from v4.manager_research import us_market_bridge

    bridge = _bridge(target_date, cutoff, positive_symbols)
    monkeypatch.setattr(us_market_bridge, "project_us_market",
                        lambda *_args, **_kwargs: bridge)
    return bridge


def test_daily_uses_shared_33_symbol_relation_resolution_and_keeps_mover_filter(tmp_path, monkeypatch):
    _current_bridge(monkeypatch, "20261012", "2026-10-11T12:00:00+08:00", ("NVDA",))
    service = _service(tmp_path)

    result = build_daily_run(
        service, "20261012", now=datetime(2026, 10, 11, 12, 0, tzinfo=HK),
    )

    assessments = result["symbol_assessments"]
    by_symbol = {row["symbol"]: row for row in assessments}
    assert len(assessments) == 33
    assert sum(row["instrument_classification"] == "EQUITY_PROXY" for row in assessments) == 12
    assert sum(row["instrument_classification"] == "ETF_PROXY" for row in assessments) == 21
    assert result["relation_evidence"]["mapped_us_symbol_count"] == 10
    assert result["relation_evidence"]["eligible_relation_count"] == 14
    assert {row["symbol"] for row in assessments if row["relation_assessment_status"] == "ASSESSED_WITH_GAPS"} == {"MU", "WDC"}
    assert len(by_symbol["NVDA"]["relations"]) == 5
    assert by_symbol["AVGO"]["relations"]
    assert result["coverage"]["reviewed_us_symbol_count"] == 10
    assert result["coverage"]["matched_us_symbol_count"] == 1
    assert result["coverage"]["matched_hk_relation_count"] == 5
    assert {row["us_symbol"] for row in result["matches"]} == {"NVDA"}
    assert len(result["matches"]) == 5
    assert all(row["change_pct"] > 0 and row["session_date"] == "20261009" for row in result["matches"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", row["relation_identity_sha256"]) for row in result["matches"])
    assert result["relation_assessment_identity"] == result["relation_evidence"]["assessment_identity"]
    current = next(row for row in result["relation_source_identities"]
                   if row["relation_source"] == "CURRENT_REVIEWED_RELATION_EVIDENCE")
    assert current["evidence_artifact_sha256"]
    assert current["review_receipt_sha256"]
    assert "review_receipt" not in result["relation_evidence"]
    assert "withheld_candidates" not in result["relation_evidence"]


def test_daily_persistence_readback_keeps_full_assessments_and_artifact_sha(tmp_path, monkeypatch):
    _current_bridge(monkeypatch, "20261012", "2026-10-12T12:00:00+08:00", ("NVDA",))
    service = _service(tmp_path)

    saved = persist_daily_run(service, "20261012", now=datetime(2026, 10, 12, 12, 0, tzinfo=HK))
    readback = read_workspace_mapping(service, "20261012")["daily_run"]

    assert readback["run_id"] == saved["run_id"]
    assert readback["artifact_sha256"] == saved["artifact_sha256"]
    assert len(readback["symbol_assessments"]) == 33
    assert len(readback["matches"]) == 5
    assert readback["relation_assessment_identity"] == saved["relation_assessment_identity"]
    assert readback["relation_source_identities"] == saved["relation_source_identities"]
    assert readback["coverage"]["reviewed_us_symbol_count"] == 10


def test_sealed_20261009_daily_archive_withholds_20261011_relation_bodies(tmp_path, monkeypatch):
    _current_bridge(
        monkeypatch, "20261009", "2026-10-09T09:10:00+08:00",
        ("NVDA", "AVGO", "COHR", "LITE", "CIEN"),
    )
    service = _service(tmp_path)

    result = build_daily_run(
        service, "20261009", now=datetime(2026, 10, 9, 9, 10, tzinfo=HK),
    )

    assert len(result["symbol_assessments"]) == 33
    relations = [relation for row in result["symbol_assessments"] for relation in row["relations"]]
    assert len(relations) == 4
    assert {relation["relation_source"] for relation in relations} == {"RELEASE_PINNED_REVIEWED_SEED"}
    assert {row["hk_symbol"] for row in result["matches"]} == {
        "HK.06088", "HK.06166", "HK.00763",
    }
    gaps = {row["symbol"]: row for row in result["symbol_assessments"]}
    for symbol in ("MU", "WDC"):
        assert gaps[symbol]["relation_assessment_status"] == "ASSESSED_WITH_GAPS_NOT_AVAILABLE_BY_CUTOFF"
        assert "relation_assessment_evidence" not in gaps[symbol]
    assert "review_receipt" not in result["relation_evidence"]
    assert "withheld_candidates" not in result["relation_evidence"]
    assert result["relation_evidence"]["artifact_sha256"] is None
    assert all(row["relation_source"] != "CURRENT_REVIEWED_RELATION_EVIDENCE"
               for row in result["relation_source_identities"])
    assert {row["relation_source"] for row in result["relation_source_identities"]} == {
        "RELEASE_PINNED_REVIEWED_SEED",
    }


def test_historical_input_identity_ignores_post_cutoff_current_artifact_sha(tmp_path, monkeypatch):
    _current_bridge(
        monkeypatch, "20261009", "2026-10-09T09:10:00+08:00", ("NVDA", "AVGO"),
    )
    service = _service(tmp_path)
    now = datetime(2026, 10, 9, 9, 10, tzinfo=HK)
    baseline = build_daily_run(service, "20261009", now=now)

    from v4.manager_research import us_mapping_research
    original_attach = us_mapping_research.attach_current_relation_evidence

    def changed_later_registry_identity(bridge):
        result = original_attach(bridge)
        # The current resolver must not select this post-cutoff artifact, so a
        # newer registry hash can be diagnostic but cannot change the input id.
        result["relation_evidence"]["artifact_sha256"] = "d" * 64
        result["relation_evidence"]["diagnostic_current_review_receipt_sha256"] = "e" * 64
        return result

    monkeypatch.setattr(us_mapping_research, "attach_current_relation_evidence", changed_later_registry_identity)
    changed = build_daily_run(service, "20261009", now=now)

    assert baseline["input_identity"] == changed["input_identity"]
    assert baseline["relation_assessment_identity"] == changed["relation_assessment_identity"]
    assert all(row["relation_source"] != "CURRENT_REVIEWED_RELATION_EVIDENCE"
               for row in changed["relation_source_identities"])


def test_relation_source_and_review_sha_changes_invalidate_daily_reuse(tmp_path, monkeypatch):
    _current_bridge(monkeypatch, "20261012", "2026-10-12T12:00:00+08:00", ("NVDA",))
    service = _service(tmp_path)
    now = datetime(2026, 10, 12, 12, 0, tzinfo=HK)
    first = persist_daily_run(service, "20261012", now=now)

    from v4.manager_research import us_mapping_research
    original_attach = us_mapping_research.attach_current_relation_evidence

    def changed_source_identity(bridge):
        result = original_attach(bridge)
        for source in result["relation_evidence"]["relation_source_artifacts"]:
            if source.get("relation_source") == "CURRENT_REVIEWED_RELATION_EVIDENCE":
                source["evidence_file_sha256"] = "d" * 64
                source["evidence_artifact_sha256"] = "e" * 64
                source["review_receipt_sha256"] = "f" * 64
        return result

    monkeypatch.setattr(us_mapping_research, "attach_current_relation_evidence", changed_source_identity)
    second = persist_daily_run(service, "20261012", now=now)

    assert first["input_identity"] != second["input_identity"]
    first_current = next(row for row in first["relation_source_identities"]
                         if row["relation_source"] == "CURRENT_REVIEWED_RELATION_EVIDENCE")
    second_current = next(row for row in second["relation_source_identities"]
                          if row["relation_source"] == "CURRENT_REVIEWED_RELATION_EVIDENCE")
    assert first_current["review_receipt_sha256"] != second_current["review_receipt_sha256"]
    assert first["relation_assessment_identity"] == second["relation_assessment_identity"]


def test_existing_daily_dispatch_path_reaches_the_same_persisted_owner(tmp_path, monkeypatch):
    from v4.manager_research import plan_owner_dispatch
    from v4.manager_research.us_mapping_research import persist_daily_run

    target_date = "20261012"
    now = datetime(2026, 10, 12, 9, 30, tzinfo=HK)
    _current_bridge(monkeypatch, target_date, "2026-10-12T09:30:00+08:00", ("NVDA",))
    service = _service(tmp_path)
    calls = []

    if hasattr(plan_owner_dispatch, "execute_bound_daily_cycle"):
        from v4.manager_research import plan_owner_dispatch as dispatch

        identity = {
            "target_trade_date": target_date, "source_trade_date": target_date,
            "branch": "MORNING", "binding_sha256": "b" * 64,
            "scheduled_slot": "20261012T0915", "trigger_id": "c" * 64,
        }
        monkeypatch.setattr(dispatch, "_admit_bound_cycle",
                            lambda *_args, **_kwargs: ({"daily_automation": None}, identity, now))
        monkeypatch.setattr(dispatch, "clock_now", lambda: now)
        monkeypatch.setattr(dispatch, "_execute_serialized_cycle",
                            lambda _service, _binding, _identity, **kwargs: kwargs["us_mapping_result"])
        service._workspace_reads = SimpleNamespace(run=lambda _key, callback, **_kwargs: callback())

        def refresh(date, *, now, timeout_seconds, execution_context):
            calls.append((date, execution_context["trigger_kind"]))
            return persist_daily_run(service, date, now=now, timeout_seconds=timeout_seconds,
                                     execution_context=execution_context)

        service.refresh_us_mapping_research = refresh
        result = dispatch.execute_bound_daily_cycle(service, target_date, "b" * 64)
        assert calls == [(target_date, "SCHEDULED")]
    else:
        def refresh(date, *, now):
            calls.append(date)
            return persist_daily_run(service, date, now=now)

        service.refresh_us_mapping_research = refresh
        result = plan_owner_dispatch._prepare_us_mapping(service, target_date, now)
        assert calls == [target_date]

    daily = result
    if "symbol_assessments" not in daily:
        daily = read_workspace_mapping(service, target_date)["daily_run"]
    assert len(daily["symbol_assessments"]) == 33
    assert daily["relation_evidence"]["eligible_relation_count"] == 14
    assert daily["input_identity"]

