"""Collect bounded, paginated ZSXQ deltas into V3.5-owned hourly storage.

The official OAuth CLI is read-only.  Shared research source code remains
untouched; this adapter only reuses its deterministic topic analyser against a
V3.5-owned, point-in-time filtered topic set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from infrastructure.data_store import NativeDataStore
from infrastructure.isolated_package_loader import load_isolated_package_module
from infrastructure.owned_path import resolve_owned_path


SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_GROUPS = (
    ("15555851111822", "小牛研报纪要"),
    ("51111814525844", "乐晴行业观察"),
)
DEFAULT_CLI = Path(
    "/Users/lexi/Documents/Codex/2026-08-13/v35-019ff682/"
    "shared-research-runtime/npm/node_modules/.bin/zsxq-cli"
)
DEFAULT_REFETCH_ROOT = Path(
    __file__
).resolve().parents[1] / "upstreams"
DEFAULT_SELECTOR_PANEL = Path(
    "/Users/lexi/Library/Application Support/com.lexi.research.shared/"
    "security/a_share_security_master_latest.parquet"
)
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
Runner = Callable[..., subprocess.CompletedProcess[str]]
Analyzer = Callable[[dict[str, Any], Path, Path], dict[str, Any]]


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _topic_key(group_id: str, row: Mapping[str, Any]) -> str:
    topic_id = str(row.get("topic_id") or row.get("id") or "").strip()
    if topic_id:
        return f"{group_id}:{topic_id}"
    body = json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
    return f"{group_id}:sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def collect_paginated_topics(
    *,
    cli: Path,
    groups: Iterable[tuple[str, str]],
    as_of: datetime,
    since: datetime,
    page_limit: int = 30,
    max_pages: int = 20,
    process_runner: Runner = subprocess.run,
) -> dict[str, Any]:
    if as_of.tzinfo is None or since.tzinfo is None:
        raise ValueError("ZSXQ pagination boundaries must be timezone-aware")
    if since > as_of:
        raise ValueError("ZSXQ pagination lower boundary exceeds cutoff")
    limit = max(1, min(30, int(page_limit)))
    page_cap = max(1, int(max_pages))
    collected: dict[str, dict[str, Any]] = {}
    group_results: list[dict[str, Any]] = []
    bounded_has_more = False
    total_pages = 0
    for group_id, group_name in groups:
        cursor = ""
        pages = 0
        group_keys: set[str] = set()
        source_has_more = False
        reached_since = False
        while pages < page_cap:
            command = [
                str(cli),
                "group",
                "+topics",
                "--group-id",
                group_id,
                "--limit",
                str(limit),
                "--json",
            ]
            if cursor:
                command.extend(["--end-time", cursor])
            completed = process_runner(
                command,
                timeout=30,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"ZSXQ_CLI_GROUP_FAILED:{group_id}:{(completed.stderr or '')[-300:]}"
                )
            try:
                payload = json.loads((completed.stdout or "").lstrip("\ufeff"))
            except json.JSONDecodeError as error:
                raise RuntimeError(f"ZSXQ_CLI_JSON_INVALID:{group_id}") from error
            rows = payload.get("topics_brief") or payload.get("topics") or []
            if not isinstance(rows, list):
                raise RuntimeError(f"ZSXQ_CLI_ROWS_INVALID:{group_id}")
            pages += 1
            total_pages += 1
            page_times: list[tuple[datetime, str]] = []
            before_count = len(group_keys)
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                row = dict(raw)
                raw_time = str(row.get("create_time") or "")
                created_at = _parse_time(raw_time)
                if created_at is None:
                    continue
                page_times.append((created_at, raw_time))
                if created_at > as_of:
                    continue
                if created_at < since:
                    reached_since = True
                    continue
                key = _topic_key(group_id, row)
                if key in collected:
                    continue
                row["group"] = {"group_id": group_id, "name": group_name}
                collected[key] = row
                group_keys.add(key)
            source_has_more = bool(payload.get("has_more"))
            if not rows or not source_has_more or reached_since:
                break
            if not page_times:
                break
            next_cursor = min(page_times, key=lambda item: item[0])[1]
            if not next_cursor or next_cursor == cursor:
                break
            if len(group_keys) == before_count and cursor:
                break
            cursor = next_cursor
        if source_has_more and not reached_since and pages >= page_cap:
            bounded_has_more = True
        group_results.append(
            {
                "group_id": group_id,
                "group_name": group_name,
                "page_count": pages,
                "deduped_count": len(group_keys),
                "source_has_more": source_has_more,
                "reached_since": reached_since,
            }
        )
    topics = sorted(
        collected.values(),
        key=lambda row: str(row.get("create_time") or ""),
        reverse=True,
    )
    return {
        "topics": topics,
        "group_results": group_results,
        "page_count": total_pages,
        "bounded_has_more": bounded_has_more,
    }


def _default_analyzer(
    recent: dict[str, Any], selector_panel: Path, refetch_root: Path
) -> dict[str, Any]:
    root = Path(refetch_root).resolve()
    expected_root = Path(__file__).resolve().parents[1] / "upstreams"
    if root != expected_root:
        raise ValueError(
            "V4 analyzer root must be the canonical upstreams package"
        )
    v3 = load_isolated_package_module(
        root,
        package_directory="shared_research",
        module_leaf="v3_zsxq_adapter",
        namespace_prefix="v35_shared_research_adapter",
    )

    if not selector_panel.is_file():
        raise FileNotFoundError(f"Mac selector panel missing: {selector_panel}")
    with _selector_environment(selector_panel):
        return dict(v3.analyze_recent_topics(recent))


@contextmanager
def _selector_environment(selector_panel: Path):
    """Bind the analyzer to one explicit selector panel for this call."""

    key = "V3_SHARED_SELECTOR_PANEL"
    previous = os.environ.get(key)
    os.environ[key] = str(Path(selector_panel).expanduser().resolve())
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _previous_success_time(data_root: Path, trade_date: str, slot: str) -> datetime | None:
    root = resolve_owned_path(
        data_root, f"research_module/runtime_outputs/zsxq_hourly/{trade_date}"
    )
    if not root.is_dir():
        return None
    candidates: list[datetime] = []
    for path in root.glob("*/v35_zsxq_*_status_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        raw_slot = str(payload.get("slot") or path.parent.name)
        if not raw_slot.isdigit() or int(raw_slot) >= int(slot):
            continue
        if payload.get("fetch_ok") is not True:
            continue
        parsed = _parse_time(payload.get("fetched_at"))
        if parsed is not None:
            candidates.append(parsed)
    return max(candidates) if candidates else None



def _acquisition_clock() -> str:
    # Always measured here, never source status/event_time or caller's historical now.
    return datetime.now(SHANGHAI).isoformat(timespec="microseconds")


def _require_acquisition_root(data_root: Path) -> None:
    root = Path(data_root).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("V5_ACQUISITION_ROOT_SYMLINK")
    marker = root / ".v5-archive-acquisition"
    fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if os.read(fd, 128) != b"v5.archive-acquisition.v2\n":
            raise ValueError("V5_ACQUISITION_PRIVATE_ROOT_REQUIRED")
    finally:
        os.close(fd)


def _publish_acquisition_receipt(store, output_relative, run_id, started_at,
                                 retrieved_at, expected_payloads, bounded_has_more, pages):
    # NativeDataStore/SafeRoot writes fsync the file and containing directory.
    # Bind exact persisted bytes AND compare them with this invocation's values.
    evidence = {}
    for name, expected in expected_payloads.items():
        relative = output_relative + "/" + name
        raw = store._io.read_bytes(relative)
        if json.loads(raw) != expected:
            raise ValueError("V5_ACQUISITION_PAYLOAD_READBACK_MISMATCH")
        evidence[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    page_bindings = []
    for index, page in enumerate(pages):
        relative = output_relative + f"/pages/{index:04d}.json"
        store._io.write_bytes(relative, page["raw"])
        raw = store._io.read_bytes(relative)
        if raw != page["raw"]:
            raise ValueError("V5_ACQUISITION_PAGE_READBACK_MISMATCH")
        page_bindings.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                              "bytes": len(raw), "group_id": page["group_id"],
                              "retrieved_at": page["retrieved_at"]})
    available_at = _acquisition_clock()
    stamps = [datetime.fromisoformat(value) for value in (started_at, retrieved_at, available_at)]
    if any(value.utcoffset() is None for value in stamps) or not stamps[0] <= stamps[1] <= stamps[2]:
        raise ValueError("V5_ACQUISITION_CLOCK_ORDER")
    previous = stamps[0]
    for page in page_bindings:
        observed = datetime.fromisoformat(page["retrieved_at"])
        if observed.utcoffset() is None or not previous <= observed <= stamps[1]:
            raise ValueError("V5_ACQUISITION_PAGE_CLOCK_ORDER")
        previous = observed
    receipt = {
        "schema_version": "v5.zsxq_acquisition_receipt.v3",
        "scope": "NEW_BOUNDED_CLI_RESPONSE_AND_DERIVED_SUMMARY_NOT_ARTICLE_PROVENANCE",
        "run_id": run_id,
        "acquisition_started_at": started_at,
        "retrieval_completed_at": retrieved_at,
        "source_payloads_available_at": available_at,
        "clock_basis": "PRODUCER_WALL_CLOCK_AFTER_CALLBACK_AND_DURABLE_READBACK",
        "files": evidence,
        "pages": page_bindings,
        "response_representation": "CLI_STDOUT_TEXT_UTF8_AFTER_BOM_REMOVAL",
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "bounded_has_more": bool(bounded_has_more),
        "full_source_coverage": False,
        "article_acquisition_verified": False,
        "issuer_body_binding_verified": False,
        "historical_pit_claimed": False,
        "natural_verified": False,
        **SAFETY,
    }
    relative = output_relative + "/acquisition_receipt.v3.json"
    # output_relative was exclusively created by this new invocation; no backfill/reuse.
    store._write(relative, receipt)
    raw = store._io.read_bytes(relative)
    if json.loads(raw) != receipt:
        raise ValueError("V5_ACQUISITION_RECEIPT_READBACK_MISMATCH")
    # Recheck the bound bytes before allowing the original success status publish.
    all_bound = {**evidence, **{page["path"]: page for page in page_bindings}}
    for name, ref in all_bound.items():
        raw_payload = store._io.read_bytes(name)
        if len(raw_payload) != ref["bytes"] or hashlib.sha256(raw_payload).hexdigest() != ref["sha256"]:
            raise ValueError("V5_ACQUISITION_PAYLOAD_CHANGED")
    return {"schema_version": receipt["schema_version"], "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def materialize_zsxq_hourly_delta(
    *,
    data_root: Path,
    trade_date: str,
    slot: str,
    cli: Path = DEFAULT_CLI,
    selector_panel: Path = DEFAULT_SELECTOR_PANEL,
    refetch_root: Path = DEFAULT_REFETCH_ROOT,
    groups: Iterable[tuple[str, str]] = DEFAULT_GROUPS,
    page_limit: int = 30,
    max_pages: int = 20,
    lookback_days: int = 4,
    process_runner: Runner = subprocess.run,
    analyzer: Analyzer | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require_acquisition_root(data_root)
    datetime.strptime(trade_date, "%Y%m%d")
    if slot != "0830" and slot not in tuple(f"{hour:02d}00" for hour in range(9, 24)):
        raise ValueError("ZSXQ delta slot must be 0830 or 0900 through 2300")
    status_relative = (
        f"research_module/runtime_outputs/zsxq_hourly/{trade_date}/{slot}/"
        f"v35_zsxq_hourly_status_{trade_date}_{slot}.json"
    )
    status_path = resolve_owned_path(data_root, status_relative)
    if status_path.is_file():
        existing = json.loads(status_path.read_text(encoding="utf-8"))
        if existing.get("fetch_ok") is True and existing.get("status") in {"READY", "READY_EMPTY"}:
            return {**existing, "reused": True}
    observed = now or datetime.now(SHANGHAI)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=SHANGHAI)
    else:
        observed = observed.astimezone(SHANGHAI)
    as_of = datetime.strptime(trade_date + slot, "%Y%m%d%H%M").replace(
        tzinfo=SHANGHAI, second=59
    )
    floor = as_of - timedelta(days=max(1, int(lookback_days)))
    previous = _previous_success_time(Path(data_root), trade_date, slot)
    since = max(floor, previous) if previous is not None else floor
    pages = []
    def capture_runner(command, **kwargs):
        completed = process_runner(command, **kwargs)
        finished = _acquisition_clock()
        if completed.returncode == 0:
            raw = (completed.stdout or "").lstrip("\ufeff").encode("utf-8")
            if len(pages) >= 400 or sum(len(p["raw"]) for p in pages) + len(raw) > 16 * 1024 * 1024:
                raise ValueError("V5_ACQUISITION_PAGE_SIZE")
            pages.append({"raw": raw, "group_id": command[command.index("--group-id") + 1],
                          "retrieved_at": finished})
        return completed
    acquisition_started_at = _acquisition_clock()
    fetched = collect_paginated_topics(
        cli=Path(cli),
        groups=groups,
        as_of=as_of,
        since=since,
        page_limit=page_limit,
        max_pages=max_pages,
        process_runner=capture_runner,
    )
    retrieval_completed_at = _acquisition_clock()
    recent = {
        "success": bool(fetched["topics"]),
        "count": len(fetched["topics"]),
        "has_more": bool(fetched["bounded_has_more"]),
        "topics_brief": fetched["topics"],
    }
    summary = (analyzer or _default_analyzer)(
        recent, Path(selector_panel), Path(refetch_root)
    )
    run_id = observed.strftime(f"{trade_date}_{slot}00_%H%M%S%f")
    output_relative = f"external_sources/zsxq_hourly/{run_id}"
    output_dir = resolve_owned_path(data_root, output_relative)
    output_dir.mkdir(parents=True, exist_ok=False)
    fetch_result = {
        "ok": True,
        "success": True,
        "mode": "official_oauth_cli_paginated",
        "count": len(fetched["topics"]),
        "page_count": fetched["page_count"],
        "groups": fetched["group_results"],
        **SAFETY,
    }
    NativeDataStore(data_root)._write(
        f"{output_relative}/zsxq_recent_topics_fetch_result.json", fetch_result
    )
    NativeDataStore(data_root)._write(
        f"{output_relative}/zsxq_recent_topics.json", recent
    )
    summary_payload = {
        "ok": True,
        "action": "v35_paginated_hourly_delta",
        "mode": "recent_effective_supplement",
        "source_mode": "official_oauth_cli_paginated",
        "recent_fetch": fetch_result,
        **summary,
        **SAFETY,
    }
    NativeDataStore(data_root)._write(
        f"{output_relative}/zsxq_summary.json", summary_payload
    )
    acquisition_evidence = _publish_acquisition_receipt(
        NativeDataStore(data_root), output_relative, run_id,
        acquisition_started_at, retrieval_completed_at,
        {"zsxq_recent_topics_fetch_result.json": fetch_result,
         "zsxq_recent_topics.json": recent, "zsxq_summary.json": summary_payload},
        fetched["bounded_has_more"], pages,
    )
    cannot_confirm = (
        ["ZSXQ_PAGINATION_BOUNDED_HAS_MORE"]
        if fetched["bounded_has_more"]
        else []
    )
    status = "READY" if fetched["topics"] else "READY_EMPTY"
    payload = {
        "schema_version": "v3_5.zsxq_hourly_delta.v1",
        "trade_date": trade_date,
        "slot": slot,
        "window": f"PAGINATED_DELTA_AS_OF_{slot[:2]}:{slot[2:]}",
        "source": "zsxq",
        "source_label": "知识星球",
        "latest_run_id": run_id,
        "fetched_at": observed.isoformat(timespec="seconds"),
        "acquisition_evidence_v2": acquisition_evidence,
        "source_since": since.isoformat(timespec="seconds"),
        "source_cutoff": as_of.isoformat(timespec="seconds"),
        "status": status,
        "topic_count": len(fetched["topics"]),
        "effective_topic_count": int(summary.get("effective_topic_count") or 0),
        "page_count": int(fetched["page_count"]),
        "fetch_ok": True,
        "risk_boundary": "research-only official OAuth CLI; no push or trading",
        "write_policy": "read_only",
        "default_status": "RESEARCH_ONLY",
        "buy_gate_effect": "none",
        "live_order_effect": "none",
        "push_attempted": False,
        "paths": {
            "run_dir": output_relative,
            "fetch_result": str(output_dir / "zsxq_recent_topics_fetch_result.json"),
            "recent_topics": str(output_dir / "zsxq_recent_topics.json"),
            "summary": str(output_dir / "zsxq_summary.json"),
        },
        "cannot_confirm": cannot_confirm,
        "status_path": status_relative,
        "reused": False,
        **SAFETY,
    }
    store = NativeDataStore(data_root)
    store._write(status_relative, payload)
    store._write(
        "research_module/runtime_outputs/zsxq_hourly/latest_zsxq_hourly_status.json",
        payload,
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--selector-panel", type=Path, default=DEFAULT_SELECTOR_PANEL)
    parser.add_argument("--refetch-root", type=Path, default=DEFAULT_REFETCH_ROOT)
    parser.add_argument("--page-limit", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        result = materialize_zsxq_hourly_delta(
            data_root=args.data_root,
            trade_date=args.date,
            slot=args.slot,
            cli=args.cli,
            selector_panel=args.selector_panel,
            refetch_root=args.refetch_root,
            page_limit=args.page_limit,
            max_pages=args.max_pages,
        )
    except Exception as error:
        print(json.dumps({"status": "CANNOT_CONFIRM", "reason": f"{type(error).__name__}: {error}", **SAFETY}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"READY", "READY_EMPTY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
