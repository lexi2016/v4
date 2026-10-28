"""infrastructure.scheduling.executor_registry: degradation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __audited_peripheral_degradation_body(_v4_scope, /, result, *, data_root, trade_date):
    """Accept only a code-2 materializer summary backed by verified artifacts."""
    if result.get("status") != "FAILED" or result.get("exit_code") != 2:
        return None
    try:
        summary = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'str')(result.get("stdout") or ""))
        if _v4_global(_v4_scope, 'set')(summary) != {"trade_date", "source", "outputs"}:
            return None
        if summary["trade_date"] != trade_date or summary["source"] != "both":
            return None
        outputs = summary["outputs"]
        if not _v4_global(_v4_scope, 'isinstance')(outputs, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(outputs) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, '_PERIPHERAL_SOURCES')):
            return None
        store = _v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root)
        sources: list[dict[str, Any]] = []
        seen: set[str] = _v4_global(_v4_scope, 'set')()
        for output in outputs:
            if _v4_global(_v4_scope, 'set')(output) != {"source", "status", "item_count", "payload_path", "receipt_path"}:
                return None
            source = output["source"]
            if source not in _v4_global(_v4_scope, '_PERIPHERAL_SOURCES') or source in seen:
                return None
            status = output["status"]
            if status not in _v4_global(_v4_scope, '_PERIPHERAL_STATUSES') or _v4_global(_v4_scope, 'type')(output["item_count"]) is not _v4_global(_v4_scope, 'int'):
                return None
            expected_payload = f"research/peripherals/{trade_date}/{source}.json"
            expected_receipt = f"receipts/research/peripherals/{trade_date}/{source}.json"
            if output["payload_path"] != expected_payload or output["receipt_path"] != expected_receipt:
                return None
            payload = store.read_exact(trade_date, source)
            if payload is None or payload["status"] != status or payload["item_count"] != output["item_count"]:
                return None
            if _v4_global(_v4_scope, 'any')(payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
                return None
            gaps = payload.get("cannot_confirm")
            if not _v4_global(_v4_scope, 'isinstance')(gaps, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(gap, _v4_global(_v4_scope, 'str')) for gap in gaps):
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
        if seen != _v4_global(_v4_scope, '_PERIPHERAL_SOURCES'):
            return None
        gaps = _v4_global(_v4_scope, 'sorted')({gap for source in sources for gap in source["cannot_confirm"]})
        if not gaps:
            return None
        return {
            "module": "ops.materialize_research_peripherals",
            "exit_code": 2,
            "gaps": gaps,
            "sources": _v4_global(_v4_scope, 'sorted')(sources, key=lambda source: source["source"]),
        }
    except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'json').JSONDecodeError):
        return None


def __audited_peripheral_timeout_reuse_body(_v4_scope, /, *, data_root, trade_date):
    """Accept a timed-out refresh only when both exact-date stores verify.

    A refresh timeout must not erase already-published same-day evidence.  The
    store reader verifies the manifest, payload schema, date/source identity,
    and safety flags before this helper returns a degradation record.  Missing
    or unsafe evidence still fails closed in ``_hourly_research``.
    """
    try:
        store = _v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root)
        sources: list[dict[str, Any]] = []
        source_fetched_at: dict[str, str] = {}
        gaps = {"PERIPHERAL_REFRESH_TIMEOUT_REUSED_EXACT_DATE"}
        for source in _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, '_PERIPHERAL_SOURCES')):
            payload = store.read_exact(trade_date, source)
            if payload is None or payload.get("status") not in _v4_global(_v4_scope, '_PERIPHERAL_STATUSES'):
                return None
            if _v4_global(_v4_scope, 'any')(
                payload.get(flag) is not False
                for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
            ):
                return None
            fetched_at = payload.get("fetched_at")
            cannot_confirm = payload.get("cannot_confirm")
            if (
                not _v4_global(_v4_scope, 'isinstance')(fetched_at, _v4_global(_v4_scope, 'str'))
                or not fetched_at
                or not _v4_global(_v4_scope, 'isinstance')(cannot_confirm, _v4_global(_v4_scope, 'list'))
                or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(gap, _v4_global(_v4_scope, 'str')) for gap in cannot_confirm)
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
            "exit_code": _v4_global(_v4_scope, '_TIMEOUT_EXIT_CODE'),
            "reason": "PERIPHERAL_REFRESH_TIMEOUT_REUSED_EXACT_DATE",
            "gaps": _v4_global(_v4_scope, 'sorted')(gaps),
            "sources": sources,
            "source_fetched_at": source_fetched_at,
        }
    except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        return None


def __collector_not_materialized_result_body(_v4_scope, /, collected, *, workload_id, modules, collector_payload):
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
        and _v4_global(_v4_scope, 'type')(row_count) is _v4_global(_v4_scope, 'int')
        and row_count > 0
    ):
        return None
    result = _v4_global(_v4_scope, 'dict')(collected)
    result.update(
        {
            "status": "NOT_MATERIALIZED",
            "workload_id": workload_id,
            "modules": modules,
            "failure_class": "UPSTREAM_NOT_READY",
            "reason": "HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED",
            "collector_status": _v4_global(_v4_scope, 'str')(collector_payload.get("status") or "CANNOT_CONFIRM"),
            "row_count": row_count if _v4_global(_v4_scope, 'type')(row_count) is _v4_global(_v4_scope, 'int') else 0,
            "hourly_artifact_status": "NOT_MATERIALIZED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    return result
