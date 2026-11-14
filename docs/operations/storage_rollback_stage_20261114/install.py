"""Stage accepted V4 releases at permanent paths. The proposed plists are inert."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from prepare import (
    LABELS, STAGE_CONFIG, changed_paths, clone_inventory, exact, load, make_proposal,
    owner, ref, remap, replace, require, role_source, save, with_inventory,
)


RECEIPT_SHA = "ba5a710d3ab36e62feb9beac9c21b26b606516667f2f03778382c1ebfe7ae1e9"
ACCEPTANCE = {
    "CONTROLS_FORWARD_RECEIPT.json": "58a3c69795aed3ad55d02cef3a0cd348890cf06510406aa9772ea58278557dd8",
    "CONTROLS_ROLLBACK_RECEIPT.json": "6e005d106df9848a78268412416d64c3bf92c75ac5f9a954e5ac4009ad2f6a87",
    "STAGE_FORWARD_RECEIPT.json": "9a6aded34bd1781729a4e8dbef3b011c6f27ba851412d2f7edfbca3bc0b7f4bc",
    "STAGE_ROLLBACK_RECEIPT.json": "2e7908628d1f60a4926c103c5bb1771a3cf0ff0ff087cb4e9ee98c96dd9f81b7",
    "rollback-main-crash/WRITE_RECEIPT.json": "a60c3fb810fe58cd3427d9f4df1c9052f9a5785a38a6f4bfe543319c5cabe643",
    "rollback-api-interrupted/WRITE_RECEIPT.json": "8234dac7cffb49f0e6dd683a9cfc3b715786d61417422a9901ff1edcd523e923",
    "rollback-main-partial/WRITE_RECEIPT.json": "3e3af583af3a5d0c35f5cc7d5ff9141ec2e1808d9948988ca49f9ec3d08fc92e",
    "rollback-api-partial/WRITE_RECEIPT.json": "602a41ddf468bd1a719591a56081571dc72f2121e4c0cb31cb436cf203e468e2",
}
MODES = ("forward", "rollback")


def accepted(path):
    source = load(exact({"path": str(path), "sha256": RECEIPT_SHA}))
    require(source["status"] == "PREPARED_NOT_ACTIVATED" and source["dry_run"] is True
            and source["auto_gc_enabled"] is False, "SOURCE_CANDIDATE_STATUS_MISMATCH")
    verified = {}
    for name, sha in ACCEPTANCE.items():
        record = {"path": str(path.parent / "acceptance" / name), "sha256": sha}
        require(load(exact(record))["status"] == "PASS", "ACCEPTANCE_FAILED:" + name)
        verified[name] = record
    return source, verified


def reject_detached(value, roots):
    if isinstance(value, str):
        for root in roots:
            location = str(root)
            require(value != location and location + "/" not in value, "DETACHED_RUNTIME_REFERENCE:" + value)
    elif isinstance(value, dict):
        for child in value.values():
            reject_detached(child, roots)
    elif isinstance(value, list):
        for child in value:
            reject_detached(child, roots)


def install_role(path, source, release_id, created, *, stage_config=None):
    app = path / "app"
    prior = clone_inventory(source["app"], app, source["metadata"])
    if stage_config is not None:
        config_bytes = (json.dumps(stage_config, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        replace(app / STAGE_CONFIG, config_bytes)
    manifest = with_inventory(source["metadata"], app)
    changes = changed_paths(prior, manifest["application_inventory"]["entries"])
    require(changes == ([STAGE_CONFIG] if stage_config is not None else []), "APP_INVENTORY_DRIFT:" + release_id)
    candidate = manifest.get("candidate")
    if isinstance(candidate, dict):
        candidate.update(app_root=str(app), release_id=release_id, root=str(path))
    else:
        candidate = release_id
    manifest.update(
        app_root=str(app), release_id=release_id, candidate=candidate, generated_at=created,
        activation_status="PREPARED_NOT_ACTIVATED", deployment_status="PREPARED",
        parent_release_root=str(Path(source["manifest"]["path"]).parent),
        parent_manifest_sha256=source["manifest"]["sha256"],
        installed_from_accepted_candidate=source["manifest"],
        installed_path_delta=changes,
    )
    if stage_config is not None:
        manifest["storage_rollback_stage"].update(
            current_owner=stage_config["research_owner_binding"],
            historical_owner_count=len(stage_config["research_historical_owner_bindings"]),
        )
        manifest["source_delta"][STAGE_CONFIG]["after"] = ref(app / STAGE_CONFIG)["sha256"]
    seal = save(path / "release-manifest.json", manifest)
    return {"app": app, "manifest": seal, "metadata": manifest, "accepted_manifest": source["manifest"],
            "accepted_inventory_sha256": source["metadata"]["application_inventory"]["aggregate_sha256"],
            "delta_from_accepted": changes}


def stage_config(source, main, detached_forward, installed_forward, release_id, mode, detached_roots):
    config = load(exact(source["config"]))
    archive = config["research_historical_owner_bindings"]
    require(len(archive) == (15 if mode == "forward" else 16), "HISTORY_COUNT_DRIFT")
    if mode == "rollback":
        require(archive[-1] == owner(detached_forward), "ROLLBACK_FORWARD_OWNER_DRIFT")
        archive[-1] = owner(installed_forward)
    config["research_owner_binding"] = owner(main)
    config["release_id"] = release_id
    seen = {item["app_root"] for item in [*archive, config["research_owner_binding"],
                                         config["research_transition_owner_binding"]]}
    require(len(seen) == len(archive) + 2, "DUPLICATE_STAGE_OWNER")
    reject_detached(config, detached_roots)
    return config


def inherited_desktop_references(proposal, baseline, detached_roots):
    inherited = {}
    candidate_env, baseline_env = proposal["EnvironmentVariables"], baseline["EnvironmentVariables"]
    desktop = Path.home() / "Desktop"
    for key, value in candidate_env.items():
        if not isinstance(value, str) or not value.startswith("/"):
            continue
        path = Path(value)
        if not path.is_relative_to(desktop):
            continue
        reject_detached(value, detached_roots)
        require(baseline_env.get(key) == value and path.exists(), "UNPROVEN_DESKTOP_REF:" + key)
        # Some external roots are writable databases. Preserve their owner path
        # rather than sealing mutable state as a code dependency.
        inherited[key] = {"path": value, "kind": "directory" if path.is_dir() else "file",
                          "same_as_frozen_live_environment": True}
    return inherited


def projected_policy(root, controls, sources, targets, proposals, live, created, detached_roots):
    prior = load(exact(controls["policy"]))
    pins = load(exact(controls["pins"]))
    att = load(exact(controls["reader_attestation"]))
    proposals_by_old_path = {sources[role]["plist"]["path"]: role for role in ("api", "stage")}
    paths = {sources[role]["app"]: targets[role]["app"] for role in LABELS}

    def remap_ref(source):
        exact(source)
        role = proposals_by_old_path.get(source["path"])
        if role:
            return {"path": live[role]["plist"]["path"], "sha256": proposals[role]["sha256"]}
        installed = Path(remap(source["path"], paths))
        if str(installed) == source["path"]:
            return source.copy()
        return ref(installed)

    pins["source_bindings"] = [remap_ref(row) for row in pins["source_bindings"]]
    pins.update(expected_main_app_root=str(targets["main"]["app"]), generated_at=created)
    for row in att["consumers"]:
        if row["plist_path"] in proposals_by_old_path:
            entry = remap_ref({"path": row["plist_path"], "sha256": row["plist_sha256"]})
            row.update(plist_path=entry["path"], plist_sha256=entry["sha256"])
        row["source_refs"] = [remap_ref(source) for source in row["source_refs"]]
    att["source_bindings_enforcement"] = (
        "Stage and API use the exact live plist paths with their proposed post-switch SHAs. "
        "Main owner sources are pinned; Main's plist SHA is recorded outside its policy."
    )
    reject_detached(pins, detached_roots)
    reject_detached(att, detached_roots)
    pin_ref = save(root / "managed-pins.json", pins)
    att_ref = save(root / "reader-attestation.json", att)
    prior.update(dry_run=True, auto_gc_enabled=False, managed_pin_inventory=pin_ref)
    prior["single_generation_lifecycle"]["reader_inventory"] = att_ref
    reject_detached(prior, detached_roots)
    return {"policy": save(root / "policy.json", prior), "pins": pin_ref, "reader_attestation": att_ref}


def verify_controls(bundle, live, *, projected):
    proposals = {value["live_plist_path"]: value["proposed_plist"] for value in bundle["roles"].values()}
    controls = bundle["control"]
    policy = load(exact(controls["policy"]))
    pins = load(exact(controls["pins"]))
    att = load(exact(controls["reader_attestation"]))
    main = bundle["roles"]["main"]
    require(policy["dry_run"] is True and policy["auto_gc_enabled"] is False
            and policy["managed_pin_inventory"] == controls["pins"]
            and policy["single_generation_lifecycle"]["reader_inventory"] == controls["reader_attestation"]
            and pins["expected_main_app_root"] == main["app_root"], "CONTROL_POLICY_DRIFT")
    bindings = {row["path"]: row["sha256"] for row in pins["source_bindings"]}
    require(len(bindings) == len(pins["source_bindings"]) == 85, "CONTROL_SCOPE_DRIFT")
    substituted = {}
    for source in pins["source_bindings"]:
        proposal = proposals.get(source["path"]) if projected else None
        if proposal is not None:
            require(proposal["sha256"] == source["sha256"], "PROJECTED_PLIST_PIN_DRIFT")
            exact(proposal)
            substituted[source["path"]] = proposal
        else:
            exact(source)
    require(len(substituted) == (2 if projected else 0), "PROJECTED_PIN_COUNT")
    for row in att["consumers"]:
        if "plist_sha256" in row:
            require(bindings[row["plist_path"]] == row["plist_sha256"], "ATTESTED_PLIST_PIN_DRIFT")
        else:
            require(row["label"] == LABELS["main"], "UNATTESTED_PLIST_SHA")
        for source in row["source_refs"]:
            require(bindings[source["path"]] == source["sha256"], "ATTESTED_SOURCE_PIN_DRIFT")
    for role, item in bundle["roles"].items():
        proposal_ref = item["proposed_plist"]
        proposal = plistlib.loads(exact(proposal_ref).read_bytes())
        row = role_source(proposal_ref, item["manifest"], role)
        require(proposal["WorkingDirectory"] == str(row["app"]), "PROPOSAL_CWD_MISMATCH")
        if role == "main":
            env = proposal["EnvironmentVariables"]
            require(env["V4_RESEARCH_RETENTION_POLICY"] == controls["policy"]["path"]
                    and env["V4_RESEARCH_RETENTION_POLICY_SHA256"] == controls["policy"]["sha256"],
                    "MAIN_POLICY_BINDING_DRIFT")
        if projected:
            exact(live[role]["plist"])
        else:
            exact({"path": item["live_plist_path"], "sha256": proposal_ref["sha256"]})
    return {"status": "PASS", "pin_count": len(bindings), "reader_count": len(att["consumers"]),
            "dry_run": True, "auto_gc_enabled": False, "projected_plists": substituted}


def source_roles(source, mode):
    result = {}
    for role, part in source[mode]["roles"].items():
        row = role_source(part["proposed_plist"], part["manifest"], role)
        if role == "stage":
            row["config"] = part["config"]
        result[role] = row
    return result


def installed_ref(role, row, live, proposal, inherited):
    return {"app_root": str(row["app"]), "manifest": row["manifest"], "proposed_plist": proposal,
            "live_plist_path": live["plist"]["path"], "from_accepted_manifest": row["accepted_manifest"],
            "accepted_inventory_sha256": row["accepted_inventory_sha256"],
            "installed_inventory_sha256": row["metadata"]["application_inventory"]["aggregate_sha256"],
            "changed_app_files": row["delta_from_accepted"], "inherited_desktop_env": inherited,
            **({"config": ref(row["app"] / STAGE_CONFIG)} if role == "stage" else {})}


def install(root, receipt_path):
    require(root.is_absolute() and root.resolve() == root and not root.exists(),
            "NEW_PERMANENT_RELEASE_ROOT_REQUIRED")
    require(root.parent == Path.home() / "Library/Application Support/com.lexi.v4.local/candidates",
            "PERMANENT_RELEASE_ROOT_REQUIRED")
    source, acceptance = accepted(receipt_path)
    live = source["live_baseline"]
    for row in live.values():
        exact(row["plist"])
        exact(row["manifest"])
    original = {mode: source_roles(source, mode) for mode in MODES}
    pending_root = Path(source["base"]["path"]).parent
    detached_roots = [receipt_path.parent, pending_root]
    ceiling = sum(
        entry["size"] for mode in MODES for role in LABELS
        for entry in original[mode][role]["metadata"]["application_inventory"]["entries"]
    )
    free = shutil.disk_usage(root.parent).free
    require(free > 2 * ceiling + 512 * 1024 * 1024, "INSTALL_DISK_BUDGET")
    created = datetime.now(timezone.utc).isoformat()
    result = {"status": "INSTALLED_PATHS_PREPARED_NOT_ACTIVATED", "root": str(root),
              "source_receipt": {"path": str(receipt_path), "sha256": RECEIPT_SHA}, "acceptance": acceptance,
              "live_baseline": live, "budget": {"available_before_bytes": free, "full_copy_ceiling_bytes": ceiling},
              "source_script": ref(__file__), "dry_run": True, "auto_gc_enabled": False,
              "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    forward_main = None
    for mode in MODES:
        target = root / mode
        origin = original[mode]
        names = {role: root.name + "-" + mode + "-" + role for role in LABELS}
        roles = {role: install_role(target / role, origin[role], names[role], created)
                 for role in ("main", "api")}
        if mode == "forward":
            forward_main = roles["main"]
        config = stage_config(origin["stage"], roles["main"], original["forward"]["main"],
                              forward_main, names["stage"], mode, detached_roots)
        roles["stage"] = install_role(target / "stage", origin["stage"], names["stage"], created,
                                      stage_config=config)
        props = {role: make_proposal(origin[role], roles[role], target / role / "proposed.plist",
                                     config=role == "stage") for role in ("api", "stage")}
        controls = projected_policy(target / "control", source[mode]["control"], origin, roles, props,
                                    live, created, detached_roots)
        props["main"] = make_proposal(origin["main"], roles["main"], target / "main/proposed.plist",
                                      policy=controls["policy"])
        records = {}
        for role in LABELS:
            proposal = plistlib.loads(exact(props[role]).read_bytes())
            reject_detached(proposal, detached_roots)
            baseline = plistlib.loads(exact(live[role]["plist"]).read_bytes())
            inherited = inherited_desktop_references(proposal, baseline, detached_roots)
            records[role] = installed_ref(role, roles[role], live[role], props[role], inherited)
            subprocess.run(["/usr/bin/plutil", "-lint", props[role]["path"]], check=True,
                           stdout=subprocess.DEVNULL)
        bundle = {"roles": records, "control": controls, "stage_owners": {
            name: config["research_" + key] for name, key in (
                ("current", "owner_binding"), ("historical", "historical_owner_bindings"),
                ("transition", "transition_owner_binding"))}}
        bundle["projected_validation"] = verify_controls(bundle, live, projected=True)
        result[mode] = bundle
    return save(root / "INSTALL_RECEIPT.json", result)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("--root", type=Path, required=True)
    build.add_argument("--candidate-receipt", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--sha256", required=True)
    verify.add_argument("--mode", choices=MODES, required=True)
    location = verify.add_mutually_exclusive_group()
    location.add_argument("--live", action="store_true")
    location.add_argument("--current-from", choices=MODES,
                          help="Validate the current live bytes against this installed mode before projecting another mode.")
    args = parser.parse_args()
    if args.command == "prepare":
        result = install(args.root, args.candidate_receipt)
    else:
        receipt = load(exact({"path": str(args.receipt), "sha256": args.sha256}))
        current = receipt["live_baseline"]
        if args.current_from:
            current = {role: {"plist": {"path": item["live_plist_path"],
                                        "sha256": item["proposed_plist"]["sha256"]}}
                       for role, item in receipt[args.current_from]["roles"].items()}
        result = verify_controls(receipt[args.mode], current, projected=not args.live)
    print(json.dumps(result, ensure_ascii=False))
