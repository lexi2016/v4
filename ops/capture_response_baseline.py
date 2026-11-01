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
import re
import stat
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


READ_ONLY_FLAGS = ("write_performed", "production_allowed", "buy_gate_updated", "orders_sent")


def _assert_read_only(sample_id: str, body: Any) -> None:
    if not isinstance(body, Mapping):
        return
    for key in READ_ONLY_FLAGS:
        if body.get(key) is True:
            raise BaselineError(f"{sample_id}: target reports {key}=true; refusing to capture")


ROOT_ENV_NAMES = (
    "V4_DATA_ROOT", "V4_PRESELECTION_SOURCE_ROOT",
    "V4_STAGE_CENTER_SELECTION_ROOT", "V4_RESEARCH_DATA_ROOT",
)
CATALOG_GENERATION_SCHEMA = "v4.date_catalog_input_generation.v1"
CATALOG_HASH_KIND = "typed_input_generation_descriptor_sha256"


def _tracked_roots() -> list[Path]:
    # Keep configured missing roots so creation during a capture is detected.
    return list(dict.fromkeys(Path(os.environ[name]) for name in ROOT_ENV_NAMES if os.environ.get(name)))


def _read_lock_path(relative: str) -> bool:
    # Exact root-owned import mutex/owner and SafeRoot's UUID temp owner name.
    # Other lock-looking files and data-file temporary names remain tracked.
    return relative in {".import.lock", ".import.lock.mutex"} or bool(
        re.fullmatch(r"\.\.import\.lock\.[0-9a-f]{32}\.tmp", relative)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _root_stamp(roots: Iterable[Path]) -> dict[str, Any]:
    """Stamp content files, not directory mtimes affected by read-lock churn."""
    stamp: dict[str, Any] = {}
    for root in roots:
        try:
            if not root.exists():
                stamp[str(root)] = {"state": "MISSING"}
                continue
            if not root.is_dir() or root.is_symlink():
                raise BaselineError(f"tracked state root is not a regular directory: {root}")
            entries: dict[str, Any] = {}
            def walk_error(error: OSError) -> None:
                raise error
            for directory, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
                directories.sort()
                # Record directory symlinks without following data outside the root.
                names = files + [name for name in directories if (Path(directory) / name).is_symlink()]
                for name in sorted(names):
                    path = Path(directory) / name
                    relative = path.relative_to(root).as_posix()
                    if _read_lock_path(relative):
                        continue
                    meta = path.lstat()
                    if stat.S_ISLNK(meta.st_mode):
                        entries[relative] = {"kind": "symlink", "target": os.readlink(path)}
                    elif stat.S_ISREG(meta.st_mode):
                        entries[relative] = {"kind": "file", "sha256": _file_sha256(path)}
                    else:
                        raise BaselineError(f"untracked special state file: {path}")
            stamp[str(root)] = {"state": "PRESENT", "files": entries}
        except OSError as error:
            raise BaselineError(f"cannot stamp tracked state root {root}: {error}") from error
    return stamp


def _input_file(env_name: str, relative: str) -> dict[str, Any]:
    root = os.environ.get(env_name)
    if not root:
        return {"state": "ROOT_NOT_CONFIGURED", "file_sha256": None}
    path = Path(root) / relative
    try:
        if not path.exists():
            return {"state": "MISSING", "file_sha256": None}
        if not path.is_file() or path.is_symlink():
            raise BaselineError(f"catalog input is not a regular file: {path}")
        return {"state": "PRESENT", "file_sha256": _file_sha256(path)}
    except OSError as error:
        raise BaselineError(f"cannot read catalog input {path}: {error}") from error


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
    native = _input_file("V4_DATA_ROOT", "date_catalog.json")
    source = _input_file("V4_PRESELECTION_SOURCE_ROOT", "date_catalog.json")
    fallback_date = context["system_date"] if native["state"] == "MISSING" else None
    if native["state"] == "MISSING" and not re.fullmatch(r"\d{8}", str(fallback_date or "")):
        raise BaselineError("native catalog fallback system_date is unavailable")
    descriptor = {
        "schema_version": CATALOG_GENERATION_SCHEMA,
        "native_catalog": native,
        "native_catalog_receipt": _input_file("V4_DATA_ROOT", "receipts/date_catalog.json"),
        "native_fallback_system_date": fallback_date,
        "explicit_preselection_catalog": source,
        "explicit_preselection_catalog_receipt": _input_file("V4_PRESELECTION_SOURCE_ROOT", "receipts/date_catalog.json"),
        "root_manifests": {name: _input_file(name, "manifest.json") for name in ROOT_ENV_NAMES},
    }
    # This key now names a typed INPUT-generation digest, not an invented
    # native catalog file. Preserve both actual raw file hashes explicitly.
    context.update({
        "date_catalog_sha256": _digest(descriptor),
        "date_catalog_hash_kind": CATALOG_HASH_KIND,
        "date_catalog_input_generation": descriptor,
        "native_date_catalog_file_sha256": native["file_sha256"],
        "preselection_date_catalog_file_sha256": source["file_sha256"],
    })
    return context


def capture(base_url: str, samples_path: Path, ignore_paths: Sequence[str]) -> dict[str, Any]:
    spec = json.loads(samples_path.read_text(encoding="utf-8"))
    samples: list[dict[str, Any]] = []
    roots = _tracked_roots()
    before = _root_stamp(roots)
    frozen_before = _frozen_context(base_url, _get_json(base_url, "/api/v1/runs/date-list")[2])
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
    frozen = _frozen_context(base_url, _get_json(base_url, "/api/v1/runs/date-list")[2])
    after = _root_stamp(roots)
    if before != after:
        raise BaselineError("tracked state directories changed during capture; not a read-only snapshot")
    if any(frozen_before.get(key) != frozen.get(key) for key in COMPARABLE_FROZEN_KEYS):
        raise BaselineError("catalog input generation or fallback clock changed during capture")
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


# The capture varies these by design (release identity, wall clock). Everything
# else that is frozen at capture time must match, or the two captures cannot be
# compared at all.
COMPARABLE_FROZEN_KEYS = ("system_date", "selection_latest_sha256", "date_catalog_sha256")


def _compare_frozen(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    left = baseline.get("frozen") or {}
    right = candidate.get("frozen") or {}
    if left.get("date_catalog_hash_kind") != right.get("date_catalog_hash_kind"):
        problems.append("NOT_COMPARABLE frozen.date_catalog_hash_kind differs")
    for label, context in (("baseline", left), ("candidate", right)):
        if context.get("date_catalog_hash_kind") == CATALOG_HASH_KIND:
            descriptor = context.get("date_catalog_input_generation")
            if (not isinstance(descriptor, Mapping)
                    or descriptor.get("schema_version") != CATALOG_GENERATION_SCHEMA
                    or not isinstance(descriptor.get("native_catalog"), Mapping)
                    or descriptor["native_catalog"].get("state") not in {"PRESENT", "MISSING"}
                    or _digest(descriptor) != context.get("date_catalog_sha256")):
                problems.append(f"NOT_COMPARABLE {label} catalog input descriptor invalid")
    for key in COMPARABLE_FROZEN_KEYS:
        if key not in left or key not in right:
            problems.append(f"NOT_COMPARABLE frozen.{key} missing on one side")
        elif left[key] != right[key]:
            problems.append(f"NOT_COMPARABLE frozen.{key} {left[key]!r} -> {right[key]!r}")
    if list(baseline.get("ignored_paths") or []) != list(candidate.get("ignored_paths") or []):
        problems.append("NOT_COMPARABLE ignored_paths differ; the normalisation rule changed")
    return problems


def compare(baseline_path: Path, candidate: Mapping[str, Any]) -> list[str]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    problems = _compare_frozen(baseline, candidate)
    left = {item["id"]: item for item in baseline["samples"]}
    right = {item["id"]: item for item in candidate["samples"]}
    for missing in sorted(set(left) - set(right)):
        problems.append(f"missing sample: {missing}")
    for extra in sorted(set(right) - set(left)):
        problems.append(f"unexpected sample: {extra}")
    for sample_id in sorted(set(left) & set(right)):
        a, b = left[sample_id], right[sample_id]
        if a.get("path") != b.get("path") or (a.get("params") or {}) != (b.get("params") or {}):
            problems.append(
                f"NOT_COMPARABLE {sample_id}: request changed "
                f"{a.get('path')}{a.get('params') or {}} -> {b.get('path')}{b.get('params') or {}}"
            )
            continue
        if a.get("error") or b.get("error"):
            problems.append(
                f"NOT_VERIFIED {sample_id}: error baseline={a.get('error')} candidate={b.get('error')}"
            )
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
