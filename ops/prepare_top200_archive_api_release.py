"""Prepare the reviewed #17/#18 API-only overlays and guard their release."""

import argparse
import ast
from contextlib import ExitStack
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import socket
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler
from zoneinfo import ZoneInfo

from infrastructure.interprocess_lock import owned_interprocess_lock
from ops.api_release_integration import inventory_digest, inventory_tree


LOCAL = Path.home() / "Library/Application Support/com.lexi.v4.local"
R1 = LOCAL / "candidates/v4-storage-release-20261114-r1"
CONTROL = LOCAL / "state/releases-control/storage-release-20261114-r1"
NATURAL = CONTROL / "NATURAL_20261116"
TARGET = LOCAL / "candidates/v4-top200-archive-20261116"
BATCH = Path.home() / "Mac_Storage_Audit/growth_20261113/panel_18_readonly_20261115/execution_17_18_20261115"
OPERATOR = Path(__file__).resolve()
REPO = OPERATOR.parents[1]
SOURCE_COMMIT = "c212d6a445b4ea038b4c5ef7c0f92973d56a5fa4"
CONTROLLER_SHA = "fb9f0bad78d2553edfdd4022c81924d3f0f5e0418b28d7fbc35ff3d50a8f54da"
INSTALL_SHA = "d384e66d55fab10388e9f4671ef260d2e065eb00f89eb74c822413471541370d"
ROLE = {"forward": "forward", "compat-rollback": "rollback"}
FILES = {"apps/api/v4_api/preselection_service.py", "infrastructure/research_workbench_host.py"}
FORMAL_API_READERS = {"apps/api/v4_api/a_share_panel_history.py", "apps/api/v4_api/preselection_service.py",
                      "ops/research_storage_pair.py"}
LIVE_API = Path.home() / "Library/LaunchAgents/com.lexi.v4.api.plist"
SAMPLES = ("600809.SH", "600187.SH", "920156.BJ")
UNKNOWN_SAMPLE = "920201.BJ"
DATE_ROUTE = "/api/v4/research/workbench/days/2026-10-30/single-research/"
SAFETY = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
DAY = "20261116"
TZ = ZoneInfo("Asia/Shanghai")
TERMINAL = {
    "NATURAL_SESSION_EVIDENCE_VERIFIED": (17, 15),
    "NATURAL_SESSION_EVIDENCE_VERIFIED_AFTER_COMPAT_ROLLBACK": (23, 58),
    "TRADING_DAY_WINDOW_ENDED_WITH_MISSING_RECEIPTS": (23, 58),
}
READ_RECEIPTS = {"STAGE_WRITE_RECEIPT.json", "MWB_WRITE_RECEIPT.json", "A_DAILY_WRITE_RECEIPT.json"}
ATTEMPT_NAME = re.compile(r"([0-9]{8})-(activate|rollback)-[0-9]{8}T[0-9]{12}-[0-9]+")
PORT = 8873
OPENER = build_opener(ProxyHandler({}))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_file(), "RELEASE_REFERENCE_PATH_INVALID")
    raw = path.read_bytes()
    require(digest(raw) == expected, f"RELEASE_REFERENCE_SHA_DRIFT:{path.name}")
    return raw


def checked_ref(reference):
    return checked(reference["path"], reference["sha256"])


def reference(path):
    return {"path": str(path), "sha256": digest(path.read_bytes())}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sealed_execution(expected_sha):
    path = BATCH / "BATCH_01_EXECUTION_STATUS.json"
    execution = json.loads(checked(path, expected_sha))
    require(execution["source_sync"]["commit"] == SOURCE_COMMIT
            and execution["source_sync"]["review"] == "PASS"
            and execution["candidate_original_files_inaccessible_verified_by_native_arrow"] is True,
            "ARCHIVE_CANDIDATE_REVIEW_REQUIRED")
    overlays = json.loads(checked_ref(execution["candidate_role_source_binding"]))
    archive = json.loads(checked_ref(execution["retained_manifest"]))
    legacy = json.loads(checked_ref(execution["frozen_legacy_rebind_replay_with_originals_denied"]))
    require(legacy["status"] == "PASS" and legacy["native_original_path_deny"] is True
            and {row["number"] for row in archive["source"]} == {17, 18}, "ARCHIVE_REPLAY_REQUIRED")
    readbacks = {}
    for variant, role in ROLE.items():
        receipt = json.loads(checked_ref(execution[f"candidate_exact_{role}_archive"]))
        require(receipt["status"] == "PASS" and receipt["native_original_path_deny"] is True
                and receipt["api_manifest_sha256"] == overlays[role]["api_manifest_sha256"]
                and receipt["candidate_workbench_host_sha256"]
                == overlays[role]["inputs"]["infrastructure/research_workbench_host.py"]["after_sha256"],
                "ARCHIVE_ROLE_PARITY_REQUIRED")
        for entry in archive["source"]:
            responses = receipt["exact_archived_routes"][str(entry["number"])]
            require(all(responses[sample]["source"]["artifact_sha256"] == entry["sha256"]
                        and responses[sample]["generation"] == entry["generation"]
                        and responses[sample]["status"] == "READY" for sample in SAMPLES),
                    "ARCHIVE_READ_SAMPLE_IDENTITY_CONFLICT")
        readbacks[variant] = receipt
    return execution, overlays, archive, readbacks


def installed_roles():
    return json.loads(checked(R1 / "INSTALL_RECEIPT.json", INSTALL_SHA))


def legacy_inventory(entries):
    return [{key: row[key] for key in ("path", "sha256", "size")} for row in entries]


def prepare_plan(execution_sha, installed, overlays):
    plans, total_bytes = {}, 0
    for variant, role in ROLE.items():
        source = R1 / role / "api"
        identity = installed[role]["roles"]["api"]
        manifest_sha = overlays[role]["api_manifest_sha256"]
        require(identity["manifest"]["path"] == str(source / "release-manifest.json")
                and identity["manifest"]["sha256"] == manifest_sha, "R1_API_MANIFEST_IDENTITY_CONFLICT")
        raw = checked_ref(identity["proposed_plist"])
        payload = plistlib.loads(raw)
        manifest = json.loads(checked_ref(identity["manifest"]))
        before = inventory_tree(source / "app")
        require(manifest["app_files"] == legacy_inventory(before) and before == manifest["application_inventory"]["entries"]
                and inventory_digest(before) == manifest["application_inventory"]["aggregate_sha256"],
                "R1_API_INVENTORY_DRIFT")
        require(set(overlays[role]["inputs"]) == FILES, "ARCHIVE_OVERLAY_FILESET_DRIFT")
        overlay = {}
        for relative, shas in overlays[role]["inputs"].items():
            checked(source / "app" / relative, shas["before_sha256"])
            overlay[relative] = checked(BATCH / "candidate-role-overlays" / role / relative, shas["after_sha256"])
        logical_bytes = sum(row.get("size", 0) for row in before)
        require(logical_bytes <= 200 * 1024**2, "API_CLONE_EXCEEDS_APPROVED_BUDGET")
        total_bytes += logical_bytes
        plans[variant] = (source, manifest, before, overlay, payload, raw, logical_bytes)
    free = shutil.disk_usage(TARGET.parent).free
    require(free >= total_bytes + 1024**3, "API_RELEASE_SPACE_BUDGET_UNAVAILABLE")
    write_new(BATCH / "BATCH_01_API_RELEASE_PREP_BUDGET.json", json_bytes({
        "status": "AUTHORIZED_CLONE_BUDGET_CHECKED", "recorded_at": datetime.now(TZ).isoformat(),
        "owner": str(OPERATOR), "sources": {variant: str(plan[0]) for variant, plan in plans.items()},
        "input_execution_sha256": execution_sha, "path": str(TARGET), "free_bytes_before": free,
        "maximum_logical_bytes": 400 * 1024**2, "estimated_payload_bytes": total_bytes,
        "retain": "Both sealed API variants, derived policy bindings and exact inverse plists",
        "temporary_outputs": "Only isolated in-memory/local-port standby process; terminate on exit",
    }))
    return plans


def rewrite_plist(payload, root, release_id, manifest_sha, binding_sha):
    require(payload["Label"] == "com.lexi.v4.api"
            and payload["ProgramArguments"][1:8] == ["-B", "-m", "apps.api.v4_api.run", "--host", "127.0.0.1", "--port", "8873"],
            "R1_API_PLIST_SCOPE_CONFLICT")
    settings = payload["EnvironmentVariables"]
    app = root / "app"
    replacements = {
        "V4_APP_ROOT": str(app), "V4_RELEASE_ID": release_id, "PYTHONPATH": f"{app / 'upstreams'}:{app}",
        "V4_RELEASE_MANIFEST_PATH": str(root / "release-manifest.json"), "V4_RELEASE_MANIFEST_SHA256": manifest_sha,
        "V4_WORKBENCH_HOST_BINDING": str(root / "workbench-binding.json"), "V4_WORKBENCH_HOST_BINDING_SHA256": binding_sha,
    }
    require(replacements.keys() <= settings.keys() and settings["V4_APP_ROOT"] == payload["WorkingDirectory"],
            "R1_API_PLIST_IDENTITY_INCOMPLETE")
    return {**payload, "WorkingDirectory": str(app), "EnvironmentVariables": {**settings, **replacements}}


def bind_main_controls(root, old_api, base_api_sha, candidate_api_sha, installed):
    """Rebind the existing formal-reader attestations without changing policy."""
    control_ref = installed["control"]
    base_main = checked_ref(installed["roles"]["main"]["proposed_plist"])
    main = plistlib.loads(base_main)
    environment = main["EnvironmentVariables"]
    policy_ref = control_ref["policy"]
    require(main["Label"] == "com.lexi.v4.scheduler"
            and environment["V4_RESEARCH_RETENTION_POLICY"] == policy_ref["path"]
            and environment["V4_RESEARCH_RETENTION_POLICY_SHA256"] == policy_ref["sha256"],
            "R1_MAIN_POLICY_IDENTITY_CONFLICT")
    policy = json.loads(checked_ref(policy_ref))
    require(policy["managed_pin_inventory"] == control_ref["pins"]
            and policy["single_generation_lifecycle"]["reader_inventory"] == control_ref["reader_attestation"]
            and policy["dry_run"] is True and policy["auto_gc_enabled"] is False,
            "R1_READER_CONTROL_IDENTITY_CONFLICT")
    pins = json.loads(checked_ref(control_ref["pins"]))
    readers = json.loads(checked_ref(control_ref["reader_attestation"]))
    require(pins["expected_main_app_root"] == environment["V4_APP_ROOT"], "R1_MAIN_APP_BINDING_CONFLICT")
    source_paths = {str(old_api / "app" / file): root / "app" / file for file in FORMAL_API_READERS}
    replacement = {old: reference(new) for old, new in source_paths.items()}
    old_sources = {ref["path"]: ref for ref in pins["source_bindings"]}
    require(len(old_sources) == len(pins["source_bindings"]) and
            {path for path in old_sources if Path(path).is_relative_to(old_api / "app")} == source_paths.keys()
            and old_sources[str(LIVE_API)]["sha256"] == base_api_sha, "R1_FORMAL_API_BINDINGS_DRIFT")
    api_readers = [body for body in readers["consumers"] if body["label"] == "com.lexi.v4.api"]
    require(len(api_readers) == 1, "R1_API_ATTESTATION_CARDINALITY_CONFLICT")
    api = api_readers[0]
    require(api["plist_path"] == str(LIVE_API) and api["plist_sha256"] == base_api_sha
            and len(api["source_refs"]) == len(source_paths)
            and {ref["path"]: ref for ref in api["source_refs"]} == {path: old_sources[path] for path in source_paths},
            "R1_API_ATTESTATION_PREIMAGE_DRIFT")
    api["plist_sha256"] = candidate_api_sha
    api["source_refs"] = [replacement[row["path"]] for row in api["source_refs"]]
    replacement[str(LIVE_API)] = {"path": str(LIVE_API), "sha256": candidate_api_sha}
    pins["source_bindings"] = [replacement.get(ref["path"], ref) for ref in pins["source_bindings"]]
    for path, value in ((root / "managed-pins.json", pins), (root / "reader-attestation.json", readers)):
        write_new(path, json_bytes(value))
    policy["managed_pin_inventory"] = reference(root / "managed-pins.json")
    policy["single_generation_lifecycle"]["reader_inventory"] = reference(root / "reader-attestation.json")
    policy_path = root / "policy.json"
    write_new(policy_path, json_bytes(policy))
    new_main = {**main, "EnvironmentVariables": {**environment,
        "V4_RESEARCH_RETENTION_POLICY": str(policy_path),
        "V4_RESEARCH_RETENTION_POLICY_SHA256": reference(policy_path)["sha256"]}}
    return base_main, plistlib.dumps(new_main)


def verify_controls(main_raw, projected=None):
    """Read all unchanged and rebound pins through their current or staged paths."""
    from ops.research_storage_retention import load_policy

    settings = plistlib.loads(main_raw)["EnvironmentVariables"]
    policy_path = Path(settings["V4_RESEARCH_RETENTION_POLICY"])
    expected = settings["V4_RESEARCH_RETENTION_POLICY_SHA256"]
    policy = load_policy(policy_path, expected_sha256=expected)
    require(policy["dry_run"] is True and policy["auto_gc_enabled"] is False, "API_CUTOVER_GC_POLICY_DRIFT")
    pins = json.loads(checked_ref(policy["managed_pin_inventory"]))
    readers = json.loads(checked_ref(policy["single_generation_lifecycle"]["reader_inventory"]))
    require(pins["expected_main_app_root"] == settings["V4_APP_ROOT"] and len(pins["source_bindings"]) >= 85,
            "API_CUTOVER_MANAGED_PIN_SCOPE_DRIFT")
    records = list(pins["source_bindings"])
    for reader in readers["consumers"]:
        if "plist_sha256" in reader:
            records.append({"path": reader["plist_path"], "sha256": reader["plist_sha256"]})
        records.extend(reader["source_refs"])
    for item in records:
        raw = (projected or {}).get(item["path"])
        if raw is not None:
            require(digest(raw) == item["sha256"], "API_CUTOVER_PROJECTED_PIN_DRIFT")
        else:
            checked_ref(item)
    return {"policy_sha256": expected, "managed_pin_count": len(pins["source_bindings"]),
            "reader_count": len(readers["consumers"]), "dry_run": True, "auto_gc_enabled": False}


def read_http(port, route, status=200, *, timeout=180):
    try:
        with OPENER.open(f"http://127.0.0.1:{port}{route}", timeout=timeout) as reply:
            code, raw = reply.status, reply.read()
    except HTTPError as error:
        code, raw = error.code, error.read()
    require(code == status, f"API_READBACK_STATUS:{code}:{route}")
    return json.loads(raw)


def archive_route(symbol, entry):
    return DATE_ROUTE + symbol + "/archived-selector?" + urlencode({
        "generation": entry["generation"], "trade_date": "2026-10-30",
        "columns": "close,volume,kb_violence_k,kb_yidong",
    })


def verify_http(port, payload, readback, archive, *, active, full):
    settings = payload["EnvironmentVariables"]
    require(read_http(port, "/healthz") == {"status": "ok"} and read_http(port, "/readyz") == SAFETY,
            "API_HEALTH_OR_RESEARCH_SAFETY_DRIFT")
    identity = read_http(port, "/api/v4/runtime-graph/frontend-build")
    require(identity["status"] == "VERIFIED" and identity["api_release_id"] == settings["V4_RELEASE_ID"]
            and identity["api_manifest_sha256"] == settings["V4_RELEASE_MANIFEST_SHA256"], "API_LOADED_MANIFEST_DRIFT")
    for sample in SAMPLES:
        meta = read_http(port, DATE_ROUTE + sample)
        require(digest(json.dumps(meta, sort_keys=True).encode()) == readback["samples"][sample]["meta_sha256"],
                f"API_DEFAULT_R4_CHANGED:{sample}")
    ready_rows = unknown_rows = 0
    for entry in archive["source"]:
        if not active:
            read_http(port, archive_route(SAMPLES[0], entry), 404)
        else:
            samples = (*SAMPLES, UNKNOWN_SAMPLE) if full else (UNKNOWN_SAMPLE,)
            for sample in samples:
                value = read_http(port, archive_route(sample, entry))
                require(value == readback["exact_archived_routes"][str(entry["number"])][sample],
                        f"API_ARCHIVED_ROW_DRIFT:{entry['number']}:{sample}")
                if sample == UNKNOWN_SAMPLE:
                    unknown_rows += 1
                else:
                    ready_rows += 1
    return {"port": port, "release_id": settings["V4_RELEASE_ID"],
            "manifest_sha256": settings["V4_RELEASE_MANIFEST_SHA256"],
            "r4_sample_count": len(SAMPLES), "archive_full_read": active and full,
            "archive_ready_rows": ready_rows, "archive_unknown_rows": unknown_rows}


def standby(payload, readback, archive, *, full=False):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    settings = {**payload["EnvironmentVariables"], "V4_API_PORT": str(port)}
    args = payload["ProgramArguments"]
    process = subprocess.Popen([*args[:7], str(port), *args[8:]], cwd=payload["WorkingDirectory"],
                               env=settings, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            require(process.poll() is None, "API_STANDBY_EXITED")
            try:
                read_http(port, "/healthz", timeout=2)
            except OSError:
                time.sleep(0.25)
            else:
                return verify_http(port, payload, readback, archive, active=True, full=full)
        raise RuntimeError("API_STANDBY_HEALTH_TIMEOUT")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def prepare(execution_sha):
    require(not TARGET.exists() and TARGET.parent.resolve(strict=True) == TARGET.parent, "RELEASE_TARGET_NOT_FRESH")
    execution, overlays, archive, readbacks = sealed_execution(execution_sha)
    installed = installed_roles()
    plans = prepare_plan(execution_sha, installed, overlays)
    TARGET.mkdir(mode=0o700)
    variants = {}
    for variant, (source, manifest, before, overlay, payload, raw, logical_bytes) in plans.items():
        root = TARGET / variant
        root.mkdir(mode=0o700)
        app = root / "app"
        subprocess.run(["/bin/cp", "-cRp", str(source / "app"), str(app)], check=True, timeout=120)
        for relative, content in overlay.items():
            file = app / relative
            info = file.stat()
            require(file.resolve(strict=True) == file and info.st_nlink == 1 and
                    not os.path.samestat(info, (source / "app" / relative).stat()), "CANDIDATE_CLONE_FILE_ALIASED")
            file.write_bytes(content)
        after = inventory_tree(app)
        indexed = {item["path"]: item for item in after}
        require({item["path"] for item in before} == indexed.keys()
                and {item["path"] for item in before if indexed[item["path"]] != item} == FILES,
                "CANDIDATE_HAS_UNAPPROVED_INVENTORY_DELTA")
        env = payload["EnvironmentVariables"]
        binding = json.loads(checked(env["V4_WORKBENCH_HOST_BINDING"], env["V4_WORKBENCH_HOST_BINDING_SHA256"]))
        require("top200_frozen_selector_archive" not in binding
                and binding.get("RESEARCH_ONLY") is True
                and all(binding.get(key) is value for key, value in SAFETY.items()), "WORKBENCH_BINDING_SCOPE_CONFLICT")
        binding["top200_frozen_selector_archive"] = execution["retained_manifest"]
        binding_path = root / "workbench-binding.json"
        write_new(binding_path, json_bytes(binding))
        release_id = f"v4-top200-archive-20261116-{variant}-api"
        parent_manifest = overlays[ROLE[variant]]["api_manifest_sha256"]
        provenance = {key: manifest.get(key) for key in ("source_root", "source_commit", "source_provenance")}
        manifest.update(release_id=release_id, app_root=str(app), activation_status="PREPARED_NOT_ACTIVATED",
                        deployment_status="PREPARED", parent_manifest_sha256=parent_manifest,
                        parent_release_root=str(source), source_root=str(REPO), source_commit=SOURCE_COMMIT,
                        source_provenance={"base": provenance, "reviewed_commit": SOURCE_COMMIT,
                                           "release_input_execution_sha256": execution_sha},
                        candidate={"root": str(root), "app_root": str(app), "release_id": release_id, "module_role": "api"},
                        application_inventory={"entries": after, "entry_count": len(after),
                                               "aggregate_sha256": inventory_digest(after)},
                        app_files=legacy_inventory(after))
        manifest_file = root / "release-manifest.json"
        write_new(manifest_file, json_bytes(manifest))
        new_payload = rewrite_plist(payload, root, release_id, reference(manifest_file)["sha256"],
                                    reference(binding_path)["sha256"])
        activate, rollback = root / "activate.plist", root / "rollback.plist"
        write_new(activate, plistlib.dumps(new_payload))
        write_new(rollback, raw)
        role_install = installed[ROLE[variant]]
        main_base, main_candidate = bind_main_controls(root, source, digest(raw), reference(activate)["sha256"], role_install)
        main_activate, main_rollback = root / "main-policy-activate.plist", root / "main-policy-rollback.plist"
        write_new(main_activate, main_candidate)
        write_new(main_rollback, main_base)
        stage = checked_ref(role_install["roles"]["stage"]["proposed_plist"])
        stage_live = str(Path.home() / "Library/LaunchAgents/com.lexi.stage-center.scheduler.plist")
        projected = {stage_live: stage}
        old_controls = verify_controls(main_base, {**projected, str(LIVE_API): raw})
        new_controls = verify_controls(main_candidate, {**projected, str(LIVE_API): activate.read_bytes()})
        variants[variant] = {"activate": reference(activate), "rollback": reference(rollback),
            "main_activate": reference(main_activate), "main_rollback": reference(main_rollback),
            "old_controls": old_controls, "new_controls": new_controls,
            "manifest": reference(manifest_file), "binding": reference(binding_path),
            "base_bytes": logical_bytes, "non_delta_sha256": inventory_digest([item for item in after if item["path"] not in FILES]),
            "standby": standby(new_payload, readbacks[variant], archive)}
        require(inventory_tree(app) == after and inventory_tree(source / "app") == before,
                "STANDBY_OR_PREPARATION_CHANGED_IMMUTABLE_API_INVENTORY")
    seal = TARGET / "SEAL.json"
    write_new(seal, json_bytes({"status": "PREPARED_NOT_ACTIVATED", "source": SOURCE_COMMIT,
                               "operator": reference(OPERATOR), "execution_sha256": execution_sha, "variants": variants}))
    return reference(seal)


def sealed_role_assets(artifacts):
    active = {role: checked_ref(artifacts[key]) for role, key in (("api", "activate"), ("main", "main_activate"))}
    base = {role: checked_ref(artifacts[key]) for role, key in (("api", "rollback"), ("main", "main_rollback"))}
    candidate = json.loads(checked_ref(artifacts["manifest"]))
    app = Path(candidate["app_root"])
    inventory = inventory_tree(app)
    require(candidate["application_inventory"]["entries"] == inventory
            and candidate["app_files"] == legacy_inventory(inventory), "SEALED_CANDIDATE_APPLICATION_DRIFT")
    checked_ref(artifacts["binding"])
    return active, base


def reseal(original_sha):
    """Retain the exact cloned release and old seal while verifying the revised operator."""
    initial_path = TARGET / "SEAL.json"
    initial = json.loads(checked(initial_path, original_sha))
    require(initial["status"] == "PREPARED_NOT_ACTIVATED" and initial["source"] == SOURCE_COMMIT
            and set(initial["variants"]) == ROLE.keys(), "BASE_SEAL_IDENTITY_CONFLICT")
    _, _, archive, readbacks = sealed_execution(initial["execution_sha256"])
    receipts = {}
    for variant, artifacts in initial["variants"].items():
        active, _ = sealed_role_assets(artifacts)
        started = time.monotonic()
        readback = standby(plistlib.loads(active["api"]), readbacks[variant], archive, full=True)
        sealed_role_assets(artifacts)
        receipts[variant] = {**readback, "elapsed_seconds": round(time.monotonic() - started, 3)}
    new = TARGET / "SEAL_REV2.json"
    write_new(new, json_bytes({**initial, "operator": reference(OPERATOR),
        "previous_seal": reference(initial_path), "full_standby_readback": receipts}))
    return reference(new)


def readback_source(raw):
    names = {"SAMPLES", "UNKNOWN_SAMPLE", "DATE_ROUTE", "PORT", "OPENER", "SAFETY",
             "archive_route", "read_http", "verify_http", "standby", "sealed_role_assets"}
    definitions = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.FunctionDef):
            targets = [node.name]
        elif isinstance(node, ast.Assign):
            targets = [item.id for item in node.targets if isinstance(item, ast.Name)]
        else:
            continue
        for name in targets:
            if name in names:
                definitions[name] = ast.dump(node, include_attributes=False)
    require(set(definitions) == names, "READBACK_SOURCE_DEFINITIONS_MISSING")
    return definitions


def reseal_recovery(previous_sha):
    """Reuse observed full standby if its original readback code and assets are exact."""
    old_path = TARGET / "SEAL_REV2.json"
    old = json.loads(checked(old_path, previous_sha))
    old_operator = TARGET / "OPERATOR_REV2.py"
    require(readback_source(checked(old_operator, old["operator"]["sha256"])) == readback_source(OPERATOR.read_bytes()),
            "READBACK_SOURCE_CHANGED_FULL_STANDBY_REQUIRED")
    checked_ref(old["previous_seal"])
    sealed_execution(old["execution_sha256"])
    for variant, plan in old["variants"].items():
        sealed_role_assets(plan)
        proof = old["full_standby_readback"][variant]
        require(proof["archive_full_read"] is True and proof["archive_ready_rows"] == 6
                and proof["archive_unknown_rows"] == 2 and proof["manifest_sha256"] == plan["manifest"]["sha256"],
                "STANDBY_RECEIPT_ROLE_IDENTITY_CONFLICT")
    new = TARGET / "SEAL_REV3.json"
    write_new(new, json_bytes({**old, "operator": reference(OPERATOR), "prior_operator": reference(old_operator),
        "full_standby_seal": reference(old_path), "full_standby_reused_with_identical_readback_source": True}))
    return reference(new)


def terminal_result(expected_sha, monitor=NATURAL):
    value = json.loads(checked(monitor / "NATURAL_RESULT.json", expected_sha))
    status = value["status"]
    require(value["trade_date"] == DAY and status in TERMINAL, "NATURAL_DAY_NOT_TERMINAL")
    observed = datetime.fromisoformat(value["observed_at"])
    earliest = datetime(2026, 11, 16, *TERMINAL[status], tzinfo=TZ)
    require(observed.tzinfo is not None and earliest <= observed <= datetime.now(TZ), "NATURAL_TERMINAL_CLOCK_CONFLICT")
    require(not value.get("release_storage_failures") and not value.get("rollback_error"),
            "NATURAL_RELEASE_STABILITY_UNCONFIRMED")
    variant = {"FORWARD": "forward", "COMPAT_ROLLBACK": "compat-rollback"}.get(value["observed_release_variant"])
    require(variant in ROLE and (status != "NATURAL_SESSION_EVIDENCE_VERIFIED_AFTER_COMPAT_ROLLBACK"
            or variant == "compat-rollback") and (status != "NATURAL_SESSION_EVIDENCE_VERIFIED" or variant == "forward"),
            "NATURAL_TERMINAL_ROLE_CONFLICT")
    require(status == "TRADING_DAY_WINDOW_ENDED_WITH_MISSING_RECEIPTS" or value["session_evidence"]["complete"] is True,
            "NATURAL_POSITIVE_RECEIPTS_INCOMPLETE")
    require(set(value["write_receipts"]) == READ_RECEIPTS, "NATURAL_WRITE_RECEIPT_SET_CONFLICT")
    for name, ref in value["write_receipts"].items():
        require(ref["path"] == str(monitor / name), "NATURAL_WRITE_RECEIPT_PATH_CONFLICT")
        body = json.loads(checked_ref(ref))
        require(body["trade_date"] == DAY and body["observed_at"] == value["observed_at"]
                and body["session_status"] == status and body.get("RESEARCH_ONLY") is True
                and body.get("auto_gc_enabled") is False
                and all(body.get(key) is expected for key, expected in SAFETY.items()), "NATURAL_WRITE_RECEIPT_IDENTITY_CONFLICT")
    if variant == "compat-rollback":
        ref = value["rollback_authority"]
        require(ref["path"] == str(monitor.parent / "ROLLBACK_RESULT.json"), "NATURAL_ROLLBACK_AUTHORITY_PATH_CONFLICT")
        body = json.loads(checked_ref(ref))
        require(body["mode"] == "rollback" and body["status"] == "DEPLOYED_AND_READ_BACK"
                and body["install"]["sha256"] == INSTALL_SHA, "NATURAL_COMPAT_ROLLBACK_NOT_READ_BACK")
    return variant, status


def controller():
    path = CONTROL / "switch_activated_exact.py"
    raw = checked(path, CONTROLLER_SHA)
    spec = importlib.util.spec_from_file_location("r1_api_release_controller", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def listeners():
    result = subprocess.run(["/usr/sbin/lsof", "-nP", "-iTCP:8873", "-sTCP:LISTEN", "-t"],
                            capture_output=True, text=True, timeout=5)
    require(result.returncode in (0, 1), "API_LISTENER_STATE_UNCONFIRMED")
    return set(result.stdout.split())


def confirm_api(control, raw, *, wait=False):
    path = control.live("api")
    require(path.read_bytes() == raw, "API_ACTIVE_PLIST_PREIMAGE_MOVED")
    end = time.monotonic() + (45 if wait else 0)
    while True:
        try:
            item = control.exact_job("api")
            require(listeners() == {str(item["pid"])}, "API_LISTENER_PID_NOT_LAUNCHAGENT")
            require(read_http(PORT, "/healthz", timeout=2) == {"status": "ok"}, "API_LISTENER_HEALTH_UNCONFIRMED")
            return item
        except (OSError, ValueError, RuntimeError):
            if time.monotonic() >= end:
                raise
            time.sleep(0.25)


def confirm_role_owner(control, role, raw):
    launch, output = control.state(role)
    settings = plistlib.loads(raw)["EnvironmentVariables"]
    require(launch["loaded"] and launch["path"] == str(control.live(role))
            and launch["working directory"] == settings["V4_APP_ROOT"]
            and settings["V4_RELEASE_ID"] in output and settings["V4_RELEASE_MANIFEST_SHA256"] in output,
            "FOREIGN_LAUNCHAGENT_BLOCKS_AUTORECOVERY")
    if role == "api" and launch["pid"] is not None:
        require(listeners() <= {str(launch["pid"])}, "API_FOREIGN_LISTENER_BLOCKS_AUTORECOVERY")
    if role == "main":
        require(settings["V4_RESEARCH_RETENTION_POLICY_SHA256"] in output, "MAIN_FOREIGN_POLICY_BLOCKS_AUTORECOVERY")


def start_main(control, raw):
    require(control.live("main").read_bytes() == raw, "MAIN_ACTIVE_PLIST_PREIMAGE_MOVED")
    log_offset = control.main_log()
    control.start_role("main")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            main = control.exact_job("main")
        except (OSError, RuntimeError):
            time.sleep(0.25)
            continue
        if control.ready(log_offset, main):
            return main
        time.sleep(0.25)
    raise RuntimeError("MAIN_REBOUND_POLICY_READINESS_TIMEOUT")


def start_group(control, desired):
    require(not listeners(), "API_FOREIGN_LISTENER_BLOCKS_START")
    control.start_role("api")
    api = confirm_api(control, desired["api"], wait=True)
    policy = verify_controls(desired["main"])
    main = start_main(control, desired["main"])
    return {"api": api, "main": main, "policy": policy}


def assert_main_workbench_idle(raw):
    """Use the R1 persisted claim guard when recovery cannot use full-group idle."""
    settings = plistlib.loads(raw)["EnvironmentVariables"]
    config_path = Path(settings["V4_MANAGER_WORKBENCH_CONFIG_PATH"])
    require(config_path.is_absolute() and config_path.resolve(strict=True) == config_path,
            "MAIN_WORKBENCH_CONFIG_PATH_INVALID")
    config = json.loads(config_path.read_bytes())
    root = Path(config["state_root"]) / "manager_workbench"
    for path in (root / "claims").glob("*.json"):
        claim = json.loads(path.read_bytes())
        job = claim.get("job_id")
        if job:
            require(re.fullmatch("[a-f0-9]{32}", job), "MAIN_WORKBENCH_CLAIM_ID_INVALID")
            record = json.loads((root / "attempts" / f"{job}.json").read_bytes())
            require(record.get("state") not in ("RUNNING", "QUEUED"), "MAIN_WORKBENCH_ACTIVE_KEEP_RUNNING")


def restore(control, previous, desired):
    current = {role: control.live(role).read_bytes() for role in previous}
    require(all(current[role] in (previous[role], desired[role]) for role in previous),
            "FOREIGN_PLIST_BLOCKS_AUTORECOVERY")
    loaded = {role: control.state(role)[0]["loaded"] for role in previous}
    for role in ("main", "api"):
        if loaded[role]:
            confirm_role_owner(control, role, current[role])
    if current == previous and all(loaded.values()):
        return {"api": confirm_api(control, previous["api"], wait=True), "main": control.exact_job("main"),
                "policy": verify_controls(previous["main"])}
    if loaded["main"]:
        assert_main_workbench_idle(current["main"])
    for role in ("main", "api"):
        if loaded[role]:
            control.stop_role(role)
    require(not listeners(), "API_FOREIGN_LISTENER_BLOCKS_AUTORECOVERY")
    for role in ("api", "main"):
        if current[role] != previous[role]:
            control.atomic_plist(control.live(role), previous[role], digest(current[role]))
    return start_group(control, previous)


def switch(control, previous, desired, expected_pids, verify):
    live = {role: control.live(role) for role in previous}
    require(all(live[role].read_bytes() == previous[role] for role in previous)
            and control.exact_job("main")["pid"] == expected_pids["main"]
            and confirm_api(control, previous["api"])["pid"] == expected_pids["api"], "LIVE_ROLE_PREIMAGE_MOVED")
    assert_main_workbench_idle(previous["main"])
    try:
        for role in ("main", "api"):
            control.stop_role(role)
        require(not listeners(), "API_OLD_LISTENER_DID_NOT_UNLOAD")
        for role in ("api", "main"):
            control.atomic_plist(live[role], desired[role], digest(previous[role]))
        after = start_group(control, desired)
        return after, verify()
    except BaseException as error:
        try:
            error.exact_recovery = restore(control, previous, desired)
        except BaseException as secondary:
            raise RuntimeError("RELEASE_FAILED_AND_EXACT_RECOVERY_UNCONFIRMED") from BaseExceptionGroup(
                "Release and restoration both failed", [error, secondary])
        raise


def existing_attempts(parent):
    attempts = {}
    for path in parent.iterdir():
        match = ATTEMPT_NAME.fullmatch(path.name)
        if match:
            order = int(match[1])
            require(path.is_dir() and not path.is_symlink() and order not in attempts, "RELEASE_ATTEMPT_ORDER_CONFLICT")
            attempts[order] = path
    return attempts


def attempt_preimage_matches(record, raw, path):
    settings = plistlib.loads(raw)["EnvironmentVariables"]
    return (record["plist"] == {"path": str(path), "sha256": digest(raw), "bytes": len(raw)}
            and record["loaded"] is True and record["state"] == "running"
            and type(record["pid"]) is int and record["pid"] > 0
            and record["app_root"] == settings["V4_APP_ROOT"]
            and record["release_id"] == settings["V4_RELEASE_ID"]
            and record["manifest_sha256"] == settings["V4_RELEASE_MANIFEST_SHA256"])


def unfinished_attempt(path, expected_sha, variant, seal_sha, natural_sha, base, active, live_paths):
    parent = TARGET / variant
    match = ATTEMPT_NAME.fullmatch(path.parent.name)
    require(path.parent.parent == parent and path.name == "START.json" and match
            and not (path.parent / "RESULT.json").exists() and not (path.parent / "RECOVERY_RESULT.json").exists(),
            "RECOVERY_ATTEMPT_NOT_UNFINISHED")
    attempts = existing_attempts(parent)
    require(attempts and attempts[max(attempts)] == path.parent, "RECOVERY_ATTEMPT_SUPERSEDED")
    attempt = json.loads(checked(path, expected_sha))
    operation = match[2]
    previous, desired = (base, active) if operation == "activate" else (active, base)
    preimages = {role: digest(raw) for role, raw in previous.items()}
    targets = {role: digest(raw) for role, raw in desired.items()}
    require(attempt["variant"] == variant and attempt["action"] == operation
            and attempt["natural_sha256"] == natural_sha and attempt["seal_sha256"] == seal_sha
            and attempt["preimages"] == preimages and attempt["target_plists"] == targets
            and set(attempt["before"]) == previous.keys()
            and all(attempt_preimage_matches(attempt["before"][role], previous[role], live_paths[role]) for role in previous),
            "RECOVERY_ATTEMPT_IDENTITY_CONFLICT")
    failure_path = path.parent / "FAILURE.json"
    if failure_path.exists():
        require(failure_path.resolve(strict=True) == failure_path, "RECOVERY_FAILURE_RECEIPT_PATH_CONFLICT")
        failure = json.loads(failure_path.read_bytes())
        require(all(failure.get(key) == value for key, value in attempt.items()), "RECOVERY_FAILURE_RECEIPT_CONFLICT")
        require(failure.get("exact_recovery") is None, "RECOVERY_ALREADY_VERIFIED")
    return attempt, previous, desired


def recover_after_interruption(control, previous, desired, stage, verify, *, expected_pids=None):
    observed = {role: control.live(role).read_bytes() for role in previous}
    require(all(observed[role] in (previous[role], desired[role]) for role in previous),
            "FOREIGN_PLIST_BLOCKS_AUTORECOVERY")
    loaded = {role: control.state(role)[0] for role in previous}
    if expected_pids is not None and (observed != previous or not all(state["loaded"] for state in loaded.values())):
        require(all(not loaded[role]["loaded"] or observed[role] != previous[role]
                    or loaded[role]["pid"] == expected_pids[role] for role in previous),
                "RECOVERY_PREIMAGE_PROCESS_NOT_OWNED")
    recovered = restore(control, previous, desired)
    require(control.exact_job("stage") == stage, "RECOVERY_CHANGED_STAGE_ROLE_STATE")
    return recovered, verify()


def cutover(action, seal_sha, natural_sha, *, start=None, start_sha=None):
    variant, natural_status = terminal_result(natural_sha)
    seal = json.loads(checked(TARGET / "SEAL_REV3.json", seal_sha))
    require(seal["status"] == "PREPARED_NOT_ACTIVATED" and seal["source"] == SOURCE_COMMIT
            and checked_ref(seal["operator"]) == OPERATOR.read_bytes(), "API_RELEASE_SEAL_IDENTITY_CONFLICT")
    previous_seal = seal["previous_seal"]
    require(previous_seal["path"] == str(TARGET / "SEAL.json"), "API_RELEASE_PREVIOUS_SEAL_PATH_CONFLICT")
    checked_ref(previous_seal)
    require(seal["full_standby_seal"]["path"] == str(TARGET / "SEAL_REV2.json"), "API_RELEASE_STANDBY_SEAL_PATH_CONFLICT")
    checked_ref(seal["full_standby_seal"])
    require(seal["full_standby_readback"][variant]["archive_ready_rows"] == 6
            and seal["full_standby_readback"][variant]["archive_unknown_rows"] == 2, "API_RELEASE_FULL_READBACK_REQUIRED")
    _, _, archive, readbacks = sealed_execution(seal["execution_sha256"])
    artifacts = seal["variants"][variant]
    active, base = sealed_role_assets(artifacts)
    installed = installed_roles()
    role = ROLE[variant]
    require(all(digest(raw) == installed[role]["roles"][key]["proposed_plist"]["sha256"] for key, raw in base.items()),
            "API_AND_MAIN_ROLLBACK_BYTES_DRIFT")
    control = controller()
    lock = control.live("api").with_name(".com.lexi.v4.api.release.lock")
    with ExitStack() as stack:
        if action != "check":
            stack.enter_context(owned_interprocess_lock(lock, timeout_seconds=2, timeout_message="API_RELEASE_SHARED_LOCK_BUSY"))
            require(control.live("main").read_bytes() in (base["main"], active["main"]), "LIVE_MAIN_PREIMAGE_UNKNOWN")
            stack.enter_context(control.writer_locks())
        require(terminal_result(natural_sha) == (variant, natural_status), "NATURAL_RESULT_MOVED")
        control.idle()
        stage = control.exact_job("stage")
        stage_expected = installed[role]["roles"]["stage"]
        require(stage["plist"]["sha256"] == stage_expected["proposed_plist"]["sha256"]
                and stage["manifest_sha256"] == stage_expected["manifest"]["sha256"], "R1_STAGE_IDENTITY_DRIFT")
        if action == "recover":
            paths = {role: control.live(role) for role in base}
            attempt, previous, desired = unfinished_attempt(start, start_sha, variant, seal_sha, natural_sha, base, active, paths)
            require(attempt["stage"]["plist"] == stage["plist"]
                    and attempt["stage"]["manifest_sha256"] == stage["manifest_sha256"],
                    "RECOVERY_STAGE_PREIMAGE_CONFLICT")
            verify_controls(previous["main"], {str(control.live("api")): previous["api"]})
            recovered, checks = recover_after_interruption(control, previous, desired, stage, lambda: verify_http(
                PORT, plistlib.loads(previous["api"]), readbacks[variant], archive,
                active=attempt["action"] == "rollback", full=True),
                expected_pids={role: item["pid"] for role, item in attempt["before"].items()})
            result = {"status": "API_AND_MAIN_POLICY_RECOVERY_VERIFIED", "variant": variant,
                      "natural_status": natural_status, "start_sha256": start_sha,
                      "after": recovered, "checks": checks}
            path = start.parent / "RECOVERY_RESULT.json"
            write_new(path, json_bytes(result))
            return {**result, "receipt": reference(path)}

        previous, desired = (active, base) if action == "rollback" else (base, active)
        before = {"api": confirm_api(control, previous["api"]), "main": control.exact_job("main")}
        require(control.live("main").read_bytes() == previous["main"], "MAIN_ACTIVE_PLIST_PREIMAGE_MOVED")
        require(before["main"]["manifest_sha256"] == installed[role]["roles"]["main"]["manifest"]["sha256"],
                "MAIN_ACTIVE_MANIFEST_MOVED")
        verify_controls(previous["main"])
        verify_controls(desired["main"], {str(control.live("api")): desired["api"]})
        check = verify_http(PORT, plistlib.loads(previous["api"]), readbacks[variant], archive,
                            active=action == "rollback", full=False)
        if action == "check":
            return {"status": "READY_FOR_API_SWITCH_WITH_MAIN_POLICY_BINDING", "variant": variant,
                    "natural_status": natural_status, "preimages": {role: digest(raw) for role, raw in previous.items()},
                    "api_pid": before["api"]["pid"], "checks": check}

        def verify():
            require(control.exact_job("stage") == stage, "API_SWITCH_CHANGED_STAGE_ROLE_STATE")
            return verify_http(PORT, plistlib.loads(desired["api"]), readbacks[variant], archive,
                               active=action == "activate", full=True)

        folder = TARGET / variant
        sequence = max(existing_attempts(folder), default=0) + 1
        attempt = folder / f"{sequence:08}-{action}-{datetime.now(TZ):%Y%m%dT%H%M%S%f}-{os.getpid()}"
        attempt.mkdir(mode=0o700)
        header = {"variant": variant, "action": action, "natural_sha256": natural_sha, "seal_sha256": seal_sha,
                  "before": before, "stage": stage, "preimages": {name: digest(raw) for name, raw in previous.items()},
                  "target_plists": {name: digest(raw) for name, raw in desired.items()}}
        write_new(attempt / "START.json", json_bytes(header))
        try:
            after, checks = switch(control, previous, desired, {key: value["pid"] for key, value in before.items()}, verify)
        except BaseException as error:
            write_new(attempt / "FAILURE.json", json_bytes({**header, "error": str(error),
                "exact_recovery": getattr(error, "exact_recovery", None),
                "observed_plists": {role: reference(control.live(role)) for role in ("api", "main", "stage")}}))
            raise
        result = {**header, "status": "API_AND_MAIN_POLICY_" + action.upper() + "_VERIFIED",
                  "natural_status": natural_status, "after": after, "checks": checks}
        write_new(attempt / "RESULT.json", json_bytes(result))
        return {**result, "receipt": reference(attempt / "RESULT.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "reseal", "reseal-recovery", "check", "activate", "rollback", "recover"))
    parser.add_argument("--execution-sha")
    parser.add_argument("--seal-sha")
    parser.add_argument("--natural-sha")
    parser.add_argument("--start", type=Path)
    parser.add_argument("--start-sha")
    args = parser.parse_args()
    if args.action == "prepare":
        needed = (args.execution_sha,)
    elif args.action in ("reseal", "reseal-recovery"):
        needed = (args.seal_sha,)
    else:
        needed = (args.seal_sha, args.natural_sha)
    if args.action == "recover":
        require(args.start is not None, "RECOVERY_START_PATH_REQUIRED")
        needed += (args.start_sha,)
    require(all(re.fullmatch("[a-f0-9]{64}", item or "") for item in needed), "RELEASE_SHA_ARGUMENT_REQUIRED")
    if args.action == "prepare":
        value = prepare(args.execution_sha)
    elif args.action == "reseal":
        value = reseal(args.seal_sha)
    elif args.action == "reseal-recovery":
        value = reseal_recovery(args.seal_sha)
    else:
        value = cutover(args.action, args.seal_sha, args.natural_sha, start=args.start, start_sha=args.start_sha)
    print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
