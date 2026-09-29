from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_LIMIT = 800
_PRODUCTION_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".css"}
_EXCLUDED_PARTS = {"tests", "test", "third_party", "vendor", "_vendor", "node_modules", ".git", ".venv", "venv", "upstreams"}
_MANAGER_PREFIXES = (
    "v4/manager_research/",
    "apps/web/src/manager-selection/",
)
_MANAGER_EXACT = {"apps/web/src/views/ManagerSelectionView.vue", "apps/web/src/styles/manager-selection.css"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def _is_phase0_legacy_source_archive(rel: Path) -> bool:
    parts = rel.parts
    return (
        len(parts) >= 6
        and parts[:3] == (".runtime", "evidence", "phase0")
        and parts[3] not in {"", ".", ".."}
        and parts[4] == "legacy_sources"
    )


def _is_candidate(rel: Path) -> bool:
    if _is_phase0_legacy_source_archive(rel):
        return False
    rel_text = rel.as_posix()
    name = rel.name.lower()
    if rel.suffix.lower() not in _PRODUCTION_SUFFIXES:
        return False
    if any(part in _EXCLUDED_PARTS for part in rel.parts):
        return False
    if ".spec." in name or ".test." in name:
        return False
    if rel_text in _MANAGER_EXACT or any(rel_text.startswith(prefix) for prefix in _MANAGER_PREFIXES):
        return False
    return True


def _exception_allowed(rel: str, sha: str, exceptions: dict[str, Any]) -> bool:
    entry = exceptions.get(rel)
    return isinstance(entry, dict) and entry.get("sha256") == sha and bool(str(entry.get("reason") or "").strip())


def check_growth(
    repo_root: Path | str,
    baseline_path: Path | str,
    exceptions_path: Path | str | None = None,
    *,
    expected_baseline_head: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    baseline_head = str(baseline.get("baseline_head") or "").strip()
    expected_head = str(expected_baseline_head or "").strip()
    baseline_rows = {row["path"]: row for row in baseline.get("files", []) if row.get("category") == "production"}
    exceptions: dict[str, Any] = {}
    if exceptions_path is not None:
        value = json.loads(Path(exceptions_path).read_text(encoding="utf-8"))
        exceptions = value.get("exceptions", {}) if isinstance(value, dict) else {}

    violations: list[dict[str, Any]] = []
    if not expected_head or baseline_head != expected_head:
        violations.append({
            "path": None,
            "reason": "BASELINE_HEAD_MISMATCH",
            "baseline_head": baseline_head or None,
            "expected_baseline_head": expected_head or None,
        })

    observed: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        rel_path = path.relative_to(root)
        if not _is_candidate(rel_path):
            continue
        rel = rel_path.as_posix()
        lines = _line_count(path)
        if lines <= _LIMIT:
            continue
        sha = _sha(path)
        base = baseline_rows.get(rel)
        if base is None:
            reason = "NEW_LONG_PRODUCTION_FILE"
        elif lines > int(base.get("lines", 0)):
            reason = "EXISTING_LONG_FILE_GREW"
        else:
            observed.append({"path": rel, "lines": lines, "baseline_lines": int(base.get("lines", 0)), "sha256": sha, "status": "BASELINE_DEBT_UNCHANGED_OR_REDUCED"})
            continue
        row = {"path": rel, "lines": lines, "baseline_lines": int(base.get("lines", 0)) if base else None, "sha256": sha, "reason": reason}
        if _exception_allowed(rel, sha, exceptions):
            row["status"] = "PINNED_EXCEPTION"
            observed.append(row)
        else:
            violations.append(row)

    return {
        "status": "FAIL" if violations else "PASS",
        "limit": _LIMIT,
        "baseline_head": baseline_head or None,
        "expected_baseline_head": expected_head or None,
        "baseline_head_verified": bool(expected_head and baseline_head == expected_head),
        "baseline_chain_rule": "refresh the baseline only after independent acceptance of the new head; next change must pass that accepted head as expected_baseline_head",
        "violations": violations,
        "observed_long_files": observed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--expected-baseline-head", required=True)
    parser.add_argument("--exceptions", type=Path)
    args = parser.parse_args(argv)
    result = check_growth(
        args.repo_root,
        args.baseline,
        args.exceptions,
        expected_baseline_head=args.expected_baseline_head,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
