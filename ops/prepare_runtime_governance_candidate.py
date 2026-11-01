"""Fresh inactive Stage/API F10 candidates; actual releases are the copy base."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import plistlib
import subprocess

from ops import prepare_f10_stage_binding as existing


def prepare(output: Path, source: Path):
    pins = {}
    for role, (label, _, _) in existing.ROLE_PINS.items():
        payload = plistlib.loads((Path.home() / "Library/LaunchAgents" / (label + ".plist")).read_bytes())
        env = payload["EnvironmentVariables"]
        pins[role] = (label, Path(env["V4_APP_ROOT"]), env["V4_RELEASE_MANIFEST_SHA256"])
    existing.ROLE_PINS = pins
    existing.SOURCE_BASELINE = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    receipt = existing.prepare(output, source)
    roles = {}
    for role in ("stage", "api"):
        before = receipt["actual_role_baselines"][role]
        proposal = receipt["release_proposal"][role]
        roles[role] = {"label": before["label"], "preimage": {k: before["environment"][k] for k in existing.IDENTITY},
            "candidate": receipt["roles"][role], "original_plist": proposal["copied_preimage"],
            "original_plist_sha256": proposal["original_sha256"], "proposed_plist": proposal["proposed_plist"],
            "proposed_plist_sha256": proposal["proposed_sha256"]}
    protected = []
    for path in sorted((Path.home() / "Library/LaunchAgents").glob("com.lexi.*.plist")):
        payload = plistlib.loads(path.read_bytes())
        if payload["Label"] not in {r["label"] for r in roles.values()}:
            protected.append({"label": payload["Label"], "plist_path": str(path), "plist_sha256": existing.sha(path.read_bytes())})
    manual_path = Path(receipt["roles"]["api"]["app_root"]) / existing.MANUAL_REL
    plan = {"schema_version": "v4.runtime_two_role_release_plan.v1", "status": "PREPARED_NOT_AUTHORIZED_TO_ACTIVATE",
        "roles": roles, "forward_order": ["stage", "api"], "rollback_order": ["api", "stage"],
        "main_binding": json.loads((Path(receipt["roles"]["stage"]["app_root"]) / "stage_center_tick_config.json").read_bytes())["research_owner_binding"],
        "manual_config": {"after_path": str(manual_path), "after_sha256": existing.sha(manual_path.read_bytes())},
        "protected_labels": protected, "protected_external": receipt["protected_external"],
        "preserved_panel_environment": receipt["preserved_panel_environment"],
        "activation_executed": False, "requires_future_explicit_activation_authorization": True,
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    existing.dump(output / "two-role-release-plan.json", plan)
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    plan = prepare(args.output, args.source)
    print(json.dumps({"status": plan["status"], "roles": plan["roles"]}, ensure_ascii=False))
