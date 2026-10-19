"""Prepare one exact-parent producer clone; never launch/fetch/POST."""
from pathlib import Path
import hashlib
import importlib.util
import json
import plistlib
import shutil

HERE = Path(__file__).resolve().parent
WT = HERE.parents[3]
SCOPE = json.loads((HERE / "REPAIR_SCOPE.json").read_text())
PARENT = Path(SCOPE["producer_parent"])
CANDIDATE = PARENT.parent / "us-mapping-natural-producer-20261020-r1"
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v4.us-market-digest.plist")
FILES = [p for p in SCOPE["source_preimage_sha256"] if not p.startswith("tests/")]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert not CANDIDATE.exists(), "candidate exists; do not overwrite"
    assert not (HERE / "REPAIR_PREPARED.json").exists(), "prepared evidence exists"
    assert sha(PARENT / "release-manifest.json") == SCOPE["parent_manifest_sha256"]
    assert sha(PLIST) == SCOPE["original_plist_sha256"]
    inventory_source = PARENT.parent / "us-mapping-close-api-20261020-r1/app/ops/api_release_integration.py"
    spec = importlib.util.spec_from_file_location("retained_inventory", inventory_source)
    inv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inv)
    parent_manifest = json.loads((PARENT / "release-manifest.json").read_text())
    before = inv.inventory_tree(PARENT / "app")
    assert before == parent_manifest["application_inventory"]["entries"]
    for path in FILES:
        assert sha(PARENT / "app" / path) == SCOPE["source_preimage_sha256"][path]
    local = HERE / "local_only"
    local.mkdir(exist_ok=True)
    original = PLIST.read_bytes()
    (local / "natural-producer-original.plist").write_bytes(original)
    shutil.copytree(PARENT / "app", CANDIDATE / "app", symlinks=True)
    for path in FILES:
        target = CANDIDATE / "app" / path
        target.unlink()
        shutil.copy2(WT / path, target)
    after = inv.inventory_tree(CANDIDATE / "app")
    a, b = ({e["path"]: e for e in entries} for entries in (before, after))
    changed = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
    assert set(changed) == set(FILES)
    delta = [{"path": p, "before": a.get(p), "after": b.get(p)} for p in changed]
    identity = dict(parent_manifest["candidate"])
    identity.update(root=str(CANDIDATE), app_root=str(CANDIDATE / "app"), release_id=CANDIDATE.name)
    if identity.get("formal_release_root") == str(PARENT):
        identity["formal_release_root"] = str(CANDIDATE)
    manifest = dict(schema_version="v4.release_candidate.v1", activation_status="PREPARED",
        candidate=identity, application_inventory=dict(entries=after, entry_count=len(after),
            aggregate_sha256=inv.inventory_digest(after)), task_overlay=dict(parent=str(PARENT),
            parent_manifest_sha256=sha(PARENT / "release-manifest.json"), source_worktree=str(WT),
            source_base_commit=SCOPE["base_commit"], full_git_equivalence_claimed=False,
            role="producer", delta=delta, all_non_delta_entries_preserved=True))
    (CANDIDATE / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    def rebind(value):
        if isinstance(value, str):
            return value.replace(str(PARENT), str(CANDIDATE)).replace(PARENT.name, CANDIDATE.name).replace(
                SCOPE["parent_manifest_sha256"], sha(CANDIDATE / "release-manifest.json"))
        if isinstance(value, list):return [rebind(v) for v in value]
        if isinstance(value, dict):return {k: rebind(v) for k, v in value.items()}
        return value
    old = plistlib.loads(original)
    proposed = rebind(old)
    proposed["EnvironmentVariables"]["V4_US_MAPPING_WIRE_DIAGNOSTIC_DIR"] = str(local)
    assert proposed.get("RunAtLoad") is False and not proposed.get("KeepAlive")
    assert proposed["StartCalendarInterval"] == old["StartCalendarInterval"]
    for key in ["StartInterval", "WatchPaths", "QueueDirectories", "Sockets", "MachServices"]:
        assert proposed.get(key) == old.get(key)
    proposal = local / "natural-producer-candidate.plist"
    proposal.write_bytes(plistlib.dumps(proposed, sort_keys=False))
    result = dict(state="PREPARED_PENDING_INDEPENDENT_REVIEW", candidate=str(CANDIDATE),
        parent=str(PARENT), parent_manifest_sha256=sha(PARENT / "release-manifest.json"),
        manifest_sha256=sha(CANDIDATE / "release-manifest.json"),
        parent_inventory_sha256=inv.inventory_digest(before), candidate_inventory_sha256=inv.inventory_digest(after),
        delta=delta, all_non_delta_entries_preserved=True,
        original_plist_sha256=sha(PLIST), proposed_plist_sha256=sha(proposal),
        source_test_sha256={p: sha(WT / p) for p in SCOPE["source_preimage_sha256"]},
        diagnostic_directory=str(local), activated=False, provider_fetches=0, business_posts=0,
        inventory_tool_sha256=sha(inventory_source),
        natural_0415="FAIL_RETAINED", quote_format_fix="NOT_IMPLEMENTED_UNRESOLVED")
    (HERE / "REPAIR_PREPARED.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in {"delta", "source_test_sha256"}}, indent=2))


if __name__ == "__main__":
    main()
