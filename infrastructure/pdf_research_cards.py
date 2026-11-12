"""Read-only machine-generated PDF research cards for the V4 research panel.

The local Qwen batch writer stores one receipt per document under
``<data_root>/external_sources/zsxq_hourly/pdf_local/research/batches/<batch>/
documents/<document_id>/receipt.json``.  This module projects only displayable
receipts for one source date.

The source date is resolved without trusting the ingestion index:

``receipt.page_input.path`` (must stay under the research root) ->
``page-input.json.source.pdf_path`` -> ``知识星球/YYYY年M月D日/``.

PDF files themselves are never opened.  The ZSXQ ingestion index is optional
source metadata and is deliberately not required: its document ids do not
currently bind these Qwen receipts, so reading the 23 MB index on every panel
request would add cost without evidence.  Cards therefore expose the PDF
filename stem as title and mark the source group CANNOT_CONFIRM.

Displayable receipts are grouped by ``document_id`` because the same source PDF
can be analyzed in several batches.  Exactly one receipt per document is kept,
chosen deterministically by status priority
``USER_ACCEPTED_REUSED_REPORT`` > ``MODEL_GENERATED_SOURCE_COMPLETE`` >
``MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING`` > ``SUCCEEDED``; ties go
to the newest receipt file mtime, then to the lowest ``batch_id`` (the first in
the already sorted receipt traversal).  A receipt whose mtime cannot be read is
treated as oldest.  Merged batches are exposed as ``superseded_batch_ids`` and
summed in ``duplicate_count``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

RESEARCH_ROOT_RELATIVE = "external_sources/zsxq_hourly/pdf_local/research"
SCHEMA_VERSION = "v4.pdf_research.machine_cards.v1"
DISPLAYABLE_STATUSES = frozenset(
    {
        "SUCCEEDED",
        "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
        "MODEL_GENERATED_SOURCE_COMPLETE",
        "USER_ACCEPTED_REUSED_REPORT",
    }
)
STATUS_PRIORITY = {
    "USER_ACCEPTED_REUSED_REPORT": 4,
    "MODEL_GENERATED_SOURCE_COMPLETE": 3,
    "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING": 2,
    "SUCCEEDED": 1,
}
REVIEWED_SOURCE_STATUSES = frozenset(
    {"SOURCE_REVIEW_COMPLETE", "SOURCE_REVIEW_ACCEPTED", "SOURCE_REVIEW_PASSED"}
)
SAFETY = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
MAX_CARDS_PER_DATE = 200
MAX_PREVIEW_CHARS = 4000
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_PAGE_INPUT_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_ID_LIST = 50
MAX_REASON_LIST = 50
DATE_IN_PDF_PATH = re.compile(r"知识星球/(\d{4})年(\d{1,2})月(\d{1,2})日/")
DOCUMENT_ID_PATTERN = re.compile(r"[0-9a-f]{64}")


class MachineCardsError(ValueError):
    """A stable, safe-to-record machine-card read error code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _date(value: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise MachineCardsError("TRADE_DATE_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise MachineCardsError("TRADE_DATE_INVALID") from error
    return value


def _read_json_bounded(path: Path, max_bytes: int) -> dict[str, Any]:
    """Read one owned JSON file with a hard byte bound."""
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("bounded JSON file exceeds limit")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bounded JSON file is not an object")
    return value


def _read_preview(path: Path) -> str:
    """Read only the first bounded characters of report.md."""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        preview = handle.read(MAX_PREVIEW_CHARS)
    return preview[1:] if preview.startswith("﻿") else preview


def _resolve_within(root: Path, raw: Any) -> Path | None:
    """Resolve one referenced artifact and confine it to the research root."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        candidate = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not candidate.is_relative_to(root):
        return None
    return candidate


def _source_date(pdf_path: Any) -> str | None:
    if not isinstance(pdf_path, str):
        return None
    match = DATE_IN_PDF_PATH.search(pdf_path.replace("\\", "/"))
    if match is None:
        return None
    year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
    try:
        return _date(f"{year}{month:02d}{day:02d}")
    except MachineCardsError:
        return None


def _base(status: str, research_date: str, *, cannot_confirm: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "research_date": research_date,
        "card_count": 0,
        "matched_count": 0,
        "duplicate_count": 0,
        "cannot_confirm_count": 0,
        "cannot_confirm": sorted(set(cannot_confirm or [])),
        "cannot_confirm_document_ids": [],
        "unresolved_document_ids": [],
        "truncated": False,
        "max_cards_per_date": MAX_CARDS_PER_DATE,
        "preview_max_chars": MAX_PREVIEW_CHARS,
        "source_index_used": False,
        "items": [],
        **SAFETY,
    }


def _review_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    metadata = receipt.get("report_metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    source_status = metadata.get("source_review_status")
    source_status = str(source_status) if isinstance(source_status, str) and source_status else None
    if source_status in REVIEWED_SOURCE_STATUSES:
        review_status = "REVIEWED"
        human_reviewed = True
    elif source_status:
        review_status = "NOT_REVIEWED"
        human_reviewed = False
    else:
        review_status = "CANNOT_CONFIRM"
        human_reviewed = False
    user_status = metadata.get("user_acceptance_status")
    user_status = str(user_status) if isinstance(user_status, str) and user_status else None
    origin_status = metadata.get("origin_status")
    origin_status = str(origin_status) if isinstance(origin_status, str) and origin_status else None
    return {
        "origin_status": origin_status,
        "source_review_status": source_status,
        "user_acceptance_status": user_status,
        "review_status": review_status,
        "human_reviewed": human_reviewed,
        "user_accepted": user_status == "USER_ACCEPTED",
    }


def _card(
    *,
    receipt: Mapping[str, Any],
    document_id: str,
    batch_id: str,
    research_date: str,
    pdf_path: str,
    report_path: Path,
    receipt_path: Path,
    research_root: Path,
) -> dict[str, Any]:
    original_filename = Path(pdf_path.replace("\\", "/")).name or document_id
    title = Path(original_filename).stem or document_id[:12]
    source_relative = pdf_path.replace("\\", "/")
    marker = source_relative.find("知识星球/")
    if marker >= 0:
        source_relative = source_relative[marker:]
    report_ref = receipt.get("report") if isinstance(receipt.get("report"), Mapping) else {}
    return {
        "document_id": document_id,
        "research_date": research_date,
        "status": str(receipt.get("status")),
        "batch_id": batch_id,
        "title": title[:200],
        "title_source": "PDF_FILENAME_STEM",
        "source": {
            "source_group_name": None,
            "source_group_status": "CANNOT_CONFIRM_INGESTION_INDEX_NOT_LINKED",
            "original_filename": original_filename[:300],
            "source_directory": Path(source_relative).parent.name,
            "source_relative_path": source_relative,
            "source_pdf_path": pdf_path,
        },
        "review": _review_projection(receipt),
        "report": {
            "path": report_path.relative_to(research_root).as_posix(),
            "receipt_path": receipt_path.relative_to(research_root).as_posix(),
            "sha256": report_ref.get("sha256"),
            "bytes": report_ref.get("bytes"),
            "preview": _read_preview(report_path),
            "preview_max_chars": MAX_PREVIEW_CHARS,
        },
        "superseded_batch_ids": [],
        "machine_generated": True,
        "read_only": True,
        **SAFETY,
    }


def read_machine_cards(data_root: Path, research_date: str) -> dict[str, Any]:
    """Project displayable machine research cards for one exact source date.

    Read-only and fail-closed: a missing root, corrupt receipt, path escape, or
    unexpected exception becomes NOT_MATERIALIZED / CANNOT_CONFIRM evidence
    instead of an exception or HTTP 500.

    One card is returned per ``document_id``.  Selection priority is
    ``USER_ACCEPTED_REUSED_REPORT`` > ``MODEL_GENERATED_SOURCE_COMPLETE`` >
    ``MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING`` > ``SUCCEEDED``;
    equal status is resolved by newest receipt file mtime, then lowest
    ``batch_id``.  ``matched_count`` is the unique document count after dedupe
    (used for truncation), ``duplicate_count`` is the number of merged receipts,
    and ``card_count`` is the number of returned items.
    """
    selected = research_date if isinstance(research_date, str) else ""
    try:
        selected = _date(research_date)
        root = Path(data_root).expanduser().resolve()
        if not root.is_dir():
            return _base("CANNOT_CONFIRM", selected, cannot_confirm=["DATA_ROOT_INVALID"])
        research_root = (root / RESEARCH_ROOT_RELATIVE).resolve()
        if not research_root.is_dir():
            return _base(
                "NOT_MATERIALIZED",
                selected,
                cannot_confirm=["PDF_RESEARCH_NOT_MATERIALIZED"],
            )
        batches_root = (research_root / "batches").resolve()
        if not batches_root.is_dir():
            return _base(
                "NOT_MATERIALIZED",
                selected,
                cannot_confirm=["PDF_RESEARCH_BATCHES_NOT_MATERIALIZED"],
            )

        reasons: set[str] = set()
        skipped_ids: list[str] = []
        unresolved_ids: list[str] = []
        cannot_count = 0

        def fail(code: str, document_id: str) -> None:
            nonlocal cannot_count
            reasons.add(code)
            cannot_count += 1
            if document_id and len(skipped_ids) < MAX_DOCUMENT_ID_LIST:
                skipped_ids.append(document_id)

        candidates: list[tuple[dict[str, Any], int, int, str]] = []
        for receipt_path in sorted(batches_root.glob("*/documents/*/receipt.json")):
            document_dir = receipt_path.parent
            fallback_id = document_dir.name if DOCUMENT_ID_PATTERN.fullmatch(document_dir.name) else ""
            resolved_receipt = _resolve_within(research_root, str(receipt_path))
            if resolved_receipt is None:
                fail("RECEIPT_PATH_REJECTED", fallback_id)
                continue
            try:
                receipt = _read_json_bounded(resolved_receipt, MAX_RECEIPT_BYTES)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                fail("RECEIPT_UNREADABLE", fallback_id)
                continue
            if receipt.get("status") not in DISPLAYABLE_STATUSES:
                continue
            document_id = receipt.get("document_id")
            if not isinstance(document_id, str) or not DOCUMENT_ID_PATTERN.fullmatch(document_id):
                fail("DOCUMENT_ID_INVALID", fallback_id)
                continue

            page_input_ref = receipt.get("page_input")
            page_input_raw = page_input_ref.get("path") if isinstance(page_input_ref, Mapping) else None
            page_input_path = _resolve_within(research_root, page_input_raw)
            if page_input_path is None:
                fail("PAGE_INPUT_PATH_REJECTED", document_id)
                continue
            try:
                page_input = _read_json_bounded(page_input_path, MAX_PAGE_INPUT_BYTES)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                fail("PAGE_INPUT_UNREADABLE", document_id)
                continue
            source_ref = page_input.get("source")
            pdf_path = source_ref.get("pdf_path") if isinstance(source_ref, Mapping) else None
            card_date = _source_date(pdf_path)
            if card_date is None:
                fail("DATE_UNRESOLVED", document_id)
                if len(unresolved_ids) < MAX_DOCUMENT_ID_LIST:
                    unresolved_ids.append(document_id)
                continue
            if card_date != selected:
                continue

            report_ref = receipt.get("report")
            report_raw = report_ref.get("path") if isinstance(report_ref, Mapping) else None
            report_path = _resolve_within(research_root, report_raw)
            if report_path is None:
                fail("REPORT_PATH_REJECTED", document_id)
                continue
            try:
                if not report_path.is_file():
                    raise OSError("report is not a file")
                card = _card(
                    receipt=receipt,
                    document_id=document_id,
                    batch_id=document_dir.parents[1].name,
                    research_date=card_date,
                    pdf_path=str(pdf_path),
                    report_path=report_path,
                    receipt_path=resolved_receipt,
                    research_root=research_root,
                )
            except (OSError, UnicodeError, ValueError, RuntimeError):
                fail("REPORT_UNREADABLE", document_id)
                continue
            try:
                receipt_mtime_ns = resolved_receipt.stat().st_mtime_ns
            except OSError:
                receipt_mtime_ns = -1
            candidates.append(
                (card, STATUS_PRIORITY[str(card["status"])], receipt_mtime_ns, str(card["batch_id"]))
            )

        grouped: dict[str, list[tuple[dict[str, Any], int, int, str]]] = {}
        for candidate in candidates:
            grouped.setdefault(str(candidate[0]["document_id"]), []).append(candidate)

        deduped: list[dict[str, Any]] = []
        duplicate_count = 0
        for group in grouped.values():
            winner = min(
                group,
                key=lambda candidate: (-candidate[1], -candidate[2], candidate[3]),
            )
            card = winner[0]
            card["superseded_batch_ids"] = sorted(
                {candidate[3] for candidate in group if candidate is not winner}
            )
            duplicate_count += len(group) - 1
            deduped.append(card)

        deduped.sort(
            key=lambda row: (
                str((row.get("source") or {}).get("original_filename") or ""),
                str(row.get("document_id") or ""),
                str(row.get("batch_id") or ""),
            )
        )
        matched_count = len(deduped)
        truncated = matched_count > MAX_CARDS_PER_DATE
        items = deduped[:MAX_CARDS_PER_DATE]
        cannot_confirm = sorted(reasons)[:MAX_REASON_LIST]
        if not items:
            status = "CANNOT_CONFIRM" if cannot_count else "READY_EMPTY"
        else:
            status = "READY"
        return {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "research_date": selected,
            "card_count": len(items),
            "matched_count": matched_count,
            "duplicate_count": duplicate_count,
            "cannot_confirm_count": cannot_count,
            "cannot_confirm": cannot_confirm,
            "cannot_confirm_document_ids": skipped_ids,
            "unresolved_document_ids": unresolved_ids,
            "truncated": truncated,
            "max_cards_per_date": MAX_CARDS_PER_DATE,
            "preview_max_chars": MAX_PREVIEW_CHARS,
            "source_index_used": False,
            "items": items,
            **SAFETY,
        }
    except MachineCardsError as error:
        return _base("CANNOT_CONFIRM", selected, cannot_confirm=[error.code])
    except Exception as error:  # fail closed: never surface a reader exception as 500
        return _base(
            "CANNOT_CONFIRM",
            selected,
            cannot_confirm=[f"MACHINE_CARDS_READ_FAILED:{type(error).__name__}"],
        )


__all__ = [
    "RESEARCH_ROOT_RELATIVE",
    "SCHEMA_VERSION",
    "DISPLAYABLE_STATUSES",
    "MachineCardsError",
    "read_machine_cards",
]
