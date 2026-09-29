"""Minimal idempotent execution guard for one bounded HKCONNECT experiment.

This module deliberately does not know how EXPERIMENT_REGISTRY.jsonl is stored or
validated.  Local Codex must adapt the existing official registry reader/builder
to the tiny RegistryBackend protocol below.  No model package is imported here.

Durability rule:
* RUN_STARTED is the fit-budget debit and MUST be durably appended before fit.
* Any prior RUN_STARTED for the same execution_id blocks automatic re-entry,
  regardless of whether a terminal event exists.
* An unclosed RUN_STARTED is counted as one budget debit and the exact actual-fit
  count is CANNOT_CONFIRM; it is never auto-retried.
* Terminalization is an adapter operation, not a generic append.  The adapter
  must validate the durable start, identity, and single-terminal invariant while
  holding the same registry lock used by the claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence, TypeVar

T = TypeVar("T")

REAL_FIT_EXECUTION_KIND = "REAL_FIT"
NO_FIT_ENGINEERING_KIND = "NO_FIT_ENGINEERING_CANARY"



class RegistryBackend(Protocol):
    """Adapter over the project's existing registry mechanism.

    list_events() must return normalized events for exactly one experiment_id.
    claim_run_started() and terminalize() must use the existing official
    append/validation path; this core module must not create a second ledger or
    database.  Both operations are atomic at the adapter boundary.
    """

    def list_events(self, experiment_id: str) -> Sequence[Mapping[str, Any]]: ...

    def claim_run_started(self, event: Mapping[str, Any], *, max_real_fit_debits: int) -> None:
        """Atomically check+append one RUN_STARTED using the existing registry.

        In one critical section, the adapter must: reject any existing event with
        the same execution_id; count RUN_STARTED real_fit_budget_debit values for
        the same experiment_id and reject when the cap is exhausted; append the
        supplied RUN_STARTED; and durably flush it before returning.  If the
        official builder has no lock, use an OS file lock on the existing registry
        file for this critical section.  Do not create a second ledger.
        """
        ...

    def terminalize(self, claim: "ExecutionClaim", event: Mapping[str, Any]) -> None:
        """Atomically append one terminal event for one durable start.

        The adapter must hold the registry lock while it verifies exactly one
        matching RUN_STARTED, rejects a forged/mismatched claim, rejects an
        existing terminal, appends the terminal through the official builder,
        and flushes/fsyncs before returning.
        """
        ...


class ExecutionGuardError(RuntimeError):
    pass


class DuplicateExecutionId(ExecutionGuardError):
    pass


class RealFitBudgetExceeded(ExecutionGuardError):
    pass


class RegistryIntegrityError(ExecutionGuardError):
    """The registry lifecycle cannot be interpreted without guessing."""


class TerminalizationRejected(ExecutionGuardError):
    """A terminal event did not match its one durable start."""


@dataclass(frozen=True)
class ExecutionClaim:
    experiment_id: str
    execution_id: str
    arm: str
    contract_sha256: str
    input_binding_sha256: str
    execution_kind: str = REAL_FIT_EXECUTION_KIND
    real_fit_budget_debit: int = 1


@dataclass(frozen=True)
class AccountingSummary:
    experiment_id: str
    run_started_count: int
    real_fit_budget_debit_count: int
    terminal_count: int
    completed_count: int
    failed_count: int
    dangling_execution_ids: tuple[str, ...]
    fit_attempted_count: int
    returned_fit_count_lower_bound: int
    actual_fit_count_status: str
    no_fit_started_count: int = 0
    no_fit_terminal_count: int = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _execution_kind(event: Mapping[str, Any]) -> str:
    value = event.get("execution_kind")
    if value in (None, ""):
        # Historical guard events predate execution_kind and are real-fit debits.
        return REAL_FIT_EXECUTION_KIND
    value = str(value)
    if value not in {REAL_FIT_EXECUTION_KIND, NO_FIT_ENGINEERING_KIND}:
        raise RegistryIntegrityError(f"unsupported execution_kind: {value}")
    return value


def _planned_real_fit_count(event: Mapping[str, Any], kind: str) -> int:
    default = 1 if kind == REAL_FIT_EXECUTION_KIND else 0
    value = event.get("planned_real_fit_count", default)
    if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1):
        raise RegistryIntegrityError(f"invalid planned_real_fit_count: {value}")
    return value


def _require_identity(event: Mapping[str, Any], *, label: str) -> tuple[str, str, str, str, str]:
    """Return lifecycle identity fields, failing closed on missing values."""

    values = tuple(str(event.get(field, "")) for field in (
        "experiment_id",
        "execution_id",
        "arm",
        "contract_sha256",
    ))
    input_binding = str(event.get("input_binding_sha256", ""))
    if not all(values) or not input_binding:
        raise RegistryIntegrityError(f"{label}:missing_lifecycle_identity")
    return (*values, input_binding)


def summarize(events: Sequence[Mapping[str, Any]], experiment_id: str) -> AccountingSummary:
    if not experiment_id:
        raise ValueError("experiment_id must be non-empty")

    scoped = [e for e in events if e.get("experiment_id") == experiment_id]
    starts = [e for e in scoped if e.get("event_type") == "RUN_STARTED"]
    terminals = [e for e in scoped if e.get("event_type") == "TERMINAL"]
    unknown = [e.get("event_type") for e in scoped if e.get("event_type") not in {"RUN_STARTED", "TERMINAL"}]
    if unknown:
        raise RegistryIntegrityError(f"unsupported lifecycle event types: {unknown}")

    starts_by_id: dict[str, Mapping[str, Any]] = {}
    for event in starts:
        identity = _require_identity(event, label="RUN_STARTED")
        execution_id = identity[1]
        if execution_id in starts_by_id:
            raise RegistryIntegrityError(f"duplicate RUN_STARTED: {execution_id}")
        kind = _execution_kind(event)
        debit = event.get("real_fit_budget_debit")
        planned = _planned_real_fit_count(event, kind)
        if isinstance(debit, bool) or not isinstance(debit, int):
            raise RegistryIntegrityError(f"invalid real_fit_budget_debit: {execution_id}")
        if kind == REAL_FIT_EXECUTION_KIND and (debit != 1 or planned != 1):
            raise RegistryIntegrityError(f"invalid real-fit start accounting: {execution_id}")
        if kind == NO_FIT_ENGINEERING_KIND and (debit != 0 or planned != 0):
            raise RegistryIntegrityError(f"invalid no-fit start accounting: {execution_id}")
        starts_by_id[execution_id] = event

    terminals_by_id: dict[str, Mapping[str, Any]] = {}
    for event in terminals:
        identity = _require_identity(event, label="TERMINAL")
        execution_id = identity[1]
        if execution_id in terminals_by_id:
            raise RegistryIntegrityError(f"duplicate TERMINAL: {execution_id}")
        start = starts_by_id.get(execution_id)
        if start is None:
            raise RegistryIntegrityError(f"TERMINAL without RUN_STARTED: {execution_id}")
        start_identity = _require_identity(start, label="RUN_STARTED")
        if identity != start_identity:
            raise RegistryIntegrityError(f"terminal identity mismatch: {execution_id}")
        start_kind = _execution_kind(start)
        terminal_kind = _execution_kind(event)
        if terminal_kind != start_kind:
            raise RegistryIntegrityError(f"terminal execution_kind mismatch: {execution_id}")
        returned = event.get("real_fit_returned_count")
        if isinstance(returned, bool) or returned not in (0, 1):
            raise RegistryIntegrityError(f"invalid real_fit_returned_count: {execution_id}")
        entered = event.get("fit_call_entered")
        if not isinstance(entered, bool):
            raise RegistryIntegrityError(f"invalid fit_call_entered: {execution_id}")
        status = str(event.get("terminal_status", ""))
        if start_kind == REAL_FIT_EXECUTION_KIND:
            if status == "COMPLETED" and (not entered or returned != 1):
                raise RegistryIntegrityError(f"completed terminal has invalid fit accounting: {execution_id}")
            if status.startswith("FAILED") and (not entered or returned != 0):
                raise RegistryIntegrityError(f"failed terminal has invalid fit accounting: {execution_id}")
        elif entered or returned != 0:
            raise RegistryIntegrityError(f"no-fit terminal entered fit accounting: {execution_id}")
        terminals_by_id[execution_id] = event

    dangling = tuple(sorted(set(starts_by_id) - set(terminals_by_id)))
    completed = sum(e.get("terminal_status") == "COMPLETED" for e in terminals_by_id.values())
    failed = sum(str(e.get("terminal_status", "")).startswith("FAILED") for e in terminals_by_id.values())
    attempted = sum(bool(e.get("fit_call_entered")) for e in terminals_by_id.values())
    returned = sum(int(e.get("real_fit_returned_count", 0) or 0) for e in terminals_by_id.values())
    budget_debits = sum(int(e.get("real_fit_budget_debit", 0) or 0) for e in starts_by_id.values())

    return AccountingSummary(
        experiment_id=experiment_id,
        run_started_count=len(starts_by_id),
        real_fit_budget_debit_count=budget_debits,
        terminal_count=len(terminals_by_id),
        completed_count=completed,
        failed_count=failed,
        dangling_execution_ids=dangling,
        fit_attempted_count=attempted,
        returned_fit_count_lower_bound=returned,
        actual_fit_count_status=(
            "CANNOT_CONFIRM_DANGLING_RUN_STARTED" if dangling else "EXACT_FOR_TERMINALIZED_EXECUTIONS"
            if not failed else "CANNOT_CONFIRM_FAILED_DURING_FIT_CALL"
        ),
        no_fit_started_count=sum(_execution_kind(e) == NO_FIT_ENGINEERING_KIND for e in starts_by_id.values()),
        no_fit_terminal_count=sum(_execution_kind(e) == NO_FIT_ENGINEERING_KIND for e in terminals_by_id.values()),
    )


class ExecutionGuard:
    """Idempotence + cumulative debit for one fixed experiment only."""

    def __init__(self, backend: RegistryBackend, *, experiment_id: str, max_real_fit_debits: int = 2):
        if max_real_fit_debits < 0:
            raise ValueError("max_real_fit_debits must be non-negative")
        self.backend = backend
        self.experiment_id = experiment_id
        self.max_real_fit_debits = max_real_fit_debits

    def accounting(self) -> AccountingSummary:
        return summarize(self.backend.list_events(self.experiment_id), self.experiment_id)

    def claim(
        self,
        *,
        execution_id: str,
        arm: str,
        contract_sha256: str,
        input_binding_sha256: str,
    ) -> ExecutionClaim:
        event = {
            "event_type": "RUN_STARTED",
            "experiment_id": self.experiment_id,
            "execution_id": execution_id,
            "arm": arm,
            "started_at": _utc_now(),
            "planned_real_fit_count": 1,
            # Debit is durable before fit.  It is not automatically reclaimed on
            # failure/interruption; only an explicit later human adjudication may
            # alter the contract, never this event.
            "real_fit_budget_debit": 1,
            "contract_sha256": contract_sha256,
            "input_binding_sha256": input_binding_sha256,
        }
        # Atomicity belongs to the adapter because it knows the existing registry
        # builder/lock discipline.  A non-atomic list-then-append is not sufficient.
        self.backend.claim_run_started(event, max_real_fit_debits=self.max_real_fit_debits)
        return ExecutionClaim(
            experiment_id=self.experiment_id,
            execution_id=execution_id,
            arm=arm,
            contract_sha256=contract_sha256,
            input_binding_sha256=input_binding_sha256,
        )

    def claim_no_fit(
        self,
        *,
        execution_id: str,
        arm: str,
        contract_sha256: str,
        input_binding_sha256: str,
    ) -> ExecutionClaim:
        """Durably claim a synthetic/no-label engineering execution with zero fit debit.

        This is deliberately separate from :meth:`claim`: a caller cannot turn a
        real-fit claim into a zero-debit claim by changing an integer argument.
        The backend still owns atomic duplicate detection and registry append.
        """

        event = {
            "event_type": "RUN_STARTED",
            "experiment_id": self.experiment_id,
            "execution_id": execution_id,
            "arm": arm,
            "started_at": _utc_now(),
            "execution_kind": NO_FIT_ENGINEERING_KIND,
            "planned_real_fit_count": 0,
            "real_fit_budget_debit": 0,
            "contract_sha256": contract_sha256,
            "input_binding_sha256": input_binding_sha256,
        }
        self.backend.claim_run_started(event, max_real_fit_debits=self.max_real_fit_debits)
        return ExecutionClaim(
            experiment_id=self.experiment_id,
            execution_id=execution_id,
            arm=arm,
            contract_sha256=contract_sha256,
            input_binding_sha256=input_binding_sha256,
            execution_kind=NO_FIT_ENGINEERING_KIND,
            real_fit_budget_debit=0,
        )

    def append_terminal(
        self,
        claim: ExecutionClaim,
        *,
        terminal_status: str,
        fit_call_entered: bool,
        real_fit_returned_count: int,
        error_type: str | None = None,
    ) -> None:
        if real_fit_returned_count not in (0, 1):
            raise ValueError("real_fit_returned_count must be 0 or 1")
        event = {
            "event_type": "TERMINAL",
            "experiment_id": claim.experiment_id,
            "execution_id": claim.execution_id,
            "arm": claim.arm,
            "finished_at": _utc_now(),
            "terminal_status": terminal_status,
            "fit_call_entered": bool(fit_call_entered),
            "real_fit_returned_count": int(real_fit_returned_count),
            "execution_kind": claim.execution_kind,
            "real_fit_budget_debit": claim.real_fit_budget_debit,
            "contract_sha256": claim.contract_sha256,
            "input_binding_sha256": claim.input_binding_sha256,
        }
        if error_type:
            event["error_type"] = error_type
        if claim.experiment_id != self.experiment_id:
            raise TerminalizationRejected("claim experiment_id does not match guard")
        if not claim.execution_id or not claim.arm:
            raise TerminalizationRejected("claim identity is incomplete")
        if claim.execution_kind == NO_FIT_ENGINEERING_KIND:
            if claim.real_fit_budget_debit != 0 or fit_call_entered or real_fit_returned_count != 0:
                raise TerminalizationRejected("no-fit claim cannot report fit activity")
        elif claim.execution_kind == REAL_FIT_EXECUTION_KIND:
            if claim.real_fit_budget_debit != 1:
                raise TerminalizationRejected("real-fit claim debit is invalid")
        else:
            raise TerminalizationRejected("claim execution_kind is unsupported")
        self.backend.terminalize(claim, event)

    def append_no_fit_terminal(
        self,
        claim: ExecutionClaim,
        *,
        succeeded: bool,
        error_type: str | None = None,
    ) -> None:
        if claim.execution_kind != NO_FIT_ENGINEERING_KIND:
            raise TerminalizationRejected("append_no_fit_terminal requires a no-fit claim")
        self.append_terminal(
            claim,
            terminal_status="ENGINEERING_CANARY_ONLY" if succeeded else "CANNOT_CONFIRM_ENGINEERING_CANARY",
            fit_call_entered=False,
            real_fit_returned_count=0,
            error_type=error_type,
        )

    def execute_once(
        self,
        *,
        execution_id: str,
        arm: str,
        contract_sha256: str,
        input_binding_sha256: str,
        fit_callable: Callable[[], T],
    ) -> T:
        """Claim one budget debit then invoke exactly one supplied callable.

        All input/parity/gate prechecks must happen before calling this method.
        If the process is killed after RUN_STARTED but before TERMINAL, the next
        invocation sees a dangling start, counts its debit, and refuses re-entry.
        """
        claim = self.claim(
            execution_id=execution_id,
            arm=arm,
            contract_sha256=contract_sha256,
            input_binding_sha256=input_binding_sha256,
        )
        try:
            result = fit_callable()
        except BaseException as exc:
            # Entering fit_callable is conservatively one attempted fit.  If the
            # terminal append itself fails, RUN_STARTED remains durable and blocks
            # all automatic retry.
            self.append_terminal(
                claim,
                terminal_status="FAILED_DURING_FIT_CALL",
                fit_call_entered=True,
                real_fit_returned_count=0,
                error_type=type(exc).__name__,
            )
            raise
        self.append_terminal(
            claim,
            terminal_status="COMPLETED",
            fit_call_entered=True,
            real_fit_returned_count=1,
        )
        return result
