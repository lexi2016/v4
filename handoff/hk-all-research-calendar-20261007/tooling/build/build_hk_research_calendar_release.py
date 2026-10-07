#!/usr/bin/env python3
"""Build immutable API and scheduler release candidates from the live R2 packages.

This builder never writes to an active or parallel release. It verifies each
live manifest and every inventoried source byte before copying, applies only
the frozen HK calendar delta, then writes a new inactive release manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


EVIDENCE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_ALL_RESEARCH_CALENDAR_20261007"
)
SOURCE_APP = EVIDENCE_ROOT / "app"
OUTPUT_PARENT = EVIDENCE_ROOT / "release_candidates"
RELEASE_IDS = {
    "api": "hk-research-calendar-all-r1-20261007-api",
    "scheduler": "hk-research-calendar-all-r1-20261007-scheduler",
}
EXPECTED_BASES = {
    "api": {
        "root": Path(
            "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
            "hk-close-hk-calendar-r2-20261007-api"
        ),
        "manifest_sha256": "46727f049c8bd490804f0a67779321dd4722971e0a027cff3dd61a32cb75101c",
        "release_id": "hk-close-hk-calendar-r2-20261007-api",
    },
    "scheduler": {
        "root": Path(
            "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
            "hk-close-hk-calendar-r2-20261007-scheduler"
        ),
        "manifest_sha256": "2ab5e59af2a381c40fa6553f019c7aecc76af32b6718c4c29fc25f0ce84f818b",
        "release_id": "r9-hk-child-binding-standard-b1f316ac73f0",
        "actual_release_id": "hk-close-hk-calendar-r2-20261007-scheduler",
    },
}
SOURCE_SHA256 = {
    "baseline_manifest.json": "f6d42c8ee02c3c0a64f357df5b6c252f75b119978bbdf092e2754069e091e255",
    "app/contracts/runtime_workloads.json": "0c6e8a7f823bfd2d01104de399593d047e870d18b28ea60269230a1ba88a028b",
    "app/contracts/trading_calendar.py": "eca22a1e45271df45fc0a3b7cec28cec4e448d1af97b80371cc5c3c1953ec0f1",
    "app/contracts/v35_runtime_graph_topology.json": "bdaa8dcc598839affbf25d10af8d77293ac45949f11c1d4accae62551bc81458",
    "app/domains/runtime_policy.py": "0575df80b82b7940505fd4509a09e6ac6588245cc1141143b11ac42b4b84a6d2",
    "app/ops/daily_materialize.py": "d5b8f1f661e88f369f3df33f773fcdac4a79de033845a43639ef098231ad96e6",
    "app/tests/test_hk_research_calendar_all.py": "ffae895e810c2f3e9b2b3d7b251d29f2a16b367a4513a73d389ab33a4fe2aefa",
}
POLICY_WORKLOADS = {
    "research_panel_daily_hk": "HK_SECURITIES_TRADE_DAY",
    "research_panel_runtime_evidence": "A_OR_HK_SECURITIES_TRADE_DAY",
    "review_core_pool_pipeline": "A_OR_HK_SECURITIES_TRADE_DAY",
    "preselection_pools": "A_OR_HK_SECURITIES_TRADE_DAY",
    "daily_materialize": "A_OR_HK_SECURITIES_TRADE_DAY",
    "hk_auction_0920": "HK_SECURITIES_TRADE_DAY",
    "hk_connect_close_review": "HK_SECURITIES_TRADE_DAY",
    "stage_workbench": "A_OR_HK_SECURITIES_TRADE_DAY",
    "fupan_review_start": "HK_SECURITIES_TRADE_DAY",
}
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(data)


def _safe_relative(value: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"unsafe inventory path: {value}")
    return Path(*posix.parts)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories.sort()
        filenames.sort()
        retained: list[str] = []
        for name in directories:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                rows.append({
                    "kind": "symlink",
                    "path": relative,
                    "target": os.readlink(path),
                    "target_exists": path.exists(),
                })
            else:
                retained.append(name)
        directories[:] = retained
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                rows.append({
                    "kind": "symlink",
                    "path": relative,
                    "target": os.readlink(path),
                    "target_exists": path.exists(),
                })
            elif stat.S_ISREG(metadata.st_mode):
                rows.append({
                    "kind": "file",
                    "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                    "path": relative,
                    "sha256": sha256_file(path),
                    "size": metadata.st_size,
                })
            else:
                raise ValueError(f"unsupported release entry type: {path}")
    return sorted(rows, key=lambda row: row["path"])


def _verify_inventory(root: Path, entries: list[dict[str, Any]]) -> None:
    observed = _inventory(root)
    if observed != entries:
        expected_by_path = {row["path"]: row for row in entries}
        observed_by_path = {row["path"]: row for row in observed}
        changed = sorted(
            path for path in set(expected_by_path) | set(observed_by_path)
            if expected_by_path.get(path) != observed_by_path.get(path)
        )
        raise ValueError(f"application inventory drift: {changed[:12]}")


def _copy_inventory(source_root: Path, destination_root: Path, entries: list[dict[str, Any]]) -> None:
    destination_root.mkdir(parents=True, exist_ok=False)
    for row in entries:
        relative = _safe_relative(row["path"])
        source = source_root / relative
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if row["kind"] == "symlink":
            if os.readlink(source) != row["target"] or source.exists() != row["target_exists"]:
                raise ValueError(f"symlink drift: {source}")
            destination.symlink_to(row["target"])
        elif row["kind"] == "file":
            shutil.copy2(source, destination)
            os.chmod(destination, int(row["mode"], 8))
        else:
            raise ValueError(f"unsupported manifest kind: {row.get('kind')}")


def _workload_objects(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path)
    rows = payload.get("workloads")
    if not isinstance(rows, list):
        raise ValueError(f"workloads must be a list: {path}")
    result = {row.get("workload_id"): row for row in rows if isinstance(row, dict)}
    if len(result) != len(rows):
        raise ValueError(f"invalid or duplicate workload id: {path}")
    return result


def _patch_workload_text(path: Path, policy_source: Path) -> dict[str, Any]:
    before_sha256 = sha256_file(path)
    source = _workload_objects(policy_source)
    expected = {key: source[key]["run_policy"] for key in POLICY_WORKLOADS}
    if expected != POLICY_WORKLOADS:
        raise ValueError("frozen candidate workload policy map changed")
    actual = _workload_objects(path)
    if not set(POLICY_WORKLOADS).issubset(actual):
        raise ValueError("live catalog is missing a targeted workload")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_workloads = False
    block_start: int | None = None
    changed: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith('  "workloads": ['):
            in_workloads = True
        elif in_workloads and line.startswith("    {"):
            block_start = index
        elif in_workloads and block_start is not None and line.startswith("    }"):
            block = lines[block_start : index + 1]
            parsed = json.loads("".join(block).rstrip().rstrip(","))
            workload_id = parsed.get("workload_id")
            if workload_id in POLICY_WORKLOADS:
                policy = POLICY_WORKLOADS[workload_id]
                for block_index in range(block_start, index + 1):
                    match = re.match(r'^(\s*"run_policy"\s*:\s*")[^"]*("\s*,?\s*)$', lines[block_index])
                    if match:
                        lines[block_index] = f'{match.group(1)}{policy}{match.group(2)}'
                        changed.add(workload_id)
                        break
                else:
                    raise ValueError(f"run_policy line missing for {workload_id}")
                if workload_id == "hk_connect_close_review":
                    slots_started = False
                    slot_lines = 0
                    prior_slots = actual[workload_id].get("slots")
                    for block_index in range(block_start, index + 1):
                        if re.match(r"^\s*\"slots\"\s*:\s*\[", lines[block_index]):
                            slots_started = True
                            continue
                        if slots_started and "]" in lines[block_index]:
                            break
                        if slots_started and '"1608"' in lines[block_index]:
                            lines[block_index] = lines[block_index].replace('"1608"', '"1610"')
                            slot_lines += 1
                    if not (
                        (prior_slots == ["1608"] and slot_lines == 1)
                        or (prior_slots == ["1610"] and slot_lines == 0)
                    ):
                        raise ValueError("close-review slot preimage is not exactly [1608]")
            block_start = None
        index += 1

    if changed != set(POLICY_WORKLOADS):
        raise ValueError(f"incomplete workload overlay: {sorted(changed)}")
    path.write_text("".join(lines), encoding="utf-8")
    patched = _workload_objects(path)
    for workload_id, policy in POLICY_WORKLOADS.items():
        if patched[workload_id]["run_policy"] != policy:
            raise ValueError(f"workload policy was not applied: {workload_id}")
    if patched["hk_connect_close_review"]["slots"] != ["1610"]:
        raise ValueError("close-review slot was not changed to 1610")
    if patched["stage_workbench"]["enabled"] is not False:
        raise ValueError("stage_workbench must remain disabled")
    return {
        "before_sha256": before_sha256,
        "after_sha256": sha256_file(path),
        "updated_workload_ids": sorted(changed),
        "close_review_slots": ["1610"],
    }


def _insert_enum(text: str, *, line: str, insert_after: str) -> str:
    if line in text:
        return text
    if text.count(insert_after) != 1:
        raise ValueError(f"enum insertion anchor must be unique: {insert_after.strip()}")
    return text.replace(insert_after, insert_after + line, 1)


def _patch_calendar_contract(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    before = text
    text = _insert_enum(
        text,
        line='    HK_SECURITIES_TRADE_DAY = "HK_SECURITIES_TRADE_DAY"\n',
        insert_after='    A_SHARE_TRADE_DAY = "A_SHARE_TRADE_DAY"\n',
    )
    text = _insert_enum(
        text,
        line='    A_OR_HK_SECURITIES_TRADE_DAY = "A_OR_HK_SECURITIES_TRADE_DAY"\n',
        insert_after='    A_OR_HK_CONNECT_TRADE_DAY = "A_OR_HK_CONNECT_TRADE_DAY"\n',
    )
    if text == before:
        raise ValueError(f"calendar contract overlay made no change: {path}")
    path.write_text(text, encoding="utf-8")
    return {"before_sha256": sha256_bytes(before.encode()), "after_sha256": sha256_file(path)}


def _patch_runtime_policy(path: Path, candidate_path: Path) -> dict[str, Any]:
    candidate = candidate_path.read_text(encoding="utf-8")
    start = candidate.index("def _requested_markets(")
    end = candidate.index("\ndef _session_eligible(", start)
    candidate_function = candidate[start:end]
    text = path.read_text(encoding="utf-8")
    old = text
    function_start = text.index("def _requested_markets(")
    function_end = text.index("\ndef _session_eligible(", function_start)
    text = text[:function_start] + candidate_function + text[function_end:]

    # The selected-market contract must expose both the HK cash-session and
    # southbound Connect calendars without changing old Connect routing.
    anchor = '        "a_share": calendar.markets["a_share"],\n'
    insertion = anchor + '        "hk_securities": calendar.markets["hk_securities"],\n'
    if insertion not in text:
        if text.count(anchor) != 1:
            raise ValueError(f"runtime market-contract anchor must be unique: {path}")
        text = text.replace(anchor, insertion, 1)
    if "calendar.markets[\"hk_securities\"]" not in text:
        raise ValueError(f"runtime policy lacks HK securities market contract: {path}")
    if text == old:
        raise ValueError(f"runtime policy overlay made no change: {path}")
    path.write_text(text, encoding="utf-8")
    return {"before_sha256": sha256_bytes(old.encode()), "after_sha256": sha256_file(path)}


def _patch_runtime_graph_service(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    old = text
    allowed = '    if market not in {"a_share", "hk_connect"}:\n'
    expanded = '    if market not in {"a_share", "hk_connect", "hk_securities"}:\n'
    if expanded not in text:
        if text.count(allowed) != 1:
            raise ValueError(f"next-market allowlist anchor must be unique: {path}")
        text = text.replace(allowed, expanded, 1)
    connect = '        "hk_connect_trade_day": (RunPolicy.HK_CONNECT_TRADE_DAY, MarketScope.HK_CONNECT),\n'
    security = connect + '        "hk_securities_trade_day": (RunPolicy.HK_SECURITIES_TRADE_DAY, MarketScope.HK_CONNECT),\n'
    if security not in text:
        if text.count(connect) != 1:
            raise ValueError(f"HK policy map anchor must be unique: {path}")
        text = text.replace(connect, security, 1)
    cross_connect = '            RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,\n            MarketScope.CROSS_MARKET,\n        ),\n'
    cross_security = cross_connect + '        "a_or_hk_securities_trade_day": (\n            RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,\n            MarketScope.CROSS_MARKET,\n        ),\n'
    if cross_security not in text:
        if text.count(cross_connect) != 1:
            raise ValueError(f"cross-market policy map anchor must be unique: {path}")
        text = text.replace(cross_connect, cross_security, 1)
    if text == old:
        raise ValueError(f"runtime graph service overlay made no change: {path}")
    path.write_text(text, encoding="utf-8")
    return {"before_sha256": sha256_bytes(old.encode()), "after_sha256": sha256_file(path)}


def _patch_daily_materialize(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    old = text
    enum_anchor = "RunPolicy.A_OR_HK_CONNECT_TRADE_DAY"
    receipt_anchor = '"A_OR_HK_CONNECT_TRADE_DAY"'
    if text.count(enum_anchor) != 1 or text.count(receipt_anchor) != 1:
        raise ValueError("daily_materialize policy anchors are not unique")
    if "--stage-selection-root" not in text:
        raise ValueError("active scheduler daily_materialize lost stage-selection-root")
    text = text.replace(enum_anchor, "RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY", 1)
    text = text.replace(receipt_anchor, '"A_OR_HK_SECURITIES_TRADE_DAY"', 1)
    path.write_text(text, encoding="utf-8")
    return {"before_sha256": sha256_bytes(old.encode()), "after_sha256": sha256_file(path)}


def _patch_topology(path: Path, source_path: Path) -> dict[str, Any]:
    before = path.read_bytes()
    candidate_bytes = source_path.read_bytes()
    current = _load_json(path)
    candidate = _load_json(source_path)
    if current.get("version") != candidate.get("version"):
        raise ValueError("active and frozen topology versions differ")
    path.write_bytes(candidate_bytes)
    return {"before_sha256": sha256_bytes(before), "after_sha256": sha256_file(path)}


def _update_manifest(root: Path, app_root: Path, *, service: str, base_manifest: dict[str, Any], base_sha: str) -> dict[str, Any]:
    manifest = json.loads(json.dumps(base_manifest))
    release_id = RELEASE_IDS[service]
    manifest["candidate_status"] = "READY_FOR_INDEPENDENT_REVIEW"
    manifest["deployment_status"] = "NOT_DEPLOYED"
    manifest["activation_status"] = "NOT_ACTIVATED"
    if "generated_at" in manifest:
        manifest["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if "generated_at_utc" in manifest:
        manifest["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    candidate = manifest.setdefault("candidate", {})
    candidate["app_root"] = str(app_root)
    candidate["root"] = str(root)
    candidate["release_id"] = release_id
    candidate["formal_release_root"] = str(EXPECTED_BASES[service]["root"].parent)
    candidate["data_copy_performed"] = False
    candidate["activation_status"] = "NOT_ACTIVATED"
    if service == "scheduler":
        manifest["release_id"] = release_id
        candidate["target_root"] = str(root)
        candidate["target_write_performed"] = False
    # Record that the scheduler's old R9 candidate identity was carried by the
    # already active R2 package, then replaced only in this new inactive copy.
    manifest.setdefault("source", {})["hk_research_calendar_release_base"] = {
        "active_release_id": EXPECTED_BASES[service].get("actual_release_id", EXPECTED_BASES[service]["release_id"]),
        "active_manifest_sha256": base_sha,
        "active_manifest_candidate_release_id": EXPECTED_BASES[service]["release_id"],
        "candidate_release_id": release_id,
        "data_copy_performed": False,
    }
    verification = manifest.setdefault("verification", {})
    verification["hk_all_research_calendar_release_prep"] = {
        "status": "BUILT_PENDING_INDEPENDENT_REVIEW",
        "base_release_id": EXPECTED_BASES[service].get("actual_release_id", EXPECTED_BASES[service]["release_id"]),
        "base_manifest_sha256": base_sha,
        "changed_application_paths": [],
        "service_action_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    entries = _inventory(app_root)
    manifest["application_inventory"] = {
        "aggregate_sha256": canonical_sha256(entries),
        "entries": entries,
        "entry_count": len(entries),
    }
    if service == "api":
        verification["hk_all_research_calendar_release_prep"]["changed_application_paths"] = [
            "contracts/runtime_workloads.json",
            "contracts/trading_calendar.py",
            "contracts/v35_runtime_graph_topology.json",
            "domains/runtime_policy.py",
            "infrastructure/runtime_graph/service.py",
        ]
    else:
        verification["hk_all_research_calendar_release_prep"]["changed_application_paths"] = [
            "contracts/runtime_workloads.json",
            "contracts/trading_calendar.py",
            "contracts/v35_runtime_graph_topology.json",
            "domains/runtime_policy.py",
            "infrastructure/runtime_graph/service.py",
            "ops/daily_materialize.py",
        ]
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        manifest[key] = False
    if "research_only" in manifest:
        manifest["research_only"] = True
    if isinstance(manifest.get("safety"), dict):
        manifest["safety"].update({
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    return manifest


def _build_service(service: str, temporary_root: Path) -> dict[str, Any]:
    base = EXPECTED_BASES[service]
    base_root = base["root"]
    manifest_path = base_root / "release-manifest.json"
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = sha256_bytes(manifest_raw)
    if manifest_sha != base["manifest_sha256"]:
        raise ValueError(f"{service} active manifest SHA drifted")
    base_manifest = json.loads(manifest_raw)
    if base_manifest.get("candidate", {}).get("app_root") != str(base_root / "app"):
        raise ValueError(f"{service} active manifest app root mismatch")
    actual_id = base_manifest.get("candidate", {}).get("release_id")
    if actual_id != base["release_id"]:
        raise ValueError(f"{service} active manifest internal release identity drifted")
    if service == "scheduler" and base_manifest.get("candidate", {}).get("target_root") != str(base_root):
        raise ValueError("scheduler active candidate target root mismatch")
    entries = base_manifest.get("application_inventory", {}).get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{service} active manifest inventory is missing")
    base_app = base_root / "app"
    _verify_inventory(base_app, entries)

    output_root = temporary_root / RELEASE_IDS[service]
    app_root = output_root / "app"
    _copy_inventory(base_app, app_root, entries)
    _verify_inventory(app_root, entries)

    policy_result = _patch_workload_text(
        app_root / "contracts/runtime_workloads.json",
        SOURCE_APP / "contracts/runtime_workloads.json",
    )
    topology_result = _patch_topology(
        app_root / "contracts/v35_runtime_graph_topology.json",
        SOURCE_APP / "contracts/v35_runtime_graph_topology.json",
    )
    calendar_result = _patch_calendar_contract(app_root / "contracts/trading_calendar.py")
    runtime_policy_result = _patch_runtime_policy(
        app_root / "domains/runtime_policy.py",
        SOURCE_APP / "domains/runtime_policy.py",
    )
    service_result = _patch_runtime_graph_service(app_root / "infrastructure/runtime_graph/service.py")
    daily_result = None
    if service == "scheduler":
        daily_result = _patch_daily_materialize(app_root / "ops/daily_materialize.py")

    manifest = _update_manifest(
        output_root,
        app_root,
        service=service,
        base_manifest=base_manifest,
        base_sha=manifest_sha,
    )
    manifest_path_out = output_root / "release-manifest.json"
    manifest_path_out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "service": service,
        "base_root": str(base_root),
        "base_release_manifest_sha256": manifest_sha,
        "base_app_inventory_sha256": base_manifest["application_inventory"]["aggregate_sha256"],
        "candidate_root": str(output_root),
        "candidate_app_root": str(app_root),
        "candidate_release_id": RELEASE_IDS[service],
        "candidate_manifest_sha256": sha256_file(manifest_path_out),
        "candidate_app_inventory_sha256": manifest["application_inventory"]["aggregate_sha256"],
        "candidate_app_inventory_entry_count": manifest["application_inventory"]["entry_count"],
        "delta": {
            "runtime_workloads": policy_result,
            "topology": topology_result,
            "trading_calendar": calendar_result,
            "runtime_policy": runtime_policy_result,
            "runtime_graph_service": service_result,
            "daily_materialize": daily_result,
        },
        "safety": dict(SAFETY),
        "activation_status": "NOT_ACTIVATED",
        "service_action_performed": False,
    }


def main() -> int:
    for relative, expected in SOURCE_SHA256.items():
        observed = sha256_file(EVIDENCE_ROOT / relative)
        if observed != expected:
            raise SystemExit(f"candidate source SHA drift: {relative}: {observed}")
    OUTPUT_PARENT.mkdir(parents=True, exist_ok=True)
    final_root = OUTPUT_PARENT / "hk-research-calendar-all-r1-20261007"
    if final_root.exists():
        raise SystemExit(f"immutable release candidate already exists: {final_root}")
    receipt_dir = EVIDENCE_ROOT / "receipts" / "hk-research-calendar-all-r1-20261007"
    receipt_path = receipt_dir / "release_build_receipt.json"
    if receipt_path.exists():
        raise SystemExit(f"refusing to overwrite build receipt: {receipt_path}")
    temporary_root = Path(tempfile.mkdtemp(prefix=".hk-research-calendar-all-r1-", dir=OUTPUT_PARENT))
    try:
        results = [_build_service(service, temporary_root) for service in ("api", "scheduler")]
        final_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary_root, final_root)
        for result in results:
            old_root = Path(result["candidate_root"])
            new_root = final_root / old_root.name
            result["candidate_root"] = str(new_root)
            result["candidate_app_root"] = str(new_root / "app")
            manifest_path = new_root / "release-manifest.json"
            manifest = _load_json(manifest_path)
            candidate = manifest["candidate"]
            candidate["root"] = str(new_root)
            candidate["app_root"] = str(new_root / "app")
            if result["service"] == "scheduler":
                candidate["target_root"] = str(new_root)
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result["candidate_manifest_sha256"] = sha256_file(manifest_path)
        receipt = {
            "schema_version": "v4.hk_research_calendar_release_build.v1",
            "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "BUILT_PENDING_INDEPENDENT_REVIEW",
            "candidate_root": str(final_root),
            "candidate_source_baseline_manifest_sha256": SOURCE_SHA256["baseline_manifest.json"],
            "services": results,
            "deployment_performed": False,
            "service_action_performed": False,
            "research_only": True,
            **SAFETY,
        }
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"receipt_path": str(receipt_path), **receipt}, ensure_ascii=False, indent=2, sort_keys=True))
    except BaseException:
        # Only the private temporary tree created by this invocation is eligible
        # for cleanup; immutable published candidates are never overwritten.
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
