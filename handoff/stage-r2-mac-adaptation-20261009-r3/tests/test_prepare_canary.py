"""Real filesystem checks with explicitly synthetic source/package fixtures."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "prepare_canary.py"


def read_tool():
    assert SCRIPT.is_file(), "the exact-SHA canary preparation tool is missing"
    spec = importlib.util.spec_from_file_location("prepare_canary_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return sha256(data).hexdigest()


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and not p.is_symlink()}


def fixture_package(tmp_path):
    source = tmp_path / "actual_app_fixture"
    package = tmp_path / "reviewed_package_fixture"
    destination = tmp_path / "isolated_canary_fixture"
    source.mkdir()
    entries = []
    for relative, before, after in [
        ("stage_center/runner.py", b"# fixture before runner\n", b"# fixture after runner\n"),
        ("ops/tick.py", b"# fixture before tick\n", b"# fixture after tick\n"),
    ]:
        src = source / relative
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(before)
        after_path = "after/stage/" + relative
        dst = package / after_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(after)
        entries.append({"group": "stage", "relative_path": relative,
                        "accepted_before_sha256": [digest(before)],
                        "after_path": after_path, "after_sha256": digest(after)})
    (source / "unchanged.txt").write_bytes(b"fixture unchanged\n")
    (package / "SOURCE_MAP.json").write_text(json.dumps({"files": entries}), encoding="utf-8")
    return package, source, destination, entries


def test_all_source_sha_failures_are_reported_before_any_destination_write(tmp_path):
    package, source, destination, entries = fixture_package(tmp_path)
    for entry in entries:
        (source / entry["relative_path"]).write_bytes(b"unsupported fixture version\n")
    before = tree_bytes(tmp_path)
    result = read_tool().prepare(package, "stage", source, destination)
    assert result["status"] == "PREFLIGHT_FAILED"
    assert result["write_performed"] is False
    assert len(result["files"]) == 2
    for row, entry in zip(result["files"], entries):
        assert row["status"] == "SOURCE_SHA_MISMATCH"
        assert row["observed_sha256"] == digest(b"unsupported fixture version\n")
        assert row["accepted_before_sha256"] == entry["accepted_before_sha256"]
        assert row["after_sha256"] == entry["after_sha256"]
    assert not destination.exists()
    assert tree_bytes(tmp_path) == before


def test_matching_sources_make_independent_copy_with_exact_after_readback(tmp_path):
    package, source, destination, entries = fixture_package(tmp_path)
    for ignored in (".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"):
        (source / ignored).mkdir()
        (source / ignored / "ignored.txt").write_bytes(b"do not copy fixture\n")
    before = tree_bytes(source)
    result = read_tool().prepare(package, "stage", source, destination)
    assert result["status"] == "CANARY_PREPARED"
    assert result["write_performed"] is True
    assert result["source_files_changed"] == []
    for entry, row in zip(entries, result["files"]):
        assert (destination / entry["relative_path"]).read_bytes() == (package / entry["after_path"]).read_bytes()
        assert row["destination_sha256"] == entry["after_sha256"]
        assert (destination / entry["relative_path"]).stat().st_ino != (source / entry["relative_path"]).stat().st_ino
    assert (destination / "unchanged.txt").read_bytes() == before["unchanged.txt"]
    assert not any((destination / name).exists() for name in (".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"))
    assert tree_bytes(source) == before


def test_inspect_only_recognizes_already_after_without_writes(tmp_path):
    package, source, _, entries = fixture_package(tmp_path)
    for entry in entries:
        (source / entry["relative_path"]).write_bytes((package / entry["after_path"]).read_bytes())
    before = tree_bytes(tmp_path)
    result = read_tool().prepare(package, "stage", source, inspect_only=True)
    assert result["status"] == "ALREADY_AFTER"
    assert all(row["status"] == "ALREADY_AFTER" for row in result["files"])
    assert result["write_performed"] is False
    assert tree_bytes(tmp_path) == before


def test_every_packaged_after_sha_is_checked_even_other_group(tmp_path):
    package, source, destination, entries = fixture_package(tmp_path)
    after_path = package / "after/api/api.py"
    after_path.parent.mkdir(parents=True)
    after_path.write_bytes(b"wrong api after fixture\n")
    entries.append({"group": "api", "relative_path": "api.py", "accepted_before_sha256": [],
                    "after_path": "after/api/api.py", "after_sha256": digest(b"reviewed api fixture\n")})
    (package / "SOURCE_MAP.json").write_text(json.dumps({"files": entries}), encoding="utf-8")
    before = tree_bytes(tmp_path)
    result = read_tool().prepare(package, "stage", source, destination)
    assert result["status"] == "PREFLIGHT_FAILED"
    assert any(row["status"] == "PACKAGE_AFTER_SHA_MISMATCH" for row in result["package_files"])
    assert not destination.exists()
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize("kind", ["source_root_symlink", "source_tree_symlink", "destination_inside_source", "destination_existing", "destination_parent_symlink"])
def test_unsafe_paths_are_rejected_before_writes(tmp_path, kind):
    package, source, destination, _ = fixture_package(tmp_path)
    if kind == "source_root_symlink":
        link = tmp_path / "linked_source"
        link.symlink_to(source, target_is_directory=True)
        source = link
    elif kind == "source_tree_symlink":
        (source / "linked_unchanged.txt").symlink_to(source / "unchanged.txt")
    elif kind == "destination_inside_source":
        destination = source / "canary"
    elif kind == "destination_existing":
        destination.mkdir()
        (destination / "keep.txt").write_bytes(b"existing fixture must remain\n")
    else:
        link = tmp_path / "linked_destination_parent"
        link.symlink_to(tmp_path, target_is_directory=True)
        destination = link / "nested_canary"
    before = tree_bytes(tmp_path)
    result = read_tool().prepare(package, "stage", source, destination)
    assert result["status"] == "PREFLIGHT_FAILED"
    assert result["write_performed"] is False
    assert tree_bytes(tmp_path) == before


def test_cli_json_explains_all_sha_mismatches_and_has_nonzero_exit(tmp_path):
    package, source, destination, entries = fixture_package(tmp_path)
    (source / entries[0]["relative_path"]).write_bytes(b"unknown fixture\n")
    before = tree_bytes(tmp_path)
    assert SCRIPT.is_file(), "the exact-SHA canary preparation tool is missing"
    run = subprocess.run([sys.executable, "-B", str(SCRIPT), "--package", str(package),
                          "--group", "stage", "--source-root", str(source),
                          "--destination", str(destination)], capture_output=True, text=True, check=False)
    assert run.returncode == 3
    assert run.stderr == ""
    result = json.loads(run.stdout)
    assert result["status"] == "PREFLIGHT_FAILED"
    assert len(result["files"]) == 2
    assert result["files"][0]["status"] == "SOURCE_SHA_MISMATCH"
    assert result["files"][1]["status"] == "BEFORE_MATCH"
    assert not destination.exists()
    assert tree_bytes(tmp_path) == before
