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
# Reviewed r5-main bytes; role copies that never carried a path record absence instead.
REMOVALS = {
    "ops/backfill_us_market_digest.py": "d2c3e11576e50aa55356ff992cb1381af77ffea99261b6e5addb0ed6260f9af0",
    "ops/collect_preopen_lane.py": "f6699c2e2088831b12557a5ca588243a011de498088277d48c9649a6f507bfe6",
    "ops/collect_research_panel_adjustment_metadata.py": "83f37fd99d66a0f11eaac71537ac2e1954fe33036d4fa750c0d0bf9bc0f96068",
    "ops/run_v3_5_runtime_graph_collector.py": "ea92de71eccc48c3ef7ce70b90f17195b0c84169753a5f2a9b9ddff7a1c131ec",
    "ops/verify_strict_us_selection_v1.py": "c3ddaec4bc3b7f60c8c1785d7ac1df3821cd9dd241149c01e21e180fdec2b2b2",
    "tests/test_collect_preopen_lane.py": "c6de4e57903db3072921f9f3b014001e0c8e91c5bb50c05cf6dffa70b8543043",
}
# Cleaned-after bytes replace these exact preimages in every role copy that carries them.
RUNTIME_TEST_FILES = {
    "tests/test_research_panel_runtime_graph.py": ("010e76aae7296fd1798b8d0bcd93935bb4bb2ef0c5959a85abf401fd5cb0f985", "989b7238998f9e90aa0194141a1724bb82dd0d53b53a553a182718cd88e60dca"),
    "tests/test_runtime_graph_hardening.py": ("857b50052ded269692ef2bb3d6be9b08bbf340d8e9b60dcda7199cfe7807c3ee", "f8b6bf99bd3b1063781c6cb1115dcba9e7191f39772cd24ac8493664b31815bf"),
}
# Live-derived scheduler repair; the asset is read from the source tree.
MAIN_OVERRIDES = {
    "ops/run_v4_macos_scheduler_due.py": (
        "e6e18cefb9df37407be7770082d844988ed765a21c33567f1a18c88ad9c65ae7",
        "docs/handoffs/unified-release-20261102/run_v4_macos_scheduler_due.r10.py",
        "ff1130e6e5be64a48b2ac1c0afcd9e8e1b83fe3a8b584f1a225c555268c41fab",
    ),
}


def apply_reviewed_removals(app, removals=REMOVALS):
    """Unlink reviewed r5 bytes from one role copy; tolerate absence and never create."""
    removed, absent = [], []
    for relative, expected in removals.items():
        path = Path(app) / relative
        if not path.exists():
            absent.append(relative); continue
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError('REVIEWED_REMOVAL_BYTES_CHANGED')
        path.unlink(); removed.append(relative)
    return removed, absent


def load_snapshot_dir(snapshot_dir):
    """Load any present role snapshots; other files in the directory are ignored."""
    snapshots = {}
    if snapshot_dir is None: return snapshots
    root = Path(snapshot_dir)
    for role in ("main", "stage", "api"):
        path = root / (role + ".json")
        if not path.is_file(): continue
        row = json.loads(path.read_bytes())
        if not isinstance(row, dict) or not isinstance(row.get("environment"), dict):
            raise ValueError("SNAPSHOT_ROLE_INVALID:" + role)
        snapshots[role] = row
    return snapshots


def apply_snapshots(actual, snapshots):
    """Refresh loaded role rows; a later snapshot replaces an older api snapshot."""
    actual.update(copy.deepcopy(snapshots))
    return set(snapshots)


def role_baseline(base, actual, role, fresh):
    """Snapshot roles copy from their refreshed app and pin; others keep the base."""
    if fresh:
        env = actual[role]["environment"]
        return Path(env["V4_APP_ROOT"]), env["V4_RELEASE_MANIFEST_SHA256"]
    return Path(base["roles"][role]["app_root"]), base["roles"][role]["manifest_sha256"]


def apply_main_overrides(app, source, overrides=None):
    """Replace reviewed live-derived Main bytes after copying; never other roles."""
    applied = {}
    for relative, (before_sha, asset, after_sha) in (MAIN_OVERRIDES if overrides is None else overrides).items():
        path = Path(app) / relative
        if not path.is_file() or sha(path.read_bytes()) != before_sha:
            raise ValueError("MAIN_OVERRIDE_PREIMAGE_CHANGED:" + relative)
        raw = (Path(source) / asset).read_bytes()
        if sha(raw) != after_sha:
            raise ValueError("MAIN_OVERRIDE_BYTES_CHANGED:" + relative)
        write(app, relative, raw)
        applied[relative] = {"path": relative, "asset": asset, "before_sha256": before_sha,
                             "after_sha256": after_sha}
    return applied


def apply_schedule_repair(app, before_app, source, relative, preimage):
    """Accept the frozen preimage or the source bytes already applied on live."""
    raw = (Path(source) / relative).read_bytes()
    current = Path(before_app) / relative
    if not current.is_file(): raise ValueError("SCHEDULE_PREIMAGE_CHANGED")
    current_sha = sha(current.read_bytes())
    if current_sha == preimage: mode = "preimage"
    elif current_sha == sha(raw): mode = "already_applied"
    else: raise ValueError("SCHEDULE_PREIMAGE_CHANGED")
    write(app, relative, raw)
    return mode


def apply_runtime_test_overlay(app, source, relative, before_sha, after_sha):
    """Accept before/after/absence in a stacked copy; always write frozen after bytes."""
    raw = (Path(source) / relative).read_bytes()
    if sha(raw) != after_sha: raise ValueError("RUNTIME_TEST_OVERLAY_BYTES_CHANGED")
    path = Path(app) / relative
    if not path.exists(): mode = "absent"
    else:
        current = sha(path.read_bytes())
        if current == before_sha: mode = "before"
        elif current == after_sha: mode = "after"
        else: raise ValueError("RUNTIME_TEST_PREIMAGE_CHANGED")
    write(app, relative, raw)
    return mode


def validate_transition_binding(binding):
    """Strict shape check for a frozen transition-owner binding."""
    keys = {"app_root", "release_id", "manifest_sha256", "trade_date"}
    if not isinstance(binding, dict) or set(binding) != keys:
        raise ValueError("TRANSITION_BINDING_INVALID")
    app_root = binding["app_root"]; release_id = binding["release_id"]
    manifest_sha = binding["manifest_sha256"]; trade_date = binding["trade_date"]
    if (not isinstance(app_root, str) or not app_root or not Path(app_root).is_absolute()
        or not isinstance(release_id, str) or not release_id
        or not isinstance(manifest_sha, str) or not manifest_sha
        or not isinstance(trade_date, str) or not re.fullmatch(r"[0-9]{8}", trade_date)):
        raise ValueError("TRANSITION_BINDING_INVALID")
    return binding


def apply_stage_transition_binding(cfg, main_env, predecessor_date):
    """Preserve an existing frozen transition owner; bind only when absent.

    The live Stage's binding names the historical transition owner (f10-daily
    for 20261102), not the current Main.  Rewriting it would invalidate the
    transition evidence publication prepare/zero_admission depend on.
    """
    existing = cfg.get("research_transition_owner_binding")
    if existing is not None:
        binding = validate_transition_binding(existing)
        if binding["trade_date"] != predecessor_date:
            raise ValueError("TRANSITION_BINDING_DRIFT")
        return binding, "preserved"
    binding = {"app_root": main_env["V4_APP_ROOT"], "release_id": main_env["V4_RELEASE_ID"],
               "manifest_sha256": main_env["V4_RELEASE_MANIFEST_SHA256"], "trade_date": predecessor_date}
    cfg["research_transition_owner_binding"] = binding
    return binding, "bound"


def validate_transition_binding_owner(binding, tools):
    """The preserved/bound transition release must still verify before publication."""
    verified_baseline(Path(binding["app_root"]), binding["manifest_sha256"], tools)


def apply_api_registration(app):
    """Insert the two API registration lines once, or accept them already present."""
    relative = "apps/api/v4_api/app.py"; path = Path(app) / relative; body = path.read_text()
    anchor = "    app.include_router(create_baimao_router(store.root))\n"
    registration = ("    from apps.api.v4_api.report_evidence_router import create_report_evidence_router\n"
                    "    app.include_router(create_report_evidence_router(resolved_research_root))\n")
    if registration in body:
        if body.count(registration) != 1: raise ValueError("API_REGISTRATION_PREIMAGE_CHANGED")
        return "already_registered"
    if body.count(anchor) != 1 or "create_report_evidence_router" in body:
        raise ValueError("API_REGISTRATION_PREIMAGE_CHANGED")
    write(app, relative, body.replace(anchor, anchor + registration).encode())
    return "anchor_applied"


def prepare(*, source, runtime, report_ref, output, api_snapshot=None, snapshot_dir=None, predecessor_date=None):
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
    snapshots = load_snapshot_dir(snapshot_dir)
    apply_snapshots(actual, snapshots)
    refreshed = set(snapshots) | ({"api"} if api_snapshot is not None else set())
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
    reviewed_removals = {relative: {'path': relative, 'before_sha256': expected, 'roles_removed': [], 'roles_absent': []} for relative, expected in REMOVALS.items()}
    runtime_test_overlay = {relative: {'path': relative, 'before_sha256': before, 'after_sha256': after, 'roles': []} for relative, (before, after) in RUNTIME_TEST_FILES.items()}
    main_override_receipt = {}
    transition_expected_binding = None
    idempotency_modes = {"schedule_repairs": {}, "runtime_test_files": {},
                         "stage_transition_binding": None, "api_registration": None}
    for role in ("main", "stage", "api"):
        fresh = role in refreshed
        fresh_api = role == "api" and fresh
        before_app, before_pin = role_baseline(base, actual, role, fresh)
        verified_baseline(before_app, before_pin, inv)
        root = output / (output.name + "-" + role); app = root / "app"
        shutil.copytree(before_app, app, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        for relative in REPORT_FILES: write(app, relative, (source / relative).read_bytes())
        additions = set(REPORT_FILES)
        removed, absent = apply_reviewed_removals(app)
        additions |= set(removed)
        for relative in removed: reviewed_removals[relative]['roles_removed'].append(role)
        for relative in absent: reviewed_removals[relative]['roles_absent'].append(role)
        for relative, (before_sha, after_sha) in RUNTIME_TEST_FILES.items():
            mode = apply_runtime_test_overlay(app, source, relative, before_sha, after_sha)
            additions.add(relative)
            runtime_test_overlay[relative]['roles'].append(role)
            idempotency_modes['runtime_test_files'].setdefault(relative, {})[role] = mode
        if role in SCHEDULE_REPAIRS:
            relative, preimage = SCHEDULE_REPAIRS[role]
            idempotency_modes['schedule_repairs'][role] = apply_schedule_repair(
                app, before_app, source, relative, preimage)
            additions.add(relative)
        if role == "main":
            applied = apply_main_overrides(app, source)
            main_override_receipt.update(applied)
            additions |= set(applied)
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
            main_env = actual["main"]["environment"]
            transition_expected_binding, mode = apply_stage_transition_binding(
                cfg, main_env, predecessor_date)
            idempotency_modes["stage_transition_binding"] = mode
            write(app, "infrastructure/manager_input_attestation.py", (source / "infrastructure/manager_input_attestation.py").read_bytes())
            additions.add("infrastructure/manager_input_attestation.py")
            cfg["release_id"] = root.name
            cfg["research_owner_binding"] = {"app_root": roles["main"]["app_root"], "release_id": roles["main"]["release_id"], "manifest_sha256": roles["main"]["manifest_sha256"]}
            dump(app / "stage_center_tick_config.json", cfg); additions.add("stage_center_tick_config.json")
        if role == "api":
            idempotency_modes["api_registration"] = apply_api_registration(app)
            additions.add("apps/api/v4_api/app.py")
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
    if transition_expected_binding is None or transition != transition_expected_binding:
        raise ValueError("TRANSITION_BINDING_DRIFT")
    validate_transition_binding_owner(transition, inv)
    dependencies.append({"producer_release": transition["release_id"],
        "producer_manifest_sha256": transition["manifest_sha256"],
        "consumer_config_sha256": sha((Path(roles["stage"]["app_root"]) / "stage_center_tick_config.json").read_bytes()),
        "transition_trade_date": transition["trade_date"], "scope": "READ_ONLY_TRANSITION_OWNER",
        "receipt_publication": "NOT_RUN"})
    receipt = {**base, "schema_version": "v4.unified_runtime_candidate.v1", "roles": roles, "report_source_ref": report_ref,
        "live_preimages": actual,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip(), "publication_dependencies": dependencies,
        "report_source_files": frozen, "schedule_source_files": schedule_frozen,
        "reviewed_removals": list(reviewed_removals.values()), "runtime_test_overlay": list(runtime_test_overlay.values()),
        "main_overrides": list(main_override_receipt.values()), "idempotency_modes": idempotency_modes,
        "activated": False, "DEPLOYMENT": "NOT_DEPLOYED", "NATURAL_VERIFIED": "NOT_RUN"}
    dump(output / "candidate_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "output"): parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--report-ref", required=True)
    parser.add_argument("--api-snapshot", type=Path, help="Explicit fresh API snapshot; any later live drift rejects the build")
    parser.add_argument("--snapshot-dir", type=Path, help="Directory with optional main.json/stage.json/api.json role snapshots; present roles replace their live preimage and api prefers its snapshot over --api-snapshot")
    parser.add_argument("--predecessor-date", required=True, help="Exact business date of the pinned prior Main transition")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(); result = prepare(source=args.source, runtime=args.runtime, report_ref=args.report_ref, output=args.output, api_snapshot=args.api_snapshot, snapshot_dir=args.snapshot_dir, predecessor_date=args.predecessor_date)
    print(json.dumps(result["roles"], ensure_ascii=False))
