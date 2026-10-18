#!/usr/bin/env python3
"""Build an inactive, SHA-bound API candidate for the Friday close resolver gap.

This helper is deliberately bound to the reviewed r4 API baseline and one source
delta. It does not activate a release, change a plist, write canonical data, or
submit a manager-workbench selection.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[3]
HANDOFF = Path(__file__).resolve().parent
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
CONFIG = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-hk-recovery-v2r1-20261016-r2.json")
ACTIVE_RELEASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-contract-repair-20261018-r4")
ACTIVE_APP = ACTIVE_RELEASE / "app"
RELEASES = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases")
CANDIDATE_RELEASE_ID = "friday-close-input-api-20261018-r1"
CANDIDATE_ROOT = RELEASES / CANDIDATE_RELEASE_ID
RELATIVE_SOURCE = "v4/manager_workbench/inputs/source_bindings.py"
ACTIVE_MANIFEST_SHA = "1d2adb1894bcb91baacf2396516409db1b2fd71755795675e81cfbed292f190b"
ACTIVE_INVENTORY_SHA = "b212852fd7e0425de7ad554e7ce4e72932d36f4f5e40254b1472b7aebdabac92"
ACTIVE_MODULE_SHA = "e1e5a52ec1cf5b214d09b1d8d9c5063ce45b0f35c052f1fad2dce47478f8a145"
ACTIVE_PLIST_SHA = "38a71ac87ee83c1c04f4078e1c99cd07aa464ed08ff9b209beaffb84785377fb"
CANONICAL_MODULE_SHA = "8157fe45536cb83ed03ccd7300f603fa26dd263098338487c15190d8ac5a1528"
OWNER_ARTIFACT_SHA = "bb79cb28341c83e7e4c1b96eb2b1cc411332efd9d96301f226b7845d23d1bd0f"
OWNER_RECEIPT_SHA = "2efaa324645d0d9de3226ca13e9709b0239d2f10947ba2b879fa0d17be4e999d"
OWNER_MANIFEST_SHA = "97b478fb8afe0f6ba87e69261c150f7d1f2ff3ff92601185e91b85998677111e"
OWNER_ARTIFACT_REL = "research/peripherals/20261017/external_finance.json"
OWNER_RECEIPT_REL = "receipts/research/peripherals/20261017/external_finance.json"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def canonical_resolver_prelude(canonical_text: str) -> str:
    start_marker = "def us_mapping(config, context):\n"
    end_marker = "    evidence,esha=read(config.relation_root,config.relation_evidence_relative)\n"
    start = canonical_text.find(start_marker)
    if start < 0:
        raise ValueError("CANONICAL_US_MAPPING_FUNCTION_MISSING")
    end = canonical_text.find(end_marker, start)
    if end < 0:
        raise ValueError("CANONICAL_US_MAPPING_RESOLVER_BOUNDARY_MISSING")
    block = canonical_text[start:end]
    required = (
        "capture_session_date",
        "US_OWNER_SESSION_ARTIFACT_NOT_UNIQUE",
        "market_snapshot_sha256",
        "validate_research_peripheral",
    )
    if any(token not in block for token in required):
        raise ValueError("CANONICAL_US_MAPPING_RESOLVER_CONTRACT_MISSING")
    if "artifact_date" in block:
        raise ValueError("CANONICAL_RESOLVER_UNEXPECTED_DOWNSTREAM_DELTA")
    return block


def merged_api_source(active_text: str, resolver_prelude: str) -> str:
    start_marker = "def us_mapping(config, context):\n"
    downstream_marker = '    snapshot_contract = snapshot.get("universe_contract")\n'
    start = active_text.find(start_marker)
    if start < 0:
        raise ValueError("ACTIVE_US_MAPPING_FUNCTION_MISSING")
    end = active_text.find(downstream_marker, start)
    if end < 0:
        raise ValueError("ACTIVE_US_MAPPING_DOWNSTREAM_BOUNDARY_MISSING")
    active_prelude = active_text[start:end]
    if not active_prelude.strip():
        raise ValueError("ACTIVE_US_MAPPING_PRELUDE_EMPTY")
    if "registry_source" not in active_text[end:]:
        raise ValueError("ACTIVE_API_RELATION_REGISTRY_BEHAVIOR_MISSING")
    # The canonical candidate supplies only the owner/session resolver prelude.
    # API r4's universe validation and relation registry remain byte-preserved.
    return (
        active_text[:start]
        + resolver_prelude
        + "    artifact_date = Path(quote_rel).parts[2]\n\n"
        + active_text[end:]
    )


PROBE = r'''import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
app, config_path, mode = sys.argv[1:]
sys.path.insert(0, app)
from v4.manager_workbench.config import load_config
from v4.manager_workbench.contracts import Phase, RunContext
from v4.manager_workbench.inputs import source_bindings
config = load_config(config_path)
context = RunContext(
    target_date="20261020", phase=Phase.MANUAL,
    cutoff=datetime.now(timezone.utc).isoformat(), trigger="MANUAL",
    source_sessions={"us": "20261016", "hk_price": "20261016"},
    rules_version=config.rules_version, scope_refs={},
)
try:
    binding = source_bindings.us_mapping(config, context)
except Exception as exc:
    print(json.dumps({"mode": mode, "status": "EXPECTED_BASELINE_FAILURE" if mode == "baseline" else "FAIL",
                      "exception_type": type(exc).__name__, "error": str(exc)}, sort_keys=True))
    sys.exit(0 if mode == "baseline" and isinstance(exc, ValueError)
             and str(exc) == "US_OWNER_RECEIPT_ARTIFACT_SESSION_INVALID" else 2)
if mode == "baseline":
    print(json.dumps({"mode": mode, "status": "UNEXPECTED_BASELINE_PASS",
                      "quote_relative": binding.get("quote_relative")}, sort_keys=True))
    sys.exit(2)
payload, observed_artifact_sha = source_bindings.read(
    config.us_root, binding["quote_relative"], binding["quote_sha256"])
snapshot = payload.get("market_snapshot", {})
quotes = snapshot.get("quotes", [])
quote_symbols = [row.get("symbol") for row in quotes if isinstance(row, dict)]
expected_symbols = binding.get("configured_symbols")
assert binding.get("quote_relative") == "research/peripherals/20261017/external_finance.json"
assert binding.get("quote_sha256") == "bb79cb28341c83e7e4c1b96eb2b1cc411332efd9d96301f226b7845d23d1bd0f"
assert observed_artifact_sha == binding.get("quote_sha256")
assert binding.get("owner_receipt_relative") == "receipts/research/peripherals/20261017/external_finance.json"
assert binding.get("owner_receipt_sha256") == "2efaa324645d0d9de3226ca13e9709b0239d2f10947ba2b879fa0d17be4e999d"
assert binding.get("capture_session_date") == "20261016"
assert binding.get("capture_phase") == "POST_CLOSE"
assert binding.get("capture_status") == "READY"
assert len(expected_symbols) == 48 and len(set(expected_symbols)) == 48
assert len(quote_symbols) == 48 and len(set(quote_symbols)) == 48
assert set(quote_symbols) == set(expected_symbols)
assert binding.get("owner_manifest_ref") == "research/peripherals/manifest.json"
assert binding.get("owner_manifest_sha256") == "97b478fb8afe0f6ba87e69261c150f7d1f2ff3ff92601185e91b85998677111e"
required_api_fields = (
    "quote_artifact_date", "quote_source_session", "universe_contract",
    "universe_version", "source_gaps_by_symbol", "relation_projection",
    "relation_registry_version", "factor_exposure_gap", "full_overlay_summary",
)
assert all(key in binding for key in required_api_fields)
print(json.dumps({
    "mode": mode, "status": "PASS", "target_date": context.target_date,
    "source_session": context.source_sessions["us"],
    "quote_relative": binding["quote_relative"],
    "quote_sha256": binding["quote_sha256"],
    "owner_receipt_relative": binding["owner_receipt_relative"],
    "owner_receipt_sha256": binding["owner_receipt_sha256"],
    "owner_manifest_sha256": binding["owner_manifest_sha256"],
    "capture_phase": binding["capture_phase"],
    "capture_status": binding["capture_status"],
    "capture_session_date": binding["capture_session_date"],
    "captured_at": binding["capture_cutoff"],
    "quote_count": len(quotes), "unique_quote_count": len(set(quote_symbols)),
    "configured_symbol_count": len(expected_symbols),
    "api_output_contract_fields_present": list(required_api_fields),
    "selector_submitted": False,
}, sort_keys=True))
'''


def run_probe(app_root: Path, mode: str) -> dict[str, object]:
    env = dict(os.environ)
    env["V35_APP_ROOT"] = str(app_root)
    completed = subprocess.run(
        [sys.executable, "-c", PROBE, str(app_root), str(CONFIG), mode],
        cwd=str(REPO), env=env, capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "OWNER_CANARY_" + mode.upper() + "_FAILED:" +
            (completed.stdout.strip() or completed.stderr.strip() or str(completed.returncode))
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OWNER_CANARY_OUTPUT_INVALID:" + mode) from exc
    if not isinstance(result, dict):
        raise RuntimeError("OWNER_CANARY_OUTPUT_NOT_OBJECT:" + mode)
    return result


def main() -> int:
    if Path.cwd().resolve() != REPO:
        raise ValueError("RUN_FROM_REPOSITORY_ROOT_REQUIRED")
    if not PLIST.is_file() or sha(PLIST.read_bytes()) != ACTIVE_PLIST_SHA:
        raise ValueError("ACTIVE_API_PLIST_PREIMAGE_CHANGED")
    if not CONFIG.is_file():
        raise ValueError("MANAGER_WORKBENCH_CONFIG_UNAVAILABLE")
    if CANDIDATE_ROOT.exists() or CANDIDATE_ROOT.is_symlink():
        raise FileExistsError("refusing to overwrite inactive API candidate root")

    sys.path.insert(0, str(REPO))
    from ops import api_release_integration as integration

    active = integration.read_active_release(PLIST)
    identity_checks = {
        "release_id": "announcement-contract-repair-20261018-r4",
        "release_manifest_sha256": ACTIVE_MANIFEST_SHA,
        "application_inventory_sha256": ACTIVE_INVENTORY_SHA,
        "api_plist_sha256": ACTIVE_PLIST_SHA,
    }
    for key, expected in identity_checks.items():
        if active.get(key) != expected:
            raise ValueError("ACTIVE_BASE_IDENTITY_CHANGED:" + key)

    active_source = Path(active["app_root"]) / RELATIVE_SOURCE
    active_raw = active_source.read_bytes()
    canonical_path = REPO / RELATIVE_SOURCE
    canonical_raw = canonical_path.read_bytes()
    if sha(active_raw) != ACTIVE_MODULE_SHA:
        raise ValueError("ACTIVE_SOURCE_PREIMAGE_CHANGED")
    if sha(canonical_raw) != CANONICAL_MODULE_SHA:
        raise ValueError("CANONICAL_SOURCE_PREIMAGE_CHANGED")
    if Path(active["app_root"]) != ACTIVE_APP:
        raise ValueError("ACTIVE_APP_ROOT_CHANGED")

    active_text = active_raw.decode("utf-8")
    canonical_text = canonical_raw.decode("utf-8")
    resolver = canonical_resolver_prelude(canonical_text)
    candidate_text = merged_api_source(active_text, resolver)
    candidate_raw = candidate_text.encode("utf-8")
    if candidate_raw == active_raw:
        raise ValueError("API_SOURCE_DELTA_EMPTY")

    local_candidate = HANDOFF / "local_only" / "api_candidate"
    source_root = local_candidate / "source"
    source_path = source_root / RELATIVE_SOURCE
    delta_receipt_path = local_candidate / "api-release-delta.json"
    patch_path = HANDOFF / "source_deltas" / "api.patch"
    report_path = HANDOFF / "API_CANDIDATE_RECEIPT.json"
    for path in (source_path, delta_receipt_path, patch_path, report_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError("refusing to overwrite candidate evidence: " + str(path))

    diff_lines = list(difflib.unified_diff(
        active_text.splitlines(), candidate_text.splitlines(),
        fromfile="active-r4/app/" + RELATIVE_SOURCE,
        tofile="friday-close-input-api-20261018-r1/app/" + RELATIVE_SOURCE,
        n=3, lineterm="",
    ))
    patch_raw = ("\n".join(diff_lines) + "\n").encode("utf-8")
    diff_sha, hunk_count = integration._diff_proof(active_raw, candidate_raw)
    if diff_sha is None or hunk_count is None:
        raise ValueError("API_SOURCE_DIFF_PROOF_UNAVAILABLE")

    delta_receipt = {
        "schema_version": integration.DELTA_SCHEMA_VERSION,
        "base": integration._base_binding(active),
        "entries": [{
            "path": RELATIVE_SOURCE,
            "before_sha256": sha(active_raw),
            "after_sha256": sha(candidate_raw),
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
        }],
    }
    delta_raw = (json.dumps(delta_receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    source_root.mkdir(parents=True, exist_ok=False)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    write_exclusive(source_path, candidate_raw)
    source_path.chmod(stat.S_IMODE(active_source.stat().st_mode))
    write_exclusive(patch_path, patch_raw)
    write_exclusive(delta_receipt_path, delta_raw)

    CANDIDATE_ROOT.mkdir(parents=False, exist_ok=False)
    integration_record = integration.build_integrated_app(
        active_api_plist_path=PLIST,
        source_root=source_root,
        candidate_root=CANDIDATE_ROOT,
        delta_receipt_path=delta_receipt_path,
        role="gateway",
        base_role="gateway",
    )
    candidate_inventory = integration.inventory_tree(CANDIDATE_ROOT / "app")
    # Preserve the active release's established manifest shape, replacing only
    # candidate identity, application inventory, and the explicit integration
    # record. Keep API-specific runtime/review metadata from the exact base.
    candidate_manifest = dict(active["manifest"])
    candidate_manifest["candidate_status"] = "READY_FOR_INDEPENDENT_REVIEW"
    candidate_manifest["activation_status"] = "NOT_ACTIVATED"
    candidate_manifest["deployment_status"] = "CANNOT_CONFIRM"
    candidate_record = dict(candidate_manifest.get("candidate") or {})
    candidate_record.update({
        "root": str(CANDIDATE_ROOT),
        "app_root": str(CANDIDATE_ROOT / "app"),
        "release_id": CANDIDATE_RELEASE_ID,
        "module_role": active["module_role"],
        "module_contract_sha256": active["module_contract_sha256"],
        "formal_release_root": str(CANDIDATE_ROOT),
    })
    candidate_manifest["candidate"] = candidate_record
    inventory_record = dict(candidate_manifest.get("application_inventory") or {})
    inventory_record.update({
        "entry_count": len(candidate_inventory),
        "aggregate_sha256": integration.inventory_digest(candidate_inventory),
        "entries": candidate_inventory,
    })
    candidate_manifest["application_inventory"] = inventory_record
    candidate_manifest["api_integration"] = integration_record
    manifest_raw = (json.dumps(candidate_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    write_exclusive(CANDIDATE_ROOT / "release-manifest.json", manifest_raw)

    baseline_probe = run_probe(ACTIVE_APP, "baseline")
    if baseline_probe.get("status") != "EXPECTED_BASELINE_FAILURE":
        raise ValueError("ACTIVE_BASELINE_FAILURE_NOT_REPRODUCED")
    candidate_probe = run_probe(CANDIDATE_ROOT / "app", "candidate")
    if candidate_probe.get("status") != "PASS":
        raise ValueError("CANDIDATE_REAL_OWNER_CANARY_FAILED")

    manifest_sha = sha(manifest_raw)
    verification = integration.verify_api_release_candidate(
        candidate_root=CANDIDATE_ROOT,
        active_api_plist_path=PLIST,
        expected_manifest_sha256=manifest_sha,
        active_pointer="base",
        role="gateway",
        base_role="gateway",
    )
    if verification.get("status") != "PASS" or verification.get("delta_paths") != [RELATIVE_SOURCE]:
        raise ValueError("API_CANDIDATE_INTEGRITY_VERIFICATION_FAILED")

    report = {
        "schema_version": "v4.us_friday_api_candidate_receipt.v1",
        "status": "CANDIDATE_READY_FOR_INDEPENDENT_REVIEW",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "target_date": "20261020",
            "us_source_session": "20261016",
            "selection_submitted": False,
            "api_activated": False,
            "plist_changed": False,
            "canonical_data_written": False,
        },
        "baseline": {
            "release_root": active["release_root"],
            "release_id": active["release_id"],
            "manifest_sha256": active["release_manifest_sha256"],
            "application_inventory_sha256": active["application_inventory_sha256"],
            "api_plist_sha256": active["api_plist_sha256"],
            "source_path": str(active_source),
            "source_sha256": sha(active_raw),
            "reproduction": baseline_probe,
        },
        "canonical_workspace_source": {
            "path": str(canonical_path),
            "sha256": sha(canonical_raw),
            "resolver_prelude_merged": True,
            "active_api_registry_and_universe_tail_preserved": True,
        },
        "delta": {
            "path": RELATIVE_SOURCE,
            "before_sha256": sha(active_raw),
            "after_sha256": sha(candidate_raw),
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
            "patch_path": str(patch_path),
            "patch_sha256": sha(patch_raw),
            "delta_receipt_path": str(delta_receipt_path),
            "delta_receipt_sha256": sha(delta_raw),
        },
        "candidate": {
            "release_root": str(CANDIDATE_ROOT),
            "release_id": CANDIDATE_RELEASE_ID,
            "manifest_sha256": manifest_sha,
            "application_inventory_sha256": verification["candidate"]["application_inventory_sha256"],
            "module_source_sha256": sha(candidate_raw),
            "independent_integrity_builder": verification,
            "real_owner_read_only_canary": candidate_probe,
        },
        "limits": [
            "Sina daily-close corroboration supports numeric equality only; it is not an official exchange-close attestation.",
            "Owner capture remains CONTROLLED_LATE_POST_CLOSE with its original captured_at and PIT limitation.",
            "This candidate has not been activated and no manager-workbench selector run or API/UI readback was performed.",
            "Independent reviewer verdict remains pending.",
        ],
        "safety": {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    report_raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    write_exclusive(report_path, report_raw)
    print(json.dumps({
        "status": report["status"],
        "baseline": baseline_probe,
        "candidate": candidate_probe,
        "active_release_id": active["release_id"],
        "candidate_release_id": CANDIDATE_RELEASE_ID,
        "candidate_manifest_sha256": manifest_sha,
        "candidate_inventory_sha256": verification["candidate"]["application_inventory_sha256"],
        "delta_path": RELATIVE_SOURCE,
        "delta_sha256": sha(candidate_raw),
        "report_path": str(report_path),
        "report_sha256": sha(report_raw),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
