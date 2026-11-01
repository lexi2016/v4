#!/usr/bin/env python3
"""Capture and compare a read-only HTTP response baseline for the V4 API.

The baseline is evidence, not a test double: it records status, content type
and a normalized body per sample, plus the frozen inputs (release identity,
catalog generation, clock) that make two captures comparable at all.

Only GET samples are allowed. The tool refuses to write a capture if the
target reports a write or if the tracked state directories change during the
run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_SAMPLES = Path(__file__).with_name("baseline_samples.json")
READ_ONLY_TIMEOUT_SECONDS = 120


class BaselineError(RuntimeError):
    pass


def _get_json(base_url: str, path: str, params: Mapping[str, Any] | None = None) -> tuple[int, str, Any]:
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
    url = base_url.rstrip("/") + path + (("?" + query) if query else "")
    last_error: Exception | None = None
    for _attempt in range(2):
        request = urllib.request.Request(url, method="GET", headers={"accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=READ_ONLY_TIMEOUT_SECONDS) as response:
                return response.status, response.headers.get("content-type", ""), _decode(response.read())
        except urllib.error.HTTPError as error:
            headers = error.headers or {}
            return error.code, headers.get("content-type", ""), _decode(error.read())
        except (TimeoutError, urllib.error.URLError) as error:
            last_error = error
    raise last_error  # type: ignore[misc]


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"__non_json_bytes__": hashlib.sha256(raw).hexdigest(), "__size__": len(raw)}


def _drop_path(value: Any, dotted: str) -> None:
    _drop_parts(value, dotted.split("."))


def _drop_parts(value: Any, parts: Sequence[str]) -> None:
    """Delete one exact dotted path; ``key[]`` descends into every list element."""
    if not parts:
        return
    head, rest = parts[0], parts[1:]
    if head.endswith("[]"):
        key = head[:-2]
        if isinstance(value, dict) and isinstance(value.get(key), list):
            for item in value[key]:
                _drop_parts(item, rest)
        return
    if isinstance(value, list):
        if head == "[]":
            if rest:
                for item in value:
                    _drop_parts(item, rest)
            return
        if head.isdigit() and int(head) < len(value):
            if rest:
                _drop_parts(value[int(head)], rest)
            else:
                value[int(head)] = None
        return
    if isinstance(value, dict):
        if head not in value:
            return
        if rest:
            _drop_parts(value[head], rest)
        else:
            value.pop(head, None)


def _normalize(body: Any, ignore_paths: Sequence[str]) -> Any:
    if body is None:
        return None
    cloned = json.loads(json.dumps(body))
    for dotted in ignore_paths:
        _drop_path(cloned, dotted)
    return cloned


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _assert_read_only(sample_id: str, body: Any) -> None:
    if not isinstance(body, Mapping):
        return
    for key in ("write_performed", "production_allowed", "buy_gate_updated", "orders_sent"):
        if body.get(key) is True and key != "production_allowed":
            raise BaselineError(f"{sample_id}: target reports {key}=true; refusing to capture")
    if body.get("write_performed") is True:
        raise BaselineError(f"{sample_id}: write_performed=true; refusing to capture")


def _tracked_roots() -> list[Path]:
    names = ("V4_DATA_ROOT", "V4_STAGE_CENTER_SELECTION_ROOT", "V4_RESEARCH_DATA_ROOT")
    roots = [Path(os.environ[name]) for name in names if os.environ.get(name)]
    return [root for root in roots if root.exists()]


def _root_stamp(roots: Iterable[Path]) -> dict[str, int | None]:
    stamp: dict[str, int | None] = {}
    for root in roots:
        try:
            stamp[str(root)] = root.stat().st_mtime_ns
        except OSError:
            stamp[str(root)] = None
    return stamp


def _frozen_context(base_url: str, body: Any) -> dict[str, Any]:
    identity = body.get("runtime_identity") if isinstance(body, Mapping) else None
    context: dict[str, Any] = {
        "system_date": body.get("system_date") if isinstance(body, Mapping) else None,
        "runtime_identity": identity,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    selection_root = os.environ.get("V4_STAGE_CENTER_SELECTION_ROOT")
    if selection_root:
        latest = Path(selection_root) / "selection_latest.json"
        if latest.is_file():
            context["selection_latest_sha256"] = hashlib.sha256(latest.read_bytes()).hexdigest()
    data_root = os.environ.get("V4_DATA_ROOT")
    if data_root:
        catalog = Path(data_root) / "date_catalog.json"
        if catalog.is_file():
            context["date_catalog_sha256"] = hashlib.sha256(catalog.read_bytes()).hexdigest()
    return context


def capture(base_url: str, samples_path: Path, ignore_paths: Sequence[str]) -> dict[str, Any]:
    spec = json.loads(samples_path.read_text(encoding="utf-8"))
    samples: list[dict[str, Any]] = []
    roots = _tracked_roots()
    before = _root_stamp(roots)
    for sample in spec["samples"]:
        if sample.get("method", "GET").upper() != "GET":
            raise BaselineError(f"{sample['id']}: only GET samples are supported")
        entry: dict[str, Any] = {
            "id": sample["id"],
            "path": sample["path"],
            "params": sample.get("params") or {},
        }
        try:
            status, content_type, body = _get_json(base_url, sample["path"], sample.get("params"))
        except (TimeoutError, urllib.error.URLError) as error:
            entry.update({"status": None, "content_type": "", "error": type(error).__name__})
            samples.append(entry)
            continue
        if status == 200:
            _assert_read_only(sample["id"], body)
        if sample["id"] == "date_list" and isinstance(body, Mapping):
            entry["identity"] = body.get("runtime_identity")
        if sample["id"] == "rg_frontend_build" and isinstance(body, Mapping):
            entry["frontend_status"] = body.get("status")
        normalized = _normalize(body, ignore_paths)
        entry.update({
            "status": status,
            "content_type": content_type,
            "body_sha256": _digest(normalized),
            "body": normalized,
        })
        samples.append(entry)
    after = _root_stamp(roots)
    if before != after:
        raise BaselineError("tracked state directories changed during capture; not a read-only snapshot")
    frozen = _frozen_context(base_url, _get_json(base_url, "/api/v1/runs/date-list")[2])
    return {
        "schema_version": "v4.response_baseline.v1",
        "base_url": base_url,
        "samples_path": str(samples_path),
        "ignored_paths": list(ignore_paths),
        "frozen": frozen,
        "samples": samples,
    }


def _load_ignore(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [str(item) for item in payload]
    entries = payload.get("paths")
    if not isinstance(entries, list):
        raise BaselineError("ignore file must be a list or contain a 'paths' list")
    return [entry["path"] for entry in entries]


def _require_identity(samples: Sequence[Mapping[str, Any]]) -> None:
    by_id = {sample["id"]: sample for sample in samples}
    identity = by_id.get("date_list", {}).get("identity") or {}
    if identity.get("status") != "MANIFEST_EXECUTION_FILES_VERIFIED":
        raise BaselineError(
            "release identity is not verified: " + str(identity.get("status") or "MISSING")
        )
    frontend_status = by_id.get("rg_frontend_build", {}).get("frontend_status")
    if frontend_status != "VERIFIED":
        raise BaselineError(
            "frontend build identity is not verified: " + str(frontend_status or "MISSING")
        )


def compare(baseline_path: Path, candidate: Mapping[str, Any]) -> list[str]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    left = {item["id"]: item for item in baseline["samples"]}
    right = {item["id"]: item for item in candidate["samples"]}
    for missing in sorted(set(left) - set(right)):
        problems.append(f"missing sample: {missing}")
    for extra in sorted(set(right) - set(left)):
        problems.append(f"unexpected sample: {extra}")
    for sample_id in sorted(set(left) & set(right)):
        a, b = left[sample_id], right[sample_id]
        if a.get("error") or b.get("error"):
            if a.get("error") != b.get("error"):
                problems.append(f"{sample_id}: capture error {a.get('error')} -> {b.get('error')}")
            continue
        if a["status"] != b["status"]:
            problems.append(f"{sample_id}: status {a['status']} -> {b['status']}")
        if a["content_type"] != b["content_type"]:
            problems.append(f"{sample_id}: content-type {a['content_type']} -> {b['content_type']}")
        if a["body_sha256"] != b["body_sha256"]:
            problems.append(f"{sample_id}: normalized body changed")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8873")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--out", type=Path, help="write a new baseline here")
    parser.add_argument("--compare", type=Path, help="compare a fresh capture against this baseline")
    parser.add_argument("--ignore", type=Path, help="JSON list of exact dotted paths to ignore")
    parser.add_argument(
        "--skip-identity-check", action="store_true",
        help="do not require verified release/frontend identity (diagnosis only)",
    )
    arguments = parser.parse_args(argv)
    ignore_paths: list[str] = []
    if arguments.ignore:
        try:
            ignore_paths = _load_ignore(arguments.ignore)
        except BaselineError as error:
            print(f"BASELINE_ERROR {error}", file=sys.stderr)
            return 2
    try:
        captured = capture(arguments.base_url, arguments.samples, ignore_paths)
        if not arguments.skip_identity_check:
            _require_identity(captured["samples"])
    except BaselineError as error:
        print(f"BASELINE_ERROR {error}", file=sys.stderr)
        return 2
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(json.dumps(captured, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {arguments.out} ({len(captured['samples'])} samples)")
    if arguments.compare:
        problems = compare(arguments.compare, captured)
        if problems:
            for problem in problems:
                print(f"DIFF {problem}")
            return 1
        print("MATCH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
