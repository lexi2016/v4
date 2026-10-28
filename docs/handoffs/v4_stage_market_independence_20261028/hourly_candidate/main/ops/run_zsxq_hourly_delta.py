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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from infrastructure.data_store import NativeDataStore
from infrastructure.isolated_package_loader import load_isolated_package_module
from infrastructure.owned_path import resolve_owned_path
from infrastructure.research_source_evidence import read_zsxq_slot_evidence
from infrastructure.zsxq_pdf_ingestion import process_next_pdf_task, process_pdf_batch, process_pdf_continuation


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
    os.environ.get(
        "V35_SHARED_RESEARCH_ADAPTER_ROOT",
        "/Users/lexi/Documents/Codex/2026-08-13/v35-019ff682/shared-research-collector",
    )
)
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
    resume_groups: Mapping[str, Mapping[str, Any]] | None = None,
    seed_topics: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if as_of.tzinfo is None or since.tzinfo is None:
        raise ValueError("ZSXQ pagination boundaries must be timezone-aware")
    if since > as_of:
        raise ValueError("ZSXQ pagination lower boundary exceeds cutoff")
    limit = max(1, min(30, int(page_limit)))
    page_cap = max(1, int(max_pages))
    collected: dict[str, dict[str, Any]] = {}
    for item in seed_topics:
        group_id = str(item.get("group", {}).get("group_id") or "")
        collected[_topic_key(group_id,item)] = dict(item)
    group_results: list[dict[str, Any]] = []
    bounded_has_more = False
    total_pages = 0
    for group_id, group_name in groups:
        prior = dict((resume_groups or {}).get(group_id, {}))
        cursor = str(prior.get("next_cursor") or "")
        pages = 0
        group_keys = {key for key,row in collected.items() if str(row.get("group",{}).get("group_id")) == group_id}
        source_has_more = bool(prior.get("source_has_more", False))
        reached_since = bool(prior.get("reached_since", False))
        complete = bool(prior) and (not source_has_more or reached_since)
        failure = None
        while not complete and pages < page_cap:
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
            try:
                completed = process_runner(command, timeout=30, capture_output=True,
                    text=True, encoding="utf-8", errors="replace", check=False, shell=False)
            except (subprocess.TimeoutExpired, OSError) as error:
                failure = f"ZSXQ_CLI_GROUP_ERROR:{group_id}:{type(error).__name__}:{error}"
                source_has_more = True
                break
            if completed.returncode != 0:
                failure = f"ZSXQ_CLI_GROUP_FAILED:{group_id}:{(completed.stderr or '')[-300:]}"
                source_has_more = True
                break
            try:
                payload = json.loads((completed.stdout or "").lstrip("\ufeff"))
            except json.JSONDecodeError as error:
                failure = f"ZSXQ_CLI_JSON_INVALID:{group_id}"
                source_has_more = True
                break
            rows = (payload.get("topics_brief") or payload.get("topics") or []) if isinstance(payload,Mapping) else None
            if not isinstance(rows, list):
                failure = f"ZSXQ_CLI_ROWS_INVALID:{group_id}"
                source_has_more = True
                break
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
        if source_has_more and not reached_since:
            bounded_has_more = True
        group_results.append(
            {
                "group_id": group_id,
                "group_name": group_name,
                "page_count": pages + int(prior.get("page_count") or 0),
                "new_page_count": pages,
                "deduped_count": len(group_keys),
                "source_has_more": source_has_more,
                "reached_since": reached_since,
                "next_cursor": cursor or None,
                "cursor_origin": prior.get("cursor_origin", "ORIGINAL_COLLECTOR_PAGE_MIN_TIME"),
                "error": failure,
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
        "page_count": total_pages + sum(int(g.get("page_count") or 0) for g in (resume_groups or {}).values()),
        "new_page_count": total_pages,
        "bounded_has_more": bounded_has_more,
    }


def _default_analyzer(
    recent: dict[str, Any], selector_panel: Path, refetch_root: Path
) -> dict[str, Any]:
    root = Path(refetch_root).resolve()
    v3 = load_isolated_package_module(
        root,
        package_directory="shared_research",
        module_leaf="v3_zsxq_adapter",
        namespace_prefix="v35_shared_research_adapter",
    )
    collector = load_isolated_package_module(
        root,
        package_directory="shared_research",
        module_leaf="collector",
        namespace_prefix="v35_shared_research_collector",
    )
    _selector_environment = getattr(collector, "_selector_environment")

    if not selector_panel.is_file():
        raise FileNotFoundError(f"Mac selector panel missing: {selector_panel}")
    with _selector_environment(selector_panel):
        return dict(v3.analyze_recent_topics(recent))


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
        evidence = read_zsxq_slot_evidence(data_root, trade_date, raw_slot)
        if (evidence is None or evidence.status_path != path
            or evidence.status.get("status") not in {"READY", "READY_EMPTY"}):
            continue
        parsed = _parse_time(evidence.status.get("source_cutoff"))
        if parsed is not None:
            candidates.append(parsed)
    return max(candidates) if candidates else None


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
    resume_source_run_id: str | None = None,
) -> dict[str, Any]:
    datetime.strptime(trade_date, "%Y%m%d")
    if slot != "0830" and slot not in tuple(f"{hour:02d}00" for hour in range(9, 24)):
        raise ValueError("ZSXQ delta slot must be 0830 or 0900 through 2300")
    status_relative = (
        f"research_module/runtime_outputs/zsxq_hourly/{trade_date}/{slot}/"
        f"v35_zsxq_hourly_status_{trade_date}_{slot}.json"
    )
    status_path = resolve_owned_path(data_root, status_relative)
    existing = None
    existing_raw = None
    if status_path.is_file():
        existing_raw = status_path.read_bytes()
        existing = json.loads(existing_raw)
        if resume_source_run_id is None and existing.get("fetch_ok") is True and existing.get("status") in {"READY", "READY_EMPTY", "PARTIAL"}:
            verified = read_zsxq_slot_evidence(data_root, trade_date, slot)
            if verified is None:
                raise ValueError("ZSXQ_EXISTING_STATUS_NOT_VERIFIED")
            return {**verified.status, "reused": True}
    if resume_source_run_id is not None and (not existing or existing.get("latest_run_id") != resume_source_run_id
            or existing.get("trade_date") != trade_date or existing.get("slot") != slot
            or any(existing.get(k) is not False for k in SAFETY)):
        raise ValueError("ZSXQ_RESUME_EXACT_SOURCE_RUN_REQUIRED")
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
    groups = tuple(groups)
    prior_groups, seed_topics = None, ()
    source_pins = {}
    if resume_source_run_id is not None:
        since = _parse_time(existing.get("source_since"))
        if since is None or _parse_time(existing.get("source_cutoff")) != as_of or since > as_of:
            raise ValueError("ZSXQ_RESUME_ORIGINAL_WINDOW_REQUIRED")
        run_relative = f"external_sources/zsxq_hourly/{resume_source_run_id}"
        if existing.get("paths",{}).get("run_dir") != run_relative:
            raise ValueError("ZSXQ_RESUME_OWNED_RUN_PATH_REQUIRED")
        saved={}
        for name in ("zsxq_recent_topics.json","zsxq_recent_topics_fetch_result.json"):
            path=resolve_owned_path(data_root,run_relative+"/"+name);raw=path.read_bytes()
            source_pins[str(path)]=hashlib.sha256(raw).hexdigest();saved[name]=json.loads(raw)
        seed_topics=saved["zsxq_recent_topics.json"]["topics_brief"]
        states=saved["zsxq_recent_topics_fetch_result.json"]["groups"]
        if [(str(g["group_id"]),str(g["group_name"])) for g in states] != list(groups):
            raise ValueError("ZSXQ_RESUME_ORIGINAL_GROUPS_REQUIRED")
        prior_groups={str(g["group_id"]):dict(g) for g in states}
        if any(str(t.get("group",{}).get("group_id")) not in prior_groups for t in seed_topics):
            raise ValueError("ZSXQ_RESUME_SAVED_TOPIC_GROUP_DRIFT")
        for gid,state in prior_groups.items():
            owned=[t for t in seed_topics if str(t.get("group",{}).get("group_id"))==gid]
            times=[_parse_time(t.get("create_time")) for t in owned]
            if len(owned)!=state["deduped_count"] or any(t is None or not since<=t<=as_of for t in times):
                raise ValueError("ZSXQ_RESUME_SAVED_TOPICS_OR_WINDOW_DRIFT")
            if state.get("source_has_more") and not state.get("reached_since"):
                if not state.get("next_cursor"):
                    if not owned:raise ValueError("ZSXQ_RESUME_CURSOR_UNBOUND")
                    state["next_cursor"]=min(owned,key=lambda t:_parse_time(t["create_time"]))["create_time"]
                    state["cursor_origin"]="DERIVED_OWNED_LEGACY_TOPIC_MIN_TIME"
                if _parse_time(state["next_cursor"]) is None or not since<=_parse_time(state["next_cursor"])<=as_of:
                    raise ValueError("ZSXQ_RESUME_CURSOR_WINDOW_DRIFT")
    fetched = collect_paginated_topics(
        cli=Path(cli),
        groups=groups,
        as_of=as_of,
        since=since,
        page_limit=page_limit,
        max_pages=max_pages,
        process_runner=process_runner,
        resume_groups=prior_groups,
        seed_topics=seed_topics,
    )
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
    if existing_raw is not None and resume_source_run_id is not None:
        if status_path.read_bytes()!=existing_raw or any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest for p,digest in source_pins.items()):
            raise ValueError("ZSXQ_RESUME_SOURCE_CHANGED_DURING_READ")
        NativeDataStore(data_root)._write(f"{output_relative}/resume_source_status.json",existing)
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
    source_completed_at = datetime.now(SHANGHAI)
    summary_sha256 = hashlib.sha256((output_dir / "zsxq_summary.json").read_bytes()).hexdigest()
    fetch_result_sha256 = hashlib.sha256((output_dir / "zsxq_recent_topics_fetch_result.json").read_bytes()).hexdigest()
    cannot_confirm = (
        ["ZSXQ_PAGINATION_BOUNDED_HAS_MORE"]
        if fetched["bounded_has_more"]
        else []
    )
    status = "PARTIAL" if fetched["bounded_has_more"] else "READY" if fetched["topics"] else "READY_EMPTY"
    payload = {
        "schema_version": "v3_5.zsxq_hourly_delta.v1",
        "trade_date": trade_date,
        "slot": slot,
        "window": f"PAGINATED_DELTA_AS_OF_{slot[:2]}:{slot[2:]}",
        "source": "zsxq",
        "source_label": "知识星球",
        "latest_run_id": run_id,
        "fetched_at": observed.isoformat(timespec="seconds"),
        "source_completed_at": source_completed_at.isoformat(timespec="microseconds"),
        "summary_sha256": summary_sha256,
        "fetch_result_sha256": fetch_result_sha256,
        "source_since": since.isoformat(timespec="seconds"),
        "source_cutoff": as_of.isoformat(timespec="seconds"),
        "resumed_from_run_id": resume_source_run_id,
        "collection_timing": "RESUMED_AFTER_ORIGINAL_WINDOW" if resume_source_run_id else "ORIGINAL_COLLECTION",
        "resume_observed_at": observed.isoformat(timespec="seconds") if resume_source_run_id else None,
        "original_source_fetched_at": existing.get("fetched_at") if resume_source_run_id else None,
        "original_window_completeness_certified": False,
        "natural_verified": False,
        "pit_certified": False,
        "resume_source_sha256": hashlib.sha256(existing_raw).hexdigest() if existing_raw is not None and resume_source_run_id is not None else None,
        "resume_input_sha256": source_pins,
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
    parser.add_argument("--date")
    parser.add_argument("--slot")
    parser.add_argument("--pdf-queue-tick", action="store_true", help="Process one verified owned-index task.")
    parser.add_argument("--pdf-enqueue-only", action="store_true", help="Enqueue exact-source PDFs without downloading or OCR.")
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="Process PDFs from the exact existing hourly run without fetching topics.",
    )
    parser.add_argument("--source-run-id", help="Exact latest_run_id from the existing hourly status.")
    parser.add_argument("--resume-topics", action="store_true", help="Continue only the exact stored topics window and original groups.")
    parser.add_argument("--pdf-limit", type=int, default=1)
    parser.add_argument("--pdf-file-id", help="Process one attachment id from topics_brief.files.")
    parser.add_argument("--pdf-time-budget-seconds", type=int, default=180)
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--selector-panel", type=Path, default=DEFAULT_SELECTOR_PANEL)
    parser.add_argument("--refetch-root", type=Path, default=DEFAULT_REFETCH_ROOT)
    parser.add_argument("--page-limit", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        if args.resume_topics and (args.pdf_queue_tick or args.pdf_only or args.pdf_enqueue_only):
            raise ValueError("--resume-topics cannot be combined with PDF modes")
        if args.pdf_queue_tick:
            if args.pdf_only or args.pdf_enqueue_only or args.date or args.slot or args.source_run_id or args.pdf_file_id:
                raise ValueError("--pdf-queue-tick cannot be combined with a source run or other PDF mode")
            result = process_next_pdf_task(data_root=args.data_root, cli=args.cli, time_budget_seconds=args.pdf_time_budget_seconds)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.pdf_enqueue_only:
            if not args.date or not args.slot or not args.source_run_id or args.pdf_file_id:
                raise ValueError("--pdf-enqueue-only requires exact date, slot, and source run")
            result = process_pdf_batch(data_root=args.data_root, trade_date=args.date, slot=args.slot, source_run_id=args.source_run_id, cli=args.cli, limit=1, enqueue_only=True, time_budget_seconds=args.pdf_time_budget_seconds)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.pdf_only:
            if not args.date or not args.slot or not args.source_run_id:
                raise ValueError("--pdf-only requires exact date, slot, and source run")
            if not args.source_run_id:
                raise ValueError("--pdf-only requires --source-run-id")
            if args.pdf_file_id:
                result = process_pdf_batch(
                    data_root=args.data_root,
                    trade_date=args.date,
                    slot=args.slot,
                    source_run_id=args.source_run_id,
                    cli=args.cli,
                    limit=1,
                    file_id=args.pdf_file_id,
                    max_pages_per_document=1,
                    time_budget_seconds=args.pdf_time_budget_seconds,
                )
            else:
                result = process_pdf_continuation(
                    data_root=args.data_root,
                    trade_date=args.date,
                    slot=args.slot,
                    source_run_id=args.source_run_id,
                    cli=args.cli,
                    max_documents=args.pdf_limit,
                    time_budget_seconds=args.pdf_time_budget_seconds,
                )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            # PDF progress is supplemental and must not fail the hourly research run.
            return 0
        if not args.date or not args.slot:
            raise ValueError("--date and --slot are required")
        if args.resume_topics and not args.source_run_id:
            raise ValueError("--resume-topics requires --source-run-id")
        if args.source_run_id and not args.resume_topics:
            raise ValueError("--source-run-id requires an explicit source-consuming mode")
        result = materialize_zsxq_hourly_delta(
            data_root=args.data_root,
            trade_date=args.date,
            slot=args.slot,
            cli=args.cli,
            selector_panel=args.selector_panel,
            refetch_root=args.refetch_root,
            page_limit=args.page_limit,
            max_pages=args.max_pages,
            resume_source_run_id=args.source_run_id if args.resume_topics else None,
        )
    except Exception as error:
        print(json.dumps({"status": "CANNOT_CONFIRM", "reason": f"{type(error).__name__}: {error}", **SAFETY}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"READY", "READY_EMPTY", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
