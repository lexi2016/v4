"""The Mac blockers, with real filesystem copies and a non-root permission case."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(os.environ.get("R3_TOOLS_DIR", ROOT / "tools"))
EXTERNAL = "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260818T140000Z-v35-stage-input-owner/app/upstreams/v3.5"


def digest(raw):
    return sha256(raw).hexdigest()


def load_tool(name="prepare_canary"):
    spec = importlib.util.spec_from_file_location(name + "_adaptation", TOOLS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    return digest(path.read_bytes())


def inventory(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for path in [Path(directory), *(Path(directory) / name for name in dirs + files)]:
            name = str(path.relative_to(root))
            info = path.lstat()
            result[name] = {"mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid,
                            "gid": info.st_gid, "kind": stat.S_IFMT(info.st_mode)}
            if path.is_symlink():
                result[name]["link_text"] = os.readlink(path)
            elif path.is_file():
                result[name]["sha256"] = digest(path.read_bytes())
    return result


def policy_fixture(package, mapping, *, group="stage", roots=None):
    group_policy = {"copy_roots": roots or ["."], "optional_roots": [], "symlinks": []}
    if group == "stage":
        group_policy["symlinks"] = [
            {"relative_path": "v3_shared_data", "link_text": "upstreams/v3_shared_data",
             "action": "preserve_internal", "reason": "Configured internal shared dependency"},
            {"relative_path": "upstreams/v3.5", "link_text": EXTERNAL,
             "action": "quarantine", "reason": "Exact legacy source identity; dynamic Mac dependency unverified"},
        ]
    policy = {"schema_version": "V4_CANARY_SOURCE_POLICY_V1", "groups": {group: group_policy}}
    mapping["canary_source_policy_sha256"] = write_json(package / "CANARY_SOURCE_POLICY.json", policy)
    write_json(package / "SOURCE_MAP.json", mapping)
    return policy


def package_fixture(tmp_path, group="stage", *, add=False):
    source, package, destination = [tmp_path / name for name in ("actual", "package", "candidate")]
    source.mkdir(parents=True)
    paths = (["apps/web/src/App.vue", "apps/web/src/components/review/StageExecutionEvidencePanel.vue"]
             if group == "ui" else ["stage_center/runner.py", "stage_center/consumer.py"])
    entries = []
    for index, name in enumerate(paths):
        before, after = (f"before fixture {index}\n".encode(), f"after fixture {index}\n".encode())
        after_path = "after/" + group + "/" + name
        target = package / after_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(after)
        entry = {"group": group, "relative_path": name, "after_path": after_path,
                 "after_sha256": digest(after), "accepted_before_sha256": [digest(before)]}
        if add and index == 1:
            entry.update(operation="add", before_path=None, before_sha256=None, accepted_before_sha256=[])
        else:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(before)
        entries.append(entry)
    (source / "unchanged.txt").write_bytes(b"source identity must survive\n")
    mapping = {"files": entries}
    write_json(package / "SOURCE_MAP.json", mapping)
    return package, source, destination, mapping


def nonroot_prepare(tmp_path, package, source, destination, group):
    """Root CI enters an unmapped user namespace; the child reports uid 65534.

    It has no root identity/capabilities over the existing filesystem namespace.
    No parent workspace or source permission is changed by the test launcher.
    A normal non-root host runs the same real subprocess without a new namespace.
    """
    before = inventory(source)
    bootstrap = r'''
import importlib.util, json, os, sys, datetime, _strptime
from zoneinfo import ZoneInfo
ZoneInfo("Asia/Hong_Kong"); ZoneInfo("Asia/Shanghai")
tool_path, group, package, source, destination = sys.argv[1:]
spec = importlib.util.spec_from_file_location("nonroot_real_prepare", tool_path)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
result = module.prepare(package, group, source, destination)
print(json.dumps({"uid": os.geteuid(), "result": result}))
'''
    prefix = ["unshare", "--user"] if os.geteuid() == 0 else []
    run = subprocess.run([*prefix, sys.executable, "-B", "-c", bootstrap,
                          str(TOOLS / "prepare_canary.py"), group, str(package), str(source), str(destination)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    payload = json.loads(run.stdout)
    assert payload["uid"] != 0, "The Errno 13 regression must use a real non-root process"
    assert inventory(source) == before
    return payload


def test_readonly_copy_replaced_by_real_nonroot_process_and_permissions_restored(tmp_path):
    package, source, destination, mapping = package_fixture(tmp_path, "api")
    for path in (source, source / "stage_center"):
        path.chmod(0o555)
    for row in mapping["files"]:
        (source / row["relative_path"]).chmod(0o444)
    payload = nonroot_prepare(tmp_path, package, source, destination, "api")
    result = payload["result"]
    assert result["status"] == "CANARY_PREPARED", result
    assert result["permissions_restored"] is True
    for relative in (".", "stage_center"):
        assert stat.S_IMODE((destination / relative).stat().st_mode) == 0o555
    for row in mapping["files"]:
        target = destination / row["relative_path"]
        assert target.read_bytes() == (package / row["after_path"]).read_bytes()
        assert stat.S_IMODE(target.stat().st_mode) == 0o444


def test_declared_internal_dependency_kept_and_exact_external_link_quarantined(tmp_path):
    package, source, destination, mapping = package_fixture(tmp_path)
    policy_fixture(package, mapping)
    shared = source / "upstreams/v3_shared_data"
    shared.mkdir(parents=True)
    (shared / "dependency.py").write_bytes(b"shared original\n")
    (source / "v3_shared_data").symlink_to("upstreams/v3_shared_data")
    (source / "upstreams/v3.5").symlink_to(EXTERNAL)
    before = inventory(source)
    result = load_tool().prepare(package, "stage", source, destination)
    assert result["status"] == "CANARY_PREPARED", result
    assert os.readlink(destination / "v3_shared_data") == "upstreams/v3_shared_data"
    assert not os.path.lexists(destination / "upstreams/v3.5")
    assert inventory(source) == before
    manifest = json.loads((destination / "CANARY_SOURCE_MANIFEST.json").read_text())
    assert manifest["canary_source_policy_sha256"] == mapping["canary_source_policy_sha256"]
    assert manifest["quarantined_links"][0]["link_text"] == EXTERNAL
    assert manifest["quarantined_links"][0]["target_contents_read"] is False
    assert manifest["source_root"] == str(source)


def test_external_quarantine_is_never_followed_even_for_directory_classification(tmp_path, monkeypatch):
    package, source, destination, mapping = package_fixture(tmp_path)
    policy_fixture(package, mapping)
    (source / "upstreams").mkdir()
    (source / "upstreams/v3.5").symlink_to(EXTERNAL)
    module = load_tool()
    original_scandir = module.os.scandir
    original_stat = module.os.stat
    def stat_probe(path, *args, **kwargs):
        if not isinstance(path, int) and kwargs.get("follow_symlinks", True):
            value = os.fspath(path)
            assert value not in {str(source / "upstreams/v3.5"), EXTERNAL}, "stat followed the quarantined external target"
        return original_stat(path, *args, **kwargs)
    class EntryProbe:
        def __init__(self, entry):
            self.entry = entry
        def __getattr__(self, name):
            return getattr(self.entry, name)
        def __fspath__(self):
            return os.fspath(self.entry)
        def is_dir(self, *, follow_symlinks=True):
            assert not (follow_symlinks and self.entry.is_symlink()), "Directory classification followed an external link"
            return self.entry.is_dir(follow_symlinks=follow_symlinks)
        def stat(self, *, follow_symlinks=True):
            assert not (follow_symlinks and self.entry.is_symlink()), "stat followed an external link"
            return self.entry.stat(follow_symlinks=follow_symlinks)
    class ScandirProbe:
        def __init__(self, iterator):
            self.iterator = iterator
        def __iter__(self):
            return self
        def __next__(self):
            return EntryProbe(next(self.iterator))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.iterator.__exit__(*args)
    monkeypatch.setattr(module.os, "scandir", lambda path: ScandirProbe(original_scandir(path)))
    monkeypatch.setattr(module.os, "stat", stat_probe)
    result = module.prepare(package, "stage", source, destination)
    assert result["status"] == "CANARY_PREPARED", result
    assert not os.path.lexists(destination / "upstreams/v3.5")


def test_ui_add_creates_only_declared_source_set_and_ignores_root_test_links(tmp_path):
    package, source, destination, mapping = package_fixture(tmp_path, "ui", add=True)
    policy_fixture(package, mapping, group="ui", roots=["apps/web"])
    temporary = source / ".pytest-tmp-a-online-1"
    temporary.mkdir()
    (temporary / "testcurrent").symlink_to("missing_unrelated_tmp")
    (source / "v3_shared_data").symlink_to("outside_ui")
    before = inventory(source)
    result = load_tool().prepare(package, "ui", source, destination)
    assert result["status"] == "CANARY_PREPARED", result
    assert result["files"][1]["status"] == "ADD_ABSENT"
    assert not (destination / temporary.name).exists()
    assert not os.path.lexists(destination / "v3_shared_data")
    assert not (destination / "unchanged.txt").exists()
    assert (destination / mapping["files"][1]["relative_path"]).read_bytes() == (package / mapping["files"][1]["after_path"]).read_bytes()
    assert inventory(source) == before


@pytest.mark.parametrize("kind", ["unknown_link", "external_escape", "changed_internal_text", "changed_external_text", "mapped_link", "occupied_add", "implicit_add", "wrong_policy_sha"])
def test_policy_does_not_allow_unknown_links_or_overwrite_unknown_or_missing_sources(tmp_path, kind):
    group = "ui" if kind in {"occupied_add", "implicit_add"} else "stage"
    package, source, destination, mapping = package_fixture(tmp_path, group, add=group == "ui")
    policy_fixture(package, mapping, group=group, roots=["apps/web"] if group == "ui" else None)
    if kind == "unknown_link":
        (source / "unknown").symlink_to("stage_center")
    elif kind == "external_escape":
        (source / "v3_shared_data").symlink_to("../outside")
    elif kind == "changed_internal_text":
        (source / "v3_shared_data").symlink_to("./upstreams/v3_shared_data")
    elif kind == "changed_external_text":
        (source / "upstreams").mkdir()
        (source / "upstreams/v3.5").symlink_to(EXTERNAL + "-different-release")
    elif kind == "mapped_link":
        path = source / mapping["files"][0]["relative_path"]
        path.unlink(); path.symlink_to(package / mapping["files"][0]["after_path"])
    elif kind == "occupied_add":
        path = source / mapping["files"][1]["relative_path"]
        path.parent.mkdir(parents=True); path.write_bytes(b"independent colleague work\n")
    elif kind == "implicit_add":
        mapping["files"][1].pop("operation")
        write_json(package / "SOURCE_MAP.json", mapping)
    else:
        (package / "CANARY_SOURCE_POLICY.json").write_bytes((package / "CANARY_SOURCE_POLICY.json").read_bytes() + b" ")
    before = inventory(source)
    result = load_tool().prepare(package, group, source, destination)
    assert result["status"] == "PREFLIGHT_FAILED", result
    assert result["write_performed"] is False
    assert not destination.exists()
    assert inventory(source) == before


def test_add_already_after_is_recognized_and_never_uses_unknown_preimage(tmp_path):
    package, source, destination, mapping = package_fixture(tmp_path, "ui", add=True)
    for row in mapping["files"]:
        path = source / row["relative_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((package / row["after_path"]).read_bytes())
    before = inventory(source)
    result = load_tool().prepare(package, "ui", source, inspect_only=True)
    assert result["status"] == "ALREADY_AFTER", result
    assert inventory(source) == before


@pytest.mark.parametrize("change", ["source_bytes", "target_bytes", "link_target", "target_symlink"])
def test_changes_during_copy_are_rejected_and_partial_copy_is_preserved(tmp_path, monkeypatch, change):
    package, source, destination, mapping = package_fixture(tmp_path)
    policy_fixture(package, mapping)
    if change == "link_target":
        shared = source / "upstreams/v3_shared_data"
        shared.mkdir(parents=True)
        (shared / "dependency.py").write_bytes(b"shared dependency\n")
        (source / "v3_shared_data").symlink_to("upstreams/v3_shared_data")
    module = load_tool()
    original_copy = module.shutil.copytree
    changed = False
    def copy_then_change(*args, **kwargs):
        nonlocal changed
        value = original_copy(*args, **kwargs)
        if not changed and Path(args[0]) == source:
            changed = True
            relative = mapping["files"][0]["relative_path"]
            if change == "source_bytes":
                (source / "unchanged.txt").write_bytes(b"concurrent source write\n")
            elif change == "target_bytes":
                (destination / relative).write_bytes(b"concurrent candidate write\n")
            elif change == "link_target":
                (source / "v3_shared_data").unlink()
                (source / "v3_shared_data").symlink_to("../outside")
            else:
                (destination / relative).unlink()
                (destination / relative).symlink_to(source / relative)
        return value
    monkeypatch.setattr(module.shutil, "copytree", copy_then_change)
    result = module.prepare(package, "stage", source, destination)
    assert result["status"] != "CANARY_PREPARED", result
    assert destination.exists(), "Do not remove evidence from a failed partial copy"
    assert result["write_performed"] is True
    retry = module.prepare(package, "stage", source, destination)
    assert retry["write_performed"] is False
    assert any("DESTINATION_ALREADY_EXISTS" in value for value in retry["errors"])
