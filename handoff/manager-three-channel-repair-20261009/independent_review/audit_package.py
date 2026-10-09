"""Independent package audit, using only disposable reconstructed source roots."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PACKAGE = ROOT / "delivery/manager-three-channel-repair-20261009"
APP = ROOT / "app"
PYTHON = "/workspace/scratch/a154a3323e32/test_env/bin/python"
NODE = "/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/node"
NODE_MODULES = "/workspace/scratch/a154a3323e32/candidate/apps/web/node_modules"
BASE = "7ca0190a721a7fd0fc0c88b79a872889867d111f"
SOURCE = "b19eb112bd641ca97cac1246af7c81d8873641f4"
EXPECTED_MANIFEST = "ccd38bc88ab8aa2231e844ef581470bea32545f7d48f988996dc9290f9689e9d"
TEMP = HERE / "package_temporary"
TEMP.mkdir(exist_ok=True)
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
           TMPDIR=str(TEMP))
commands = []


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def rel(value):
    path = PurePosixPath(value)
    assert value and not path.is_absolute() and ".." not in path.parts and str(path) == value, value
    return path


def snapshot(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in root.rglob("*")
            if p.is_file() and not p.is_symlink()}


def run(name, argv, *, cwd=None, env=None, expected=0, timeout=60):
    began = time.monotonic()
    value = subprocess.run(argv, cwd=cwd or HERE, env=env or ENV, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=timeout)
    log = HERE / ("package_" + name + ".log")
    log.write_text(value.stdout)
    command = {"name": name, "argv": argv, "cwd": str(cwd or HERE),
               "exit_code": value.returncode, "expected_exit_code": expected,
               "elapsed_seconds": round(time.monotonic() - began, 3),
               "log": log.name, "log_sha256": sha(log.read_bytes())}
    if env:
        command["environment_overrides"] = {key: env.get(key) for key in (
            "PYTHONDONTWRITEBYTECODE", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "TMPDIR",
            "V4_HANDOFF", "V4_REVIEW_ROOT", "V4_REVIEW_PYTHON", "V4_REVIEW_NODE",
            "V4_REVIEW_NODE_MODULES", "V4_TEST_SOURCE_ROOT", "V4_TEST_PYTHON") if key in env}
    commands.append(command)
    assert value.returncode == expected, (name, value.returncode, value.stdout[-5000:])
    return value.stdout


manifest = json.loads((PACKAGE / "source_manifest.json").read_text())
assert sha((PACKAGE / "source_manifest.json").read_bytes()) == EXPECTED_MANIFEST
assert manifest["base_commit"] == SOURCE and manifest["local_comparison_baseline"] == BASE
assert manifest["not_full_deployable_app"] is True
review = json.loads((HERE / "source_identity_receipt.json").read_text())
reviewed = {row["path"]: row for row in review["files"]}
tree = {row["path"]: row for row in json.loads((ROOT / "input/tree.json").read_text())["tree"]}
assembly = json.loads((ROOT / "evidence/assembly.json").read_text())
base_rows = {row["path"]: row for row in assembly["files"]}
assert len(manifest["files"]) == len(reviewed) == 13
assert {row["path"] for row in manifest["files"]} == set(reviewed)
profiles = list(manifest["profiles"])
assert profiles == ["api_r3_candidate", "web_r3_candidate", "test_delta"]
payloads = []
for row in manifest["files"]:
    rel(row["path"])
    expected = reviewed[row["path"]]
    for side in ("before", "after"):
        name = row[side + "_path"]
        if name is None:
            assert side == "before" and row["change"] == "added"
            assert row["path"] not in base_rows and row[side + "_sha256"] is None
            continue
        rel(name)
        raw = (PACKAGE / name).read_bytes()
        assert len(raw) == row[side + "_bytes"]
        assert sha(raw) == row[side + "_sha256"] == expected[side + "_sha256"]
        assert blob(raw) == row[side + "_git_blob_sha"]
        if side == "before":
            origin = row["before_origin"]
            assert origin["commit"] == SOURCE
            assert tree[origin["repository_path"]]["sha"] == blob(raw)
        else:
            assert raw == (APP / row["path"]).read_bytes()
        payloads.append(name)
for profile, data in manifest["profiles"].items():
    rel(data["patch_path"])
    assert sha((PACKAGE / data["patch_path"]).read_bytes()) == data["patch_sha256"]
    assert data["source_file_count"] == len([row for row in manifest["files"] if row["profile"] == profile])
for row in manifest["preserve"]:
    rel(row["reference_path"])
    raw = (PACKAGE / row["reference_path"]).read_bytes()
    assert sha(raw) == row["sha256"] == base_rows[row["path"]]["sha256"]

support_manifest = json.loads((PACKAGE / "test_source_manifest.json").read_text())
assert support_manifest["changed_tests"] == [row for row in manifest["files"] if row["profile"] == "test_delta"]
support = support_manifest["unchanged_support"]
assert len(support) == 16
for row in support:
    rel(row["path"]); rel(row["archive_path"])
    raw = (PACKAGE / row["archive_path"]).read_bytes()
    assert sha(raw) == row["sha256"] and len(raw) == row["bytes"]
    assert row["fixed_commit"] == SOURCE
    assert raw == (APP / row["path"]).read_bytes()
    for fixed in row["fixed_repository_paths"]:
        assert blob(raw) == tree[fixed]["sha"] and len(raw) == tree[fixed]["size"]
for row in json.loads((PACKAGE / "reference/reused_tool_identity.json").read_text()):
    raw = (PACKAGE / row["path"]).read_bytes()
    assert sha(raw) == row["sha256"] and row["behavior_changed"] is False
    assert blob(raw) == tree[row["repository_path"]]["sha"]

inventory = snapshot(PACKAGE)
source_review_evidence = json.loads((PACKAGE / "independent_review/final_review_receipt.json").read_text())["evidence"]
for row in source_review_evidence:
    raw = (PACKAGE / "independent_review" / row["path"]).read_bytes()
    assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], row["path"]
links = []
pending_links = []
for path in PACKAGE.rglob("*.md"):
    for _label, target in re.findall(r"\[([^\]]*)\]\(([^)]*)\)", path.read_text()):
        if target.startswith(("http:", "https:", "#", "sandbox:", "app:")):
            continue
        local = target.split("#")[0]
        if not local:
            continue
        resolved = (path.parent / local).resolve()
        assert resolved == PACKAGE or PACKAGE in resolved.parents, (path, target)
        item = {"file": path.relative_to(PACKAGE).as_posix(), "target": target}
        if (path.parent / local).exists():
            links.append(item)
        else:
            pending_links.append(item)
assert pending_links == [
    {"file": "README.md", "target": "independent_review/PACKAGE_AUDIT.md"},
    {"file": "README.md", "target": "PACKAGE_SHA256SUMS"},
    {"file": "TESTING.md", "target": "independent_review/PACKAGE_AUDIT.md"},
], pending_links
assert not [p for p in PACKAGE.rglob("*") if p.is_symlink()]
for name in inventory:
    path = PurePosixPath(name)
    assert not set(path.parts).intersection({"node_modules", ".git", "__pycache__", ".pytest_cache", "venv", "dist"})
    assert path.suffix not in {".parquet", ".csv", ".db", ".sqlite", ".zip", ".pdf", ".pem", ".key", ".png", ".jpg", ".pyc"}
secret_patterns = [re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
                   re.compile(rb"gh[pousr]_[A-Za-z0-9_]{30,}"),
                   re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}")]
assert not [name for name in inventory if any(pattern.search((PACKAGE / name).read_bytes()) for pattern in secret_patterns)]

verify_script = str(PACKAGE / "tools/verify_delivery.py")
run("provided_verify", [PYTHON, verify_script, "--package", str(PACKAGE)])
replay = json.loads(run("provided_replay", [PYTHON, str(PACKAGE / "tools/replay_delivery.py"),
                                           "--package", str(PACKAGE)]))
assert replay["status"] == "PASS" and replay["manifest_sha256"] == EXPECTED_MANIFEST

handoff = (PACKAGE / "HOST_HANDOFF.md").read_text()
snippets = re.findall(r"<<'PY'\n(.*?)\nPY", handoff, re.S)
assert len(snippets) == 1
snippet = snippets[0]
(HERE / "host_support_copy_snippet.py").write_text(snippet + "\n")
test_section = handoff.split("## 5.", 1)[1].split("## 6.", 1)[0]
test_blocks = re.findall(r"```bash\n(.*?)\n```", test_section, re.S)
assert len(test_blocks) == 1
test_block = test_blocks[0]
assert '(\ncd "$V4_REVIEW_ROOT/apps/web"\n' in test_block
(HERE / "host_test_commands.sh").write_text(test_block + "\n")
support_results = []
for scenario in ("missing_and_identical", "different_existing", "symlink_escape"):
    with tempfile.TemporaryDirectory(prefix="support-case-", dir=TEMP) as directory:
        target = Path(directory)
        if scenario == "missing_and_identical":
            row = support[0]
            path = target / row["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((PACKAGE / row["archive_path"]).read_bytes())
        elif scenario == "different_existing":
            path = target / support[-1]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Synthetic conflicting test helper\n")
        else:
            outside = target.parent / (target.name + "-outside")
            outside.mkdir()
            (target / "apps").symlink_to(outside, target_is_directory=True)
        before = snapshot(target)
        env = dict(ENV, V4_HANDOFF=str(PACKAGE), V4_REVIEW_ROOT=str(target))
        expected = 0 if scenario == "missing_and_identical" else 1
        output = run("support_" + scenario, [PYTHON, "-c", snippet], env=env, expected=expected)
        if expected == 0:
            assert snapshot(target) == {row["path"]: row["sha256"] for row in support}
            repeat = run("support_identical_repeat", [PYTHON, "-c", snippet], env=env)
            assert "added 0 support files" in repeat
        else:
            assert snapshot(target) == before
        if scenario == "symlink_escape":
            assert not list(outside.iterdir())
            outside.rmdir()
        support_results.append({"scenario": scenario, "expected_exit_code": expected,
                                "status": "PASS", "no_unintended_writes": True})

host_results = {}
archive = subprocess.check_output(["git", "-C", str(APP), "archive", BASE])
with tempfile.TemporaryDirectory(prefix="host-flow-", dir=TEMP) as directory:
    target = Path(directory)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="data")
    assert snapshot(target) == {row["path"]: row["sha256"] for row in assembly["files"]}
    for row in support:
        (target / row["path"]).unlink()
    for profile in profiles:
        run("host_before_" + profile, [PYTHON, verify_script, "--package", str(PACKAGE),
             "--profile", profile, "--source-root", str(target), "--against", "before"])
    for profile in profiles:
        patch = str(PACKAGE / manifest["profiles"][profile]["patch_path"])
        for options in (["--check"], []):
            run("host_forward_" + profile + ("_check" if options else ""),
                ["git", "-C", str(target), "apply", *options, patch])
    for profile in profiles:
        run("host_after_" + profile, [PYTHON, verify_script, "--package", str(PACKAGE),
             "--profile", profile, "--source-root", str(target), "--against", "after"])
    for row in manifest["files"]:
        assert sha((target / row["path"]).read_bytes()) == row["after_sha256"]
    env = dict(ENV, V4_HANDOFF=str(PACKAGE), V4_REVIEW_ROOT=str(target),
               V4_REVIEW_PYTHON=PYTHON, V4_REVIEW_NODE=NODE, V4_REVIEW_NODE_MODULES=NODE_MODULES,
               V4_TEST_SOURCE_ROOT=str(target), V4_TEST_PYTHON=PYTHON)
    run("host_support_copy", [PYTHON, "-c", snippet], env=env)
    xml = target / "three-channel-core-results.xml"
    output = run("host_tests", ["bash", "-eu", "-c", test_block], env=env, cwd=PACKAGE, timeout=60)
    cases = list(ET.parse(xml).getroot().iter("testcase"))
    assert len(cases) == 43 and not any(case.find("failure") is not None or case.find("error") is not None for case in cases)
    assert "25 passed" in output
    (HERE / "package_host_core_results.xml").write_bytes(xml.read_bytes())
    for row in manifest["files"]:
        assert sha((target / row["path"]).read_bytes()) == row["after_sha256"]
    for profile in reversed(profiles):
        patch = str(PACKAGE / manifest["profiles"][profile]["patch_path"])
        for options in (["--reverse", "--check"], ["--reverse"]):
            run("host_reverse_" + profile + ("_check" if "--check" in options else ""),
                ["git", "-C", str(target), "apply", *options, patch])
    for profile in profiles:
        run("host_restored_" + profile, [PYTHON, verify_script, "--package", str(PACKAGE),
             "--profile", profile, "--source-root", str(target), "--against", "before"])
    xml.unlink()
    (target / "apps/web/node_modules").unlink()
    assert snapshot(target) == {row["path"]: row["sha256"] for row in assembly["files"]}
    host_results = {"status": "PASS", "baseline_files_reconstructed": 1028,
                    "changed_after_images_verified": 13, "support_files_added": 16,
                    "core_python_passed": 43, "frontend_passed": 25,
                    "documented_patch_order_executed": profiles,
                    "documented_reverse_order_executed": list(reversed(profiles)),
                    "host_section_5_exact_shell_block_executed_from_package_cwd": True,
                    "host_section_5_shell_block_sha256": sha(test_block.encode()),
                    "full_1028_file_baseline_restored_after_removing_test_only_junit_and_symlink": True,
                    "temporary_directory_removed": True,
                    "Mac_native_acceptance": "NOT_RUN"}
assert snapshot(PACKAGE) == inventory
receipt = {
    "schema_version": "independent_three_channel_package_audit.v1",
    "status": "REVIEWED_PRE_FINAL_CHECKSUM_AND_REMOTE_READBACK",
    "package_root": str(PACKAGE), "source_manifest_sha256": EXPECTED_MANIFEST,
    "package_file_count_at_audit": len(inventory),
    "package_bytes_at_audit": sum((PACKAGE / name).stat().st_size for name in inventory),
    "payload_count": len(payloads), "runtime_files": 7, "changed_test_files": 6,
    "source_origin_and_reviewed_after_checks": "PASS", "unchanged_support_files_verified": 16,
    "preserved_files_verified": 3, "reused_verifier_tools_verified": 2,
    "provided_profile_replay": replay, "host_support_copy_probes": support_results,
    "documented_host_flow": host_results, "existing_markdown_links_verified": len(links),
    "source_review_evidence_files_sha256_and_bytes_verified": len(source_review_evidence),
    "external_local_markdown_links": [],
    "declared_pending_links": pending_links, "symlinks_or_forbidden_artifact_paths": [],
    "credential_pattern_matches": [], "package_unchanged_during_audit": True,
    "runtime_or_application_test_files_edited_by_reviewer": False,
    "package_findings": [{"id": "IR-PKG-01", "severity": "P2", "status": "RESOLVED",
                           "summary": "HOST frontend invocation lacked a required source cwd; package cwd collected no tests.",
                           "resolution": "Documented subshell changes to the isolated source apps/web directory before the same Vitest invocation.",
                           "runtime_or_test_changes": False,
                           "red_log": "package_host_web_initial_failure.log",
                           "green_log": "package_host_tests.log"}],
    "commands": commands, "audited_package_file_sha256": inventory,
    "not_run": ["Final PACKAGE_SHA256SUMS verification (generated after this report)",
                "Final ZIP and remote GitHub readback (publication occurs after this audit)",
                "Mac native acceptance", "Live API/UI acceptance", "Deployment", "Natural-session acceptance"],
}
(HERE / "package_audit_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({key: value for key, value in receipt.items()
                  if key not in {"commands", "audited_package_file_sha256", "provided_profile_replay"}}, indent=2))
