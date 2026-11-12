"""Shared executor-registry helpers.

This module contains implementation helpers used by the facade's stable seam.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from infrastructure.research_peripheral_store import ResearchPeripheralStore

_PERIPHERAL_SOURCES = frozenset({"external_finance", "ai_news"})
_PERIPHERAL_STATUSES = frozenset({"READY", "READY_EMPTY", "CANNOT_CONFIRM"})
_TIMEOUT_EXIT_CODE = 124


def _audited_peripheral_degradation(
    result: dict[str, Any],
    *,
    data_root: Path,
    trade_date: str,
) -> dict[str, Any] | None:
    """Accept only a code-2 materializer summary backed by verified artifacts."""
    if result.get("status") != "FAILED" or result.get("exit_code") != 2:
        return None
    try:
        summary = result.get("_authoritative_payload")
        if not isinstance(summary, dict):
            summary = json.loads(str(result.get("stdout") or ""))
        if set(summary) != {"trade_date", "source", "outputs"}:
            return None
        if summary["trade_date"] != trade_date or summary["source"] != "both":
            return None
        outputs = summary["outputs"]
        if not isinstance(outputs, list) or len(outputs) != len(_PERIPHERAL_SOURCES):
            return None
        store = ResearchPeripheralStore(data_root)
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for output in outputs:
            if set(output) != {"source", "status", "item_count", "payload_path", "receipt_path"}:
                return None
            source = output["source"]
            if source not in _PERIPHERAL_SOURCES or source in seen:
                return None
            status = output["status"]
            if status not in _PERIPHERAL_STATUSES or type(output["item_count"]) is not int:
                return None
            expected_payload = f"research/peripherals/{trade_date}/{source}.json"
            expected_receipt = f"receipts/research/peripherals/{trade_date}/{source}.json"
            if output["payload_path"] != expected_payload or output["receipt_path"] != expected_receipt:
                return None
            payload = store.read_exact(trade_date, source)
            if payload is None or payload["status"] != status or payload["item_count"] != output["item_count"]:
                return None
            if any(payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
                return None
            gaps = payload.get("cannot_confirm")
            if not isinstance(gaps, list) or any(not isinstance(gap, str) for gap in gaps):
                return None
            seen.add(source)
            sources.append(
                {
                    "source": source,
                    "status": status,
                    "item_count": output["item_count"],
                    "cannot_confirm": gaps,
                }
            )
        if seen != _PERIPHERAL_SOURCES:
            return None
        gaps = sorted({gap for source in sources for gap in source["cannot_confirm"]})
        if not gaps:
            return None
        return {
            "module": "ops.materialize_research_peripherals",
            "exit_code": 2,
            "gaps": gaps,
            "sources": sorted(sources, key=lambda source: source["source"]),
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _audited_peripheral_timeout_reuse(
    *,
    data_root: Path,
    trade_date: str,
) -> dict[str, Any] | None:
    """Accept a timed-out refresh only when both exact-date stores verify.

    A refresh timeout must not erase already-published same-day evidence.  The
    store reader verifies the manifest, payload schema, date/source identity,
    and safety flags before this helper returns a degradation record.  Missing
    or unsafe evidence still fails closed in ``_hourly_research``.
    """
    try:
        store = ResearchPeripheralStore(data_root)
        sources: list[dict[str, Any]] = []
        source_fetched_at: dict[str, str] = {}
        gaps = {"PERIPHERAL_REFRESH_TIMEOUT_REUSED_EXACT_DATE"}
        for source in sorted(_PERIPHERAL_SOURCES):
            payload = store.read_exact(trade_date, source)
            if payload is None or payload.get("status") not in _PERIPHERAL_STATUSES:
                return None
            if any(
                payload.get(flag) is not False
                for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
            ):
                return None
            fetched_at = payload.get("fetched_at")
            cannot_confirm = payload.get("cannot_confirm")
            if (
                not isinstance(fetched_at, str)
                or not fetched_at
                or not isinstance(cannot_confirm, list)
                or any(not isinstance(gap, str) for gap in cannot_confirm)
            ):
                return None
            source_fetched_at[source] = fetched_at
            gaps.update(cannot_confirm)
            sources.append(
                {
                    "source": source,
                    "status": payload["status"],
                    "item_count": payload["item_count"],
                    "cannot_confirm": cannot_confirm,
                }
            )
        return {
            "module": "ops.materialize_research_peripherals",
            "exit_code": _TIMEOUT_EXIT_CODE,
            "reason": "PERIPHERAL_REFRESH_TIMEOUT_REUSED_EXACT_DATE",
            "gaps": sorted(gaps),
            "sources": sources,
            "source_fetched_at": source_fetched_at,
        }
    except (KeyError, OSError, TypeError, ValueError):
        return None


def _bounded(value: str | None, limit: int) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[truncated, total {len(text)} chars]"


def _collector_not_materialized_result(
    collected: dict[str, Any],
    *,
    workload_id: str,
    modules: list[str],
    collector_payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert an empty collector response into a typed upstream failure.

    ``ops.collect_hourly_research_input`` may complete its own bounded fetch
    with ``READY_EMPTY``.  That is evidence that the fetch ran, not evidence
    that a formal hourly research artifact can be published.  Keep the
    collector receipt in the child result while preventing the executor from
    invoking the archive runner or reporting a successful workload.
    """

    row_count = collector_payload.get("row_count")
    if (
        collector_payload.get("status") == "READY_WITH_RESEARCH_POOL"
        and type(row_count) is int
        and row_count > 0
    ):
        return None
    result = dict(collected)
    result.update(
        {
            "status": "NOT_MATERIALIZED",
            "workload_id": workload_id,
            "modules": modules,
            "failure_class": "UPSTREAM_NOT_READY",
            "reason": "HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED",
            "collector_status": str(collector_payload.get("status") or "CANNOT_CONFIRM"),
            "row_count": row_count if type(row_count) is int else 0,
            "hourly_artifact_status": "NOT_MATERIALIZED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    return result


def _default_runner(
    command: list[str],
    *,
    cwd: Path | None,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        shell=False,
        cwd=cwd,
        env=env,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
