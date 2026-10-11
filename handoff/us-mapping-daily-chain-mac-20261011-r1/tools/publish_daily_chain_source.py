#!/usr/bin/env python3
"""Prepare and, after independent review, switch the US daily-chain API release.

The default command is read-only with respect to live state and writes only a
fresh operation bundle below this task's ``publication-r2`` directory.  The
explicit ``execute`` command is a separately reviewed, CAS-guarded transaction
for the single API LaunchAgent; it never edits the scheduler or research
binding and automatically attempts a same-batch rollback only while its own
candidate plist still owns the active pointer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import sys
import types
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


E = Path(__file__).resolve().parents[1]
TASK = "V4_US_MAPPING_DAILY_CHAIN_MAC_20261011_R1"
ADAPTER_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/"
    "V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1/tools/deployment/"
    "fused_publication_adapter.py"
)
ADAPTER_SHA256 = "30685f5cdf66af3f620f1b494673f1bacc140d0b8f10df67358a90bee929d156"
STAGE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/"
    "V4_STAGE_RESEARCH_R4_MAC_20261009/local_fix/r4_mac_fix_20261010_r5"
)
STAGE_API_PATH = STAGE_ROOT / "tools/stage_api_release.py"
STAGE_API_SHA256 = "f9aee4ff7770174d6671df7cdf9e5815fcf184c41788bb13d3c6e76b111b1f02"
PUBLISHER_HELPER_PATH = STAGE_ROOT / "test_support/publication/api_only_cutover_issue32_r4.py"
PUBLISHER_HELPER_SHA256 = "864a07b9bdf915a14b877eac89ddc931bb0f4976b70599c242671ff177e9cf25"
EXPECTED_CUTOVER_SHA256 = "4747df35c3d7922bd1122256565e1136d5740d942ebb03d925ef870d056df22e"
ACTIVE_SUMMARY_PATH = E / "active_rebase_2_summary.json"
ACTIVE_SUMMARY_SHA256 = "e5dd7a51dafbda13116768e1fdee42c4aa02f045317e41376c3c38f4d040aa9e"
ACTIVE_API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
ACTIVE_SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
EXPECTED_API_PLIST_SHA256 = "b2d8b1b80d0ca843a1d19f70d05281edd51862af4badb6f60fe367873d28c821"
EXPECTED_SCHEDULER_SHA256 = "fbce935c11b5b207739f6f12845209f4c6da07b68fbd034325169100ce4826c7"
EXPECTED_ACTIVE_RELEASE_ID = "hk-0920-auto-ui-20261011-r2"
EXPECTED_ACTIVE_MANIFEST_SHA256 = "89bccfee1357886fe2b4b3417611414b59429618e950eb6389764e925031d1db"
EXPECTED_ACTIVE_INVENTORY_SHA256 = "92b32c193e177078f30e81fbf1aacc5fea67cb7eee5c5770368368e23f30fc42"
CANDIDATE_RELEASE_ROOT = E / "integrated_release/manager-us-mapping-daily-chain-20261011-r1"
CANDIDATE_APP_ROOT = CANDIDATE_RELEASE_ROOT / "app"
CANDIDATE_MANIFEST_PATH = CANDIDATE_RELEASE_ROOT / "release-manifest.json"
CANDIDATE_MANIFEST_SHA256 = "3b548f81684bd48e19b9cad8ac824f036163699f8cf53dc3234bc184df9014ad"
CANDIDATE_DELTA_PATH = CANDIDATE_RELEASE_ROOT / "publication-delta-receipt.json"
CANDIDATE_DELTA_SHA256 = "6c35e10f1379f6bf444063e39186a9e0c4f16ff4ba80cd20c7cbeb0bf5bbb28b"
CANDIDATE_RELEASE_ID = "manager-us-mapping-daily-chain-20261011-r1"
CANDIDATE_INVENTORY_SHA256 = "a31930985518157c6a148d4460526b2c057c89134b2089983323bca42ae18eed"
SOURCE_DELTA_PATH = E / "receipts/source_delta_r2.json"
SOURCE_DELTA_SHA256 = "0c80ed4a779dd8023e7705bdea7f1b24feac0264bb6dfaa89bd2a3695dde0a76"
SOURCE_REVIEW_PATH = E / "reviewer/source_r2_review.json"
SOURCE_REVIEW_SHA256 = "9179d9e7c15a381d3afa3314eb1c410359fd3e5b092f784a61dd3f8bef3b40ca"
WRITER_IDENTITY = "/root/us_daily_chain_writer"
REVIEW_SCHEMA = "v4.us_daily_chain.publication_tool_independent_review.r2"
CONFIRM_EXECUTE = "SWITCH_API_ONLY_TO_US_DAILY_CHAIN_20261011_R1"
HISTORY_PAIRS = (("20260924", "STAGE_0930_0935"), ("20261009", "STAGE_0930_0935"))
EXPECTED_EXISTING_STAGE_ERROR = {
    "detail": "approved research read binding is unavailable or invalid",
}
REQUIRED_CHANGED_ENV_KEYS = {
    "V35_APP_ROOT",
    "V35_RELEASE_ID",
    "PYTHONPATH",
    "V35_RELEASE_MANIFEST_PATH",
    "V35_RELEASE_MANIFEST_SHA256",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON_DUPLICATE_KEY:" + key)
        result[key] = value
    return result


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError("EXACT_JSON_FILE_REQUIRED:" + str(path))
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=_unique_pairs,
                       parse_constant=lambda item: (_ for _ in ()).throw(
                           ValueError("JSON_NONFINITE:" + item)))
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED:" + str(path))
    return value, raw


def _read_exact(path: Path, expected_sha: str, label: str) -> bytes:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(label + "_NOT_EXACT_FILE")
    raw = path.read_bytes()
    if _sha(raw) != expected_sha:
        raise ValueError(label + "_SHA_MISMATCH")
    return raw


def _load_pinned_module(path: Path, expected_sha: str, name: str) -> types.ModuleType:
    raw = _read_exact(path, expected_sha, name.upper())
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _runtime() -> tuple[Any, Any, Any, Any, Any]:
    _read_exact(PUBLISHER_HELPER_PATH, PUBLISHER_HELPER_SHA256,
                "PINNED_API_RELEASE_TRANSITION_HELPER")
    adapter = _load_pinned_module(ADAPTER_PATH, ADAPTER_SHA256,
                                  "us_daily_chain_fused_publication_adapter")
    wrapper, publisher, guard = adapter._load_runtime()
    if (Path(publisher.__file__).resolve() != PUBLISHER_HELPER_PATH
            or _sha(Path(publisher.__file__).read_bytes()) != PUBLISHER_HELPER_SHA256):
        raise ValueError("PINNED_API_RELEASE_TRANSITION_HELPER_IDENTITY_MISMATCH")
    active_helper_path = Path(guard._base_binding(
        guard.read_active_release(publisher.ACTIVE_API_PLIST))["app_root"]
    ) / "ops/prepare_api_only_cutover.py"
    candidate_helper_path = CANDIDATE_APP_ROOT / "ops/prepare_api_only_cutover.py"
    helper = _load_pinned_module(active_helper_path, EXPECTED_CUTOVER_SHA256,
                                 "us_daily_chain_api_cutover_helper")
    _read_exact(candidate_helper_path, EXPECTED_CUTOVER_SHA256,
                "CANDIDATE_API_CUTOVER_HELPER")
    stage_api = _load_pinned_module(STAGE_API_PATH, STAGE_API_SHA256,
                                    "us_daily_chain_stage_history_reader")
    return adapter, wrapper, publisher, guard, (helper, stage_api)


def _expected_active_summary() -> dict[str, Any]:
    summary, raw = _read_json(ACTIVE_SUMMARY_PATH)
    if _sha(raw) != ACTIVE_SUMMARY_SHA256:
        raise ValueError("ACTIVE_REBASE_SUMMARY_SHA_MISMATCH")
    return summary


def _validate_source_review() -> dict[str, Any]:
    review, raw = _read_json(SOURCE_REVIEW_PATH)
    if _sha(raw) != SOURCE_REVIEW_SHA256:
        raise ValueError("SOURCE_R2_REVIEW_SHA_MISMATCH")
    verdict = review.get("verdict", {})
    if (review.get("schema_version") != "v4.us_daily_chain.independent_source_review.r2"
            or review.get("reviewer_identity") != "/root/us_daily_chain_review"
            or review.get("reviewer_independent_from") != WRITER_IDENTITY
            or verdict.get("reviewed") != "PASS"
            or verdict.get("frozen_pass_scope") != "PASS"
            or not str(verdict.get("behavior_verified", "")).startswith("PASS_")
            or review.get("scope", {}).get("scope_matches_frozen_allowlist") is not True
            or review.get("findings") != []):
        raise ValueError("SOURCE_R2_REVIEW_NOT_PASS")
    delta, delta_raw = _read_json(SOURCE_DELTA_PATH)
    if _sha(delta_raw) != SOURCE_DELTA_SHA256:
        raise ValueError("SOURCE_R2_DELTA_SHA_MISMATCH")
    return {"review": review, "delta": delta}


def _assert_identity(observed: Mapping[str, Any], expected: Mapping[str, str],
                     label: str) -> None:
    if observed.get("state") != "LOADED" or not isinstance(observed.get("identity"), dict):
        raise ValueError(label + "_RUNTIME_IDENTITY_UNVERIFIED")
    identity = observed["identity"]
    for key, value in expected.items():
        if identity.get(key) != value:
            raise ValueError(label + "_RUNTIME_IDENTITY_MISMATCH:" + key)


def _health_readiness(publisher: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for endpoint in ("/healthz", "/readyz"):
        status, raw = publisher._http_get(endpoint)
        if status != 200:
            raise ValueError("API_HEALTH_HTTP_STATUS:" + endpoint + ":" + str(status))
        try:
            body = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("API_HEALTH_JSON_INVALID:" + endpoint) from exc
        if not isinstance(body, dict):
            raise ValueError("API_HEALTH_OBJECT_REQUIRED:" + endpoint)
        api_status = body.get("status")
        if api_status is not None and str(api_status).lower() not in {"ok", "ready"}:
            raise ValueError("API_HEALTH_STATUS_NOT_READY:" + endpoint)
        if body.get("ready") is False or body.get("is_ready") is False:
            raise ValueError("API_READINESS_FALSE:" + endpoint)
        record: dict[str, Any] = {"http_status": status}
        if api_status is not None:
            record["status"] = api_status
        for key in ("ready", "is_ready", "production_allowed", "buy_gate_updated", "orders_sent"):
            if key in body:
                record[key] = body[key]
        if endpoint == "/readyz":
            for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
                if body.get(key) is not False:
                    raise ValueError("API_READINESS_SAFETY_FLAG_NOT_FALSE:" + key)
        result[endpoint] = record
    return result


def _history(stage_api: Any, publisher: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for day, stage in HISTORY_PAIRS:
        query = "/api/v3/workbench/stage?" + urllib.parse.urlencode(
            {"date": day, "stage": stage, "limit": 50}
        )
        request = urllib.request.Request(
            publisher.BASE_URL + query,
            headers={"Accept": "*/*", "Accept-Encoding": "identity"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status, raw = response.status, response.read(8 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read(8 * 1024 * 1024)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ValueError("STAGE_HTTP_TRANSPORT_FAILED:" + day + ":" + type(exc).__name__) from exc

        if status == 200:
            payload = stage_api._object(raw, "STAGE_HTTP")
            value = stage_api._history_semantics(payload)
            if value.get("trade_date") != day or value.get("stage_id") != stage:
                raise ValueError("STAGE_RESPONSE_DATE_STAGE_MISMATCH:" + day)
            records.append({
                "trade_date": day,
                "stage_id": stage,
                "http_status": 200,
                "semantics": stage_api._history_http_record(day, stage, value),
            })
            continue

        if status == 409 and (day, stage) == HISTORY_PAIRS[1]:
            error_body = json.loads(raw, object_pairs_hook=_unique_pairs,
                                    parse_constant=lambda item: (_ for _ in ()).throw(
                                        ValueError("JSON_NONFINITE:" + item)))
            if error_body != EXPECTED_EXISTING_STAGE_ERROR:
                raise ValueError("STAGE_BASELINE_409_SEMANTICS_CHANGED:" + day)
            records.append({
                "trade_date": day,
                "stage_id": stage,
                "http_status": 409,
                "error_semantics": error_body,
                "error_semantic_sha256": _sha(_json_bytes(error_body)),
                "baseline_state": "BASELINE_FAIL_CANNOT_CONFIRM",
            })
            continue

        raise ValueError("STAGE_HTTP_STATUS_NOT_ALLOWED:" + day + ":" + str(status))
    return records


def _assert_history_matches(stage_api: Any, actual: list[dict[str, Any]],
                            expected: list[dict[str, Any]], label: str) -> None:
    if not isinstance(actual, list) or not isinstance(expected, list) or len(actual) != len(expected):
        raise ValueError(label + "_STAGE_SEMANTICS_CHANGED")
    for current, baseline in zip(actual, expected):
        identity = (current.get("trade_date"), current.get("stage_id"))
        if identity != (baseline.get("trade_date"), baseline.get("stage_id")):
            raise ValueError(label + "_STAGE_SEMANTICS_CHANGED")
        if current.get("http_status") != baseline.get("http_status"):
            raise ValueError(label + "_STAGE_HTTP_STATUS_CHANGED:" + str(identity[0]))
        if current.get("http_status") == 200:
            if not stage_api._history_http_matches(
                    [current.get("semantics")], [baseline.get("semantics")]):
                raise ValueError(label + "_STAGE_SEMANTICS_CHANGED:" + str(identity[0]))
        elif current.get("http_status") == 409:
            if (baseline.get("baseline_state") != "BASELINE_FAIL_CANNOT_CONFIRM"
                    or current.get("error_semantics") != baseline.get("error_semantics")
                    or current.get("error_semantic_sha256") != baseline.get("error_semantic_sha256")):
                raise ValueError(label + "_STAGE_BASELINE_ERROR_CHANGED:" + str(identity[0]))
        else:
            raise ValueError(label + "_STAGE_HTTP_STATUS_NOT_ALLOWED:" + str(identity[0]))


def _parse_assignments(plist: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    arguments = plist.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments or arguments[0] != "/usr/bin/env":
        raise ValueError("API_PLIST_PROGRAM_ARGUMENTS_INVALID")
    for item in arguments[1:]:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            if key and key.replace("_", "").isalnum():
                values[key] = value
    return values


def _validate_plist_delta(before_raw: bytes, candidate_raw: bytes,
                          manifest_sha: str) -> dict[str, Any]:
    before = plistlib.loads(before_raw)
    after = plistlib.loads(candidate_raw)
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("API_PLIST_OBJECT_REQUIRED")
    before_args = before.get("ProgramArguments")
    after_args = after.get("ProgramArguments")
    if not isinstance(before_args, list) or not isinstance(after_args, list):
        raise ValueError("API_PLIST_PROGRAM_ARGUMENTS_INVALID")
    if len(before_args) != len(after_args) or before_args[0] != after_args[0]:
        raise ValueError("API_PLIST_LAUNCH_ARGUMENT_SHAPE_CHANGED")
    changed_keys: set[str] = set()
    for old, new in zip(before_args, after_args):
        if old == new:
            continue
        if not isinstance(old, str) or not isinstance(new, str) or "=" not in old or "=" not in new:
            raise ValueError("API_PLIST_NON_ENV_ARGUMENT_CHANGED")
        old_key, old_value = old.split("=", 1)
        new_key, new_value = new.split("=", 1)
        if old_key != new_key or old_key not in REQUIRED_CHANGED_ENV_KEYS or old_value == new_value:
            raise ValueError("API_PLIST_ENVIRONMENT_DELTA_OUT_OF_SCOPE")
        changed_keys.add(old_key)
    if changed_keys != REQUIRED_CHANGED_ENV_KEYS:
        raise ValueError("API_PLIST_REQUIRED_RELEASE_ENV_DELTA_MISMATCH")
    before_environment = before.get("EnvironmentVariables", {})
    after_environment = after.get("EnvironmentVariables", {})
    if not isinstance(before_environment, dict) or not isinstance(after_environment, dict):
        raise ValueError("API_PLIST_ENVIRONMENT_OBJECT_INVALID")
    if set(before_environment) != set(after_environment):
        raise ValueError("API_PLIST_ENVIRONMENT_KEYS_CHANGED")
    env_changed = {key for key in set(before_environment) | set(after_environment)
                   if before_environment.get(key) != after_environment.get(key)}
    if not env_changed <= REQUIRED_CHANGED_ENV_KEYS:
        raise ValueError("API_PLIST_ENVIRONMENT_DELTA_OUT_OF_SCOPE")
    top_before = {key: value for key, value in before.items()
                  if key not in {"ProgramArguments", "EnvironmentVariables", "WorkingDirectory"}}
    top_after = {key: value for key, value in after.items()
                 if key not in {"ProgramArguments", "EnvironmentVariables", "WorkingDirectory"}}
    if top_before != top_after:
        raise ValueError("API_PLIST_OTHER_TOP_LEVEL_VALUE_CHANGED")
    old_env = _parse_assignments(before)
    new_env = _parse_assignments(after)
    expected = {
        "V35_APP_ROOT": str(CANDIDATE_APP_ROOT),
        "V35_RELEASE_ID": CANDIDATE_RELEASE_ID,
        "PYTHONPATH": f"{CANDIDATE_APP_ROOT / 'upstreams'}:{CANDIDATE_APP_ROOT}",
        "V35_RELEASE_MANIFEST_PATH": str(CANDIDATE_MANIFEST_PATH),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
    }
    if any(new_env.get(key) != value for key, value in expected.items()):
        raise ValueError("API_PLIST_CANDIDATE_RELEASE_IDENTITY_MISMATCH")
    if before.get("WorkingDirectory") != old_env.get("V35_APP_ROOT"):
        raise ValueError("API_PLIST_BEFORE_WORKING_DIRECTORY_MISMATCH")
    if after.get("WorkingDirectory") != str(CANDIDATE_APP_ROOT):
        raise ValueError("API_PLIST_CANDIDATE_WORKING_DIRECTORY_MISMATCH")
    return {
        "changed_environment_keys": sorted(changed_keys),
        "working_directory_changed": True,
        "other_plist_values_preserved": True,
    }


def _validate_inputs(adapter: Any, publisher: Any, guard: Any,
                     stage_api: Any) -> dict[str, Any]:
    summary = _expected_active_summary()
    if not ACTIVE_API_PLIST.is_file() or ACTIVE_API_PLIST.is_symlink():
        raise ValueError("ACTIVE_API_PLIST_NOT_REGULAR")
    if _sha(ACTIVE_API_PLIST.read_bytes()) != EXPECTED_API_PLIST_SHA256:
        raise ValueError("ACTIVE_API_PLIST_SHA_MISMATCH")
    if not ACTIVE_SCHEDULER_PLIST.is_file() or ACTIVE_SCHEDULER_PLIST.is_symlink():
        raise ValueError("ACTIVE_SCHEDULER_PLIST_NOT_REGULAR")
    scheduler_sha = _sha(ACTIVE_SCHEDULER_PLIST.read_bytes())
    if scheduler_sha != EXPECTED_SCHEDULER_SHA256:
        raise ValueError("ACTIVE_SCHEDULER_PLIST_SHA_MISMATCH")

    active = guard.read_active_release(publisher.ACTIVE_API_PLIST)
    base = guard._base_binding(active)
    expected_summary = {
        "app_root": str(active["app_root"]),
        "release_manifest_sha256": active["release_manifest_sha256"],
        "application_inventory_sha256": active["application_inventory_sha256"],
        "api_plist_sha256": active["api_plist_sha256"],
    }
    if any(summary.get(key) != value for key, value in expected_summary.items()):
        raise ValueError("ACTIVE_RELEASE_DIFFERS_FROM_PINNED_SUMMARY")
    if (active.get("release_id") != EXPECTED_ACTIVE_RELEASE_ID
            or active.get("release_manifest_sha256") != EXPECTED_ACTIVE_MANIFEST_SHA256
            or active.get("application_inventory_sha256") != EXPECTED_ACTIVE_INVENTORY_SHA256
            or active.get("api_plist_sha256") != EXPECTED_API_PLIST_SHA256):
        raise ValueError("ACTIVE_RELEASE_IDENTITY_MISMATCH")

    source = _validate_source_review()
    manifest, manifest_raw = _read_json(CANDIDATE_MANIFEST_PATH)
    if _sha(manifest_raw) != CANDIDATE_MANIFEST_SHA256:
        raise ValueError("CANDIDATE_MANIFEST_SHA_MISMATCH")
    delta, delta_raw = _read_json(CANDIDATE_DELTA_PATH)
    if _sha(delta_raw) != CANDIDATE_DELTA_SHA256:
        raise ValueError("CANDIDATE_DELTA_SHA_MISMATCH")
    if _sha(SOURCE_DELTA_PATH.read_bytes()) != manifest.get("source", {}).get("writer_delta_receipt_sha256"):
        raise ValueError("CANDIDATE_SOURCE_DELTA_BINDING_MISMATCH")
    candidate = manifest.get("candidate", {})
    inventory_record = manifest.get("application_inventory", {})
    integration = manifest.get("api_integration", {})
    if (manifest.get("schema_version") != "v4.release_candidate.v1"
            or manifest.get("candidate_status") != "READY_FOR_REVIEW"
            or manifest.get("activation_status") != "NOT_ACTIVATED"
            or manifest.get("deployment_status") is not False
            or candidate.get("root") != str(CANDIDATE_RELEASE_ROOT)
            or candidate.get("app_root") != str(CANDIDATE_APP_ROOT)
            or candidate.get("release_id") != CANDIDATE_RELEASE_ID
            or integration.get("status") != "PASS"
            or integration.get("active_pointer") != "base"
            or integration.get("base") != base
            or integration.get("active_api_plist_sha256") != EXPECTED_API_PLIST_SHA256
            or integration.get("candidate", {}).get("app_root") != str(CANDIDATE_APP_ROOT)
            or integration.get("candidate", {}).get("release_id") != CANDIDATE_RELEASE_ID
            or integration.get("candidate", {}).get("manifest_path") != str(CANDIDATE_MANIFEST_PATH)
            or integration.get("candidate", {}).get("application_inventory_sha256") != CANDIDATE_INVENTORY_SHA256
            or integration.get("delta_receipt_file") != CANDIDATE_DELTA_PATH.name
            or integration.get("delta_receipt_sha256") != CANDIDATE_DELTA_SHA256
            or integration.get("non_delta_active_release_bytes_preserved") is not True):
        raise ValueError("CANDIDATE_MANIFEST_INTEGRATION_IDENTITY_MISMATCH")
    safety = manifest.get("safety", {})
    if (safety.get("RESEARCH_ONLY") is not True
            or any(safety.get(key) is not False for key in
                   ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise ValueError("CANDIDATE_FINANCIAL_SAFETY_FLAGS_INVALID")
    actual_inventory = guard.inventory_tree(CANDIDATE_APP_ROOT)
    inventory_sha = guard.inventory_digest(actual_inventory)
    if (inventory_sha != CANDIDATE_INVENTORY_SHA256
            or inventory_record.get("aggregate_sha256") != inventory_sha
            or inventory_record.get("entry_count") != len(actual_inventory)
            or inventory_record.get("entries") != actual_inventory):
        raise ValueError("CANDIDATE_APPLICATION_INVENTORY_MISMATCH")
    if (delta.get("schema_version") != "v4.api_release_delta_receipt.v1"
            or delta.get("base") != base
            or delta.get("application_inventory_sha256") != inventory_sha
            or delta.get("entries") != integration.get("delta_entries")
            or sorted(row.get("path") for row in delta.get("entries", []))
            != sorted(integration.get("delta_paths", []))):
        raise ValueError("CANDIDATE_DELTA_MANIFEST_BINDING_MISMATCH")
    verified_delta, preserved = guard._verify_delta_files(
        base_app=Path(base["app_root"]), candidate_app=CANDIDATE_APP_ROOT,
        entries=delta["entries"], static_tree=delta.get("static_tree"),
    )
    if verified_delta != delta["entries"]:
        raise ValueError("CANDIDATE_DELTA_VERIFICATION_RECORD_MISMATCH")
    preserved_sha = guard.inventory_digest(preserved)
    if (integration.get("non_delta_entry_count") != len(preserved)
            or integration.get("non_delta_inventory_sha256") != preserved_sha):
        raise ValueError("CANDIDATE_NON_DELTA_PRESERVATION_PROOF_MISMATCH")
    candidate_frontend = publisher._validate_frontend_dist(
        CANDIDATE_APP_ROOT, actual_inventory
    )

    for relative in ("stage_center/approved_research_read.json",
                     "stage_center/approved_research_read.sha256"):
        active_binding = Path(base["app_root"]) / relative
        candidate_binding = CANDIDATE_APP_ROOT / relative
        if active_binding.is_symlink() or candidate_binding.is_symlink():
            raise ValueError("APPROVED_RESEARCH_BINDING_NOT_REGULAR:" + relative)
        active_bytes = active_binding.read_bytes()
        candidate_bytes = candidate_binding.read_bytes()
        if active_bytes != candidate_bytes:
            raise ValueError("APPROVED_RESEARCH_BINDING_CHANGED:" + relative)

    observed = publisher._observe_loaded()
    active_runtime = {
        "V35_APP_ROOT": str(active["app_root"]),
        "V35_RELEASE_ID": EXPECTED_ACTIVE_RELEASE_ID,
        "V35_RELEASE_MANIFEST_SHA256": EXPECTED_ACTIVE_MANIFEST_SHA256,
    }
    _assert_identity(observed, active_runtime, "ACTIVE_API")
    health = _health_readiness(publisher)
    before_history = _history(stage_api, publisher)
    return {
        "summary": summary,
        "active": active,
        "base": base,
        "scheduler_sha256": scheduler_sha,
        "manifest": manifest,
        "manifest_sha256": _sha(manifest_raw),
        "delta": delta,
        "delta_sha256": _sha(delta_raw),
        "candidate_frontend": candidate_frontend,
        "inventory_sha256": inventory_sha,
        "inventory_count": len(actual_inventory),
        "delta_count": len(verified_delta),
        "non_delta_count": len(preserved),
        "non_delta_inventory_sha256": preserved_sha,
        "source_review_sha256": SOURCE_REVIEW_SHA256,
        "source_delta_sha256": SOURCE_DELTA_SHA256,
        "loaded_identity": observed["identity"],
        "health_readiness": health,
        "stage_before": before_history,
    }


def _write_once(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if path.read_bytes() != raw:
        raise ValueError("OUTPUT_WRITEBACK_MISMATCH:" + str(path))


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    raw = _json_bytes(value)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    _write_once(temporary, raw)
    os.replace(temporary, path)


def _prepare(adapter: Any, wrapper: Any, publisher: Any, guard: Any,
             helper: Any, stage_api: Any) -> dict[str, Any]:
    receipt_path = E / "receipts/publication_tool_r2.json"
    if os.path.lexists(receipt_path):
        raise FileExistsError("PUBLICATION_TOOL_RECEIPT_ALREADY_EXISTS")
    inputs = _validate_inputs(adapter, publisher, guard, stage_api)
    before_raw = ACTIVE_API_PLIST.read_bytes()
    if _sha(before_raw) != EXPECTED_API_PLIST_SHA256:
        raise ValueError("ACTIVE_API_PLIST_CHANGED_DURING_PREPARATION")
    current_plist = plistlib.loads(before_raw)
    candidate_plist = helper.rewrite_api_only_plist(
        current_plist,
        candidate_app_root=CANDIDATE_APP_ROOT,
        release_id=CANDIDATE_RELEASE_ID,
        manifest_path=CANDIDATE_MANIFEST_PATH,
        manifest_sha256=inputs["manifest_sha256"],
        candidate_manager_state_root=None,
    )
    candidate_raw = plistlib.dumps(candidate_plist, fmt=plistlib.FMT_XML, sort_keys=True)
    plist_diff = _validate_plist_delta(before_raw, candidate_raw, inputs["manifest_sha256"])
    rollback_raw = before_raw
    if _sha(rollback_raw) != _sha(before_raw):
        raise ValueError("ROLLBACK_PREIMAGE_MISMATCH")

    operation_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    operation_root = E / "publication-r2" / ("operation-" + operation_id)
    operation_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    before_path = operation_root / "current-before.plist"
    candidate_path = operation_root / "candidate.plist"
    rollback_path = operation_root / "rollback.plist"
    plan_path = operation_root / "plan.json"
    review_path = operation_root / "independent-review.json"
    _write_once(before_path, before_raw)
    _write_once(candidate_path, candidate_raw)
    _write_once(rollback_path, rollback_raw)
    tool_sha = _sha(Path(__file__).read_bytes())
    binding_paths = ["stage_center/approved_research_read.json",
                     "stage_center/approved_research_read.sha256"]
    binding_sha = {path: _sha((Path(inputs["base"]["app_root"]) / path).read_bytes())
                   for path in binding_paths}
    plan = {
        "schema_version": "v4.us_daily_chain.publication_plan.r2",
        "operation_id": operation_id,
        "status": "PREPARED_NOT_DEPLOYED",
        "activation_status": "NOT_ACTIVATED",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tool": {"path": str(Path(__file__).resolve()), "sha256": tool_sha},
        "writer_identity": WRITER_IDENTITY,
        "inputs": {
            "adapter_path": str(ADAPTER_PATH), "adapter_sha256": ADAPTER_SHA256,
            "active_summary_path": str(ACTIVE_SUMMARY_PATH), "active_summary_sha256": ACTIVE_SUMMARY_SHA256,
            "active_release_id": EXPECTED_ACTIVE_RELEASE_ID,
            "active_manifest_sha256": EXPECTED_ACTIVE_MANIFEST_SHA256,
            "active_inventory_sha256": EXPECTED_ACTIVE_INVENTORY_SHA256,
            "source_delta_path": str(SOURCE_DELTA_PATH), "source_delta_sha256": inputs["source_delta_sha256"],
            "source_review_path": str(SOURCE_REVIEW_PATH), "source_review_sha256": inputs["source_review_sha256"],
            "candidate_manifest_path": str(CANDIDATE_MANIFEST_PATH),
            "candidate_manifest_sha256": inputs["manifest_sha256"],
            "candidate_delta_path": str(CANDIDATE_DELTA_PATH),
            "candidate_delta_sha256": inputs["delta_sha256"],
            "candidate_inventory_sha256": inputs["inventory_sha256"],
            "candidate_inventory_entry_count": inputs["inventory_count"],
            "delta_entry_count": inputs["delta_count"],
            "non_delta_entry_count": inputs["non_delta_count"],
            "non_delta_inventory_sha256": inputs["non_delta_inventory_sha256"],
            "stage_api_reader_path": str(STAGE_API_PATH), "stage_api_reader_sha256": STAGE_API_SHA256,
            "publisher_transition_helper_path": str(PUBLISHER_HELPER_PATH),
            "publisher_transition_helper_sha256": PUBLISHER_HELPER_SHA256,
            "cutover_helper_sha256": EXPECTED_CUTOVER_SHA256,
        },
        "before": {
            "active_api_plist_path": str(ACTIVE_API_PLIST),
            "active_api_plist_sha256": _sha(before_raw),
            "scheduler_plist_path": str(ACTIVE_SCHEDULER_PLIST),
            "scheduler_plist_sha256": inputs["scheduler_sha256"],
            "loaded_identity": inputs["loaded_identity"],
            "health_readiness": inputs["health_readiness"],
            "stage_semantics": inputs["stage_before"],
            "approved_research_binding_sha256": binding_sha,
        },
        "candidate": {
            "release_root": str(CANDIDATE_RELEASE_ROOT),
            "app_root": str(CANDIDATE_APP_ROOT),
            "release_id": CANDIDATE_RELEASE_ID,
            "manifest_path": str(CANDIDATE_MANIFEST_PATH),
            "manifest_sha256": inputs["manifest_sha256"],
            "application_inventory_sha256": inputs["inventory_sha256"],
            "frontend_integrity": inputs["candidate_frontend"],
            "api_plist_path": str(candidate_path),
            "api_plist_sha256": _sha(candidate_raw),
        },
        "rollback": {
            "plist_path": str(rollback_path),
            "plist_sha256": _sha(rollback_raw),
            "exact_current_before_copy": True,
            "cas_required_current_sha256": _sha(candidate_raw),
        },
        "artifacts": {
            "operation_root": str(operation_root),
            "plan_path": str(plan_path),
            "current_before_plist_path": str(before_path),
            "candidate_plist_path": str(candidate_path),
            "rollback_plist_path": str(rollback_path),
            "execution_receipt_path": str(operation_root / "execution-receipt.json"),
        },
        "plist_delta": plist_diff,
        "shared_lock": {
            "path": str(ACTIVE_API_PLIST.with_name(".com.lexi.v35.api-only.release.lock")),
            "provider": "pinned Stage R5 publisher._switch_lock / guard shared_api_release_lock",
        },
        "review_gate": {
            "receipt_path": str(review_path),
            "schema_version": REVIEW_SCHEMA,
            "status_required": "PASS",
            "bindings_required": ["tool_sha256", "plan_sha256", "operation_id",
                                  "candidate_inventory_sha256", "candidate_manifest_sha256",
                                  "candidate_delta_sha256", "active_api_plist_sha256",
                                  "publisher_transition_helper_sha256"],
            "reviewer_must_be_independent_from": WRITER_IDENTITY,
            "required_model": "gpt-6-luna",
            "required_reasoning_effort": "max",
        },
        "execute_contract": {
            "confirmation_token": CONFIRM_EXECUTE,
            "allowed_live_write": str(ACTIVE_API_PLIST),
            "allowed_service_label": "com.lexi.v35.api-only",
            "scheduler_action": "UNCHANGED",
            "approved_research_binding_action": "UNCHANGED",
            "launchctl_transition": ["bootout", "_wait_for_unloaded", "bootstrap", "_wait_for_candidate"],
            "rollback_transition": ["_wait_for_recovery_transition", "bootout_if_candidate",
                                    "_wait_for_unloaded", "bootstrap_if_unloaded", "_wait_for_candidate"],
            "post_switch_checks": ["loaded identity", "/healthz", "/readyz", "two Stage semantic readbacks"],
            "rollback": "Only restore saved preimage when current active plist SHA exactly equals this candidate plist SHA.",
        },
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False,
                    "natural_verified": False},
    }
    plan_raw = _json_bytes(plan)
    _write_once(plan_path, plan_raw)
    plan_sha = _sha(plan_raw)
    receipt = {
        "schema_version": "v4.us_daily_chain.publication_tool_receipt.r2",
        "status": "PREPARED_NOT_DEPLOYED",
        "operation_id": operation_id,
        "tool_path": str(Path(__file__).resolve()),
        "tool_sha256": tool_sha,
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha,
        "candidate_manifest_sha256": inputs["manifest_sha256"],
        "candidate_delta_sha256": inputs["delta_sha256"],
        "candidate_inventory_sha256": inputs["inventory_sha256"],
        "publisher_transition_helper_sha256": PUBLISHER_HELPER_SHA256,
        "active_api_plist_sha256": _sha(before_raw),
        "candidate_api_plist_sha256": _sha(candidate_raw),
        "rollback_api_plist_sha256": _sha(rollback_raw),
        "delta_entry_count": inputs["delta_count"],
        "non_delta_entry_count": inputs["non_delta_count"],
        "stage_before_semantics": inputs["stage_before"],
        "execution_status": "NOT_RUN",
        "independent_review_status": "PENDING",
        "files_written": [str(before_path), str(candidate_path), str(rollback_path), str(plan_path)],
        "safety": {"live_api_plist_written": False, "scheduler_plist_written": False,
                    "launchctl_called": False, "owner_api_called": False,
                    "RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False},
        "cannot_confirm": [
            "The reviewed candidate is prepared but not activated.",
            "Independent publication-tool review and execute-time review-gate receipt are pending.",
            "Candidate API runtime, post-switch Stage API readback, UI readback, and natural-slot behavior are not verified.",
        ],
    }
    _write_once(receipt_path, _json_bytes(receipt))
    return receipt


def _validate_plan(plan_path: Path, expected_sha: str, publisher: Any,
                   guard: Any) -> tuple[dict[str, Any], bytes]:
    if not plan_path.is_absolute() or plan_path.resolve(strict=True) != plan_path:
        raise ValueError("PLAN_PATH_NOT_EXACT")
    operation_root = plan_path.parent
    if E / "publication-r2" not in operation_root.parents:
        raise ValueError("PLAN_PATH_OUTSIDE_PUBLICATION_SCOPE")
    plan, raw = _read_json(plan_path)
    if _sha(raw) != expected_sha:
        raise ValueError("PLAN_SHA_MISMATCH")
    tool_sha = _sha(Path(__file__).read_bytes())
    if (plan.get("schema_version") != "v4.us_daily_chain.publication_plan.r2"
            or plan.get("status") != "PREPARED_NOT_DEPLOYED"
            or plan.get("activation_status") != "NOT_ACTIVATED"
            or plan.get("tool", {}).get("sha256") != tool_sha
            or plan.get("artifacts", {}).get("plan_path") != str(plan_path)):
        raise ValueError("PLAN_IDENTITY_OR_TOOL_SHA_MISMATCH")
    artifacts = plan.get("artifacts", {})
    for key, expected in (("current_before_plist_path", plan.get("before", {}).get("active_api_plist_sha256")),
                          ("candidate_plist_path", plan.get("candidate", {}).get("api_plist_sha256")),
                          ("rollback_plist_path", plan.get("rollback", {}).get("plist_sha256"))):
        path = Path(artifacts.get(key, ""))
        if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != expected:
            raise ValueError("PLAN_ARTIFACT_SHA_MISMATCH:" + key)
    if (Path(artifacts["current_before_plist_path"]).read_bytes()
            != Path(artifacts["rollback_plist_path"]).read_bytes()):
        raise ValueError("ROLLBACK_PREIMAGE_NOT_EXACT_COPY")
    if _sha(ACTIVE_API_PLIST.read_bytes()) != plan["before"]["active_api_plist_sha256"]:
        raise ValueError("ACTIVE_API_PLIST_PREIMAGE_CAS_MISMATCH")
    if _sha(ACTIVE_SCHEDULER_PLIST.read_bytes()) != plan["before"]["scheduler_plist_sha256"]:
        raise ValueError("ACTIVE_SCHEDULER_PLIST_CHANGED")
    active = guard.read_active_release(publisher.ACTIVE_API_PLIST)
    if (active.get("release_manifest_sha256") != plan["inputs"]["active_manifest_sha256"]
            or active.get("application_inventory_sha256") != plan["inputs"]["active_inventory_sha256"]
            or active.get("api_plist_sha256") != plan["before"]["active_api_plist_sha256"]):
        raise ValueError("ACTIVE_RELEASE_CHANGED_SINCE_PREPARE")
    return plan, raw


def _validate_independent_review(path: Path, plan: Mapping[str, Any],
                                 plan_sha: str) -> dict[str, Any]:
    review, raw = _read_json(path)
    verdict = review.get("verdict", {})
    expected = {
        "tool_sha256": plan["tool"]["sha256"],
        "plan_sha256": plan_sha,
        "operation_id": plan["operation_id"],
        "candidate_inventory_sha256": plan["candidate"]["application_inventory_sha256"],
        "candidate_manifest_sha256": plan["candidate"]["manifest_sha256"],
        "candidate_delta_sha256": plan["inputs"]["candidate_delta_sha256"],
        "active_api_plist_sha256": plan["before"]["active_api_plist_sha256"],
        "publisher_transition_helper_sha256": plan["inputs"]["publisher_transition_helper_sha256"],
    }
    if (review.get("schema_version") != REVIEW_SCHEMA
            or review.get("status") != "PASS"
            or review.get("reviewer_identity") in (None, "", WRITER_IDENTITY)
            or review.get("reviewer_independent_from") != WRITER_IDENTITY
            or review.get("model") != "gpt-6-luna"
            or review.get("reasoning_effort") != "max"
            or verdict.get("reviewed") != "PASS"
            or verdict.get("frozen_pass_scope") != "PASS"
            or verdict.get("behavior_verified") != "PASS"):
        raise ValueError("INDEPENDENT_PUBLICATION_REVIEW_NOT_PASS")
    for key, value in expected.items():
        if review.get(key) != value:
            raise ValueError("INDEPENDENT_REVIEW_BINDING_MISMATCH:" + key)
    return {"path": str(path), "sha256": _sha(raw),
            "reviewer_identity": review["reviewer_identity"]}


def _transition_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "before": {"loaded_identity": plan["before"]["loaded_identity"]},
        "target": {
            "app_root": plan["candidate"]["app_root"],
            "release_id": plan["candidate"]["release_id"],
            "release_manifest_sha256": plan["candidate"]["manifest_sha256"],
        },
    }


def _candidate_wait_expectation(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "app_root": plan["candidate"]["app_root"],
        "release_id": plan["candidate"]["release_id"],
        "release_manifest_sha256": plan["candidate"]["manifest_sha256"],
        "candidate_release": {
            "frontend": plan["candidate"]["frontend_integrity"],
        },
    }


def _active_wait_expectation(plan: Mapping[str, Any], publisher: Any,
                             guard: Any) -> dict[str, Any]:
    active = guard.read_active_release(publisher.ACTIVE_API_PLIST)
    expected_identity = {
        "app_root": plan["before"]["loaded_identity"]["V35_APP_ROOT"],
        "release_id": plan["inputs"]["active_release_id"],
        "release_manifest_sha256": plan["inputs"]["active_manifest_sha256"],
        "application_inventory_sha256": plan["inputs"]["active_inventory_sha256"],
    }
    if any(active.get(key) != value for key, value in expected_identity.items()):
        raise ValueError("ROLLBACK_ACTIVE_RELEASE_IDENTITY_CHANGED")
    inventory = active.get("inventory")
    if not isinstance(inventory, list) or guard.inventory_digest(inventory) != expected_identity[
            "application_inventory_sha256"]:
        raise ValueError("ROLLBACK_ACTIVE_INVENTORY_CHANGED")
    frontend = publisher._validate_frontend_dist(Path(active["app_root"]), inventory)
    return {
        "app_root": expected_identity["app_root"],
        "release_id": expected_identity["release_id"],
        "release_manifest_sha256": expected_identity["release_manifest_sha256"],
        "candidate_release": {"frontend": frontend},
    }


def _execute(plan_path: Path, plan_sha: str, review_path: Path,
             confirm: str, adapter: Any, wrapper: Any, publisher: Any,
             guard: Any, helper: Any, stage_api: Any) -> dict[str, Any]:
    if confirm != CONFIRM_EXECUTE:
        raise ValueError("EXECUTE_CONFIRMATION_TOKEN_MISMATCH")
    plan, _plan_raw = _validate_plan(plan_path, plan_sha, publisher, guard)
    review = _validate_independent_review(review_path, plan, plan_sha)
    fresh = _validate_inputs(adapter, publisher, guard, stage_api)
    if (fresh["inventory_sha256"] != plan["candidate"]["application_inventory_sha256"]
            or fresh["manifest_sha256"] != plan["candidate"]["manifest_sha256"]
            or fresh["delta_sha256"] != plan["inputs"]["candidate_delta_sha256"]
            or fresh["candidate_frontend"] != plan["candidate"]["frontend_integrity"]
            or fresh["source_review_sha256"] != plan["inputs"]["source_review_sha256"]):
        raise ValueError("CANDIDATE_INPUTS_CHANGED_SINCE_REVIEW")
    operation_root = Path(plan["artifacts"]["operation_root"])
    execution_path = Path(plan["artifacts"]["execution_receipt_path"])
    if execution_path.exists() or execution_path.is_symlink():
        raise FileExistsError("EXECUTION_RECEIPT_ALREADY_EXISTS")
    receipt: dict[str, Any] = {
        "schema_version": "v4.us_daily_chain.publication_execution_receipt.r2",
        "status": "EXECUTING",
        "operation_id": plan["operation_id"],
        "tool_sha256": plan["tool"]["sha256"],
        "plan_sha256": plan_sha,
        "review": review,
        "steps": [],
        "recovery": {"status": "NOT_REQUIRED"},
        "safety": {"scheduler_changed": False, "approved_research_binding_changed": False,
                    "RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False},
    }
    _write_json_atomic(execution_path, receipt)
    before_raw = Path(plan["artifacts"]["current_before_plist_path"]).read_bytes()
    candidate_raw = Path(plan["artifacts"]["candidate_plist_path"]).read_bytes()
    active_path = Path(plan["before"]["active_api_plist_path"])
    expected_before_sha = plan["before"]["active_api_plist_sha256"]
    candidate_sha = plan["candidate"]["api_plist_sha256"]
    try:
        with publisher._switch_lock() as lease:
            if _sha(active_path.read_bytes()) != expected_before_sha:
                raise ValueError("ACTIVE_API_PLIST_PREIMAGE_CAS_MISMATCH")
            current_runtime = publisher._observe_loaded()
            _assert_identity(current_runtime, {
                "V35_APP_ROOT": plan["before"]["loaded_identity"]["V35_APP_ROOT"],
                "V35_RELEASE_ID": plan["before"]["loaded_identity"]["V35_RELEASE_ID"],
                "V35_RELEASE_MANIFEST_SHA256": plan["before"]["loaded_identity"]["V35_RELEASE_MANIFEST_SHA256"],
            }, "EXECUTE_PREIMAGE")
            current_health = _health_readiness(publisher)
            if current_health != plan["before"]["health_readiness"]:
                raise ValueError("API_HEALTH_READINESS_CHANGED_SINCE_PREPARE")
            current_stage = _history(stage_api, publisher)
            _assert_history_matches(stage_api, current_stage,
                                    plan["before"]["stage_semantics"], "PRE_SWITCH")
            if _sha(ACTIVE_SCHEDULER_PLIST.read_bytes()) != plan["before"]["scheduler_plist_sha256"]:
                raise ValueError("ACTIVE_SCHEDULER_PLIST_CHANGED_BEFORE_SWITCH")
            publisher._atomic_replace_bytes(active_path, candidate_raw, active_path,
                                             expected_before_sha, lock_lease=lease)
            receipt["steps"].append({"step": "active_plist_cas_replace", "result": "PASS",
                                     "active_api_plist_sha256": candidate_sha})
            _write_json_atomic(execution_path, receipt)
            publisher._launchctl_action("bootout")
            receipt["steps"].append({"step": "launchctl_bootout", "result": "PASS"})
            _write_json_atomic(execution_path, receipt)
            unloaded = publisher._wait_for_unloaded(
                [plan["before"]["loaded_identity"]], timeout_s=30
            )
            if unloaded.get("wait_status") != "ABSENT_CONFIRMED":
                raise ValueError("API_ONLY_SWITCH_BOOTOUT_NOT_CONFIRMED")
            receipt["steps"].append({
                "step": "launchctl_bootout_wait_absent",
                "result": "PASS",
                "poll_count": unloaded.get("poll_count"),
            })
            _write_json_atomic(execution_path, receipt)
            if _sha(active_path.read_bytes()) != candidate_sha:
                raise ValueError("ACTIVE_API_PLIST_CHANGED_AFTER_BOOTOUT")
            publisher._launchctl_action("bootstrap")
            receipt["steps"].append({"step": "launchctl_bootstrap", "result": "PASS"})
            _write_json_atomic(execution_path, receipt)
            candidate_wait = publisher._wait_for_candidate(
                _candidate_wait_expectation(plan), CANDIDATE_APP_ROOT, timeout_s=60
            )
            receipt["steps"].append({
                "step": "launchctl_bootstrap_wait_ready",
                "result": "PASS",
                "runtime": candidate_wait.get("runtime"),
            })
            _write_json_atomic(execution_path, receipt)
            loaded = publisher._observe_loaded()
            _assert_identity(loaded, {
                "V35_APP_ROOT": str(CANDIDATE_APP_ROOT),
                "V35_RELEASE_ID": CANDIDATE_RELEASE_ID,
                "V35_RELEASE_MANIFEST_SHA256": plan["candidate"]["manifest_sha256"],
            }, "CANDIDATE_API")
            health = _health_readiness(publisher)
            stage_after = _history(stage_api, publisher)
            _assert_history_matches(stage_api, stage_after,
                                    plan["before"]["stage_semantics"], "POST_SWITCH")
            scheduler_after = _sha(ACTIVE_SCHEDULER_PLIST.read_bytes())
            if scheduler_after != plan["before"]["scheduler_plist_sha256"]:
                raise ValueError("SCHEDULER_CHANGED_DURING_SWITCH")
            for relative, digest in plan["before"]["approved_research_binding_sha256"].items():
                if _sha((CANDIDATE_APP_ROOT / relative).read_bytes()) != digest:
                    raise ValueError("APPROVED_RESEARCH_BINDING_CHANGED:" + relative)
            receipt.update({
                "status": "ACTIVATED_AND_VERIFIED",
                "loaded_identity_after": loaded["identity"],
                "health_readiness_after": health,
                "stage_semantics_after": stage_after,
                "candidate_transition_wait": candidate_wait,
                "bootout_absence_wait": unloaded,
                "scheduler_plist_sha256_after": scheduler_after,
                "recovery": {"status": "NOT_REQUIRED"},
            })
            _write_json_atomic(execution_path, receipt)
            return receipt
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        try:
            with publisher._switch_lock() as lease:
                current_sha = _sha(active_path.read_bytes()) if active_path.is_file() else "ABSENT"
                if current_sha != candidate_sha:
                    receipt["recovery"] = {
                        "status": "NOT_ATTEMPTED_ACTIVE_POINTER_NOT_OWNED",
                        "active_api_plist_sha256": current_sha,
                    }
                else:
                    publisher._atomic_replace_bytes(active_path, before_raw, active_path,
                                                     candidate_sha, lock_lease=lease)
                    transition, runtime_role = publisher._wait_for_recovery_transition(
                        _transition_plan(plan), timeout_s=30
                    )
                    recovery_transition: dict[str, Any] = {
                        "initial_runtime_role": runtime_role,
                        "initial_transition": transition,
                    }
                    candidate_identity = {
                        "V35_APP_ROOT": str(CANDIDATE_APP_ROOT),
                        "V35_RELEASE_ID": CANDIDATE_RELEASE_ID,
                        "V35_RELEASE_MANIFEST_SHA256": plan["candidate"]["manifest_sha256"],
                    }
                    if runtime_role == "candidate":
                        publisher._launchctl_action("bootout")
                        candidate_unloaded = publisher._wait_for_unloaded(
                            [candidate_identity], timeout_s=30
                        )
                        if candidate_unloaded.get("wait_status") != "ABSENT_CONFIRMED":
                            raise ValueError("ROLLBACK_CANDIDATE_BOOTOUT_NOT_CONFIRMED")
                        recovery_transition["candidate_bootout_absence"] = candidate_unloaded
                        runtime_role = "unloaded"
                    if runtime_role == "unloaded":
                        if _sha(active_path.read_bytes()) != expected_before_sha:
                            raise ValueError("ROLLBACK_ACTIVE_API_PLIST_PREIMAGE_MISMATCH")
                        publisher._launchctl_action("bootstrap")
                    rollback_wait = publisher._wait_for_candidate(
                        _active_wait_expectation(plan, publisher, guard),
                        Path(plan["before"]["loaded_identity"]["V35_APP_ROOT"]),
                        timeout_s=60,
                    )
                    recovery_transition["original_runtime_wait_ready"] = rollback_wait
                    recovered = publisher._observe_loaded()
                    _assert_identity(recovered, {
                        "V35_APP_ROOT": plan["before"]["loaded_identity"]["V35_APP_ROOT"],
                        "V35_RELEASE_ID": plan["before"]["loaded_identity"]["V35_RELEASE_ID"],
                        "V35_RELEASE_MANIFEST_SHA256": plan["before"]["loaded_identity"]["V35_RELEASE_MANIFEST_SHA256"],
                    }, "ROLLBACK_API")
                    health = _health_readiness(publisher)
                    stage_after_rollback = _history(stage_api, publisher)
                    _assert_history_matches(stage_api, stage_after_rollback,
                                            plan["before"]["stage_semantics"], "ROLLBACK")
                    receipt["recovery"] = {
                        "status": "ROLLED_BACK_AND_VERIFIED",
                        "active_api_plist_sha256": _sha(active_path.read_bytes()),
                        "loaded_identity": recovered["identity"],
                        "runtime_transition": recovery_transition,
                        "health_readiness": health,
                        "stage_semantics": stage_after_rollback,
                    }
        except Exception as recovery_exc:
            receipt["recovery"] = {
                "status": "ROLLBACK_FAILED_OR_UNVERIFIED",
                "error": {"type": type(recovery_exc).__name__,
                          "message": str(recovery_exc)[:500]},
            }
        receipt["status"] = "FAILED_ROLLED_BACK" if receipt["recovery"].get("status") == "ROLLED_BACK_AND_VERIFIED" else "FAILED_RECOVERY_UNVERIFIED"
        _write_json_atomic(execution_path, receipt)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("prepare", "execute"), default="prepare")
    parser.add_argument("--plan", type=Path, help="prepared plan path for execute")
    parser.add_argument("--plan-sha256", help="exact SHA256 of the prepared plan")
    parser.add_argument("--review-receipt", type=Path, help="independent publication review bound to plan/tool")
    parser.add_argument("--confirm", help="exact execute confirmation token")
    args = parser.parse_args(argv)
    try:
        adapter, wrapper, publisher, guard, modules = _runtime()
        helper, stage_api = modules
        if args.action == "prepare":
            result = _prepare(adapter, wrapper, publisher, guard, helper, stage_api)
        else:
            if args.plan is None or args.plan_sha256 is None or args.review_receipt is None or args.confirm is None:
                raise ValueError("EXECUTE_REQUIRES_PLAN_SHA_REVIEW_RECEIPT_AND_CONFIRMATION")
            result = _execute(args.plan, args.plan_sha256, args.review_receipt,
                              args.confirm, adapter, wrapper, publisher, guard,
                              helper, stage_api)
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__,
                          "error": str(exc)[:500]}, ensure_ascii=False, sort_keys=True),
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
