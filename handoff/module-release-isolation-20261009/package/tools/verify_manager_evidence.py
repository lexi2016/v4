#!/usr/bin/env python3
"""Verify hashes and frozen claims in manager_evidence/ without changing state."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def flags_ok(value: dict[str, Any]) -> bool:
    return (
        value.get("research_only") is True
        and value.get("production_allowed") is False
        and value.get("buy_gate_updated") is False
        and value.get("orders_sent") is False
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    manager = args.root.resolve() / "manager_evidence"
    manifest_path = manager / "manifest.json"
    errors: list[str] = []
    checked = 0

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        manifest = read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read manifest: {exc}", file=sys.stderr)
        return 1

    require(manifest.get("schema_version") == "v4.module_release_isolation.manager_evidence.v1",
            "manager evidence schema mismatch")
    local_records = [
        (manifest.get("summary"), manifest.get("summary_sha256")),
        (manifest.get("current_runtime_identity"), manifest.get("current_runtime_identity_sha256")),
        (manifest.get("r3_candidate_summary"), manifest.get("r3_candidate_summary_sha256")),
        (manifest.get("source_extracts"), manifest.get("source_extracts_sha256")),
    ]
    for rel, expected in local_records:
        path = manager / str(rel)
        try:
            actual = sha256(path)
            checked += 1
            require(actual == expected, f"local SHA mismatch: {path}")
        except OSError as exc:
            errors.append(f"missing local evidence {path}: {exc}")

    resolved_evidence: dict[str, Path] = {}
    for item in manifest.get("evidence", []):
        raw_path = Path(str(item.get("path", "")))
        path = raw_path if raw_path.is_absolute() else manager / raw_path
        kind = str(item.get("kind", "unnamed"))
        expected = item.get("sha256")
        try:
            actual = sha256(path)
            checked += 1
            require(actual == expected, f"SHA mismatch for {kind}: {path}")
            resolved_evidence[kind] = path
        except OSError as exc:
            errors.append(f"missing evidence for {kind} at {path}: {exc}")

    try:
        identity = read_json(manager / str(manifest["current_runtime_identity"]))
        r3_summary = read_json(manager / str(manifest["r3_candidate_summary"]))
        r3_receipt = read_json(resolved_evidence["r3_mac_candidate_receipt"])
        policy = read_json(resolved_evidence["policy_only_review"])
        owner_identity = read_json(resolved_evidence["runtime_identity_snapshot"])
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot parse required JSON evidence: {exc}")
        identity = r3_summary = r3_receipt = policy = owner_identity = {}

    services = {row.get("label"): row for row in identity.get("services", [])}
    api = services.get("com.lexi.v35.api-only", {})
    scheduler = services.get("com.lexi.v35.scheduler", {})
    require(api.get("environment", {}).get("V35_APP_ROOT")
            != scheduler.get("environment", {}).get("V35_APP_ROOT"),
            "configured API and scheduler roots must remain distinct")
    require(api.get("manifest_pin_matches") is True and scheduler.get("manifest_pin_matches") is True,
            "captured API/scheduler release manifest pin mismatch")
    require(api.get("manager_binding", {}).get("enabled") is False,
            "captured API manager binding is no longer represented as disabled")
    require(scheduler.get("manager_binding", {}).get("enabled") is True,
            "captured scheduler manager binding is no longer represented as enabled")
    require(api.get("manager_binding", {}).get("sha256") != scheduler.get("manager_binding", {}).get("sha256"),
            "captured API and scheduler bindings unexpectedly match")

    results = r3_receipt.get("test_results", {})
    for key, count in (("r3_scoped", 66), ("daily_regression", 36), ("policy_and_verifier", 18)):
        row = results.get(key, {})
        require(row.get("status") == "PASS" and row.get("passed") == count and row.get("failed") == 0,
                f"R3 writer receipt mismatch for {key}")
    hk = results.get("original_hk_supplement", {})
    require(hk.get("status") == "FAIL_RECORDED" and hk.get("passed") == 12 and hk.get("failed") == 3,
            "preserved HK suite boundary must remain 12 passed / 3 failed")
    require(r3_receipt.get("status") == "CANDIDATE_SAVED_WRITER_TESTED_REVIEW_PENDING",
            "R3 receipt must remain writer-tested and review-pending")
    boundary = r3_receipt.get("current_review_and_integration_boundary", {})
    require(boundary.get("independent_review") == "PENDING"
            and boundary.get("shared_root_published") is False
            and boundary.get("stage_delta_applied") is False,
            "R3 review/publication/stage boundary changed in source receipt")
    require(policy.get("verdict") == "PASS_POLICY_ONLY"
            and policy.get("automatic_application") is False
            and not policy.get("broad_prefixes_added"),
            "policy evidence must remain review-only, with no broad path prefixes")
    require(r3_summary.get("runtime_and_review", {}).get("independent_review") == "PENDING"
            and r3_summary.get("runtime_and_review", {}).get("shared_release") == "NOT_RUN",
            "compact R3 summary promotes writer status beyond its receipt")
    for label, row in (("API", api), ("scheduler", scheduler)):
        env = row.get("environment", {})
        if "RESEARCH_ONLY" in env:
            require(env.get("RESEARCH_ONLY").lower() in {"1", "true"},
                    f"{label} RESEARCH_ONLY flag is not true")
        for name in ("production_allowed", "PRODUCTION_ALLOWED", "buy_gate_updated",
                     "BUY_GATE_UPDATED", "orders_sent", "ORDERS_SENT"):
            if name in env:
                require(env.get(name, "").lower() == "false", f"{label} safety flag {name} is not false")
    require(flags_ok(api.get("safety_flags", {})), "API research-only flags do not remain safe")
    require(flags_ok(scheduler.get("manager_binding", {})),
            "scheduler manager binding research-only flags do not remain safe")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: manager evidence hashes and frozen claims verified ({checked} SHA checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
