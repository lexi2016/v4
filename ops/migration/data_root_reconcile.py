from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any


class ReconcileError(ValueError):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _root(value: Path | str) -> Path:
    lexical = Path(value).expanduser()
    if not lexical.is_absolute():
        lexical = Path.cwd() / lexical
    lexical = Path(os.path.abspath(os.fspath(lexical)))
    if lexical.is_symlink() or any(parent.is_symlink() for parent in lexical.parents):
        raise ReconcileError(f"ROOT_SYMLINK_REJECTED:{lexical}")
    p = lexical.resolve()
    if not p.is_dir():
        raise ReconcileError(f"ROOT_MISSING:{p}")
    return p


def _semantic_key(path: Path, data: bytes) -> str | None:
    """Return only business identities whose schema is explicitly understood.

    Hashing and semantic extraction use the same byte snapshot so a concurrent
    writer cannot produce a SHA from one version and a business key from another.
    """
    if path.suffix.lower() != ".json":
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") == "v3_5.preselection_pool.v1":
        trade_date = str(value.get("trade_date") or "").strip()
        pool_id = str(value.get("pool_id") or "").strip()
        if trade_date and pool_id:
            return f"preselection_pool:{trade_date}:{pool_id}"
    return None


def _inventory(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows[rel] = {"kind": "symlink", "size": None, "sha256": None, "business_key": None}
        elif path.is_file():
            before = path.stat()
            data = path.read_bytes()
            after = path.stat()
            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)
            ):
                raise ReconcileError(f"FILE_CHANGED_DURING_SCAN:{path}")
            rows[rel] = {
                "kind": "file",
                "size": after.st_size,
                "sha256": hashlib.sha256(data).hexdigest(),
                "business_key": _semantic_key(path, data),
            }
    return rows


def _semantic_reconcile(
    source_inventory: dict[str, dict[str, Any]], target_inventory: dict[str, dict[str, Any]]
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    by_side: dict[str, dict[str, list[dict[str, Any]]]] = {
        "source": defaultdict(list),
        "target": defaultdict(list),
    }
    for side, inventory in (("source", source_inventory), ("target", target_inventory)):
        for rel, item in inventory.items():
            key = item.get("business_key")
            if item.get("kind") == "file" and key:
                by_side[side][str(key)].append(
                    {"relative_path": rel, "sha256": item["sha256"], "size": item["size"]}
                )

    counts = {
        "same_key_same_bytes": 0,
        "same_key_conflict_keep_both": 0,
        "semantic_source_only": 0,
        "semantic_target_only": 0,
        "duplicate_key_quarantine": 0,
    }
    entries: list[dict[str, Any]] = []
    all_keys = sorted(set(by_side["source"]) | set(by_side["target"]))
    for key in all_keys:
        src = by_side["source"].get(key, [])
        dst = by_side["target"].get(key, [])
        row: dict[str, Any] = {"business_key": key, "source": src, "target": dst}
        if len(src) > 1 or len(dst) > 1:
            row.update(decision="DUPLICATE_KEY_QUARANTINE", reason="MULTIPLE_FILES_CLAIM_SAME_BUSINESS_KEY")
            counts["duplicate_key_quarantine"] += 1
        elif src and dst:
            if src[0]["sha256"] == dst[0]["sha256"] and src[0]["size"] == dst[0]["size"]:
                row.update(decision="SAME_KEY_SAME_BYTES", reason="SEMANTIC_KEY_AND_BYTES_IDENTICAL")
                counts["same_key_same_bytes"] += 1
            else:
                row.update(decision="SAME_KEY_CONFLICT_KEEP_BOTH", reason="SAME_BUSINESS_KEY_DIFFERENT_CONTENT")
                counts["same_key_conflict_keep_both"] += 1
        elif src:
            row.update(decision="SEMANTIC_SOURCE_ONLY", reason="BUSINESS_KEY_MISSING_ON_TARGET")
            counts["semantic_source_only"] += 1
        else:
            row.update(decision="SEMANTIC_TARGET_ONLY", reason="BUSINESS_KEY_MISSING_ON_SOURCE")
            counts["semantic_target_only"] += 1
        entries.append(row)
    return counts, entries


def reconcile_roots(source_root: Path | str, target_root: Path | str) -> dict[str, Any]:
    source = _root(source_root)
    target = _root(target_root)
    if source == target or _under(source, target) or _under(target, source):
        raise ReconcileError(f"ROOT_OVERLAP:source={source}:target={target}")
    src = _inventory(source)
    dst = _inventory(target)
    entries: list[dict[str, Any]] = []
    counts = {"same_bytes": 0, "conflict_keep_both": 0, "source_only": 0, "target_only": 0, "quarantine": 0}
    for rel in sorted(set(src) | set(dst)):
        s = src.get(rel)
        t = dst.get(rel)
        row: dict[str, Any] = {"relative_path": rel, "source": s, "target": t}
        if (s and s.get("kind") != "file") or (t and t.get("kind") != "file"):
            row.update(decision="QUARANTINE", reason="NON_REGULAR_OR_SYMLINK")
            counts["quarantine"] += 1
        elif s is not None and t is not None:
            if s["sha256"] == t["sha256"] and s["size"] == t["size"]:
                row.update(decision="SAME_BYTES", reason="IDENTICAL_SHA256_AND_SIZE")
                counts["same_bytes"] += 1
            else:
                row.update(decision="CONFLICT_KEEP_BOTH", reason="SAME_PATH_DIFFERENT_CONTENT")
                counts["conflict_keep_both"] += 1
        elif s is not None:
            row.update(decision="SOURCE_ONLY", reason="MISSING_ON_TARGET")
            counts["source_only"] += 1
        else:
            row.update(decision="TARGET_ONLY", reason="MISSING_ON_SOURCE")
            counts["target_only"] += 1
        entries.append(row)

    semantic_counts, semantic_entries = _semantic_reconcile(src, dst)
    source_regular = sum(item.get("kind") == "file" for item in src.values())
    target_regular = sum(item.get("kind") == "file" for item in dst.values())
    source_keyed = sum(item.get("kind") == "file" and bool(item.get("business_key")) for item in src.values())
    target_keyed = sum(item.get("kind") == "file" and bool(item.get("business_key")) for item in dst.values())
    semantic_coverage = {
        "source_regular_files": source_regular,
        "source_keyed_regular_files": source_keyed,
        "source_unkeyed_regular_files": source_regular - source_keyed,
        "target_regular_files": target_regular,
        "target_keyed_regular_files": target_keyed,
        "target_unkeyed_regular_files": target_regular - target_keyed,
    }
    return {
        "schema_version": "v4.migration.data_root_reconciliation.v2",
        "source_root": str(source),
        "target_root": str(target),
        "counts": counts,
        "entries": entries,
        "semantic_key_support": ["v3_5.preselection_pool.v1:trade_date+pool_id"],
        "semantic_counts": semantic_counts,
        "semantic_entries": semantic_entries,
        "semantic_coverage": semantic_coverage,
        "cutover_eligible": False,
        "unsupported_schema_promotion_allowed": False,
        "destructive_actions_allowed": False,
        "overwrite_allowed": False,
        "dedupe_delete_allowed": False,
        "writer_migrated": False,
        "decision_rule": {
            "SAME_BYTES": "eligible only for no-copy optimization in isolated staging after semantic validation; do not delete serving copies",
            "CONFLICT_KEEP_BOTH": "preserve both bytes and quarantine from authority promotion until owner/schema/date reconciliation",
            "SOURCE_ONLY": "preserve and migrate only inside an approved dataset/workload batch",
            "TARGET_ONLY": "preserve; do not overwrite from source",
            "QUARANTINE": "do not follow or promote non-regular/symlink entries",
            "SAME_KEY_CONFLICT_KEEP_BOTH": "same business identity claims different bytes even when paths differ; preserve both and block cutover",
            "DUPLICATE_KEY_QUARANTINE": "one side has multiple files claiming one business identity; do not guess authority",
        },
    }


def write_report(result: dict[str, Any], output: Path | str) -> Path:
    source = Path(str(result["source_root"])).resolve()
    target = Path(str(result["target_root"])).resolve()
    raw = Path(output).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    raw = Path(os.path.abspath(os.fspath(raw)))
    if raw.is_symlink() or any(parent.is_symlink() for parent in raw.parents):
        raise ReconcileError(f"OUTPUT_SYMLINK_REJECTED:{raw}")
    parent = raw.parent.resolve()
    resolved_output = parent / raw.name
    if _under(resolved_output, source) or _under(resolved_output, target):
        raise ReconcileError(f"OUTPUT_INSIDE_DATA_ROOT:{resolved_output}")
    parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with resolved_output.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise ReconcileError(f"OUTPUT_EXISTS:{resolved_output}") from error
    return resolved_output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = reconcile_roots(args.source_root, args.target_root)
        report_path = write_report(result, args.output) if args.output else None
    except (ReconcileError, OSError) as error:
        print(json.dumps({"status": "REJECTED", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps({
        "status": "RECONCILED_READ_ONLY",
        "counts": result["counts"],
        "semantic_counts": result["semantic_counts"],
        "report_path": str(report_path) if report_path else None,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
