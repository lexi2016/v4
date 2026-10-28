"""Existing 1500/1530 handler migrated from disclosed runtime owner.
No producer implementation is introduced here; it invokes the original bound
materializer and verifies the resulting source/coverage/safety contract.
"""
from __future__ import annotations
import json, os, re
from pathlib import Path
from typing import Any
from contracts.runtime_tasks import DispatchRequest
from infrastructure.owned_path import resolve_owned_path

def _manager_close_hk_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Hong_Kong"))


def _manager_close_child_timeout_seconds(
    request: DispatchRequest, *, prepare_only: bool = False, now=None
) -> int:
    """Bound the child by the original 1530 capture window."""
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    if prepare_only:
        if request.slot != "1500":
            raise ValueError("MANAGER_PREPARE_SLOT_INVALID")
        return 60
    if request.slot != "1530":
        raise ValueError("MANAGER_CAPTURE_SLOT_INVALID")
    try:
        session_date = datetime.strptime(request.business_date, "%Y%m%d").date()
    except (TypeError, ValueError) as error:
        raise ValueError("MANAGER_CAPTURE_DATE_INVALID") from error
    hk = ZoneInfo("Asia/Hong_Kong")
    start = datetime.combine(session_date, time(15, 30), tzinfo=hk)
    end = start + timedelta(minutes=2)
    current = _manager_close_hk_now() if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("MANAGER_CAPTURE_CLOCK_INVALID")
    current = current.astimezone(hk)
    if current < start:
        raise ValueError("MANAGER_CAPTURE_WINDOW_NOT_OPEN")
    remaining = (end - current).total_seconds()
    # _run accepts whole seconds; floor so it cannot outlive the exclusive
    # 15:32 deadline. Refuse the last fractional second before starting a child.
    if remaining < 1.0:
        raise ValueError("EXACT_1530_SNAPSHOT_WINDOW_MISSED")
    return min(30, int(remaining))


def _manager_universe_dependency(self: Any, request: DispatchRequest) -> dict[str, Any]:
    """Run inside existing 1500 hourly work; failure never stops sibling research."""
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError
    try:
        result = _manager_close_1530(self, request, prepare_only=True)
    except WorkloadExecutionError as exc:
        result = dict(exc.result)
    return {**result, 'dependency_phase': 'HK_UNIVERSE_PREPARE_ONLY',
            'snapshot_requested': False, 'candidate_publication_requested': False}

def _manager_close_1530(self: Any, request: DispatchRequest, *, prepare_only: bool = False) -> dict[str, Any]:
    """1530 only: the sole V4 materializer child, explicit roots and readback."""
    import hashlib
    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError
    from infrastructure.manager_close_attempt import write_attempt

    module="ops.materialize_manager_close_discovery"
    flags={"RESEARCH_ONLY":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
    configured_app=os.environ.get("V4_MANAGER_MATERIALIZER_APP_ROOT")
    configured_state=os.environ.get("V4_MANAGER_RESEARCH_STATE_ROOT")
    state=Path(configured_state).expanduser() if configured_state else None

    def fail(reason: str, child: dict[str, Any] | None = None, *, preserve_attempt: bool = False,
             diagnostic: dict | None = None, failure_class: str = "UPSTREAM_NOT_READY",
             child_timeout_seconds: int | None = None) -> None:
        # This is a non-data attempt receipt, never a second materializer.
        # An absent explicit state binding remains visible in the dispatcher
        # receipt; it must not be guessed from the V35 input root.
        if (not prepare_only and state is not None and state.is_absolute()
            and reason!="MANAGER_SLOT_LOCKED" and not preserve_attempt):
            try:
                write_attempt(state,request.business_date,"FAILED",reason,datetime.now(ZoneInfo("Asia/Hong_Kong")),diagnostic=diagnostic)
            except (ValueError,OSError):
                pass
        result={"status":"FAILED","workload_id":"hourly_research","slot":request.slot,
                "modules":[module],"exit_code":2,"failure_class":failure_class,
                "reason":reason,**flags}
        if diagnostic is not None:
            result["failure_diagnostic"] = diagnostic
        if child:
            result["child_status"]=child.get("status")
            result["child_exit_code"]=child.get("exit_code")
            if child.get("exception_type"):
                result["child_exception_type"]=child.get("exception_type")
        if child_timeout_seconds is not None:
            result["child_timeout_seconds"]=child_timeout_seconds
        raise WorkloadExecutionError(result)

    capture_mode=os.environ.get("V4_MANAGER_CLOSE_CAPTURE_MODE", "").strip()
    if capture_mode and capture_mode != "PYTDX_LATE_OBSERVATION":
        fail("MANAGER_CLOSE_CAPTURE_MODE_INVALID",failure_class="INVALID_INPUT")
    if not prepare_only and capture_mode == "PYTDX_LATE_OBSERVATION":
        # The accepted PyTDX late-observation lane is invoked after the
        # successful 15:55 Stage workbench below. Never fall through to the
        # legacy 15:30 Futu capture when that mode is enabled.
        return {"status":"NOT_APPLICABLE","slot":"1530","modules":[module],"exit_code":0,
                "no_op":True,"reason":"1530_CAPTURE_DISABLED_BY_PYTDX_LATE_OBSERVATION_MODE",
                "capture_mode":capture_mode,**flags}
    if prepare_only and capture_mode == "PYTDX_LATE_OBSERVATION":
        # The late-observation owner consumes the exact existing D-1 Top100
        # pool. Do not invoke the legacy Futu universe-preparation owner from
        # the 15:00 dependency in PyTDX mode.
        return {"status":"NOT_APPLICABLE","slot":"1500","modules":[module],"exit_code":0,
                "no_op":True,"reason":"FUTU_UNIVERSE_PREPARE_SKIPPED_BY_PYTDX_LATE_OBSERVATION_MODE",
                "snapshot_requested":False,"candidate_publication_requested":False,
                "capture_mode":capture_mode,**flags}

    if not configured_app or state is None or not state.is_absolute():
        fail("MANAGER_EXPLICIT_BINDING_MISSING")
    app=Path(configured_app).expanduser()
    if not app.is_absolute(): fail("MANAGER_APP_ROOT_INVALID")
    app=app.resolve(); state=state.resolve()
    module_path=app/"ops/materialize_manager_close_discovery.py"
    for relative in ("ops/materialize_manager_close_discovery.py","apps/api/v35_api/app.py",
                     "apps/api/v35_api/manager_workbench_router.py","v4/manager_research/__init__.py"):
        if not (app/relative).is_file(): fail("MANAGER_APP_CLOSURE_MISSING")
    expected_child_sha = os.environ.get("V4_MANAGER_MATERIALIZER_SHA256", "")
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_child_sha)
            or hashlib.sha256(module_path.read_bytes()).hexdigest() != expected_child_sha):
        fail("MANAGER_MATERIALIZER_SHA_MISMATCH", failure_class="INVALID_INPUT")
    if not getattr(self,"hk_universe_root",None) or not getattr(self,"shared_futu_python_executable",None):
        fail("MANAGER_EXISTING_DATA_BINDING_MISSING")
    configured_owner_root = os.environ.get("V4_MANAGER_UNIVERSE_OWNER_ROOT")
    owner_root = (Path(configured_owner_root).expanduser()
                  if configured_owner_root else getattr(self, "repo_root", None))
    # Preserve the existing scheduler repo_root fallback when the optional
    # explicit owner-root binding is absent; the owner SHA remains mandatory.
    owner_sha = os.environ.get("V4_MANAGER_UNIVERSE_OWNER_SHA256", "")
    if (owner_root is None or not Path(owner_root).is_absolute()
        or not re.fullmatch(r"[0-9a-f]{64}", owner_sha)):
        fail("HK_UNIVERSE_OWNER_BINDING_REQUIRED",failure_class="INVALID_INPUT")
    owner_root = Path(owner_root).resolve()
    try:
        owner_path = resolve_owned_path(owner_root, "stage_center/hk_universe_preflight.py")
        actual_owner_sha = hashlib.sha256(owner_path.read_bytes()).hexdigest() if owner_path.is_file() else None
    except (ValueError, OSError):
        fail("HK_UNIVERSE_OWNER_BINDING_INVALID",failure_class="INVALID_INPUT")
    if actual_owner_sha != owner_sha:
        fail("HK_UNIVERSE_OWNER_SHA_MISMATCH",failure_class="INVALID_INPUT")
    env=dict(os.environ)
    env.update({"PYTHONPATH":os.pathsep.join(str(p) for p in (app,app/"upstreams",app/"upstreams/v3_shared_data")),
                "PYTHONNOUSERSITE":"1","PYTHONDONTWRITEBYTECODE":"1",
                "RESEARCH_ONLY":"true","PRODUCTION_ALLOWED":"false","BUY_GATE_UPDATED":"false","ORDERS_SENT":"false"})
    args=["--data-root",str(self.data_root),"--universe-root",str(self.hk_universe_root),
          "--futu-python",str(self.shared_futu_python_executable),"--trade-date",request.business_date,
          "--state-root",str(state),"--app-root",str(app),"--news-owner-root",str(self.repo_root),
          "--universe-owner-root",str(owner_root),"--universe-owner-sha256",owner_sha]
    rebound_root = os.environ.get('V4_CLOSE_REBOUND_AUTHORITY_ROOT')
    if rebound_root:
        # No fallback to unrelated roots. The child checks closure before any
        # history witness; the original post-window guard still runs first.
        args.extend(['--rebound-authority-root', rebound_root])
    if prepare_only:
        args.append("--universe-only")
    try:
        timeout_seconds = _manager_close_child_timeout_seconds(
            request, prepare_only=prepare_only
        )
    except ValueError as error:
        reason = str(error)
        if reason in {"MANAGER_CAPTURE_WINDOW_NOT_OPEN", "EXACT_1530_SNAPSHOT_WINDOW_MISSED"}:
            fail(reason, failure_class="NOT_DUE")
        fail(reason, failure_class="INVALID_INPUT")
    try:
        child=self._run(module,args,cwd=app,env=env,timeout_seconds=timeout_seconds)
    except (OSError, RuntimeError, ValueError):
        fail("MANAGER_CHILD_START_FAILED")
    if not prepare_only:
        try:
            _manager_close_child_timeout_seconds(request)
        except ValueError:
            fail("EXACT_1530_SNAPSHOT_WINDOW_MISSED",child,failure_class="NOT_DUE")
    if child.get("status")=="TIMEOUT":
        fail("MANAGER_CHILD_TIMEOUT",child,child_timeout_seconds=timeout_seconds)
    if child.get("status")!="SUCCEEDED" or child.get("exit_code")!=0:
        try:
            failure_payload=json.loads(str(child.get("stdout") or ""))
        except (ValueError, TypeError):
            failure_payload={}
        identity_ok=(isinstance(failure_payload,dict)
            and failure_payload.get("schema_version")=="v4.manager_close_materialization_result.v1"
            and failure_payload.get("trade_date")==request.business_date and failure_payload.get("slot")=="1530"
            and failure_payload.get("state_root")==str(state)
            and failure_payload.get("module_origin")==str(module_path)
            and failure_payload.get("module_sha256")==hashlib.sha256(module_path.read_bytes()).hexdigest()
            and all(failure_payload.get(k) is v for k,v in flags.items()))
        diagnostic = None
        if identity_ok and "failure_diagnostic" in failure_payload:
            from infrastructure.manager_close_attempt import validate_failure_diagnostic
            try:
                diagnostic = validate_failure_diagnostic(failure_payload["failure_diagnostic"])
                if diagnostic["code"] != failure_payload.get("reason"):
                    raise ValueError("reason mismatch")
            except ValueError:
                fail("MANAGER_CHILD_DIAGNOSTIC_INVALID",child,failure_class="INVALID_INPUT")
        child_class = "UPSTREAM_NOT_READY"
        if diagnostic is not None:
            if (diagnostic["layer"] == "CAPTURE_WINDOW" and diagnostic["kind"] == "EXPIRED"
                and diagnostic["code"] in {"EXACT_1530_SNAPSHOT_WINDOW_MISSED", "SNAPSHOT_RETURNED_AFTER_1530_WINDOW"}
                and failure_payload.get("terminal") is True and failure_payload.get("failure_class") == "NOT_DUE"):
                child_class = "NOT_DUE"
            elif diagnostic["kind"] in {"INVALID", "CONFLICT", "PIT_UNSAFE"}:
                child_class = "INVALID_INPUT"
        if prepare_only and identity_ok and diagnostic is not None:
            fail(diagnostic["code"],child,diagnostic=diagnostic,failure_class=child_class,preserve_attempt=True)
        if identity_ok and failure_payload.get("reason")=="MANAGER_SLOT_LOCKED":
            fail("MANAGER_SLOT_LOCKED",child)
        if identity_ok and failure_payload.get("status") in {"INPUT_MISSING","PENDING_SLOT","FAILED"}:
            try:
                attempt=json.loads(resolve_owned_path(state,f"workbench_research/{request.business_date}/1530.status.json").read_text())
                if (attempt.get("trade_date")==request.business_date and attempt.get("market")=="HK_CONNECT"
                    and attempt.get("slot")=="1530" and attempt.get("status")==failure_payload["status"]
                    and attempt.get("cannot_confirm")==[failure_payload.get("reason")]
                    and attempt.get("candidates")==[]
                    and attempt.get("priority_summary")=={"focus":[],"theme_changes":[],"risk_upgrades":[]}
                    and all(attempt.get(k) is v for k,v in flags.items())):
                    if diagnostic is not None and attempt.get("failure_diagnostic") != diagnostic:
                        fail("MANAGER_CHILD_DIAGNOSTIC_MISMATCH",child,failure_class="INVALID_INPUT")
                    fail(failure_payload["reason"],child,preserve_attempt=True,
                         diagnostic=diagnostic,failure_class=child_class)
            except (ValueError,TypeError,OSError):
                pass
        fail("MANAGER_CHILD_EXECUTION_FAILED",child)
    try:
        result=json.loads(str(child.get("stdout") or ""))
        if not isinstance(result,dict): raise ValueError
        if (result.get("schema_version")!="v4.manager_close_materialization_result.v1"
            or result.get("trade_date")!=request.business_date or result.get("slot")!="1530"
            or result.get("state_root")!=str(state)
            or result.get("module_origin")!=str(module_path)
            or result.get("module_sha256")!=hashlib.sha256(module_path.read_bytes()).hexdigest()
            or any(result.get(k) is not v for k,v in flags.items())): raise ValueError
        if prepare_only:
            if result.get("status") == "UNIVERSE_READY":
                if (result.get("universe_owner_sha256") != owner_sha
                    or type(result.get("code_count")) is not int or result["code_count"] <= 0
                    or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("authority_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{24}", str(result.get("authority_run_id", "")))):
                    raise ValueError("dependency identity invalid")
                return {"status":"SUCCEEDED","slot":request.slot,"modules":[module],"exit_code":0,
                        "materializer":result,**flags}
            if result.get("status") != "NOT_APPLICABLE":
                raise ValueError("preparation returned a data product")
        if result.get("status")=="NOT_APPLICABLE":
            from contracts.trading_calendar import load_market_calendar,resolve_market_states,TradingDayState
            market=resolve_market_states(load_market_calendar(),request.business_date)["hk_connect"]
            if market not in {TradingDayState.NON_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}: raise ValueError
            return {"status":"SUCCEEDED","slot":"1530","modules":[module],"exit_code":0,
                    "no_op":True,"materializer":result,**flags}
        if result.get("status") not in {"MATERIALIZED","ALREADY_EXISTS"}: raise ValueError
        reference=f"workbench_research/{request.business_date}/1530.json"
        if result.get("artifact_ref")!=reference: raise ValueError
        artifact_path=resolve_owned_path(state,reference)
        raw=artifact_path.read_bytes(); payload=json.loads(raw)
        if (hashlib.sha256(raw).hexdigest()!=result.get("artifact_sha256")
            or payload.get("schema_version")!="v4.manager_workbench.research.v1"
            or payload.get("rule_version") not in {"manager-close-rework-r2-v1", "20260921_REBOUND_V3_1530_OBSERVATION_V1"}
            or payload.get("market")!="HK_CONNECT" or payload.get("trade_date")!=request.business_date
            or payload.get("slot")!="1530" or payload.get("run_id")!=result.get("run_id")
            or payload.get("status") not in {"READY","READY_EMPTY","PARTIAL"}
            or payload.get("status")!=result.get("artifact_status")
            or any(payload.get(k) is not v for k,v in flags.items())): raise ValueError
        candidates=payload.get("candidates")
        if not isinstance(candidates,list) or not all(isinstance(c,dict) for c in candidates): raise ValueError
        if any(type(result.get(k)) is not int for k in ("candidate_count","observation_count","qualified_count")): raise ValueError
        if (len(candidates)!=result["candidate_count"] or len(candidates)!=result["observation_count"]
            or sum(c.get("qualified") is True for c in candidates)!=result["qualified_count"]): raise ValueError
        _validate_manager_close_readback(payload)
        if payload['rule_version'] == '20260921_REBOUND_V3_1530_OBSERVATION_V1':
            if not rebound_root or not Path(rebound_root).expanduser().is_absolute():
                raise ValueError('REBOUND_HISTORY_AUTHORITY_ROOT_NOT_BOUND')
            expected_binding = dict(schema_version='v4.manager_close.rebound_authority_binding.v1',
                root_sha256=hashlib.sha256(str(Path(rebound_root).expanduser().resolve()).encode()).hexdigest())
            if (result.get('published_rule_version') != payload['rule_version']
                or result.get('rebound_authority_binding') != expected_binding
                or payload['rebound_screen'].get('authority_binding') != expected_binding):
                raise ValueError('REBOUND_HISTORY_AUTHORITY_BINDING_MISMATCH')
    except (ValueError,TypeError,KeyError,OSError):
        fail("MANAGER_CHILD_RESULT_INVALID",child)
    return {"status":"SUCCEEDED","slot":"1530","modules":[module],"exit_code":0,
            "materializer":result,"artifact_status":result["artifact_status"],
            "qualified_count":result["qualified_count"],**flags}


def _manager_close_recapture_after_stage_workbench(
    self: Any, request: DispatchRequest, *, stage_result: dict[str, Any]
) -> dict[str, Any]:
    """Run the existing PyTDX recapture owner after the same-date 15:55 Stage.

    This is a caller of ``ops.materialize_manager_close_discovery`` only. It
    does not implement a quote producer, and it does not touch the historical
    1530 output lane.
    """
    import hashlib
    import json
    import os
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError

    module = "ops.materialize_manager_close_discovery"
    flags = {"RESEARCH_ONLY": True, "production_allowed": False,
             "buy_gate_updated": False, "orders_sent": False}

    def fail(reason: str, *, child: dict[str, Any] | None = None,
             failure_class: str = "UPSTREAM_NOT_READY") -> None:
        result = {"status": "FAILED", "workload_id": "stage_workbench",
                  "slot": request.slot, "modules": ["ops.materialize_stage_workbench", module],
                  "exit_code": 2, "failure_class": failure_class,
                  "reason": reason, "stage_workbench_status": stage_result.get("status"),
                  "stage_workbench_exit_code": stage_result.get("exit_code"), **flags}
        if child:
            result["close_recapture_child_status"] = child.get("status")
            result["close_recapture_child_exit_code"] = child.get("exit_code")
            try:
                payload = json.loads(str(child.get("stdout") or ""))
            except (TypeError, ValueError):
                payload = {}
            if isinstance(payload, dict):
                result["close_recapture_reason"] = payload.get("reason")
                result["close_recapture_status"] = payload.get("status")
            stderr = str(child.get("stderr") or "").strip()
            if stderr:
                result["child_stderr"] = stderr[:512]
        raise WorkloadExecutionError(result)

    if request.slot != "1555":
        fail("MANAGER_PYTDX_RECAPTURE_REQUIRES_1555_STAGE", failure_class="INVALID_INPUT")
    mode = str(getattr(request.mode, "value", request.mode))
    if mode != "LIVE":
        fail("MANAGER_PYTDX_RECAPTURE_LIVE_ONLY", failure_class="INVALID_INPUT")
    if not isinstance(stage_result, dict):
        fail("MANAGER_PYTDX_RECAPTURE_STAGE_RESULT_INVALID", failure_class="INVALID_INPUT")
    if os.environ.get("V4_MANAGER_CLOSE_CAPTURE_MODE", "").strip() != "PYTDX_LATE_OBSERVATION":
        fail("MANAGER_PYTDX_RECAPTURE_MODE_NOT_ENABLED", failure_class="INVALID_INPUT")

    configured_app = os.environ.get("V4_MANAGER_MATERIALIZER_APP_ROOT", "").strip()
    configured_sha = os.environ.get("V4_MANAGER_MATERIALIZER_SHA256", "").strip()
    configured_state = os.environ.get("V4_MANAGER_RESEARCH_STATE_ROOT", "").strip()
    configured_python = os.environ.get("V35_HK_0_2_REAL_PYTHON", "").strip()
    configured_provider = os.environ.get("V35_SHARED_PACKAGE_ROOT", "").strip()
    app = Path(configured_app).expanduser() if configured_app else None
    state = Path(configured_state).expanduser() if configured_state else None
    python = Path(configured_python).expanduser() if configured_python else None
    provider = Path(configured_provider).expanduser() if configured_provider else None
    universe = getattr(self, "hk_universe_root", None)
    shared_store = getattr(self, "shared_data_root", None)
    if (app is None or state is None or python is None or provider is None or universe is None
            or shared_store is None):
        fail("MANAGER_PYTDX_RECAPTURE_EXPLICIT_BINDING_MISSING", failure_class="INVALID_INPUT")
    app = app.resolve()
    state = state.resolve()
    universe = Path(universe).expanduser().resolve()
    shared_store = Path(shared_store).expanduser().resolve()
    provider = provider.resolve()
    module_path = app / module.replace(".", "/")
    module_path = module_path.with_suffix(".py")
    if (not app.is_dir() or not state.is_absolute() or not state.is_dir()
            or not universe.is_dir() or not provider.is_dir()
            or shared_store != (universe / ".runtime/data").resolve()
            or python is None or not python.is_absolute() or not python.is_file()
            or not os.access(python, os.X_OK)
            or not re.fullmatch(r"[0-9a-f]{64}", configured_sha)
            or not module_path.is_file()
            or hashlib.sha256(module_path.read_bytes()).hexdigest() != configured_sha):
        fail("MANAGER_PYTDX_RECAPTURE_BINDING_INVALID", failure_class="INVALID_INPUT")
    date = request.business_date
    expected_artifact = f"workbench_research/{date}/close_recapture.json"
    expected_receipt = f"workbench_research/{date}/close_recapture.receipt.json"
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": os.pathsep.join((str(app), str(app / "upstreams"),
                                        str(app / "upstreams/v3_shared_data"), str(provider))),
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "RESEARCH_ONLY": "true", "PRODUCTION_ALLOWED": "false",
        "BUY_GATE_UPDATED": "false", "ORDERS_SENT": "false",
    })
    args = ["--close-recapture", "--state-root", str(state),
            "--universe-root", str(universe), "--trade-date", date,
            "--app-root", str(app), "--pytdx-python", str(python),
            "--provider-root", str(provider)]
    timeout = min(420, max(30, int(getattr(self, "timeout_seconds", 420))))
    try:
        child = self._run(module, args, cwd=app, env=env, timeout_seconds=timeout)
    except (OSError, RuntimeError, ValueError) as error:
        fail(f"MANAGER_PYTDX_RECAPTURE_CHILD_START_FAILED:{type(error).__name__}")
    try:
        result = json.loads(str(child.get("stdout") or ""))
    except (TypeError, ValueError):
        result = {}
    identity = (isinstance(result, dict)
        and result.get("schema_version") == "v4.manager_close_recapture_result.v1"
        and result.get("source_trade_date") == date
        and result.get("module_origin") == str(module_path)
        and result.get("module_sha256") == configured_sha
        and result.get("state_root") == str(state)
        and result.get("capture_mode") == "LATE_OBSERVATION"
        and all(result.get(key) is value for key, value in flags.items()))
    if not identity:
        fail("MANAGER_PYTDX_RECAPTURE_CHILD_RESULT_INVALID", child=child, failure_class="INVALID_INPUT")
    if child.get("status") != "SUCCEEDED" or child.get("exit_code") != 0:
        reason = result.get("reason") or "MANAGER_PYTDX_RECAPTURE_CHILD_FAILED"
        fail(str(reason)[:160], child=child)
    if result.get("status") == "NOT_APPLICABLE":
        return {"status": "NOT_APPLICABLE", "slot": request.slot, "modules": [module],
                "exit_code": 0, "materializer": result, "no_op": True, **flags}
    if result.get("status") not in {"MATERIALIZED", "PARTIAL", "ALREADY_EXISTS"}:
        fail("MANAGER_PYTDX_RECAPTURE_STATUS_INVALID", child=child, failure_class="INVALID_INPUT")
    if result.get("artifact_ref") != expected_artifact or result.get("receipt_ref") != expected_receipt:
        fail("MANAGER_PYTDX_RECAPTURE_REFERENCE_INVALID", child=child, failure_class="INVALID_INPUT")
    try:
        artifact_path = resolve_owned_path(state, expected_artifact)
        receipt_path = resolve_owned_path(state, expected_receipt)
        artifact_raw = artifact_path.read_bytes()
        receipt_raw = receipt_path.read_bytes()
        payload = json.loads(artifact_raw)
        receipt = json.loads(receipt_raw)
        artifact_sha = hashlib.sha256(artifact_raw).hexdigest()
        receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
        snapshot_ref = result.get("snapshot_ref")
        candidate_ref = result.get("candidate_overlay_ref")
        snapshot_sha = result.get("snapshot_sha256")
        candidate_sha = result.get("candidate_overlay_sha256")
        snapshot_raw = resolve_owned_path(state, snapshot_ref).read_bytes()
        candidate_raw = resolve_owned_path(state, candidate_ref).read_bytes()
        snapshot = json.loads(snapshot_raw)
        candidate_overlay = json.loads(candidate_raw)
        if (artifact_sha != result.get("artifact_sha256")
                or receipt_sha != result.get("receipt_sha256")
                or hashlib.sha256(snapshot_raw).hexdigest() != snapshot_sha
                or hashlib.sha256(candidate_raw).hexdigest() != candidate_sha
                or payload.get("schema_version") != "v4.manager_close_recapture.v1"
                or payload.get("source_trade_date") != date
                or payload.get("plan_trade_date") != result.get("plan_trade_date")
                or payload.get("capture_mode") != "LATE_OBSERVATION"
                or payload.get("observation_type") != "PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION"
                or payload.get("pool", {}).get("trade_date") != date
                or payload.get("source", {}).get("provider") != "pytdx_exhq"
                or payload.get("source", {}).get("source_id") != "pytdx"
                or payload.get("bar_window", {}).get("stage_id") != "STAGE_1545_1555"
                or payload.get("snapshot", {}).get("artifact_ref") != snapshot_ref
                or payload.get("snapshot", {}).get("sha256") != snapshot_sha
                or payload.get("candidate_overlay", {}).get("artifact_ref") != candidate_ref
                or payload.get("candidate_overlay", {}).get("sha256") != candidate_sha
                or receipt.get("schema_version") != "v4.manager_close_recapture_receipt.v1"
                or receipt.get("source_trade_date") != date
                or receipt.get("target_trade_date") != result.get("plan_trade_date")
                or receipt.get("artifact_ref") != expected_artifact
                or receipt.get("artifact_sha256") != artifact_sha
                or receipt.get("snapshot_ref") != result.get("snapshot_ref")
                or receipt.get("snapshot_sha256") != result.get("snapshot_sha256")
                or receipt.get("candidate_overlay_ref") != result.get("candidate_overlay_ref")
                or receipt.get("candidate_overlay_sha256") != result.get("candidate_overlay_sha256")
                or snapshot.get("schema_version") != "v4.manager_close_recapture_pytdx_snapshot.v1"
                or snapshot.get("source_trade_date") != date
                or snapshot.get("stage_id") != "STAGE_1545_1555"
                or candidate_overlay.get("schema_version") != "v4.manager_close_recapture_candidate_overlay.v1"
                or candidate_overlay.get("source_trade_date") != date
                or candidate_overlay.get("target_trade_date") != result.get("plan_trade_date")
                or not isinstance(candidate_overlay.get("rows"), list)
                or len(candidate_overlay["rows"]) != result.get("candidate_count")
                or type(result.get("candidate_count")) is not int
                or result.get("candidate_count") <= 0
                or result.get("candidate_count") != payload.get("candidate_overlay", {}).get("count")
                or any(payload.get(key) is not value for key, value in flags.items())
                or any(receipt.get(key) is not value for key, value in flags.items())):
            raise ValueError("CLOSE_RECAPTURE_READBACK_MISMATCH")
    except (OSError, TypeError, ValueError, KeyError):
        fail("MANAGER_PYTDX_RECAPTURE_STORE_READBACK_INVALID", child=child, failure_class="INVALID_INPUT")
    return {"status": "SUCCEEDED" if result.get("status") != "PARTIAL" else "PARTIAL",
            "slot": request.slot, "modules": [module], "exit_code": 0,
            "stage_workbench_status": stage_result.get("status"),
            "stage_workbench_exit_code": stage_result.get("exit_code"),
            "materializer": result, "artifact_sha256": artifact_sha,
            "receipt_sha256": receipt_sha, **flags}

def _validate_manager_close_readback(payload: dict[str, Any]) -> None:
    """Versioned R2/V3 wire admission after the sole V4 child publishes.

    Full B1 validation runs in that child and in the API. This second readback
    rejects malformed/contradictory rows without importing V4 into the V35 owner.
    It never upgrades source strings into market evidence or enables new rules.
    """
    import math
    from datetime import datetime
    from zoneinfo import ZoneInfo
    rule = payload.get('rule_version')
    is_v3 = rule == '20260921_REBOUND_V3_1530_OBSERVATION_V1'
    if rule not in {'manager-close-rework-r2-v1', '20260921_REBOUND_V3_1530_OBSERVATION_V1'}:
        raise ValueError('RULE_VERSION_UNSUPPORTED')
    required = (('amount_100m_lt_le_200m_hkd', 'oversold_le_80pct_prior60_high',
                 'volume_ge_1_5_previous5_full_days', 'last_price_ge_1_03_low_so_far', 'final_close_confirmation')
                if is_v3 else
                ('turnover_gt_100m_hkd','verified_volume_expansion','verified_oversold_or_breakout','new_direct_pit_catalyst'))
    def stamp(value):
        if not isinstance(value,str): raise ValueError("TIME_MISSING")
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        if parsed.tzinfo is None: raise ValueError("TIME_NAIVE")
        return parsed
    as_of=stamp(payload.get("as_of")); generated=stamp(payload.get("generated_at"))
    local=as_of.astimezone(ZoneInfo("Asia/Hong_Kong"))
    if local.strftime("%Y%m%d")!=payload["trade_date"] or not (15,30)<=(local.hour,local.minute)<(15,32) or generated<as_of:
        raise ValueError("OBSERVATION_WINDOW_INVALID")
    coverage=payload.get("coverage",{})
    if any(type(coverage.get(k)) is not int or coverage[k]<0 for k in ("eligible_count","covered_count","missing_count")):
        raise ValueError("COVERAGE_INVALID")
    if coverage["covered_count"]+coverage["missing_count"]!=coverage["eligible_count"]: raise ValueError("COVERAGE_SUM_INVALID")
    symbols=set(); ids=set()
    for c in payload["candidates"]:
        if (not isinstance(c.get("candidate_id"),str) or not c["candidate_id"] or c["candidate_id"] in ids
            or not re.fullmatch(r"HK\.\d{5}",str(c.get("symbol",""))) or c["symbol"] in symbols
            or c.get("trade_date")!=payload["trade_date"]): raise ValueError("CANDIDATE_ID_INVALID")
        ids.add(c["candidate_id"]);symbols.add(c["symbol"])
        predicates=c.get("predicates")
        if not isinstance(predicates,list) or len(predicates)!=len(required): raise ValueError("CONDITIONS_MISSING")
        for p,key in zip(predicates,required):
            if (not isinstance(p,dict) or p.get("predicate_id")!=key or p.get("rule_version")!=payload["rule_version"]
                or not (type(p.get("value")) is bool or p.get("value")=="unknown")):
                raise ValueError("CONDITION_INVALID")
        if not is_v3 and any(p["value"]!="unknown" for p in predicates[1:3]): raise ValueError("UNIMPLEMENTED_AUTHORITY_POSITIVE")
        expected=False if any(p["value"] is False for p in predicates) else None
        if c.get("qualified") is not expected: raise ValueError("QUALIFIED_INCONSISTENT")
        for key in ("first_seen_at","last_seen_at","observed_at","available_at"):
            if stamp(c.get(key))>as_of: raise ValueError("CANDIDATE_FUTURE")
        amount=c.get("turnover_amount"); volume=c.get("volume_comparison")
        if (not isinstance(amount,dict) or "value" not in amount or not isinstance(volume,dict)
            or "ratio" not in volume or (not is_v3 and (volume["ratio"] is not None or volume.get("baseline_as_of") is not None))):
            raise ValueError("NESTED_VALUES_MISSING")
        value=amount["value"]
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value)): raise ValueError("AMOUNT_INVALID")
        if stamp(amount.get("as_of"))>as_of: raise ValueError("AMOUNT_FUTURE")
        if predicates[0]["value"]!="unknown":
            if (amount.get("currency")!="HKD" or amount.get("unit")!="HKD" or amount.get("contract_state")!="VERIFIED_HKD"
                or amount.get("status")!="OBSERVED" or value is None
                or predicates[0]["value"] is not (100_000_000<value<=200_000_000 if is_v3 else value>100_000_000)):
                raise ValueError("AMOUNT_CONTRACT_INVALID")
        sources=c.get("sources")
        if not isinstance(sources,list) or not sources: raise ValueError("LINEAGE_MISSING")
        for source in sources:
            if (not isinstance(source,dict) or any(not source.get(k) for k in ("owner","role","run_id","source_date","reason","sha256"))
                or source.get("lane") not in c.get("source_lanes",[]) or source.get("market")!="HK_CONNECT"
                or not re.fullmatch(r"[0-9a-f]{64}",str(source.get("sha256")))): raise ValueError("LINEAGE_INVALID")
            if not stamp(source.get("observed_at"))<=stamp(source.get("available_at"))<=as_of: raise ValueError("LINEAGE_FUTURE")

    if is_v3:
        _validate_manager_close_v3_wire(payload)

def _validate_manager_close_v3_wire(payload: dict[str, Any]) -> None:
    """Wire consistency only; source admission still belongs to V4 child/API.

    Do not import the V4 business modules into this separate hourly owner.
    This branch cannot promote unknown units or a 1530 price into final close.
    """
    import math
    from datetime import datetime
    from decimal import Decimal
    rule = '20260921_REBOUND_V3_1530_OBSERVATION_V1'
    phase = 'SNAPSHOT_1530_NOT_FINAL_CLOSE'
    screen = payload.get('rebound_screen')
    if (not isinstance(screen, dict) or screen.get('rule_version') != rule
        or screen.get('phase') != phase or 'final_close' not in screen
        or screen['final_close'] is not None or type(screen.get('confirmed_strict_count')) is not int
        or screen['confirmed_strict_count'] != 0 or payload.get('status') != 'PARTIAL'):
        raise ValueError('V3_FINAL_CLOSE_OR_PHASE_INVALID')
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    decisions = screen.get('source_rows')
    if not isinstance(decisions, list) or len(decisions) != payload['coverage']['covered_count']:
        raise ValueError('V3_DECISION_COVERAGE_INVALID')
    recorded = {}; groups = {'STRICT_ASOF_OBSERVATION': [], 'NEAR_ASOF_OBSERVATION': [], 'PENDING_EVIDENCE': []}
    for row in decisions:
        if not isinstance(row, dict) or not re.fullmatch(r'HK\.\d{5}', str(row.get('symbol', ''))) or row['symbol'] in recorded:
            raise ValueError('V3_DECISION_ID_INVALID')
        if (row.get('rule_version') != rule or row.get('approved_rule_version') != '20260921_REBOUND_V3'
            or row.get('phase') != phase or 'final_close' not in row or row['final_close'] is not None
            or row.get('close_confirmation') != 'unknown'):
            raise ValueError('V3_DECISION_PHASE_INVALID')
        metrics = row.get('metrics'); gates = metrics.get('gates') if isinstance(metrics, dict) else None
        if (not isinstance(gates, dict) or set(gates) != {'amount','oversold','volume','rebound'}
            or any(type(v) is not bool and v != 'unknown' for v in gates.values())):
            raise ValueError('V3_GATES_INVALID')
        strict = all(v is True for v in gates.values())
        near = (gates['amount'] is True and gates['oversold'] is True
                and all(gates[k] != 'unknown' for k in ('volume','rebound'))
                and sum(gates[k] is True for k in ('volume','rebound')) == 1)
        kind = ('EXCLUDED' if gates['amount'] is False or gates['oversold'] is False else
                'PENDING_EVIDENCE' if 'unknown' in gates.values() else
                'STRICT_ASOF_OBSERVATION' if strict else 'NEAR_ASOF_OBSERVATION' if near else 'EXCLUDED')
        if metrics.get('strict') is not strict or metrics.get('near') is not near or row.get('classification') != kind:
            raise ValueError('V3_UNKNOWN_OR_CLASSIFICATION_INVALID')
        for k in ('volume_ratio_5d','rebound_price_vs_low_pct','oversold_cutoff','near_failed_ratio'):
            if metrics.get(k) is not None and not number(metrics[k]): raise ValueError('V3_METRIC_INVALID')
        if gates['volume'] != 'unknown':
            ratio = metrics.get('volume_ratio_5d')
            if not number(ratio) or ratio < 0 or gates['volume'] is not (ratio >= 1.5):
                raise ValueError('V3_VOLUME_GATE_INVALID')
        if gates['rebound'] != 'unknown':
            price, low = row.get('last_price'), row.get('low_so_far')
            if (not number(price) or not number(low) or not 0 < low <= price
                or gates['rebound'] is not (Decimal(str(price)) >= Decimal('1.03') * Decimal(str(low)))):
                raise ValueError('V3_REBOUND_GATE_INVALID')
        if near:
            failed = 'volume' if gates['volume'] is False else 'rebound'
            failed_value = metrics['volume_ratio_5d'] if failed == 'volume' else metrics['rebound_price_vs_low_pct']
            threshold = 1.5 if failed == 'volume' else 3.0
            if (not number(failed_value) or metrics.get('near_failed_gate') != failed
                or metrics.get('near_failed_value') != failed_value or metrics.get('near_gate_value') != threshold
                or metrics.get('near_failed_ratio') != failed_value / threshold):
                raise ValueError('V3_NEAR_METRICS_INVALID')
        recorded[row['symbol']] = row
        if kind in groups: groups[kind].append(row['symbol'])
    visible = {r['symbol'] for r in decisions if r['classification'] != 'EXCLUDED'}
    if {c['symbol'] for c in payload['candidates']} != visible:
        raise ValueError('V3_VISIBLE_DECISION_SET_INVALID')
    for key, kind in [('strict_observation','STRICT_ASOF_OBSERVATION'),('near_observation','NEAR_ASOF_OBSERVATION'),('pending','PENDING_EVIDENCE')]:
        if (not isinstance(screen.get(key), list) or len(set(screen[key])) != len(screen[key])
            or set(screen[key]) != set(groups[kind])):
            raise ValueError('V3_GROUP_INVALID')
    for c in payload['candidates']:
        decision = c.get('position', {}).get('rebound_v3'); p = c['predicates']
        if not isinstance(decision, dict) or dict(symbol=c['symbol'], **decision) != recorded[c['symbol']]:
            raise ValueError('V3_CANDIDATE_DECISION_INVALID')
        gates = decision['metrics']['gates']
        if [v['value'] for v in p] != [gates[k] for k in ('amount','oversold','volume','rebound')] + ['unknown']:
            raise ValueError('V3_FIVE_PREDICATES_INVALID')
        priority = c.get('research_priority', {}); plan = c.get('observation_plan', {})
        if (c.get('data_status') != decision['classification'] or priority.get('level') != c['data_status']
            or priority.get('rule_version') != rule or priority.get('formal_rank_changed') is not False
            or priority.get('buy_gate_changed') is not False or plan.get('phase') != phase
            or 'final_close' not in plan or plan['final_close'] is not None):
            raise ValueError('V3_PLAN_OR_PRIORITY_INVALID')
        if gates['oversold'] != 'unknown':
            peak = c['position'].get('prior60_high'); price = decision.get('last_price')
            if not number(peak) or peak <= 0 or not number(price) or price <= 0:
                raise ValueError('V3_OVERSOLD_INPUT_INVALID')
            cutoff = Decimal('0.8') * Decimal(str(peak))
            if (decision['metrics'].get('oversold_cutoff') != float(cutoff)
                or gates['oversold'] is not (Decimal(str(price)) <= cutoff)):
                raise ValueError('V3_OVERSOLD_GATE_INVALID')
        volume = c['volume_comparison']; ratio = volume['ratio']
        if ratio is not None and (not number(ratio) or ratio < 0): raise ValueError('V3_VOLUME_RATIO_INVALID')
        if gates['volume'] == 'unknown':
            if ratio is not None or volume.get('baseline_as_of') is not None:
                raise ValueError('V3_UNKNOWN_VOLUME_INVALID')
        else:
            if ratio != decision['metrics']['volume_ratio_5d'] or volume.get('state') != 'CUMULATIVE_VS_PREVIOUS5_FULL_DAYS':
                raise ValueError('V3_VOLUME_COMPARISON_INVALID')
            baseline = datetime.fromisoformat(str(volume.get('baseline_as_of')).replace('Z','+00:00'))
            if baseline.tzinfo is None or baseline > datetime.fromisoformat(payload['as_of'].replace('Z','+00:00')):
                raise ValueError('V3_VOLUME_BASELINE_FUTURE')
    strict = sorted(groups['STRICT_ASOF_OBSERVATION'])
    near_rows = sorted((r for r in decisions if r['classification']=='NEAR_ASOF_OBSERVATION'),
        key=lambda r:(-(r['metrics']['near_failed_ratio'] or 0),r['symbol']))
    expected_focus = strict + [r['symbol'] for r in near_rows[:max(0,10-len(strict))]]
    if screen.get('focus_symbols') != expected_focus:
        raise ValueError('V3_FOCUS_INVALID')
    focus = payload.get('priority_summary', {}).get('focus', [])
    expected_ids = {c['candidate_id'] for c in payload['candidates'] if c['symbol'] in expected_focus}
    if (not isinstance(focus, list) or any(not isinstance(f, dict) for f in focus)
        or len(focus) != len(expected_ids) or {f.get('candidate_id') for f in focus} != expected_ids):
        raise ValueError('V3_FOCUS_ITEMS_INVALID')
