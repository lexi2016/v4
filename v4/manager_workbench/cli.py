"""Existing Mac process/scheduler invocation only. Does not start a web daemon."""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from .api import create_router
from .config import load_config
from .contracts import JobState, Lane, Phase, PlanSnapshot, JobRecord
from .executors import CodexExecutor, verify_review_pair
from .scheduler import tick
from .service import create_service
from .store import WorkbenchStore


def _binding(spec: str) -> dict[str, Any]:
    if ":" not in spec:
        raise ValueError("BINDING_FORMAT_INVALID")
    module, function = spec.split(":", 1)
    if not module or not function or any(ch in module+function for ch in ("/","\\"," ")):
        raise ValueError("BINDING_FORMAT_INVALID")
    value = getattr(importlib.import_module(module), function)()
    if not isinstance(value, dict) or not all(k in value for k in ("adapters","engines","executor")):
        raise ValueError("BINDING_INTERFACE_MISSING")
    return value


def _canary_verified(job: JobRecord, plan: PlanSnapshot | None, article_id: str) -> bool:
    """No fake canary pass from a host PID, saved empty lane or HTTP 200."""
    if plan is None or job.state != JobState.SUCCEEDED or job.run_id != plan.run_id:
        return False
    if (plan.context.scope_refs.get("canary_article_id") != article_id or
            plan.context.scope_refs.get("canary_mode") != "SINGLE_ARTICLE"):
        return False
    announcement = [l for l in plan.lanes if l.lane == Lane.ANNOUNCEMENT]
    if len(announcement)!=1 or len(announcement[0].rows)!=1:
        return False
    reader=[r for r in job.execution_refs if r.get("role")=="READER"]
    reviewer=[r for r in job.execution_refs if r.get("role")=="REVIEWER"]
    if len(reader)!=1 or len(reviewer)!=1:
        return False
    if (any(r.get("simulated") is not False or not r.get("isolation_proof")
            or any(flag in str(r.get("isolation_proof", "")).upper()
                   for flag in ("FAKE", "SIMULAT", "MOCK", "TEST_ONLY"))
            for r in reader+reviewer)
            or not plan.review_refs or not all(r in plan.review_refs for r in reader+reviewer)):
        return False
    try:
        verify_review_pair(reader[0],reviewer[0])
    except Exception:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manager-workbench",description="MWB v1 isolated integration CLI")
    parser.add_argument("--config",required=True,help="Sanitized local JSON config")
    parser.add_argument("--binding",help="Mac-provided importable module:factory; NOT browser input")
    subs = parser.add_subparsers(dest="command",required=True)
    job = subs.add_parser("job");job.add_argument("job_id")
    run = subs.add_parser("run");run.add_argument("target_date");run.add_argument("--phase",choices=["MANUAL","RETROSPECTIVE"],default="MANUAL")
    due = subs.add_parser("tick");due.add_argument("--at",help="Optional aware ISO-8601 for isolated testing")
    canary = subs.add_parser("canary");canary.add_argument("target_date")
    canary.add_argument("--article-id",required=True,help="One pinned canonical article ID; not URL/path")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.command=="job":
            record=WorkbenchStore(cfg.state_root).get_job(args.job_id)
            print(json.dumps(record.model_dump(mode="json") if record else {"state":"NOT_FOUND"},ensure_ascii=False))
            return 0 if record else 4
        if not args.binding:
            raise ValueError("MAC_BINDING_REQUIRED")
        bind=_binding(args.binding)
        service=create_service(cfg,bind["adapters"],bind["engines"],bind["executor"])
        if args.command=="tick":
            from datetime import datetime
            moment=datetime.fromisoformat(args.at) if args.at else None
            output=tick(service,calendar=bind.get("calendar"),stage_feed=bind.get("stage_feed"),at=moment)
            print(json.dumps(output,ensure_ascii=False))
            return 0
        if args.command=="canary":
            if not cfg.cli_isolation_attested or not isinstance(bind["executor"],CodexExecutor):
                raise ValueError("REAL_CANARY_ISOLATION_NOT_VERIFIED")
            if re.fullmatch(r"[A-Za-z0-9:_.-]{1,128}",args.article_id) is None:
                raise ValueError("CANARY_ARTICLE_ID_INVALID")
            record=service.submit(args.target_date,Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT],
                                  scope_refs={"canary_article_id":args.article_id,"canary_mode":"SINGLE_ARTICLE"})
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                latest=service.jobs.get(record.job_id)
                if latest.state in (JobState.SUCCEEDED,JobState.PARTIAL,JobState.FAILED,JobState.INTERRUPTED):
                    from fastapi import FastAPI
                    from fastapi.testclient import TestClient
                    api=FastAPI();api.include_router(create_router(service))
                    reply=TestClient(api).get(f"/api/v4/manager-workbench/days/{args.target_date}",params={"run_id":latest.run_id})
                    plan = None
                    if latest.state == JobState.SUCCEEDED and reply.status_code == 200:
                        # A terminal failed job may never have published a plan.
                        plan = service.store.get_plan(args.target_date,run_id=latest.run_id)
                    data = reply.json().get("data") or {}
                    snapshot = data.get("snapshot") or {}
                    passed = (_canary_verified(latest,plan,args.article_id) and
                              reply.status_code == 200 and
                              snapshot.get("run_id") == plan.run_id and
                              snapshot.get("product_sha256") == plan.product_sha256)
                    proof={"job_state":latest.state.value,"api_status":reply.status_code,
                           "run_id":latest.run_id,"semantic_execution_count":len([r for r in latest.execution_refs if r.get("role")]),
                           "independent_reader_reviewer_verified":bool(passed),
                           "failure_code":latest.failure_code}
                    print(json.dumps(proof,ensure_ascii=False))
                    return 0 if passed else 5
                time.sleep(.2)
            print(json.dumps({"state":"TIMEOUT_BUT_JOB_NOT_CANCELLED","job_id":record.job_id}))
            return 6
        record=service.submit(args.target_date,Phase(args.phase))
        print(json.dumps({"job_id":record.job_id,"run_id":record.run_id,"state":record.state.value}))
        return 0
    except Exception as exc:
        # Return only a stable code, never credentials, prompt, source paths or traceback.
        code=str(exc)
        if code not in ("MAC_BINDING_REQUIRED","REAL_CANARY_ISOLATION_NOT_VERIFIED","BINDING_INTERFACE_MISSING",
                        "BINDING_FORMAT_INVALID","HK_CALENDAR_NOT_BOUND","HK_NEXT_SESSION_NOT_BOUND"):
            code="WORKBENCH_CLI_FAILED"
        print(json.dumps({"state":"FAILED","failure_code":code}),file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
