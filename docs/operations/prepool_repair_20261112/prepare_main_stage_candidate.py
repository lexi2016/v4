"""Prepare the frozen two-file Main delta plus Stage owner-control repin.

Reuses the deployed inventory / APFS clone / policy-pin pattern from
prepare_daily_result_receipt_release.py and prepare_stage_owner_repin_r3.py.
Never activates, writes live plists, runs producers, or changes Stage code.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))
from ops.api_release_integration import inventory_tree, inventory_digest


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    return {"path": str(path), "sha256": sha(path)}


def load(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return ref(path)


def clone_inventory(source, target, manifest):
    entries = manifest["application_inventory"]["entries"]
    require(inventory_digest(entries) == manifest["application_inventory"]["aggregate_sha256"], "INVENTORY_AGGREGATE_DRIFT")
    target.mkdir(parents=True)
    for entry in entries:
        src, dst = source / entry["path"], target / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if entry["kind"] == "symlink":
            link = os.readlink(src)
            require(hashlib.sha256(link.encode()).hexdigest() == entry["sha256"], "SOURCE_SYMLINK_DRIFT")
            dst.symlink_to(link)
        else:
            require(sha(src) == entry["sha256"], "SOURCE_FILE_DRIFT:" + entry["path"])
            cloned = subprocess.run(["/bin/cp", "-c", "-p", str(src), str(dst)], capture_output=True)
            if cloned.returncode:
                require(not dst.exists(), "PARTIAL_CLONE_EXISTS")
                shutil.copy2(src, dst)
    require(inventory_tree(target) == entries, "CLONED_INVENTORY_DRIFT")
    return entries


def changed_paths(before, after):
    require(len(before) == len(after), "INVENTORY_COUNT_CHANGED")
    require([e["path"] for e in before] == [e["path"] for e in after], "INVENTORY_PATHS_CHANGED")
    return [a["path"] for a, b in zip(before, after) if a != b]


def with_inventory(manifest, app):
    result = copy.deepcopy(manifest)
    entries = inventory_tree(app)
    result["application_inventory"] = {"entry_count": len(entries), "entries": entries,
                                         "aggregate_sha256": inventory_digest(entries)}
    result["app_files"] = [{k: e[k] for k in ("path", "sha256", "size")} for e in entries]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-main-manifest-sha256", required=True)
    parser.add_argument("--expected-stage-manifest-sha256", required=True)
    args = parser.parse_args()
    root = args.candidate_root
    require(root.is_absolute() and not root.exists(), "NEW_ABSOLUTE_CANDIDATE_REQUIRED")
    main_live = Path.home() / "Library/LaunchAgents/com.lexi.v4.scheduler.plist"
    stage_live = Path.home() / "Library/LaunchAgents/com.lexi.stage-center.scheduler.plist"
    main_raw, stage_raw = main_live.read_bytes(), stage_live.read_bytes()
    main_plist, stage_plist = plistlib.loads(main_raw), plistlib.loads(stage_raw)
    me, se = main_plist["EnvironmentVariables"], stage_plist["EnvironmentVariables"]
    old_main, old_stage = Path(me["V4_APP_ROOT"]), Path(se["V4_APP_ROOT"])
    old_main_seal, old_stage_seal = Path(me["V4_RELEASE_MANIFEST_PATH"]), Path(se["V4_RELEASE_MANIFEST_PATH"])
    require(me["V4_RELEASE_MANIFEST_SHA256"] == sha(old_main_seal) == args.expected_main_manifest_sha256, "MAIN_SOURCE_IDENTITY_DRIFT")
    require(se["V4_RELEASE_MANIFEST_SHA256"] == sha(old_stage_seal) == args.expected_stage_manifest_sha256, "STAGE_SOURCE_IDENTITY_DRIFT")
    delta_path = Path(__file__).with_name("RUNTIME_DELTA.json")
    delta = load(delta_path)
    require(str(old_main) == delta["origin_app_root"] and sha(old_main_seal) == delta["origin_manifest_sha256"], "INLINE_DELTA_ORIGIN_DRIFT")
    policy_path = Path(me["V4_RESEARCH_RETENTION_POLICY"])
    require(sha(policy_path) == me["V4_RESEARCH_RETENTION_POLICY_SHA256"], "MAIN_POLICY_DRIFT")
    policy = load(policy_path)
    pin_ref, att_ref = policy["managed_pin_inventory"], policy["single_generation_lifecycle"]["reader_inventory"]
    require(sha(pin_ref["path"]) == pin_ref["sha256"], "MAIN_PINS_DRIFT")
    require(sha(att_ref["path"]) == att_ref["sha256"], "MAIN_READERS_DRIFT")
    pins, att = load(pin_ref["path"]), load(att_ref["path"])
    # Controller accepted exactly the already deployed membership transition.
    # Every other stale pin still blocks before candidate writes.
    membership = old_stage.parent.parent
    membership_before = membership / "before-stage.plist"
    membership_proposed = membership / "proposed-stage.plist"
    stale_stage_sha = "24355058e5aacf2df8cfe0d3c1269f1ea012aff2b2d4be0544ac584223a15af6"
    actual_stage_sha = "10212fdf1526e88b7a654a9161a0028fd6e66a3479fd2e106b32726e1ecc4dfd"
    require(sha(membership_before) == stale_stage_sha, "MEMBERSHIP_BEFORE_PLIST_DRIFT")
    require(sha(membership_proposed) == actual_stage_sha, "MEMBERSHIP_PROPOSED_PLIST_DRIFT")
    require(membership_proposed.read_bytes() == stage_raw, "MEMBERSHIP_LIVE_PLIST_NOT_EXACT")
    accepted_transition = dict(reason="Controller accepted only the previously deployed membership transition",
        previous_plist=ref(membership_before), deployed_proposal=ref(membership_proposed),
        actual_live_plist=ref(stage_live), stage_manifest=ref(old_stage_seal))
    for source in pins["source_bindings"]:
        if source["path"] == str(stage_live):
            require(source["sha256"] == stale_stage_sha, "STALE_STAGE_PIN_OUTSIDE_ACCEPTED_TRANSITION")
        else:
            require(sha(source["path"]) == source["sha256"], "OLD_SOURCE_PIN_DRIFT:" + source["path"])
    for consumer in att["consumers"]:
        for source in consumer.get("source_refs", []):
            require(sha(source["path"]) == source["sha256"], "OLD_READER_SOURCE_DRIFT")
    selected = [c for c in att["consumers"] if c["label"] == stage_plist["Label"]]
    require(len(selected) == 1, "EXACT_STAGE_READER_REQUIRED")
    stage_consumer = selected[0]
    require(stage_consumer["plist_path"] == str(stage_live) and stage_consumer["plist_sha256"] == stale_stage_sha, "STAGE_READER_PLIST_DRIFT")
    stage_refs_before = copy.deepcopy(stage_consumer["source_refs"])
    require(len(stage_refs_before) == 3, "THREE_STAGE_SOURCE_REFS_REQUIRED")
    stage_relative = ("stage_center/_runner_parts/a_name_authority.py", "stage_center/runner.py", "stage_center_tick_config.json")
    require(all(source["path"].endswith("/" + rel) for source, rel in zip(stage_refs_before, stage_relative)), "STAGE_SOURCE_REF_SCOPE_DRIFT")
    for source, relative in zip(stage_refs_before[:2], stage_relative[:2]):
        require(sha(old_stage / relative) == source["sha256"], "MEMBERSHIP_STAGE_READER_CODE_DRIFT")
    accepted_transition["stage_reader_sources"] = [dict(previous=source,
        actual_membership=ref(old_stage / relative)) for source, relative in zip(stage_refs_before, stage_relative)]
    stage_config_before = load(se["STAGE_CENTER_CONFIG"])
    require(Path(se["STAGE_CENTER_CONFIG"]) == old_stage / "stage_center_tick_config.json", "STAGE_CONFIG_PATH_DRIFT")
    old_owner = stage_config_before["research_owner_binding"]
    require(old_owner == dict(app_root=str(old_main), release_id=me["V4_RELEASE_ID"], manifest_path=str(old_main_seal), manifest_sha256=sha(old_main_seal)), "CURRENT_STAGE_OWNER_MISMATCH")
    require(len(stage_config_before["research_historical_owner_bindings"]) == 10, "EXPECTED_TEN_HISTORICAL_OWNERS")
    main_app, stage_app = root / "main/app", root / "stage/app"
    main_before = clone_inventory(old_main, main_app, load(old_main_seal))
    subprocess.run([sys.executable, str(Path(__file__).with_name("apply_runtime_delta.py")), "--app-root", str(main_app), "--action", "apply"], check=True)
    main_manifest = with_inventory(load(old_main_seal), main_app)
    main_changed = changed_paths(main_before, main_manifest["application_inventory"]["entries"])
    require(set(main_changed) == set(delta["files"]), "MAIN_DIFF_EXCEEDS_TWO_FILES")
    now = datetime.now(timezone.utc).isoformat()
    main_id, stage_id = root.name + "-main", root.name + "-stage"
    main_manifest.update(app_root=str(main_app), release_id=main_id, candidate=root.name,
        parent_release_root=str(old_main_seal.parent), parent_manifest_sha256=sha(old_main_seal), generated_at=now,
        source_root=str(WORKTREE), source_commit=delta["baseline_commit"], activation_status="PREPARED_NOT_ACTIVATED", deployment_status="PREPARED")
    main_manifest["preselection_publication_repair"] = dict(runtime_delta=ref(delta_path),
        writer_binding=ref(Path(__file__).with_name("SOURCE_BINDING.json")), independent_review="REQUIRED_BEFORE_ACTIVATION",
        immutable_source_delta=main_changed, numerical_formula_BUY_changes=False)
    main_seal = save(root / "main/release-manifest.json", main_manifest)
    stage_before = clone_inventory(old_stage, stage_app, load(old_stage_seal))
    config = copy.deepcopy(stage_config_before)
    config["research_owner_binding"] = dict(app_root=str(main_app), release_id=main_id,
        manifest_path=main_seal["path"], manifest_sha256=main_seal["sha256"])
    config["research_historical_owner_bindings"].append(copy.deepcopy(old_owner))
    require(len({r["app_root"] for r in [config["research_owner_binding"], *config["research_historical_owner_bindings"]]}) == 12, "OWNER_ROOT_DUPLICATE")
    require(config["research_transition_owner_binding"] == stage_config_before["research_transition_owner_binding"], "TRANSITION_CHANGED")
    config["release_id"] = stage_id
    config_path = stage_app / "stage_center_tick_config.json"
    os.chmod(config_path, 0o644)
    save(config_path, config)
    stage_manifest = with_inventory(load(old_stage_seal), stage_app)
    stage_changed = changed_paths(stage_before, stage_manifest["application_inventory"]["entries"])
    require(stage_changed == ["stage_center_tick_config.json"], "STAGE_CODE_CHANGED")
    stage_manifest.update(app_root=str(stage_app), release_id=stage_id, candidate=root.name,
        parent_release_root=str(old_stage_seal.parent), parent_manifest_sha256=sha(old_stage_seal), generated_at=now,
        activation_status="PREPARED_NOT_ACTIVATED", deployment_status="PREPARED")
    stage_manifest["preselection_main_owner_repin"] = dict(source_script=ref(__file__), previous_history_count=10,
        historical_count=11, previous_current_owner=old_owner, transition_unchanged=True, code_bytes_changed=False)
    stage_seal = save(root / "stage/release-manifest.json", stage_manifest)
    def remap(value):
        if isinstance(value, str):
            for before, after in ((old_main, main_app), (old_stage, stage_app)):
                if value == str(before) or value.startswith(str(before) + "/"):
                    return str(after) + value[len(str(before)):]
            return value
        if isinstance(value, list): return [remap(v) for v in value]
        if isinstance(value, dict): return {k: remap(v) for k, v in value.items()}
        return value
    stage_proposed = remap(copy.deepcopy(stage_plist))
    stage_proposed["EnvironmentVariables"].update(V4_APP_ROOT=str(stage_app), V4_RELEASE_ID=stage_id,
        V4_RELEASE_MANIFEST_PATH=stage_seal["path"], V4_RELEASE_MANIFEST_SHA256=stage_seal["sha256"], STAGE_CENTER_CONFIG=str(config_path))
    stage_proposed["WorkingDirectory"] = str(stage_app)
    stage_plist_path = root / "stage/proposed.plist"
    stage_plist_path.write_bytes(plistlib.dumps(stage_proposed, sort_keys=False))
    (root / "stage/before.plist").write_bytes(stage_raw)
    # Stage source pins still name the previous control-only clone. Rebind
    # exactly those three registered paths to the actual current Stage clone.
    stage_mapping = {s["path"]: str(stage_app / rel) for s, rel in zip(stage_refs_before, stage_relative)}
    pin_changes = []
    for index, source in enumerate(pins["source_bindings"]):
        before = copy.deepcopy(source)
        if source["path"] == str(stage_live):
            source["sha256"] = sha(stage_plist_path)
        else:
            mapped = stage_mapping.get(source["path"], remap(source["path"]))
            source.update(ref(Path(mapped)))
        if before != source:
            pin_changes.append(dict(index=index, before=before, proposed=copy.deepcopy(source)))
    require(sum(x["before"]["path"] in stage_mapping for x in pin_changes) == 3, "THREE_STAGE_PIN_REBINDS_REQUIRED")
    require(sum(x["before"]["path"] == str(stage_live) for x in pin_changes) == 1, "STAGE_PLIST_PIN_REBIND_REQUIRED")
    pins.update(expected_main_app_root=str(main_app), generated_at=now)
    new_pins = save(root / "main-control/research_storage_pins.json", pins)
    for consumer in att["consumers"]:
        if consumer["label"] == stage_plist["Label"]:
            consumer["plist_sha256"] = sha(stage_plist_path)
            consumer["source_refs"] = [ref(Path(stage_mapping[s["path"]])) for s in consumer["source_refs"]]
        else:
            consumer["source_refs"] = [ref(Path(remap(s["path"]))) for s in consumer.get("source_refs", [])]
    new_att = save(root / "main-control/reader-attestation.json", att)
    policy["managed_pin_inventory"] = new_pins
    policy["single_generation_lifecycle"]["reader_inventory"] = new_att
    new_policy = save(root / "main-control/research_storage_policy.json", policy)
    main_proposed = remap(copy.deepcopy(main_plist))
    main_proposed["EnvironmentVariables"].update(V4_APP_ROOT=str(main_app), V4_RELEASE_ID=main_id,
        V4_RELEASE_MANIFEST_PATH=main_seal["path"], V4_RELEASE_MANIFEST_SHA256=main_seal["sha256"],
        V4_RESEARCH_RETENTION_POLICY=new_policy["path"], V4_RESEARCH_RETENTION_POLICY_SHA256=new_policy["sha256"])
    main_proposed["WorkingDirectory"] = str(main_app)
    main_plist_path = root / "main-control/proposed.plist"
    main_plist_path.write_bytes(plistlib.dumps(main_proposed, sort_keys=False))
    (root / "main-control/before.plist").write_bytes(main_raw)
    require(main_live.read_bytes() == main_raw and stage_live.read_bytes() == stage_raw, "LIVE_PLISTS_CHANGED_DURING_PREPARE")
    require(sha(policy_path) == me["V4_RESEARCH_RETENTION_POLICY_SHA256"], "LIVE_POLICY_CHANGED_DURING_PREPARE")
    result = dict(status="PREPARED_NOT_ACTIVATED", root=str(root), no_live_actions=True,
        source_script=ref(__file__), runtime_delta=ref(delta_path),
        accepted_existing_membership_transition=accepted_transition,
        main=dict(app_root=str(main_app), manifest=main_seal, inventory_changed=main_changed,
            live_plist=str(main_live), before_plist=ref(root / "main-control/before.plist"), proposed_plist=ref(main_plist_path),
            before_policy=ref(policy_path), proposed_policy=new_policy, proposed_pins=new_pins, proposed_reader_attestation=new_att),
        stage=dict(app_root=str(stage_app), manifest=stage_seal, inventory_changed=stage_changed, code_bytes_changed=False,
            config=ref(config_path), previous_history_count=10, historical_count=11, transition_unchanged=True,
            live_plist=str(stage_live), before_plist=ref(root / "stage/before.plist"), proposed_plist=ref(stage_plist_path)),
        pin_changes=pin_changes, activation_precondition="Independent incremental review; controller verifies every current before identity and applies existing coordinated owner transition. No activation by this script.",
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    receipt = save(root / "PREPARE_RECEIPT.json", result)
    save(args.evidence_root / "PREPOOL_MAIN_STAGE_PREPARE.json", result)
    print(json.dumps(dict(status=result["status"], receipt=receipt, main_changed=main_changed, stage_changed=stage_changed)))


if __name__ == "__main__":
    main()
