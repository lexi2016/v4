"""Build one V3.5-owned hourly research source from already-landed inputs.

This is a bounded port of V3's ``run_hourly_research.py`` input path.  The
business normalizer is the frozen V3 implementation in
``domains.research_hourly``; this module only discovers an owned ZSXQ status,
applies the original item-quality rules, and atomically publishes the frozen
source consumed by ``ops.run_hourly_research``.

Oracle SHA-256 (V3 producer):
850FFFDF16B7C0127852CBE9CC374AED353E8D7CB1C2BA73D2EFF880C95D022E
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from domains.research_hourly import build_research_lane_snapshot
from infrastructure.owned_path import resolve_owned_path


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SLOTS = ("0830", *(f"{hour:02d}00" for hour in range(7, 24)))
_VOLATILE_IDENTITY_KEYS = frozenset(
    {"generated_at", "crawl_time", "first_seen_at", "last_checked_at", "observed_at"}
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    if path.is_file():
        if path.read_bytes() == encoded:
            return path
        try:
            existing = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            existing = {}
        if _canonical_identity(existing) == _canonical_identity(payload):
            return path
        existing_rows = (
            existing.get("stock_research_timeline")
            if isinstance(existing, Mapping)
            else None
        )
        new_rows = payload.get("stock_research_timeline")
        gaps = payload.get("cannot_confirm")
        explicit_late_recovery = isinstance(gaps, list) and any(
            isinstance(gap, Mapping)
            and gap.get("reason") == "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"
            for gap in gaps
        )
        if (
            isinstance(new_rows, list)
            and new_rows
            and (not existing_rows or explicit_late_recovery)
        ):
            superseded_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            recovery_payload = dict(payload)
            recovery_payload.setdefault("retry_of_sha256", superseded_sha)
            # The destination bytes are the only authoritative supersession
            # target; a caller-provided label must not be able to point the
            # recovery artifact at a different same-slot input.
            recovery_payload["supersedes"] = superseded_sha
            manifest = dict(
                recovery_payload.get("source_manifest")
                if isinstance(recovery_payload.get("source_manifest"), Mapping)
                else {}
            )
            business_date = str(
                recovery_payload.get("trade_date")
                or manifest.get("trade_date")
                or ""
            )
            slot = str(
                recovery_payload.get("slot")
                or manifest.get("hourly_slot")
                or ""
            )
            pit_cutoff = str(
                recovery_payload.get("pit_cutoff")
                or manifest.get("pit_cutoff")
                or ""
            )
            if not pit_cutoff and re.fullmatch(r"\d{8}", business_date) and re.fullmatch(r"\d{4}", slot):
                pit_cutoff = _cutoff(business_date, slot).isoformat(timespec="seconds")
            raw_receipts = recovery_payload.get("source_receipts")
            if raw_receipts is None:
                raw_receipts = manifest.get("source_receipts")
            source_receipts = (
                [str(item) for item in raw_receipts if str(item)]
                if isinstance(raw_receipts, (list, tuple))
                else ([str(raw_receipts)] if raw_receipts else [])
            )
            manifest.setdefault("pit_cutoff", pit_cutoff)
            manifest.setdefault("source_receipts", source_receipts)
            recovery_payload["source_manifest"] = manifest
            recovery_payload["recovery_metadata"] = {
                "retry_of_sha256": str(recovery_payload["retry_of_sha256"]),
                "supersedes": str(recovery_payload["supersedes"]),
                "pit_cutoff": pit_cutoff,
                "source_receipts": source_receipts,
            }
            encoded = json.dumps(
                recovery_payload, ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
            digest = hashlib.sha256(encoded).hexdigest()[:16]
            recovery = path.with_name(f"{path.stem}.recovery-{digest}{path.suffix}")
            if recovery.is_file():
                if recovery.read_bytes() == encoded:
                    return recovery
                raise ValueError(
                    f"conflicting hourly research recovery input: {recovery.name}"
                )
            temporary = recovery.with_name(
                f".{recovery.name}.{os.getpid()}.tmp"
            )
            temporary.write_bytes(encoded)
            os.replace(temporary, recovery)
            return recovery
        raise ValueError(f"conflicting hourly research input: {path.name}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)
    return path


def _canonical_identity(value: Any, path: tuple[str, ...] = ()) -> Any:
    """Remove only volatile observation timestamps from same-slot identity."""
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_identity(item, (*path, str(key)))
            for key, item in value.items()
            if key not in _VOLATILE_IDENTITY_KEYS
            and not (key == "published_at" and path == ("source_manifest",))
        }
    if isinstance(value, list):
        return [_canonical_identity(item, path) for item in value]
    return value


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    digits = "".join(character for character in text if character.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _clean_name(value: Any) -> str:
    return re.sub(r"[（(].*?[）)]", "", str(value or "")).replace(" ", "").strip()


def _zsxq_topic_url(topic_id: Any) -> str:
    """Build a ZSXQ topic URL only from an exact 17-digit ASCII topic id."""
    if isinstance(topic_id, bool):
        return ""
    if isinstance(topic_id, int):
        candidate = str(topic_id)
    elif isinstance(topic_id, str):
        candidate = topic_id
    else:
        return ""
    if not re.fullmatch(r"[0-9]{17}", candidate):
        return ""
    return f"https://wx.zsxq.com/dweb2/index/topic_detail/{candidate}"


def _compact(*values: Any, limit: int = 5000) -> str:
    text = re.sub(r"\s+", " ", " ".join(str(value or "") for value in values)).strip()
    return text[:limit]


def _as_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(_SHANGHAI)


def _cutoff(business_date: str, slot: str) -> datetime:
    return datetime.strptime(
        business_date + slot, "%Y%m%d%H%M"
    ).replace(tzinfo=_SHANGHAI, second=59)


def _latest_zsxq_status(
    data_root: Path, business_date: str, slot: str
) -> tuple[Path, dict[str, Any]] | None:
    root = resolve_owned_path(
        data_root,
        f"research_module/runtime_outputs/zsxq_hourly/{business_date}",
    )
    if not root.is_dir():
        return None
    candidates: list[tuple[int, Path, dict[str, Any]]] = []
    for path in root.glob("*/v35_zsxq_*_status_*.json"):
        payload = _read_json(path)
        raw_slot = str(payload.get("slot") or path.parent.name)
        if not raw_slot.isdigit() or int(raw_slot) > int(slot):
            continue
        if payload.get("fetch_ok") is not True:
            continue
        # A newer empty delta must not hide an earlier verified non-empty
        # same-day snapshot.  Hourly consumers need the latest usable research
        # state, while READY_EMPTY remains valid evidence that the refresh ran.
        if payload.get("status") != "READY":
            continue
        candidates.append((int(raw_slot), path, payload))
    if not candidates:
        return None
    _, path, payload = max(candidates, key=lambda item: item[0])
    return path, payload


def _source_quality(
    *, body: str, code: str, theme: str, source_type: str, cannot_confirm: list[str]
) -> tuple[str, str]:
    # Exact V3 build_item weights for the ZSXQ lane.
    score = 48.0
    if len(body) >= 120:
        score += 15
    if code:
        score += 15
    if theme:
        score += 6
    if "研报" in body or "research" in body.lower() or source_type in {"research", "report"}:
        score += 6
    score = min(100.0, score)
    level = "HIGH" if score >= 80 else "MEDIUM" if score >= 55 else "LOW"
    evidence = (
        "L2_MEDIUM"
        if cannot_confirm
        else "L3_STRONG"
        if score >= 80
        else "L2_MEDIUM"
        if score >= 55
        else "L1_WEAK"
    )
    return level, evidence


def _zsxq_rows(
    data_root: Path, business_date: str, slot: str
) -> tuple[list[dict[str, Any]], list[str]]:
    selected = _latest_zsxq_status(data_root, business_date, slot)
    if selected is None:
        return [], ["ZSXQ_STATUS_NOT_AVAILABLE_BY_SLOT"]
    status_path, status = selected
    fetched_at = _as_time(status.get("fetched_at"))
    cutoff = _cutoff(business_date, slot)
    if fetched_at is None:
        return [], ["ZSXQ_STATUS_NOT_POINT_IN_TIME_SAFE"]
    late_recovery = fetched_at > cutoff
    if late_recovery:
        source_cutoff = _as_time(status.get("source_cutoff"))
        if source_cutoff is None or source_cutoff > cutoff:
            return [], ["ZSXQ_STATUS_NOT_POINT_IN_TIME_SAFE"]
    paths = status.get("paths") if isinstance(status.get("paths"), Mapping) else {}
    summary_path = Path(str(paths.get("summary") or ""))
    summary = _read_json(summary_path) if summary_path.is_file() else {}
    if not summary:
        return [], ["ZSXQ_SUMMARY_UNREADABLE"]
    boundary = [
        str(value)
        for value in status.get("cannot_confirm") or []
        if str(value).strip()
    ]
    if late_recovery:
        boundary.append("ZSXQ_RECOVERY_FETCHED_AFTER_SLOT")
    if summary.get("primary_refetch_failed") is True:
        boundary.append("ZSXQ_PRIMARY_REFETCH_FAILED_FALLBACK_USED")
    rows: list[dict[str, Any]] = []
    stock_master: dict[str, dict[str, Any]] = {}
    for topic in summary.get("effective_topics") or []:
        if not isinstance(topic, Mapping):
            continue
        published = _as_time(topic.get("create_time"))
        if published is None or published > cutoff:
            continue
        themes = topic.get("themes") if isinstance(topic.get("themes"), list) else []
        theme = " / ".join(
            str(item.get("theme") or "").strip()
            for item in themes
            if isinstance(item, Mapping) and str(item.get("theme") or "").strip()
        )
        companies_raw = topic.get("companies")
        companies = (
            [companies_raw]
            if isinstance(companies_raw, Mapping)
            else [item for item in companies_raw if isinstance(item, Mapping)]
            if isinstance(companies_raw, list)
            else []
        )
        for company in companies:
            code = _normalize_code(company.get("code"))
            if not code:
                continue
            name = _clean_name(company.get("name")) or code
            title = str(topic.get("title") or topic.get("evidence") or "知识星球研报")
            body = str(topic.get("content_head") or topic.get("evidence") or title)
            topic_id = topic.get("topic_id")
            group_id = topic.get("group_id")
            topic_group = topic.get("group")
            if group_id is None and isinstance(topic_group, Mapping):
                group_id = topic_group.get("group_id")
            topic_url = _zsxq_topic_url(topic_id)
            source_cannot_confirm = [*boundary]
            if not topic_url and "URL_REQUIRED" not in source_cannot_confirm:
                source_cannot_confirm.append("URL_REQUIRED")
            confidence, evidence_level = _source_quality(
                body=body,
                code=code,
                theme=theme,
                source_type="zsxq",
                cannot_confirm=source_cannot_confirm,
            )
            raw_id = hashlib.sha256(
                f"{business_date}|zsxq|{topic_id}|{code}".encode("utf-8")
            ).hexdigest()[:16]
            observed = fetched_at.isoformat(timespec="seconds")
            rows.append(
                {
                    "raw_id": raw_id,
                    "trade_date": business_date,
                    "source_type": "zsxq",
                    "source_name": "知识星球",
                    "source_path": (
                        f"research_module/runtime_outputs/zsxq_hourly/"
                        f"{business_date}/{status.get('slot')}/{status_path.name}"
                    ),
                    "url": topic_url,
                    "topic_id": topic_id,
                    "group_id": group_id,
                    "title": title,
                    "raw_text": _compact(body, title),
                    "published_at": published.isoformat(timespec="seconds"),
                    "crawl_time": observed,
                    "source_published_at": published.isoformat(timespec="seconds"),
                    "first_seen_at": observed,
                    "last_checked_at": observed,
                    "display_event_time": published.isoformat(timespec="seconds"),
                    "is_new_since_last_slot": True,
                    "is_recheck_duplicate": False,
                    "source_evidence_level": evidence_level,
                    "source_confidence": confidence,
                    "source_cannot_confirm": source_cannot_confirm,
                    "themes": [theme] if theme else [],
                    "mentioned_stock_candidates": [name, code],
                    "stock": name,
                    "stock_code": code,
                    "stock_name": name,
                    "slot": slot,
                }
            )
            stock_master[code] = {"name": name, "aliases": [name, code]}
    return rows, boundary


def build_hourly_research_input(
    *, data_root: Path, business_date: str, slot: str
) -> dict[str, Any]:
    if slot not in _SLOTS:
        raise ValueError("hourly research slot must be 0830 or 0700 through 2300")
    datetime.strptime(business_date, "%Y%m%d")
    rows, gaps = _zsxq_rows(Path(data_root), business_date, slot)
    stock_master = {
        str(row["stock_code"]): {
            "name": str(row["stock_name"]),
            "aliases": [str(row["stock_name"]), str(row["stock_code"])],
        }
        for row in rows
    }
    snapshot = build_research_lane_snapshot(business_date, rows, stock_master)
    generated_at = min(datetime.now(_SHANGHAI), _cutoff(business_date, slot))
    snapshot["source_manifest"].update(
        {
            "generated_at": generated_at.isoformat(timespec="seconds"),
            "published_at": generated_at.isoformat(timespec="seconds"),
            "hourly_slot": slot,
            "producer": "ops.collect_hourly_research_input",
            "producer_oracle_sha256": "850fffdf16b7c0127852cbe9cc374aed353e8d7cb1c2ba73d2eff880c95d022e",
        }
    )
    snapshot["cannot_confirm"] = [
        *snapshot.get("cannot_confirm", []),
        *({"module": "research_intelligence", "reason": gap} for gap in gaps),
    ]
    snapshot["hourly_research"] = {
        "schema_version": "hourly_research_dashboard.v1",
        "trade_date": business_date,
        "latest_slot": slot,
        "latest_research_slot": slot,
        "slot_count": 1,
        "status": "READY_WITH_RESEARCH_POOL" if rows else "READY_EMPTY",
        "row_count": len(rows),
    }
    destination = resolve_owned_path(
        data_root, f"research/incoming/{business_date}/{slot}.json"
    )
    published_path = _atomic_json(destination, snapshot)
    source_path = published_path.relative_to(Path(data_root)).as_posix()
    return {
        "schema_version": "v3_5.hourly_research_input_run.v1",
        "status": "READY_WITH_RESEARCH_POOL" if rows else "READY_EMPTY",
        "business_date": business_date,
        "slot": slot,
        "row_count": len(rows),
        "source_path": source_path,
        "source_sha256": hashlib.sha256(published_path.read_bytes()).hexdigest(),
        "recovery": published_path != destination,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect one V3.5 hourly research input")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True)
    args = parser.parse_args()
    result = build_hourly_research_input(
        data_root=args.data_root,
        business_date=args.date,
        slot=args.slot,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
