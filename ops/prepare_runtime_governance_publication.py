"""Exact three-owner publication parameters; never changes a live plist/job."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import plistlib

from ops.prepare_f10_stage_binding import dump, inventory_tools, loaded_role, sha

LABELS = {"main": "com.lexi.v4.scheduler", "stage": "com.lexi.stage-center.scheduler", "api": "com.lexi.v4.api"}
IDENTITY = ("V4_APP_ROOT", "V4_RELEASE_ID", "V4_RELEASE_MANIFEST_PATH", "V4_RELEASE_MANIFEST_SHA256")


def omitted_owner_proof(ledger_root, release_id, app_root, *, first_date="00000000"):
    checked = []; matches = []
    root = Path(ledger_root) / "receipts/live"
    for date in sorted(root.iterdir()):
        if not date.is_dir() or date.name < first_date: continue
        for path in sorted(date.glob("*/*.dispatch-receipt.json")):
            raw = path.read_bytes(); row = json.loads(raw)
            checked.append({"path": str(path), "sha256": sha(raw)})
            if row.get("release_id") == release_id or row.get("app_root") == app_root:
                matches.append({"path": str(path), "sha256": sha(raw), "status": row.get("status"), "slot": row.get("slot")})
    return {"release_id": release_id, "app_root": app_root, "ledger_root": str(ledger_root), "first_date": first_date,
        "receipt_count": len(checked), "checked_receipts_sha256": sha(json.dumps(checked, sort_keys=True).encode()), "matching_receipts": matches,
        "admission": "ZERO_MATCHES_REQUIRED_UNDER_GUARD", "reason": "No valid hourly publication can exist without its bound dispatch completion; any match requires compatibility review"}


def prepare(candidate, output, batch1):
    if output.exists(): raise ValueError("PUBLICATION_OUTPUT_MUST_BE_NEW")
    candidate_receipt = json.loads((candidate / "candidate_receipt.json").read_bytes())
    first = json.loads((batch1 / "candidate_receipt.json").read_bytes())
    records = {}; original = {}; output.mkdir()
    for role, label in LABELS.items():
        before = candidate_receipt["live_preimages"][role]
        env = before["environment"]
        if loaded_role(label, Path(env["V4_APP_ROOT"]), env["V4_RELEASE_MANIFEST_SHA256"]) != before:
            raise ValueError("PUBLICATION_LIVE_PREIMAGE_DRIFT:" + role)
        path = Path(before["plist_path"]); raw = path.read_bytes()
        if sha(raw) != before["plist_sha256"]: raise ValueError("PUBLICATION_PLIST_CAS_DRIFT")
        original[role] = raw
        payload = plistlib.loads(raw); after = copy.deepcopy(payload)
        new = candidate_receipt["roles"][role]; app = new["app_root"]
        after["WorkingDirectory"] = app
        after["ProgramArguments"] = [arg.replace(env["V4_APP_ROOT"], app) for arg in payload["ProgramArguments"]]
        proposed_env = after["EnvironmentVariables"]
        proposed_env.update(dict(zip(IDENTITY, (app, new["release_id"], str(Path(app).parent / "release-manifest.json"), new["manifest_sha256"]))))
        if role != "api": proposed_env["PYTHONPATH"] = proposed_env["PYTHONPATH"].replace(env["V4_APP_ROOT"], app)
        if role == "stage": proposed_env["STAGE_CENTER_CONFIG"] = app + "/stage_center_tick_config.json"
        if role == "api": proposed_env["V4_MANUAL_COLLECTION_STAGE_CONFIG"] = app + "/config/api-v4_manual_collection_stage_config.json"
        newraw = plistlib.dumps(after, sort_keys=True)
        (output / (role + ".original.plist")).write_bytes(raw); (output / (role + ".proposed.plist")).write_bytes(newraw)
        records[role] = {"label": label, "preimage": {key: env[key] for key in IDENTITY}, "candidate": new,
            "original_plist": str(output / (role + ".original.plist")), "original_plist_sha256": sha(raw),
            "proposed_plist": str(output / (role + ".proposed.plist")), "proposed_plist_sha256": sha(newraw)}
    main_env = plistlib.loads(original["main"])["EnvironmentVariables"]
    proof = omitted_owner_proof(main_env["V4_DISPATCH_LEDGER_ROOT"], main_env["V4_RELEASE_ID"], main_env["V4_APP_ROOT"])
    if proof["matching_receipts"]: raise ValueError("OMITTED_MAIN_HAS_RECEIPTS_COMPATIBILITY_REQUIRED")
    protected = []
    for path in sorted((Path.home() / "Library/LaunchAgents").glob("com.lexi.*.plist")):
        label = plistlib.loads(path.read_bytes())["Label"]
        if label not in LABELS.values(): protected.append({"label": label, "plist_path": str(path), "plist_sha256": sha(path.read_bytes())})
    stage_app = Path(records["stage"]["candidate"]["app_root"])
    manual = Path(records["api"]["candidate"]["app_root"]) / "config/api-v4_manual_collection_stage_config.json"
    plan = {"schema_version": "v4.runtime_main_stage_api_publication.v1", "status": "PREPARED_NOT_AUTHORIZED_TO_ACTIVATE",
        "roles": records, "forward_order": ["main", "stage", "api"], "rollback_order": ["api", "stage", "main"],
        "main_binding": json.loads((stage_app / "stage_center_tick_config.json").read_bytes())["research_owner_binding"],
        "manual_config": {"after_path": str(manual), "after_sha256": sha(manual.read_bytes())},
        "protected_labels": protected, "protected_external": first["protected_external"], "preserved_panel_environment": first["preserved_panel_environment"],
        "omitted_main_owner_zero_proof": proof, "requires_future_explicit_activation_authorization": True,
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    dump(output / "publication-plan.json", plan)
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "output", "batch1"): parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args(); plan = prepare(args.candidate, args.output, args.batch1)
    print(json.dumps({"status": plan["status"], "plan_path": str(args.output / "publication-plan.json"), "omitted_owner_receipts": len(plan["omitted_main_owner_zero_proof"]["matching_receipts"])}))
