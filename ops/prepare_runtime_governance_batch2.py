"""Overlay this batch on actual Main/Stage/API releases without old-tree copying.

This is candidate assembly only. Main needs its own future guarded publication;
the Batch1 Stage/API activation command does not publish this Main candidate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import subprocess

from ops.prepare_f10_stage_binding import no_alias, write, dump, verified_baseline, loaded_role


def sha(raw): return hashlib.sha256(raw).hexdigest()


def replace_once(text, before, after):
    if text.count(before) != 1: raise ValueError("OVERLAY_PREIMAGE_NOT_EXACT:" + before[:100])
    return text.replace(before, after, 1)


def patch_dispatch(text):
    text = replace_once(text, "    dry_run: bool = False,\n) -> DispatchReceipt:",
        "    dry_run: bool = False,\n    completion_workload_ids: tuple[str, ...] = (),\n) -> DispatchReceipt:")
    admission = '''    if completion_workload_ids and completion_workload_ids != {
        "1500": ("fupan_close_materials",), "1555": ("fupan_review_start",),
    }.get(request.slot):
        raise ValueError("COMPLETION_WORKLOAD_SCOPE_INVALID")
'''
    text = replace_once(text, "    if catalog.safety.production_allowed", admission + "    if catalog.safety.production_allowed")
    text = replace_once(text, "        claim = ledger.try_claim_dispatch(request)\n        if not claim.acquired:", "        claim = None if completion_workload_ids else ledger.try_claim_dispatch(request)\n        if claim is not None and not claim.acquired:")
    text = replace_once(text, "        run_id = claim.run_id\n", "        run_id = claim.run_id if claim is not None else uuid4().hex\n")
    text = replace_once(text, "        if workload.enabled and request.slot in workload.slots\n", "        if workload.enabled and request.slot in workload.slots\n        and (not completion_workload_ids or workload.workload_id in completion_workload_ids)\n")
    text = replace_once(text, "    failed: list[str] = []", "    failed: list[str] = []\n    busy: list[str] = []")
    text = replace_once(text, "                if not workload_claim.acquired:\n                    continue", '''                if not workload_claim.acquired:
                    if not ledger.claim_completed(workload_claim.relative_path):
                        busy.append(workload.workload_id)
                        results.append({"status": "FAILED", "workload_id": workload.workload_id,
                            "failure_class": "UPSTREAM_NOT_READY", "reason": "EXISTING_WORKLOAD_IN_PROGRESS",
                            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})
                    continue''')
    text = replace_once(text, "        if failed:\n", "        if failed or busy:\n")
    text = replace_once(text, "        payload = receipt.to_dict()\n", "        payload = receipt.to_dict()\n        payload['completion_only'] = bool(completion_workload_ids)\n")
    return replace_once(text, "                workload_ids=tuple(failed),\n", "                workload_ids=tuple(failed),\n                release_dispatch=not completion_workload_ids,\n")


def patch_ledger(text):
    text = replace_once(text, "    def write_receipt(self, relative: str, payload: Mapping[str, Any]) -> None:", '''    def write_receipt(self, relative: str, payload: Mapping[str, Any]) -> None:
        from infrastructure.interprocess_lock import owned_interprocess_lock
        with owned_interprocess_lock(self._path(relative).parent / ".receipt-publish.lock", timeout_seconds=10,
                                     timeout_message="DISPATCH_RECEIPT_PUBLICATION_BUSY"):
            self._write_receipt_unlocked(relative, payload)

    def _write_receipt_unlocked(self, relative: str, payload: Mapping[str, Any]) -> None:''')
    text = replace_once(text, "    def release_failed_request(\n", '''    def claim_completed(self, relative: str) -> bool:
        return self._has_completed_receipt(_read_existing_claim(self._path(relative)))

    def release_failed_request(
''')
    start = text.index("    def release_failed_request("); end = text.index("    def receipt_relative(", start)
    part = text[start:end]
    part = replace_once(part, "        workload_ids: tuple[str, ...],\n", "        workload_ids: tuple[str, ...],\n        release_dispatch: bool = True,\n")
    before = '''        reason = self._claim_identity_mismatch(
            dispatch_relative,
            expected_run_id=run_id,
            identity=identity,
        )
        if reason is not None:
            raise ValueError(reason)'''
    part = replace_once(part, before, "        if release_dispatch:\n" + "\n".join("    " + line for line in before.splitlines()))
    part = replace_once(part, "        self._unlink_claim(dispatch_relative)", "        if release_dispatch: self._unlink_claim(dispatch_relative)")
    return text[:start] + part + text[end:]


def patch_due(text):
    text = replace_once(text, "        observed.append(payload)", "        if not payload.get('completion_only'): observed.append(payload)")
    return replace_once(text, '        if not isinstance(payload, dict) or str(payload.get("status") or "") != "FAILED":',
        '        if not isinstance(payload, dict) or payload.get("completion_only") or str(payload.get("status") or "") != "FAILED":')


def patch_stage(text):
    before = "    return _v4_impl(globals(), config, trade_date, stage_id, evaluated_at, mode=mode, runner=runner, precaptures=precaptures)"
    after = '''    persisted = _v4_impl(globals(), config, trade_date, stage_id, evaluated_at, mode=mode, runner=runner, precaptures=precaptures)
    from infrastructure.stage_completion_hooks import deliver
    deliver(config=config, trade_date=trade_date, stage_id=stage_id, receipt=persisted,
            settled=_stage_settled(persisted), mode=mode)
    return persisted'''
    return replace_once(text, before, after)


MAIN_FILES = ("infrastructure/review_generation.py", "ops/build_a_share_close_review.py", "ops/build_close_review.py",
    "ops/collect_hkconnect_close_snapshot.py", "infrastructure/tdx_minute_replay_provider.py", "ops/consume_close_stage_completion.py",
    "ops/recover_stage_data.py", "ops/verify_tdx_trade_window_canary.py", "ops/build_runtime_governance_registry.py")
API_FILES = ("infrastructure/operations_sop_reader.py", "docs/operations/RUNTIME_DATA_RECOVERY_SOP.md")
STAGE_FILES = ("infrastructure/stage_completion_hooks.py", "ops/consume_close_stage_completion.py", "ops/recover_stage_data.py", "ops/verify_tdx_trade_window_canary.py")


def prepare(output, source, batch1):
    no_alias(output); no_alias(source)
    if output.exists(): raise ValueError("CANDIDATE_OUTPUT_ALREADY_EXISTS")
    baseline = json.loads((batch1 / "candidate_receipt.json").read_bytes())
    labels = {"main": "com.lexi.v4.scheduler", "stage": "com.lexi.stage-center.scheduler", "api": "com.lexi.v4.api"}
    pins = {}
    for role, label in labels.items():
        p = plistlib.loads((Path.home() / "Library/LaunchAgents" / (label + ".plist")).read_bytes())
        env = p["EnvironmentVariables"]; pins[role] = (label, Path(env["V4_APP_ROOT"]), env["V4_RELEASE_MANIFEST_SHA256"])
    inventory_path = pins["api"][1] / "ops/api_release_integration.py"
    spec = importlib.util.spec_from_file_location("governance_batch2_inventory", inventory_path)
    inv = importlib.util.module_from_spec(spec); spec.loader.exec_module(inv)
    live = {role: loaded_role(*pin) for role, pin in pins.items()}
    for role, (_, app, pin) in pins.items(): verified_baseline(app, pin, inv)
    output.mkdir(); result = {}
    for role in ("main", "stage", "api"):
        base = pins[role][1] if role == "main" else Path(baseline["roles"][role]["app_root"])
        base_manifest = json.loads((base.parent / "release-manifest.json").read_bytes())
        root = output / (output.name + "-" + role); app = root / "app"
        shutil.copytree(base, app, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        before = {r["path"]: r for r in inv.inventory_tree(base)}
        for relative in {"main": MAIN_FILES, "api": API_FILES, "stage": STAGE_FILES}[role]:
            write(app, relative, (source / relative).read_bytes())
        if role == "main":
            write(app, "infrastructure/scheduling/dispatcher.py", patch_dispatch((base / "infrastructure/scheduling/dispatcher.py").read_text()).encode())
            write(app, "infrastructure/scheduling/execution_ledger.py", patch_ledger((base / "infrastructure/scheduling/execution_ledger.py").read_text()).encode())
            write(app, "ops/run_v4_macos_scheduler_due.py", patch_due((base / "ops/run_v4_macos_scheduler_due.py").read_text()).encode())
        elif role == "stage":
            write(app, "ops/run_stage_center_nodes.py", patch_stage((base / "ops/run_stage_center_nodes.py").read_text()).encode())
            cfg = json.loads((app / "stage_center_tick_config.json").read_bytes())
            cfg["release_id"] = root.name
            cfg["research_owner_binding"] = {"app_root": result["main"]["app_root"], "release_id": result["main"]["release_id"], "manifest_sha256": result["main"]["manifest_sha256"]}
            # Global defaults stay off. Isolated fixtures exercise opt-in.
            cfg["close_review_completion_enabled"] = False
            cfg["report_evidence_sidecar_enabled"] = False
            dump(app / "stage_center_tick_config.json", cfg)
        else:
            manual = json.loads((app / "config/api-v4_manual_collection_stage_config.json").read_bytes())
            manual["stage_owner_root"] = result["stage"]["app_root"]
            dump(app / "config/api-v4_manual_collection_stage_config.json", manual)
        entries = inv.inventory_tree(app); after = {r["path"]: r for r in entries}
        delta = [p for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]
        allowed = set({"main": MAIN_FILES, "api": API_FILES, "stage": STAGE_FILES}[role]) | {
            "main": {"infrastructure/scheduling/dispatcher.py", "infrastructure/scheduling/execution_ledger.py", "ops/run_v4_macos_scheduler_due.py"}, "stage": {"ops/run_stage_center_nodes.py", "stage_center_tick_config.json"}, "api": {"config/api-v4_manual_collection_stage_config.json"}}[role]
        if set(delta) - allowed: raise ValueError("UNOWNED_OVERLAY:" + repr(set(delta) - allowed))
        manifest = copy.deepcopy(base_manifest)
        manifest.update(app_root=str(app), release_id=root.name, activation_status="PREPARED_NOT_ACTIVATED", deployment_status="NOT_DEPLOYED")
        manifest["candidate"].update(root=str(root), app_root=str(app), release_id=root.name)
        manifest["application_inventory"] = {"entries": entries, "entry_count": len(entries), "aggregate_sha256": inv.inventory_digest(entries)}
        manifest["app_files"] = entries
        manifest["runtime_governance_overlay"] = {"source_root": str(source), "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip(),
            "base_app": str(base), "base_manifest_sha256": sha((base.parent / "release-manifest.json").read_bytes()),
            "delta": [{"path": p, "before": before.get(p), "after": after.get(p)} for p in delta],
            "source_dependencies_preserved": ["current PDF owner", "current Main executor registry and 15:55 manager", "all unlisted runtime files"], "deployment_allowed": False}
        dump(root / "release-manifest.json", manifest)
        result[role] = {"app_root": str(app), "release_id": root.name, "manifest_sha256": sha((root / "release-manifest.json").read_bytes()), "inventory_sha256": inv.inventory_digest(entries), "delta": delta}
    for role, pin in pins.items():
        if loaded_role(*pin) != live[role]: raise ValueError("LIVE_ROLE_CHANGED_DURING_OVERLAY")
        verified_baseline(pin[1], pin[2], inv)
    for row in result.values(): verified_baseline(Path(row["app_root"]), row["manifest_sha256"], inv)
    from ops.build_runtime_governance_registry import publication_checks
    dependencies = publication_checks(stage_app=Path(result["stage"]["app_root"]),
        api_manual=Path(result["api"]["app_root"]) / "config/api-v4_manual_collection_stage_config.json",
        inventory_module=inventory_path)
    receipt = {"schema_version": "v4.runtime_governance_batch2_candidate.v1", "roles": result, "live_preimages": live,
        "publication_dependencies": dependencies,
        "publication_roles_required": ["main", "stage", "api"], "batch1_activation_cannot_publish_batch2_main": True,
        "activation_executed": False, "default_completion_hooks_enabled": False, "RESEARCH_ONLY": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    dump(output / "candidate_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "batch1"): parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(); result = prepare(args.output, args.source, args.batch1)
    print(json.dumps(result["roles"], ensure_ascii=False))
