from copy import deepcopy
from contextlib import contextmanager
from threading import Event, Thread, current_thread

import pytest
from infrastructure.research_peripheral_store import ResearchPeripheralStore

from v4.manager_research.us_market_bridge import (
    ResearchPeripheralUsMarketReader,
    project_us_market,
)

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


class Reader:
    def __init__(self, payload=None, lineage=None):
        self.payload = payload
        self.lineage = lineage or {
            "status":"VERIFIED", "payload_sha256":"a"*64,
            "receipt_sha256":"b"*64, "manifest_sha256":"c"*64,
        }
        self.calls=[]
    def read_exact_session(self, session_date):
        self.calls.append(session_date)
        return deepcopy(self.payload), deepcopy(self.lineage)


def snapshot(*, provider_dates=("20260923",), captured_at="2026-09-23T16:17:00-04:00", status="READY"):
    rows=[]
    for i in range(24):
        rows.append({"label":"AI算力" if i==0 else f"proxy-{i}", "group":"GLOBAL_INDUSTRY",
            "mapping_type":"stock_basket_proxy", "pct_change":3.5 if i==0 else -0.5,
            "status":"READY", "proxy_symbols":["NVDA"], "available_symbols":["NVDA"], "coverage":{"available":1,"requested":1}})
    return {"market_snapshot": {"schema_version":"v3_5.us_market_snapshot.v1",
        "mapping_version":"v3_5.global_industry_proxy_map.v1", "capture_phase":"POST_CLOSE",
        "capture_session_date":"20260923", "provider_session_dates":list(provider_dates),
        "status":status, "captured_at":captured_at, "provider":"SIMULATED_PROVIDER",
        "source_response_sha256":"d"*64, "rows":rows,
        "requested_symbol_count":33, "available_symbol_count":1,
        "quotes":[{"symbol":"NVDA","change_pct":2.1,"session_date":"20260923","session_time":"16:00:00"}], **FLAGS}}


def context():
    return {"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}


def test_exact_session_raw_movers_are_preserved_without_hk_mapping():
    reader=Reader(snapshot())
    out=project_us_market(reader,"20260924",context())
    assert reader.calls == ["20260923"]
    assert out["status"] == "READY"
    assert out["coverage_scope"].endswith("NOT_FULL_US_MARKET")
    assert [r["label"] for r in out["raw_industry_up"]] == ["AI算力"]
    assert [r["symbol"] for r in out["raw_individual_up"]] == ["NVDA"]


def test_provider_session_mismatch_is_not_relaxed_by_calendar_verification():
    out=project_us_market(Reader(snapshot(provider_dates=("20260922","20260923"))),"20260924",context())
    assert out["status"] == "CANNOT_CONFIRM"
    assert out["mapping_eligible"] is False
    assert out["raw_industry_up"] and out["raw_individual_up"]
    assert "US_MARKET_PROVIDER_SESSION_DATE_UNIQUE_REQUIRED" in out["gaps"]


def test_after_cutoff_capture_is_rejected_and_missing_exact_is_explicit():
    late=project_us_market(Reader(snapshot(captured_at="2026-09-24T10:00:00+08:00")),"20260924",context())
    assert "US_MARKET_CAPTURE_AFTER_MANAGER_CUTOFF_OR_UNKNOWN" in late["gaps"]
    missing=project_us_market(Reader(None),"20260924",context())
    assert missing["status"] == "INPUT_MISSING"
    assert missing["raw_industry_up"] == []

def test_partial_snapshot_keeps_raw_discovery_but_never_becomes_ready():
    out=project_us_market(Reader(snapshot(status="PARTIAL")),"20260924",context())
    assert out["status"] == "PARTIAL"
    assert out["mapping_eligible"] is True
    assert out["coverage"]["requested_symbol_count"] == 33
    assert out["coverage"]["available_symbol_count"] == 1
    assert out["raw_industry_up"] and out["raw_individual_up"]

    from v4.manager_research.research_evidence import us_mappings
    relation={"manager_theme":"AI_COMPUTE","issuer_available_at":"2026-09-23T12:02:00+08:00",
        "source_refs":[{"payload_sha256":"b"*64}]}
    direct={"identity_pair_basis":{"us_symbol":"NVDA"},"source_refs":[{"payload_sha256":"c"*64}]}
    industry,individual=us_mappings(out,{"HK.01234":[relation]},{"HK.01234":[direct]})
    assert "HK.01234" in industry and "HK.01234" in individual


@pytest.mark.parametrize("failure", [
    "lineage", "schema", "session", "provider_date", "snapshot_status", "cutoff", "safety",
])
def test_hard_identity_failures_keep_raw_display_but_block_us_hk_mapping(failure):
    payload=snapshot()
    lineage={"status":"VERIFIED","payload_sha256":"a"*64,
        "receipt_sha256":"b"*64,"manifest_sha256":"c"*64}
    market=payload["market_snapshot"]
    if failure == "lineage":
        lineage["status"]="CANNOT_CONFIRM"
    elif failure == "schema":
        market["schema_version"]="unknown"
    elif failure == "session":
        market["capture_session_date"]="20260922"
    elif failure == "provider_date":
        market["provider_session_dates"]=["20260922","20260923"]
    elif failure == "snapshot_status":
        market["status"]="CANNOT_CONFIRM"
    elif failure == "cutoff":
        market["captured_at"]="2026-09-24T10:00:00+08:00"
    elif failure == "safety":
        market["orders_sent"]=True
    out=project_us_market(Reader(payload,lineage),"20260924",context())
    assert out["status"] == "CANNOT_CONFIRM"
    assert out["mapping_eligible"] is False
    assert out["mapping_ineligible_reasons"]
    assert out["raw_industry_up"] and out["raw_individual_up"]

    from v4.manager_research.research_evidence import us_mappings
    relation={"manager_theme":"AI_COMPUTE","issuer_available_at":"2026-09-23T12:02:00+08:00",
        "source_refs":[{"payload_sha256":"b"*64}]}
    direct={"identity_pair_basis":{"us_symbol":"NVDA"},"source_refs":[{"payload_sha256":"c"*64}]}
    industry,individual=us_mappings(out,{"HK.01234":[relation]},{"HK.01234":[direct]})
    assert industry == {} and individual == {}


def test_missing_cutoff_fails_closed_without_reading_owner():
    reader=Reader(snapshot())
    out=project_us_market(reader,"20260924",{})
    assert out["status"] == "CANNOT_CONFIRM"
    assert reader.calls == []


@pytest.mark.parametrize("cutoff", [
    "2025-12-31T09:00:00+08:00",
    "2026-01-01T09:00:00+08:00",
    "2027-01-04T09:00:00+08:00",
])
def test_calendar_coverage_gap_is_explained_without_owner_read(cutoff):
    reader=Reader(snapshot())
    out=project_us_market(reader,"20260102",{"research_cutoff":cutoff})
    assert out["status"] == "CANNOT_CONFIRM"
    assert "US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE" in out["gaps"]
    assert out["mapping_eligible"] is False
    assert out["expected_us_session"] is None
    assert reader.calls == []


def _owner_payload(*, fetched_at, change_pct):
    from ops.us_market_digest import GLOBAL_INDUSTRY_PROXY_MAP, build_us_market_phase_payload

    symbols=sorted({symbol for row in GLOBAL_INDUSTRY_PROXY_MAP for symbol in row["proxy_symbols"]})
    quotes={symbol:{"last":100.0+change_pct,"previous_close":100.0,"change_pct":change_pct,
        "session_date":"20260923","session_time":"16:00:00"} for symbol in symbols}
    return build_us_market_phase_payload("20260923",capture_phase="POST_CLOSE",fetched_at=fetched_at,
        capture_id=f"SIMULATED-{change_pct}",run_id=f"SIMULATED-RUN-{change_pct}",
        fetch_rss=lambda *_args,**_kwargs:b"<rss><channel></channel></rss>",
        fetch_quotes=lambda *_args,**_kwargs:quotes)


def test_owner_replace_cannot_mix_payload_with_new_receipt_or_manifest(tmp_path):
    root=tmp_path/"us-owner"
    owner=ResearchPeripheralStore(root)
    original=_owner_payload(fetched_at="2026-09-23T20:17:00Z",change_pct=1.0)
    replacement=_owner_payload(fetched_at="2026-09-23T20:18:00Z",change_pct=2.0)
    original_sha=owner.publish(original)["payload_sha256"]
    reader=ResearchPeripheralUsMarketReader(root)
    exact_read_entered=Event();allow_exact_read_to_finish=Event()
    original_read=reader.store.read_exact

    def pause_after_owner_validation(trade_date,source):
        value=original_read(trade_date,source)
        exact_read_entered.set()
        if not allow_exact_read_to_finish.wait(timeout=5):
            raise TimeoutError("controlled replacement race timed out")
        return value

    reader.store.read_exact=pause_after_owner_validation
    replace_lock_attempted=Event();replace_lock_acquired=Event();replace_finished=Event()
    original_lock=owner._lock

    @contextmanager
    def observe_replace_lock():
        if current_thread().name == "simulated-owner-replace":
            replace_lock_attempted.set()
        with original_lock():
            if current_thread().name == "simulated-owner-replace":
                replace_lock_acquired.set()
            yield

    owner._lock=observe_replace_lock
    read_result=[];errors=[]

    def read_worker():
        try:
            read_result.append(reader.read_exact_session("20260923"))
        except BaseException as error:
            errors.append(error)

    def replace_worker():
        try:
            owner.replace(replacement,expected_sha256=original_sha,reason="SIMULATED_CONTROLLED_RACE")
            replace_finished.set()
        except BaseException as error:
            errors.append(error)

    reading=Thread(target=read_worker,name="simulated-owner-read")
    replacing=Thread(target=replace_worker,name="simulated-owner-replace")
    reading.start()
    try:
        assert exact_read_entered.wait(timeout=3)
        replacing.start()
        assert replace_lock_attempted.wait(timeout=3)
        # The source replace reaches the same owner lock and remains blocked
        # until the bridge finishes hashing the exact bytes it validated.
        assert not replace_lock_acquired.wait(timeout=0.1)
    finally:
        allow_exact_read_to_finish.set()
        reading.join(timeout=5)
        if replacing.ident is not None:
            replacing.join(timeout=5)
    assert not reading.is_alive() and not replacing.is_alive()
    assert errors == []
    assert replace_finished.is_set()
    assert len(read_result) == 1
    payload,lineage=read_result[0]
    assert payload == original
    assert lineage["status"] == "VERIFIED"
    assert lineage["payload_sha256"] == original_sha
    assert owner.read_exact("20260923","external_finance") == replacement
