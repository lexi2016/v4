"""Single-owner V3.5 dispatcher with calendar and idempotency gates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from contracts.runtime_tasks import (
    DispatchMode,
    DispatchRequest,
    RuntimeCatalog,
    WorkloadDefinition,
)
from contracts.trading_calendar import MarketScope, RunPolicy, SessionRequirement
from domains.runtime_policy import RunDecision, evaluate_run_policy
from infrastructure.scheduling import manager_capture_retry as capture_retry
from infrastructure.owned_io import SafeRoot
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import WorkloadExecutionError


Executor = Callable[[WorkloadDefinition, DispatchRequest, RunDecision], Any]

RETRYABLE_FAILURE_CLASSES = frozenset(
    {"UPSTREAM_NOT_READY", "NETWORK", "EXTERNAL_SOURCE", "RESEARCH_SOURCE_REFRESH_RETRY_REQUIRED"}
)


# Verify the caller-pinned release and this explicit reviewed execution set.
# Split helpers, namespace adapters and their package initializers are pinned too.
# This is NOT a complete transitive dependency closure or signature trust store.
_RUNTIME_IDENTITY_FILES = (
    'infrastructure/scheduling/dispatcher.py',
    'infrastructure/scheduling/input_retry_identity.py',
    'ops/run_scheduled_slot.py',
    'infrastructure/scheduling/executor_registry.py',
    'contracts/runtime_workloads.json',
    'domains/intraday_research.py',
    'ops/run_intraday_research.py',
    'infrastructure/scheduling/manager_capture_retry.py',
    'infrastructure/scheduling/manager_close_executor.py',
    'ops/run_v35_macos_scheduler.py',
    'ops/run_v35_macos_scheduler_daemon.py',
    'contracts/__init__.py',
    'domains/_preselection_materializer_parts/__init__.py',
    'domains/_preselection_materializer_parts/_namespace.py',
    'domains/_preselection_materializer_parts/a_share_pool.py',
    'domains/_preselection_materializer_parts/hk_pool.py',
    'domains/_preselection_materializer_parts/hourly_pool.py',
    'domains/_preselection_materializer_parts/row_assembly.py',
    'domains/_preselection_materializer_parts/source_identity.py',
    'domains/preselection_materializer.py',
    'infrastructure/__init__.py',
    'infrastructure/interprocess_lock.py',
    'infrastructure/isolated_package_loader.py',
    'infrastructure/owned_io.py',
    'infrastructure/preselection_pool_store.py',
    'infrastructure/scheduling/__init__.py',
    'infrastructure/scheduling/_executor_registry_parts/__init__.py',
    'infrastructure/scheduling/_executor_registry_parts/_namespace.py',
    'infrastructure/scheduling/_executor_registry_parts/close_review.py',
    'infrastructure/scheduling/_executor_registry_parts/daily_reader.py',
    'infrastructure/scheduling/_executor_registry_parts/degradation.py',
    'infrastructure/scheduling/_executor_registry_parts/intraday_jobs.py',
    'infrastructure/scheduling/_executor_registry_parts/panel_evidence.py',
    'infrastructure/scheduling/_executor_registry_parts/panel_execution.py',
    'infrastructure/scheduling/_executor_registry_parts/preselection.py',
    'infrastructure/scheduling/_executor_registry_parts/process_boundary.py',
    'infrastructure/scheduling/_executor_registry_parts/research_jobs.py',
    'infrastructure/scheduling/_executor_registry_parts/research_materials.py',
    'infrastructure/scheduling/_executor_registry_parts/stage_jobs.py',
    'infrastructure/scheduling/_executor_registry_parts/us_digest.py',
    'ops/_run_v35_macos_scheduler_parts/__init__.py',
    'ops/_run_v35_macos_scheduler_parts/_namespace.py',
    'ops/_run_v35_macos_scheduler_parts/cli_entry.py',
    'ops/_run_v35_macos_scheduler_parts/runtime_validation.py',
    'ops/_run_v35_macos_scheduler_parts/schedule_selection.py',
    'ops/_run_v35_macos_scheduler_parts/scheduler_io.py',
    'ops/materialize_scheduled_preselection.py',
    'ops/materialize_shared_v192_preselection.py',
    'stage_center/__init__.py',
    'stage_center/_runner_parts/__init__.py',
    'stage_center/_runner_parts/_namespace.py',
    'stage_center/_runner_parts/a_candidate_authority.py',
    'stage_center/_runner_parts/a_name_authority.py',
    'stage_center/_runner_parts/configuration.py',
    'stage_center/_runner_parts/hk_candidate_authority.py',
    'stage_center/_runner_parts/hk_input_validation.py',
    'stage_center/_runner_parts/row_evidence.py',
    'stage_center/_runner_parts/runner_receipts.py',
    'stage_center/_runner_parts/selection_input_validation.py',
    'stage_center/_runner_parts/slot_execution.py',
    'stage_center/_runner_parts/slot_idempotency.py',
    'stage_center/_runner_parts/slot_lock.py',
    'stage_center/_runner_parts/tick_planning.py',
    'stage_center/runner.py',
)


def validate_release_identity() -> dict[str, str]:
    """Fail before claims/transport when API and scheduler release pins diverge."""
    names = ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256")
    env = {name: os.environ.get(name, "") for name in names}
    if any(not value for value in env.values()):
        raise ValueError("RELEASE_IDENTITY_MISSING")
    app = Path(env["V35_APP_ROOT"]); path = Path(env["V35_RELEASE_MANIFEST_PATH"])
    if (not app.is_absolute() or not path.is_absolute() or ".." in app.parts or ".." in path.parts
            or app != Path(__file__).resolve().parents[2]
            or not re.fullmatch(r"[0-9a-f]{64}", env["V35_RELEASE_MANIFEST_SHA256"])):
        raise ValueError("RELEASE_IDENTITY_INVALID")
    raw = SafeRoot(path.parent).read_bytes(path.name, max_bytes=16 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != env["V35_RELEASE_MANIFEST_SHA256"]:
        raise ValueError("RELEASE_MANIFEST_SHA_MISMATCH")
    payload = json.loads(raw)
    if (payload.get("schema_version") != "v4.release_candidate.v1"
            or payload.get("candidate", {}).get("app_root") != str(app)
            or payload.get("candidate", {}).get("release_id") != env["V35_RELEASE_ID"]):
        raise ValueError("RELEASE_MANIFEST_IDENTITY_MISMATCH")
    inventory = payload["application_inventory"]; entries = inventory["entries"]
    if (not isinstance(entries, list) or inventory.get("entry_count") != len(entries)
            or hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True,
                 separators=(",", ":")).encode()).hexdigest() != inventory.get("aggregate_sha256")):
        raise ValueError("RELEASE_INVENTORY_MISMATCH")
    by_path = {item["path"]: item for item in entries}
    if len(by_path) != len(entries):
        raise ValueError("RELEASE_INVENTORY_DUPLICATE")
    source = SafeRoot(app)
    for relative in _RUNTIME_IDENTITY_FILES:
        item = by_path.get(relative, {})
        content = source.read_bytes(relative, max_bytes=8 * 1024 * 1024)
        if (item.get("kind") != "file" or item.get("size") != len(content)
                or item.get("sha256") != hashlib.sha256(content).hexdigest()):
            raise ValueError("RELEASE_RUNTIME_BYTES_MISMATCH")
    return {"release_id": env["V35_RELEASE_ID"], "app_root": str(app),
            "release_manifest_path": str(path), "release_manifest_sha256": env["V35_RELEASE_MANIFEST_SHA256"]}


def _failure_class(workload_results: tuple[dict[str, Any], ...]) -> str:
    """Return a typed, scheduler-consumable class for a failed dispatch."""
    # Deterministic contract rejection takes priority over a sibling's outage.
    for result in workload_results:
        explicit = str(result.get("failure_class") or "").strip().upper()
        if explicit in {"INVALID_INPUT", "CONTRACT", "SAFETY"}:
            return explicit
    for result in workload_results:
        explicit = str(result.get("failure_class") or "").strip().upper()
        if explicit:
            return explicit
    text = " ".join(
        str(result.get(field) or "")
        for result in workload_results
        for field in ("status", "stderr", "stdout", "reason")
    ).lower()
    if any(token in text for token in ("timeout", "network", "connection", "proxy")):
        return "NETWORK"
    if any(token in text for token in ("upstream", "not ready", "missing", "unavailable")):
        return "UPSTREAM_NOT_READY"
    if any(token in text for token in ("external", "finance", "research source")):
        return "EXTERNAL_SOURCE"
    if any(token in text for token in ("unsafe", "safety")):
        return "SAFETY"
    return "CONTRACT"


@dataclass(frozen=True)
class DispatchReceipt:
    schema_version: str
    status: str
    run_id: str
    scheduled_date: str
    business_date: str
    target_date: str
    slot: str
    mode: DispatchMode
    selected_workload_ids: tuple[str, ...]
    started_workload_ids: tuple[str, ...]
    eligible_markets: tuple[str, ...]
    blocked_markets: tuple[str, ...]
    resolved_dates: dict[str, dict[str, str]]
    receipt_path: str
    workload_results: tuple[dict[str, Any], ...] = ()
    failure_class: str = ""
    retry_after: str = ""
    release_id: str = ""
    upstream_fingerprint: str = ""
    app_root: str = ""
    release_manifest_path: str = ""
    release_manifest_sha256: str = ""
    attempt: int = 0
    production_allowed: bool = False
    buy_gate_updated: bool = False
    orders_sent: bool = False
    invoked_workload_ids: tuple[str, ...] = ()
    succeeded_workload_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "run_id": self.run_id,
            "scheduled_date": self.scheduled_date,
            "business_date": self.business_date,
            "target_date": self.target_date,
            "slot": self.slot,
            "mode": self.mode.value,
            "selected_workload_ids": list(self.selected_workload_ids),
            "started_workload_ids": list(self.started_workload_ids),
            "invoked_workload_ids": list(self.invoked_workload_ids),
            "succeeded_workload_ids": list(self.succeeded_workload_ids),
            "eligible_markets": list(self.eligible_markets),
            "blocked_markets": list(self.blocked_markets),
            "resolved_dates": self.resolved_dates,
            "receipt_path": self.receipt_path,
            "workload_results": list(self.workload_results),
            "failure_class": self.failure_class,
            "retry_after": self.retry_after,
            "release_id": self.release_id,
            "upstream_fingerprint": self.upstream_fingerprint,
            "app_root": self.app_root,
            "release_manifest_path": self.release_manifest_path,
            "release_manifest_sha256": self.release_manifest_sha256,
            "attempt": self.attempt,
            "production_allowed": self.production_allowed,
            "buy_gate_updated": self.buy_gate_updated,
            "orders_sent": self.orders_sent,
        }


def _resolved_dates(
    workload: WorkloadDefinition,
    request: DispatchRequest,
) -> dict[str, str]:
    values = {
        "SCHEDULED_DATE": request.scheduled_date,
        "BUSINESS_DATE": request.business_date,
        "TARGET_DATE": request.target_date,
    }
    return {
        "scheduled_date": values[workload.scheduled_date_role],
        "signal_date": values[workload.signal_date_role],
        "target_date": values[workload.target_date_role],
    }


def _receipt(
    request: DispatchRequest,
    *,
    status: str,
    run_id: str,
    selected: tuple[str, ...] = (),
    started: tuple[str, ...] = (),
    invoked: tuple[str, ...] = (),
    eligible_markets: tuple[str, ...] = (),
    blocked_markets: tuple[str, ...] = (),
    resolved_dates: dict[str, dict[str, str]] | None = None,
    receipt_path: str = "",
    workload_results: tuple[dict[str, Any], ...] = (),
    failure_class: str = "",
    retry_after: str = "",
    release_id: str = "",
    upstream_fingerprint: str = "",
    app_root: str = "",
    release_manifest_path: str = "",
    release_manifest_sha256: str = "",
    attempt: int = 0,
) -> DispatchReceipt:
    return DispatchReceipt(
        schema_version="v3_5.dispatch.v1",
        status=status,
        run_id=run_id,
        scheduled_date=request.scheduled_date,
        business_date=request.business_date,
        target_date=request.target_date,
        slot=request.slot,
        mode=request.mode,
        selected_workload_ids=selected,
        started_workload_ids=started,
        invoked_workload_ids=invoked,
        succeeded_workload_ids=started,
        eligible_markets=eligible_markets,
        blocked_markets=blocked_markets,
        resolved_dates=resolved_dates or {},
        receipt_path=receipt_path,
        workload_results=workload_results,
        failure_class=failure_class,
        retry_after=retry_after,
        release_id=release_id,
        upstream_fingerprint=upstream_fingerprint,
        app_root=app_root,
        release_manifest_path=release_manifest_path,
        release_manifest_sha256=release_manifest_sha256,
        attempt=attempt,
    )


def _cadence_eligible(
    workload: WorkloadDefinition,
    request: DispatchRequest,
) -> bool:
    if (
        workload.run_policy is not RunPolicy.NATURAL_DAY
        or not workload.non_trading_day_slots
    ):
        return True
    market_day = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        request.business_date,
        request.slot,
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )
    return market_day.eligible or request.slot in workload.non_trading_day_slots


def dispatch_due(
    request: DispatchRequest,
    catalog: RuntimeCatalog,
    executor: Executor,
    *,
    ledger: ExecutionLedger | None = None,
    dry_run: bool = False,
) -> DispatchReceipt:
    if catalog.safety.production_allowed or catalog.safety.buy_gate_updated or catalog.safety.orders_sent:
        raise ValueError("unsafe runtime catalog")
    try:
        identity = validate_release_identity()
    except (OSError, ValueError, KeyError, TypeError):
        # No claim, executor, or allegedly verified identity on failure.
        return _receipt(request, status="FAILED", run_id=uuid4().hex, failure_class="RELEASE_IDENTITY")
    is_capture = request.slot == "1530" and request.mode.value == "LIVE" and not dry_run
    if is_capture:
        if ledger is None:
            return _receipt(request, status="FAILED", run_id=uuid4().hex, failure_class="CAPTURE_LEDGER_REQUIRED", **identity)
        if request.scheduled_date != request.business_date or request.target_date != request.business_date:
            return _receipt(request, status="FAILED", run_id=uuid4().hex, failure_class="CAPTURE_DATE_IDENTITY", **identity)
        state = capture_retry.capture_state(ledger.root, request.business_date, datetime.now(UTC))
        if not state["due"]:
            return _receipt(request, status="CAPTURE_NOT_DUE", run_id=uuid4().hex,
                            failure_class=state["status"], **identity)
    if dry_run and ledger is not None:
        ledger = ledger.dry_run_namespace()
    if ledger is not None:
        prior_attempts = sum(
            1
            for item in ledger.list_receipts(
                request.business_date, mode=request.mode.value
            )
            if str(item.get("slot") or "") == request.slot
        )
        claim = ledger.try_claim_dispatch(request)
        if not claim.acquired:
            return _receipt(
                request,
                status="CONCURRENCY_SKIPPED",
                run_id=claim.run_id,
                **identity,
            )
        run_id = claim.run_id
        if is_capture:
            try:
                prior_attempts = capture_retry.reserve_attempt(ledger.root, request.business_date,
                                                               run_id, datetime.now(UTC)) - 1
            except (ValueError, OSError):
                ledger.release_failed_request(request, run_id=run_id, workload_ids=())
                return _receipt(request, status="FAILED", run_id=run_id,
                                failure_class="CAPTURE_RESERVATION_REJECTED", **identity)
    else:
        run_id = uuid4().hex
        prior_attempts = 0
    due = tuple(
        workload
        for workload in catalog.workloads
        if workload.enabled and request.slot in workload.slots
    )
    decisions: dict[str, RunDecision] = {
        workload.workload_id: evaluate_run_policy(
            workload.run_policy,
            request.business_date,
            request.slot,
            market_scope=workload.market_scope,
            session_requirement=workload.session_requirement,
        )
        for workload in due
    }
    cadence_eligible = {
        workload.workload_id: _cadence_eligible(workload, request)
        for workload in due
    }
    selected_workloads = tuple(
        workload
        for workload in due
        if decisions[workload.workload_id].eligible
        and cadence_eligible[workload.workload_id]
    )
    selected_ids = tuple(workload.workload_id for workload in selected_workloads)
    eligible_markets = tuple(
        sorted(
            {
                market
                for workload in selected_workloads
                for market in decisions[workload.workload_id].eligible_markets
            }
        )
    )
    blocked_markets = tuple(
        sorted(
            {
                market
                for workload in due
                for market in decisions[workload.workload_id].blocked_markets
            }
        )
    )
    resolved_dates = {
        workload.workload_id: _resolved_dates(workload, request)
        for workload in selected_workloads
    }
    if not due:
        status = "NO_DUE_WORKLOADS"
    elif not selected_workloads and any(
        workload.run_policy is RunPolicy.NATURAL_DAY
        and not cadence_eligible[workload.workload_id]
        for workload in due
    ):
        status = "NON_TRADING_DAY_CADENCE"
    elif not selected_workloads:
        status = (
            "NON_TRADING_DAY"
            if all(decision.reason in {"NON_TRADING_DAY", "UNKNOWN"} for decision in decisions.values())
            else "NO_ELIGIBLE_WORKLOADS"
        )
    elif dry_run:
        status = "DRY_RUN_SELECTED"
    else:
        status = "SUCCEEDED"
    started: list[str] = []
    invoked: list[str] = []
    results: list[dict[str, Any]] = []
    failed: list[str] = []
    if selected_workloads and not dry_run:
        for workload in selected_workloads:
            if ledger is not None:
                workload_claim = ledger.try_claim_workload(
                    request,
                    workload,
                    run_id=run_id,
                )
                if not workload_claim.acquired:
                    continue
            try:
                # Keep the legacy started field's success semantics, while
                # exposing calls that fail before producing a successful result.
                from infrastructure.scheduling.input_retry_identity import observe_input_identity, make_input_wait, input_wait_changed
                before_identity = observe_input_identity(workload.workload_id, request.business_date, request.target_date, request.slot)
                prior_wait = None
                prior_output = None
                if ledger is not None and before_identity is not None:
                    prior = sorted(ledger.list_receipts(request.business_date, mode=request.mode.value),
                        key=lambda item: str(item.get("finished_at") or ""), reverse=True)
                    for item in prior:
                        if str(item.get("slot")) != request.slot:
                            continue
                        prior_output = next((r for r in item.get("workload_results", [])
                            if r.get("workload_id") == workload.workload_id), None)
                        prior_wait = prior_output.get("input_wait") if prior_output is not None else None
                        if prior_output is not None:
                            break
                if prior_wait is not None and not input_wait_changed(prior_wait):
                    output = {**prior_output, "workload_id": workload.workload_id,
                        "input_wait": prior_wait,
                        "reason": "UNCHANGED_INPUT_WAIT", "producer_called": False}
                elif (prior_output is not None
                        and prior_output.get("status") == "FAILED"
                        and str(prior_output.get("failure_class") or "") in RETRYABLE_FAILURE_CLASSES
                        and prior_output.get("retry_after")
                        and datetime.now(UTC) < datetime.fromisoformat(str(prior_output["retry_after"]).replace("Z", "+00:00"))):
                    output = {**prior_output, "reason": "TRANSIENT_BACKOFF", "producer_called": False}
                else:
                    invoked.append(workload.workload_id)
                    output = executor(workload, request, decisions[workload.workload_id])

                if isinstance(output, dict):
                    output = dict(output)
                    output.setdefault("workload_id", workload.workload_id)
                    output.setdefault("status", "SUCCEEDED")
                    output.setdefault("modules", (workload.workload_id,))
                    output.setdefault("exit_code", 0)
                else:
                    output = {
                        "status": "SUCCEEDED",
                        "workload_id": workload.workload_id,
                        "modules": (workload.workload_id,),
                        "exit_code": 0,
                    }
                unsafe = any(
                    bool(output.get(field))
                    for field in ("production_allowed", "buy_gate_updated", "orders_sent")
                )
                output["production_allowed"] = False
                output["buy_gate_updated"] = False
                output["orders_sent"] = False
                status_value = str(output.get("status") or "FAILED")
                if unsafe:
                    output["status"] = "FAILED"
                    output["stderr"] = (
                        str(output.get("stderr") or "")
                        + "\nunsafe safety boundary"
                    ).strip()
                elif status_value not in {"SUCCEEDED", "ALREADY_EXISTS"}:
                    output["status"] = "FAILED"
                    output["stderr"] = (
                        str(output.get("stderr") or "")
                        + f"\nunsupported executor status: {status_value}"
                    ).strip()
                results.append(output)
                if output["status"] != "SUCCEEDED" and output["status"] != "ALREADY_EXISTS":
                    failed.append(workload.workload_id)
                else:
                    started.append(workload.workload_id)
            except WorkloadExecutionError as error:
                result = dict(error.result)
                result.setdefault("workload_id", workload.workload_id)
                result.setdefault("modules", [workload.workload_id])
                result.setdefault("exit_code", 1)
                result.setdefault("stderr", str(error))
                result["production_allowed"] = False
                result["buy_gate_updated"] = False
                result["orders_sent"] = False
                results.append(result)
                failed.append(workload.workload_id)
            except Exception as error:  # executor contracts must fail closed
                results.append(
                    {
                        "status": "FAILED",
                        "workload_id": workload.workload_id,
                        "modules": [],
                        "exit_code": 1,
                        "stderr": f"{type(error).__name__}: {error}",
                        "production_allowed": False,
                        "buy_gate_updated": False,
                        "orders_sent": False,
                    }
                )
                failed.append(workload.workload_id)
        if failed:
            status = "FAILED"
        elif len(started) != len(selected_workloads):
            status = "DUPLICATE_WORKLOAD_SKIPPED"
    if status == "FAILED":
        from infrastructure.scheduling.input_retry_identity import observe_input_identity, make_input_wait
        for output in results:
            if output.get("status") in {"SUCCEEDED", "ALREADY_EXISTS"}:
                continue
            kind = str(output.get("failure_class") or "") or _failure_class((output,))
            output.setdefault("failure_class", kind)
            if kind in {"UPSTREAM_NOT_READY", "INVALID_INPUT", "CONTRACT", "HK_HISTORY_RESOLUTION_CACHE_REJECTED"}:
                input_identity = observe_input_identity(str(output.get("workload_id") or ""), request.business_date, request.target_date, request.slot)
                if input_identity is not None and not isinstance(output.get("input_wait"), dict):
                    output["input_wait"] = make_input_wait(input_identity, str(output.get("failure_code") or kind))
            if (kind in RETRYABLE_FAILURE_CLASSES and not isinstance(output.get("input_wait"), dict)
                    and observe_input_identity(str(output.get("workload_id") or ""), request.business_date, request.target_date, request.slot) is not None):
                output.setdefault("retry_after", (datetime.now(UTC) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
    receipt_path = (
        ledger.receipt_relative(request, run_id=run_id)
        if ledger is not None
        else ""
    )
    failure_class = _failure_class(tuple(results)) if status == "FAILED" else ""
    upstream_fingerprint = str(os.environ.get("V35_UPSTREAM_FINGERPRINT") or "")
    retry_after = ""
    finished_at = datetime.now(UTC)
    capture_metadata = None
    if is_capture:
        capture_metadata = capture_retry.retry_metadata(request.business_date, prior_attempts + 1, finished_at)
        if status != "FAILED" or failure_class not in capture_retry.RETRYABLE:
            capture_metadata.update(status="COMPLETED" if status == "SUCCEEDED" else "TERMINAL", retry_after="")
    if status == "FAILED" and failure_class in RETRYABLE_FAILURE_CLASSES:
        if is_capture:
            retry_after = capture_metadata["retry_after"] if failure_class in capture_retry.RETRYABLE else ""
        else:
            retry_after = (finished_at + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    if status == "FAILED" and not is_capture:
        transient_deadlines = [str(output["retry_after"]) for output in results
            if output.get("status") == "FAILED" and output.get("retry_after")
            and not isinstance(output.get("input_wait"), dict)
            and output.get("failure_class") in RETRYABLE_FAILURE_CLASSES]
        if transient_deadlines:
            retry_after = min(transient_deadlines)
    receipt = _receipt(
        request,
        status=status,
        run_id=run_id,
        selected=selected_ids,
        started=tuple(started),
        invoked=tuple(invoked),
        eligible_markets=eligible_markets,
        blocked_markets=blocked_markets,
        resolved_dates=resolved_dates,
        receipt_path=receipt_path,
        workload_results=tuple(results),
        failure_class=failure_class,
        retry_after=retry_after,
        **identity,
        upstream_fingerprint=upstream_fingerprint,
        attempt=prior_attempts + 1,
    )
    if ledger is not None:
        payload = receipt.to_dict()
        payload["finished_at"] = finished_at.isoformat().replace("+00:00", "Z")
        if capture_metadata is not None:
            payload["capture_retry"] = capture_metadata
        ledger.write_receipt(receipt_path, payload)
        # Consumer success may still have an unfinished formal lane. Release
        # only that incomplete workload's own claim; successful siblings retain
        # their original claims and never re-enter their executors.
        incomplete = tuple(dict.fromkeys([*failed, *(str(output["workload_id"])
            for output in results if isinstance(output.get("input_wait"), dict)
            and output["input_wait"].get("wait_for_input_change") is True)]))
        if status == "FAILED" or incomplete:
            ledger.release_failed_request(request, run_id=run_id, workload_ids=incomplete)
    return receipt
