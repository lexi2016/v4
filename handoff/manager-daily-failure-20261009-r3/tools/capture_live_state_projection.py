#!/usr/bin/env python3
"""One-pass, sequential, local GET capture. Stores only status projection and full-body SHA-256."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT = Path(__file__).resolve().parents[1] / "evidence" / "live_get_projection_20261009.json"
BASE = "http://127.0.0.1:8873/api/v4/manager/research/workspace"
QUERIES = [
    "date=20261009&selection_date=20261008&announcement_date=20261007&view=auto",
    "date=20261009&selection_date=20261009&announcement_date=20261008&view=auto",
]
TZ = ZoneInfo("Asia/Shanghai")
SAFE_FIELDS = {"status", "run_id", "generated_at", "research_cutoff", "enabled", "available", "present", "exists", "error_code", "code", "reason_code"}
CODE_VALUE = re.compile(r"^[A-Z0-9_]+(?::[A-Za-z0-9_.]+)?$")
CONTEXT_WORDS = ("plan_product", "daily_run", "announcement", "market_screen", "security_master", "selection_diagnostics", "planning_close", "hk", "connect", "universe")

def now() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")

def get_path(value: object, dotted: str) -> object:
    cur = value
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur

def pick_fields(value: object, fields: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {name: value[name] for name in fields if name in value and (value[name] is None or isinstance(value[name], (str, int, float, bool)))}

def status_projection(body: object) -> dict[str, object]:
    if not isinstance(body, dict):
        return {"json_object": False}
    paths = {
        "plan_product": ("status", "run_id", "generated_at"),
        "us_mapping_research.daily_run": ("status", "run_id", "generated_at", "research_cutoff"),
        "announcement_review": ("status", "run_id", "generated_at"),
        "announcement_observation": ("status", "run_id", "generated_at"),
        "owner_chain.announcements": ("status", "run_id"),
        "owner_chain.announcement_selection": ("status", "run_id"),
        "owner_chain.us_mapping_daily_plan_reference": ("status", "run_id"),
        "market_screen": ("status", "error_code", "code", "reason_code"),
        "selection_diagnostics": ("status",),
        "date_bindings": ("selection_date", "announcement_date", "plan_date"),
        "planning_close_recapture_evidence": ("status", "run_id"),
    }
    selected = {}
    for path, fields in paths.items():
        item = pick_fields(get_path(body, path), fields)
        if item:
            selected[path] = item
    safe_nested = []
    def walk(value: object, path: str = "") -> None:
        if isinstance(value, dict):
            context = path.lower()
            if any(word in context for word in CONTEXT_WORDS):
                for key, item in value.items():
                    if key in SAFE_FIELDS and item is not None and isinstance(item, (str, int, float, bool)):
                        if key in {"error_code", "code", "reason_code"} and isinstance(item, str) and not CODE_VALUE.fullmatch(item):
                            continue
                        if key in {"status", "run_id", "generated_at", "research_cutoff", "enabled", "available", "present", "exists", "error_code", "code", "reason_code"}:
                            safe_nested.append({"path": f"{path}.{key}", "value": item})
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    walk(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            # Preserve structure-free status evidence without exposing rows or symbols.
            for item in value:
                if isinstance(item, (dict, list)):
                    walk(item, path + "[]")
    walk(body)
    return {
        "selected": selected,
        "additional_status_fields": safe_nested[:160],
        "research_only_flags": {key: body.get(key) for key in ("RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent") if key in body},
    }

def main() -> int:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    results = []
    for query in QUERIES:  # Deliberately sequential; no concurrent requests.
        url = f"{BASE}?{query}"
        row: dict[str, object] = {"query": query, "request_started_at_cst": now(), "method": "GET"}
        request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with opener.open(request, timeout=25) as response:
                raw = response.read()
                row["http_status"] = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            row["http_status"] = exc.code
        except Exception as exc:
            row["transport_error_type"] = type(exc).__name__
            row["response_completed_at_cst"] = now()
            results.append(row)
            continue
        row["response_completed_at_cst"] = now()
        row["response_bytes"] = len(raw)
        row["response_sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            row["json_parse"] = "NON_JSON_BODY_NOT_SAVED"
        else:
            row["projection"] = status_projection(parsed)
        results.append(row)
    document = {
        "schema_version": "v4.manager_daily_failure_r3.live_get_projection.v1",
        "captured_at_cst": now(),
        "source": "127.0.0.1:8873; two sequential GET requests; response bodies not persisted",
        "requests": results,
    }
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
