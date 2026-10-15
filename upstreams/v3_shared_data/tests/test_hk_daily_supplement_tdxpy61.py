from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from upstreams.v3_shared_data.shared_data import hk_daily_supplement as owner
from v4.manager_workbench.inputs import source_bindings


TARGET="20261015"
SESSIONS=[(datetime.strptime(TARGET,"%Y%m%d")-timedelta(days=offset)).strftime("%Y%m%d")
          for offset in range(60,-1,-1)]
CODES=["HK.00001","HK.00002"]
PANEL_ID={"panel_manifest_relative":"assets/hk_0_2/panels/panel/manifest.json",
    "panel_manifest_sha256":"a"*64,"manifest_prepared_at":"2026-10-15T09:20:00+00:00",
    "panel_relative":"assets/hk_0_2/panels/panel/panel.parquet","panel_sha256":"b"*64,
    "panel_max_date":TARGET}
MASTER_ID={"manifest_relative":"assets/hk_security_master/runs/master/manifest.json",
    "manifest_sha256":"c"*64,"artifact_relative":"assets/hk_security_master/runs/master/master.csv",
    "artifact_sha256":"d"*64,"run_id":"master","trade_date":TARGET,"row_count":len(CODES),
    "universe_codes_sha256":hashlib.sha256(json.dumps(CODES,separators=(",",":"),sort_keys=True).encode()).hexdigest(),
    "captured_at":"2026-10-15T09:30:00+00:00"}


class FakeAPI:
    def __init__(self):self.calls=[];self.disconnected=False
    def get_instrument_bars(self,category,market,code,start,count):
        self.calls.append((category,market,code,start,count))
        return [{"datetime":datetime.strptime(day,"%Y%m%d").strftime("%Y-%m-%d 15:00"),
            "open":70.0,"high":71.0,"low":69.0,"close":70.0,"trade":100,"amount":1000.0}
            for day in SESSIONS]
    def disconnect(self):self.disconnected=True


class Clock:
    def __init__(self,start):self.value=start
    def __call__(self):
        current=self.value
        self.value+=timedelta(seconds=1)
        return current


def _catalogue(api,endpoint,clock):
    rows=[{"market":31,"code":code[3:],"name":code} for code in CODES]
    responses=[("get_markets",[],[
        {"market":31,"name":"香港主板","category":2},
        {"market":48,"name":"香港创业板","category":2},
        {"market":49,"name":"香港基金","category":2}]),
        ("get_instrument_count",[],2),("get_instrument_info",[0,2],rows),
        ("get_instrument_count",[],2)]
    calls=[]
    for method,args,response in responses:
        started=owner._time_text(clock())
        available=owner._time_text(clock())
        calls.append({"method":method,"arguments":args,
            "request_sha256":owner._sha(owner._canonical(dict(endpoint=endpoint,method=method,arguments=args))),
            "started_at":started,"available_at":available,"response":response,
            "response_sha256":owner._sha(owner._canonical(response))})
    doc=owner._catalogue_document(endpoint,calls,owner._time_text(clock()))
    owner._verify_catalogue(doc)
    return doc


@pytest.fixture
def capture_setup(tmp_path,monkeypatch):
    monkeypatch.setattr(owner,"requested_sessions",lambda day,count=61:(SESSIONS,"e"*64))
    monkeypatch.setattr(owner,"_read_panel_identity",lambda *args,**kwargs:dict(PANEL_ID))
    monkeypatch.setattr(owner,"_read_master_identity",lambda *args,**kwargs:(dict(MASTER_ID),list(CODES)))
    monkeypatch.setattr(owner,"_catalogue",_catalogue)
    panel_gap_plan={"schema_version":"v3_shared_data.hk_0_2_panel_window_gaps.v1",
        "window_validator":"OVERSOLD_60_5_V1","target_date":"20261016","price_date":TARGET,
        "phase":"NEXT_DAY","cutoff":"2026-10-15T10:00:00+00:00","requested_sessions":SESSIONS,
        "calendar_sha256":"e"*64,"panel_identity":dict(PANEL_ID),"master_identity":dict(MASTER_ID),
        "master_scope_count":len(CODES),"records":[{"code":code,"reasons":["HISTORY_DATE_DUPLICATE_OR_GAP"],
            "missing_sessions":[SESSIONS[0]]} for code in CODES],"gap_codes":list(CODES),"panel_valid_count":0,
        "replacement_reason":"COMPLETE_61_SAME_PROFILE_REQUIRED_NO_UNVERIFIED_SOURCE_MIX",
        "protocol_request_count":128,"projected_session_count":61}
    return tmp_path/"shared",panel_gap_plan


def _capture(root,plan,clock):
    apis=[]
    def connector(endpoint):
        api=FakeAPI();apis.append(api);return api
    result=owner.capture_tdxpy_window_supplement(root,target_date=TARGET,connector=connector,
        clock=clock,panel_binding=dict(manifest_relative=PANEL_ID["panel_manifest_relative"],
            manifest_sha256=PANEL_ID["panel_manifest_sha256"]),panel_gap_plan=plan)
    return result,apis


def test_tdx61_panel_gaps_reuse_exact_security_cache_and_bind_exact_parents(capture_setup,monkeypatch):
    root,plan=capture_setup
    first_clock=Clock(datetime(2026,10,15,11,0,tzinfo=timezone.utc))
    first,first_apis=_capture(root,plan,first_clock)
    assert first["target_date"]==TARGET
    assert first["scope_count"]==2 and first["ready_count"]==2
    assert first["network_bar_requests"]==2 and first["cache_hits"]==0
    assert first_apis[0].disconnected

    second_clock=Clock(datetime(2026,10,15,12,0,tzinfo=timezone.utc))
    second,second_apis=_capture(root,plan,second_clock)
    assert second["manifest_sha256"]!=first["manifest_sha256"]
    assert second["cache_hits"]==2 and second["network_bar_requests"]==0
    assert second_apis[0].calls==[] and second_apis[0].disconnected

    pin=dict(second)
    output=Path(pin["source_local_path"])
    manifest_bytes=(output/pin["manifest_relative"]).read_bytes()
    panel_manifest_path=root/PANEL_ID["panel_manifest_relative"]
    master_manifest_path=root/MASTER_ID["manifest_relative"]
    panel_manifest_path.parent.mkdir(parents=True,exist_ok=True)
    panel_manifest_path.write_text(json.dumps({"panel_sha256":"b"*64}),encoding="utf-8")
    master_manifest_path.parent.mkdir(parents=True,exist_ok=True)
    master_manifest_path.write_text(json.dumps({"trade_date":TARGET,"artifact_sha256":"d"*64}),encoding="utf-8")

    original_read=source_bindings.read
    def parent_read(source,relative,expected=None):
        if relative==PANEL_ID["panel_manifest_relative"]:return {"panel_sha256":"b"*64},PANEL_ID["panel_manifest_sha256"]
        if relative==MASTER_ID["manifest_relative"]:return {"trade_date":TARGET,"artifact_sha256":"d"*64},MASTER_ID["manifest_sha256"]
        return original_read(source,relative,expected)
    monkeypatch.setattr(source_bindings,"read",parent_read)
    config=SimpleNamespace(shared_root=root)
    context=SimpleNamespace(source_sessions={"hk_price":TARGET},cutoff="2026-10-15T13:00:00+00:00")
    discovered=source_bindings._tdxpy_history_for_exact_parents(config,context,
        {"manifest_relative":PANEL_ID["panel_manifest_relative"],"manifest_sha256":PANEL_ID["panel_manifest_sha256"]},
        {"manifest_relative":MASTER_ID["manifest_relative"],"manifest_sha256":MASTER_ID["manifest_sha256"]})
    assert discovered["manifest_sha256"]==second["manifest_sha256"]
    assert discovered["raw_sha256"]==second["raw_sha256"]
    assert discovered["target_date"]==TARGET
    assert (output/discovered["manifest_relative"]).read_bytes()==manifest_bytes

    before_second=SimpleNamespace(source_sessions={"hk_price":TARGET},
        cutoff="2026-10-15T11:59:59+00:00")
    earlier=source_bindings._tdxpy_history_for_exact_parents(config,before_second,
        {"manifest_relative":PANEL_ID["panel_manifest_relative"],"manifest_sha256":PANEL_ID["panel_manifest_sha256"]},
        {"manifest_relative":MASTER_ID["manifest_relative"],"manifest_sha256":MASTER_ID["manifest_sha256"]})
    assert earlier["manifest_sha256"]==first["manifest_sha256"]
    before_all=SimpleNamespace(source_sessions={"hk_price":TARGET},
        cutoff="2026-10-15T10:59:59+00:00")
    assert source_bindings._tdxpy_history_for_exact_parents(config,before_all,
        {"manifest_relative":PANEL_ID["panel_manifest_relative"],"manifest_sha256":PANEL_ID["panel_manifest_sha256"]},
        {"manifest_relative":MASTER_ID["manifest_relative"],"manifest_sha256":MASTER_ID["manifest_sha256"]}) is None

    with pytest.raises(ValueError,match="TDXPY_MANIFEST_IDENTITY_INVALID"):
        owner.read_tdxpy_window_supplement(pin,target_date="20261016",cutoff="2026-10-15T13:00:00+00:00",
            expected_panel_sha="b"*64,expected_master_sha="d"*64,expected_codes=CODES,
            expected_panel_manifest_sha=PANEL_ID["panel_manifest_sha256"],
            expected_master_manifest_sha=MASTER_ID["manifest_sha256"])
    with pytest.raises(ValueError,match="TDXPY_WINDOW_PARENT_OR_CUTOFF_INVALID"):
        owner.read_tdxpy_window_supplement(pin,target_date=TARGET,cutoff="2026-10-15T11:59:59+00:00",
            expected_panel_sha="x"*64,expected_master_sha="d"*64,expected_codes=CODES,
            expected_panel_manifest_sha=PANEL_ID["panel_manifest_sha256"],
            expected_master_manifest_sha=MASTER_ID["manifest_sha256"])


def test_partial_transport_catalogue_cache_refreshes_and_keeps_original_evidence(capture_setup,monkeypatch):
    root,plan=capture_setup
    plan=dict(plan,records=[dict(code=CODES[0],reasons=[],missing_sessions=[]),
        dict(code=CODES[1],reasons=["HISTORY_DATE_DUPLICATE_OR_GAP"],missing_sessions=[SESSIONS[0]])],
        gap_codes=[CODES[1]],panel_valid_count=1)
    calls=[]
    def partial_then_complete(api,endpoint,clock):
        calls.append(endpoint)
        complete=_catalogue(api,endpoint,clock)
        observed_calls=[dict(call) for call in complete["calls"]]
        page=next(call for call in observed_calls if call["method"]=="get_instrument_info")
        page["response"]=page["response"][:1]
        page["response_sha256"]=owner._sha(owner._canonical(page["response"]))
        partial=owner._catalogue_document(endpoint,observed_calls,complete["available_at"],
            failure={"error_type":"TimeoutError","error":"timed out"})
        if len(calls)>2:return complete
        owner._verify_catalogue(partial)
        return partial

    monkeypatch.setattr(owner,"_catalogue",partial_then_complete)
    first,_=_capture(root,plan,Clock(datetime(2026,10,15,11,0,tzinfo=timezone.utc)))
    output=Path(first["source_local_path"])
    cache_path=output/"catalogues/116.205.143.214_7727.json"
    previous_bytes=cache_path.read_bytes()
    previous_sha=hashlib.sha256(previous_bytes).hexdigest()
    assert json.loads(previous_bytes)["coverage_status"]=="PARTIAL"
    assert first["ready_count"]==0 and first["unassessed_count"]==1

    second,_=_capture(root,plan,Clock(datetime(2026,10,15,12,0,tzinfo=timezone.utc)))
    assert calls==[owner.TDXPY_NODES[0],owner.TDXPY_NODES[1],owner.TDXPY_NODES[0]]
    assert second["ready_count"]==1 and second["unassessed_count"]==0
    second_manifest=json.loads((output/second["manifest_relative"]).read_bytes())
    assert second_manifest["catalogue_coverage_status"]=="COMPLETE"
    assert second_manifest["unassessed_count"]==0
    current_cache=json.loads(cache_path.read_bytes())
    assert current_cache["coverage_status"]=="COMPLETE"
    assert current_cache["cache_refresh"]["previous_sha256"]==previous_sha
    archive=output/current_cache["cache_refresh"]["previous_relative"]
    assert archive.read_bytes()==previous_bytes
    raw=json.loads((output/second["raw_relative"]).read_bytes())
    assert raw["catalogue_cache_refreshes"][0]["status"]=="RECOVERED"
    checked,records=owner.read_tdxpy_window_supplement(second,target_date=TARGET,
        cutoff=second["available_at"],expected_panel_sha=PANEL_ID["panel_sha256"],
        expected_master_sha=MASTER_ID["artifact_sha256"],expected_codes=CODES,
        expected_panel_manifest_sha=PANEL_ID["panel_manifest_sha256"],
        expected_master_manifest_sha=MASTER_ID["manifest_sha256"])
    assert checked["run_id"]==second["run_id"] and len(records)==1


def test_stable_partial_catalogue_cache_is_not_refetched(capture_setup,monkeypatch):
    root,plan=capture_setup
    calls=[]
    def stable_partial(api,endpoint,clock):
        calls.append(endpoint)
        complete=_catalogue(api,endpoint,clock)
        return owner._catalogue_document(endpoint,complete["calls"],complete["available_at"],
            failure={"error_type":"ValueError","error":"TDXPY_CATALOGUE_TOTAL_CHANGED"})

    monkeypatch.setattr(owner,"_catalogue",stable_partial)
    first,_=_capture(root,plan,Clock(datetime(2026,10,15,11,0,tzinfo=timezone.utc)))
    second,_=_capture(root,plan,Clock(datetime(2026,10,15,12,0,tzinfo=timezone.utc)))
    assert first["ready_count"]==second["ready_count"]==2
    assert calls==[owner.TDXPY_NODES[0]]
    raw=json.loads((Path(second["source_local_path"])/second["raw_relative"]).read_bytes())
    assert raw["catalogue_cache_refreshes"]==[]
