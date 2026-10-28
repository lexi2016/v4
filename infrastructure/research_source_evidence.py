"""Read one exact, owned ZSXQ slot receipt and its run-bound artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from domains.research_source_validation import (
    collector_source_cutoff,
    strict_source_receipt_time,
)
from infrastructure.owned_path import resolve_owned_path


_STATUS_SCHEMA = "v3_5.zsxq_hourly_delta.v1"
_SUMMARY_NAME = "zsxq_summary.json"
_FETCH_NAME = "zsxq_recent_topics_fetch_result.json"


@dataclass(frozen=True)
class ZsxqSlotEvidence:
    """Parsed evidence and physical hashes from the three exact owned files."""

    status_path: Path
    status: dict[str, Any]
    summary: dict[str, Any]
    fetch_result: dict[str, Any]
    status_sha256: str
    summary_sha256: str
    fetch_result_sha256: str


def _parse_object(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _read_declared_artifact(
    data_root: Path, value: Any, expected_relative: str
) -> tuple[dict[str, Any], bytes] | None:
    if not isinstance(value, str) or not value:
        return None
    if Path(value).is_absolute():
        try:
            relative = Path(value).absolute().relative_to(
                Path(data_root).resolve()
            ).as_posix()
        except (OSError, ValueError):
            return None
    else:
        relative = value
    if relative != expected_relative:
        return None
    try:
        raw = resolve_owned_path(data_root, expected_relative).read_bytes()
    except (OSError, ValueError):
        return None
    parsed = _parse_object(raw)
    return (parsed, raw) if parsed is not None else None


def read_zsxq_slot_evidence(
    data_root: str | Path, business_date: str, slot: str
) -> ZsxqSlotEvidence | None:
    """Read and validate the exact date/slot receipt, summary and fetch bytes.

    Each of the three files is read once. Their parsed objects and SHA-256
    values therefore always refer to the same physical byte sequences.
    References must resolve to the exact owned status run; no ``latest``
    discovery, traversal, cross-run alias, or out-of-root path is accepted.
    """
    if (
        not isinstance(business_date, str)
        or re.fullmatch(r"\d{8}", business_date) is None
        or not isinstance(slot, str)
        or re.fullmatch(r"\d{4}", slot) is None
    ):
        return None
    status_relative = (
        f"research_module/runtime_outputs/zsxq_hourly/{business_date}/{slot}/"
        f"v35_zsxq_hourly_status_{business_date}_{slot}.json"
    )
    try:
        root = Path(data_root)
        status_path = resolve_owned_path(root, status_relative)
        status_raw = status_path.read_bytes()
    except (OSError, TypeError, ValueError):
        return None
    status = _parse_object(status_raw)
    if status is None or (
        status.get("schema_version") != _STATUS_SCHEMA
        or status.get("source") != "zsxq"
        or status.get("trade_date") != business_date
        or status.get("slot") != slot
        or status.get("status_path") != status_relative
        or status.get("fetch_ok") is not True
        or status.get("status") not in {"READY", "READY_EMPTY"}
        or status.get("production_allowed") is not False
        or status.get("buy_gate_updated") is not False
        or status.get("orders_sent") is not False
    ):
        return None

    run_id = str(status.get("latest_run_id") or "")
    if re.fullmatch(rf"{business_date}_{slot}00_[A-Za-z0-9_-]+", run_id) is None:
        return None
    run_relative = f"external_sources/zsxq_hourly/{run_id}"
    paths = status.get("paths")
    if not isinstance(paths, Mapping) or paths.get("run_dir") != run_relative:
        return None
    summary_artifact = _read_declared_artifact(
        root, paths.get("summary"), f"{run_relative}/{_SUMMARY_NAME}"
    )
    fetch_artifact = _read_declared_artifact(
        root, paths.get("fetch_result"),
        f"{run_relative}/{_FETCH_NAME}",
    )
    if summary_artifact is None or fetch_artifact is None:
        return None
    summary, summary_raw = summary_artifact
    fetch_result, fetch_raw = fetch_artifact

    fetched_at = strict_source_receipt_time(status.get("fetched_at"))
    source_cutoff = strict_source_receipt_time(status.get("source_cutoff"))
    try:
        expected_cutoff = collector_source_cutoff(business_date, slot)
    except ValueError:
        return None
    if (
        fetched_at is None
        or source_cutoff != expected_cutoff
        or summary.get("ok") is not True
        or fetch_result.get("ok") is not True
        or fetch_result.get("success") is not True
        or fetch_result.get("page_count") != status.get("page_count")
        or summary.get("raw_topic_count") != status.get("topic_count")
        or summary.get("effective_topic_count") != status.get("effective_topic_count")
    ):
        return None

    if status.get("status") == "READY_EMPTY":
        page_count = status.get("page_count")
        topic_count = status.get("topic_count")
        effective_topic_count = status.get("effective_topic_count")
        if (
            fetched_at.strftime("%Y%m%d") != business_date
            or fetched_at > expected_cutoff
            or type(page_count) is not int
            or page_count < 1
            or type(topic_count) is not int
            or topic_count != 0
            or type(effective_topic_count) is not int
            or effective_topic_count != 0
            or type(summary.get("raw_topic_count")) is not int
            or summary.get("raw_topic_count") != 0
            or type(summary.get("effective_topic_count")) is not int
            or summary.get("effective_topic_count") != 0
            or summary.get("effective_topics") != []
            or summary.get("stock_lookup_error") not in {None, ""}
            or type(fetch_result.get("count")) is not int
            or fetch_result.get("count") != 0
            or type(fetch_result.get("page_count")) is not int
            or fetch_result.get("page_count") < 1
        ):
            return None

    return ZsxqSlotEvidence(
        status_path=status_path,
        status=status,
        summary=summary,
        fetch_result=fetch_result,
        status_sha256=hashlib.sha256(status_raw).hexdigest(),
        summary_sha256=hashlib.sha256(summary_raw).hexdigest(),
        fetch_result_sha256=hashlib.sha256(fetch_raw).hexdigest(),
    )


__all__ = ["ZsxqSlotEvidence", "read_zsxq_slot_evidence"]
