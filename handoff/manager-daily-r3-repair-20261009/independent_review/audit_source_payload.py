"""Read-only independent role/provenance audit of this pinned R3 source assembly.

Requires the original reviewed workspace inputs and candidate. This is review
evidence, not a host installer, business verifier, or full application test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


BASE = "b98d85c95d19780e2900dce7de9372328e67acf6"
LOCAL_BASE = "c973cbc268c686af4492a7dfa4cef8417ca8edf4"
PRODUCT = "v4/manager_research/workspace_daily_channels.py"
BINDING = {
    "apps/api/v35_api/manager_research_router.py",
    "infrastructure/scheduling/manager_announcement_supervisor.py",
    "ops/render_manager_announcement_binding.py",
    "ops/run_manager_announcement_cycle.py",
    "v4/manager_research/plan_owner_dispatch.py",
    "v4/manager_research/workspace_plan_autorun.py",
}
REUSED_API = {
    "infrastructure/_research_peripheral_store_parts/_namespace.py",
    "v3_shared_data/shared_data/hk_daily_supplement.py",
    "v4/manager_research/service.py",
    "v4/manager_research/us_mapping_research.py",
    "v4/manager_research/workspace.py",
    "v4/manager_research/workspace_history.py",
}
EXPECTED = {
    "api_current": BINDING | REUSED_API | {PRODUCT},
    "api_r2_increment": BINDING | {PRODUCT},
    "worker_current": BINDING - {"apps/api/v35_api/manager_research_router.py"},
    "hk_child": {
        "ops/macos_research_panel_daily.py",
        "ops/_macos_research_panel_daily_parts/hk_capture_gate.py",
        "ops/ensure_hk_security_master.py",
    },
    "web_cumulative": {
        "apps/web/src/api/managerWorkspace.ts",
        "apps/web/src/manager-selection/catalystObservationPanel.ts",
        "apps/web/src/manager-selection/dailyResearchRun.ts",
        "apps/web/src/manager-selection/researchAttention.ts",
    },
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() if raw is not None else None


def run(root, package):
    manifest = json.loads((package / "source_manifest.json").read_text())
    remote = root / "input/remote"
    r3_prefix = "handoff/manager-daily-failure-20261009-r3/package/"
    r3 = json.loads((remote / r3_prefix / "source_manifest.json").read_text())
    r3_rows = {(r["role"], r["source_relative_path"]): r for r in r3["files"]}
    r1 = remote / "handoff/manager-daily-automation-repair-20261008-r1"
    r2 = remote / "handoff/manager-daily-automation-repair-20261009-r2"
    tree = json.loads((root / "input/tree.json").read_text())
    assert tree["sha"] == BASE and tree["truncated"] is False
    tree_rows = {r["path"]: r for r in tree["tree"]}
    assert manifest["base_commit"] == BASE
    assert manifest["parent_shared_baseline"] == "66bb05a2e12976775ccb997191ce943bae8cc9a5"
    assert set(manifest["profiles"]) == set(EXPECTED)
    assert manifest["flags"] == {"RESEARCH_ONLY": True, "production_allowed": False,
                                  "buy_gate_updated": False, "orders_sent": False}
    assert manifest["not_full_deployable_app"] is True
    assert manifest["actual_runtime_process_identity"] == "NOT_RUN"
    assert {p.relative_to(package / "runtime").as_posix() for p in (package / "runtime").rglob("*") if p.is_file()} == {p + ".patch" for p in EXPECTED}
    r1_records = json.loads((r1 / "source_manifest.json").read_text())["files"]
    r1_by = {(r["profile"], r["path"]): r for r in r1_records}
    audited = []
    for profile, wanted in EXPECTED.items():
        rows = [r for r in manifest["files"] if r["profile"] == profile]
        assert len(rows) == len(wanted) == manifest["profiles"][profile]["source_file_count"]
        assert {r["path"] for r in rows} == wanted
        patch = manifest["profiles"][profile]
        raw_patch = (package / patch["patch_path"]).read_bytes()
        assert sha(raw_patch) == patch["patch_sha256"]
        assert {line[6:] for line in raw_patch.decode().splitlines() if line.startswith("+++ b/")} == wanted
        for row in rows:
            path, origin = row["path"], row["before_origin"]
            before = (package / row["before_path"]).read_bytes() if row["before_path"] else None
            after = (package / row["after_path"]).read_bytes()
            for side, raw in (("before", before), ("after", after)):
                assert row[side + "_sha256"] == sha(raw)
                assert row[side + "_git_blob_sha"] == blob(raw)
                assert row[side + "_bytes"] == (len(raw) if raw is not None else None)
                assert row[side + "_path"] == (f"{side}/{profile}/{path}" if raw is not None else None)
            assert before != after
            assert row["change"] == ("added" if before is None else "modified")
            assert origin["host_recheck_required"] is True
            expected_after_root = root / ("hk_child_candidate" if profile == "hk_child" else "candidate")
            assert after == (expected_after_root / path).read_bytes()
            evidence = []
            if profile == "api_r2_increment":
                assert origin["local_comparison_commit"] == LOCAL_BASE
                assert origin["not_current_api_preimage"] is True
                baseline = subprocess.check_output(["git", "-C", str(root / "candidate"), "show", f"{LOCAL_BASE}:{path}"])
                assert baseline == before
                if path != PRODUCT:
                    original = r1_by[("api", path)]
                    assert before == (r1 / original["after_path"]).read_bytes()
                    assert sha(before) == original["after_sha256"]
                    evidence.append("EXACT_FIXED_R1_AFTER_REUSED_BY_R2")
                else:
                    fixed = "handoff/manager-workbench-mac-completion-20261008/source/api_app/" + path
                    assert blob(before) == tree_rows[fixed]["sha"]
                    evidence.append("FIXED_PARENT_MAC_COMPLETION_NOT_R3_LIVE_SNAPSHOT")
            elif profile == "web_cumulative":
                original = r1_by[("web", path)]
                assert sha(before) == original["before_sha256"]
                assert origin["repository_path"] == original["before_source_origin"]
                assert origin["commit"] == original["before_source_commit"]
                assert origin["r3_live_snapshot_available"] is False
                evidence.append("PINNED_R1_WEB_BEFORE_NOT_CURRENT_MAC_READ")
            elif profile == "api_current" and path == PRODUCT:
                assert origin["basis"] == "PINNED_PARENT_MAC_COMPLETION_SOURCE_NOT_IN_32_R3_LIVE_SNAPSHOTS"
                assert origin["r3_live_snapshot_available"] is False
                assert origin["commit"] == BASE
                evidence.append("FIXED_PARENT_MAC_COMPLETION_NOT_R3_LIVE_SNAPSHOT")
            else:
                role = {"api_current": "current_api_manager", "worker_current": "current_bound_announcement_worker_20261006", "hk_child": "hk_child_conflict"}[profile]
                original = r3_rows[(role, path)]
                assert origin["commit"] == BASE
                assert origin["source_root_observed_in_package"] == original["source_root"]
                assert origin["r3_live_snapshot_available"] == original["available"]
                assert origin["repository_path"] == (r3_prefix + original["package_relative_path"] if original["available"] else None)
                assert sha(before) == original["source_sha256"]
                evidence.append("EXACT_SUPPLIED_ROLE_SNAPSHOT" if original["available"] else "SUPPLIED_ABSENCE_REQUIRES_HOST_ABSENCE_GATE")
            if origin.get("repository_path"):
                # The fixed parent product module was assembled into the
                # candidate baseline directly, not duplicated under remote/.
                # Bind that exact Git object to the independently supplied
                # remote tree blob instead of inventing a missing file.
                if path == PRODUCT and profile == "api_current":
                    original_raw = subprocess.check_output(["git", "-C", str(root / "candidate"), "show", f"{LOCAL_BASE}:{path}"])
                else:
                    original_raw = (remote / origin["repository_path"]).read_bytes()
                assert original_raw == before
                assert blob(before) == tree_rows[origin["repository_path"]]["sha"]
                evidence.append("LOCAL_FIXED_INPUT_BYTES_AND_RECORDED_GIT_BLOB_MATCH")
            if profile == "hk_child":
                original = r1_by[("hk_child", path)]
                assert after == (r1 / original["after_path"]).read_bytes()
                evidence.append("EXACT_R1_HK_AFTER_REPLAY")
            elif profile == "web_cumulative":
                after_root = r2 if path.endswith("catalystObservationPanel.ts") else r1
                assert after == (after_root / "after/web" / path).read_bytes()
                evidence.append("EXACT_FIXED_R1_R2_WEB_AFTER_NO_R3_UI_EDIT")
            elif profile == "api_current" and path in REUSED_API:
                if path == "v3_shared_data/shared_data/hk_daily_supplement.py":
                    reused = r1 / "after/hk_upstream/shared_data/hk_daily_supplement.py"
                else:
                    after_root = r2 if path == "v4/manager_research/workspace.py" else r1
                    reused = after_root / "after/api" / path
                assert after == reused.read_bytes()
                evidence.append("EXACT_FIXED_R1_R2_API_AFTER")
            audited.append({"profile": profile, "path": path, "before_sha256": sha(before), "after_sha256": sha(after), "evidence": evidence})
    assert len(manifest["files"]) == len(audited) == 32
    preserved = []
    expected_preserve = {
        "apps/api/v35_api/app.py": (["api_current", "api_r2_increment"], "issue32_protected"),
        "apps/api/v35_api/preselection_router.py": (["api_current", "api_r2_increment"], "issue32_protected"),
        "apps/api/v35_api/preselection_service.py": (["api_current", "api_r2_increment"], "issue32_protected"),
        "ops/_macos_research_panel_daily_parts/_namespace.py": (["hk_child"], "hk_child_conflict"),
    }
    assert len(manifest["preserve"]) == 4
    assert {r["path"] for r in manifest["preserve"]} == set(expected_preserve)
    for row in manifest["preserve"]:
        path = row["path"]
        profiles, role = expected_preserve[path]
        assert row["profiles"] == profiles
        original = r3_rows[(role, path)]
        raw = (remote / r3_prefix / original["package_relative_path"]).read_bytes()
        assert raw == (package / row["reference_path"]).read_bytes()
        assert sha(raw) == row["sha256"] == original["source_sha256"]
        source_root = root / ("hk_child_candidate" if role == "hk_child_conflict" else "candidate")
        assert (source_root / path).read_bytes() == raw
        assert all(path not in expected for expected in EXPECTED.values())
        preserved.append({"path": path, "sha256": sha(raw), "profiles": profiles})
    return {"status": "PASS", "scope": "SOURCE_ROLE_AND_PROVENANCE_ONLY", "manifest_sha256": sha((package / "source_manifest.json").read_bytes()),
            "profile_counts": {name: len(paths) for name, paths in EXPECTED.items()}, "records": audited, "preserved": preserved,
            "new_runtime_paths": sorted(BINDING | {PRODUCT}), "live_business_io": False, "actual_runtime_process_identity": "NOT_RUN"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.workspace, args.package), indent=2))
