"""Read-only stock clue aggregation over machine-generated research reports.

The layer answers one research question only: *which stocks were mentioned by
how many independent machine-generated research reports on one exact source
date?*  It is a deterministic textual projection of the existing Qwen report
cards; it never scores, ranks for trading, or touches any signal, buy point or
BUY gate.

Input contract
--------------
``read_machine_cards(data_root, research_date)`` provides the deduplicated
card set.  Every card's ``report.path`` is resolved under the research root
``<data_root>/external_sources/zsxq_hourly/pdf_local/research`` and the full
``report.md`` is read (never the 4000-character card preview).  Reads are
bounded to 512 KiB; a longer report is truncated and flagged.

Deterministic entity-matching rules
-----------------------------------
a. The first 300 characters of each report are skipped.  That region contains
   the title and source attribution and would otherwise match broker names and
   the original PDF filename.
b. NAME hit: every ``name`` in the name table that occurs in the remaining
   report body maps to that row's ``ts_code``.
c. CODE hit: ``\\b\\d{6}\\.(SZ|SH|BJ)\\b`` and ``\\b\\d{5}\\.HK\\b`` are
   extracted directly from the remaining report body.
d. Multiple occurrences of the same target inside one report count once.

LinkProbability prior and confirmation gate
-------------------------------------------
Common-word stock names (for example ``机器人`` or ``农产品``) are also ordinary
nouns.  Instead of treating every name hit as a clue, the layer builds a
prior from the whole local report corpus (deduplicated by ``document_id``,
not limited to the requested date).  For every name in the name table:

* ``total`` counts all occurrences in all corpus report bodies (the first 300
  characters are skipped);
* ``evidenced`` counts occurrences whose report contains that target's
  explicit stock code, or whose +-15 character window contains a company /
  stock marker from ``CONTEXT_MARKERS``; one occurrence counts at most once;
* ``link_probability = evidenced / total`` (raw ratio, no smoothing);
  ``total == 0`` yields ``None``.

**Boundary rule (frozen; do not change back):** ``total < 3`` is an
insufficient sample and is always weak, never excluded and never confirmed by
the prior alone.  The low-evidence exclusion boundary is **inclusive**:
``total >= 3`` and ``link_probability <= 0.2`` is excluded.  It must not be
rewritten as ``< 0.2``; the frozen acceptance case 机器人 2/10 == 0.2 depends
on the inclusive comparison.

Per card the rules are, in priority order:

1. an explicit code hit confirms the target (``confirm_reasons=["CODE"]``,
   independent of the prior);
2. ``total < 3`` is an insufficient sample and is always weak, never generic
   and never confirmed by the prior alone;
3. ``total >= 3`` and ``link_probability <= 0.2`` is excluded as low-evidence
   and recorded in top-level ``generic_filtered``;
4. ``0.2 < link_probability < 0.5`` is a weak hit;
5. ``link_probability >= 0.5`` confirms the target with
   ``confirm_reasons=["CONTEXT"]``; when the same target also has an explicit
   code in the report the reasons become ``["CODE", "CONTEXT"]``;
6. paragraph coherence: when one paragraph (split on blank lines) already has
   at least two confirmed targets, weak names in that paragraph are upgraded
   to confirmed with ``confirm_reasons=["COHERENCE"]``.

The field name ``generic_filtered`` is kept unchanged for schema
compatibility, but it is a **low-evidence exclusion** list, not a pure
common-word list.  An entry may be a generic word (for example ``机器人``) or
a real company that never received company context in the corpus (for example
a zero-evidence name).  UI copy must say "低证据排除：可能为通用词，也可能是
语料中未获得公司上下文" and must not label the whole list as generic words.

A weak hit increments ``weak_document_count`` only, never ``document_count``.
Stock rows with ``document_count == 0`` are weak-only.  They never enter the
main ``items`` array; up to 20 of them are exposed separately in top-level
``weak_items`` (sorted by ``weak_document_count`` descending, then ``ts_code``
ascending) so the weak layer is visible without disturbing the confirmed
list.

Name table
----------
The pointer file ``<data_root>/../workspace/数据/data_layer_interface_current/
CURRENT_SELECTOR_READY_PANEL.txt`` names one parquet file on its first line.
Only ``trade_date``, ``ts_code``, ``name`` and ``tdx_industry_code`` are read.
Rows with a non-empty ``name`` are kept, the newest ``trade_date`` wins, one
row per ``ts_code`` is kept, spaces are removed from names, names shorter than
three characters are dropped, and brokers are removed: industry code
``T1002``, any name containing ``证券``, plus the fixed names
``申万宏源``/``国泰海通``/``中金公司``/``中信建投``/``东方财富`` (their
industry code is missing upstream).  The table is cached in process by
``(path, mtime_ns)`` under a lock and the DataFrame is released immediately
after the mapping is built.

Link corpus cache
-----------------
The corpus statistics are cached in process under a lock with the key
``(research_root, report_count, max(report.md mtime_ns), corpus_fingerprint,
name_table path, name_table mtime_ns)``.  The fingerprint is the SHA-256 of the
sorted ``relative_path:mtime_ns:size`` records of every deduplicated corpus report,
so deleting a non-newest report or restoring a report with a preserved mtime
invalidates the cache.  Cached report bodies are reused by later requests, so
a warm request does not reread the corpus.  Per-report match decisions are
additionally cached under the same corpus key plus the report mtime, so a warm
request only aggregates cached decisions and does not re-run name matching.
The fingerprint is returned as top-level ``corpus_fingerprint``.  A failed or
empty corpus sets ``corpus_cache_status`` to ``CANNOT_CONFIRM`` and the layer
degrades to code-only matching instead of raising.

If the pointer or parquet is unavailable the layer degrades explicitly:
``name_map_status`` becomes ``CANNOT_CONFIRM``, matching continues by stock
code only, and the reason is recorded in ``cannot_confirm``.

Every unexpected error is converted into a structured ``CANNOT_CONFIRM``
payload; this reader never raises and never surfaces an HTTP 500.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any, Iterator, Mapping

from infrastructure.owned_io import OwnedIOError, SafeRoot
from infrastructure.pdf_research_cards import (
    RESEARCH_ROOT_RELATIVE,
    read_machine_card_sources,
    read_machine_cards,
)

SCHEMA_VERSION = "v4.research.stock_clues.v1"
SAFETY = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
NAME_MAP_POINTER_RELATIVE = (
    "..",
    "workspace",
    "数据",
    "data_layer_interface_current",
    "CURRENT_SELECTOR_READY_PANEL.txt",
)
NAME_MAP_COLUMNS = ("trade_date", "ts_code", "name", "tdx_industry_code")
MAX_REPORT_BYTES = 512 * 1024
MAX_NAME_POINTER_BYTES = 64 * 1024
CORPUS_VERSION = "v4.research.stock_clues.link_corpus.v2"
SKIP_HEAD_CHARS = 300
DEFAULT_CLUE_LIMIT = 50
MAX_CLUE_LIMIT = 200
MAX_TITLES_PER_STOCK = 5
MAX_REASON_LIST = 50
MAX_GENERIC_FILTERED = 30
MAX_WEAK_ITEMS = 20
MIN_NAME_LENGTH = 3
BROKER_INDUSTRY_CODE = "T1002"
BROKER_NAME_MARKER = "证券"
BROKER_FIXED_NAMES = frozenset(
    {"申万宏源", "国泰海通", "中金公司", "中信建投", "东方财富"}
)
CONTEXT_WINDOW_CHARS = 15
CONTEXT_MARKERS = (
    "股份",
    "集团",
    "科技",
    "公司",
    "控股",
    "营收",
    "净利",
    "业绩",
    "标的",
    "龙头",
    "估值",
    "市值",
    "评级",
    "目标价",
    "产能",
    "订单",
    "客户",
    "证券代码",
)
LINK_MIN_SAMPLE = 3
LINK_GENERIC_MAX = 0.2
LINK_CONFIRM_MIN = 0.5
CONFIRM_REASON_ORDER = ("CODE", "CONTEXT", "COHERENCE")
STOCK_CODE_PATTERN = re.compile(r"\b\d{6}\.(?:SZ|SH|BJ)\b|\b\d{5}\.HK\b")
PARAGRAPH_PATTERN = re.compile(r"\n\s*\n")
MAX_NAME_MAP_CACHE_ENTRIES = 4
MAX_LINK_CORPUS_CACHE_ENTRIES = 2
MAX_CARD_MATCH_CACHE_ENTRIES = 2048


class StockCluesError(ValueError):
    """A stable, safe-to-record stock-clue read error code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_name_map_lock = threading.Lock()
_name_map_cache: dict[tuple[str, int], dict[str, Any]] = {}
_link_corpus_lock = threading.Lock()
_link_corpus_cache: dict[
    tuple[str, str, str, int, int, str, str, int], dict[str, Any]
] = {}
_card_match_lock = threading.Lock()
_card_match_cache: dict[
    tuple[
        str,
        int,
        tuple[str, str, str, int, int, str, str, int] | None,
    ],
    tuple[Any, ...],
] = {}


def _effective_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_CLUE_LIMIT
    return max(1, min(value, MAX_CLUE_LIMIT))


def _base(
    status: str,
    research_date: str,
    *,
    clue_limit: int,
    cannot_confirm: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "research_date": research_date,
        "card_count": 0,
        "scanned_card_count": 0,
        "skipped_card_count": 0,
        "stock_count": 0,
        "confirmed_stock_count": 0,
        "weak_only_stock_count": 0,
        "corpus_report_count": 0,
        "corpus_fingerprint": "",
        "corpus_cutoff_date": research_date,
        "corpus_version": CORPUS_VERSION,
        "corpus_cache_status": "CANNOT_CONFIRM",
        "generic_filtered": [],
        "weak_items": [],
        "clue_limit": clue_limit,
        "name_map_status": "CANNOT_CONFIRM",
        "name_map_path": "",
        "name_map_trade_date": "",
        "truncated_report_count": 0,
        "cannot_confirm": sorted(set(cannot_confirm or []))[:MAX_REASON_LIST],
        "items": [],
        **SAFETY,
    }


def _name_map_failure(
    *,
    reason: str,
    path: str = "",
    trade_date: str = "",
) -> dict[str, Any]:
    return {
        "status": "CANNOT_CONFIRM",
        "mapping": {},
        "code_to_name": {},
        "by_first": {},
        "first_pattern": None,
        "trade_date": trade_date,
        "path": path,
        "mtime_ns": 0,
        "reasons": [reason],
    }


def _build_name_map(parquet_path: Path) -> tuple[dict[str, str], str]:
    """Build the broker-filtered ``name -> ts_code`` map from four columns."""
    import pandas as pd  # local import keeps the API import path light

    safe_parent = SafeRoot(parquet_path.parent.resolve(strict=True))
    with safe_parent.parent(parquet_path.name) as (parent_fd, name):
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OwnedIOError("NAME_MAP_NOT_REGULAR")
        with os.fdopen(descriptor, "rb") as handle:
            frame = pd.read_parquet(handle, columns=list(NAME_MAP_COLUMNS))
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    try:
        named = frame[frame["name"].notna() & frame["trade_date"].notna()]
        if named.empty:
            raise ValueError("NAME_MAP_EMPTY")
        trade_dates = named["trade_date"].astype(str)
        trade_date = str(trade_dates.max())
        rows = named[trade_dates == trade_date].drop_duplicates("ts_code")
        rows = rows.sort_values("ts_code", kind="stable")
        names = rows["name"].astype(str).str.replace(" ", "", regex=False).str.strip()
        industry = rows["tdx_industry_code"].fillna("").astype(str)
        keep = names.str.len() >= MIN_NAME_LENGTH
        keep &= industry != BROKER_INDUSTRY_CODE
        keep &= ~names.str.contains(BROKER_NAME_MARKER, regex=False)
        keep &= ~names.isin(BROKER_FIXED_NAMES)
        mapping: dict[str, str] = {}
        for ts_code, name in zip(rows.loc[keep, "ts_code"].astype(str), names[keep]):
            code = ts_code.strip()
            if code and name and name not in mapping:
                mapping[name] = code
    finally:
        del frame
    if not mapping:
        raise ValueError("NAME_MAP_EMPTY")
    return mapping, trade_date


def _build_name_index(
    mapping: Mapping[str, str],
) -> tuple[dict[str, tuple[tuple[str, str], ...]], re.Pattern[str] | None]:
    """Index names by first character so each report body is scanned once."""
    by_first: dict[str, list[tuple[str, str]]] = {}
    for name in sorted(mapping):
        by_first.setdefault(name[0], []).append((name, mapping[name]))
    if not by_first:
        return {}, None
    first_chars = "".join(re.escape(char) for char in sorted(by_first))
    return (
        {char: tuple(entries) for char, entries in by_first.items()},
        re.compile(f"[{first_chars}]"),
    )


def _load_name_map(data_root: Path) -> dict[str, Any]:
    """Resolve the pointer, load/cached the parquet, and never raise."""
    try:
        resolved_data_root = Path(data_root).expanduser().resolve(strict=True)
        pointer_root = resolved_data_root.parent.resolve(strict=True)
        pointer_path = resolved_data_root.joinpath(*NAME_MAP_POINTER_RELATIVE).resolve(strict=False)
        pointer_relative = Path(*NAME_MAP_POINTER_RELATIVE[1:]).as_posix()
        pointer_reader = SafeRoot(pointer_root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return _name_map_failure(reason="NAME_MAP_POINTER_UNAVAILABLE")
    try:
        pointer_text = pointer_reader.read_bytes(
            pointer_relative, max_bytes=MAX_NAME_POINTER_BYTES
        ).decode("utf-8", errors="replace")
    except (OSError, OwnedIOError, UnicodeError, ValueError):
        return _name_map_failure(reason="NAME_MAP_POINTER_UNAVAILABLE", path=str(pointer_path))
    lines = [line.strip() for line in pointer_text.splitlines() if line.strip()]
    if not lines:
        return _name_map_failure(reason="NAME_MAP_POINTER_INVALID", path=str(pointer_path))
    parquet_path = Path(lines[0]).expanduser()
    if not parquet_path.is_absolute():
        parquet_path = pointer_path.parent / parquet_path
    try:
        parquet_path = parquet_path.resolve(strict=True)
        parquet_parent = SafeRoot(parquet_path.parent)
        with parquet_parent.parent(parquet_path.name) as (parent_fd, name):
            parquet_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(parquet_stat.st_mode):
            raise OwnedIOError("NAME_MAP_NOT_REGULAR")
        mtime_ns = parquet_stat.st_mtime_ns
    except (OSError, OwnedIOError, RuntimeError, ValueError):
        return _name_map_failure(reason="NAME_MAP_UNAVAILABLE", path=str(parquet_path))

    key = (str(parquet_path), mtime_ns)
    with _name_map_lock:
        cached = _name_map_cache.get(key)
        if cached is None:
            try:
                mapping, trade_date = _build_name_map(parquet_path)
            except ValueError as error:
                code = str(error)
                reason = code if code.startswith("NAME_MAP_") else "NAME_MAP_EMPTY"
                return _name_map_failure(reason=reason, path=str(parquet_path))
            except Exception as error:  # noqa: BLE001 - degrade, never raise
                return _name_map_failure(
                    reason=f"NAME_MAP_READ_FAILED:{type(error).__name__}",
                    path=str(parquet_path),
                )
            by_first, first_pattern = _build_name_index(mapping)
            code_to_name = {code: name for name, code in mapping.items()}
            cached = {
                "status": "READY",
                "mapping": mapping,
                "code_to_name": code_to_name,
                "by_first": by_first,
                "first_pattern": first_pattern,
                "trade_date": trade_date,
                "path": str(parquet_path),
                "mtime_ns": mtime_ns,
                "reasons": [],
            }
            if len(_name_map_cache) >= MAX_NAME_MAP_CACHE_ENTRIES:
                _name_map_cache.pop(next(iter(_name_map_cache)))
            _name_map_cache[key] = cached
        return cached


def _read_owned_report(root: SafeRoot, relative: str) -> tuple[str | None, bool, str | None]:
    """Read a bounded report prefix through the descriptor-anchored root."""
    try:
        with root.parent(relative) as (parent_fd, name):
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode):
                    return None, False, "REPORT_PATH_REJECTED"
                raw = bytearray()
                while len(raw) <= MAX_REPORT_BYTES:
                    try:
                        chunk = os.read(descriptor, min(65536, MAX_REPORT_BYTES + 1 - len(raw)))
                    except InterruptedError:
                        continue
                    if not chunk:
                        break
                    raw.extend(chunk)
                after = os.fstat(descriptor)
                if (before.st_dev, before.st_ino, before.st_size) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                ):
                    return None, False, "REPORT_CHANGED_DURING_READ"
            finally:
                os.close(descriptor)
    except (OSError, OwnedIOError, ValueError):
        return None, False, "REPORT_UNREADABLE"
    truncated = len(raw) > MAX_REPORT_BYTES
    if truncated:
        raw = raw[:MAX_REPORT_BYTES]
    report_text = bytes(raw).decode("utf-8", errors="replace")
    if report_text.startswith(chr(0xFEFF)):
        report_text = report_text[1:]
    return report_text, truncated, None


def _owned_report_relative_path(raw: Any) -> str | None:
    """Accept only report paths relative to the existing research root."""
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        return None
    if PureWindowsPath(raw).drive or raw.startswith("/"):
        return None
    parts = raw.split("/")
    if parts[0] != "batches" or any(part in {"", ".", ".."} for part in parts):
        return None
    return f"{RESEARCH_ROOT_RELATIVE}/{raw}"


def _discover_corpus_reports(
    data_root: Path,
    cutoff_date: str,
) -> tuple[list[dict[str, Any]], int, str, list[str]]:
    """List deduplicated reports with source dates no later than the cutoff."""
    source_projection = read_machine_card_sources(data_root, cutoff_date)
    status = str(source_projection.get("status") or "CANNOT_CONFIRM")
    reasons = [str(item) for item in source_projection.get("cannot_confirm") or []]
    if status != "READY":
        return [], 0, "", [f"LINK_CORPUS_SOURCE_{status}", *reasons]
    if int(source_projection.get("cannot_confirm_count") or 0) != 0:
        return [], 0, "", ["LINK_CORPUS_SOURCE_INCOMPLETE", *reasons]
    sources = source_projection.get("items")
    if not isinstance(sources, list) or not sources:
        return [], 0, "", ["LINK_CORPUS_EMPTY"]
    try:
        max_mtime_ns = max(int(item["report_mtime_ns"]) for item in sources)
        records = sorted(
            f"{item['report_path']}:{item['research_date']}:{item['status']}:"
            f"{item['report_mtime_ns']}:{item['report_size']}"
            for item in sources
        )
    except (KeyError, TypeError, ValueError):
        return [], 0, "", ["LINK_CORPUS_SOURCE_INVALID"]
    fingerprint_input = "\n".join((CORPUS_VERSION, cutoff_date, *records))
    fingerprint = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()
    return sources, max_mtime_ns, fingerprint, []


def _link_corpus_failure(reasons: str | list[str], cutoff_date: str) -> dict[str, Any]:
    reason_list = [reasons] if isinstance(reasons, str) else reasons
    return {
        "status": "CANNOT_CONFIRM",
        "cache_status": "CANNOT_CONFIRM",
        "corpus_key": None,
        "corpus_fingerprint": "",
        "corpus_cutoff_date": cutoff_date,
        "corpus_version": CORPUS_VERSION,
        "report_count": 0,
        "report_mtimes": {},
        "stats": {},
        "bodies": {},
        "truncations": {},
        "reasons": reason_list,
    }


def _build_link_corpus(
    sources: list[dict[str, Any]],
    name_map: Mapping[str, Any],
    data_root: Path,
    *,
    cutoff_date: str,
    fingerprint: str,
) -> dict[str, Any]:
    """Read the bounded, cutoff-bound corpus and build name priors."""
    mapping = name_map["mapping"]
    by_first = name_map["by_first"]
    first_pattern = name_map["first_pattern"]
    totals = {name: 0 for name in mapping}
    evidenced = {name: 0 for name in mapping}
    bodies: dict[str, str] = {}
    truncations: dict[str, bool] = {}
    report_mtimes: dict[str, int] = {}
    secure_root = SafeRoot(Path(data_root).expanduser().resolve(strict=True))
    for source in sources:
        relative = str(source.get("report_path") or "")
        owned_relative = _owned_report_relative_path(relative)
        if owned_relative is None:
            return _link_corpus_failure("LINK_CORPUS_REPORT_PATH_REJECTED", cutoff_date)
        text, truncated, error_code = _read_owned_report(secure_root, owned_relative)
        if error_code is not None or text is None:
            return _link_corpus_failure("LINK_CORPUS_REPORT_UNREADABLE", cutoff_date)
        bodies[relative] = text
        truncations[relative] = truncated
        report_mtimes[relative] = int(source["report_mtime_ns"])
        body = text[SKIP_HEAD_CHARS:]
        codes = {match.group() for match in STOCK_CODE_PATTERN.finditer(body)}
        for name, code, start, end in _iter_name_hits(body, by_first, first_pattern):
            totals[name] += 1
            if code in codes or _has_context_marker(body, start, end):
                evidenced[name] += 1
    stats = {
        name: {
            "total": totals[name],
            "evidenced": evidenced[name],
            "link_probability": _link_probability(totals[name], evidenced[name]),
        }
        for name in mapping
    }
    return {
        "status": "READY",
        "cache_status": "BUILT",
        "corpus_key": None,
        "corpus_fingerprint": fingerprint,
        "corpus_cutoff_date": cutoff_date,
        "corpus_version": CORPUS_VERSION,
        "report_count": len(sources),
        "report_mtimes": report_mtimes,
        "stats": stats,
        "bodies": bodies,
        "truncations": truncations,
        "reasons": [],
    }


def _load_link_corpus(
    data_root: Path,
    name_map: Mapping[str, Any],
    cutoff_date: str,
) -> dict[str, Any]:
    """Load or build the process-wide prior for one exact date cutoff."""
    if name_map.get("status") != "READY":
        return _link_corpus_failure("LINK_CORPUS_NAME_MAP_UNAVAILABLE", cutoff_date)
    try:
        sources, max_mtime_ns, fingerprint, reasons = _discover_corpus_reports(
            data_root, cutoff_date
        )
    except Exception as error:  # noqa: BLE001 - degrade, never raise
        return _link_corpus_failure(
            f"LINK_CORPUS_DISCOVERY_FAILED:{type(error).__name__}", cutoff_date
        )
    if reasons:
        return _link_corpus_failure(reasons, cutoff_date)
    if not sources:
        return _link_corpus_failure("LINK_CORPUS_EMPTY", cutoff_date)
    root = Path(data_root).expanduser().resolve(strict=True)
    key = (
        str(root / RESEARCH_ROOT_RELATIVE),
        cutoff_date,
        CORPUS_VERSION,
        len(sources),
        max_mtime_ns,
        fingerprint,
        str(name_map.get("path") or ""),
        int(name_map.get("mtime_ns") or 0),
    )
    with _link_corpus_lock:
        cached = _link_corpus_cache.get(key)
        if cached is not None:
            return {**cached, "cache_status": "HIT"}
        try:
            built = _build_link_corpus(
                sources,
                name_map,
                root,
                cutoff_date=cutoff_date,
                fingerprint=fingerprint,
            )
        except Exception as error:  # noqa: BLE001 - degrade, never raise
            return _link_corpus_failure(
                f"LINK_CORPUS_STATS_FAILED:{type(error).__name__}", cutoff_date
            )
        if built["status"] != "READY":
            return built
        built["corpus_key"] = key
        if len(_link_corpus_cache) >= MAX_LINK_CORPUS_CACHE_ENTRIES:
            _link_corpus_cache.pop(next(iter(_link_corpus_cache)))
        _link_corpus_cache[key] = built
        return built


def _has_context_marker(body: str, start: int, end: int) -> bool:
    """Check the fixed company/stock marker set within +-15 characters."""
    window = body[
        max(0, start - CONTEXT_WINDOW_CHARS) : end + CONTEXT_WINDOW_CHARS
    ]
    return any(marker in window for marker in CONTEXT_MARKERS)


def _iter_name_hits(
    body: str,
    by_first: Mapping[str, tuple[tuple[str, str], ...]],
    first_pattern: re.Pattern[str] | None,
) -> Iterator[tuple[str, str, int, int]]:
    """Yield ``(name, ts_code, start, end)`` for every name occurrence."""
    if first_pattern is None:
        return
    for match in first_pattern.finditer(body):
        for name, code in by_first.get(match.group(), ()):
            if body.startswith(name, match.start()):
                yield name, code, match.start(), match.start() + len(name)


def _link_probability(total: int, evidenced: int) -> float | None:
    """Return the raw evidenced/total ratio, or ``None`` for a zero sample."""
    if total <= 0:
        return None
    return evidenced / total


def _match_paragraph(
    paragraph: str,
    name_map: Mapping[str, Any],
    link_stats: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[
    dict[str, set[str]],
    set[str],
    dict[str, dict[str, Any]],
    set[str],
    set[str],
]:
    """Apply code/name/prior/coherence rules to one report paragraph.

    Returns ``(confirmed reasons, weak codes, generic records, named codes,
    coded codes)``.  ``confirmed`` maps each confirmed code to the reasons
    triggered inside this paragraph.
    """
    coded = {match.group() for match in STOCK_CODE_PATTERN.finditer(paragraph)}
    confirmed: dict[str, set[str]] = {code: {"CODE"} for code in coded}
    named: dict[str, dict[str, Any]] = {}
    if link_stats is not None:
        for name, code, _start, _end in _iter_name_hits(
            paragraph, name_map["by_first"], name_map["first_pattern"]
        ):
            if code not in named:
                stats = link_stats.get(name)
                named[code] = {
                    "name": name,
                    "ts_code": code,
                    "total": int(stats["total"]) if stats is not None else 0,
                    "link_probability": (
                        stats["link_probability"] if stats is not None else None
                    ),
                }
    weak: set[str] = set()
    generic: dict[str, dict[str, Any]] = {}
    if link_stats is not None:
        for code, record in named.items():
            total = int(record["total"])
            link_probability = record["link_probability"]
            if code in confirmed:
                # CODE is already a confirmation.  A qualifying name prior adds
                # CONTEXT evidence but can never downgrade the code hit.
                if (
                    total >= LINK_MIN_SAMPLE
                    and link_probability is not None
                    and link_probability >= LINK_CONFIRM_MIN
                ):
                    confirmed[code].add("CONTEXT")
                continue
            if total < LINK_MIN_SAMPLE:
                weak.add(code)
            elif link_probability is not None and link_probability <= LINK_GENERIC_MAX:
                generic[code] = record
            elif link_probability is not None and link_probability < LINK_CONFIRM_MIN:
                weak.add(code)
            else:
                confirmed[code] = {"CONTEXT"}
    if len(confirmed) >= 2 and weak:
        for code in weak:
            confirmed[code] = {"COHERENCE"}
        weak = set()
    return confirmed, weak, generic, set(named), coded


def _scan_card(
    body: str,
    name_map: Mapping[str, Any],
    link_stats: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[
    dict[str, set[str]],
    set[str],
    dict[str, dict[str, Any]],
    set[str],
    set[str],
]:
    """Aggregate paragraph-level matches into one card-level decision."""
    card_confirmed: dict[str, set[str]] = {}
    card_weak: set[str] = set()
    card_generic: dict[str, dict[str, Any]] = {}
    card_named: set[str] = set()
    card_coded: set[str] = set()
    for paragraph in PARAGRAPH_PATTERN.split(body):
        if not paragraph.strip():
            continue
        confirmed, weak, generic, named, coded = _match_paragraph(
            paragraph, name_map, link_stats
        )
        card_named |= named
        card_coded |= coded
        for code, reason_set in confirmed.items():
            card_confirmed.setdefault(code, set()).update(reason_set)
        card_weak |= weak
        for code, record in generic.items():
            card_generic.setdefault(code, record)
    card_weak -= set(card_confirmed)
    for code in list(card_generic):
        if code in card_confirmed or code in card_weak:
            card_generic.pop(code, None)
    return card_confirmed, card_weak, card_generic, card_named, card_coded


def _matched_by(methods: set[str]) -> str:
    if methods >= {"NAME", "CODE"}:
        return "BOTH"
    return "NAME" if "NAME" in methods else "CODE"


def read_stock_clues(
    data_root: Path,
    research_date: str,
    *,
    limit: int = DEFAULT_CLUE_LIMIT,
) -> dict[str, Any]:
    """Aggregate stock clues for one exact source date; always returns a dict.

    Sorting is ``document_count`` descending, then ``weak_document_count``
    descending, then ``ts_code`` ascending.  The main ``items`` array contains
    confirmed rows only; it is capped at ``limit`` (clamped to 1..200).
    Weak-only rows are kept out of ``items`` and exposed separately in
    ``weak_items`` (at most 20, sorted by ``weak_document_count`` descending
    then ``ts_code`` ascending).  ``stock_count`` counts every distinct
    retained target before the limit; ``confirmed_stock_count`` counts rows
    with ``document_count >= 1`` and ``weak_only_stock_count`` the rest.
    Low-evidence exclusions are reported separately in ``generic_filtered``
    and never create a row.
    """
    selected = research_date if isinstance(research_date, str) else ""
    clue_limit = _effective_limit(limit)
    try:
        cards = read_machine_cards(data_root, research_date, limit=None)
        if cards.get("status") != "READY" and cards.get("status") != "READY_EMPTY":
            return _base(
                str(cards.get("status") or "CANNOT_CONFIRM"),
                selected,
                clue_limit=clue_limit,
                cannot_confirm=[
                    f"MACHINE_CARDS:{reason}"
                    for reason in (cards.get("cannot_confirm") or [])
                ],
            )
        card_items = cards.get("items") if isinstance(cards.get("items"), list) else []
        if not card_items:
            return _base("READY_EMPTY", selected, clue_limit=clue_limit)

        root = Path(data_root).expanduser().resolve(strict=True)
        secure_root = SafeRoot(root)
        name_map = _load_name_map(root)
        if (
            name_map.get("status") == "READY"
            and str(name_map.get("trade_date") or "") > selected
        ):
            name_map = _name_map_failure(
                reason="NAME_MAP_AFTER_RESEARCH_DATE",
                path=str(name_map.get("path") or ""),
                trade_date=str(name_map.get("trade_date") or ""),
            )
        corpus = _load_link_corpus(root, name_map, selected)
        corpus_ready = corpus["status"] == "READY"
        link_stats = corpus["stats"] if corpus_ready else None
        corpus_bodies = corpus["bodies"] if corpus_ready else {}
        corpus_truncations = corpus["truncations"] if corpus_ready else {}
        corpus_report_mtimes = corpus.get("report_mtimes") or {}
        reasons: set[str] = set(name_map["reasons"])
        reasons |= set(corpus.get("reasons") or [])
        reasons |= {
            f"MACHINE_CARDS:{reason}" for reason in (cards.get("cannot_confirm") or [])
        }

        entries: dict[str, dict[str, Any]] = {}
        generic_candidates: dict[str, dict[str, Any]] = {}
        scanned = 0
        skipped = 0
        truncated_count = 0
        seen_documents: set[str] = set()
        for card in card_items:
            if not isinstance(card, Mapping):
                reasons.add("CARD_IDENTITY_INVALID")
                skipped += 1
                continue
            document_id = card.get("document_id")
            if not isinstance(document_id, str) or not document_id:
                reasons.add("CARD_IDENTITY_INVALID")
                skipped += 1
                continue
            if document_id in seen_documents:
                continue
            seen_documents.add(document_id)
            report_ref = card.get("report")
            relative = report_ref.get("path") if isinstance(report_ref, Mapping) else None
            if not isinstance(relative, str) or not relative.strip():
                reasons.add("REPORT_PATH_REJECTED")
                skipped += 1
                continue
            owned_relative = _owned_report_relative_path(relative)
            if owned_relative is None:
                reasons.add("REPORT_PATH_REJECTED")
                skipped += 1
                continue
            cache_key = relative
            match_key = None
            cached_match = None
            if (
                corpus_ready
                and name_map["status"] == "READY"
                and corpus.get("corpus_key") is not None
            ):
                report_mtime_ns = corpus_report_mtimes.get(relative)
                if report_mtime_ns is not None:
                    match_key = (cache_key, report_mtime_ns, corpus["corpus_key"])
                    with _card_match_lock:
                        cached_match = _card_match_cache.get(match_key)
            if cached_match is not None:
                confirmed, weak, generic, named, coded, truncated = cached_match
            else:
                if cache_key in corpus_bodies:
                    text = corpus_bodies[cache_key]
                    truncated = bool(corpus_truncations.get(cache_key, False))
                else:
                    text, truncated, error_code = _read_owned_report(secure_root, owned_relative)
                    if error_code is not None or text is None:
                        if error_code:
                            reasons.add(error_code)
                        skipped += 1
                        continue
                confirmed, weak, generic, named, coded = _scan_card(
                    text[SKIP_HEAD_CHARS:], name_map, link_stats
                )
                if match_key is not None:
                    with _card_match_lock:
                        if len(_card_match_cache) >= MAX_CARD_MATCH_CACHE_ENTRIES:
                            _card_match_cache.pop(next(iter(_card_match_cache)))
                        _card_match_cache[match_key] = (
                            confirmed,
                            weak,
                            generic,
                            named,
                            coded,
                            truncated,
                        )
            scanned += 1
            if truncated:
                truncated_count += 1
                reasons.add("REPORT_TRUNCATED")
            card_date = card.get("research_date")
            card_date = card_date if isinstance(card_date, str) and card_date else selected
            title = card.get("title")
            title = str(title).strip()[:200] if title is not None else ""
            for ts_code, reason_set in confirmed.items():
                entry = entries.get(ts_code)
                if entry is None:
                    entry = {
                        "confirmed": 0,
                        "weak": 0,
                        "methods": set(),
                        "reasons": [],
                        "titles": [],
                        "dates": set(),
                    }
                    entries[ts_code] = entry
                if ts_code in named:
                    entry["methods"].add("NAME")
                if ts_code in coded:
                    entry["methods"].add("CODE")
                entry["dates"].add(card_date)
                entry["confirmed"] += 1
                for reason in CONFIRM_REASON_ORDER:
                    if reason in reason_set and reason not in entry["reasons"]:
                        entry["reasons"].append(reason)
                if (
                    title
                    and title not in entry["titles"]
                    and len(entry["titles"]) < MAX_TITLES_PER_STOCK
                ):
                    entry["titles"].append(title)
            for ts_code in weak:
                entry = entries.get(ts_code)
                if entry is None:
                    entry = {
                        "confirmed": 0,
                        "weak": 0,
                        "methods": set(),
                        "reasons": [],
                        "titles": [],
                        "dates": set(),
                    }
                    entries[ts_code] = entry
                entry["methods"].add("NAME")
                entry["dates"].add(card_date)
                entry["weak"] += 1
            for ts_code, record in generic.items():
                generic_candidates.setdefault(ts_code, record)

        if scanned == 0 and skipped > 0:
            return _base(
                "CANNOT_CONFIRM", selected, clue_limit=clue_limit, cannot_confirm=sorted(reasons)
            )

        confirmed_codes = {
            ts_code for ts_code, entry in entries.items() if entry["confirmed"] > 0
        }
        generic_rows = [
            record
            for ts_code, record in generic_candidates.items()
            if ts_code not in confirmed_codes
        ]
        generic_rows.sort(
            key=lambda record: (
                -int(record["total"]),
                str(record["name"]),
                str(record["ts_code"]),
            )
        )

        rows: list[dict[str, Any]] = []
        for ts_code, entry in entries.items():
            name = name_map["code_to_name"].get(ts_code)
            link_probability = None
            if name is not None and link_stats is not None:
                stats = link_stats.get(name)
                if stats is not None:
                    link_probability = stats["link_probability"]
            rows.append(
                {
                    "ts_code": ts_code,
                    "name": name,
                    "document_count": entry["confirmed"],
                    "weak_document_count": entry["weak"],
                    "link_probability": link_probability,
                    "confirm_reasons": list(entry["reasons"]),
                    "document_titles": list(entry["titles"]),
                    "matched_by": _matched_by(entry["methods"]),
                    "first_seen_date": min(entry["dates"]),
                    "last_seen_date": max(entry["dates"]),
                }
            )
        rows.sort(
            key=lambda row: (
                -row["document_count"],
                -row["weak_document_count"],
                row["ts_code"],
            )
        )
        confirmed_rows = [row for row in rows if row["document_count"] > 0]
        weak_rows = [
            row
            for row in rows
            if row["document_count"] == 0 and row["weak_document_count"] > 0
        ]
        weak_rows.sort(key=lambda row: (-row["weak_document_count"], row["ts_code"]))
        weak_items = [
            {
                "name": row["name"],
                "ts_code": row["ts_code"],
                "weak_document_count": row["weak_document_count"],
                "link_probability": row["link_probability"],
            }
            for row in weak_rows[:MAX_WEAK_ITEMS]
        ]
        confirmed_stock_count = len(confirmed_rows)
        weak_only_stock_count = len(weak_rows)
        if confirmed_stock_count:
            status = "READY"
        elif (
            name_map.get("status") != "READY"
            or corpus.get("status") != "READY"
            or skipped > 0
        ):
            status = "CANNOT_CONFIRM"
        else:
            status = "READY_EMPTY"
        return {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "research_date": selected,
            "card_count": len(card_items),
            "scanned_card_count": scanned,
            "skipped_card_count": skipped,
            "stock_count": len(rows),
            "confirmed_stock_count": confirmed_stock_count,
            "weak_only_stock_count": weak_only_stock_count,
            "corpus_report_count": int(corpus.get("report_count") or 0),
            "corpus_fingerprint": str(corpus.get("corpus_fingerprint") or ""),
            "corpus_cutoff_date": str(corpus.get("corpus_cutoff_date") or selected),
            "corpus_version": CORPUS_VERSION,
            "corpus_cache_status": str(corpus.get("cache_status") or "CANNOT_CONFIRM"),
            "generic_filtered": generic_rows[:MAX_GENERIC_FILTERED],
            "weak_items": weak_items,
            "clue_limit": clue_limit,
            "name_map_status": name_map["status"],
            "name_map_path": name_map["path"],
            "name_map_trade_date": name_map["trade_date"],
            "truncated_report_count": truncated_count,
            "cannot_confirm": sorted(reasons)[:MAX_REASON_LIST],
            "items": confirmed_rows[:clue_limit],
            **SAFETY,
        }
    except StockCluesError as error:
        return _base("CANNOT_CONFIRM", selected, clue_limit=clue_limit, cannot_confirm=[error.code])
    except Exception as error:  # fail closed: never surface a reader exception as 500
        return _base(
            "CANNOT_CONFIRM",
            selected,
            clue_limit=clue_limit,
            cannot_confirm=[f"STOCK_CLUES_READ_FAILED:{type(error).__name__}"],
        )


__all__ = [
    "SCHEMA_VERSION",
    "StockCluesError",
    "read_stock_clues",
]
