"""Combine frozen runtime/report bytes on live-derived candidates, no activation."""
from __future__ import annotations
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

from ops.prepare_f10_stage_binding import dump, loaded_role, sha, verified_baseline, write

REPORT_FILES = (
    "apps/api/v4_api/report_evidence_router.py", "apps/api/v4_api/report_evidence_mcp.py",
    "domains/report_evidence.py", "infrastructure/report_evidence_index.py",
    "infrastructure/report_evidence_native.py", "infrastructure/report_evidence_sidecar.py",
    "ops/report_evidence_index.py", "ops/verify_report_evidence_canary.py",
    "ops/run_report_evidence_sidecar_job.py",
)
ALIAS = "infrastructure/report_evidence_pdf_owner.py"
OWNER_SHA = "f567de644f88f9db18a82bde7d3c6d93b31f79bca806141d7f51d30dc0189cde"
SCHEDULE_REPAIRS = {
    "main": ("ops/run_stage_center_milestone.py", "1e72438420cdff455bb181ad63b4b78ea47981d43c3524c100cbc25d8db1dac6"),
    "api": ("domains/task_status.py", "24d52d7258bb4421810c6116dc54366df9f1363f3fa62850f1a828bd67011ae6"),
}


def prepare(*, source, runtime, report_ref, output, api_snapshot=None, predecessor_date=None):
    if output.exists(): raise ValueError("UNIFIED_OUTPUT_MUST_BE_NEW")
    if not isinstance(predecessor_date, str) or not re.fullmatch(r"[0-9]{8}", predecessor_date):
        raise ValueError("EXACT_TRANSITION_DATE_REQUIRED")
    if not re.fullmatch("[0-9a-f]{40}", report_ref): raise ValueError("EXACT_FROZEN_REPORT_COMMIT_REQUIRED")
    base = json.loads((runtime / "candidate_receipt.json").read_bytes())
    frozen = {}
    for relative in (*REPORT_FILES, ALIAS):
        raw = subprocess.check_output(["git", "show", report_ref + ":" + relative], cwd=source)
        if (source / relative).read_bytes() != raw: raise ValueError("REPORT_SOURCE_NOT_FROZEN:" + relative)
        frozen[relative] = {"sha256": sha(raw), "bytes": len(raw)}
    schedule_frozen = {}
    for role, (relative, _) in SCHEDULE_REPAIRS.items():
        raw = subprocess.check_output(["git", "show", report_ref + ":" + relative], cwd=source)
        if (source / relative).read_bytes() != raw: raise ValueError("SCHEDULE_SOURCE_NOT_FROZEN:" + relative)
        schedule_frozen[role] = {"path": relative, "sha256": sha(raw), "bytes": len(raw)}
    actual = copy.deepcopy(base["live_preimages"])
    if api_snapshot is not None:
        actual["api"] = json.loads(Path(api_snapshot).read_bytes())
    current_api = Path(actual["api"]["environment"]["V4_APP_ROOT"])
    alias = (source / ALIAS).read_bytes()
    if sha(alias) != OWNER_SHA or (current_api / "infrastructure/zsxq_pdf_ingestion.py").read_bytes() != alias:
        raise ValueError("CURRENT_READ_ONLY_PDF_OWNER_BYTES_CHANGED")
    spec = importlib.util.spec_from_file_location("unified_inventory", current_api / "ops/api_release_integration.py")
    inv = importlib.util.module_from_spec(spec); spec.loader.exec_module(inv)
    for role, row in actual.items():
        env = row["environment"]
        if loaded_role(row["label"], Path(env["V4_APP_ROOT"]), env["V4_RELEASE_MANIFEST_SHA256"]) != row:
            raise ValueError("CURRENT_OWNER_DRIFT:" + role)
        verified_baseline(Path(env["V4_APP_ROOT"]), env["V4_RELEASE_MANIFEST_SHA256"], inv)
    output.mkdir(); roles = {}
    for role in ("main", "stage", "api"):
        fresh_api = role == "api" and api_snapshot is not None
        before_app = current_api if fresh_api else Path(base["roles"][role]["app_root"])
        before_pin = actual["api"]["environment"]["V4_RELEASE_MANIFEST_SHA256"] if fresh_api else base["roles"][role]["manifest_sha256"]
        verified_baseline(before_app, before_pin, inv)
        root = output / (output.name + "-" + role); app = root / "app"
        shutil.copytree(before_app, app, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        for relative in REPORT_FILES: write(app, relative, (source / relative).read_bytes())
        additions = set(REPORT_FILES)
        if role in SCHEDULE_REPAIRS:
            relative, preimage = SCHEDULE_REPAIRS[role]
            if sha((before_app / relative).read_bytes()) != preimage:
                raise ValueError("SCHEDULE_PREIMAGE_CHANGED:" + role)
            write(app, relative, (source / relative).read_bytes()); additions.add(relative)
        if fresh_api:
            write(app, "docs/operations/RUNTIME_DATA_RECOVERY_SOP.md", (source / "docs/operations/RUNTIME_DATA_RECOVERY_SOP.md").read_bytes())
            reader = (app / "infrastructure/operations_sop_reader.py").read_text()
            if "'runtime-data-recovery':" not in reader:
                if reader.count("DOCUMENTS={\n") != 1: raise ValueError("SOP_READER_PREIMAGE_CHANGED")
                reader = reader.replace("DOCUMENTS={\n", "DOCUMENTS={\n    'runtime-data-recovery':('运行链补数据与复用规程','docs/operations/RUNTIME_DATA_RECOVERY_SOP.md'),\n", 1)
                write(app, "infrastructure/operations_sop_reader.py", reader.encode())
            additions |= {"docs/operations/RUNTIME_DATA_RECOVERY_SOP.md", "infrastructure/operations_sop_reader.py"}
        if role in {"main", "stage"}:
            write(app, ALIAS, alias); additions.add(ALIAS)
        if role == "stage":
            # This module is absent from the deployed Stage. Main's accepted
            # scoring/classification module is never replaced by the API copy.
            if not (app / "domains/report_subjects.py").exists():
                write(app, "domains/report_subjects.py", (current_api / "domains/report_subjects.py").read_bytes())
                additions.add("domains/report_subjects.py")
            cfg = json.loads((app / "stage_center_tick_config.json").read_bytes())
            if cfg.get("research_transition_owner_binding") is not None:
                raise ValueError("TRANSITION_BINDING_ALREADY_PRESENT")
            main_env = actual["main"]["environment"]
            cfg["research_transition_owner_binding"] = {
                "app_root": main_env["V4_APP_ROOT"], "release_id": main_env["V4_RELEASE_ID"],
                "manifest_sha256": main_env["V4_RELEASE_MANIFEST_SHA256"], "trade_date": predecessor_date,
            }
            write(app, "infrastructure/manager_input_attestation.py", (source / "infrastructure/manager_input_attestation.py").read_bytes())
            additions.add("infrastructure/manager_input_attestation.py")
            cfg["release_id"] = root.name
            cfg["research_owner_binding"] = {"app_root": roles["main"]["app_root"], "release_id": roles["main"]["release_id"], "manifest_sha256": roles["main"]["manifest_sha256"]}
            dump(app / "stage_center_tick_config.json", cfg); additions.add("stage_center_tick_config.json")
        if role == "api":
            path = app / "apps/api/v4_api/app.py"; body = path.read_text()
            anchor = "    app.include_router(create_baimao_router(store.root))\n"
            if body.count(anchor) != 1 or "create_report_evidence_router" in body: raise ValueError("API_REGISTRATION_PREIMAGE_CHANGED")
            body = body.replace(anchor, anchor + "    from apps.api.v4_api.report_evidence_router import create_report_evidence_router\n    app.include_router(create_report_evidence_router(resolved_research_root))\n")
            write(app, "apps/api/v4_api/app.py", body.encode()); additions.add("apps/api/v4_api/app.py")
            manual_path = Path(actual["api"]["environment"]["V4_MANUAL_COLLECTION_STAGE_CONFIG"]) if fresh_api else app / "config/api-v4_manual_collection_stage_config.json"
            manual = json.loads(manual_path.read_bytes())
            manual["stage_owner_root"] = roles["stage"]["app_root"]
            dump(app / "config/api-v4_manual_collection_stage_config.json", manual); additions.add("config/api-v4_manual_collection_stage_config.json")
        entries = inv.inventory_tree(app); after = {r["path"]: r for r in entries}
        runtime_before = {r["path"]: r for r in inv.inventory_tree(before_app)}
        added_delta = {p for p in set(runtime_before) | set(after) if runtime_before.get(p) != after.get(p)}
        cache_omissions = {p for p in added_delta if p in runtime_before and p not in after and "__pycache__" in Path(p).parts and p.endswith((".pyc", ".pyo"))}
        if added_delta - additions - cache_omissions: raise ValueError("UNOWNED_UNIFIED_DELTA:" + repr(added_delta - additions - cache_omissions))
        current_app = Path(actual[role]["environment"]["V4_APP_ROOT"])
        current = {r["path"]: r for r in inv.inventory_tree(current_app)}
        delta = sorted(p for p in set(current) | set(after) if current.get(p) != after.get(p))
        allowed = set(base["roles"][role]["delta"]) | additions
        if set(delta) - allowed: raise ValueError("UNOWNED_CURRENT_DELTA:" + repr(set(delta) - allowed))
        if role == "main":
            for relative in ("infrastructure/zsxq_pdf_ingestion.py", "infrastructure/data_store.py", "domains/report_subjects.py"):
                if (app / relative).read_bytes() != (current_app / relative).read_bytes(): raise ValueError("MAIN_CANONICAL_DEPENDENCY_OVERWRITE:" + relative)
        manifest = copy.deepcopy(json.loads((before_app.parent / "release-manifest.json").read_bytes()))
        manifest.update(app_root=str(app), release_id=root.name, activation_status="PREPARED_NOT_ACTIVATED", deployment_status="NOT_DEPLOYED")
        manifest["candidate"].update(root=str(root), app_root=str(app), release_id=root.name)
        manifest["application_inventory"] = {"entries": entries, "entry_count": len(entries), "aggregate_sha256": inv.inventory_digest(entries)}
        manifest["app_files"] = entries
        manifest["unified_implementation"] = {"source_root": str(source), "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip(),
            "runtime_base": str(runtime), "report_source_ref": report_ref, "report_files": frozen,
            "schedule_repair": schedule_frozen.get(role),
            "actual_current_app": str(current_app), "actual_current_manifest_sha256": actual[role]["environment"]["V4_RELEASE_MANIFEST_SHA256"],
            "actual_current_delta": [{"path": p, "before": current.get(p), "after": after.get(p)} for p in delta],
            "protected_current_files_unchanged": sum(after.get(p) == row for p, row in current.items()),
            "owner_alias_sha256": OWNER_SHA if role != "api" else None,
            "canonical_pdf_producer_and_main_scoring_preserved": True, "defaults_changed": False}
        dump(root / "release-manifest.json", manifest)
        roles[role] = {"app_root": str(app), "release_id": root.name, "manifest_sha256": sha((root / "release-manifest.json").read_bytes()),
            "inventory_sha256": inv.inventory_digest(entries), "delta": delta, "actual_current_app": str(current_app),
            "actual_current_manifest_sha256": actual[role]["environment"]["V4_RELEASE_MANIFEST_SHA256"],
            "protected_current_files_unchanged": manifest["unified_implementation"]["protected_current_files_unchanged"]}
    for role, row in actual.items():
        env = row["environment"]
        if loaded_role(row["label"], Path(env["V4_APP_ROOT"]), env["V4_RELEASE_MANIFEST_SHA256"]) != row: raise ValueError("CURRENT_OWNER_CHANGED_DURING_BUILD")
        verified_baseline(Path(roles[role]["app_root"]), roles[role]["manifest_sha256"], inv)
    from ops.build_runtime_governance_registry import publication_checks
    dependencies = publication_checks(stage_app=Path(roles["stage"]["app_root"]), api_manual=Path(roles["api"]["app_root"]) / "config/api-v4_manual_collection_stage_config.json", inventory_module=current_api / "ops/api_release_integration.py")
    transition = json.loads((Path(roles["stage"]["app_root"]) / "stage_center_tick_config.json").read_bytes())["research_transition_owner_binding"]
    main_env = actual["main"]["environment"]
    if transition != {"app_root": main_env["V4_APP_ROOT"], "release_id": main_env["V4_RELEASE_ID"],
                      "manifest_sha256": main_env["V4_RELEASE_MANIFEST_SHA256"], "trade_date": predecessor_date}:
        raise ValueError("TRANSITION_BINDING_DRIFT")
    verified_baseline(Path(transition["app_root"]), transition["manifest_sha256"], inv)
    dependencies.append({"producer_release": transition["release_id"],
        "producer_manifest_sha256": transition["manifest_sha256"],
        "consumer_config_sha256": sha((Path(roles["stage"]["app_root"]) / "stage_center_tick_config.json").read_bytes()),
        "transition_trade_date": predecessor_date, "scope": "READ_ONLY_TRANSITION_OWNER",
        "receipt_publication": "NOT_RUN"})
    receipt = {**base, "schema_version": "v4.unified_runtime_candidate.v1", "roles": roles, "report_source_ref": report_ref,
        "live_preimages": actual,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip(), "publication_dependencies": dependencies,
        "report_source_files": frozen, "schedule_source_files": schedule_frozen,
        "activated": False, "DEPLOYMENT": "NOT_DEPLOYED", "NATURAL_VERIFIED": "NOT_RUN"}
    dump(output / "candidate_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "output"): parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--report-ref", required=True)
    parser.add_argument("--api-snapshot", type=Path, help="Explicit fresh API snapshot; any later live drift rejects the build")
    parser.add_argument("--predecessor-date", required=True, help="Exact business date of the pinned prior Main transition")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(); result = prepare(source=args.source, runtime=args.runtime, report_ref=args.report_ref, output=args.output, api_snapshot=args.api_snapshot, predecessor_date=args.predecessor_date)
    print(json.dumps(result["roles"], ensure_ascii=False))
