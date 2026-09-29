#!/usr/bin/env python3
"""Build a review-only, source-only V4 upload snapshot.

The source repository is read-only. All outputs stay under this script's
parent task directory. Upload chunk rows use UTF-8 text pieces; rows sharing a
path are concatenated in ascending `part` order before creating a Git blob.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


SOURCE_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
OUTPUT_ROOT = Path(__file__).resolve().parents[1]
MAX_JSON_CHUNK_BYTES = 400_000
MAX_CONTENT_SEGMENT_BYTES = 40_000

TEXT_SUFFIXES = {
    ".py", ".pyi", ".pyx", ".pxd", ".ts", ".tsx", ".js", ".jsx",
    ".mjs", ".cjs", ".vue", ".html", ".css", ".scss", ".sass",
    ".json", ".json5", ".jsonl", ".toml", ".yaml", ".yml", ".lock",
    ".txt", ".md", ".rst", ".adoc", ".sh", ".zsh", ".bash", ".sql",
    ".ini", ".cfg", ".conf", ".xml", ".plist", ".properties", ".ps1",
    ".bat", ".cmd", ".csv", ".svg", ".proto", ".graphql", ".gql",
    ".ipynb", ".snap", ".typed", ".0-license",
}
TEXT_NAMES = {
    "makefile", "dockerfile", "containerfile", "procfile", "license",
    "license.md", "notice", "notice.md", "py.typed", ".gitignore",
    ".gitattributes", ".editorconfig", ".python-version", ".npmrc",
    ".prettierrc", ".eslintrc", "justfile", "taskfile",
}
SOURCE_ROOTS = {
    "apps", "contracts", "domains", "docs", "infrastructure", "ops",
    "stage_center", "tests", "tools", "upstreams", "v4", "v4_migration",
    "verification",
}
ROOT_METADATA_NAMES = {
    "readme.md", "agents.md", "pyproject.toml", "uv.lock", "package.json",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "requirements.txt",
    "requirements-dev.txt", "tox.ini", "pytest.ini", "mypy.ini",
    "ruff.toml", "setup.cfg", "setup.py", "tsconfig.json", "vite.config.ts",
    "vitest.config.ts", "eslint.config.js", "prettier.config.js",
}

EXCLUDED_DIR_NAMES = {
    ".git", ".pytest_cache", "__pycache__", ".venv", "venv", "env",
    ".runtime", "runtime", "state", "node_modules", ".mypy_cache",
    ".ruff_cache", ".tox", ".next", ".nuxt", "dist", "build", "coverage",
    "target", "logs", "log", "captures", "capture", "market_capture",
    "market_captures", "raw_captures", "artifacts", "output", "outputs",
    "runs", "old-data",
}
EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo", ".parquet", ".day", ".mutex", ".current", ".zip",
    ".diff", ".tour", ".sqlite", ".sqlite3", ".db", ".pem", ".key",
    ".p12", ".pfx", ".crt", ".cer", ".jpg", ".jpeg", ".png", ".gif",
    ".webp", ".pdf", ".dylib", ".so", ".dylib", ".dll", ".bin",
}
LOCAL_SECRET_NAME = re.compile(
    r"(^\.env(?:\..*)?$|(^|[._-])(secrets?|credentials?|private[-_]?keys?)([._-]|$)|"
    r"(^|[._-])local[-_](?:settings|config|secrets?)([._-]|$))",
    re.IGNORECASE,
)

MARKET_CAPTURE_PATHS = {
    "tests/fixtures/research/snapshots/research_lane_snapshot_20260730.json":
        "historical research snapshot data fixture",
    "tests/fixtures/stage_0925_20260730_tdxpy_input.json":
        "historical market capture fixture",
    "tests/fixtures/stage_0925_20260730_tdxpy_provider_snapshot.json":
        "historical market provider capture fixture",
    "tests/fixtures/manager_20260924_preopen_screen.json":
        "historical preopen market/research data fixture",
}
MARKET_CAPTURE_PREFIXES = {
    "tests/fixtures/hkconnect_stage_replay/": "historical HK market capture fixture",
    "upstreams/v3_shared_data/tests/fixtures/exact-search-morning-news-20260824/":
        "captured market-news HTML and manifest fixtures",
}


def run_git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=SOURCE_ROOT, check=True, capture_output=True
    ).stdout


def git_text(*args: str) -> str:
    return run_git(*args).decode("utf-8", "replace").strip()


def current_status() -> tuple[bytes, dict[str, str], Counter[str]]:
    raw = run_git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    records = raw.split(b"\0")
    paths: dict[str, str] = {}
    counts: Counter[str] = Counter()
    i = 0
    while i < len(records):
        record = records[i]
        i += 1
        if not record:
            continue
        code = record[:2].decode("ascii", "replace")
        name = record[3:].decode("utf-8", "surrogateescape")
        paths[name] = code
        if code == "??":
            counts["untracked"] += 1
        elif "D" in code:
            counts["deleted"] += 1
        elif "M" in code or "A" in code or "R" in code or "C" in code:
            counts["tracked_changed"] += 1
        else:
            counts["other"] += 1
        if "R" in code or "C" in code:
            # Porcelain -z uses a second NUL-delimited path for a rename/copy.
            if i < len(records):
                i += 1
    return raw, paths, counts


def candidate_paths() -> list[str]:
    raw = run_git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    paths = [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]
    return sorted(set(paths))


def split_status(path: str, status_paths: dict[str, str]) -> str:
    if path in status_paths:
        return status_paths[path]
    parent = str(PurePosixPath(path).parent)
    if parent in status_paths and status_paths[parent] == " D":
        return "untracked_under_deleted_gitlink"
    return "clean_at_capture"


def excluded_reason(path: str) -> str | None:
    p = PurePosixPath(path)
    parts = p.parts
    lower = path.lower()
    name = p.name.lower()

    for part in parts:
        low = part.lower()
        if low.startswith(".pytest-tmp-"):
            return "pytest temporary runtime tree"
        if low in EXCLUDED_DIR_NAMES:
            return "runtime data, generated artifact, cache, or vendored build output"
    if name == ".ds_store":
        return "macOS filesystem metadata"
    if name.endswith(("~", ".bak", ".orig", ".rej")) or "pre-key" in name:
        return "backup or superseded local file"
    if lower.startswith("docs/evidence/"):
        return "evidence artifact rather than source documentation"
    if lower.startswith("verification/formula_margin_shadow_v1/"):
        return "verification receipt, chat package, or captured result artifact"
    if lower.startswith("docs/superpowers/"):
        return "historical planning artifact"
    for prefix, reason in MARKET_CAPTURE_PREFIXES.items():
        if lower.startswith(prefix.lower()):
            return reason
    for exact, reason in MARKET_CAPTURE_PATHS.items():
        if lower == exact.lower():
            return reason
    if LOCAL_SECRET_NAME.search(name) or name.startswith(".env"):
        return "local secret or credential configuration"
    if p.suffix.lower() in EXCLUDED_SUFFIXES:
        return "binary, generated data, or non-source artifact"
    if p.suffix.lower() == ".csv" and not lower.startswith("tests/fixtures/"):
        return "data table outside a source fixture directory"
    if p.suffix.lower() == ".html" and (
        "capture" in lower or "market-news" in lower or "market_news" in lower
    ):
        return "captured web content"
    if len(parts) > 1 and parts[0] not in SOURCE_ROOTS:
        return "outside source, tests, dependency, and documentation scope"
    if len(parts) == 1 and name not in ROOT_METADATA_NAMES and p.suffix.lower() not in TEXT_SUFFIXES:
        return "outside root source/dependency metadata allowlist"
    if len(parts) > 1 and p.suffix.lower() not in TEXT_SUFFIXES and name not in TEXT_NAMES:
        return "non-text or unsupported source file type"
    return None


def split_utf8(text: str, max_bytes: int) -> list[str]:
    out: list[str] = []
    part: list[str] = []
    size = 0
    for ch in text:
        char_size = len(ch.encode("utf-8"))
        if part and size + char_size > max_bytes:
            out.append("".join(part))
            part = []
            size = 0
        part.append(ch)
        size += char_size
    if part or not out:
        out.append("".join(part))
    return out


SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b")),
    ("credential_url", re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^/\s@]{8,}@")),
]
ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd|secret)\b"
    r"\s*[:=]\s*['\"]([^'\"\r\n]{20,})['\"]"
)
PLACEHOLDER = re.compile(
    r"(?i)(?:placeholder|your[-_ ]|example|sample|dummy|fake|test[-_ ]|changeme|"
    r"replace[-_ ]|redacted|not[-_ ]a[-_ ]secret|<[^>]+>|\$\{[^}]+\}|\.\.\.)"
)


def secret_paths(entries: list[dict]) -> list[str]:
    findings: set[str] = set()
    for entry in entries:
        text = entry["source_text"]
        path = entry["path"]
        if any(pattern.search(text) for _, pattern in SECRET_PATTERNS):
            findings.add(path)
            continue
        for match in ASSIGNMENT_SECRET.finditer(text):
            value = match.group(1)
            if not PLACEHOLDER.search(value):
                findings.add(path)
                break
    return sorted(findings)


def classify(path: str) -> str:
    if path.startswith("tests/fixtures/") or "/fixtures/" in path:
        return "test_fixture"
    if path.startswith("tests/") or "/tests/" in path or path.endswith(".spec.ts"):
        return "test_source"
    if path.startswith("docs/") or path.lower().endswith(("readme.md", "license.md")):
        return "documentation"
    if path.startswith("contracts/"):
        return "source_contract_or_configuration"
    if path == "uv.lock" or path.endswith(("requirements.txt", "package-lock.json", "pnpm-lock.yaml")):
        return "dependency_lock"
    if path.startswith("verification/"):
        return "verification_source"
    return "production_source_or_dependency_manifest"


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def mode_for(path: Path) -> str:
    return "100755" if path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) else "100644"


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def collect() -> tuple[list[dict], list[dict], list[str], dict, bytes, dict[str, str], Counter[str]]:
    start_status_raw, start_status_paths, start_status_counts = current_status()
    start_head = git_text("rev-parse", "HEAD")
    branch = git_text("branch", "--show-current")
    status_sha = hashlib.sha256(start_status_raw).hexdigest()
    start_candidates = candidate_paths()
    excluded: list[dict] = []
    records: list[dict] = []
    for rel in start_candidates:
        reason = excluded_reason(rel)
        src = SOURCE_ROOT / rel
        if reason:
            excluded.append({"path": rel, "reason": reason})
            continue
        try:
            if not src.is_file() or src.is_symlink():
                excluded.append({"path": rel, "reason": "not a regular file"})
                continue
            raw = src.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            excluded.append({"path": rel, "reason": "not readable UTF-8 text"})
            continue
        mode = mode_for(src)
        records.append({
            "path": rel,
            "mode": mode,
            "type": "blob",
            "classification": classify(rel),
            "source_status": split_status(rel, start_status_paths),
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob_sha": git_blob_sha(raw),
            "source_text": text,
            "source_bytes": raw,
        })
    return records, excluded, start_candidates, {
        "git_head": start_head,
        "branch": branch,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status_sha256": status_sha,
        "status_counts": dict(start_status_counts),
        "candidate_path_count": len(start_candidates),
    }, start_status_raw, start_status_paths, start_status_counts


def dependent_test_paths(excluded_fixture_paths: list[str], records: list[dict]) -> dict[str, list[str]]:
    fixture_test_scope = {
        "tests/fixtures/manager_20260924_preopen_screen.json": [
            "tests/test_manager_research_attention.py",
        ],
        "tests/fixtures/research/snapshots/research_lane_snapshot_20260730.json": [
            "tests/test_research_graph_contract.py",
        ],
        "tests/fixtures/stage_0925_20260730_tdxpy_input.json": [
            "tests/test_stage_0925_frozen_regression.py",
            "tests/test_stage_0925_vertical_parity.py",
            "tests/test_stage_eight_runs.py",
        ],
        "tests/fixtures/stage_0925_20260730_tdxpy_provider_snapshot.json": [
            "tests/test_stage_0925_vertical_parity.py",
            "tests/test_stage_eight_runs.py",
        ],
    }
    fixture_prefix_scope = {
        "tests/fixtures/hkconnect_stage_replay/": [
            "tests/test_hkconnect_stage_replay_provider.py",
            "tests/test_stage_eight_runs.py",
        ],
        "upstreams/v3_shared_data/tests/fixtures/exact-search-morning-news-20260824/": [
            "tests/test_research_peripheral_regressions.py",
        ],
    }
    out: dict[str, list[str]] = {}
    for fixture in excluded_fixture_paths:
        dependents = fixture_test_scope.get(fixture, [])
        for prefix, tests in fixture_prefix_scope.items():
            if fixture.startswith(prefix):
                dependents = tests
                break
        if dependents:
            out[fixture] = sorted(set(dependents))
    return out


def make_chunks(records: list[dict]) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    file_parts: dict[str, int] = {}
    for record in records:
        upload_path = record.get("upload_path", record["path"])
        segments = split_utf8(record["source_text"], MAX_CONTENT_SEGMENT_BYTES)
        file_parts[upload_path] = len(segments)
        for index, segment in enumerate(segments, start=1):
            rows.append({
                "path": upload_path,
                "mode": record["mode"],
                "type": record["type"],
                "content": segment,
                "part": index,
                "parts": len(segments),
            })
    chunks: list[dict] = []
    current: list[dict] = []
    for row in rows:
        proposed = current + [row]
        data = json_bytes({"schema": "v4-github-tree-entries.v1", "entries": proposed})
        if current and len(data) > MAX_JSON_CHUNK_BYTES:
            chunk_data = json_bytes({"schema": "v4-github-tree-entries.v1", "entries": current})
            chunks.append({"data": chunk_data, "entry_count": len(current)})
            current = [row]
            data = json_bytes({"schema": "v4-github-tree-entries.v1", "entries": current})
        else:
            current = proposed
        if len(data) > MAX_JSON_CHUNK_BYTES:
            raise ValueError(f"single transport row exceeds JSON chunk bound: {row['path']}")
    if current:
        chunk_data = json_bytes({"schema": "v4-github-tree-entries.v1", "entries": current})
        chunks.append({"data": chunk_data, "entry_count": len(current)})
    return chunks, [{"path": path, "parts": count} for path, count in sorted(file_parts.items())]


def readme_text(source: dict, records: list[dict], excluded: list[dict]) -> str:
    fixture_paths = [
        item["path"] for item in excluded
        if item["path"].startswith("tests/fixtures/") or "/tests/fixtures/" in item["path"]
    ]
    source_status = source["status_counts"]
    return f"""# V4 source review snapshot

This is the unified review entry point for this V4 source snapshot upload. The source bytes came from `/Users/lexi/Desktop/学习/v4_app`.

- Source HEAD: `{source['git_head']}` on `{source['branch']}`.
- The package includes the current working-tree bytes for selected tracked and untracked source, test, fixture, contract, documentation, and dependency files. Dirty and untracked production helpers are represented directly in the manifest.
- Working-tree status at capture: `{source_status.get('tracked_changed', 0)}` tracked changed rows, `{source_status.get('deleted', 0)}` deleted rows, and `{source_status.get('untracked', 0)}` untracked rows.
- This is a review snapshot. It does not claim that these bytes match the active deployment. Active-deploy equivalence is `CANNOT_CONFIRM`.
- No claim is made that all tests pass. This task did not run the test suite. Market-capture fixtures and runtime artifacts listed in `docs/source_snapshot_20260929/metadata/exclusions.json` are intentionally absent, including {len(fixture_paths)} excluded fixture paths.
- The payload contains {len(records)} source UTF-8 text files plus snapshot metadata and packaging scripts. `upload/tree_entries_*.json` stays at or below {MAX_JSON_CHUNK_BYTES:,} bytes per file. Rows with one `path` are concatenated in ascending `part` order to recover that file's exact UTF-8 bytes. Each row carries `path`, `mode`, `type`, and `content`.
- `docs/source_snapshot_20260929/metadata/manifest.json` records source SHA-256 and Git blob SHA values. The source worktree had no root `README.md`; its `START_HERE.md` is included. The metadata directory also records source status, exclusions, path-only secret scan results, and the packaging scripts.
- The local package directory's `metadata/transport_index.json` records upload chunk hashes. It is uploader metadata and is not itself part of the GitHub tree, since it includes hashes of those transport chunks.

The snapshot does not contain `.git`, runtime data, local secret configuration, caches, `node_modules`, virtual environments, generated outputs, market captures, logs, or review receipts. The one deleted tracked Git link at `upstreams/review_core` is represented by its current untracked helper files, which are listed individually in the manifest.
"""


def build(preflight_only: bool = False) -> int:
    records, excluded, candidates, source, start_status_raw, start_status_paths, start_status_counts = collect()
    publish_root = "docs/source_snapshot_20260929"
    if any(path.startswith(f"{publish_root}/") for path in candidates):
        print(f"Source already contains the reserved snapshot documentation path: {publish_root}")
        return 5

    source_readme = next((record for record in records if record["path"].lower() == "readme.md"), None)

    if preflight_only:
        findings = secret_paths(records)
        if findings:
            print("Potential secret pattern paths require review:")
            for path in findings:
                print(path)
            return 3
        print(f"Secret scan: no pattern matches across {len(records)} selected UTF-8 source files.")
        print(f"Selected paths: {len(records)}; excluded paths: {len(excluded)}.")
        return 0

    start_map = {record["path"]: record["sha256"] for record in records}
    end_map: dict[str, str] = {}
    for rel in candidate_paths():
        if excluded_reason(rel):
            continue
        src = SOURCE_ROOT / rel
        if not src.is_file() or src.is_symlink():
            continue
        try:
            data = src.read_bytes()
            data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        end_map[rel] = hashlib.sha256(data).hexdigest()
    source_consistent = end_map == start_map
    drift_paths = sorted(
        path for path in (set(start_map) | set(end_map))
        if start_map.get(path) != end_map.get(path)
    )
    if not source_consistent:
        print("Source content changed during capture; no upload tree was built.")
        for path in drift_paths:
            print(path)
        return 4

    included_paths = {record["path"] for record in records}
    status_deletions = sorted(
        path for path, code in start_status_paths.items()
        if "D" in code and path not in included_paths
    )
    excluded_counts = Counter(item["reason"] for item in excluded)
    excluded_fixture_paths = [
        item["path"] for item in excluded
        if item["path"].startswith("tests/fixtures/") or "/tests/fixtures/" in item["path"]
    ]
    market_capture_fixtures = [
        {"path": path, "reason": reason}
        for path, reason in sorted(MARKET_CAPTURE_PATHS.items())
        if any(item["path"] == path for item in excluded)
    ] + [
        item for item in excluded
        if any(item["path"].startswith(prefix) for prefix in MARKET_CAPTURE_PREFIXES)
    ]
    fixture_scope = dependent_test_paths(excluded_fixture_paths, records)
    excluded_doc = {
        "schema": "v4-source-exclusions.v1",
        "excluded_path_count": len(excluded),
        "reason_counts": dict(sorted(excluded_counts.items())),
        "excluded_paths": excluded,
        "market_capture_fixture_count": len(market_capture_fixtures),
        "market_capture_fixtures": market_capture_fixtures,
        "missing_test_scope": [
            {
                "fixture_path": fixture,
                "dependent_tests": test_paths,
                "status": "FIXTURE_EXCLUDED_TEST_NOT_RUN",
            }
            for fixture, test_paths in sorted(fixture_scope.items())
        ],
        "binary_fixtures_needed_for_source_review": [],
        "binary_files_seen": [
            item["path"] for item in excluded
            if PurePosixPath(item["path"]).suffix.lower() in {".parquet", ".day", ".zip", ".pdf", ".png", ".jpg"}
        ],
    }
    write_json(OUTPUT_ROOT / "metadata" / "exclusions.json", excluded_doc)

    state_doc = {
        "schema": "v4-source-state.v1",
        **source,
        "status_counts": dict(start_status_counts),
        "candidate_path_count": len(candidates),
        "included_file_count": len(records),
        "excluded_file_count": len(excluded),
        "tracked_deletions_not_present_in_snapshot": status_deletions,
        "source_content_consistent_at_capture": True,
        "content_drift_paths": [],
        "active_deploy_equivalence": "CANNOT_CONFIRM",
        "all_tests_claimed": False,
        "tests_run": False,
        "review_only": True,
    }
    write_json(OUTPUT_ROOT / "metadata" / "source_state.json", state_doc)

    readme = readme_text(source, records, excluded)
    (OUTPUT_ROOT / "README.md").write_text(readme, encoding="utf-8")

    def payload_record(tree_path: str, data: bytes, classification: str) -> dict:
        text = data.decode("utf-8")
        return {
            "path": tree_path,
            "upload_path": tree_path,
            "mode": "100644",
            "type": "blob",
            "classification": classification,
            "source_status": "snapshot_generated",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob_sha": git_blob_sha(data),
            "source_text": text,
            "source_bytes": data,
        }

    artifact_map = {
        "README.md": ("README.md", (OUTPUT_ROOT / "README.md").read_bytes(), "snapshot_summary"),
        f"{publish_root}/metadata/source_state.json": (
            f"{publish_root}/metadata/source_state.json",
            (OUTPUT_ROOT / "metadata/source_state.json").read_bytes(), "snapshot_metadata",
        ),
        f"{publish_root}/metadata/exclusions.json": (
            f"{publish_root}/metadata/exclusions.json",
            (OUTPUT_ROOT / "metadata/exclusions.json").read_bytes(), "snapshot_metadata",
        ),
        f"{publish_root}/scripts/build_snapshot.py": (
            f"{publish_root}/scripts/build_snapshot.py",
            (OUTPUT_ROOT / "scripts/build_snapshot.py").read_bytes(), "snapshot_packaging_script",
        ),
        f"{publish_root}/scripts/verify_snapshot.py": (
            f"{publish_root}/scripts/verify_snapshot.py",
            (OUTPUT_ROOT / "scripts/verify_snapshot.py").read_bytes(), "snapshot_packaging_script",
        ),
    }
    source_upload_records = []
    for record in records:
        copy = dict(record)
        copy["upload_path"] = (
            f"{publish_root}/README_SOURCE.md"
            if source_readme is not None and record["path"].lower() == "readme.md"
            else record["path"]
        )
        source_upload_records.append(copy)
    artifact_records = [payload_record(path, data, classification) for path, (_, data, classification) in artifact_map.items()]
    scan_records = source_upload_records + artifact_records
    findings = secret_paths(scan_records)
    scan_doc = {
        "schema": "v4-source-secret-scan.v1",
        "scope": "all source and snapshot metadata/script files selected for GitHub upload",
        "scanner": "high-confidence credential patterns and non-placeholder credential assignments",
        "result": "POTENTIAL_SECRET_PATHS_FOUND" if findings else "NO_PATTERN_MATCHES",
        "finding_paths": findings,
        "scanned_file_count": len(scan_records),
        "values_emitted": False,
    }
    write_json(OUTPUT_ROOT / "metadata" / "secret_scan.json", scan_doc)
    if findings:
        print("Potential secret pattern paths require review:")
        for path in findings:
            print(path)
        print("Stopped before creating upload chunks or manifest.")
        return 3
    scan_artifact = payload_record(
        f"{publish_root}/metadata/secret_scan.json",
        (OUTPUT_ROOT / "metadata/secret_scan.json").read_bytes(),
        "snapshot_metadata",
    )
    artifact_records.append(scan_artifact)

    def source_manifest_record(record: dict) -> dict:
        published = record["upload_path"]
        return {
            "path": record["path"],
            "published_path": published,
            "mode": record["mode"],
            "type": record["type"],
            "classification": record["classification"],
            "source_status": record["source_status"],
            "size_bytes": record["size_bytes"],
            "sha256": record["sha256"],
            "git_blob_sha": record["git_blob_sha"],
        }

    manifest_target = f"{publish_root}/metadata/manifest.json"
    manifest = {
        "schema": "v4-github-source-snapshot.v1",
        "snapshot_kind": "review_only_current_worktree_source",
        "source_root": str(SOURCE_ROOT),
        "source_git_head": source["git_head"],
        "source_branch": source["branch"],
        "source_status_sha256": source["status_sha256"],
        "status_counts": dict(start_status_counts),
        "source_file_count": len(records),
        "source_bytes": sum(record["size_bytes"] for record in records),
        "files": [source_manifest_record(record) for record in source_upload_records],
        "snapshot_artifacts": [
            {
                "path": artifact["upload_path"],
                "mode": artifact["mode"],
                "type": artifact["type"],
                "classification": artifact["classification"],
                "size_bytes": artifact["size_bytes"],
                "sha256": artifact["sha256"],
                "git_blob_sha": artifact["git_blob_sha"],
            }
            for artifact in artifact_records
        ],
        "manifest_published_path": manifest_target,
        "manifest_self_digest": "recorded in local metadata/transport_index.json to avoid a self-hash cycle",
        "exclusions_published_path": f"{publish_root}/metadata/exclusions.json",
        "source_state_published_path": f"{publish_root}/metadata/source_state.json",
        "secret_scan_published_path": f"{publish_root}/metadata/secret_scan.json",
        "upload_transport": {
            "row_schema": ["path", "mode", "type", "content", "part", "parts"],
            "reassembly": "group by path, sort by part ascending, concatenate content, encode as UTF-8",
            "max_chunk_bytes": MAX_JSON_CHUNK_BYTES,
            "transport_index_path": "metadata/transport_index.json (local uploader metadata; not in GitHub tree)",
        },
        "active_deploy_equivalence": "CANNOT_CONFIRM",
        "all_tests_claimed": False,
        "tests_run": False,
    }
    write_json(OUTPUT_ROOT / "metadata/manifest.json", manifest)
    manifest_record = payload_record(
        manifest_target,
        (OUTPUT_ROOT / "metadata/manifest.json").read_bytes(),
        "snapshot_metadata",
    )

    for record in source_upload_records:
        record["path"] = record["upload_path"]
    payload_records = source_upload_records + artifact_records + [manifest_record]
    chunks, part_index = make_chunks(payload_records)
    upload_dir = OUTPUT_ROOT / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for old_chunk in upload_dir.glob("tree_entries_*.json"):
        old_chunk.unlink()
    chunk_records = []
    for index, chunk in enumerate(chunks, start=1):
        name = f"tree_entries_{index:04d}.json"
        target = upload_dir / name
        target.write_bytes(chunk["data"])
        chunk_records.append({
            "path": f"upload/{name}",
            "size_bytes": len(chunk["data"]),
            "sha256": hashlib.sha256(chunk["data"]).hexdigest(),
            "entry_rows": chunk["entry_count"],
        })

    manifest_bytes = (OUTPUT_ROOT / "metadata/manifest.json").read_bytes()
    transport_index = {
        "schema": "v4-github-source-transport-index.v1",
        "source_git_head": source["git_head"],
        "manifest_published_path": manifest_target,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_git_blob_sha": git_blob_sha(manifest_bytes),
        "tree_file_count": len({r["upload_path"] for r in payload_records}),
        "transport_row_count": sum(chunk["entry_count"] for chunk in chunks),
        "max_chunk_bytes": MAX_JSON_CHUNK_BYTES,
        "largest_chunk_bytes": max((chunk["size_bytes"] for chunk in chunk_records), default=0),
        "chunks": chunk_records,
        "file_parts": part_index,
    }
    write_json(OUTPUT_ROOT / "metadata/transport_index.json", transport_index)
    print(f"Built {len(records)} source files plus {len(artifact_records) + 1} snapshot artifacts.")
    print(f"GitHub tree paths: {transport_index['tree_file_count']}; source bytes: {manifest['source_bytes']}.")
    print(f"Upload chunks: {len(chunks)}; largest chunk: {transport_index['largest_chunk_bytes']} bytes.")
    print(f"Excluded paths: {len(excluded)}; market capture fixture paths: {len(market_capture_fixtures)}.")
    print(f"Secret scan: clean across {len(scan_records)} non-manifest files.")
    print(f"Source HEAD: {source['git_head']}; active deploy equivalence: CANNOT_CONFIRM.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    try:
        return build(preflight_only=args.preflight_only)
    except Exception as exc:
        # Keep diagnostics structural; never dump source text or caught values.
        print(f"Snapshot build failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
