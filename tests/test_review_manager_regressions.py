"""Real service/store with controlled read-only providers; no remote sources."""
import threading
import time
import pytest
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore


def observation(date="20260904", count=1):
    return {"target_trade_date": date, "stage_id": "STAGE_0935_0940", "market": "HK_CONNECT",
            "rows": [{"code": f"HK.{i:05d}", "name": f"Offline fixture {i}", "rank": i,
                      "source_last_bar_time": f"{date[:4]}-{date[4:6]}-{date[6:]}T09:40:00+08:00"}
                     for i in range(1,count+1)]}

@pytest.mark.parametrize("method", ["get", "ensure"])
def test_requested_date_must_equal_observation_date(tmp_path, method):
    calls=[]
    def provider(**kw):
        calls.append(kw)
        return {"status": "CANNOT_CONFIRM", "reason": "OFFLINE", "facts": []}
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path), lambda date: observation("20260903"), provider)
    try:
        result=getattr(service,method)("20260904")
        assert result["target_trade_date"] == "20260904"
        assert result["status"] == "CANNOT_CONFIRM"
        assert "STAGE_OBSERVATION_TARGET_DATE_MISMATCH" in str(result)
        assert calls == []
        assert not list((tmp_path/"jobs").glob("*.json"))
    finally:
        service.close()


def test_matching_date_remains_valid_and_research_only(tmp_path):
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path), observation, None)
    try:
        result=service.get("20260904")
        assert result["target_trade_date"] == "20260904"
        assert result["status"] == "NOT_MATERIALIZED"
        assert result["RESEARCH_ONLY"] is True
        assert all(result[k] is False for k in ("production_allowed","buy_gate_updated","orders_sent"))
    finally:
        service.close()


def test_provider_timeout_finishes_before_blocked_call_is_released(tmp_path):
    entered=threading.Event()
    release=threading.Event()
    def provider(**kw):
        entered.set()
        release.wait(8)  # bounded cleanup even if the assertion below fails
        return {"status": "CANNOT_CONFIRM", "reason": "OFFLINE", "facts": []}
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path), observation, provider,
                                      row_timeout_seconds=1.0)
    future=None
    try:
        result=service.ensure("20260904")
        job_id=result["job"]["job_id"]
        assert entered.wait(1), "provider was not started"
        future=service._active.get(job_id)
        deadline=time.monotonic()+3.2
        job=service.job(job_id)
        while time.monotonic()<deadline and job["status"] in {"QUEUED", "RUNNING"}:
            time.sleep(0.02)
            job=service.job(job_id)
        assert not release.is_set()
        assert job["status"] == "CANNOT_CONFIRM", job
        assert job["results"]["HK.00001"]["reason"] == "SOURCE_PROVIDER_TIMEOUT"
        product=service.get("20260904")["product"]
        assert product is not None
        assert product["RESEARCH_ONLY"] is True
    finally:
        release.set()
        if future is not None:
            future.result(timeout=5)
        service.close()


@pytest.mark.parametrize("method, force", [("get",False),("ensure",False),("ensure",True)])
def test_persisted_running_job_without_local_owner_is_not_restarted_or_claimed_running(tmp_path, method, force):
    calls=[]
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path), observation,
        lambda **kw: calls.append(kw) or {"status":"CANNOT_CONFIRM","facts":[]})
    try:
        data=service._read_input("20260904")
        job_id=service._job_id(data)
        service.store.write_job({"job_id":job_id,"target_trade_date":"20260904",
            "input_identity":data["input_identity"],"status":"RUNNING","attempt":1})
        # This persisted receipt could be a crashed process OR another live
        # process. Neither automatic restart nor "still running here" is proven.
        result=service.get("20260904") if method=="get" else service.ensure("20260904",force=force)
        assert result["status"]=="CANNOT_CONFIRM"
        assert "JOB_OWNER_UNCONFIRMED" in str(result)
        assert result["can_ensure"] is False and result["can_retry"] is False
        assert calls==[]
        assert service.store.read_job(job_id)["status"]=="RUNNING"  # read-only, no invented dead-owner diagnosis
    finally:
        service.close()
