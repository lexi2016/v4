"""Single-owner V4 dispatcher with calendar and idempotency gates."""
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
from infrastructure.owned_io import SafeRoot
from infrastructure.scheduling.execution_ledger import ExecutionLedger, SchedulerLaneExpired
from infrastructure.scheduling.executor_registry import WorkloadExecutionError


Executor = Callable[[WorkloadDefinition, DispatchRequest, RunDecision], Any]

RETRYABLE_FAILURE_CLASSES = frozenset(
    {"UPSTREAM_NOT_READY", "INPUT_MISSING", "NETWORK", "EXTERNAL_SOURCE", "RESEARCH_SOURCE_REFRESH_RETRY_REQUIRED"}
)


# Verify the caller-pinned release and the six executing dispatch inputs.  This
# is NOT an audit of the entire release, nor a signature trust store.
_RUNTIME_IDENTITY_FILES = (
    "infrastructure/scheduling/dispatcher.py", "ops/run_scheduled_slot.py",
    "infrastructure/scheduling/executor_registry.py", "contracts/runtime_workloads.json",
    "domains/intraday_research.py", "ops/run_intraday_research.py",
)


def validate_release_identity() -> dict[str, str]:
    """Fail before claims/transport when API and scheduler release pins diverge."""
    names = ("V4_APP_ROOT", "V4_RELEASE_ID", "V4_RELEASE_MANIFEST_PATH", "V4_RELEASE_MANIFEST_SHA256")
    env = {name: os.environ.get(name, "") for name in names}
    if any(not value for value in env.values()):
        raise ValueError("RELEASE_IDENTITY_MISSING")
    app = Path(env["V4_APP_ROOT"]); path = Path(env["V4_RELEASE_MANIFEST_PATH"])
    if (not app.is_absolute() or not path.is_absolute() or ".." in app.parts or ".." in path.parts
            or app != Path(__file__).resolve().parents[2]
            or not re.fullmatch(r"[0-9a-f]{64}", env["V4_RELEASE_MANIFEST_SHA256"])):
        raise ValueError("RELEASE_IDENTITY_INVALID")
    raw = SafeRoot(path.parent).read_bytes(path.name, max_bytes=16 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != env["V4_RELEASE_MANIFEST_SHA256"]:
        raise ValueError("RELEASE_MANIFEST_SHA_MISMATCH")
    payload = json.loads(raw)
    if (payload.get("schema_version") != "v4.release_candidate.v1"
            or payload.get("candidate", {}).get("app_root") != str(app)
            or payload.get("candidate", {}).get("release_id") != env["V4_RELEASE_ID"]):
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
    return {"release_id": env["V4_RELEASE_ID"], "app_root": str(app),
            "release_manifest_path": str(path), "release_manifest_sha256": env["V4_RELEASE_MANIFEST_SHA256"]}


def refresh_retry_source_identity(identity: dict[str, Any]) -> dict[str, Any]:
    """Observe a bounded set of existing source pointers, never market files.

    These are change hints only: the original consumer still verifies dates,
    manifests, SHA and PIT before use. Timestamps and release code do not reset
    a data-dependency attempt budget.
    """
    items = []
    descriptors = identity.get("descriptors", [])
    if not isinstance(descriptors, list) or len(descriptors) > 8:
        descriptors = []
    uncertain = not descriptors
    for descriptor in descriptors:
        item = dict(descriptor)
        try:
            path = Path(descriptor["path"])
            if not path.is_absolute() or ".." in path.parts or path.resolve() != path:
                raise ValueError("SOURCE_POINTER_PATH_INVALID")
            try:
                with path.open("rb") as stream:
                    raw = stream.read(1024 * 1024 + 1)
            except FileNotFoundError:
                items.append({**item, "state": "MISSING"})
                continue
            if len(raw) > 1024 * 1024:
                raise ValueError("SOURCE_POINTER_OVERSIZED")
            if descriptor["kind"] == "shared_latest":
                payload = json.loads(raw)
                entries = payload["entries"]
                if not isinstance(entries, dict): raise ValueError("SOURCE_ENTRIES_INVALID")
                # Only the exact target/roles consumed by this request matter.
                selected = {}
                for key in descriptor["entry_keys"]:
                    entry = entries.get(key)
                    if entry is None: selected[key] = None; continue
                    if not isinstance(entry, dict): raise ValueError("SOURCE_ENTRY_INVALID")
                    selected[key] = {k: v for k, v in entry.items()
                        if k in {"run_id", "idempotency_key", "owner"} or k.endswith("sha256")}
                raw = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
            elif descriptor["kind"] != "pointer":
                raise ValueError("SOURCE_POINTER_KIND_INVALID")
            items.append({**item, "state": "OBSERVED", "sha256": hashlib.sha256(raw).hexdigest()})
        except (OSError, ValueError, KeyError, TypeError):
            uncertain = True
            items.append({**item, "state": "CANNOT_CONFIRM"})
    digest = hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": "v4.dispatch_retry_source.v1", "descriptors": descriptors,
            "status": "CANNOT_CONFIRM" if uncertain else "IDENTIFIED",
            "fingerprint": digest, "items": items}

def capture_retry_source_identity(executor: Executor, request: DispatchRequest,
                                  selected_ids: tuple[str, ...]) -> dict[str, Any]:
    if "research_panel_daily_a" in selected_ids:
        # Selector/backtest pointers are this producer's OUTPUTS. They cannot
        # identify changed TDX inputs. No cheap authoritative input manifest is
        # bound here; use the explicit bounded unknown-identity policy.
        identity = refresh_retry_source_identity({"descriptors": []})
        identity["reason"] = "A_DAILY_INPUT_IDENTITY_UNAVAILABLE"
        return identity
    descriptors = []
    panel_consumers = {"preselection_pools", "daily_materialize", "stage_workbench", "a_share_close_review"}
    if panel_consumers.intersection(selected_ids):
        selector_root = getattr(executor, "selector_data_root", None)
        paths = ([Path(selector_root) / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt"]
                 if selector_root else [])
        for path in paths:
            descriptor = {"path": str(path), "kind": "pointer"}
            if descriptor not in descriptors: descriptors.append(descriptor)
    if "preselection_pools" in selected_ids and getattr(executor, "shared_data_root", None):
        descriptors.append({"path": str(Path(executor.shared_data_root) / "latest.json"),
            "kind": "shared_latest", "entry_keys": [request.target_date + "/" + role for role in (
                "A_SHARE_V192_PREMARKET_POOL_V3", "HK_CONNECT_D1_TOP100_0_2")]})
    return refresh_retry_source_identity({"descriptors": descriptors})

def _failure_class(workload_results: tuple[dict[str, Any], ...]) -> str:
    """Return a typed, scheduler-consumable class for a failed dispatch."""
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
    source_identity: dict[str, Any] | None = None
    invoked_workload_ids: tuple[str, ...] = ()
    succeeded_workload_ids: tuple[str, ...] = ()
    production_allowed: bool = False
    buy_gate_updated: bool = False
    orders_sent: bool = False

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
            "source_identity": self.source_identity,
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
    source_identity: dict[str, Any] | None = None,
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
        source_identity=source_identity,
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
    if ledger is not None:
        try:
            ledger.validate_scheduler_lane(request.business_date, request.slot)
        except SchedulerLaneExpired:
            return _receipt(request, status="EXPIRED", run_id="", failure_class="NOT_DUE", **identity)
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
    source_identity = capture_retry_source_identity(executor, request, selected_ids)
    invoked: list[str] = []
    started: list[str] = []
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
                if ledger is not None:
                    ledger.validate_scheduler_lane(request.business_date, request.slot)
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
            except SchedulerLaneExpired:
                results.append({"status": "FAILED", "workload_id": workload.workload_id,
                    "failure_class": "NOT_DUE", "reason": "SCHEDULER_SLOT_EXPIRED",
                    "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})
                failed.append(workload.workload_id)
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
    receipt_path = (
        ledger.receipt_relative(request, run_id=run_id)
        if ledger is not None
        else ""
    )
    failure_class = _failure_class(tuple(results)) if status == "FAILED" else ""
    upstream_fingerprint = str(os.environ.get("V4_UPSTREAM_FINGERPRINT") or "")
    retry_after = ""
    if status == "FAILED" and failure_class in RETRYABLE_FAILURE_CLASSES:
        retry_after = (
            datetime.now(UTC) + timedelta(minutes=5)
        ).isoformat().replace("+00:00", "Z")
    receipt = _receipt(
        request,
        status=status,
        run_id=run_id,
        selected=selected_ids,
        started=tuple(started),
        invoked=tuple(invoked),
        source_identity=source_identity,
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
        payload["finished_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        ledger.write_receipt(receipt_path, payload)
        if status == "FAILED":
            ledger.release_failed_request(
                request,
                run_id=run_id,
                workload_ids=tuple(failed),
            )
    return receipt
