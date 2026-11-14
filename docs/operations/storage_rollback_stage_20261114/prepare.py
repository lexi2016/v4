"""Seal detached forward/rollback V4 roles against exact source inventories."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
HELPER = HERE.parent / "prepool_repair_20261112/prepare_main_stage_candidate.py"
spec = importlib.util.spec_from_file_location("candidate_helpers", HELPER)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
clone_inventory, with_inventory, changed_paths = (
    helpers.clone_inventory, helpers.with_inventory, helpers.changed_paths)
ref, sha, load, save, require = helpers.ref, helpers.sha, helpers.load, helpers.save, helpers.require

FORWARD_RECEIPT_SHA = "9e87231de26130c93ccc2f499bfb3b055a504b379a38406a548cd78d8df7ee63"
LABELS = {"main": "com.lexi.v4.scheduler", "api": "com.lexi.v4.api",
          "stage": "com.lexi.stage-center.scheduler"}
LIVE_PLIST_SHA = {
    "main": "70db2af75ed395d62b46eb77294e0f9d9b98a791f13e94e0282eacebab49fde9",
    "api": "88ff9703f2fc5d2ff893dd356293d09d72f174c6251cefddee31b20cb8409c70",
    "stage": "a2f78aed2ff701bdff4796164c14d9a929b00e2d49de8d643f5a65c49b7ffc5c",
}
LIVE_MANIFEST_SHA = {
    "main": "d3ec529152c9a6b6a0c23acbc93704ff5b80a7fad1449b3618cc7a4cb5d9c6b7",
    "api": "47f9e83ea0bdfe9d8fee4c445ab4441e22afcdf384a94bc81553db928ee3bbdd",
    "stage": "7ca70aa89d931d559e15dafc0ed3a92d5d505f44cafe4ecfef545c8b4fcebd76",
}
SERVICE = "v4/manager_workbench/service.py"
STORE = "v4/manager_workbench/store.py"
STAGE_CONFIG = "stage_center_tick_config.json"
STAGE_ATTESTATION = "infrastructure/manager_input_attestation.py"
PATCHES = {
    "service": ("rollback-service.patch",
                "832cf305b77b7d17ee835fa0fd70cad695615ac6dbebeb859453fe4c99ed4536",
                "948fe929981481dcf7bbfa57a066ab2167ecc5a97de418b8937aea0d900ea9ea"),
    "main": ("rollback-store.patch",
             "0206e67a5c309fe038f1300ed9705622a7e16cb4f51f6ea16d4aa4870c9fc9ab",
             "398ab4b2f24e9b412dbfa30f894ac336eb208843049eac025e9ce2e57620492e"),
    "api": ("rollback-store.patch",
            "b71cd3591f2073c1150918f78e9c6b921e36c81772f1843b53914500d02b4331",
            "c52956b672505de07fcbee8486c0aaceb9a14bd4af37ace4a73f9d79ef1e7176"),
    "stage": ("stage-attestation.patch",
              "63408260062e5f32430a00990ef716d81b103b3090cf93374b4cc6112fdf5b17",
              "c4b6e6a68f458318cc7c81411d05185736d8e6ac8d5e9ff3aee3253efb6bffb2"),
}


def exact(reference):
    path = Path(reference["path"])
    require(path.is_absolute() and path.resolve() == path
            and sha(path) == reference["sha256"], "SOURCE_DRIFT:" + str(path))
    return path


def role_source(plist_ref, manifest_ref, role):
    plist_file, manifest_file = exact(plist_ref), exact(manifest_ref)
    plist = plistlib.loads(plist_file.read_bytes())
    env = plist["EnvironmentVariables"]
    manifest = load(manifest_file)
    app = Path(env["V4_APP_ROOT"])
    require(plist["Label"] == LABELS[role] and app.is_absolute() and app.resolve() == app
            and env["V4_RELEASE_MANIFEST_PATH"] == str(manifest_file)
            and env["V4_RELEASE_MANIFEST_SHA256"] == manifest_ref["sha256"]
            and env["V4_RELEASE_ID"] == manifest["release_id"]
            and str(app) == manifest["app_root"] and app.parent == manifest_file.parent,
            "ROLE_IDENTITY_DRIFT:" + role)
    return {"app": app, "manifest": manifest_ref, "metadata": manifest,
            "plist": plist_ref, "proposal": plist}


def owner(role):
    return {"app_root": str(role["app"]), "release_id": role["metadata"]["release_id"],
            "manifest_path": role["manifest"]["path"], "manifest_sha256": role["manifest"]["sha256"]}


def replace(path, data):
    temp = path.with_name("." + path.name + ".candidate")
    with temp.open("xb") as stream:
        stream.write(data)
    temp.chmod(path.stat().st_mode & 0o777)
    temp.replace(path)


def patched(source, patch_key):
    patch_name, before, expected = PATCHES[patch_key]
    require(sha(source) == before, "PATCH_BASE_MISMATCH:" + patch_key)
    data = subprocess.run(["/usr/bin/patch", "-s", "-F", "0", "-o", "-", str(source)],
                          input=(HERE / patch_name).read_bytes(), check=True,
                          stdout=subprocess.PIPE).stdout
    require(hashlib.sha256(data).hexdigest() == expected, "PATCH_RESULT_MISMATCH:" + patch_key)
    compile(data, str(source), "exec")
    return data


def seal(root, origin, release_id, deltas, generated_at, details):
    app = root / "app"
    before = clone_inventory(origin["app"], app, origin["metadata"])
    changed = {}
    for relative, contents in deltas.items():
        path = app / relative
        prior = sha(path)
        replace(path, contents)
        changed[relative] = {"before": prior, "after": sha(path)}
    manifest = with_inventory(origin["metadata"], app)
    require(set(changed_paths(before, manifest["application_inventory"]["entries"])) == set(deltas),
            "INVENTORY_SCOPE_DRIFT:" + release_id)
    candidate = manifest.get("candidate")
    if isinstance(candidate, dict):
        candidate.update(root=str(root), app_root=str(app), release_id=release_id)
    else:
        candidate = release_id
    manifest.update(app_root=str(app), release_id=release_id, candidate=candidate,
                    parent_release_root=str(Path(origin["manifest"]["path"]).parent),
                    parent_manifest_sha256=origin["manifest"]["sha256"], generated_at=generated_at,
                    activation_status="PREPARED_NOT_ACTIVATED", deployment_status="PREPARED",
                    storage_rollback_stage=details, source_delta=changed)
    return {"app": app, "metadata": manifest,
            "manifest": save(root / "release-manifest.json", manifest), "delta": changed}


def remap(value, paths):
    if isinstance(value, str):
        for before, after in paths.items():
            if value == str(before) or value.startswith(str(before) + "/"):
                return str(after) + value[len(str(before)):]
        return value
    if isinstance(value, dict):
        return {key: remap(item, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [remap(item, paths) for item in value]
    return value


def make_proposal(source, target, path, *, config=False, policy=None):
    proposal = remap(source["proposal"], {source["app"]: target["app"]})
    env = proposal["EnvironmentVariables"]
    env.update(V4_APP_ROOT=str(target["app"]), V4_RELEASE_ID=target["metadata"]["release_id"],
               V4_RELEASE_MANIFEST_PATH=target["manifest"]["path"],
               V4_RELEASE_MANIFEST_SHA256=target["manifest"]["sha256"])
    if config:
        env["STAGE_CENTER_CONFIG"] = str(target["app"] / STAGE_CONFIG)
    if policy is not None:
        env["V4_RESEARCH_RETENTION_POLICY"] = policy["path"]
        env["V4_RESEARCH_RETENTION_POLICY_SHA256"] = policy["sha256"]
    proposal["WorkingDirectory"] = str(target["app"])
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        plistlib.dump(proposal, stream, sort_keys=False)
    return ref(path)


def stage(config, root, origin, main, prior, generated_at, correction):
    result = deepcopy(config)
    historical = result["research_historical_owner_bindings"]
    for argument in prior:
        binding = owner(argument)
        if binding not in historical:
            historical.append(binding)
    transition = result["research_transition_owner_binding"]
    roots = [item["app_root"] for item in [owner(main), *historical, transition]]
    require(len(historical) == 14 + len(prior) <= 16 and len(roots) == len(set(roots)),
            "HISTORICAL_OWNER_SCOPE")
    result["research_owner_binding"] = owner(main)
    release_id = "v4-storage-rollback-stage-20261114-" + root.parent.name + "-stage"
    result["release_id"] = release_id
    config_bytes = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    sealed = seal(root, origin, release_id,
                  {STAGE_CONFIG: config_bytes, STAGE_ATTESTATION: correction}, generated_at,
                  {"mode": root.parent.name, "current_owner": owner(main),
                   "historical_owner_count": len(historical), "transition": transition,
                   "source_patches": {"historical_manifest": ref(HERE / "stage-attestation.patch")}})
    sealed["config"] = ref(sealed["app"] / STAGE_CONFIG)
    sealed["owners"] = {"current": owner(main), "historical": historical, "transition": transition}
    return sealed


def candidate_policy(root, base_policy, base_pins, base_att, origins, targets, proposals, generated_at):
    source_roots = {origins[role]["app"]: targets[role]["app"] for role in ("main", "api", "stage")}
    proposal_overrides = {
        str(Path.home() / "Library/LaunchAgents" / (LABELS[role] + ".plist")): proposals[role]
        for role in ("api", "stage")
    }
    def rebind(source):
        if source["path"] in proposal_overrides:
            return proposal_overrides[source["path"]].copy()
        original = Path(source["path"])
        destination = Path(remap(str(original), source_roots))
        if original == destination:
            exact(source)
            return source.copy()
        exact(source)
        return ref(destination)

    pins = deepcopy(base_pins)
    pins.update(expected_main_app_root=str(targets["main"]["app"]), generated_at=generated_at)
    pins["source_bindings"] = [rebind(source) for source in pins["source_bindings"]]
    att = deepcopy(base_att)
    for reader in att["consumers"]:
        if reader["plist_path"] in proposal_overrides:
            proposal = proposal_overrides[reader["plist_path"]]
            reader.update(plist_path=proposal["path"], plist_sha256=proposal["sha256"])
        reader["source_refs"] = [rebind(source) for source in reader.get("source_refs", [])]
    extra = ref(targets["stage"]["app"] / STAGE_ATTESTATION)
    next(reader for reader in att["consumers"] if reader["label"] == LABELS["stage"])["source_refs"].append(extra)
    att["source_bindings_enforcement"] = (
        "Candidate Stage and API plist refs use the exact detached proposals. "
        "Main owner sources are pinned and the Main proposal is sealed by the prepare receipt.")
    if extra not in pins["source_bindings"]:
        pins["source_bindings"].append(extra)
    path_sha = {source["path"]: source["sha256"] for source in pins["source_bindings"]}
    require(len(path_sha) == len(pins["source_bindings"]), "DUPLICATE_PIN_PATH")
    for reader in att["consumers"]:
        for source in reader.get("source_refs", []):
            require(path_sha.get(source["path"]) == source["sha256"], "READER_SOURCE_NOT_PINNED")
        if "plist_sha256" in reader:
            require(path_sha.get(reader["plist_path"]) == reader["plist_sha256"], "READER_PLIST_NOT_PINNED")
    for source in pins["source_bindings"]:
        exact(source)
    pins_ref = save(root / "managed-pins.json", pins)
    att_ref = save(root / "reader-attestation.json", att)
    policy = deepcopy(base_policy)
    policy.update(dry_run=True, auto_gc_enabled=False, managed_pin_inventory=pins_ref)
    policy["single_generation_lifecycle"]["reader_inventory"] = att_ref
    return {"policy": save(root / "policy.json", policy), "pins": pins_ref,
            "reader_attestation": att_ref, "matched_source_pins": len(path_sha)}


def summarize(role, proposal):
    return {"app_root": str(role["app"]), "manifest": role["manifest"],
            "source_delta": role.get("delta", {}), "proposed_plist": proposal,
            **{key: role[key] for key in ("owners", "config") if key in role}}


def build(root, forward_receipt):
    require(root.is_absolute() and root.resolve() == root
            and all(not (root / name).exists() and not (root / name).is_symlink()
                    for name in ("roles", "PREPARE_RECEIPT.json")),
            "NEW_ABSOLUTE_CANDIDATE_ROLES_REQUIRED")
    forward_path = exact({"path": str(forward_receipt), "sha256": FORWARD_RECEIPT_SHA})
    upstream = load(forward_path)
    require(upstream["status"] == "PREPARED_NOT_ACTIVATED" and upstream["gc"] is False,
            "UNSEALED_FORWARD_BASE")
    live = {}
    for role, label in LABELS.items():
        path = Path.home() / "Library/LaunchAgents" / (label + ".plist")
        plist = {"path": str(path), "sha256": LIVE_PLIST_SHA[role]}
        manifest_path = plistlib.loads(exact(plist).read_bytes())["EnvironmentVariables"]["V4_RELEASE_MANIFEST_PATH"]
        live[role] = role_source(plist, {"path": manifest_path, "sha256": LIVE_MANIFEST_SHA[role]}, role)
    r3 = {role: role_source(upstream[role + "_proposed"], upstream["roles"][role]["manifest"], role)
          for role in ("main", "api")}
    for role in r3:
        require(upstream["roles"][role]["based_on"] == live[role]["manifest"], "ROLE_BASE_DRIFT:" + role)
    stage_ref = upstream["stage_kept"]["config"]
    require(exact(stage_ref) == live["stage"]["app"] / STAGE_CONFIG
            and upstream["stage_kept"]["manifest"] == live["stage"]["manifest"], "STAGE_BASE_DRIFT")
    baseline_stage = load(stage_ref["path"])
    require(len(baseline_stage["research_historical_owner_bindings"]) == 14
            and baseline_stage["research_owner_binding"] == owner(live["main"]), "STAGE_OWNER_BASE_DRIFT")
    policy = load(exact(upstream["policy"]))
    require(policy["dry_run"] is True and policy["auto_gc_enabled"] is False, "GC_BUDGET_NOT_DRY_RUN")
    pins = load(exact(policy["managed_pin_inventory"]))
    att = load(exact(policy["single_generation_lifecycle"]["reader_inventory"]))
    actual = {live["api"]["plist"]["path"]: r3["api"]["plist"],
              live["stage"]["plist"]["path"]: live["stage"]["plist"]}
    for source in pins["source_bindings"]:
        physical = actual.get(source["path"], source)
        require(physical["sha256"] == source["sha256"], "BASE_PIN_SHA_DRIFT")
        exact(physical)
    correction = patched(live["stage"]["app"] / STAGE_ATTESTATION, "stage")
    service = patched(live["main"]["app"] / SERVICE, "service")
    require(sha(live["api"]["app"] / SERVICE) == PATCHES["service"][1], "API_SERVICE_BASE_DRIFT")
    stores = {role: patched(r3[role]["app"] / STORE, role) for role in r3}
    clone_bytes = sum(item["size"] for role in ("main", "api", "stage")
                      for item in live[role]["metadata"]["application_inventory"]["entries"])
    clone_bytes += sum(item["size"] for item in live["stage"]["metadata"]["application_inventory"]["entries"])
    free = shutil.disk_usage(root.parent).free
    require(free > 2 * clone_bytes + 512 * 1024 * 1024, "CANDIDATE_DISK_BUDGET")
    stamp = datetime.now(timezone.utc).isoformat()
    result = {"status": "PREPARED_NOT_ACTIVATED", "root": str(root), "base": ref(forward_path),
              "source": {"builder": ref(__file__), "helper": ref(HELPER)},
              "budget": {"available_before_bytes": free, "full_copy_ceiling_bytes": clone_bytes},
              "live_baseline": {role: {key: row[key] for key in ("manifest", "plist")} for role, row in live.items()},
              "dry_run": True, "auto_gc_enabled": False, "RESEARCH_ONLY": True,
              "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    origins = {**r3, "stage": live["stage"]}
    for group in ("forward", "rollback"):
        path = root / "roles" / group
        control = path / "control"
        control.mkdir(parents=True)
        if group == "forward":
            targets = dict(r3)
            prior = [live["main"]]
        else:
            targets = {
                role: seal(path / role, live[role], "v4-storage-rollback-stage-20261114-rollback-" + role,
                           {SERVICE: service, STORE: stores[role]}, stamp,
                           {"mode": "rollback", "forward_reader": r3[role]["manifest"],
                            "source_patches": {key: ref(HERE / PATCHES[key][0])
                                               for key in ("service", role)}})
                for role in ("main", "api")
            }
            prior = [live["main"], r3["main"]]
        targets["stage"] = stage(baseline_stage, path / "stage", live["stage"], targets["main"],
                                 prior, stamp, correction)
        proposed = {"stage": make_proposal(live["stage"], targets["stage"], path / "stage/proposed.plist", config=True)}
        proposed["api"] = make_proposal(r3["api"] if group == "forward" else live["api"], targets["api"],
                                        control / "proposed-api.plist" if group == "forward" else path / "api/proposed.plist")
        policy_output = candidate_policy(control, policy, pins, att, origins, targets, proposed, stamp)
        proposed["main"] = make_proposal(r3["main"] if group == "forward" else live["main"], targets["main"],
                                         control / "proposed-main.plist" if group == "forward" else path / "main/proposed.plist",
                                         policy=policy_output["policy"])
        result[group] = {"roles": {role: summarize(targets[role], proposed[role]) for role in LABELS},
                         "control": policy_output}
    for row in live.values():
        exact(row["manifest"])
        exact(row["plist"])
    exact(stage_ref)
    return save(root / "PREPARE_RECEIPT.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--forward-receipt", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.forward_receipt), ensure_ascii=False))
