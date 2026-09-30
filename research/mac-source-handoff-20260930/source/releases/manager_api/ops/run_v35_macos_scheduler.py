"""Minute-level macOS scheduler entry for the fixed V3.5 workload slots.

The LaunchAgent invokes this entry repeatedly. It only dispatches when the
current Shanghai ``HHMM`` is one of ``ops.run_scheduled_slot.ALL_SLOTS``; the
existing execution ledger provides cross-invocation idempotency. Test/canary
overrides remain constrained to the same fixed slot allowlist.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from infrastructure.scheduling.executor_registry import STAGE_BY_SLOT, WorkloadExecutionError
from infrastructure.http_transport import build_proxy_environment
from ops.daily_materialize import resolve_selector_panel
from ops.materialize_stage_acquisition_universe import (
    materialize_stage_acquisition_universe,
)
from ops.run_scheduled_slot import (
    ALL_SLOTS,
    SHANGHAI,
    ZERO_EXIT_STATUSES,
    compute_dates,
    run_scheduled_slot,
)
from contracts.trading_calendar import (
    TradingDayState,
    load_market_calendar,
    resolve_market_states,
)
from stage_center.consumer import StageSelectionConsumer

RESULT_SCHEMA = "v3_5.macos_scheduler_result.v1"
CATCHUP_HOURLY_SLOTS = tuple(f"{hour:02d}00" for hour in range(7, 24))
# Research-panel A/H lanes are fixed canonical producer slots.  They receive
# the same fairness treatment as hourly work, while the dependent 17:30
# evidence node remains in ordered post-close catch-up below.
CATCHUP_EXACT_PRIORITY_SLOTS = frozenset(CATCHUP_HOURLY_SLOTS) | frozenset({"1700", "1720"})
# Fixed non-hourly owners must be recoverable after a five-minute launchd
# heartbeat without being confused with the neighbouring hourly workload.
# Morning stage/pre-stage slots are listed explicitly because a retryable
# 09:01 receipt must not monopolize the dispatcher after launchd wakes late.
# The post-close owners remain in ``POST_CLOSE_CATCHUP_SLOTS`` so their
# dependency ordering is preserved by the dedicated branch below.
CATCHUP_FIXED_SLOTS = (
    "0830",
    "0840",
    "0901",
    "0915",
    "0925",
    "0935",
    "0940",
    "0945",
    "1030",
    "1130",
    "1730",
    "2001",
    "2115",
)
POST_CLOSE_CATCHUP_SLOTS = (
    "1500", "1555", "1605", "1608", "1700", "1710", "1720", "1730", "1800", "2030", "2040",
    "2050", "2105", "2108", "2110", "2115", "2140",
)
# The post-close nodes are recovered in dependency order before hourly research.
# 21:40 remains the final same-day materializer slot in this ordered sequence.
CRITICAL_SAME_DAY_SLOT = "2140"
CRITICAL_SAME_DAY_CATCHUP_END_HOUR = 23
DEFAULT_CATCHUP_WINDOW_MINUTES = 59
FAILED_SLOT_RETRY_BACKOFF_SECONDS = 300
MAX_FAILED_SLOT_ATTEMPTS = 3
RETRYABLE_FAILURE_CLASSES = frozenset(
    {
        "UPSTREAM_NOT_READY",
        "NETWORK",
        "EXTERNAL_SOURCE",
        "RESEARCH_SOURCE_REFRESH_RETRY_REQUIRED",
        "INTRADAY_NO_REQUEST",
    }
)
TERMINAL_FAILURE_CLASSES = frozenset(
    {"CONTRACT", "INVALID_INPUT", "SAFETY", "NON_TRADING_DAY", "NOT_DUE"}
)
SHARED_STAGE_BY_SLOT = {
    slot: stage_id for slot, stage_id in STAGE_BY_SLOT.items() if slot != "0925"
}
STAGE_INPUT_SLOTS = frozenset(STAGE_BY_SLOT)
STAGE_WORKLOAD_IDS = frozenset(
    {"stage_workbench", "fupan_close_materials", "fupan_review_start"}
)


def _fixed_slot_catchup_allowed(slot: str, moment: datetime) -> bool:
    """Apply slot-specific catch-up deadlines to non-hourly owners.

    The 09:15 HK auction capture is an opening-window input.  A late wake can
    recover it only while the capture window is still open; after 09:19:59 a
    retry of that slot would be a false representation of the live auction.
    Other fixed slots retain the caller's normal bounded catch-up window.
    """

    if slot == "1130":
        return moment.hour == 11 and moment.minute <= 38
    if slot != "0915":
        return True
    return moment.hour == 9 and moment.minute <= 19


def _intraday_attempt_outcome(observed: list[dict[str, Any]]) -> str | None:
    """Classify an intraday failure before release/upstream retry resets.

    A retry is safe only when the child explicitly persisted that no provider
    request was made.  A successful/ALREADY_EXISTS child is already complete;
    it must not block a retry of a failed sibling workload.  Missing, malformed,
    or contradictory attempt metadata remains unknown and blocks the scheduler,
    even if an unrelated release or upstream pointer changed.
    """

    aggregate_no_request = False
    saw_child = False
    saw_child_no_request = False
    saw_child_success = False
    for payload in observed:
        aggregate_failure = str(payload.get("failure_class") or "").strip().upper()
        if aggregate_failure == "INTRADAY_NO_REQUEST":
            aggregate_no_request = True
        elif aggregate_failure.startswith("INTRADAY_"):
            return "BLOCK"
        results = payload.get("workload_results")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict) or result.get("workload_id") != "v4_intraday_research":
                continue
            saw_child = True
            state = str(result.get("attempt_state") or "").strip().upper()
            failure = str(result.get("failure_class") or "").strip().upper()
            status = str(result.get("status") or "").strip().upper()
            if status in {"SUCCEEDED", "ALREADY_EXISTS"}:
                # A completed child may have made a provider request.  Its
                # request-boundary state is therefore not evidence that the
                # failed Stage sibling must be blocked.  A terminal success
                # carrying failure/unknown/in-flight metadata is contradictory
                # and remains fail-closed.
                if (
                    failure
                    or result.get("error_code")
                    or state not in {"", "SUCCEEDED", "REQUEST_ATTEMPTED"}
                ):
                    return "BLOCK"
                saw_child_success = True
                continue
            if (
                state == "FAILED_NO_REQUEST"
                and failure == "INTRADAY_NO_REQUEST"
                and status in {"", "FAILED"}
            ):
                saw_child_no_request = True
                continue
            # A child result is the durable request-boundary fact.  Do not let
            # an aggregate INTRADAY_NO_REQUEST label override a sent,
            # in-flight, malformed, or otherwise inconsistent child result.
            return "BLOCK"
    if saw_child:
        if saw_child_success:
            # Do not let a successful intraday child suppress retry of a
            # retryable Stage sibling; the execution ledger retains the
            # completed child and prevents it from being run again.
            return "BLOCK" if aggregate_no_request or saw_child_no_request else None
        return "RETRY" if saw_child_no_request else "BLOCK"
    # An aggregate label without a matching explicit child state is not
    # sufficient evidence for a safe provider retry.
    return "BLOCK" if aggregate_no_request else None


def _is_non_trading_day(business_date: str) -> bool:
    """Return whether both stage markets are closed for the exact date.

    Stage candidate input is a prerequisite only on an eligible market day.
    The dispatcher remains the authority for the terminal result; this guard
    only prevents a non-trading date from invoking the prerequisite first.
    """

    states = resolve_market_states(load_market_calendar(), business_date)
    return all(
        states[key] is TradingDayState.NON_TRADING_DAY
        for key in ("a_share", "hk_connect")
    )


def current_slot(now: datetime | None = None) -> tuple[str, str]:
    moment = now or datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    else:
        moment = moment.astimezone(SHANGHAI)
    return moment.strftime("%Y%m%d"), moment.strftime("%H%M")


def _slot_blocks_retry(
    ledger_root: Path,
    business_date: str,
    slot: str,
    *,
    moment: datetime,
    retry_backoff_seconds: int = FAILED_SLOT_RETRY_BACKOFF_SECONDS,
    max_failed_attempts: int = MAX_FAILED_SLOT_ATTEMPTS,
    upstream_fingerprint: str | None = None,
    release_id: str | None = None,
) -> bool:
    claim = (
        ledger_root
        / "claims"
        / "live"
        / business_date
        / slot
        / "dispatch.claim.json"
    )
    if claim.is_file():
        return True
    receipts = ledger_root / "receipts" / "live" / business_date / slot
    if not receipts.is_dir():
        return False
    observed: list[dict[str, Any]] = []
    for path in receipts.glob("*.dispatch-receipt.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return True
        if not isinstance(payload, dict):
            return True
        observed.append(payload)
    if not observed:
        return False
    if any(str(payload.get("status") or "") != "FAILED" for payload in observed):
        return True
    failure_classes = {str(payload.get("failure_class") or "").upper() for payload in observed}
    if failure_classes & TERMINAL_FAILURE_CLASSES:
        return True
    intraday_outcome = _intraday_attempt_outcome(observed)
    if intraday_outcome == "BLOCK":
        return True
    # A new exact upstream pointer or release invalidates the old retry cap.
    # This is the key distinction from the former permanent three-attempt
    # block: a repaired selector/current or a new immutable release gets a
    # fresh attempt without changing the historical receipts.
    if upstream_fingerprint is not None and any(
        str(payload.get("upstream_fingerprint") or "") != upstream_fingerprint
        for payload in observed
    ):
        return False
    if release_id is not None and any(
        str(payload.get("release_id") or "") != release_id
        for payload in observed
    ):
        return False
    legacy_receipts = [payload for payload in observed if not str(payload.get("failure_class") or "").strip()]
    typed_classes = failure_classes - {""}
    if typed_classes and not typed_classes.issubset(RETRYABLE_FAILURE_CLASSES):
        # Unknown failure types stay fail-closed until the executor classifies
        # them; they must not be retried blindly by the minute launcher.
        return True
    if legacy_receipts and len(legacy_receipts) >= max(0, int(max_failed_attempts)):
        # Receipts emitted before typed failure metadata existed retain the
        # historical bounded-attempt contract.  A current release or exact
        # upstream fingerprint was handled above and intentionally resets this
        # compatibility cap without rewriting the old receipts.
        return True
    # Retryable upstream/network failures are governed by time backoff, not a
    # permanent attempt ceiling.  ``max_failed_attempts`` remains accepted for
    # compatibility with older callers but is intentionally not used to turn
    # a recoverable input outage into a terminal receipt.
    finished: list[datetime] = []
    retry_after: list[datetime] = []
    for payload in observed:
        retry_value = str(payload.get("retry_after") or "")
        if retry_value:
            try:
                parsed_retry = datetime.fromisoformat(retry_value.replace("Z", "+00:00"))
            except ValueError:
                return True
            if parsed_retry.tzinfo is None or parsed_retry.utcoffset() is None:
                return True
            retry_after.append(parsed_retry.astimezone(UTC))
            continue
        raw = str(payload.get("finished_at") or "")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return True
        finished.append(parsed.astimezone(UTC))
    current = moment.astimezone(UTC)
    if retry_after:
        return current < max(retry_after)
    return current - max(finished) < timedelta(
        seconds=max(0, int(retry_backoff_seconds))
    )


def resolve_due_slot(
    *,
    ledger_root: Path,
    now: datetime | None = None,
    catchup_window_minutes: int = DEFAULT_CATCHUP_WINDOW_MINUTES,
    upstream_fingerprint: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an exact slot or the earliest bounded unclaimed catch-up.

    Only the most recent hour and only a bounded sub-hour window are eligible.
    Claims and successful receipts block duplicates. Failed hourly receipts are
    eligible for a bounded, backoff-controlled retry so a temporary network
    outage can recover after wake. Special stage and pool slots are never
    synthesized.
    """
    moment = now or datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    else:
        moment = moment.astimezone(SHANGHAI)
    business_date = moment.strftime("%Y%m%d")
    observed_slot = moment.strftime("%H%M")
    exact = {
        "business_date": business_date,
        "observed_slot": observed_slot,
        "slot": observed_slot,
        "catchup": False,
        "lag_minutes": 0,
    }
    # Do not let an older post-close retry monopolize the dispatcher at an
    # exact hourly wake.  The current hourly workload is independent of the
    # prior close node and must get one attempt; the ordered post-close list
    # remains eligible on the next five-minute wake.  This prevents a failed
    # 15:00 receipt from starving 16:00/17:00 research indefinitely while
    # preserving dependency order for the non-hourly 17:30 evidence slot.
    if observed_slot in CATCHUP_EXACT_PRIORITY_SLOTS and not _slot_blocks_retry(
        Path(ledger_root),
        business_date,
        observed_slot,
        moment=moment,
        upstream_fingerprint=upstream_fingerprint,
        release_id=release_id,
    ):
        return exact
    if 15 <= int(observed_slot[:2]) <= CRITICAL_SAME_DAY_CATCHUP_END_HOUR:
        # v16 fairness: among already-due slots, give unattempted owners their
        # first chance before retrying failed siblings. Stable order preserves
        # the existing post-close sequence within each group; gates stay below.
        def attempted(slot: str) -> bool:
            receipts = Path(ledger_root) / "receipts" / "live" / business_date / slot
            return receipts.is_dir() and any(receipts.glob("*.dispatch-receipt.json"))

        for slot in sorted(POST_CLOSE_CATCHUP_SLOTS, key=attempted):
            if observed_slot < slot:
                continue
            if _slot_blocks_retry(
                Path(ledger_root),
                business_date,
                slot,
                moment=moment,
                upstream_fingerprint=upstream_fingerprint,
                release_id=release_id,
            ):
                continue
            scheduled = moment.replace(
                hour=int(slot[:2]), minute=int(slot[2:]), second=0, microsecond=0
            )
            if slot == observed_slot:
                return exact
            return {
                "business_date": business_date,
                "observed_slot": observed_slot,
                "slot": slot,
                "catchup": True,
                "lag_minutes": int((moment - scheduled).total_seconds() // 60),
            }
    if observed_slot in ALL_SLOTS:
        if _slot_blocks_retry(
            Path(ledger_root),
            business_date,
            observed_slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            return {
                **exact,
                "slot": None,
                "status": "RETRY_BACKOFF",
                "retry_blocked": True,
            }
        return exact
    window = max(0, int(catchup_window_minutes))
    for slot in reversed(CATCHUP_FIXED_SLOTS):
        if not _fixed_slot_catchup_allowed(slot, moment):
            continue
        scheduled = moment.replace(
            hour=int(slot[:2]),
            minute=int(slot[2:]),
            second=0,
            microsecond=0,
        )
        lag_minutes = int((moment - scheduled).total_seconds() // 60)
        if lag_minutes < 0 or lag_minutes > window:
            continue
        if _slot_blocks_retry(
            Path(ledger_root),
            business_date,
            slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            continue
        return {
            "business_date": business_date,
            "observed_slot": observed_slot,
            "slot": slot,
            "catchup": True,
            "lag_minutes": lag_minutes,
        }
    for slot in reversed(CATCHUP_HOURLY_SLOTS):
        scheduled = moment.replace(
            hour=int(slot[:2]),
            minute=0,
            second=0,
            microsecond=0,
        )
        lag_minutes = int((moment - scheduled).total_seconds() // 60)
        if lag_minutes < 0 or lag_minutes > window:
            continue
        if _slot_blocks_retry(
            Path(ledger_root),
            business_date,
            slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            continue
        return {
            "business_date": business_date,
            "observed_slot": observed_slot,
            "slot": slot,
            "catchup": True,
            "lag_minutes": lag_minutes,
        }
    return exact


def _with_runtime_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize scheduler result metadata without inventing success evidence."""

    result = dict(payload)
    for field in ("failure_class", "retry_after"):
        value = result.get(field)
        result[field] = value if value not in (None, "") else None
    for field, env_name in (
        ("release_id", "V35_RELEASE_ID"),
        ("upstream_fingerprint", "V35_UPSTREAM_FINGERPRINT"),
    ):
        value = result.get(field) or os.environ.get(env_name)
        result[field] = value if value not in (None, "") else None
    try:
        result["attempt"] = max(0, int(result.get("attempt") or 0))
    except (TypeError, ValueError):
        result["attempt"] = 0
    return result


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(_with_runtime_metadata(payload), ensure_ascii=False, sort_keys=True))


def _last_json_object(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("shared acquisition did not emit a JSON object")


def run_shared_stage_acquisition(
    *,
    business_date: str,
    slot: str,
    data_root: Path,
    shared_data_root: Path,
    shared_package_root: Path,
    selector_data_root: Path,
    timeout_seconds: float,
    process_runner=subprocess.run,
    universe_materializer=materialize_stage_acquisition_universe,
) -> dict[str, Any]:
    """Acquire the fixed shared stage bundle before V3.5 materialization."""
    stage_id = SHARED_STAGE_BY_SLOT.get(slot)
    if stage_id is None:
        return {"status": "NOT_STAGE_SLOT"}
    universe = universe_materializer(data_root, business_date)
    artifact = universe.get("artifact") if isinstance(universe, dict) else None
    if (
        not isinstance(universe, dict)
        or universe.get("status") != "READY"
        or not isinstance(universe.get("row_count"), int)
        or universe["row_count"] <= 0
        or not isinstance(artifact, dict)
    ):
        raise RuntimeError("STAGE_ACQUISITION_UNIVERSE_NOT_READY")
    unsafe_universe = [
        key
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
        if artifact.get(key) is not False
    ]
    if unsafe_universe:
        raise RuntimeError(
            "STAGE_ACQUISITION_UNIVERSE_UNSAFE:" + ",".join(unsafe_universe)
        )
    bundled_stage_root = (
        Path(__file__).resolve().parents[1] / "upstreams" / "v3_shared_data"
    )
    if not (bundled_stage_root / "scripts" / "run_scheduled_stage_bundle.py").is_file():
        raise RuntimeError(
            "BUNDLED_STAGE_ACQUISITION_MISSING:" + str(bundled_stage_root)
        )
    panel = resolve_selector_panel(selector_data_root, business_date)
    pointer = selector_data_root / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
    env = build_proxy_environment(os.environ.copy())
    env.update(
        {
            "V3_SHARED_DATA_STORE_ROOT": str(shared_data_root),
            "V35_DATA_ROOT": str(data_root),
            "V3_SHARED_SELECTOR_READY_PANEL_POINTER": str(pointer),
            "V3_SHARED_SELECTOR_READY_PANEL": str(panel),
            "V3_SHARED_FUTU_PYTHON": sys.executable,
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
        }
    )
    completed = process_runner(
        [
            sys.executable,
            "-m",
            "scripts.run_scheduled_stage_bundle",
            "--trade-date",
            business_date,
            "--stage-id",
            stage_id,
        ],
        cwd=bundled_stage_root,
        env=env,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    payload = _last_json_object(completed.stdout)
    if completed.returncode != 0 or not payload.get("ok") or payload.get("status") != "READY":
        detail = payload.get("error") or completed.stderr[-1200:] or payload.get("status")
        raise RuntimeError(f"SHARED_STAGE_ACQUISITION_FAILED:{stage_id}:{detail}")
    unsafe = [
        key
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
        if payload.get(key) is not False
    ]
    if unsafe:
        raise RuntimeError("SHARED_STAGE_ACQUISITION_UNSAFE:" + ",".join(unsafe))
    return {
        "status": "READY",
        "stage_id": stage_id,
        "receipt_path": payload.get("receipt_path"),
        "stage_acquisition_universe": {
            "status": universe["status"],
            "row_count": universe["row_count"],
            "run_id": universe.get("run_id"),
            "current_path": str(universe.get("current_path") or ""),
            "idempotent": bool(universe.get("idempotent")),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def ensure_stage_candidate_input(
    *,
    data_root: Path,
    business_date: str,
    universe_materializer=None,
) -> dict[str, Any]:
    """Idempotently ensure the stage consumer has a verified candidate input.

    The shared Stage Center remains the sole raw/selection producer.  This
    small prerequisite is owned by the V3.5 scheduler so consume-only mode
    cannot leave a stage slot without the exact-date acquisition universe.
    """

    materializer = universe_materializer or materialize_stage_acquisition_universe
    universe = materializer(data_root, business_date)
    artifact = universe.get("artifact") if isinstance(universe, dict) else None
    if (
        not isinstance(universe, dict)
        or universe.get("status") != "READY"
        or not isinstance(universe.get("row_count"), int)
        or isinstance(universe.get("row_count"), bool)
        or universe["row_count"] <= 0
        or not isinstance(artifact, dict)
    ):
        raise RuntimeError("STAGE_ACQUISITION_UNIVERSE_NOT_READY")
    unsafe_universe = [
        key
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
        if artifact.get(key) is not False
    ]
    if unsafe_universe:
        raise RuntimeError(
            "STAGE_ACQUISITION_UNIVERSE_UNSAFE:" + ",".join(unsafe_universe)
        )
    return {
        "status": universe["status"],
        "row_count": universe["row_count"],
        "run_id": universe.get("run_id"),
        "current_path": str(
            Path(universe.get("current_path") or "").expanduser().resolve()
        ),
        "artifact_sha256": universe.get("artifact_sha256"),
        "manifest_sha256": universe.get("manifest_sha256"),
        "receipt_sha256": universe.get("receipt_sha256"),
        "idempotent": bool(universe.get("idempotent")),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def consume_shared_stage_selection(
    *,
    business_date: str,
    slot: str,
    selection_root: Path,
    stage_acquisition_universe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the shared selection consumed by this scheduler.

    An explicit ``V35_STAGE_CENTER_SELECTION_ROOT`` changes this boundary to
    read-only consumption.  In particular, this helper deliberately does not
    invoke the bundled raw/selection producer or publish an artifact.  The
    scheduler owns only the exact-date candidate-input prerequisite and
    reports its verified evidence alongside the consume-only envelope.
    """
    stage_id = STAGE_BY_SLOT.get(slot)
    if stage_id is None:
        return {"status": "NOT_STAGE_SLOT", "write_performed": False}
    result = {
        "status": "CONSUME_ONLY",
        "stage_id": stage_id,
        "business_date": business_date,
        "selection_root": str(selection_root.expanduser().resolve()),
        "direct_acquisition_called": False,
        "producer_called": False,
        "write_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if stage_acquisition_universe is not None:
        result["stage_acquisition_universe"] = dict(stage_acquisition_universe)
    selection = StageSelectionConsumer(selection_root).get(business_date, stage_id)
    result.update(
        {
            "selection_status": selection.get("status", "CANNOT_CONFIRM"),
            "selection_artifact_id": selection.get("artifact_id"),
            "selection_run_id": selection.get("run_id"),
            "selection_markets": selection.get("markets", {}),
            "cannot_confirm": list(selection.get("cannot_confirm") or []),
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the due fixed V3.5 macOS slot")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--ledger-root", required=True, type=Path)
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--hk-universe-root", type=Path)
    parser.add_argument("--shared-package-root", type=Path)
    parser.add_argument("--selector-data-root", type=Path)
    parser.add_argument("--preselection-input-root", type=Path)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument(
        "--hk-0-2-python",
        type=Path,
        default=(
            Path(os.environ["V35_HK_0_2_PYTHON"])
            if os.environ.get("V35_HK_0_2_PYTHON")
            else None
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--slot", choices=ALL_SLOTS, help="fixed-slot canary override")
    parser.add_argument("--date", help="YYYYMMDD canary date; requires --slot")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--release-id", default=os.environ.get("V35_RELEASE_ID", ""))
    parser.add_argument("--upstream-fingerprint", default=os.environ.get("V35_UPSTREAM_FINGERPRINT", ""))
    args = parser.parse_args(argv)
    if args.date and not args.slot:
        parser.error("--date requires --slot")

    # launchd does not guarantee proxy variable casing for child processes.
    # Install the bounded research transport environment at this scheduler
    # boundary so hourly peripheral executors inherit the same proxy-first,
    # loopback-direct policy as the shared-stage child.
    os.environ.update(build_proxy_environment(os.environ.copy()))

    detected_date, detected_slot = current_slot()
    if args.slot:
        due = {
            "business_date": args.date or detected_date,
            "observed_slot": detected_slot,
            "slot": args.slot,
            "catchup": False,
            "lag_minutes": 0,
        }
    else:
        due = resolve_due_slot(
            ledger_root=args.ledger_root,
            release_id=args.release_id or None,
            upstream_fingerprint=args.upstream_fingerprint or None,
        )
    if due.get("retry_blocked"):
        _emit(
            {
                "schema_version": RESULT_SCHEMA,
                "status": "RETRY_BACKOFF",
                "business_date": due["business_date"],
                "observed_slot": due["observed_slot"],
                "slot": None,
                "catchup": {"applied": False, "lag_minutes": 0},
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 0
    slot = str(due["slot"])
    business_date = args.date or str(due["business_date"])
    if slot not in ALL_SLOTS:
        _emit(
            {
                "schema_version": RESULT_SCHEMA,
                "status": "NO_DUE_SLOT",
                "business_date": business_date,
                "observed_slot": due["observed_slot"],
                "catchup": {
                    "applied": False,
                    "lag_minutes": 0,
                },
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 0

    shared_acquisition: dict[str, Any] = {
        "status": "NOT_STAGE_WORKLOAD_SELECTED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    stage_gate_state: dict[str, Any] = {
        "attempted": False,
        "result": None,
        "failure": None,
    }

    def stage_workload_guard(workload, request, _decision):
        """Lazily gate only an actually selected Stage workload.

        The dispatcher remains responsible for workload selection and claims.
        This callback only memoizes the existing Stage prerequisite so a mixed
        dispatch cannot run it once per Stage workload or before an independent
        intraday workload.
        """

        nonlocal shared_acquisition
        workload_id = str(getattr(workload, "workload_id", ""))
        if workload_id not in STAGE_WORKLOAD_IDS:
            return None
        if stage_gate_state["attempted"]:
            if stage_gate_state["failure"] is not None:
                failure = dict(stage_gate_state["failure"])
                failure["workload_id"] = workload_id
                raise WorkloadExecutionError(failure)
            return stage_gate_state["result"]

        stage_gate_state["attempted"] = True
        if _is_non_trading_day(request.business_date):
            gate = {
                "status": "SKIPPED_NON_TRADING_DAY",
                "stage_workload_id": workload_id,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            stage_gate_state["result"] = gate
            shared_acquisition = gate
            return gate

        try:
            if args.stage_selection_root is None:
                raise ValueError("STAGE_SELECTION_ROOT_MISSING")
            stage_acquisition_universe = ensure_stage_candidate_input(
                data_root=args.data_root,
                business_date=request.business_date,
            )
            consumed = consume_shared_stage_selection(
                business_date=request.business_date,
                slot=request.slot,
                selection_root=args.stage_selection_root,
                stage_acquisition_universe=stage_acquisition_universe,
            )
            selection_status = str(consumed.get("selection_status") or "CANNOT_CONFIRM").upper()
            if selection_status not in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"}:
                raise RuntimeError("STAGE_SELECTION_NOT_READY")
            unsafe = [
                field
                for payload in (stage_acquisition_universe, consumed)
                for field in ("production_allowed", "buy_gate_updated", "orders_sent")
                if payload.get(field) is not False
            ]
            if unsafe:
                raise RuntimeError("STAGE_SELECTION_UNSAFE")
            gate = {
                "status": "READY",
                "stage_workload_id": workload_id,
                "selection_status": selection_status,
                "stage_acquisition_universe": stage_acquisition_universe,
                "selection": consumed,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        except Exception as error:
            failure = {
                "status": "FAILED",
                "workload_id": workload_id,
                "modules": ["stage_gate"],
                "exit_code": 1,
                "reason": "STAGE_PRECONDITION_NOT_READY",
                "error_code": type(error).__name__.upper(),
                "failure_class": "UPSTREAM_NOT_READY",
                "attempt_state": "STAGE_GATE_FAILED",
                "cannot_confirm": ["STAGE_PRECONDITION_NOT_READY"],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            stage_gate_state["failure"] = failure
            shared_acquisition = failure
            raise WorkloadExecutionError(failure) from error

        stage_gate_state["result"] = gate
        shared_acquisition = gate
        return gate

    try:
        dates = compute_dates(business_date=business_date, slot=slot)
        result = run_scheduled_slot(
            data_root=args.data_root,
            slot=slot,
            business_date=dates["business_date"],
            scheduled_date=dates["scheduled_date"],
            target_date=dates["target_date"],
            ledger_root=args.ledger_root,
            shared_data_root=args.shared_data_root,
            hk_universe_root=args.hk_universe_root,
            shared_package_root=args.shared_package_root,
            hk_0_2_python_executable=args.hk_0_2_python,
            selector_data_root=args.selector_data_root,
            preselection_input_root=args.preselection_input_root,
            stage_selection_root=args.stage_selection_root,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
            workload_guard=None if args.dry_run else stage_workload_guard,
        )
    except Exception as error:  # launchd boundary: always emit fail-closed JSON
        _emit(
            {
                "schema_version": RESULT_SCHEMA,
                "status": "FAILED",
                "slot": slot,
                "business_date": business_date,
                "reason": f"{type(error).__name__}: {error}",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 1

    _emit(
        {
            **result,
            "macos_scheduler_schema_version": RESULT_SCHEMA,
            "shared_acquisition": shared_acquisition,
            "observed_slot": due["observed_slot"],
            "catchup": {
                "applied": bool(due["catchup"]),
                "lag_minutes": int(due["lag_minutes"]),
                "scheduled_slot": slot,
            },
        }
    )
    return 0 if result["status"] in ZERO_EXIT_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
