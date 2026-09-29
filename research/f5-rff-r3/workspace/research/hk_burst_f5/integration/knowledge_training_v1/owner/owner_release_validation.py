"""Fail-closed validation for a newly bound F5 owner execution.

This validator is deliberately separate from the closed META2023 recovery
release. A knowledge binding, review, or metadata permission is never a fit
authorization. The CLI has no option to load executable policy or Python code.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping


OWNER_ROOT = Path(__file__).resolve().parent
OWNER_DIR = OWNER_ROOT.parent
WORKSPACE_ROOT = Path("/Users/lexi/Desktop/学习/因子工厂/workspace")
RESEARCH_ROOT = WORKSPACE_ROOT / "research/hk_burst_f5"
REVISION_BINDING_PATH = OWNER_ROOT / "OWNER_REVISION_BINDING.json"
OLD_CLOSED_EXECUTION_IDS = {
    "F5_META2023_BASEPLUS64_R1_20260923_CALENDAR_ADAPTER_20260924_CANDIDATE_BEFORE_FIT_RECOVERY_02",
}
ACCEPTED_HELPERS = {
    "core": (OWNER_DIR.parent.parent / "batches/factory_pilot_20260920/train_resume_20260921/src/f5_knowledge_core.py",
             "fedfcf9a1c62d19f0cf462b3002466beb714369bf943016fe655a0790a426c4e"),
    "official": (OWNER_DIR.parent.parent / "batches/factory_pilot_20260920/train_resume_20260921/src/f5_knowledge_official.py",
                 "1960962e805b4cd544452675488c0a0a3cbfb529a9ecb7997b28f96cd45f3914"),
}
OFFICIAL_COMPONENTS = {
    "guard": (WORKSPACE_ROOT / "hkconnect_price_semantics_v2_20260919/zero_label_parity/execution_guard_core.py",
              "85929366a7b018480085c02f80edd312f7f47de94bab5c32982d4e8637d7d7e0"),
    "adapter": (WORKSPACE_ROOT / "hkconnect_price_semantics_v2_20260919/zero_label_parity/registry_adapter.py",
                "8596f2a20c165b5fbc2b92a597cb3e1177f6e40bfefac62753b40b3c7daae17f"),
    "builder": (Path("/Users/lexi/Desktop/学习/因子工厂/contracts/build_experiment_registry_backfill_20260821.py"),
                "df4bfc89fa5487966a8c7e1c1c50832e140339c2ccda3a02a9a59e5aaaeb58cf"),
    "validator": (Path("/Users/lexi/Desktop/学习/因子工厂/contracts/validate_experiment_registry_append_compatibility_v1.py"),
                  "80e49d05d13f33ee7e2cb8d4d10cae0e297bcdf5b113ff857d3bd141dea0f438"),
}
PINNED_RUNTIME_CODE = {
    "native_evidence_reuse_helper": (Path("/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/factory_pilot_20260920/train_resume_20260921/src/f5_native_evidence_reuse.py"),
                                     "966f83c03c801b5ee71a830122eddac01c8e687f4f4864ed2d369bba04bd955e"),
    "native_runtime_helper": (Path("/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/factory_pilot_20260920/train_resume_20260921/src/f5_native_runtime.py"),
                              "f09555e99cde8cf05cafcf4c0452ce2d9988a4eba4ca52f947a3441d79d093c1"),
    "native_reuse_binding": (Path("/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/input_refs/NATIVE_EVIDENCE_REUSE.json"),
                             "028d3a59c0584e0893ad81efdac49a6b088638a70d87d457e1a58cd73e10e486"),
    "original_metrics": (Path("/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/spike5/metrics.py"),
                         "c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763"),
    "original_settings": (Path("/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/spike5/settings.py"),
                          "702c374612806e45647b8cdb8cb345736b6cac689f23df352c00d08735bfb4fc"),
    "original_contract": (Path("/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/config/contract.json"),
                          "17ecffd1304e152da4f611b3ffc4b5e92633fac20d528b93ce9b6f8714b1c4bb"),
    "original_runner": (Path("/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/spike5/runner.py"),
                        "7afe20601a06c1932021eea38b7be0a7b4c868bec0f1875565e915f36ce7582a"),
}
PINNED_HISTORICAL_SOURCES = {
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/src/run_candidate.py": "9fb023f4944282fca26358530dc4981c7860ff2d3723e963ca1940e200370a8c",
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/src/runtime_common.py": "976e7852271a5011a4378323400067631802874d24fe0b55c34a63cc897461b9",
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/src/resource_tree.py": "8b13418ea44416a14bdf03e65dd79abee0872c95254e80cc28ca16dbc9f77190",
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/candidate_before_fit_recovery_20260924/src/candidate_recovery_entry.py": "cad7b0317dfee5e8b9358d1a4710b73ff51955765fe73bcc3d6bc064c084aa45",
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/candidate_before_fit_recovery_20260924/src/candidate_recovery_overlay.py": "b3d262176df5aaa3829cadf32093203573a6a09c39482ef5b2eb8311295dc437",
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/candidate_before_fit_recovery_20260924/src/candidate_recovery_worker.py": "a731a87db8ecef8b64307c01a6f162a08b68091c4b6ed11cef23fd98f6bdeb23",
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/candidate_before_fit_recovery_02/src/candidate_recovery_attempt02_launcher.py": "491916943ae64941f7e8a4bf8fe529121a1b966d19fa6aceb9d6e0918d213151",
}
PINNED_HISTORICAL_EVIDENCE = {
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/candidate_before_fit_recovery_02/input_refs/CANDIDATE_BEFORE_FIT_RECOVERY_02_BINDING.json": "e6fb3f0ae507481a27445a999d82ef5f1cdf48ef2682a026c29e220381f7f902",
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/candidate_before_fit_recovery_02/execution/CANDIDATE_BEFORE_FIT_RECOVERY_02/CANDIDATE_RUN_RECEIPT.json": "6e5a695596aef91607511b5dfc7b86169dd997589729cd3837b995c91bfe66cd",
    "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/candidate_before_fit_recovery_02/execution/CANDIDATE_BEFORE_FIT_RECOVERY_02/CANDIDATE_FIT_RECEIPT.json": "08fdaf8c5f60a5262acd63694c48fe15251d3c313909c88be2c292cd14405b70",
}


# Immutable source metadata supplied with the R1 review. Reading this contract
# is not permission to reopen its closed route or to read its payload inputs.
STATIC_CONTRACT_BASELINE = (
    Path("/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/contracts/contract.json"),
    "b98de920afe259e6c3b3f320d5f5bd145b999b7b488abe6c8486e285b5f76547",
)


class OwnerReleaseRejected(RuntimeError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_metadata(path: Path, label: str, *, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    path = Path(path)
    try:
        st = path.lstat()
    except OSError as exc:
        raise OwnerReleaseRejected(f"OWNER_BOUND_METADATA_MISSING:{label}") from exc
    if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_size > max_bytes:
        raise OwnerReleaseRejected(f"OWNER_BOUND_METADATA_TYPE_OR_SIZE:{label}")
    return path.read_bytes()


def read_object(path: Path, label: str) -> dict[str, Any]:
    raw = _regular_metadata(path, label)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise OwnerReleaseRejected(f"OWNER_BOUND_METADATA_DUPLICATE_KEY:{label}:{key}")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda token: (_ for _ in ()).throw(
                               OwnerReleaseRejected(f"OWNER_BOUND_METADATA_NONFINITE:{label}:{token}")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OwnerReleaseRejected(f"OWNER_BOUND_METADATA_JSON_INVALID:{label}") from exc
    if not isinstance(value, dict):
        raise OwnerReleaseRejected(f"OWNER_BOUND_METADATA_NOT_OBJECT:{label}")
    return value


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise OwnerReleaseRejected(code)


def _hash(value: Any, code: str) -> str:
    _require(isinstance(value, str) and len(value) == 64 and
             all(char in "0123456789abcdef" for char in value), code)
    return value


def _under(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve(strict=True).relative_to(Path(root).resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def validate_revision_binding(path: Path = REVISION_BINDING_PATH) -> dict[str, Any]:
    """Verify fixed maintenance and historical dependencies without loading code."""
    if Path(path).resolve() != REVISION_BINDING_PATH.resolve():
        raise OwnerReleaseRejected("OWNER_REVISION_BINDING_PATH_NOT_FIXED")
    binding = read_object(REVISION_BINDING_PATH, "owner_revision_binding")
    _require(binding.get("schema") == "f5.training_owner_revision_binding.v1",
             "OWNER_REVISION_BINDING_SCHEMA_MISMATCH")
    _require(binding.get("status") == "MAINTENANCE_SOURCE_CLOSURE_BOUND",
             "OWNER_REVISION_BINDING_NOT_ACTIVE")
    entries = binding.get("files")
    _require(isinstance(entries, list) and bool(entries), "OWNER_REVISION_FILE_MANIFEST_MISSING")
    seen: set[str] = set()
    for item in entries:
        _require(isinstance(item, dict), "OWNER_REVISION_FILE_ENTRY_INVALID")
        path_text = item.get("path")
        expected = _hash(item.get("sha256"), "OWNER_REVISION_FILE_SHA_INVALID")
        _require(isinstance(path_text, str) and path_text not in seen,
                 "OWNER_REVISION_FILE_DUPLICATE_OR_PATH_INVALID")
        seen.add(path_text)
        source = Path(path_text)
        _require(source.is_file() and not source.is_symlink(),
                 "OWNER_REVISION_SOURCE_FILE_MISSING_OR_SYMLINK")
        _require(sha256_file(source) == expected, "OWNER_REVISION_SOURCE_SHA_MISMATCH")
    helpers = binding.get("accepted_helpers")
    _require(isinstance(helpers, list) and len(helpers) == 2,
             "OWNER_ACCEPTED_HELPER_MANIFEST_MISSING")
    expected_helpers = {str(path.resolve()): digest for path, digest in ACCEPTED_HELPERS.values()}
    actual_helpers = {str(Path(item.get("path", "")).resolve()): item.get("sha256")
                      for item in helpers if isinstance(item, dict)}
    _require(actual_helpers == expected_helpers, "OWNER_ACCEPTED_HELPER_PATH_SET_MISMATCH")
    for item in helpers:
        _require(isinstance(item, dict), "OWNER_ACCEPTED_HELPER_ENTRY_INVALID")
        source = Path(item.get("path", ""))
        _require(source.is_file() and not source.is_symlink() and
                 sha256_file(source) == _hash(item.get("sha256"), "OWNER_ACCEPTED_HELPER_SHA_INVALID"),
                 "OWNER_ACCEPTED_HELPER_DRIFT")
    history = binding.get("historical_owner_sources")
    _require(isinstance(history, list) and bool(history), "OWNER_HISTORICAL_SOURCE_MANIFEST_MISSING")
    expected_history = {str(Path(item["path"]).resolve()): item["sha256"]
                        for item in binding.get("historical_owner_sources", [])}
    expected_pinned = {str(Path(path).resolve()): digest for path, digest in PINNED_HISTORICAL_SOURCES.items()}
    _require(len(expected_history) == len(history) and expected_history == expected_pinned,
             "OWNER_HISTORICAL_SOURCE_SET_MISMATCH")
    migrations = binding.get("historical_source_migrations", [])
    _require(isinstance(migrations, list), "OWNER_HISTORICAL_MIGRATION_MANIFEST_INVALID")
    migration_by_path = {item.get("source_path"): item for item in migrations if isinstance(item, dict)}
    _require(len(migration_by_path) == len(migrations), "OWNER_HISTORICAL_MIGRATION_DUPLICATE_OR_INVALID")
    expected_migrated_path = str(Path(
        "/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/"
        "meta2023_baseplus64_r1_20260923/src/resource_tree.py"
    ).resolve())
    _require(set(migration_by_path) == {expected_migrated_path},
             "OWNER_HISTORICAL_MIGRATION_SET_MISMATCH")
    for item in history:
        _require(isinstance(item, dict), "OWNER_HISTORICAL_SOURCE_ENTRY_INVALID")
        source = Path(item.get("path", ""))
        expected_sha = _hash(item.get("sha256"), "OWNER_HISTORICAL_SOURCE_SHA_INVALID")
        _require(source.is_file() and not source.is_symlink(), "OWNER_HISTORICAL_SOURCE_MISSING_OR_SYMLINK")
        actual_sha = sha256_file(source)
        if actual_sha == expected_sha:
            _require(str(source.resolve()) not in migration_by_path,
                     "OWNER_HISTORICAL_MIGRATION_UNUSED")
            continue
        migration = migration_by_path.get(str(source.resolve()))
        _require(isinstance(migration, dict) and
                 migration.get("pinned_sha256") == expected_sha and
                 migration.get("observed_current_sha256") == actual_sha and
                 migration.get("original_bytes_status") == "CANNOT_CONFIRM" and
                 migration.get("status") == "REPLACED_BY_SHARED_RUNTIME_COMPONENT",
                 "OWNER_HISTORICAL_SOURCE_DRIFT")
        from runtime_bridge import load_owner_runtime_bridge, runtime_shared_source_records
        runtime_bridge = load_owner_runtime_bridge()
        shared_sources = runtime_shared_source_records(runtime_bridge)
        monitor = shared_sources["resource_monitor"]
        _require(migration.get("replacement_path") == monitor["path"] and
                 migration.get("replacement_sha256") == monitor["sha256"] and
                 migration.get("replacement_sha256") ==
                 "9d0792a8e582d0345c83ddaf83a15612a5629b5f0460833b4715068324ff2752",
                 "OWNER_HISTORICAL_REPLACEMENT_COMPONENT_MISMATCH")
    from runtime_bridge import load_owner_runtime_bridge, runtime_shared_source_records
    bridge_bindings = runtime_shared_source_records(load_owner_runtime_bridge())
    _require(binding.get("runtime_manifest_binding_policy") ==
             "ORIGINAL_RUNTIME_VERIFIER_AND_FROZEN_REVIEW_AT_LOAD;SHA_RECORDED_PER_EXECUTION",
             "OWNER_SHARED_RUNTIME_MANIFEST_POLICY_MISMATCH")
    declared_runtime_sources = binding.get("runtime_shared_components")
    _require(isinstance(declared_runtime_sources, dict) and declared_runtime_sources == bridge_bindings,
             "OWNER_SHARED_RUNTIME_COMPONENT_BINDING_MISMATCH")
    evidence = binding.get("historical_execution_evidence")
    _require(isinstance(evidence, list), "OWNER_HISTORICAL_EVIDENCE_BINDING_MISSING")
    actual_evidence = {str(Path(item.get("path", "")).resolve()): item.get("sha256")
                       for item in evidence if isinstance(item, dict)}
    expected_evidence = {str(Path(path).resolve()): digest
                         for path, digest in PINNED_HISTORICAL_EVIDENCE.items()}
    _require(len(actual_evidence) == len(evidence) and actual_evidence == expected_evidence,
             "OWNER_HISTORICAL_EVIDENCE_SET_MISMATCH")
    for path_text, expected_sha in expected_evidence.items():
        path = Path(path_text)
        _require(path.is_file() and not path.is_symlink() and sha256_file(path) == expected_sha,
                 "OWNER_HISTORICAL_EVIDENCE_SHA_MISMATCH")
    official = binding.get("official_components")
    _require(isinstance(official, dict), "OWNER_OFFICIAL_COMPONENT_BINDING_MISSING")
    for label, (source, expected_sha) in OFFICIAL_COMPONENTS.items():
        item = official.get(label)
        _require(isinstance(item, dict) and Path(item.get("path", "")).resolve() == source.resolve() and
                 item.get("sha256") == expected_sha and source.is_file() and
                 sha256_file(source) == expected_sha,
                 "OWNER_OFFICIAL_COMPONENT_PATH_OR_SHA_MISMATCH")
    runtime_sources = binding.get("runtime_code_bindings")
    _require(isinstance(runtime_sources, dict) and set(runtime_sources) == set(PINNED_RUNTIME_CODE),
             "OWNER_RUNTIME_CODE_BINDINGS_MISSING_OR_EXTRA")
    for label, (source, expected_sha) in PINNED_RUNTIME_CODE.items():
        item = runtime_sources[label]
        _require(isinstance(item, dict) and Path(item.get("path", "")).resolve() == source.resolve() and
                 item.get("sha256") == expected_sha and source.is_file() and
                 sha256_file(source) == expected_sha,
                 "OWNER_RUNTIME_CODE_PATH_OR_SHA_MISMATCH")
    baseline_path, baseline_sha = STATIC_CONTRACT_BASELINE
    baseline_ref = binding.get("static_contract_baseline")
    _require(isinstance(baseline_ref, dict) and
             Path(baseline_ref.get("path", "")).resolve() == baseline_path.resolve() and
             baseline_ref.get("sha256") == baseline_sha and
             baseline_path.is_file() and not baseline_path.is_symlink() and
             sha256_file(baseline_path) == baseline_sha,
             "OWNER_STATIC_BASELINE_BINDING_MISMATCH")
    return binding

def _static_source_bindings(baseline: Mapping[str, Any],
                            revision: Mapping[str, Any]) -> dict[str, Any]:
    """Original complete role set plus this revision's actual maintenance closure."""
    sources = baseline.get("source_code_bindings")
    _require(isinstance(sources, dict) and bool(sources),
             "OWNER_STATIC_BASELINE_CODE_SET_MISSING")
    expected = dict(sources)
    for category in ("files", "accepted_helpers", "historical_owner_sources"):
        for index, item in enumerate(revision[category]):
            expected[f"knowledge_{category}_{index:02d}"] = item
    for name, item in revision["runtime_shared_components"].items():
        expected["knowledge_runtime_shared_" + name] = item
    for name, item in revision["official_components"].items():
        expected["knowledge_official_" + name] = item
    normalized = {}
    for name, item in expected.items():
        _require(isinstance(item, dict) and isinstance(item.get("path"), str),
                 "OWNER_STATIC_BASELINE_CODE_ENTRY_INVALID")
        normalized[name] = {**item, "path": str(Path(item["path"]).resolve())}
    return normalized


def _validate_bound_static_contract(*, contract: Mapping[str, Any],
                                   input_binding: Mapping[str, Any],
                                   owner_binding: Mapping[str, Any],
                                   release: Mapping[str, Any],
                                   revision: Mapping[str, Any],
                                   contract_path: Path, input_binding_path: Path,
                                   contract_sha256: str) -> None:
    """Path-aware port of original runtime_common.verify_static_contract:132-238.

    The fixed baseline is metadata, not a release or a source of market rows.
    Current paths come from the separately bound new owner execution; frozen
    calendar/fit/source/lineage expectations never come from the tested
    contract's own declarations. This is called again at the original candidate
    static-reader and authorizer seams via validate_owner_release.
    """
    baseline_path, baseline_sha = STATIC_CONTRACT_BASELINE
    _require(sha256_file(baseline_path) == baseline_sha,
             "OWNER_STATIC_BASELINE_SHA_MISMATCH")
    baseline = read_object(baseline_path, "static_contract_baseline")
    _require(input_binding.get("contract_path") == str(contract_path) and
             input_binding.get("contract_sha256") == contract_sha256,
             "CONTRACT_BINDING_HASH_OR_PATH_MISMATCH")
    input_ref = contract.get("input_binding")
    _require(isinstance(input_ref, dict) and input_ref.get("path") == str(input_binding_path),
             "CONTRACT_INPUT_BINDING_PATH_MISMATCH")
    inputs = contract.get("input_files")
    _require(isinstance(inputs, dict) and bool(inputs) and inputs == input_binding.get("input_files"),
             "CONTRACT_INPUT_FILE_MANIFEST_MISMATCH")
    _require("original_full_market_calendar" not in inputs,
             "UNSUPPORTED_RAW_FULL_MARKET_CALENDAR_BINDING")
    calendar = inputs.get("source_2023_eval_calendar")
    calendar_sha = "bf17fff8196f5019744bb44bbcfd1eee1224876760215910cefc019ffbe9b013"
    _require(isinstance(calendar, dict) and calendar.get("expected_sha256") == calendar_sha and
             type(calendar.get("expected_rows")) is int and calendar["expected_rows"] == 243,
             "SOURCE_2023_EVAL_CALENDAR_BINDING_MISMATCH")
    _require(isinstance(calendar.get("path"), str) and Path(calendar["path"]).name == "eval_calendar.csv.gz",
             "SOURCE_2023_EVAL_CALENDAR_PATH_MISMATCH")
    adapter = contract.get("calendar_adapter")
    expected_adapter = {
        "calendar_input_role": "source_2023_eval_calendar", "calendar_rows": 243,
        "first_global_session_id": 1233, "calendar_sha256": calendar_sha,
        "fixed_before_oof_score_parse": True,
        "raw_full_market_calendar_input_bound_or_read": False,
    }
    _require(isinstance(adapter, dict) and all(
        type(adapter.get(key)) is type(value) and adapter.get(key) == value
        for key, value in expected_adapter.items()),
        "SOURCE_2023_CALENDAR_ADAPTER_CONTRACT_MISMATCH")
    fit = contract.get("fit")
    _require(isinstance(fit, dict), "FROZEN_CANDIDATE_FIT_CONFIG_INVALID")
    source_params, candidate_params = fit.get("base_params_from_original_PLUS_PATH_contract"), fit.get("candidate_params")
    _require(isinstance(source_params, dict) and candidate_params == source_params and
             all(type(candidate_params.get(k)) is int and candidate_params[k] == 42
                 for k in ("seed", "data_random_seed", "feature_fraction_seed", "bagging_seed")) and
             fit.get("num_boost_round") == 200 and fit.get("parameter_delta") == {"num_boost_round": 200} and
             fit.get("candidate_fit_calls_max") == 1 and fit.get("control_fit_calls") == 0 and
             fit.get("control_prediction_calls") == 0,
             "FROZEN_CANDIDATE_FIT_CONFIG_INVALID")
    # Equality between two mutable dicts alone does not freeze parameters.
    _require(json.dumps(fit, sort_keys=True, allow_nan=False) ==
             json.dumps(baseline["fit"], sort_keys=True, allow_nan=False),
             "FROZEN_CANDIDATE_FIT_BASELINE_MISMATCH")

    scope = contract.get("scope_lock")
    _require(isinstance(scope, dict) and isinstance(scope.get("path"), str) and
             scope == release.get("scope_lock") and scope.get("path") == owner_binding.get("scope_lock_path"),
             "OWNER_SCOPE_LOCK_PATH_OR_RELEASE_MISMATCH")
    scope_path = Path(scope["path"])
    _require(scope_path.is_file() and not scope_path.is_symlink() and
             sha256_file(scope_path) == _hash(scope.get("sha256"), "SCOPE_LOCK_SHA_INVALID"),
             "SCOPE_LOCK_SHA_MISMATCH")
    # New roots/ids may change; safety/calendar/fit/resource scope may not.
    baseline_scope_ref = baseline["scope_lock"]
    baseline_scope_path = Path(baseline_scope_ref["path"])
    _require(sha256_file(baseline_scope_path) == baseline_scope_ref["sha256"],
             "OWNER_STATIC_BASELINE_SCOPE_SHA_MISMATCH")
    frozen_scope = read_object(baseline_scope_path, "baseline_scope_lock")
    actual_scope = read_object(scope_path, "scope_lock")
    scope_keys = ("research_only", "production_allowed", "buy_gate_updated", "orders_sent",
                  "resource_caps", "calendar_contract", "fit_contract", "forbidden")
    _require(all(key in actual_scope and key in frozen_scope and
                 json.dumps(actual_scope[key], sort_keys=True, allow_nan=False) ==
                 json.dumps(frozen_scope[key], sort_keys=True, allow_nan=False)
                 for key in scope_keys), "OWNER_SCOPE_FROZEN_SEMANTICS_MISMATCH")

    sources = contract.get("source_code_bindings")
    _require(isinstance(sources, dict) and sources == input_binding.get("source_code_bindings"),
             "CONTRACT_BINDING_CODE_SET_MISMATCH")
    _require(sources == _static_source_bindings(baseline, revision),
             "OWNER_COMPLETE_SOURCE_BINDING_SET_MISMATCH")
    for name, item in sources.items():
        if name == "native_validation_bindings":
            continue  # only the exact baseline entry can reach this exemption
        path = Path(item["path"])
        expected_source_sha = _hash(item.get("sha256"), f"SOURCE_CODE_SHA_INVALID:{name}")
        _require(path.is_file() and not path.is_symlink(),
                 f"SOURCE_CODE_MISSING_OR_SYMLINK:{name}")
        migration = next((entry for entry in revision.get("historical_source_migrations", [])
                          if entry.get("source_path") == str(path.resolve())), None)
        if migration is not None:
            _require(expected_source_sha == migration.get("pinned_sha256") and
                     migration.get("original_bytes_status") == "CANNOT_CONFIRM" and
                     sha256_file(path) == migration.get("observed_current_sha256") and
                     migration.get("replacement_path") ==
                     revision.get("runtime_shared_components", {}).get("resource_monitor", {}).get("path") and
                     migration.get("replacement_sha256") ==
                     revision.get("runtime_shared_components", {}).get("resource_monitor", {}).get("sha256"),
                     f"HISTORICAL_SOURCE_MIGRATION_BINDING_MISMATCH:{name}")
        else:
            _require(sha256_file(path) == expected_source_sha,
                     f"SOURCE_CODE_SHA_MISMATCH:{name}")

    artifacts = owner_binding.get("prefit_artifacts")
    _require(isinstance(artifacts, dict) and isinstance(owner_binding.get("prefit_root"), str),
             "PREFIT_RETRY_OUTPUT_PATH_BINDING_MISMATCH")
    expected_paths = {"root": str(Path(owner_binding["prefit_root"]).resolve())}
    for out_key, artifact_key in (("result_receipt", "prefit_receipt"), ("run_receipt", "prefit_run_receipt"),
                                  ("resource_trace", "prefit_resource_trace"), ("worker_status", "prefit_worker_status")):
        item = artifacts.get(artifact_key)
        _require(isinstance(item, dict) and isinstance(item.get("path"), str),
                 "PREFIT_RETRY_OUTPUT_PATH_BINDING_MISMATCH")
        expected_paths[out_key] = str(Path(item["path"]).resolve())
    expected_paths["metadata_preflight"] = str(Path(expected_paths["root"]) / "METADATA_PREFLIGHT.json")
    _require(contract.get("prefit_output_paths") == expected_paths and
             contract.get("prefit_execution_id") == owner_binding.get("prefit_execution_id"),
             "PREFIT_RETRY_OUTPUT_PATH_BINDING_MISMATCH")

    lineage = contract.get("prefit_retry_lineage")
    _require(isinstance(lineage, dict), "PREFIT_RETRY_PRIOR_FAILURE_COUNT_MISMATCH")
    priors = lineage.get("prior_failures")
    baseline_lineage = baseline["prefit_retry_lineage"]
    frozen_priors = baseline_lineage["prior_failures"]
    _require(isinstance(priors, list) and len(priors) == len(frozen_priors) == 2,
             "PREFIT_RETRY_PRIOR_FAILURE_COUNT_MISMATCH")
    path_fields = (("failure_receipt", "prior_failure_receipt_paths"),
                   ("run_receipt", "prior_attempt_run_receipt_paths"),
                   ("resource_trace", "prior_attempt_resource_trace_paths"))
    for kind, binding_key in path_fields:
        paths = owner_binding.get(binding_key)
        _require(isinstance(paths, list) and len(paths) == 2 and all(isinstance(p, str) for p in paths),
                 "OWNER_PRIOR_PATH_SET_MISMATCH")
    for i, (prior, frozen) in enumerate(zip(priors, frozen_priors)):
        _require(isinstance(prior, dict) and prior.get("execution_id") == frozen["execution_id"],
                 "PREFIT_RETRY_PRIOR_EXECUTION_ORDER_MISMATCH")
        for kind, binding_key in path_fields:
            label = kind.upper()
            _require(prior.get(kind + "_path") == owner_binding[binding_key][i],
                     f"OWNER_PRIOR_PATH_BINDING_MISMATCH:{kind}")
            path = Path(prior[kind + "_path"])
            _require(prior.get(kind + "_sha256") == frozen[kind + "_sha256"] and
                     path.is_file() and not path.is_symlink() and
                     sha256_file(path) == prior[kind + "_sha256"],
                     f"PREFIT_RETRY_PRIOR_{label}_BINDING_MISMATCH")
        _hash(prior.get("terminal_event_sha256"), "PREFIT_RETRY_PRIOR_TERMINAL_EVENT_SHA_REQUIRED")
        _require(prior["terminal_event_sha256"] == frozen["terminal_event_sha256"] and
                 prior.get("terminal_status") == frozen.get("terminal_status"),
                 "OWNER_PRIOR_TERMINAL_BASELINE_MISMATCH")
    latest = priors[-1]
    _require(lineage.get("retry_of_execution_id") == latest["execution_id"] and
             lineage.get("prior_failure_receipt_path") == latest["failure_receipt_path"] and
             lineage.get("prior_failure_receipt_sha256") == latest["failure_receipt_sha256"] and
             lineage.get("prior_terminal_event_sha256") == latest["terminal_event_sha256"],
             "PREFIT_RETRY_DIRECT_LINEAGE_ALIAS_MISMATCH")
    _require(all(type(lineage.get(key)) is type(baseline_lineage[key]) and
                 lineage.get(key) == baseline_lineage[key] for key in (
                     "retry_count", "new_execution_requires_fresh_parent_prefit_release",
                     "old_terminal_artifacts_are_immutable")),
             "OWNER_PRIOR_LINEAGE_POLICY_MISMATCH")


def validate_owner_release(*, binding_path: Path, release_path: Path,
                           knowledge_binding_path: Path, knowledge_binding_sha256: str,
                           operation: str, fixture_root: Path | None = None,
                           review_ref_path: Path | None = None,
                           revision_binding_path: Path = REVISION_BINDING_PATH) -> dict[str, Any]:
    """Verify one source binding and its separately issued permission document.

    ``fixture_root`` exists only for in-process tests. It is never accepted by
    the production CLI; test fixtures must contain the explicit synthetic-only
    marker and use a temporary registry/data-free callback.
    """
    if operation not in {"run", "readback", "evaluation_readback", "reconcile_result", "append_review"}:
        raise OwnerReleaseRejected("OWNER_OPERATION_NOT_SUPPORTED")
    revision = validate_revision_binding(revision_binding_path)
    test_root = Path(fixture_root).resolve(strict=True) if fixture_root is not None else None
    resolved_inputs = [Path(binding_path).resolve(strict=True), Path(release_path).resolve(strict=True),
                       Path(knowledge_binding_path).resolve(strict=True)]
    if test_root is None:
        _require(all(_under(path, RESEARCH_ROOT) for path in resolved_inputs),
                 "OWNER_NEW_BINDING_OUTSIDE_RESEARCH_ROOT")
    else:
        _require(all(_under(path, test_root) for path in resolved_inputs),
                 "OWNER_FIXTURE_INPUT_OUTSIDE_TEMP_ROOT")
    binding_path, release_path, knowledge_binding_path = resolved_inputs
    binding = read_object(binding_path, "execution_binding")
    release = read_object(release_path, "parent_release")
    binding_sha = sha256_file(binding_path)
    knowledge_sha = _hash(knowledge_binding_sha256, "OWNER_KNOWLEDGE_BINDING_SHA_INVALID")
    _require(binding.get("schema") == "f5.training_owner_execution_binding.v1" and
             binding.get("status") == "NEW_EXECUTION_BINDING_READY",
             "OWNER_EXECUTION_BINDING_NOT_READY")
    _require(release.get("schema") == "f5.training_owner_release.v1" and
             release.get("active") is True, "OWNER_PARENT_RELEASE_NOT_ACTIVE")
    if test_root is not None:
        _require(release.get("synthetic_fixture_only") is True and
                 release.get("real_payload_access") is False and
                 release.get("formal_registry_path") is False,
                 "OWNER_TEST_RELEASE_NOT_SYNTHETIC_ONLY")
    else:
        _require(release.get("synthetic_fixture_only") is not True,
                 "OWNER_SYNTHETIC_RELEASE_CANNOT_ENTER_PRODUCTION_CLI")
        _require(release.get("source_binding_path") == str(binding_path) and
                 release.get("source_binding_sha256") == binding_sha,
                 "OWNER_PARENT_RELEASE_BINDING_MISMATCH")
    _require(release.get("source_binding_path") == str(binding_path) and
             release.get("source_binding_sha256") == binding_sha,
             "OWNER_PARENT_RELEASE_BINDING_MISMATCH")
    _require(binding.get("owner_revision_binding_sha256") == sha256_file(revision_binding_path),
             "OWNER_REVISION_BINDING_SHA_MISMATCH")
    _require(binding.get("knowledge_binding_path") == str(knowledge_binding_path) and
             binding.get("knowledge_binding_sha256") == knowledge_sha and
             release.get("knowledge_binding_path") == str(knowledge_binding_path) and
             release.get("knowledge_binding_sha256") == knowledge_sha,
             "OWNER_KNOWLEDGE_BINDING_NOT_RELEASE_BOUND")
    _require(binding.get("execution_id") == release.get("execution_id") and
             binding.get("experiment_id") == release.get("experiment_id") and
             binding.get("route_id") == release.get("route_id") and
             binding.get("track_id") == release.get("track_id"),
             "OWNER_BINDING_RELEASE_IDENTITY_MISMATCH")
    execution_id = binding.get("execution_id")
    _require(isinstance(execution_id, str) and execution_id not in OLD_CLOSED_EXECUTION_IDS,
             "OWNER_CLOSED_META2023_EXECUTION_REJECTED")
    _require("CANDIDATE_BEFORE_FIT_RECOVERY_02" not in str(execution_id),
             "OWNER_CLOSED_META2023_EXECUTION_REJECTED")
    _require(binding.get("route_id") != "F5_META2023_BASEPLUS64_R1_20260923",
             "OWNER_CLOSED_META2023_ROUTE_REJECTED")
    _require(release.get("route_id") == binding.get("route_id") and
             release.get("track_id") == binding.get("track_id"),
             "OWNER_PARENT_RELEASE_ROUTE_MISMATCH")

    contract_path = Path(binding.get("contract_path", "")).resolve(strict=True)
    input_binding_path = Path(binding.get("input_binding_path", "")).resolve(strict=True)
    contract_raw = _regular_metadata(contract_path, "contract")
    input_raw = _regular_metadata(input_binding_path, "input_binding")
    contract_sha, input_sha = _sha(contract_raw), _sha(input_raw)
    _require(contract_sha == binding.get("contract_sha256") == release.get("contract_sha256"),
             "OWNER_CONTRACT_BINDING_SHA_MISMATCH")
    _require(input_sha == binding.get("input_binding_sha256") == release.get("input_binding_sha256"),
             "OWNER_INPUT_BINDING_SHA_MISMATCH")
    contract = json.loads(contract_raw.decode("utf-8"))
    input_binding = json.loads(input_raw.decode("utf-8"))
    _require(isinstance(contract, dict) and isinstance(input_binding, dict),
             "CONTRACT_AND_BINDING_MUST_BE_OBJECTS")
    _require(contract.get("candidate_execution_id") == binding.get("owner_execution_template_id") and
             contract.get("owner_execution_template_id") == binding.get("owner_execution_template_id") and
             contract.get("experiment_id") == binding.get("experiment_id") and
             contract.get("route_id") == binding.get("route_id") and
             contract.get("track_id") == binding.get("track_id"),
             "OWNER_CONTRACT_TEMPLATE_IDENTITY_MISMATCH")
    _require(contract.get("official_registry_path") == binding.get("official_registry_path"),
             "OWNER_REGISTRY_PATH_NOT_CONTRACT_BOUND")
    _require(binding.get("official_registry_path") == release.get("official_registry_path"),
             "OWNER_REGISTRY_PATH_NOT_RELEASE_BOUND")
    lifecycle = contract.get("official_lifecycle")
    _require(isinstance(lifecycle, dict), "OWNER_OFFICIAL_LIFECYCLE_BINDING_MISSING")
    for name, (source, expected_sha) in OFFICIAL_COMPONENTS.items():
        item = lifecycle.get(name)
        _require(isinstance(item, dict) and Path(item.get("path", "")).resolve() == source.resolve() and
                 item.get("sha256") == expected_sha,
                 "OWNER_CONTRACT_OFFICIAL_COMPONENT_PATH_OR_SHA_MISMATCH")
    runtime_bindings = contract.get("source_code_bindings")
    _require(isinstance(runtime_bindings, dict) and set(PINNED_RUNTIME_CODE).issubset(runtime_bindings),
             "OWNER_CONTRACT_DYNAMIC_SOURCE_SET_INVALID")
    for name, (source, expected_sha) in PINNED_RUNTIME_CODE.items():
        item = runtime_bindings[name]
        _require(isinstance(item, dict) and Path(item.get("path", "")).resolve() == source.resolve() and
                 item.get("sha256") == expected_sha,
                 "OWNER_CONTRACT_DYNAMIC_SOURCE_PATH_OR_SHA_MISMATCH")
    if operation == "run":
        _validate_bound_static_contract(
            contract=contract, input_binding=input_binding, owner_binding=binding,
            release=release, revision=revision, contract_path=contract_path,
            input_binding_path=input_binding_path, contract_sha256=contract_sha,
        )
    for key in ("prefit_receipt", "prefit_run_receipt", "prefit_resource_trace", "prefit_worker_status"):
        item = (binding.get("prefit_artifacts") or {}).get(key)
        release_item = (release.get("prefit_artifacts") or {}).get(key)
        _require(isinstance(item, dict) and isinstance(release_item, dict) and
                 item == release_item and isinstance(item.get("path"), str),
                 f"OWNER_PREFIT_ARTIFACT_BINDING_MISSING:{key}")
        if operation == "run":
            path = Path(item["path"])
            _require(path.is_file() and not path.is_symlink() and
                     sha256_file(path) == _hash(item.get("sha256"), f"OWNER_PREFIT_ARTIFACT_SHA_INVALID:{key}"),
                     f"OWNER_PREFIT_ARTIFACT_DRIFT:{key}")
    if operation == "run":
        prefit_docs = {
            key: read_object(Path((binding["prefit_artifacts"][key])["path"]), key)
            for key in ("prefit_receipt", "prefit_run_receipt", "prefit_resource_trace", "prefit_worker_status")
        }
        prefit_result = prefit_docs["prefit_receipt"]
        _require(prefit_result.get("fit_calls") == 0 and prefit_result.get("predict_calls") == 0 and
                 prefit_result.get("control_fit_calls") == 0 and
                 prefit_result.get("control_prediction_calls") == 0 and
                 prefit_result.get("research_only") is True and
                 prefit_result.get("production_allowed") is False and
                 prefit_result.get("buy_gate_updated") is False and
                 prefit_result.get("orders_sent") is False,
                 "OWNER_PREFIT_AUTHORITY_NOT_NO_FIT")
        prefit_run = prefit_docs["prefit_run_receipt"]
        prefit_worker = prefit_docs["prefit_worker_status"]
        prefit_trace = prefit_docs["prefit_resource_trace"]
        _require(prefit_run.get("execution_id") == binding.get("prefit_execution_id") and
                 prefit_run.get("fit_calls") == 0 and prefit_run.get("predict_calls") == 0 and
                 prefit_run.get("prefit_result_receipt_sha256") == binding["prefit_artifacts"]["prefit_receipt"]["sha256"] and
                 prefit_run.get("prefit_worker_status_sha256") == binding["prefit_artifacts"]["prefit_worker_status"]["sha256"] and
                 prefit_worker.get("status") == "COMPLETED" and
                 prefit_worker.get("execution_id") == binding.get("prefit_execution_id") and
                 prefit_worker.get("fit_call_entered") is False and
                 prefit_worker.get("fit_returned") is False and
                 prefit_worker.get("predict_calls") == 0 and
                 prefit_trace.get("terminal_reason") is None and
                 prefit_trace.get("worker_exitcode") == 0,
                 "OWNER_PREFIT_RUN_LINEAGE_INVALID")

    _require(binding.get("execution_kind") == release.get("execution_kind"),
             "OWNER_EXECUTION_KIND_MISMATCH")
    _require(release.get("no_retry_after_fit_entry") is True and
             release.get("automatic_retry") is False and release.get("refund_debit") is False,
             "OWNER_RETRY_OR_DEBIT_POLICY_INVALID")
    budget = release.get("budget")
    _require(isinstance(budget, dict) and
             type(budget.get("prior_debits")) is int and budget["prior_debits"] >= 0 and
             type(budget.get("max_total_guard_debits")) is int and
             budget["max_total_guard_debits"] >= budget["prior_debits"] and
             budget.get("new_attempt_debit") == 1,
             "OWNER_BUDGET_RELEASE_INVALID")
    limits = release.get("resource_limits")
    _require(isinstance(limits, dict) and
             int(limits.get("wall_seconds_max", 0)) == 600 and
             int(limits.get("aggregate_rss_bytes_max", 0)) == 3221225472 and
             int(limits.get("threads", 0)) == 4,
             "OWNER_RESOURCE_RELEASE_INVALID")
    fit_scope = release.get("fit_scope")
    _require(isinstance(fit_scope, dict) and
             fit_scope.get("candidate_fit_calls") == 1 and
             fit_scope.get("control_fit_calls") == 0 and
             fit_scope.get("control_prediction_calls") == 0,
             "OWNER_FIT_SCOPE_RELEASE_INVALID")
    _require(isinstance(release.get("parent_authorization_id"), str) and
             bool(release["parent_authorization_id"].strip()), "OWNER_PARENT_AUTHORIZATION_ID_MISSING")
    _require(isinstance(release.get("reviewer_agent"), str) and bool(release["reviewer_agent"]) and
             release.get("reviewer_verdict") == "PASS" and
             release.get("independent_reviewer_pass") is True,
             "OWNER_RELEASE_REVIEW_IDENTITY_INVALID")
    _hash(release.get("reviewer_receipt_sha256"), "OWNER_RELEASE_REVIEW_SHA_INVALID")

    scopes = release.get("metadata_scopes")
    _require(isinstance(scopes, dict), "OWNER_METADATA_SCOPES_MISSING")
    if operation == "run":
        _require(release.get("candidate_fit_allowed") is True and
                 release.get("execution_kind") == "REAL_FIT" and
                 scopes.get("knowledge_read") is True and
                 scopes.get("registry_read") is True and
                 scopes.get("registry_append") is True,
                 "OWNER_FIT_OR_METADATA_SCOPE_NOT_AUTHORIZED")
    elif operation == "readback":
        _require(scopes.get("knowledge_read") is True and scopes.get("registry_read") is True,
                 "OWNER_METADATA_READ_NOT_AUTHORIZED")
    elif operation == "evaluation_readback":
        # A distinct, explicit read grant. Ordinary linkage readback is not
        # permission to stream model/score/evaluation bytes.
        sources = {item["path"] for item in revision["files"]}
        _require(all(str(OWNER_ROOT / name) in sources for name in
                     ("evaluation_readback.py", "evaluation_readback_io.py")),
                 "OWNER_EVALUATION_READER_NOT_REVISION_BOUND")
        from evaluation_readback import authorized_paths
        authorized_paths(binding, release)
    elif operation == "reconcile_result":
        _require(scopes.get("knowledge_read") is True and scopes.get("registry_read") is True and
                 scopes.get("result_append") is True,
                 "OWNER_RESULT_RECONCILE_NOT_AUTHORIZED")
    else:
        _require(scopes.get("knowledge_read") is True and scopes.get("registry_read") is True and
                 scopes.get("review_append") is True,
                 "OWNER_REVIEW_APPEND_NOT_AUTHORIZED")
        _require(review_ref_path is not None, "OWNER_REVIEW_REF_REQUIRED")
        review_path = Path(review_ref_path).resolve(strict=True)
        knowledge_root = knowledge_binding_path.parent.resolve(strict=True)
        _require(_under(review_path, knowledge_root), "OWNER_REVIEW_REF_OUTSIDE_KNOWLEDGE_ROOT")
        relative_review_path = review_path.relative_to(knowledge_root).as_posix()
        review_ref = scopes.get("review_ref")
        _require(isinstance(review_ref, dict) and review_ref.get("path") == relative_review_path and
                 review_ref.get("sha256") == sha256_file(review_path),
                 "OWNER_REVIEW_REF_NOT_AUTHORIZATION_BOUND")

    if operation == "run":
        registry = Path(binding["official_registry_path"])
        _require(registry.is_file() and not registry.is_symlink(), "OWNER_OFFICIAL_REGISTRY_MISSING")
        before_sha = _hash(release.get("official_registry_sha256_before_start"),
                           "OWNER_RELEASE_REGISTRY_SHA_MISSING")
        _require(sha256_file(registry) == before_sha, "OWNER_RELEASE_REGISTRY_SNAPSHOT_MISMATCH")
        try:
            raw_events = registry.read_bytes().splitlines()
            events = [json.loads(line.decode("utf-8")) for line in raw_events if line.strip()]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OwnerReleaseRejected("OWNER_RELEASE_REGISTRY_METADATA_INVALID") from exc
        same_experiment_starts = [event for event in events
                                  if event.get("experiment_id") == binding.get("experiment_id")
                                  and event.get("event_type") == "RUN_STARTED"]
        observed_debits = sum(int((event.get("deterministic_metrics") or {}).get("real_fit_budget_debit") or 0)
                              for event in same_experiment_starts)
        _require(observed_debits == budget["prior_debits"], "OWNER_RELEASE_PRIOR_DEBIT_SNAPSHOT_MISMATCH")
        _require(not any(event.get("execution_id") == execution_id for event in events),
                 "OWNER_EXECUTION_ID_ALREADY_REGISTERED")
        output_dir = Path(binding.get("output_dir", ""))
        _require(not output_dir.exists(), "OWNER_OUTPUT_PATH_ALREADY_EXISTS_NO_REENTRY")

    return {
        "binding": binding,
        "release": release,
        "contract": contract,
        "contract_sha256": contract_sha,
        "input_binding_sha256": input_sha,
        "binding_sha256": binding_sha,
        "revision_binding": revision,
        "parent_authorization_id": release["parent_authorization_id"],
        "max_real_fit_debits": budget["max_total_guard_debits"],
        "resource_limits": limits,
        "operation": operation,
    }
