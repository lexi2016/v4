"""Exact-date, cutoff-bound V3 news/research score context.

The stage-center process never imports the legacy V3 package.  This module
reads the two immutable V3 research artifacts and exposes the small score
overlay used by the old live-stage formula.  All paths are explicit and every
artifact is checked before a context is returned; a missing or drifted input
raises instead of silently producing a zero-filled research overlay.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ResearchContextError(ValueError):
    """An exact-date research/news artifact failed its read contract."""


_DATE_RE = re.compile(r"^\d{8}$")
_SLOT_RE = re.compile(r"^(\d{2})(\d{2})$")
_A_CODE_RE = re.compile(r"(\d{6})")
_READY_STATUSES = frozenset({"READY", "READY_WITH_RESEARCH_POOL", "DATA_PARTIAL_OBSERVE_ONLY"})
_SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ResearchScore:
    """The V3 score fields and provenance for one canonical A-share code."""

    news_quality_score: float = 0.0
    research_quality_score: float = 0.0
    latest_research_slot: str = ""
    research_delta_hits: int = 0
    news_research_reason: tuple[str, ...] = ()
    source_health: str = ""


@dataclass(frozen=True)
class ResearchContext:
    """Scores valid for one exact trade date and one stage cutoff."""

    trade_date: str
    stage_cutoff: str
    selected_slot: str
    by_code: Mapping[str, ResearchScore]
    source_evidence: tuple[str, ...]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ResearchContextError(f"research JSON unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ResearchContextError(f"research JSON object required: {path}")
    return value


def _safe_float(value: Any) -> float:
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _canonical_a_code(value: Any) -> str:
    match = _A_CODE_RE.search(str(value or "").strip().upper())
    return f"A.{match.group(1)}" if match else ""


def _normalize_date(value: Any) -> str:
    return str(value or "").strip().replace("-", "")


def _cutoff_minutes(value: Any) -> int:
    text = str(value or "").strip()
    match = re.search(r"(?:^|\D)(\d{1,2}):(\d{2})", text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    elif re.fullmatch(r"\d{3,4}", text):
        padded = text.zfill(4)
        hour, minute = int(padded[:2]), int(padded[2:])
    else:
        raise ResearchContextError(f"stage cutoff is not a clock time: {value!r}")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ResearchContextError(f"stage cutoff is invalid: {value!r}")
    return hour * 60 + minute


def _slot_minutes(slot: str) -> int:
    match = _SLOT_RE.fullmatch(slot)
    if not match:
        raise ResearchContextError(f"hourly research slot is invalid: {slot!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ResearchContextError(f"hourly research slot is invalid: {slot!r}")
    return hour * 60 + minute


def _v3_system_root(root: Path | str) -> Path:
    """Resolve either the V3 ``v3_system`` root or its data child."""
    supplied = Path(root).expanduser().resolve()
    if (supplied / "30_runtime").is_dir():
        return supplied
    # RunnerConfig.v3_formal_root is the legacy data directory:
    # v3_system/30_runtime/opening_advisor_8771/data.
    if len(supplied.parents) >= 3:
        candidate = supplied.parents[2]
        if (candidate / "30_runtime").is_dir():
            return candidate
    raise ResearchContextError(f"V3 system root cannot be resolved: {supplied}")


def _assert_safe(payload: Mapping[str, Any], label: str) -> None:
    for flag in _SAFETY_FLAGS:
        if flag in payload and payload.get(flag) is not False:
            raise ResearchContextError(f"{label} safety flag {flag} must be false")


def _assert_declared_items_sha(payload: Mapping[str, Any], path: Path, label: str) -> None:
    """Honor optional producer-declared item SHA without requiring old files to carry it."""
    declared = payload.get("items_sha256") or payload.get("research_items_sha256") or payload.get("csv_sha256")
    paths = payload.get("paths")
    if not declared and isinstance(paths, Mapping):
        path_entry = paths.get("csv") or paths.get("items")
        if isinstance(path_entry, Mapping):
            declared = path_entry.get("sha256")
    if declared in (None, ""):
        return
    declared_text = str(declared).strip()
    if not _SHA_RE.fullmatch(declared_text) or _sha(path).lower() != declared_text.lower():
        raise ResearchContextError(f"{label} items SHA mismatch")


def _news_score(row: Mapping[str, Any]) -> float:
    """Exact Windows V3 ``_quality_score_from_news_row`` semantics."""
    score = 20.0
    if str(row.get("preselect_hit") or "").upper() == "Y":
        score += 18.0
    if str(row.get("formal_pool_hit") or "").upper() == "Y":
        score += 16.0
    if row.get("research_hit_status") == "RESEARCH_TRACE_HIT":
        score += 14.0
    if row.get("stock_code"):
        score += 12.0
    if row.get("logic_excerpt"):
        score += 10.0
    if row.get("theme"):
        score += 6.0
    return min(score, 100.0)


def _research_paths(v3_root: Path, trade_date: str, cutoff: int) -> tuple[str, Path, Path, Path]:
    date_root = v3_root / "研报模块" / "runtime_outputs" / "hourly_research" / trade_date
    if not date_root.is_dir():
        raise ResearchContextError("V3 exact-date hourly research root missing")
    candidates: list[tuple[int, str, Path, Path, Path]] = []
    for directory in date_root.iterdir():
        if not directory.is_dir() or not _SLOT_RE.fullmatch(directory.name):
            continue
        slot_minutes = _slot_minutes(directory.name)
        if slot_minutes > cutoff:
            continue
        manifest = directory / f"hourly_research_manifest_{trade_date}_{directory.name}.json"
        items = directory / f"hourly_research_items_{trade_date}_{directory.name}.csv"
        acceptance = directory / f"hourly_research_acceptance_{trade_date}_{directory.name}.json"
        if manifest.is_file() and items.is_file() and acceptance.is_file():
            candidates.append((slot_minutes, directory.name, manifest, items, acceptance))
    if not candidates:
        raise ResearchContextError("V3 exact-date hourly research manifest/items missing before cutoff")
    _minutes, slot, manifest, items, acceptance = max(candidates, key=lambda item: item[0])
    return slot, manifest, items, acceptance


def load_research_context(
    v3_root: Path | str,
    *,
    trade_date: str,
    stage_cutoff: str,
) -> ResearchContext:
    """Load exact-date V3 morning-news and latest-as-of hourly research.

    ``stage_cutoff`` is the stage's immutable cutoff (for example
    ``09:35:05``).  The selected hourly slot is the greatest slot not later
    than that cutoff; no date-specific slot mapping or future fallback is
    permitted.
    """
    if not _DATE_RE.fullmatch(str(trade_date)):
        raise ResearchContextError("trade_date must be YYYYMMDD")
    cutoff_minutes = _cutoff_minutes(stage_cutoff)
    v3_system = _v3_system_root(v3_root)
    morning = v3_system / "30_runtime" / "timeline_scheduler" / "morning_news_0830" / trade_date / f"stock_mentions_{trade_date}.csv"
    if not morning.is_file():
        raise ResearchContextError("V3 exact-date morning news CSV missing")
    slot, manifest_path, items_path, acceptance_path = _research_paths(v3_system, trade_date, cutoff_minutes)
    manifest = _read_json(manifest_path)
    if _normalize_date(manifest.get("trade_date")) != trade_date or str(manifest.get("slot") or "") != slot:
        raise ResearchContextError("V3 hourly research manifest date/slot mismatch")
    if manifest.get("status") not in _READY_STATUSES:
        raise ResearchContextError("V3 hourly research manifest status invalid")
    _assert_safe(manifest, "V3 hourly research manifest")
    _assert_declared_items_sha(manifest, items_path, "V3 hourly research manifest")
    acceptance = _read_json(acceptance_path)
    if _normalize_date(acceptance.get("trade_date")) != trade_date or str(acceptance.get("slot") or "") != slot:
        raise ResearchContextError("V3 hourly research acceptance date/slot mismatch")
    if acceptance.get("status") not in _READY_STATUSES or acceptance.get("ok") is not True:
        raise ResearchContextError("V3 hourly research acceptance status invalid")
    _assert_safe(acceptance, "V3 hourly research acceptance")
    _assert_declared_items_sha(acceptance, items_path, "V3 hourly research acceptance")

    news_by_code: dict[str, tuple[float, tuple[str, ...]]] = {}
    try:
        with morning.open("r", encoding="utf-8-sig", newline="") as stream:
            news_rows = list(csv.DictReader(stream))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ResearchContextError("V3 exact-date morning news CSV unreadable") from error
    for row in news_rows:
        row_date = _normalize_date(row.get("trade_date"))
        if row_date and row_date != trade_date:
            raise ResearchContextError("V3 morning news trade_date mismatch")
        code = _canonical_a_code(row.get("stock_code"))
        if not code:
            continue
        score = _news_score(row)
        reasons = tuple(
            str(item).strip()
            for item in (row.get("intersection_summary") or row.get("trigger_basis") or row.get("source_title"),)
            if str(item).strip()
        )
        previous = news_by_code.get(code)
        if previous is None or score > previous[0]:
            news_by_code[code] = (score, reasons)
        elif score == previous[0] and reasons:
            news_by_code[code] = (score, tuple(dict.fromkeys((*previous[1], *reasons))))

    research_by_code: dict[str, tuple[float, int, tuple[str, ...]]] = {}
    try:
        with items_path.open("r", encoding="utf-8-sig", newline="") as stream:
            research_rows = list(csv.DictReader(stream))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ResearchContextError("V3 exact-date hourly research items unreadable") from error
    expected_count = manifest.get("row_count")
    if expected_count not in (None, "") and int(expected_count) != len(research_rows):
        raise ResearchContextError("V3 hourly research manifest row_count mismatch")
    acceptance_count = acceptance.get("row_count")
    if acceptance_count not in (None, "") and int(acceptance_count) != len(research_rows):
        raise ResearchContextError("V3 hourly research acceptance row_count mismatch")
    for row in research_rows:
        if _normalize_date(row.get("trade_date")) != trade_date or str(row.get("slot") or "") != slot:
            raise ResearchContextError("V3 hourly research item date/slot mismatch")
        code = _canonical_a_code(row.get("stock_code") or row.get("extracted_stock_codes"))
        if not code:
            continue
        score = _safe_float(row.get("quality_score"))
        prior_score, prior_delta, prior_reasons = research_by_code.get(code, (0.0, 0, ()))
        reason = str(row.get("title") or row.get("theme_tags") or "").strip()
        reasons = tuple(dict.fromkeys((*prior_reasons, *([reason] if reason else []))))
        is_new = str(row.get("is_new_since_last_slot") or "").strip().lower() in {"true", "1", "yes"}
        research_by_code[code] = (max(prior_score, score), prior_delta + int(is_new), reasons)

    all_codes = set(news_by_code) | set(research_by_code)
    by_code = {
        code: ResearchScore(
            news_quality_score=news_by_code.get(code, (0.0, ()))[0],
            research_quality_score=research_by_code.get(code, (0.0, 0, ()))[0],
            latest_research_slot=slot if code in research_by_code else "",
            research_delta_hits=research_by_code.get(code, (0.0, 0, ()))[1],
            news_research_reason=tuple(dict.fromkeys((*news_by_code.get(code, (0.0, ()))[1], *research_by_code.get(code, (0.0, 0, ()))[2]))),
            source_health=str((manifest.get("source_health") or {}).get("status") or manifest.get("status") or ""),
        )
        for code in sorted(all_codes)
    }
    evidence = (
        f"v3_morning_news_csv={morning}",
        f"v3_morning_news_csv_sha256={_sha(morning)}",
        f"v3_asof_research_manifest={manifest_path}",
        f"v3_asof_research_manifest_sha256={_sha(manifest_path)}",
        f"v3_asof_research_items={items_path}",
        f"v3_asof_research_items_sha256={_sha(items_path)}",
        f"v3_asof_research_acceptance={acceptance_path}",
        f"v3_asof_research_acceptance_sha256={_sha(acceptance_path)}",
        f"v3_asof_research_slot={slot}",
        f"v3_asof_research_cutoff={stage_cutoff}",
    )
    return ResearchContext(
        trade_date=trade_date,
        stage_cutoff=str(stage_cutoff),
        selected_slot=slot,
        by_code=by_code,
        source_evidence=evidence,
    )


__all__ = ["ResearchContext", "ResearchContextError", "ResearchScore", "load_research_context"]
