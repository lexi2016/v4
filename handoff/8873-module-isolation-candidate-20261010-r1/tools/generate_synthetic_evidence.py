#!/usr/bin/env python3
"""Reproduce same-gateway release evidence with newly created synthetic fixtures.

Only the explicitly selected test helpers and existing builder/integration
primitives are exercised. No native publisher or service controller is called.
The exported evidence contains JSON, this script and a README, never app/dist
trees, plist contents, a full environment or real owner products.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shlex
import sys
import time


SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}
EXTRA = "modules/alpha_extra.py"
ALPHA = "modules/alpha.py"
BETA = "modules/beta.py"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def check_export(value):
    """Reject full plist/environment representations in exported JSON."""
    if isinstance(value, dict):
        require(not ({"ProgramArguments", "EnvironmentVariables", "identity_from_plist"} & set(value)),
                "FULL_ENVIRONMENT_OR_PLIST_EXPORT_REJECTED")
        for item in value.values():
            check_export(item)
    elif isinstance(value, list):
        for item in value:
            check_export(item)


def write_json(path, value):
    check_export(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2)
        handle.write("\n")


def clean_path(value, *, existing):
    raw = Path(value)
    require(raw.is_absolute() and ".." not in raw.parts, "ABSOLUTE_CANONICAL_PATH_REQUIRED")
    require(not raw.is_symlink(), "PATH_SYMLINK_REJECTED")
    require(raw.parent.is_dir() and raw.parent.resolve(strict=True) == raw.parent,
            "EXISTING_CANONICAL_PARENT_REQUIRED")
    if existing:
        require(raw.is_dir() and raw.resolve(strict=True) == raw, "CODE_ROOT_DIRECTORY_REQUIRED")
    else:
        require(not raw.exists(), "FRESH_OUTPUT_DIRECTORY_REQUIRED:" + str(raw))
    return raw


def disjoint(first, second):
    return not (first.is_relative_to(second) or second.is_relative_to(first))


def install_isolation_guard():
    """Deny subprocess/network actions; fixture paths are checked separately.

    This is deliberately not a filesystem syscall sandbox. SafeRoot uses
    descriptor-relative open/mkdir operations, whose base descriptors are not
    consistently exposed by Python's audit events. Treating those paths as
    CWD-relative would misreport the actual write destination.
    """
    observed = {"blocked_attempts": [], "filesystem_scope":
                "New disjoint roots and fixture paths enforced by runner; no general syscall sandbox claimed"}
    denied = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
              "os.posix_spawnp", "socket.connect", "socket.bind", "socket.getaddrinfo"}

    def audit(event, arguments):
        if event in denied:
            observed["blocked_attempts"].append(event)
            raise RuntimeError("SYNTHETIC_ONLY_FORBIDDEN_ACTION:" + event)

    sys.addaudithook(audit)
    return observed


def load_helpers(code_root):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(code_root))
    helper_path = code_root / "tests/test_api_business_modules.py"
    require(helper_path.is_file() and not helper_path.is_symlink(), "TEST_HELPER_REQUIRED")
    spec = importlib.util.spec_from_file_location("_issue30_synthetic_helpers", helper_path)
    require(spec is not None and spec.loader is not None, "TEST_HELPER_LOAD_FAILED")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    for module in (helper, helper.integration, helper.builder):
        require(Path(module.__file__).resolve().is_relative_to(code_root), "CODE_ROOT_IMPORT_MISMATCH")
    return helper


def source_inventory(code_root):
    paths = {"tests/test_api_business_modules.py", "deployment/api_module_contracts.json"}
    paths.update(path.relative_to(code_root).as_posix() for directory in ("ops", "infrastructure")
                 for path in (code_root / directory).rglob("*.py"))
    return [{"path": relative, "sha256": digest((code_root / relative).read_bytes()),
             "size": (code_root / relative).stat().st_size} for relative in sorted(paths)]


class EvidenceRun:
    def __init__(self, helper, fixture_root, evidence_root):
        self.helper = helper
        self.integration = helper.integration
        self.fixture_root = fixture_root
        self.evidence_root = evidence_root
        self.candidates = []
        self.commits = 0
        self.stale_rejections = 0
        self.rollback_preparations = 0
        self.scenarios = []

    def inventory(self, root):
        entries = self.integration.inventory_tree(root)
        return {"entries": entries, "entry_count": len(entries),
                "aggregate_sha256": self.integration.inventory_digest(entries)}

    def snapshot(self, active):
        require(active["root"].is_relative_to(self.fixture_root), "FIXTURE_ROOT_ESCAPE")
        require(active["plist"].is_relative_to(active["root"]), "SYNTHETIC_PLIST_ESCAPE")
        identity = self.integration.read_active_release(active["plist"])
        require(Path(identity["release_root"]).is_relative_to(active["root"]), "ACTIVE_RELEASE_ESCAPE")
        payload = plistlib.loads(active["plist"].read_bytes())
        env = dict(item.split("=", 1) for item in payload["ProgramArguments"] if "=" in item)
        require(env.get("RESEARCH_ONLY") == "1", "RESEARCH_ONLY_CHANGED")
        require(all(env.get(key) == "false" for key in ("production_allowed", "buy_gate_updated", "orders_sent")),
                "FINANCIAL_SAFETY_CHANGED")
        contract = json.loads(active["contract"].read_bytes())
        require(contract["approval_id"] == "SYNTHETIC_TEST_ONLY", "NON_SYNTHETIC_OWNER_CONTRACT")
        require(all(Path(root).is_relative_to(active["root"]) for root in contract["protected_external_roots"]),
                "EXTERNAL_OWNER_ROOT_NOT_SYNTHETIC")
        return {"scope": "SYNTHETIC_ONLY", "base_identity": self.integration._base_binding(identity),
                "synthetic_plist_path": str(active["plist"]),
                "synthetic_plist_sha256": identity["api_plist_sha256"],
                "launch_bindings_sha256": identity["launch_bindings_sha256"],
                "owner_contract_sha256": digest(active["contract"].read_bytes()),
                "app": self.inventory(Path(identity["app_root"])),
                "static": self.inventory(Path(identity["app_root"]) / "apps/web/dist"),
                "state": self.inventory(active["state"]), "safety": dict(SAFETY)}

    def export_original_json(self, source, destination):
        require(source.is_relative_to(self.fixture_root), "EXPORT_SOURCE_NOT_SYNTHETIC")
        raw = source.read_bytes()
        check_export(json.loads(raw))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(raw)
        require(digest(destination.read_bytes()) == digest(raw), "EXPORTED_BYTES_CHANGED")
        return {"source_path": str(source), "evidence_path": destination.relative_to(self.evidence_root).as_posix(),
                "sha256": digest(raw), "size": len(raw), "bytes_copied_unchanged": True}

    def setup(self, name):
        active = self.helper.setup_active(self.fixture_root / name)
        stage = self.evidence_root / name / "000-base"
        snapshot = self.snapshot(active)
        write_json(stage / "active-snapshot.json", snapshot)
        provenance = [self.export_original_json(active["contract"], stage / "synthetic-owner-contract.json"),
                      self.export_original_json(active["initial_app"].parent / "release-manifest.json",
                                                stage / "base-manifest.json")]
        write_json(stage / "export-provenance.json", provenance)
        return active

    def preservation(self, before, after, targets):
        old = [row for row in before["app"]["entries"] if row["path"] not in targets]
        new = [row for row in after["app"]["entries"] if row["path"] not in targets]
        require(old == new, "NON_TARGET_APP_BYTES_OR_METADATA_CHANGED")
        require(before["static"] == after["static"], "STATIC_CHANGED")
        require(before["state"] == after["state"], "SYNTHETIC_STATE_CHANGED")
        require(before["owner_contract_sha256"] == after["owner_contract_sha256"], "OWNER_CONTRACT_CHANGED")
        require(before["launch_bindings_sha256"] == after["launch_bindings_sha256"], "LAUNCH_BINDINGS_CHANGED")
        require(before["safety"] == after["safety"] == SAFETY, "SAFETY_CHANGED")
        return {"scope": "SYNTHETIC_ONLY", "status": "PASS", "target_paths": sorted(targets),
                "non_target_app_entries_before": old, "non_target_app_entries_after": new,
                "non_target_inventory_sha256_before": self.integration.inventory_digest(old),
                "non_target_inventory_sha256_after": self.integration.inventory_digest(new),
                "static_before_sha256": before["static"]["aggregate_sha256"],
                "static_after_sha256": after["static"]["aggregate_sha256"],
                "state_before_sha256": before["state"]["aggregate_sha256"],
                "state_after_sha256": after["state"]["aggregate_sha256"],
                "non_target_app_unchanged": True, "all_static_unchanged": True,
                "synthetic_state_unchanged": True, "owner_contract_unchanged": True,
                "launch_and_safety_bindings_unchanged": True, "safety": dict(SAFETY)}

    def build(self, active, number, name, module, changes=None, prepared=None):
        stage = self.evidence_root / active["root"].name / f"{number:03d}-{name}"
        before = self.snapshot(active)
        write_json(stage / "active-before-build.json", before)
        started = utc_now()
        if prepared is None:
            candidate = self.helper.build(active, name, module, changes)
        else:
            candidate = self.helper.build_rollback(active, prepared, name=name)
        after = self.snapshot(active)
        require(before == after, "BUILDER_CHANGED_ACTIVE_OR_STATE")
        write_json(stage / "active-after-build.json", after)
        manifest_path = candidate / "release-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        receipt = json.loads((candidate / self.integration.DELTA_RECEIPT_NAME).read_bytes())
        targets = {row["path"] for row in receipt["entries"]}
        candidate_snapshot = dict(before)
        candidate_snapshot["app"] = self.inventory(candidate / "app")
        candidate_snapshot["static"] = self.inventory(candidate / "app/apps/web/dist")
        write_json(stage / "candidate-full-inventory.json", candidate_snapshot["app"])
        write_json(stage / "base-identity.json", manifest["api_integration"]["base"])
        write_json(stage / "build-preservation.json", self.preservation(before, candidate_snapshot, targets))
        write_json(stage / "build-invocation.json", {"scope": "SYNTHETIC_ONLY", "started_at": started,
            "completed_at": utc_now(), "module_id": module,
            "helper": "build_rollback" if prepared is not None else "build",
            "builder": "ops.build_release_candidate.build_module_candidate",
            "integration": "ops.api_release_integration.build_integrated_app",
            "candidate_root": str(candidate), "active_unchanged_during_build": True,
            "native_publisher_called": False, "service_actions_called": False})
        provenance = []
        for source, filename in ((manifest_path, "candidate-manifest.json"),
                (candidate / self.integration.DELTA_RECEIPT_NAME, "delta-receipt.json"),
                (active["root"] / f"{name}-build-receipt.json", "build-receipt.json"),
                (candidate / "config/api-module-cutover-plan.json", "cutover-plan.json")):
            provenance.append(self.export_original_json(source, stage / filename))
        write_json(stage / "export-provenance.json", provenance)
        built = {"active": active, "candidate": candidate, "stage": stage, "targets": targets,
                 "receipt": receipt, "build_base": before["base_identity"], "module_id": module}
        self.candidates.append(built)
        return built

    def commit(self, built):
        active, candidate, stage = built["active"], built["candidate"], built["stage"]
        before = self.snapshot(active)
        write_json(stage / "active-before-synthetic-commit.json", before)
        started = utc_now()
        proof = self.helper.synthetic_commit(active, candidate)
        after = self.snapshot(active)
        require(after["base_identity"]["release_id"] == candidate.name, "SYNTHETIC_POINTER_READBACK_FAILED")
        require(after["base_identity"]["generation"] == before["base_identity"]["generation"] + 1,
                "GENERATION_DID_NOT_INCREMENT")
        observed = {row["path"]: row for row in after["app"]["entries"]}
        for row in built["receipt"]["entries"]:
            require(observed.get(row["path"], {}).get("sha256") == row["after_sha256"],
                    "TARGET_SHA_MISMATCH:" + row["path"])
        preservation = self.preservation(before, after, built["targets"])
        write_json(stage / "active-after-synthetic-commit.json", after)
        write_json(stage / "commit-preservation.json", preservation)
        write_json(stage / "synthetic-commit-receipt.json", {"scope": "SYNTHETIC_ONLY",
            "status": "PASS", "started_at": started, "completed_at": utc_now(),
            "helper": "tests.test_api_business_modules.synthetic_commit", "verification_result": proof,
            "mutation": "Only this run's newly created synthetic LaunchAgent plist was rewritten",
            "native_publisher_called": False, "launchctl_called": False, "service_readback_performed": False,
            "mac_native_verification": "NOT_RUN", "safety": dict(SAFETY)})
        self.commits += 1
        return after

    def reject_stale(self, built):
        active, stage = built["active"], built["stage"]
        before = self.snapshot(active)
        write_json(stage / "active-before-stale-attempt.json", before)
        try:
            self.helper.synthetic_commit(active, built["candidate"])
        except ValueError as error:
            require("ACTIVE_BASE_CHANGED" in str(error), "UNEXPECTED_STALE_REJECTION:" + str(error))
            code = str(error)
        else:
            raise AssertionError("STALE_CANDIDATE_WAS_NOT_REJECTED")
        after = self.snapshot(active)
        require(before == after, "STALE_REJECTION_CHANGED_ACTIVE_OR_STATE")
        write_json(stage / "active-after-stale-attempt.json", after)
        write_json(stage / "stale-rejection-receipt.json", {"scope": "SYNTHETIC_ONLY", "status": "PASS",
            "expected_rejection": "ACTIVE_BASE_CHANGED", "actual_exception_type": "ValueError",
            "actual_error_code": code, "candidate_base": built["build_base"],
            "current_active_base": before["base_identity"], "active_plist_bytes_unchanged": True,
            "app_static_and_state_inventories_unchanged": True, "silent_rebase_performed": False,
            "native_publisher_called": False, "service_actions_called": False})
        self.stale_rejections += 1

    def prepare_rollback(self, active, built):
        stage = self.evidence_root / active["root"].name / "040-prepare-rollback-A"
        before = self.snapshot(active)
        write_json(stage / "active-before-preparation.json", before)
        prepared = self.helper.prepare_rollback(active, built["candidate"], name="reverse-A")
        after = self.snapshot(active)
        require(before == after, "ROLLBACK_PREPARATION_CHANGED_ACTIVE_OR_STATE")
        require(prepared["base"] == before["base_identity"], "ROLLBACK_NOT_BOUND_TO_CURRENT_ACTIVE")
        write_json(stage / "active-after-preparation.json", after)
        write_json(stage / "rollback-preparation-receipt.json", prepared)
        write_json(stage / "rollback-invocation.json", {"scope": "SYNTHETIC_ONLY", "status": "PASS",
            "entrypoint": "ops.api_release_integration.prepare_module_rollback",
            "whole_release_restore_performed": False, "current_active_base": before["base_identity"],
            "rollback_of": prepared["rollback_of"], "native_publisher_called": False})
        provenance = self.export_original_json(Path(prepared["delta_receipt_path"]), stage / "reverse-delta-receipt.json")
        write_json(stage / "export-provenance.json", provenance)
        self.rollback_preparations += 1
        return prepared

    def expect(self, active, mapping):
        snapshot = self.snapshot(active)
        entries = {row["path"]: row for row in snapshot["app"]["entries"]}
        for path, value in mapping.items():
            if value is None:
                require(path not in entries, "EXPECTED_PATH_ABSENT:" + path)
            else:
                require(entries.get(path, {}).get("sha256") == digest(value), "EXPECTED_BYTES:" + path)
        return snapshot

    def scenarios_all(self):
        active = self.setup("sequential-ab-latest-b-rollback-a")
        a = self.build(active, 10, "A", "alpha", {ALPHA: b"ALPHA = 1\n", EXTRA: b"EXTRA = True\n"})
        self.commit(a)
        b = self.build(active, 20, "B", "beta", {BETA: b"BETA = 1\n"})
        self.commit(b)
        latest_b = self.build(active, 30, "B-latest", "beta", {BETA: b"BETA = 2\n"})
        self.commit(latest_b)
        self.expect(active, {ALPHA: b"ALPHA = 1\n", EXTRA: b"EXTRA = True\n", BETA: b"BETA = 2\n"})
        prepared = self.prepare_rollback(active, a)
        reverse = self.build(active, 50, "rollback-A", "alpha", prepared=prepared)
        self.commit(reverse)
        final = self.expect(active, {ALPHA: b"ALPHA = 0\n", EXTRA: None, BETA: b"BETA = 2\n"})
        self.scenarios.append({"name": active["root"].name, "status": "PASS", "candidate_count": 4,
            "alpha_restored_to_G": True, "alpha_added_file_removed": True, "latest_beta_preserved": True,
            "final_base_identity": final["base_identity"]})

        active = self.setup("same-g-stale-beta-rebuilt")
        a = self.build(active, 10, "A", "alpha", {ALPHA: b"ALPHA = 10\n", EXTRA: b"EXTRA = True\n"})
        stale = self.build(active, 20, "B-stale", "beta", {BETA: b"BETA = 10\n"})
        require(a["build_base"] == stale["build_base"], "CANDIDATES_NOT_FROM_IDENTICAL_G")
        self.commit(a)
        self.reject_stale(stale)
        rebuilt = self.build(active, 30, "B-rebuilt", "beta", {BETA: b"BETA = 10\n"})
        require(rebuilt["build_base"] != stale["build_base"], "B_WAS_NOT_REBUILT_ON_LATEST_BASE")
        self.commit(rebuilt)
        final = self.expect(active, {ALPHA: b"ALPHA = 10\n", EXTRA: b"EXTRA = True\n", BETA: b"BETA = 10\n"})
        self.scenarios.append({"name": active["root"].name, "status": "PASS", "candidate_count": 3,
            "same_G_candidates": True, "stale_beta_rejected": True, "alpha_preserved_during_rejection": True,
            "beta_rebuilt_on_current_alpha": True, "final_base_identity": final["base_identity"],
            "concurrency_scope": "Same-base candidates and serialized stale commit; this scenario does not claim process-race testing"})

        active = self.setup("reverse-order-ba")
        b = self.build(active, 10, "B", "beta", {BETA: b"BETA = 20\n"})
        self.commit(b)
        a = self.build(active, 20, "A", "alpha", {ALPHA: b"ALPHA = 20\n", EXTRA: b"EXTRA = True\n"})
        self.commit(a)
        final = self.expect(active, {ALPHA: b"ALPHA = 20\n", EXTRA: b"EXTRA = True\n", BETA: b"BETA = 20\n"})
        self.scenarios.append({"name": active["root"].name, "status": "PASS", "candidate_count": 2,
            "beta_then_alpha_accumulated": True, "final_base_identity": final["base_identity"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-root", required=True, help="Exact work or delivered full-after source root")
    parser.add_argument("--fixture-root", required=True, help="New, isolated directory for synthetic app/plist fixtures")
    parser.add_argument("--evidence-root", required=True, help="New, separate directory receiving JSON evidence and runner")
    args = parser.parse_args()
    started_at, started = utc_now(), time.monotonic()
    code_root = clean_path(args.code_root, existing=True)
    fixture_root = clean_path(args.fixture_root, existing=False)
    evidence_root = clean_path(args.evidence_root, existing=False)
    require(all(disjoint(a, b) for a, b in ((code_root, fixture_root), (code_root, evidence_root),
                                           (fixture_root, evidence_root))), "ROOTS_MUST_BE_DISJOINT")
    guard = install_isolation_guard()
    fixture_root.mkdir()
    evidence_root.mkdir()
    code_before = source_inventory(code_root)
    helper = load_helpers(code_root)
    run = EvidenceRun(helper, fixture_root, evidence_root)
    run.scenarios_all()
    require(code_before == source_inventory(code_root), "CODE_CHANGED_DURING_RUN")
    require(not guard["blocked_attempts"], "FORBIDDEN_ACTION_WAS_ATTEMPTED")
    require(len(run.candidates) == 9 and run.commits == 8 and run.stale_rejections == 1
            and run.rollback_preparations == 1, "SCENARIO_COUNT_MISMATCH")
    write_json(evidence_root / "code-source-identity.json", {"code_root": str(code_root),
        "source_files": code_before, "code_unchanged_during_run": True,
        "source_inventory_sha256": digest(json.dumps(code_before, sort_keys=True, separators=(",", ":")).encode()),
        "helper": "tests/test_api_business_modules.py", "runtime": sys.version})
    runner_bytes = Path(__file__).read_bytes()
    with (evidence_root / "generate_synthetic_evidence.py").open("xb") as handle:
        handle.write(runner_bytes)
    actual_command = shlex.join(sys.orig_argv)
    readme = f"""# SYNTHETIC_ONLY release evidence

This run exercises supplied test helpers and the actual existing Python builder/integration primitives. It does not call a native publisher, launchctl, service reload, HTTP health check, or Mac API/UI. The label and port in synthetic metadata are declarations, not proof of a running service. Shared locking, exact-base verification, candidate construction, inverse-delta preparation and isolated plist mutation are exercised.

## Observed run

Started: {started_at}

Actual command (this run's paths):

```sh
{actual_command}
```

`run-summary.json` contains the outcome and exact counts. There are three independent fixture scenarios: A → B → latest B → reverse A (including deletion of A's added file); same-G A/B candidates with stale-B rejection and rebuilding B from A; and B → A.

Each candidate directory contains original manifest/delta/build/plan JSON bytes, their source-path/SHA provenance, full app inventories, static/state inventories, and non-target preservation checks. Commit receipts are explicitly synthetic helper receipts. Initial owner contracts are synthetic fixtures with approval_id SYNTHETIC_TEST_ONLY. No real owner is approved by this run.

## Artifact and portability rules

This export contains JSON evidence, this README and the runner. It contains no app/dist directory, plist file, complete environment, credentials or real owner product. Synthetic plist paths and hashes appear as evidence; plist contents remain only in the fixture directory. Static and state entries are hashes and inventory metadata of fixed synthetic bytes.

All original receipt bytes, absolute run paths and SHAs are preserved. The export is an evidence record, not a relocatable active release. Moving these JSON files does not rebind their embedded paths; never rewrite paths while retaining old hashes. Re-run the script with an explicit source root and NEW, disjoint fixture/evidence roots to generate new paths and new SHAs:

```sh
/absolute/path/to/python -B /absolute/path/to/generate_synthetic_evidence.py \\
  --code-root /absolute/path/to/work-or-full-after \\
  --fixture-root /absolute/existing/parent/new-fixtures \\
  --evidence-root /absolute/existing/parent/new-evidence
```

Use the supplied test environment with pytest available. Roots must not already exist, must have existing canonical parents and must not overlap. The runner prevents subprocess/network calls and explicitly roots all fixture/evidence paths in its two new directories. This is not a general filesystem syscall sandbox. No natural-language business/API/UI verification or Mac service continuity is claimed. Safety remains RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false.
"""
    with (evidence_root / "README.md").open("x", encoding="utf-8") as handle:
        handle.write(readme)
    expected_files = len([path for path in evidence_root.rglob("*") if path.is_file()]) + 2
    summary = {"schema_version": "issue30.synthetic_evidence_run.v1", "scope": "SYNTHETIC_ONLY",
        "status": "PASS", "started_at": started_at, "completed_at": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 6), "command": actual_command,
        "code_root": str(code_root), "fixture_root": str(fixture_root), "evidence_root": str(evidence_root),
        "scenario_count": len(run.scenarios), "candidate_count": len(run.candidates),
        "synthetic_commit_count": run.commits, "stale_rejection_count": run.stale_rejections,
        "rollback_preparation_count": run.rollback_preparations,
        "candidate_manifest_count": len(run.candidates), "exported_file_count": expected_files,
        "scenarios": run.scenarios, "code_unchanged_during_run": True,
        "native_publisher_called": False, "launchctl_called": False, "service_actions_called": False,
        "api_ui_or_mac_verification": "NOT_RUN", "all_non_target_preservation_checks_passed": True,
        "isolation_guard": guard, "runner_sha256": digest(runner_bytes), "safety": dict(SAFETY)}
    write_json(evidence_root / "run-summary.json", summary)
    index = [{"path": path.relative_to(evidence_root).as_posix(), "sha256": digest(path.read_bytes()),
              "size": path.stat().st_size} for path in sorted(evidence_root.rglob("*")) if path.is_file()]
    write_json(evidence_root / "evidence-index.json", {"scope": "SYNTHETIC_ONLY",
        "entries": index, "entry_count": len(index), "index_excludes_itself": True,
        "aggregate_sha256": digest(json.dumps(index, sort_keys=True, separators=(",", ":")).encode())})
    actual_files = [path for path in evidence_root.rglob("*") if path.is_file()]
    require(len(actual_files) == expected_files, "EVIDENCE_FILE_COUNT_MISMATCH")
    require(all(path.suffix in {".json", ".md", ".py"} for path in actual_files), "UNAPPROVED_EXPORT_TYPE")
    require(not any(path.name == "dist" for path in evidence_root.rglob("*")), "DIST_DIRECTORY_EXPORTED")
    print(json.dumps({key: summary[key] for key in ("status", "scope", "scenario_count", "candidate_count",
        "synthetic_commit_count", "stale_rejection_count", "rollback_preparation_count",
        "candidate_manifest_count", "exported_file_count", "evidence_root", "fixture_root")}, sort_keys=True))


if __name__ == "__main__":
    main()
