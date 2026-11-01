"""Task-specific reviewed overlay and bounded API cutover; no action at import.

Run with the pinned PANEL_PYTHON from the task worktree. --check is read-only;
--prepare writes a new private candidate only; --activate/--rollback change the
API LaunchAgent only and must be invoked by the controller after review.
"""
from __future__ import annotations

import argparse
import difflib
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
import sys
import tempfile
import time
import urllib.request

SOURCE = Path(__file__).resolve().parents[3]
BASE_COMMIT = "bbed661f1441239f7a06f093418efb6ceab0c7cc"
HOME = Path("/Users/lexi")
BASE = HOME / "Library/Application Support/com.lexi.v4.local/candidates/perf-date-list-20261101"
TARGET = BASE.parent / "perf-runtime-repair-20261101-r1"
PLIST = HOME / "Library/LaunchAgents/com.lexi.v4.api.plist"
PLIST_SHA = "9d4a872d3d0b7f6246f209969f1dbe31a97fc260ecb77d76e8f498326752f908"
BASE_MANIFEST_SHA = "843d568dd1c43caa8c19d6307369e25288d5cffbfc9ac48e6b5616f77af18979"
TOOLS_SHA = "35ac1a9b6f3ea885b2788a9476dbc2f4dc21f42f43a359b63a0c22265c1fd154"
BASE_FILES = {
    "apps/api/v4_api/app.py": "bbde8f1f62b09d165d6da2f7963536f8d7d4133fa93d3c232a1490c5a1464954",
    "domains/preselection.py": "5f6ec00e0a95ad7d84a858d819924a25e2c78076bf0d82166add23f3b494fd4a",
}
RECEIPT = TARGET / "repair-preparation.json"
STAGED_PLIST = TARGET / "config/com.lexi.v4.api.plist"
BACKUP = TARGET / "config/pre-repair-com.lexi.v4.api.plist"
DOMAIN = f"gui/{os.getuid()}"
JOB = DOMAIN + "/com.lexi.v4.api"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def api_tools():
    # The deployed manifest uses module_role=api and has no role-contract file.
    # Reuse its pinned official inventory/diff primitives; its newer high-level
    # gateway/stage/manager API cannot validate this package's existing schema.
    path = BASE / "app/ops/api_release_integration.py"
    if sha(path.read_bytes()) != TOOLS_SHA:
        raise ValueError("OFFICIAL_INVENTORY_TOOL_DRIFT")
    spec = importlib.util.spec_from_file_location("perf_repair_official_inventory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_lock():
    # Existing V4 API mutex is .com.lexi.v4.api.release.lock.mutex.
    # The absent/incompatible gateway role-contract points at the retired V35
    # plist, so do not call or rewrite that contract for this task.
    sys.path.insert(0, str(BASE / "app"))
    from infrastructure.interprocess_lock import owned_interprocess_lock
    return owned_interprocess_lock(PLIST.with_name(".com.lexi.v4.api.release.lock"),
        timeout_seconds=2, timeout_message="API_RELEASE_SHARED_LOCK_BUSY")


def source_provenance():
    pins = json.loads((SOURCE / "docs/handoffs/perf-runtime-repair-20261101/source-receipt.json").read_text())
    return {"baseline_commit": BASE_COMMIT, "commit_contains_repair": False,
        "worktree_root": str(SOURCE), "source_state": "REVIEWED_UNCOMMITTED_DELTA",
        "reviewed_source_sha256": {name: pins["files"][name]["after_sha256"] for name in sorted(BASE_FILES)},
        "runtime_base_release_root": str(BASE), "runtime_base_manifest_sha256": BASE_MANIFEST_SHA}


def assert_manifest_identity(manifest, root, *, original=False):
    expected = {"root": str(BASE.parent if original else root),
        "app_root": str(root / "app"), "release_id": root.name, "module_role": "api"}
    if manifest.get("schema_version") != "v4.release_candidate.v1" or manifest.get("candidate") != expected:
        raise ValueError("REPAIR_SCHEMA_OR_IDENTITY_MISMATCH")
    if not original and (manifest.get("release_id") != expected["release_id"]
            or manifest.get("app_root") != expected["app_root"]
            or manifest.get("source_root") != str(SOURCE)
            or manifest.get("source_commit") != BASE_COMMIT
            or manifest.get("source_provenance") != source_provenance()):
        raise ValueError("REPAIR_TOP_LEVEL_IDENTITY_OR_PROVENANCE_MISMATCH")


def set_candidate_metadata(manifest):
    manifest["candidate"].update(root=str(TARGET), app_root=str(TARGET / "app"), release_id=TARGET.name)
    manifest.update(release_id=TARGET.name, app_root=str(TARGET / "app"),
        source_root=str(SOURCE), source_commit=BASE_COMMIT,
        source_provenance=source_provenance())
    return manifest


def release_files(root, expected_sha, *, original=False):
    tools = api_tools()
    tools._exact_path(root, kind="directory", label="REPAIR_RELEASE")
    manifest_path = tools._exact_path(root / "release-manifest.json", kind="file", label="REPAIR_MANIFEST")
    raw = manifest_path.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError("REPAIR_MANIFEST_SHA_MISMATCH")
    manifest = json.loads(raw)
    assert_manifest_identity(manifest, root, original=original)
    actual = tools.inventory_tree(root / "app")
    record = manifest["application_inventory"]
    if (record.get("entries") != actual or record.get("entry_count") != len(actual)
            or record.get("aggregate_sha256") != tools.inventory_digest(actual)
            or manifest.get("app_files") != actual):
        raise ValueError("REPAIR_INVENTORY_OR_APP_FILES_DRIFT")
    return manifest, actual


def preflight_base(*, check_plist=True):
    if check_plist and sha(PLIST.read_bytes()) != PLIST_SHA:
        raise ValueError("ACTIVE_PLIST_CAS_CHANGED")
    manifest, inventory = release_files(BASE, BASE_MANIFEST_SHA, original=True)
    if check_plist:
        payload = plistlib.loads(PLIST.read_bytes())
        env = payload["EnvironmentVariables"]
        if (payload.get("Label") != "com.lexi.v4.api"
                or payload.get("WorkingDirectory") != str(BASE / "app")
                or env.get("V4_APP_ROOT") != str(BASE / "app")
                or env.get("V4_RELEASE_ID") != BASE.name
                or env.get("V4_RELEASE_MANIFEST_PATH") != str(BASE / "release-manifest.json")
                or env.get("V4_RELEASE_MANIFEST_SHA256") != BASE_MANIFEST_SHA):
            raise ValueError("ACTIVE_PLIST_IDENTITY_MISMATCH")
    return manifest, inventory


def verify_candidate(*, expected_manifest_sha256, active_pointer="base"):
    tools = api_tools()
    preflight_base(check_plist=active_pointer == "base")
    manifest, inventory = release_files(TARGET, expected_manifest_sha256)
    integration = manifest.get("repair_integration", {})
    delta_path = TARGET / "reviewed-delta.json"
    delta_raw = delta_path.read_bytes()
    delta = json.loads(delta_raw)
    if (integration.get("schema_version") != "v4.perf_runtime_repair.integration.v1"
            or integration.get("base_manifest_sha256") != BASE_MANIFEST_SHA
            or integration.get("delta_receipt_sha256") != sha(delta_raw)
            or delta.get("base_manifest_sha256") != BASE_MANIFEST_SHA
            or delta.get("schema_version") != "v4.perf_runtime_repair.delta.v1"
            or "api_integration" in manifest):
        raise ValueError("REPAIR_BASE_OR_DELTA_BINDING_MISMATCH")
    entries = delta["entries"]
    overlays = checked_overlay(check_plist=False)
    if ([item["path"] for item in entries] != sorted(BASE_FILES)
            or any(item["before_sha256"] != BASE_FILES[item["path"]]
                   or item["after_sha256"] != sha(overlays[item["path"]]) for item in entries)):
        raise ValueError("REPAIR_REVIEWED_DELTA_MISMATCH")
    records, preserved = tools._verify_delta_files(
        base_app=BASE / "app", candidate_app=TARGET / "app", entries=entries)
    if (integration.get("delta_entries") != records
            or integration.get("non_delta_entry_count") != len(preserved)
            or integration.get("non_delta_inventory_sha256") != tools.inventory_digest(preserved)):
        raise ValueError("REPAIR_NON_DELTA_PROOF_MISMATCH")
    staged = plistlib.loads(STAGED_PLIST.read_bytes())
    env = staged["EnvironmentVariables"]
    if (staged.get("WorkingDirectory") != str(TARGET / "app")
            or env.get("V4_APP_ROOT") != str(TARGET / "app")
            or env.get("V4_RELEASE_ID") != TARGET.name
            or env.get("V4_RELEASE_MANIFEST_PATH") != str(TARGET / "release-manifest.json")
            or env.get("V4_RELEASE_MANIFEST_SHA256") != expected_manifest_sha256):
        raise ValueError("STAGED_PLIST_IDENTITY_MISMATCH")
    return {"status": "PASS", "schema": "TASK_SPECIFIC_PINNED_API_MANIFEST",
        "module_role": "api", "application_inventory_entry_count": len(inventory),
        "application_inventory_sha256": tools.inventory_digest(inventory),
        "base_manifest_sha256": BASE_MANIFEST_SHA, "delta_paths": sorted(BASE_FILES),
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": tools.inventory_digest(preserved)}


def exact_overlay(before: bytes, after: bytes, live: bytes) -> bytes:
    """Apply reviewed hunks with exact, unique context; never replace live app."""
    old, new = before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True)
    result = live.decode()
    cursor = 0
    for group in difflib.SequenceMatcher(None, old, new, autojunk=False).get_grouped_opcodes(3):
        old_text = "".join(old[group[0][1]:group[-1][2]])
        new_text = "".join(new[group[0][3]:group[-1][4]])
        if not old_text or result.count(old_text) != 1:
            raise ValueError("INCOMPATIBLE_OR_AMBIGUOUS_LIVE_HUNK")
        pos = result.index(old_text)
        if pos < cursor:
            raise ValueError("LIVE_HUNK_ORDER_MISMATCH")
        result = result[:pos] + new_text + result[pos + len(old_text):]
        cursor = pos + len(new_text)
    return result.encode()


def checked_overlay(*, check_plist=True):
    if check_plist and sha(PLIST.read_bytes()) != PLIST_SHA:
        raise ValueError("ACTIVE_PLIST_CAS_CHANGED")
    pins = json.loads((SOURCE / "docs/handoffs/perf-runtime-repair-20261101/source-receipt.json").read_text())
    result = {}
    for relative, expected in BASE_FILES.items():
        live = (BASE / "app" / relative).read_bytes()
        if sha(live) != expected:
            raise ValueError("BASE_FILE_CAS_CHANGED:" + relative)
        before = subprocess.check_output(["git", "show", f"{BASE_COMMIT}:{relative}"], cwd=SOURCE)
        after = (SOURCE / relative).read_bytes()
        if sha(after) != pins["files"][relative]["after_sha256"]:
            raise ValueError("REVIEWED_SOURCE_CHANGED:" + relative)
        result[relative] = exact_overlay(before, after, live)
    return result


def check_detailed_identity(detail, staged_env):
    for key in ("release_id_status", "app_root_status", "release_manifest_sha_status"):
        if detail.get(key) != "VERIFIED":
            raise ValueError("DETAILED_IDENTITY_FIELD_NOT_VERIFIED:" + key)
    for key in ("V4_RELEASE_ID", "V4_APP_ROOT", "V4_RELEASE_MANIFEST_SHA256"):
        if detail.get("declared_environment", {}).get(key) != staged_env[key]:
            raise ValueError("DETAILED_STAGED_PIN_MISMATCH:" + key)
    # The read-only identity reader compares against the still-active plist.
    # Exclude only that comparison and its aggregate; validate all remaining
    # detailed fields, retaining missing receipt/inventory evidence as unknown.
    ignored = {"status", "plist_bindings", "plist_binding_status", "identity_payload_sha256"}
    relevant = {key: value for key, value in detail.items() if key not in ignored}

    def drift_paths(value, prefix=""):
        if isinstance(value, dict):
            return [item for key, child in value.items() for item in drift_paths(child, prefix + "/" + key)]
        if isinstance(value, list):
            return [item for index, child in enumerate(value) for item in drift_paths(child, prefix + "/" + str(index))]
        return [prefix] if value == "DRIFT" else []

    drift = drift_paths(relevant)
    if drift:
        raise ValueError("DETAILED_IDENTITY_DRIFT:" + ",".join(drift))
    keys = ("release_id_status", "app_root_status", "release_manifest_sha_status",
            "receipt_status", "runtime_inventory_status", "runtime_dependency_manifest_status",
            "selected_modules_status")
    return {"staged_release_pins": "VERIFIED", "relevant_drift_paths": [],
        "statuses": {key: detail.get(key, "CANNOT_CONFIRM") for key in keys},
        "live_plist_binding_status": detail.get("plist_binding_status", "CANNOT_CONFIRM"),
        "live_plist_comparison_excluded": True,
        "aggregate_status_before_staged_filter": detail.get("status", "CANNOT_CONFIRM")}


def validate_process_files(plist_path):
    payload = plistlib.loads(plist_path.read_bytes())
    env = {**os.environ, **payload["EnvironmentVariables"]}
    code = """import json
from infrastructure.scheduling.dispatcher import validate_release_identity
from apps.api.v4_api.runtime_graph_router import _frontend_build_identity, _runtime_identity
identity = validate_release_identity()
frontend = _frontend_build_identity()
assert frontend['status'] == 'VERIFIED', frontend
print(json.dumps({'identity': identity, 'frontend': frontend, 'raw_runtime_identity': _runtime_identity()}))
"""
    result = json.loads(subprocess.check_output(
        [payload["ProgramArguments"][0], "-B", "-c", code],
        cwd=payload["WorkingDirectory"], env=env, text=True, timeout=30,
    ))
    result["detailed_identity"] = check_detailed_identity(result.pop("raw_runtime_identity"), payload["EnvironmentVariables"])
    return result


def prepare():
    tools = api_tools()
    overlays = checked_overlay()
    base_manifest, base_inventory = preflight_base()
    required = sum(int(item.get("size", 0)) for item in base_inventory)
    if shutil.disk_usage(TARGET.parent).free < required * 2 + 1024 ** 3:
        raise ValueError("INSUFFICIENT_CANDIDATE_SPACE")
    TARGET.mkdir()  # refuses existing candidate; never overwrite a snapshot
    shutil.copytree(BASE / "app", TARGET / "app", symlinks=True)
    if tools.inventory_tree(TARGET / "app") != base_inventory:
        raise ValueError("BASE_COPY_DRIFT")
    entries = []
    for relative, raw in sorted(overlays.items()):
        path = tools._safe_child(TARGET / "app", relative, allow_missing=False)
        mode = path.stat().st_mode & 0o777
        try:
            path.chmod(mode | 0o200)
            path.write_bytes(raw)
        finally:
            path.chmod(mode)
        before = (BASE / "app" / relative).read_bytes()
        proof, count = tools._diff_proof(before, raw)
        entries.append({"path": relative, "before_sha256": sha(before),
                        "after_sha256": sha(raw), "unified_diff_sha256": proof,
                        "unified_diff_hunk_count": count})
    delta = TARGET / "reviewed-delta.json"
    json_write(delta, {"schema_version": "v4.perf_runtime_repair.delta.v1",
                      "base_manifest_sha256": BASE_MANIFEST_SHA, "entries": entries})
    records, preserved = tools._verify_delta_files(
        base_app=BASE / "app", candidate_app=TARGET / "app", entries=entries)
    manifest = base_manifest
    # Preserve the original api module schema. Its inherited gateway integration
    # record cannot describe this repair and is retained only in the pinned base.
    manifest.pop("api_integration", None)
    set_candidate_metadata(manifest)
    inventory = tools.inventory_tree(TARGET / "app")
    manifest["application_inventory"] = {"entries": inventory, "entry_count": len(inventory),
                                        "aggregate_sha256": tools.inventory_digest(inventory)}
    manifest["app_files"] = inventory
    manifest["repair_integration"] = {
        "schema_version": "v4.perf_runtime_repair.integration.v1",
        "base_release_root": str(BASE), "base_manifest_sha256": BASE_MANIFEST_SHA,
        "delta_receipt_sha256": sha(delta.read_bytes()), "delta_entries": records,
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": tools.inventory_digest(preserved)}
    manifest.update(activation_status="NOT_ACTIVATED", deployment_status="CANNOT_CONFIRM")
    json_write(TARGET / "release-manifest.json", manifest)
    payload = plistlib.loads(PLIST.read_bytes())
    env = payload["EnvironmentVariables"]
    env.update(V4_APP_ROOT=str(TARGET / "app"), V4_RELEASE_ID=TARGET.name,
               V4_RELEASE_MANIFEST_PATH=str(TARGET / "release-manifest.json"),
               V4_RELEASE_MANIFEST_SHA256=sha((TARGET / "release-manifest.json").read_bytes()))
    payload["WorkingDirectory"] = str(TARGET / "app")
    STAGED_PLIST.parent.mkdir()
    STAGED_PLIST.write_bytes(plistlib.dumps(payload))
    BACKUP.write_bytes(PLIST.read_bytes())
    verified = verify_candidate(expected_manifest_sha256=env["V4_RELEASE_MANIFEST_SHA256"])
    process = validate_process_files(STAGED_PLIST)
    json_write(RECEIPT, {"status": "PREPARED_NOT_ACTIVATED", "base_plist_sha256": PLIST_SHA,
        "candidate_plist_sha256": sha(STAGED_PLIST.read_bytes()),
        "manifest_sha256": env["V4_RELEASE_MANIFEST_SHA256"],
        "verification": verified, "isolated_identity": process})
    print(json.dumps({"status": "PREPARED_NOT_ACTIVATED", "receipt": str(RECEIPT)}))


def repair_prepared_metadata():
    # Exact previously prepared artifacts; preserve them before a metadata-only
    # repair. The existing app and reviewed-delta bytes must remain unchanged.
    expected_manifest = "1c1895521af351118d85e826d8014ad9b9c96e54d5a3dc30a5a51b1a3e61c11f"
    expected_receipt = "ef52beb743621955a666781b215b2df9ac1c86139d06914dff883c9158cbc55b"
    manifest_path = TARGET / "release-manifest.json"
    if sha(manifest_path.read_bytes()) != expected_manifest or sha(RECEIPT.read_bytes()) != expected_receipt:
        raise ValueError("PREPARED_METADATA_CAS_CHANGED")
    tools = api_tools()
    base_manifest, _ = preflight_base()
    old = json.loads(manifest_path.read_text())
    before_inventory = tools.inventory_tree(TARGET / "app")
    if (old["application_inventory"]["entries"] != before_inventory
            or old["app_files"] != before_inventory
            or tools.inventory_digest(before_inventory) != "9772f211dd1cc8f6ac9e7097ade338216410fe854ecec54120cfa140263fde36"):
        raise ValueError("PREPARED_APP_DRIFT")
    entries = json.loads((TARGET / "reviewed-delta.json").read_text())["entries"]
    records, preserved = tools._verify_delta_files(base_app=BASE / "app", candidate_app=TARGET / "app", entries=entries)
    evidence = TARGET / "metadata-before-top-level-identity-fix"
    evidence.mkdir()  # one operation only; no overwrite or blind retries
    for path in (manifest_path, STAGED_PLIST, RECEIPT):
        (evidence / path.name).write_bytes(path.read_bytes())
    manifest = set_candidate_metadata(base_manifest)
    manifest.pop("api_integration", None)
    manifest["application_inventory"] = old["application_inventory"]
    manifest["app_files"] = before_inventory
    manifest["repair_integration"] = old["repair_integration"]
    manifest.update(activation_status="NOT_ACTIVATED", deployment_status="CANNOT_CONFIRM")
    assert records == manifest["repair_integration"]["delta_entries"]
    assert tools.inventory_digest(preserved) == manifest["repair_integration"]["non_delta_inventory_sha256"]

    def replace_metadata(path, raw):
        # Only this non-active candidate's three owned metadata files.
        if path not in (manifest_path, STAGED_PLIST, RECEIPT):
            raise ValueError("METADATA_PATH_OUT_OF_SCOPE")
        if path.read_bytes() != (evidence / path.name).read_bytes():
            raise ValueError("PREPARED_METADATA_CAS_CHANGED:" + path.name)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".metadata-repair-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                temporary.chmod(path.stat().st_mode & 0o777)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    replace_metadata(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    manifest_sha = sha(manifest_path.read_bytes())
    payload = plistlib.loads(PLIST.read_bytes())
    payload["WorkingDirectory"] = str(TARGET / "app")
    payload["EnvironmentVariables"].update(V4_APP_ROOT=str(TARGET / "app"), V4_RELEASE_ID=TARGET.name,
        V4_RELEASE_MANIFEST_PATH=str(manifest_path), V4_RELEASE_MANIFEST_SHA256=manifest_sha)
    replace_metadata(STAGED_PLIST, plistlib.dumps(payload))
    verified = verify_candidate(expected_manifest_sha256=manifest_sha)
    process = validate_process_files(STAGED_PLIST)
    if tools.inventory_tree(TARGET / "app") != before_inventory:
        raise ValueError("APP_CHANGED_DURING_METADATA_REPAIR")
    receipt = {"status": "PREPARED_NOT_ACTIVATED", "base_plist_sha256": PLIST_SHA,
        "candidate_plist_sha256": sha(STAGED_PLIST.read_bytes()), "manifest_sha256": manifest_sha,
        "verification": verified, "isolated_identity": process,
        "metadata_revision": "TOP_LEVEL_IDENTITY_AND_SOURCE_PROVENANCE_REPAIRED",
        "superseded_manifest_sha256": expected_manifest, "superseded_preparation_sha256": expected_receipt,
        "preserved_evidence_root": str(evidence), "application_bytes_changed": False}
    replace_metadata(RECEIPT, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({"status": "PREPARED_METADATA_REPAIRED_NOT_ACTIVATED", "receipt": str(RECEIPT)}))


def launchctl(*args):
    result = subprocess.run(["/bin/launchctl", *args], text=True, capture_output=True, timeout=10)
    return result


def listener_present():
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", 8873)) == 0


def unload():
    printed = launchctl("print", JOB)
    if printed.returncode == 0:
        result = launchctl("bootout", JOB)
        if result.returncode:
            raise RuntimeError("BOOTOUT_FAILED:" + result.stderr)
    elif "Could not find service" not in printed.stderr:
        raise RuntimeError("JOB_STATE_UNKNOWN:" + printed.stderr)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = launchctl("print", JOB)
        if result.returncode and "Could not find service" in result.stderr:
            if not listener_present():
                return
        elif result.returncode:
            raise RuntimeError("UNLOAD_STATE_UNKNOWN:" + result.stderr)
        time.sleep(0.2)
    raise RuntimeError("UNLOAD_OR_LISTENER_TIMEOUT; no bootstrap attempted")


def atomic_plist(raw):
    # Same-directory atomic replace; preserve existing plist mode.
    mode = PLIST.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile(dir=PLIST.parent, prefix=".v4-perf-repair-", delete=False) as stream:
        path = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            path.chmod(mode)
            os.replace(path, PLIST)
        finally:
            path.unlink(missing_ok=True)


def assert_live(expected_id, expected_manifest, *, frontend):
    printed = launchctl("print", JOB)
    match = re.search(r"\bpid = (\d+)", printed.stdout)
    if printed.returncode or not match:
        raise ValueError("LIVE_JOB_PID_MISSING")
    listeners = subprocess.check_output(["/usr/sbin/lsof", "-nP", "-iTCP:8873", "-sTCP:LISTEN", "-t"], text=True, timeout=5)
    if set(listeners.split()) != {match.group(1)}:
        raise ValueError("LISTENER_PID_MISMATCH")

    def fetch(route):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                "http://127.0.0.1:8873" + route, timeout=10) as response:
            return json.load(response)
    if fetch("/readyz") != {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}:
        raise ValueError("LIVE_SAFETY_FLAGS_INVALID")
    if fetch("/healthz") != {"status": "ok"}:
        raise ValueError("HEALTH_RESPONSE_INVALID")
    identity = fetch("/api/v1/runs/date-list")["runtime_identity"]
    if (identity.get("status") != "MANIFEST_EXECUTION_FILES_VERIFIED"
            or identity.get("release_id") != expected_id
            or identity.get("manifest_sha256") != expected_manifest):
        raise ValueError("LIVE_RELEASE_IDENTITY_MISMATCH")
    if frontend:
        build = fetch("/api/v4/runtime-graph/frontend-build")
        if (build.get("status") != "VERIFIED" or build.get("api_release_id") != expected_id
                or build.get("api_manifest_sha256") != expected_manifest):
            raise ValueError("LIVE_FRONTEND_IDENTITY_MISMATCH")


def start_and_validate(raw, *, frontend):
    payload = plistlib.loads(raw)
    result = launchctl("bootstrap", DOMAIN, str(PLIST))
    if result.returncode:
        raise RuntimeError("BOOTSTRAP_FAILED:" + result.stderr)
    expected = payload["EnvironmentVariables"]
    deadline = time.monotonic() + 30
    last = None
    while time.monotonic() < deadline:
        try:
            assert_live(expected["V4_RELEASE_ID"], expected["V4_RELEASE_MANIFEST_SHA256"], frontend=frontend)
            return
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            last = repr(error)
            time.sleep(0.3)
    raise RuntimeError("READINESS_TIMEOUT:" + str(last))


def switch(*, rollback=False):
    with release_lock():
        receipt = json.loads(RECEIPT.read_text())
        old, new = BACKUP.read_bytes(), STAGED_PLIST.read_bytes()
        if sha(old) != PLIST_SHA or sha(new) != receipt["candidate_plist_sha256"]:
            raise ValueError("PREPARED_PLIST_DRIFT")
        expected_current = sha(new) if rollback else PLIST_SHA
        if sha(PLIST.read_bytes()) != expected_current:
            raise ValueError("ACTIVE_PLIST_CAS_CHANGED")
        verify_candidate(expected_manifest_sha256=receipt["manifest_sha256"],
            active_pointer="candidate" if rollback else "base")
        validate_process_files(STAGED_PLIST)  # before any service change
        desired, previous = (old, new) if rollback else (new, old)
        # Failure before unload completes leaves the original plist untouched.
        unload()
        try:
            if sha(PLIST.read_bytes()) != expected_current:
                raise ValueError("ACTIVE_PLIST_CAS_CHANGED_AFTER_UNLOAD")
            atomic_plist(desired)
            start_and_validate(desired, frontend=not rollback)
        except BaseException as primary:
            try:
                if PLIST.read_bytes() not in (desired, previous):
                    raise ValueError("ROLLBACK_CAS_CONFLICT")
                unload()
                if PLIST.read_bytes() not in (desired, previous):
                    raise ValueError("ROLLBACK_CAS_CONFLICT_AFTER_UNLOAD")
                atomic_plist(previous)
                start_and_validate(previous, frontend=rollback)
            except BaseException as recovery:
                raise RuntimeError(f"CUTOVER_FAILED:{primary!r}; AUTOMATIC_ROLLBACK_FAILED:{recovery!r}") from primary
            raise RuntimeError(f"CUTOVER_FAILED:{primary!r}; AUTOMATIC_ROLLBACK_VERIFIED") from primary
        print(json.dumps({"status": "ROLLBACK_VERIFIED" if rollback else "ACTIVATED_VERIFIED"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "repair-prepared-metadata", "activate", "rollback"))
    action = parser.parse_args().action
    if action == "check":
        overlays = checked_overlay()
        _, inventory = preflight_base()
        print(json.dumps({"status": "PINNED_LIVE_PREFLIGHT_PASS", "inventory_entries": len(inventory), "overlays": {key: sha(value) for key, value in overlays.items()}}))
    elif action == "prepare":
        prepare()
    elif action == "repair-prepared-metadata":
        repair_prepared_metadata()
    else:
        switch(rollback=action == "rollback")
