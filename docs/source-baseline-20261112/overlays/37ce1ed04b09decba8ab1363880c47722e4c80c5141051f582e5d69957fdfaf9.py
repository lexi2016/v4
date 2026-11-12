"""One Mac writer for the V3 ZSXQ summary consumed by V3 and V3.5.

The business analysis is the copied V3 ``fixed_v24_refetch`` implementation.
This module only replaces its Windows acquisition shell with the official
OAuth CLI and publishes one immutable, research-only result per date/slot.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import v3_zsxq_adapter as v3


GROUPS = tuple((row["group_id"], row["name"]) for row in v3.GROUPS)
SHANGHAI = ZoneInfo("Asia/Shanghai")
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@contextmanager
def _selector_environment(panel: Path):
    key = "V3_SHARED_SELECTOR_PANEL"
    previous = os.environ.get(key)
    os.environ[key] = str(panel)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _validated_reuse(pointer: Path) -> dict[str, Any] | None:
    payload = _read_json(pointer)
    if (
        payload.get("status") != "READY"
        or payload.get("fetch_ok") is not True
        or any(payload.get(key) is not False for key in SAFETY)
    ):
        return None
    paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
    summary = Path(str(paths.get("summary") or ""))
    topics = Path(str(paths.get("recent_topics") or ""))
    if not summary.is_file() or not topics.is_file():
        return None
    return {**payload, "reused": True}


def _fetch_group(
    *, cli: Path, group_id: str, limit: int, process_runner: Runner
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
    completed = process_runner(
        command,
        timeout=90,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
        env={
            **os.environ,
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
        },
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"ZSXQ_CLI_GROUP_FAILED:{group_id}:{(completed.stderr or '')[-500:]}"
        )
    try:
        payload = json.loads((completed.stdout or "").lstrip("\ufeff"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"ZSXQ_CLI_JSON_INVALID:{group_id}") from error
    if not isinstance(payload, dict) or not (
        payload.get("success") or payload.get("ok") or payload.get("topics_brief")
    ):
        raise RuntimeError(f"ZSXQ_CLI_SOURCE_NOT_READY:{group_id}")
    raw_topics = payload.get("topics_brief") or payload.get("topics") or []
    topics: list[dict[str, Any]] = []
    for raw in raw_topics:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        row["group"] = {
            "group_id": group_id,
            "name": dict(GROUPS).get(group_id, ""),
        }
        topics.append(row)
    return topics, {
        "group_id": group_id,
        "success": True,
        "count": len(topics),
    }


def collect(
    *,
    state_root: Path,
    trade_date: str,
    slot: str,
    cli: Path,
    selector_panel: Path,
    limit: int = 20,
    process_runner: Runner = subprocess.run,
) -> dict[str, Any]:
    datetime.strptime(trade_date, "%Y%m%d")
    if slot != "0830":
        raise ValueError("shared V3 ZSXQ writer is fixed to the 0830 graph slot")
    state_root = Path(state_root).expanduser().resolve()
    pointer = state_root / "latest" / trade_date / f"{slot}.json"
    lock_path = state_root / "locks" / f"{trade_date}-{slot}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        reused = _validated_reuse(pointer)
        if reused is not None:
            return reused
        if process_runner is subprocess.run and not (cli.is_file() and os.access(cli, os.X_OK)):
            raise FileNotFoundError(f"official ZSXQ CLI missing or not executable: {cli}")
        if not selector_panel.is_file():
            raise FileNotFoundError(f"Mac selector panel missing: {selector_panel}")

        observed = datetime.now(SHANGHAI)
        run_id = observed.strftime(f"{trade_date}-{slot}-%H%M%S%f")
        run_root = state_root / "runs" / trade_date / slot / run_id
        zsxq_root = run_root / "zsxq"
        zsxq_root.mkdir(parents=True, exist_ok=False)
        topics: list[dict[str, Any]] = []
        group_results: list[dict[str, Any]] = []
        for group_id, _name in GROUPS:
            rows, result = _fetch_group(
                cli=cli,
                group_id=group_id,
                limit=limit,
                process_runner=process_runner,
            )
            topics.extend(rows)
            group_results.append(result)
        topics.sort(key=lambda row: str(row.get("create_time") or ""), reverse=True)
        recent = {
            "success": bool(topics),
            "count": len(topics),
            "has_more": False,
            "topics_brief": topics,
        }
        _atomic_json(zsxq_root / "zsxq_recent_topics.json", recent)
        fetch_result = {
            "ok": bool(topics),
            "success": bool(topics),
            "mode": "official_oauth_cli",
            "count": len(topics),
            "groups": group_results,
            **SAFETY,
        }
        _atomic_json(zsxq_root / "zsxq_recent_topics_fetch_result.json", fetch_result)
        with _selector_environment(selector_panel):
            analysis = v3.analyze_recent_topics(recent)
        summary = {
            "ok": True,
            "action": "preview_recent_effective_supplement",
            "mode": "recent_effective_supplement",
            "source_mode": "official_oauth_cli",
            "primary_refetch_failed": False,
            "recent_fetch": fetch_result,
            **analysis,
            **SAFETY,
        }
        _atomic_json(zsxq_root / "zsxq_summary.json", summary)
        signature = hashlib.sha256(
            json.dumps(
                sorted(str(row.get("topic_id") or "") for row in topics),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        result = {
            "schema_version": "v3_shared_research.zsxq_0830.v1",
            "status": "READY",
            "fetch_ok": True,
            "trade_date": trade_date,
            "slot": slot,
            "run_id": run_id,
            "fetched_at": observed.isoformat(timespec="seconds"),
            "topic_count": len(topics),
            "effective_topic_count": int(summary.get("effective_topic_count") or 0),
            "topic_signature_sha256": signature,
            "reused": False,
            "paths": {
                "run_dir": str(run_root),
                "zsxq_dir": str(zsxq_root),
                "fetch_result": str(zsxq_root / "zsxq_recent_topics_fetch_result.json"),
                "recent_topics": str(zsxq_root / "zsxq_recent_topics.json"),
                "summary": str(zsxq_root / "zsxq_summary.json"),
            },
            "write_policy": "read_only",
            "default_status": "RESEARCH_ONLY",
            "push_attempted": False,
            **SAFETY,
        }
        _atomic_json(run_root / "receipt.json", result)
        _atomic_json(pointer, result)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect the shared Mac V3 ZSXQ summary")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", default="0830")
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--selector-panel", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    result = collect(
        state_root=args.state_root,
        trade_date=args.date,
        slot=args.slot,
        cli=args.cli,
        selector_panel=args.selector_panel,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
