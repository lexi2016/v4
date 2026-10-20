"""Prepare the approved r6+calendar overlay only. Never activate or fetch."""
from pathlib import Path
import hashlib
import importlib.util
import json
import plistlib
import re
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WT = HERE.parents[2]
SCOPE = json.loads((HERE / "DEPLOYMENT_SCOPE.json").read_bytes())
PARENT = Path(SCOPE["parent"])
CANDIDATE = Path(SCOPE["candidate"])
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert not CANDIDATE.exists(), "candidate exists; inspect identity, never overwrite"
    assert not (HERE / "DEPLOYMENT_PREPARED.json").exists()
    frozen = HERE / "PREPARED.json"
    assert sha(frozen) == SCOPE["source_prepared_sha256"]
    prepared = json.loads(frozen.read_bytes())
    assert sha(PLIST) == SCOPE["parent_plist_sha256"]
    assert sha(PARENT / "release-manifest.json") == SCOPE["parent_manifest_sha256"]
    assert plistlib.loads(PLIST.read_bytes())["WorkingDirectory"] == str(PARENT / "app")
    tool = PARENT / "app/ops/api_release_integration.py"
    spec = importlib.util.spec_from_file_location("retained_inventory", tool)
    inv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inv)
    old_manifest = json.loads((PARENT / "release-manifest.json").read_bytes())
    before = inv.inventory_tree(PARENT / "app")
    assert before == old_manifest["application_inventory"]["entries"]
    assert inv.inventory_digest(before) == old_manifest["application_inventory"]["aggregate_sha256"]
    build = HERE / SCOPE["build"]
    assert build.name == "candidate-build-r2"
    assert sha(build / ".vite/manifest.json") == prepared["local_build"]["manifest_sha256"]
    sources = SCOPE["overlay_source_sha256"]
    for relative, expected in sources.items():
        assert sha(WT / relative) == expected
        assert sha(PARENT / "app" / relative) == prepared["source_sha256"][relative]["before"]
        assert sha(HERE / "local_only/r6-source-r2" / relative) == expected
    additions = {
        "manager-selection/index.html": prepared["local_build"]["manager_selection_html"]["sha256"],
        **{r["path"]: r["sha256"] for r in prepared["local_build"]["manager_selection_assets"]
           if not r.get("active_release_same_bytes")},
    }
    assert set("apps/web/dist/" + path for path in additions) | set(sources) == set(SCOPE["FROZEN_DELTA"])
    for relative, expected in additions.items():
        assert sha(build / relative) == expected
    # Prove unchanged other-page build inputs and their actual referenced bytes.
    other_paths = set()
    for entry in ["index.html", "daily-research-command/index.html"]:
        assert (build / entry).read_bytes() == (PARENT / "app/apps/web/dist" / entry).read_bytes()
        other_paths.add(entry)
        for asset in re.findall(r'(?:src|href)="/(assets/[^"?]+)', (build / entry).read_text()):
            assert (build / asset).read_bytes() == (PARENT / "app/apps/web/dist" / asset).read_bytes()
            other_paths.add(asset)
    shared = next(r for r in prepared["local_build"]["manager_selection_assets"] if r.get("active_release_same_bytes"))
    assert sha(build / shared["path"]) == sha(PARENT / "app/apps/web/dist" / shared["path"]) == shared["sha256"]
    local = HERE / "local_only"
    original = PLIST.read_bytes()
    backup = local / "calendar-api-original.plist"
    assert not backup.exists(), "raw backup already exists; do not overwrite"
    backup.write_bytes(original)
    # Retain all existing root sidecars as historical parent bytes as well.
    shutil.copytree(PARENT, CANDIDATE, symlinks=True)
    for relative in sources:
        target = CANDIDATE / "app" / relative
        target.unlink()
        shutil.copy2(WT / relative, target)
    for relative in additions:
        target = CANDIDATE / "app/apps/web/dist" / relative
        if target.exists():
            assert relative == "manager-selection/index.html", "new hashed asset collision"
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / relative, target)
    after = inv.inventory_tree(CANDIDATE / "app")
    a, b = ({r["path"]: r for r in entries} for entries in [before, after])
    changed = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
    assert set(changed) == set(SCOPE["FROZEN_DELTA"])
    assert not a.keys() - b.keys(), "unexpected deletion"
    assert all(a[k] == b[k] for k in a.keys() - set(changed))
    all_dist = {str(p.relative_to(CANDIDATE / "app")) for p in (CANDIDATE / "app/apps/web/dist").rglob("*") if p.is_file()}
    assert all_dist == {k for k in b if k.startswith("apps/web/dist/")}
    delta = [{"path": p, "before": a.get(p), "after": b.get(p)} for p in changed]
    identity = dict(old_manifest["candidate"])
    identity.update(root=str(CANDIDATE), app_root=str(CANDIDATE / "app"), release_id=CANDIDATE.name)
    if identity.get("formal_release_root") == str(PARENT):
        identity["formal_release_root"] = str(CANDIDATE)
    sidecars = {f.name: sha(f) for f in PARENT.iterdir() if f.is_file() and f.name != "release-manifest.json"}
    assert all(sha(CANDIDATE / k) == digest for k, digest in sidecars.items())
    manifest = dict(schema_version="v4.release_candidate.v1", activation_status="PREPARED",
        candidate=identity, application_inventory=dict(entries=after, entry_count=len(after), aggregate_sha256=inv.inventory_digest(after)),
        task_overlay=dict(parent=str(PARENT), parent_manifest_sha256=SCOPE["parent_manifest_sha256"],
            source_worktree=str(WT), source_base_commit=prepared["base_commit"],
            source_prepared_sha256=sha(frozen), full_git_equivalence_claimed=False,
            delta=delta, all_non_delta_entries_preserved=True, parent_sidecars_retained_as_history=sidecars,
            build="active-r6 source/config/package + three approved source overlays; r2 output only"))
    (CANDIDATE / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    def rebind(value):
        if isinstance(value, str):
            return value.replace(str(PARENT), str(CANDIDATE)).replace(PARENT.name, CANDIDATE.name).replace(
                SCOPE["parent_manifest_sha256"], sha(CANDIDATE / "release-manifest.json"))
        if isinstance(value, list):return [rebind(v) for v in value]
        if isinstance(value, dict):return {k: rebind(v) for k, v in value.items()}
        return value
    old_plist = plistlib.loads(original)
    proposed = rebind(old_plist)
    def changed_fields(a, b, path=""):
        if isinstance(a, dict):
            assert a.keys() == b.keys()
            return [r for k in a for r in changed_fields(a[k], b[k], path + "/" + k)]
        if isinstance(a, list):
            assert len(a) == len(b)
            return [r for i, (x, y) in enumerate(zip(a, b)) for r in changed_fields(x, y, path + "/" + str(i))]
        return [] if a == b else [dict(path=path, before=a, after=b)]
    plist_delta = changed_fields(old_plist, proposed)
    assert all(isinstance(r["before"], str) and r["after"] == rebind(r["before"]) for r in plist_delta)
    assert proposed.get("RunAtLoad") == old_plist.get("RunAtLoad")
    assert proposed.get("KeepAlive") == old_plist.get("KeepAlive")
    proposal = local / "calendar-api-candidate.plist"
    assert not proposal.exists()
    proposal.write_bytes(plistlib.dumps(proposed, sort_keys=False))
    output = dict(state="PREPARED_PENDING_INDEPENDENT_CANDIDATE_REVIEW", source_prepared_sha256=sha(frozen),
        deployment_scope_sha256=sha(HERE / "DEPLOYMENT_SCOPE.json"), parent=str(PARENT), candidate=str(CANDIDATE),
        parent_manifest_sha256=SCOPE["parent_manifest_sha256"], candidate_manifest_sha256=sha(CANDIDATE / "release-manifest.json"),
        parent_inventory_sha256=inv.inventory_digest(before), candidate_inventory_sha256=inv.inventory_digest(after),
        parent_entry_count=len(before), candidate_entry_count=len(after), exact_delta=delta,
        all_non_delta_entries_preserved=True, all_dist_enumerated=True, dist_entry_count=len(all_dist),
        unchanged_root_daily_and_referenced_assets=sorted(other_paths), old_hashed_assets_preserved=True,
        shared_runtime_unchanged=shared, original_plist_sha256=sha(backup), proposed_plist_sha256=sha(proposal),
        plist_delta=plist_delta, full_git_equivalence_claimed=False,
        inventory_tool_sha256=sha(tool), source_overlay_sha256=sources,
        activated=False, research_data_writes=0, provider_calls=0, business_posts=0)
    (HERE / "DEPLOYMENT_PREPARED.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k not in {"exact_delta", "plist_delta"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
