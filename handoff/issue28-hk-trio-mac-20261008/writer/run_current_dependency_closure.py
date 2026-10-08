from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[1]
BUNDLE = BASE / "input" / "package"
OUT = BASE / "isolated_test" / "current_dependency_closure_retry"
TARGET = "stage_center/_runner_parts/hk_input_validation.py"
SUPPORT_PREFIX = "harness/support/"
OWNER_PREFIX = "input/source/"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_read(root: Path, rel: str) -> bytes:
    relative = PurePosixPath(rel)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe source path: {rel}")
    root = root.resolve(strict=True)
    path = root.joinpath(*relative.parts)
    if path.is_symlink():
        raise ValueError(f"source symlink rejected: {rel}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"source path missing or escaped owner root: {rel}")
    before = path.stat(follow_symlinks=False)
    if not path.is_file():
        raise ValueError(f"source is not a regular file: {rel}")
    data = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after) or len(data) != after.st_size:
        raise ValueError(f"source changed during isolated copy: {rel}")
    return data


def write_clone(root: Path, rel: str, data: bytes) -> Path:
    relative = PurePosixPath(rel)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe clone path: {rel}")
    path = root.joinpath(*relative.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--actual-stage-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()
    # Preserve the configured venv symlink path; resolving it points to the
    # base interpreter and drops the V4 environment's site-packages.
    python = args.python.expanduser().absolute()
    if OUT.exists():
        raise SystemExit(f"refuse to reuse existing isolation directory: {OUT}")
    if not python.is_file():
        raise SystemExit("configured V4 interpreter is not a regular file")
    roots = {"actual_stage_owner": args.actual_stage_root, "canonical": args.canonical_root}
    input_manifest = json.loads((BUNDLE / "harness" / "INPUT_MANIFEST.json").read_text(encoding="utf-8"))
    candidate = json.loads((BUNDLE / "candidate_identity.json").read_text(encoding="utf-8"))
    candidates = {entry["owner"]: entry for entry in candidate["files"]}
    manifest_files = input_manifest["files"]
    support_entries = [entry for entry in manifest_files if entry["path"].startswith(SUPPORT_PREFIX)]
    if len(support_entries) != 17 or set(roots) != {"canonical", "actual_stage_owner"}:
        raise ValueError("unexpected owner/dependency inventory")
    OUT.mkdir(parents=True)
    owner_results = []
    for owner in ("actual_stage_owner", "canonical"):
        owner_root = roots[owner].resolve(strict=True)
        dest = OUT / owner
        app = dest / "app"
        harness = dest / "harness"
        app.mkdir(parents=True)
        expected = {}
        owner_prefix = f"{OWNER_PREFIX}{owner}/"
        owner_entries = [entry for entry in manifest_files if entry["path"].startswith(owner_prefix)]
        if len(owner_entries) != 13:
            raise ValueError(f"expected 13 frozen owner files for {owner}")
        for entry in owner_entries:
            rel = entry["path"][len(owner_prefix):]
            data = (BUNDLE / entry["path"]).read_bytes()
            if len(data) != entry["bytes"] or sha(data) != entry["sha256"]:
                raise ValueError(f"frozen owner input changed: {entry['path']}")
            write_clone(app, rel, data)
            expected["app/" + rel] = entry["sha256"]
        candidate_bytes = (BUNDLE / "after" / TARGET).read_bytes()
        after_sha = candidates[owner]["after_sha256"]
        if sha(candidate_bytes) != after_sha:
            raise ValueError("candidate after SHA mismatch")
        write_clone(app, TARGET, candidate_bytes)
        expected["app/" + TARGET] = after_sha

        dependency_records = []
        for entry in support_entries:
            rel = entry["path"][len(SUPPORT_PREFIX):]
            raw = safe_read(owner_root, rel)
            current_sha = sha(raw)
            write_clone(harness / "support", rel, raw)
            expected["support/" + rel] = current_sha
            dependency_records.append({
                "relative_path": rel,
                "current_sha256": current_sha,
                "pinned_supplement_sha256": entry["sha256"],
                "matches_pinned_supplement": current_sha == entry["sha256"],
                "bytes": len(raw),
            })

        for rel in ("conftest.py", "pytest.ini"):
            raw = (BUNDLE / "harness" / rel).read_bytes()
            if rel == "conftest.py":
                original = b'role = "PINNED_SUPPLEMENT_NOT_CURRENT_RUNTIME_IDENTITY"'
                replacement = b'role = "CURRENT_OWNER_DEPENDENCY_COPY"'
                if raw.count(original) != 1:
                    raise ValueError("expected one role label in cloned conftest")
                raw = raw.replace(original, replacement)
            write_clone(harness, rel, raw)
        tests_dir = harness / "tests"
        tests_dir.mkdir(parents=True)
        for rel in ("test_hk_prior_observation_source_binding.py",
                    "test_hk_split_date_identity_closure.py",
                    "test_root_identity_probe.py"):
            data = (BUNDLE / "harness" / "tests" / rel).read_bytes()
            write_clone(tests_dir, rel, data)
        expected_path = dest / "IMPORT_EXPECTATIONS.json"
        expected_path.write_text(json.dumps(expected, indent=2) + chr(10), encoding="utf-8")
        log_root = dest / "targeted"
        log_root.mkdir()
        home = dest / "home"
        tmp = dest / "tmp"
        home.mkdir()
        tmp.mkdir()
        xml_path = log_root / "junit.xml"
        log_path = log_root / "pytest.log"
        imports_path = log_root / "imports.json"
        command = [
            str(python), "-B", "-m", "pytest", "-q", "-ra", "-p", "no:cacheprovider",
            "-c", str(harness / "pytest.ini"), f"--confcutdir={harness}",
            f"--basetemp={log_root / 'data'}", f"--junitxml={xml_path}",
            "tests/test_hk_split_date_identity_closure.py", "tests/test_root_identity_probe.py",
        ]
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "PYTHONPATH": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "ISSUE28_TEST_OWNER": owner,
            "ISSUE28_TEST_PHASE": "after_current_dependencies",
            "ISSUE28_TEST_APP": str(app),
            "ISSUE28_TEST_IMPORT_EXPECTATIONS": str(expected_path),
            "ISSUE28_TEST_IMPORT_LOG": str(imports_path),
        }
        process = subprocess.run(command, cwd=harness, env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        log_path.write_text(process.stdout, encoding="utf-8")
        cases = ET.parse(xml_path).getroot().findall(".//testcase") if xml_path.exists() else []
        failures = [item.get("name") for item in cases if item.find("failure") is not None]
        errors = [item.get("name") for item in cases if item.find("error") is not None]
        skipped = [item.get("name") for item in cases if item.find("skipped") is not None]
        imports = json.loads(imports_path.read_text(encoding="utf-8")) if imports_path.exists() else {}
        changed_clone = []
        for relative, expected_sha in expected.items():
            clone_path = (app / relative.removeprefix("app/") if relative.startswith("app/")
                          else harness / relative)
            if not clone_path.is_file() or sha(clone_path.read_bytes()) != expected_sha:
                changed_clone.append(relative)
        owner_result = {
            "owner": owner,
            "exit_code": process.returncode,
            "cases": len(cases),
            "passed": len(cases) - len(failures) - len(errors) - len(skipped),
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
            "candidate_file_sha256": sha((app / TARGET).read_bytes()),
            "clone_integrity_changes": changed_clone,
            "current_dependency_count": len(dependency_records),
            "current_dependencies_differing_from_pinned": sum(not x["matches_pinned_supplement"] for x in dependency_records),
            "dependency_sources": dependency_records,
            "imports": imports.get("loaded", []),
            "artifacts": {
                "junit": {"path": str(xml_path), "sha256": sha(xml_path.read_bytes()) if xml_path.exists() else None},
                "pytest_log": {"path": str(log_path), "sha256": sha(log_path.read_bytes())},
                "imports": {"path": str(imports_path), "sha256": sha(imports_path.read_bytes()) if imports_path.exists() else None},
            },
            "command": command,
            "cwd": str(harness),
        }
        owner_results.append(owner_result)
        print(json.dumps({
            "owner": owner,
            "exit_code": process.returncode,
            "cases": len(cases),
            "passed": owner_result["passed"],
            "failures": len(failures),
            "errors": len(errors),
            "skipped": len(skipped),
            "candidate_file_sha256": owner_result["candidate_file_sha256"],
            "current_dependency_count": len(dependency_records),
            "differing_dependencies": owner_result["current_dependencies_differing_from_pinned"],
            "imports_record": owner_result["artifacts"]["imports"],
        }, ensure_ascii=False), flush=True)
    report = {
        "schema_version": "issue28.mac_current_dependency_isolation.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_commit": "88da6312d3ca1cbe116e87aadb107d7cbd7de2a5",
        "scope": "ISOLATED_CURRENT_EXERCISED_DEPENDENCY_CLOSURE_NOT_FULL_STAGE_RUNTIME",
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "pytest_version": importlib.metadata.version("pytest"),
        "owners": owner_results,
        "runtime_recovery_status": "CANNOT_CONFIRM",
        "not_claimed": ["full Stage app/service runtime", "ops/dispatch", "API/UI", "business source validity",
                        "deployment", "natural-slot result", "historical receipt recovery"],
    }
    result_path = OUT / "RESULTS.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(json.dumps({"report": str(result_path), "runtime_recovery_status": "CANNOT_CONFIRM"}, ensure_ascii=False))
    return max((item["exit_code"] for item in owner_results), default=1)


if __name__ == "__main__":
    raise SystemExit(main())
