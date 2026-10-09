"""Audit the scoped baseline against the captured fixed remote tree and runtime diff."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
APP = ROOT / "app"
BASE = "7ca0190a721a7fd0fc0c88b79a872889867d111f"
SOURCE = "b19eb112bd641ca97cac1246af7c81d8873641f4"
RUNTIME = [
    "apps/api/v35_api/manager_research_router.py",
    "apps/web/src/api/managerWorkspace.ts",
    "ops/run_manager_daily_announcement.py",
    "upstreams/v3_shared_data/shared_data/hk_security_master.py",
    "v4/manager_research/plan_owner_dispatch.py",
    "v4/manager_research/workspace_announcements.py",
    "v4/manager_research/workspace_plan.py",
]
TESTS = [
    "apps/web/src/api/managerWorkspace.threeChannel.spec.ts",
    "tests/manager_three_channel_ui_fixture.py",
    "tests/test_manager_announcement_handoff_20261009.py",
    "tests/test_manager_us_mapping_three_channel_20261009.py",
    "tests/test_manager_three_channel_hk_reader.py",
    "tests/test_manager_screen_summary_contract.py",
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def git(*args, **kwargs):
    return subprocess.check_output(["git", "-C", str(APP), *args], **kwargs)


assembly = json.loads((ROOT / "evidence/assembly.json").read_text())
tree = json.loads((ROOT / "input/tree.json").read_text())
assert tree["sha"] == SOURCE and tree["truncated"] is False
entries = {row["path"]: row for row in tree["tree"]}
assert git("rev-parse", "HEAD").decode().strip() == BASE

# Read original bytes from the baseline Git objects; the worktree is not used
# for verifying a before-image that a writer has already modified.
records = assembly["files"]
requests = "".join(BASE + ":" + row["path"] + "\n" for row in records).encode()
batch = git("cat-file", "--batch", input=requests)
offset = 0
before = {}
for row in records:
    end = batch.index(b"\n", offset)
    blob, kind, count = batch[offset:end].split()
    assert kind == b"blob", row["path"]
    size = int(count)
    raw = batch[end + 1:end + 1 + size]
    assert batch[end + 1 + size:end + 2 + size] == b"\n"
    offset = end + 2 + size
    assert sha(raw) == row["sha256"] and size == row["bytes"], row["path"]
    assert git_blob(raw) == row["git_blob"] == blob.decode(), row["path"]
    assert row["fixed_source_paths"], row["path"]
    for remote_path in row["fixed_source_paths"]:
        assert entries[remote_path]["sha"] == row["git_blob"], remote_path
        assert entries[remote_path]["size"] == size, remote_path
    before[row["path"]] = sha(raw)
assert offset == len(batch)

input_manifest = json.loads((ROOT / "input/package_file_index.json").read_text())
input_verified = 0
for row in input_manifest:
    name = row["path"]
    raw = (ROOT / "input/remote" / name).read_bytes()
    assert git_blob(raw) == entries[name]["sha"]
    assert len(raw) == entries[name]["size"]
    input_verified += 1

changed = git("diff", "--name-only").decode().splitlines()
untracked = git("ls-files", "--others", "--exclude-standard").decode().splitlines()
assert set(changed) <= set(RUNTIME + TESTS), changed
assert set(untracked) <= set(TESTS + ["apps/web/node_modules"]), untracked
assert set(RUNTIME) <= set(changed)
assert (APP / "apps/web/node_modules").is_symlink()
identity = []
for name in RUNTIME + TESTS:
    raw = (APP / name).read_bytes()
    identity.append({"path": name, "role": "runtime" if name in RUNTIME else "test",
        "before_sha256": before.get(name), "after_sha256": sha(raw), "after_bytes": len(raw)})

receipt = {
    "classification": "INDEPENDENT_LOCAL_SOURCE_IDENTITY_AUDIT",
    "source_repository": "lexi2016/v4", "source_transport_commit": SOURCE,
    "declared_frozen_r3_candidate": "ca01c4d0260fecf7aae3c89e96899f36901bf8f7",
    "local_assembly_git_baseline": BASE, "runtime_root": str(APP),
    "remote_tree_basis": "Captured fixed-commit GitHub tree; no new remote lookup performed by this reviewer",
    "remote_tree_file_sha256": sha((ROOT / "input/tree.json").read_bytes()),
    "assembly_manifest_sha256": sha((ROOT / "evidence/assembly.json").read_bytes()),
    "baseline_files_verified": len(records), "input_files_verified": input_verified,
    "changed_tracked_paths": changed, "untracked_paths": untracked,
    "test_only_symlink_excluded_from_delivery": "apps/web/node_modules",
    "runtime_file_count": len(RUNTIME), "test_file_count": len(TESTS),
    "files": identity, "scope_check": "PASS", "status": "PASS",
    "not_current_deployment_identity": True,
}
(HERE / "source_identity_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({key: value for key, value in receipt.items() if key != "files"}, indent=2))
