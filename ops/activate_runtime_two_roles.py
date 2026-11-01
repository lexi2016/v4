"""Guarded Stage -> API switch using exact, freshly prepared two-role bytes.

No activation is performed by candidate preparation. The mutation CLI requires
an explicit operator authorization flag and the captured preparation SHA.
The original fixed workflow supplies guards, CAS, idle checks and unload waits.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import plistlib
import re

from ops import activate_stage_four_repairs as fixed

LABELS = {"stage": "com.lexi.stage-center.scheduler", "api": "com.lexi.v4.api"}
ENV_KEYS = {
    "stage": {*fixed.IDENTITY, "PYTHONPATH", "STAGE_CENTER_CONFIG"},
    "api": {*fixed.IDENTITY, "V4_MANUAL_COLLECTION_STAGE_CONFIG"},
}


def configure(plan_path: Path, evidence: Path):
    plan = json.loads(plan_path.read_bytes())
    fixed.require(list(plan["roles"]) == ["stage", "api"] or set(plan["roles"]) == set(LABELS), "TWO_OWNED_ROLES_REQUIRED")
    fixed.require(plan["forward_order"] == ["stage", "api"] and plan["rollback_order"] == ["api", "stage"], "ROLE_ORDER_INVALID")
    fixed.require(plan.get("RESEARCH_ONLY") is True and all(plan.get(k) is False for k in ("production_allowed", "buy_gate_updated", "orders_sent")), "UNSAFE_PLAN")
    targets = {}
    proposals = {}
    for role, label in LABELS.items():
        row = plan["roles"][role]
        fixed.require(row["label"] == label, "WRONG_TARGET_LABEL")
        old = Path(row["preimage"]["V4_APP_ROOT"]).parent
        new = Path(row["candidate"]["app_root"]).parent
        fixed.require(new.is_relative_to(fixed.LOCAL / "candidates") and new != old and not new.is_symlink(), "WRONG_CANDIDATE_TARGET")
        original = Path(row["original_plist"]).read_bytes()
        proposed = Path(row["proposed_plist"]).read_bytes()
        fixed.require(fixed.sha(original) == row["original_plist_sha256"] and fixed.sha(proposed) == row["proposed_plist_sha256"], "PROPOSAL_BYTES_CHANGED")
        before, after = plistlib.loads(original), plistlib.loads(proposed)
        fixed.require(before["Label"] == after["Label"] == label, "WRONG_PLIST_LABEL")
        expected = copy.deepcopy(before)
        expected["WorkingDirectory"] = str(new / "app")
        if role == "stage":
            expected["ProgramArguments"] = [v.replace(str(old / "app"), str(new / "app")) for v in before["ProgramArguments"]]
        delta = {k for k in set(before["EnvironmentVariables"]) | set(after["EnvironmentVariables"]) if before["EnvironmentVariables"].get(k) != after["EnvironmentVariables"].get(k)}
        fixed.require(delta <= ENV_KEYS[role], "UNOWNED_ENVIRONMENT_DELTA")
        expected["EnvironmentVariables"] = after["EnvironmentVariables"]
        fixed.require(expected == after, "UNOWNED_PLIST_DELTA")
        env = after["EnvironmentVariables"]
        fixed.require(tuple(env[k] for k in fixed.IDENTITY) == (str(new / "app"), new.name, str(new / "release-manifest.json"), row["candidate"]["manifest_sha256"]), "WRONG_PROPOSED_RELEASE")
        fixed.require(all(before["EnvironmentVariables"].get(k) == v for k, v in row["preimage"].items()), "WRONG_PREIMAGE")
        if role == "stage":
            fixed.require(env["STAGE_CENTER_CONFIG"] == str(new / "app/stage_center_tick_config.json"), "WRONG_STAGE_CONFIG")
            fixed.require(env["PYTHONPATH"] == before["EnvironmentVariables"]["PYTHONPATH"].replace(str(old / "app"), str(new / "app")), "WRONG_STAGE_PYTHONPATH")
        else:
            fixed.require(env["V4_MANUAL_COLLECTION_STAGE_CONFIG"] == str(new / "app/config/api-v4_manual_collection_stage_config.json"), "WRONG_MANUAL_CONFIG")
        targets[role] = (label, old, row["preimage"]["V4_RELEASE_MANIFEST_SHA256"], new, row["candidate"]["manifest_sha256"])
        proposals[role] = (original, proposed)
    fixed.TARGETS = targets
    fixed.EVIDENCE = evidence
    fixed.API = targets["api"][3]
    fixed.BASE_API = targets["api"][1]
    fixed.TOOLS_PIN = fixed.sha((fixed.BASE_API / "app/ops/api_release_integration.py").read_bytes())

    def staged(role, raw):
        fixed.require(raw == proposals[role][0], "PROPOSAL_PREIMAGE_CHANGED")
        return proposals[role][1]

    def protection():
        for item in plan["protected_external"].values():
            if "path" in item: fixed.pinned(Path(item["path"]), item["sha256"])
        inv = fixed.tools()
        panel = Path(plan["preserved_panel_environment"]["V4_RESEARCH_PANEL_ROOT"])
        entries = inv.inventory_tree(panel)
        fixed.require({"entry_count": len(entries), "aggregate_sha256": inv.inventory_digest(entries)} == plan["protected_external"]["panel_inventory"], "PANEL_INVENTORY_CHANGED")
        protected = {}
        for row in plan["protected_labels"]:
            path = Path(row["plist_path"]); fixed.pinned(path, row["plist_sha256"])
            payload = plistlib.loads(path.read_bytes())
            printed = fixed.lc("print", fixed.DOMAIN + "/" + row["label"])
            if printed.returncode:
                fixed.require("Could not find service" in printed.stderr, "PROTECTED_JOB_STATE_UNKNOWN")
                state = {"loaded": False}
            else:
                text = printed.stdout
                expected_env = payload.get("EnvironmentVariables", {})
                actual_env = dict(re.findall(r"^\s*([^\n]+?) => ([^\n]*)$", text, re.M))
                fixed.require(all(actual_env.get(k) == str(v) for k, v in expected_env.items()), "PROTECTED_LOADED_ENV_CHANGED")
                for field, value in (("working directory", payload.get("WorkingDirectory")), ("program", (payload.get("ProgramArguments") or [payload.get("Program")])[0])):
                    if value is not None: fixed.require(re.search(r"^\s*" + re.escape(field) + r" = " + re.escape(value) + r"\s*$", text, re.M), "PROTECTED_LOADED_DEFINITION_CHANGED")
                match = re.search(r"^\s*pid = (\d+)\s*$", text, re.M)
                state = {"loaded": True, "pid": int(match[1]) if match else None, "environment": actual_env}
            protected[row["label"]] = {"sha256": fixed.sha(path.read_bytes()), "loaded": state}
        return {"external": plan["protected_external"], "panel": plan["protected_external"]["panel_inventory"], "jobs": protected}

    def forward():
        manual = plan["manual_config"]
        fixed.pinned(Path(manual["after_path"]), manual["after_sha256"])
        cfg = json.loads(Path(manual["after_path"]).read_bytes())
        fixed.require(cfg["stage_owner_root"] == str(targets["stage"][3] / "app"), "MANUAL_STAGE_OWNER_MISMATCH")
        stage_config = json.loads((targets["stage"][3] / "app/stage_center_tick_config.json").read_bytes())
        fixed.require(stage_config["research_owner_binding"] == plan["main_binding"], "STAGE_MAIN_BINDING_CHANGED")
        return {"manual_config_sha256": manual["after_sha256"], "main_binding": stage_config["research_owner_binding"], "API": fixed.live_api(proposals["api"][1]), "UI_VERIFIED": "NOT_RUN", "NATURAL_VERIFIED": "NOT_RUN"}

    fixed.staged, fixed.external_protection, fixed.verify_forward = staged, protection, forward
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "activate", "rollback"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--plan-sha")
    parser.add_argument("--authorize-live-role-switch", action="store_true")
    args = parser.parse_args()
    configure(args.plan, args.evidence)
    if args.action == "prepare":
        with redirect_stdout(io.StringIO()): fixed.prepare()
        receipt = args.evidence / "preparation.json"
        plan = json.loads(receipt.read_bytes())
        plan.update(GOAL="Exact fresh Stage then API two-role switch preserving Main/pre/panel/data",
            PASS_SIGNAL="Two exact loaded roles; API identity/manual Stage/Main pins; protected bytes unchanged; fixture scope only until explicitly activated",
            STOP_RULE="Fresh under-guard CAS/idle/inventory failure stops; after touch restore only owned roles in reverse order; foreign CAS conflict never overwritten",
            adapter_sha256=fixed.sha(Path(__file__).read_bytes()), two_role_plan_path=str(args.plan.resolve()),
            two_role_plan_sha256=fixed.sha(args.plan.read_bytes()))
        receipt.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"status": "PREPARED_NOT_ACTIVATED", "receipt": str(receipt), "sha256": fixed.sha(receipt.read_bytes())}))
    else:
        fixed.require(args.authorize_live_role_switch, "FUTURE_EXPLICIT_ACTIVATION_AUTHORIZATION_REQUIRED")
        fixed.require(bool(args.plan_sha), "PLAN_SHA_REQUIRED")
        prepared = json.loads((args.evidence / "preparation.json").read_bytes())
        fixed.pinned(Path(__file__), prepared["adapter_sha256"])
        fixed.require(str(args.plan.resolve()) == prepared["two_role_plan_path"], "TWO_ROLE_PLAN_PATH_CHANGED")
        fixed.pinned(args.plan, prepared["two_role_plan_sha256"])
        fixed.switch(args.plan_sha, rollback=args.action == "rollback")


if __name__ == "__main__": main()
