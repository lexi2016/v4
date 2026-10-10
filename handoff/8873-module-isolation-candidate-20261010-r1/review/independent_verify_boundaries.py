"""Independent rechecks of four concrete findings, using only synthetic tmp trees."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
sys.path.insert(0, str(WORK))
sys.path.insert(0, str(WORK / "tests"))

from test_api_business_modules import setup_active, make_delta, build, synthetic_commit, sha, change_contract
from ops import api_release_integration as api
from ops import build_release_candidate as builder
from ops.prepare_api_only_cutover import render_module_cutover


def source_hashes():
    files = ["ops/api_business_modules.py", "ops/api_release_integration.py",
             "ops/build_release_candidate.py", "ops/prepare_api_only_cutover.py",
             "tests/test_api_business_modules.py"]
    return {name: hashlib.sha256((WORK / name).read_bytes()).hexdigest() for name in files}


def require_rejection(action, code):
    try:
        action()
    except (ValueError, FileNotFoundError) as error:
        assert code in str(error), str(error)
        return str(error)
    raise AssertionError("Unsafe output was accepted")


def call_builder(active, source, receipt, candidate, **kwargs):
    return builder.build_module_candidate(
        source_root=source, candidate_root=candidate,
        active_api_plist_path=active["plist"], release_id=candidate.name,
        role="gateway", api_integration_delta_receipt_path=receipt,
        module_id="alpha", formal_release_root=active["root"] / "unused-formal",
        **kwargs)


def main():
    started = datetime.now(timezone.utc).isoformat()
    hashes = source_hashes()
    rows = []
    for scope in ["active_app", "owner_state", "candidate_app"]:
        with tempfile.TemporaryDirectory(prefix="independent-receipt-fixed-") as td:
            root = Path(td); active = setup_active(root)
            source, receipt = make_delta(active, "A", "alpha", {"modules/alpha.py": b"ALPHA = 1\n"})
            destinations = {"active_app": active["initial_app"] / "review_unexpected.json",
                            "owner_state": active["state"] / "review_unexpected.json",
                            "candidate_app": root / "A/app/modules/beta.py"}
            before_app = api.inventory_tree(active["initial_app"])
            before_state = api.inventory_tree(active["state"])
            before_plist = active["plist"].read_bytes()
            code = "API_BUSINESS_RECEIPT_OVERLAPS_CANDIDATE" if scope == "candidate_app" else "API_BUSINESS_OUTPUT_BOUNDARY"
            reason = require_rejection(lambda: call_builder(active, source, receipt, root / "A", receipt_path=destinations[scope]), code)
            assert not (root / "A").exists()
            assert api.inventory_tree(active["initial_app"]) == before_app
            assert api.inventory_tree(active["state"]) == before_state
            assert active["plist"].read_bytes() == before_plist
            assert api.read_active_release(active["plist"])["release_id"] == "G"
            rows.append({"finding": "F1", "scope": scope, "status": "PASS", "rejection": reason})

    with tempfile.TemporaryDirectory(prefix="independent-lineage-fixed-") as td:
        root = Path(td); active = setup_active(root)
        a = build(active, "A", "alpha", {"modules/alpha.py": b"ALPHA = 1\n"}); synthetic_commit(active, a)
        b = build(active, "B", "beta", {"modules/beta.py": b"BETA = 1\n"}); synthetic_commit(active, b)
        c = build(active, "C", "beta", {"modules/beta.py": b"BETA = 2\n"}); synthetic_commit(active, c)
        before = api.inventory_tree(b / "app")
        target = b / "app/review-poisoned-history"
        def prepare(output):
            return api.prepare_module_rollback(active_api_plist_path=active["plist"], target_release_root=a,
                expected_manifest_sha256=sha((a / "release-manifest.json").read_bytes()), output_root=output)
        reason = require_rejection(lambda: prepare(target), "API_BUSINESS_OUTPUT_BOUNDARY")
        assert not target.exists()
        assert api.inventory_tree(b / "app") == before
        assert api.read_active_release(active["plist"])["release_id"] == "C"
        assert prepare(root / "safe-rollback")["status"] == "READY_FOR_REVIEW"
        rows.append({"finding": "F2", "scope": "intermediate_retained_release", "status": "PASS", "rejection": reason})

    for key in ["V4_MANAGER_SCREEN_AUTHORITY_ROOT", "V4_MANAGER_NEWS_OWNER_ROOT", "V4_DAILY_REVIEW_ROOT"]:
        with tempfile.TemporaryDirectory(prefix="independent-data-fixed-") as td:
            root = Path(td); active = setup_active(root)
            external = root / "synthetic-owner-products"; external.mkdir()
            (external / "sentinel").write_bytes(b"UNCHANGED")
            payload = plistlib.loads(active["plist"].read_bytes())
            payload["ProgramArguments"].insert(1, key + "=" + str(external))
            active["plist"].write_bytes(plistlib.dumps(payload))
            source, receipt = make_delta(active, "A", "alpha", {"modules/alpha.py": b"ALPHA = 1\n"})
            before = api.inventory_tree(external)
            reason = require_rejection(lambda: call_builder(active, source, receipt, external / "A"), "API_BUSINESS_OUTPUT_BOUNDARY")
            assert api.inventory_tree(external) == before
            rows.append({"finding": "F3", "scope": key, "status": "PASS", "rejection": reason})

    with tempfile.TemporaryDirectory(prefix="independent-plan-fixed-") as td:
        root = Path(td); active = setup_active(root)
        candidate = build(active, "A", "alpha", {"modules/alpha.py": b"ALPHA = 1\n"})
        shutil.rmtree(candidate / "config")
        (candidate / "config").symlink_to(active["state"], target_is_directory=True)
        before = api.inventory_tree(active["state"])
        reason = require_rejection(lambda: render_module_cutover(
            source_active_plist_path=active["plist"], candidate_root=candidate, release_id="A",
            manifest_path=candidate / "release-manifest.json",
            manifest_sha256=sha((candidate / "release-manifest.json").read_bytes()), role="gateway",
            source_root=root / "A-source", formal_release_root=root / "unused-formal", module_id="alpha"),
            "API_BUSINESS_CONFIG_PATH_SYMLINK_OR_ALIAS")
        assert api.inventory_tree(active["state"]) == before
        assert api.read_active_release(active["plist"])["release_id"] == "G"
        rows.append({"finding": "F4", "scope": "candidate_config_symlink", "status": "PASS", "rejection": reason})

    for declaration, code in [("shared/*.py", "API_BUSINESS_SOURCE_PATH_FORBIDDEN"),
                              ("shared", "API_BUSINESS_PATH_OWNER_OVERLAP")]:
        with tempfile.TemporaryDirectory(prefix="independent-shared-fixed-") as td:
            root = Path(td); active = setup_active(root)
            def damage(contract):
                contract["shared_paths"][0]["path"] = declaration
                contract["modules"][0]["paths"].append("shared/registry.py")
            change_contract(active, damage)
            before_app = api.inventory_tree(active["initial_app"])
            before_state = api.inventory_tree(active["state"])
            reason = require_rejection(lambda: build(active, "A", "alpha", {
                "shared/registry.py": b'ROUTES = ("alpha-new", "beta")\n'}), code)
            assert not (root / "A").exists()
            assert api.inventory_tree(active["initial_app"]) == before_app
            assert api.inventory_tree(active["state"]) == before_state
            rows.append({"finding": "F5", "scope": declaration, "status": "PASS", "rejection": reason})

    assert source_hashes() == hashes, "Reviewed source changed while verification ran"
    report = {"reviewer": "/root/independent_review", "scope": "SYNTHETIC_TMP_ONLY",
              "status": "PASS", "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
              "python": sys.version, "source_sha256": hashes, "cases": rows,
              "case_count": len(rows), "live_services_called": False}
    (ROOT / "analysis/independent_boundary_verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
