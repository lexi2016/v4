"""Bounded daily writes inside the existing V4 owners.

The policy supplies reviewed per-output ceilings. The owner supplies a verified
input scope. Plans are built automatically and retain exact source identities.
This module never creates a producer, changes a reservation, or writes data.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import argparse
from pathlib import Path


SCHEMA = "v4.daily_incremental_capacity.v1"
PLAN_SCHEMA = "v4.daily_incremental_write_plan.v1"
PHASES = {"qfq", "daily_product", "top200"}
_PLAN = ContextVar("v4_daily_incremental_write_plan", default=None)


class CapacityProofError(ValueError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return sha256(encoded(value)).hexdigest()


def enabled(policy):
    return bool((policy.get("governance", {}).get("incremental_capacity") or {}).get("enabled"))


def file_reference(path):
    path = Path(path)
    if (not path.is_absolute() or path.is_symlink()
            or path.resolve(strict=True) != path or not path.is_file()):
        raise CapacityProofError("CAPACITY_INPUT_NOT_REGULAR")
    before = path.stat()
    value = sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise CapacityProofError("CAPACITY_INPUT_MOVED")
    return dict(path=str(path), sha256=value, size=after.st_size)


def check_inputs(references):
    if not references or len({ref["path"] for ref in references}) != len(references):
        raise CapacityProofError("CAPACITY_INPUT_SCOPE_INVALID")
    for reference in references:
        if file_reference(reference["path"]) != reference:
            raise CapacityProofError("CAPACITY_INPUT_CHANGED")


def phase_limits(policy, phase):
    config = policy.get("governance", {}).get("incremental_capacity") or {}
    if config.get("schema") != SCHEMA or config.get("enabled") is not True:
        raise CapacityProofError("INCREMENTAL_CAPACITY_POLICY_NOT_ENABLED")
    if phase not in PHASES or set(config.get("phases", {})) != PHASES:
        raise CapacityProofError("INCREMENTAL_CAPACITY_PHASES_REQUIRED")
    reference = config.get("reviewed_limits")
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not isinstance(reference["sha256"], str) or len(reference["sha256"]) != 64):
        raise CapacityProofError("INCREMENTAL_LIMIT_REVIEW_REQUIRED")
    checked = file_reference(reference["path"])
    if checked["sha256"] != reference["sha256"]:
        raise CapacityProofError("INCREMENTAL_LIMIT_REVIEW_CHANGED")
    review = json.loads(Path(reference["path"]).read_bytes())
    limits = config["phases"][phase]
    fields = {"fixed_bytes", "per_symbol_bytes", "per_changed_row_bytes", "max_file_bytes", "max_symbols",
              "max_changed_rows", "max_revised_symbols"}
    if (set(limits) != fields or any(type(value) is not int or value < 0 for value in limits.values())
            or limits["fixed_bytes"] <= 0 or limits["max_file_bytes"] <= 0):
        raise CapacityProofError("INCREMENTAL_LIMITS_INVALID")
    if (review.get("schema") != "v4.daily_incremental_limits_review.v1"
            or review.get("status") != "PASS" or review.get("phase_limits") != config["phases"]):
        raise CapacityProofError("INCREMENTAL_LIMIT_REVIEW_CONFLICT")
    return limits


def build_plan(policy, phase, *, target, scope, source_identity, references,
               changed_rows, revised_symbols=0, classifications=None):
    """One fixed, nonincreasing claim bound from a verified automatic scope.

    Byte ceilings are output contracts enforced by the serializers. A historical
    average, current free space, or operator-written per-date proof is not used.
    """
    limits = phase_limits(policy, phase)
    if (type(target) is not int or len(str(target)) != 8 or not scope
            or list(scope) != sorted(set(scope)) or not source_identity
            or type(changed_rows) is not int or changed_rows < 0
            or type(revised_symbols) is not int or revised_symbols < 0):
        raise CapacityProofError("INCREMENTAL_SCOPE_INVALID")
    if (len(scope) > limits["max_symbols"] or changed_rows > limits["max_changed_rows"]
            or revised_symbols > limits["max_revised_symbols"]):
        raise CapacityProofError("INCREMENTAL_SCOPE_EXCEEDED_FULL_REBUILD_REQUIRED")
    if classifications and any(value in {"RULE_REVISION", "NEW_OR_MISSING_HISTORY"}
                               for value in classifications.values()):
        raise CapacityProofError("INCREMENTAL_SCOPE_EXCEEDED_FULL_REBUILD_REQUIRED")
    review_reference = file_reference(policy["governance"]["incremental_capacity"]["reviewed_limits"]["path"])
    references = list({ref["path"]: ref for ref in [*references, review_reference]}.values())
    check_inputs(references)
    predicted = (limits["fixed_bytes"] + len(scope) * limits["per_symbol_bytes"]
                 + changed_rows * limits["per_changed_row_bytes"])
    if predicted <= 0 or (phase == "qfq" and limits["fixed_bytes"] < 64 * 1024**2):
        raise CapacityProofError("INCREMENTAL_PEAK_NOT_PROVEN")
    value = dict(schema=PLAN_SCHEMA, phase=phase, target=target, scope=list(scope),
                 source_identity=source_identity, references=references,
                 changed_rows=changed_rows, revised_symbols=revised_symbols,
                 classifications=classifications or {}, limits=limits,
                 predicted_bytes=predicted, policy_sha256=digest(policy))
    return {**value, "plan_sha256": digest(value)}


def validate_plan(plan, *, policy=None, phase=None, target=None):
    if not isinstance(plan, dict):
        raise CapacityProofError("INCREMENTAL_PLAN_REQUIRED")
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if plan.get("schema") != PLAN_SCHEMA or digest(payload) != plan.get("plan_sha256"):
        raise CapacityProofError("INCREMENTAL_PLAN_DIGEST_CONFLICT")
    if phase is not None and plan["phase"] != phase:
        raise CapacityProofError("INCREMENTAL_PHASE_CONFLICT")
    if target is not None and plan["target"] != target:
        raise CapacityProofError("INCREMENTAL_TARGET_CONFLICT")
    if policy is not None:
        if plan["policy_sha256"] != digest(policy) or plan["limits"] != phase_limits(policy, plan["phase"]):
            raise CapacityProofError("INCREMENTAL_PLAN_POLICY_CONFLICT")
    check_inputs(plan["references"])
    return plan


@contextmanager
def write_scope(plan):
    """Keep the same immutable plan at all existing owner write boundaries."""
    validate_plan(plan)
    current = _PLAN.get()
    if current is not None:
        if current != plan:
            raise CapacityProofError("NESTED_INCREMENTAL_PLAN_CONFLICT")
        yield current
        return
    token = _PLAN.set(plan)
    try:
        yield plan
    finally:
        _PLAN.reset(token)


def current_plan():
    return _PLAN.get()


def incoming_bytes(size):
    check_serialized_write(size)
    return ((size + 4095) // 4096) * 4096


def prepare_qfq_plan(module, policy, *, data_root, return_root, pointers, target, kwargs):
    """Use the original source builder once, then preclassify before QFQ claim.

    Input preparation has its own existing bounded input admission and adapters.
    A failed input operation retains that small reservation. No QFQ reservation
    is created when classification or a reviewed output bound is unavailable.
    """
    from ops import research_storage_governance as governance
    from ops import research_panel_delta as delta
    from ops import research_panel_logical as logical

    if kwargs.get("storage_layout", "arrow_blocks_v1") != "arrow_blocks_v1" or any(
            kwargs.get(name) is not None for name in
            ("history_extension", "tail_delta", "archive_additions", "same_asof_metadata_ref")):
        raise CapacityProofError("INCREMENTAL_SCOPE_EXCEEDED_FULL_REBUILD_REQUIRED")
    # Resolve caps before any bounded input work, so an unreviewed deployment
    # cannot create a new input attempt merely to discover missing limits.
    phase_limits(policy, "qfq")
    current = {role: Path(Path(path).read_text(encoding="utf-8-sig").strip())
               for role, path in pointers.items()}
    if set(current) != {"selector", "backtest"} or not all(logical.is_logical(path) for path in current.values()):
        raise CapacityProofError("INCREMENTAL_LOGICAL_BASELINE_REQUIRED")
    snapshot_path = module.input_path(data_root)
    driver, _ = module.authorities(kwargs["driver_path"], kwargs["formula_path"])
    if kwargs.get("refresh_inputs") is True and kwargs.get("checkpoint_resume") is None:
        from ops.research_panel_adjustment_inputs import prepare_snapshot
        from ops.research_panel_daily_source import build_cache_configuration

        receipt_root = Path(module.os.environ["V4_RESEARCH_PANEL_RECEIPT_ROOT"])
        with governance.input_preflight(tdx_root=kwargs["tdx_root"], receipt_root=receipt_root,
                                        target=target, operation="adjustment_snapshot") as input_claim:
            with governance.input_write_seams(input_claim), module.publication_lock(data_root):
                journal = Path(data_root) / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"
                module.recover_pair(journal, pointers)
                required = module.required_a_history(pointers)
                retained = module.selected_history_retention(module.accepted_history_retention(pointers), target=target)
                cache = build_cache_configuration(data_root=Path(data_root), tdx_root=kwargs["tdx_root"],
                                                 target=target, codes=list(required))
                prepare_snapshot(tdx_root=kwargs["tdx_root"], data_root=Path(data_root), target=target,
                                 driver=driver, required_start=required, force_refresh=False,
                                 retained_history=retained, research_cache_config_ref=cache)
    current = {role: Path(Path(path).read_text(encoding="utf-8-sig").strip())
               for role, path in pointers.items()}
    if not all(logical.is_logical(path) for path in current.values()):
        raise CapacityProofError("INCREMENTAL_LOGICAL_BASELINE_REQUIRED")
    snapshot = module.load_snapshot(snapshot_path, target)
    contracts = {role: module.panel_contract(path) for role, path in current.items()}
    old_refs = [value["adjustment_snapshot"] for value in contracts.values()]
    if old_refs[0] != old_refs[1]:
        raise CapacityProofError("INCREMENTAL_PAIRED_SNAPSHOT_CONFLICT")
    old_snapshot_path = module._source(old_refs[0], owner="incremental baseline snapshot")
    old_snapshot = json.loads(old_snapshot_path.read_bytes())
    source_semantics = dict(driver_sha256=module.sha(kwargs["driver_path"]),
                            formula_sha256=module.sha(kwargs["formula_path"]),
                            field_contract_sha256=module.sha(kwargs["contract_csv"]),
                            user_formula_sha256=module.USER_FORMULA_SHA)
    refs = [file_reference(path) for path in [*pointers.values(), *current.values(),
            snapshot_path, old_snapshot_path, *[kwargs[key] for key in ("driver_path", "formula_path", "contract_csv")]]]
    refs = list({ref["path"]: ref for ref in refs}.values())
    schemas = {role: logical.LogicalFile(path).schema_arrow for role, path in current.items()}
    codes = sorted(snapshot["symbols"])
    classifications = {}
    row_counts = {}
    classification_dependencies = {}
    changed_rows = 0
    baseline_hashes = {role:module.sha(path) for role,path in current.items()}
    c = dict(snapshot=snapshot, target=target, driver=driver, run_dir=Path(return_root),
             currents=current, contracts=contracts, baseline_hashes=baseline_hashes)
    # Read one existing bucket at a time, not a second full-market panel.
    for bucket in range(32):
        members = [code for code in codes if module._bucket(code) == bucket]
        if not members:
            continue
        frames, _ = delta._read_delta_bucket(vars(module), current, {}, bucket, members, schemas)
        values = delta.classify_delta_scope(vars(module), c, frames, old_snapshot, schemas,
                                           source_semantics, members)
        for code, item in values.items():
            classifications[code] = item["kind"]
            row_counts[code] = item["changed_rows"]
            classification_dependencies[code] = item["classification_sha256"]
            changed_rows += item["changed_rows"]
    check_inputs(refs)
    revised = sum(value not in {"APPEND", "UNCHANGED"} for value in classifications.values())
    return build_plan(policy, "qfq", target=target, scope=codes,
                      source_identity=dict(snapshot_sha256=module.sha(snapshot_path),
                                           baseline=baseline_hashes,
                                           source_semantics=source_semantics, changed_rows_by_symbol=row_counts,
                                           classification_dependencies=classification_dependencies), references=refs,
                      changed_rows=changed_rows, revised_symbols=revised,
                      classifications=classifications)


def product_plan(policy, context, phase, *, symbols=None, history_dates=()):
    """Automatically count the exact dated Reader scope before output admission."""
    if history_dates:
        raise CapacityProofError("DAILY_HISTORY_BOOTSTRAP_REQUIRES_EXPLICIT_ADMISSION")
    require_writer_coverage(phase)
    context.unchanged()
    selected = sorted(symbols if symbols is not None else context.scope)
    if not set(selected) <= set(context.scope):
        raise CapacityProofError("INCREMENTAL_PRODUCT_SCOPE_CONFLICT")
    # Existing Reader supplies only this symbol's bound date window. No output
    # or label computation happens during the count.
    rows = sum(len(context.read(symbol)[0]) for symbol in selected)
    references = [file_reference(Path(ref["path"])) for ref in
                  (context.receipt_ref, context.snapshot_ref, context.config_ref, context.reader_ref)]
    references = list({ref["path"]: ref for ref in references}.values())
    context.unchanged()
    return build_plan(policy, phase, target=context.target, scope=selected,
                      source_identity=context.identity, references=references,
                      changed_rows=rows)


def check_serialized_write(size, *, plan=None):
    plan = current_plan() if plan is None else plan
    if plan is None:
        return
    if type(size) is not int or size < 0 or size > plan["limits"]["max_file_bytes"]:
        raise CapacityProofError("INCREMENTAL_SINGLE_WRITE_BOUND_EXCEEDED")


def ordinary_resident_bytes(governance, config, state):
    """Same roots and inode deduplication as Claim.begin, under the caller lock."""
    roots = set(config["accounting_roots"].get("ordinary", []))
    roots.update(state.get("resident_baseline_paths") or [])
    roots.update(governance.ordinary_resident_paths(config))
    for row in state["tasks"].values():
        if row["category"] == "ordinary":
            roots.update(row.get("billing_paths", []))
            # A crash before checkpoint may leave a new owned generation absent
            # from billing_paths. Preserve its recorded absence boundary.
            for root, before in row.get("initial_children", {}).items():
                directory = governance.safe_path(root)
                roots.update(str(path) for path in directory.iterdir() if path.name not in before)
    seen = set()
    return sum(governance.billing_bytes(path, seen=seen)
               for path in governance.unique_roots(roots) if path.exists())


def maximum_phase_bytes(policy):
    result = {}
    for phase in sorted(PHASES):
        value = phase_limits(policy, phase)
        result[phase] = (value["fixed_bytes"] + value["max_symbols"] * value["per_symbol_bytes"]
                         + value["max_changed_rows"] * value["per_changed_row_bytes"])
    return result


# This candidate has not yet changed all product subprocess serializers. Keep
# that fact executable: a review JSON or low observed sample cannot waive it.
# Instrumentation is a code map, not independent end-to-end acceptance.
INSTRUMENTED_WRITER_PHASES = frozenset({"qfq"})
ACCEPTED_WRITER_PHASES = frozenset()


def require_writer_coverage(phase):
    if phase not in INSTRUMENTED_WRITER_PHASES:
        raise CapacityProofError("INCREMENTAL_PRODUCT_WRITER_COVERAGE_NOT_PROVEN:" + phase)


def locked_runtime_probe(policy, *, tdx_root):
    """Read-only probe. Caller MUST hold role, pool-writer and registry locks.

    Does not reacquire Registry.transaction, mkdir, create a claim or persist a
    receipt. Frozen registry bytes are checked before and after the root walk.
    """
    from ops import research_storage_governance as governance
    config = governance.configuration(policy)
    if config is None:
        raise CapacityProofError("GOVERNANCE_REQUIRED")
    registry = governance.Registry(config, policy["data_root"])
    before = file_reference(registry.path)
    state = registry.read()
    if any(row["state"] in {"RUNNING", "VALIDATING"} for row in state["tasks"].values()):
        raise CapacityProofError("ACTIVE_EXECUTOR_OR_UNRECONCILED_RUNNING_ROW")
    resident = ordinary_resident_bytes(governance, config, state)
    peaks = maximum_phase_bytes(policy)
    peaks["input"] = governance.input_forecast(tdx_root)["predicted_bytes"]
    after = file_reference(registry.path)
    if before != after:
        raise CapacityProofError("LOCKED_REGISTRY_CHANGED_DURING_PROBE")
    unproven = sorted(PHASES - ACCEPTED_WRITER_PHASES)
    return dict(schema="v4.daily_capacity_locked_probe.v1",
                registry_sha256=before["sha256"], policy_sha256=digest(policy),
                category_used_bytes=resident, phase_peak_bytes=peaks,
                predicted_peak_bytes=sum(peaks.values()),
                eligibility="CANNOT_CONFIRM" if unproven else "PASS",
                unproven_writer_phases=unproven,
                reservation_write=False, reservation_release=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--tdx-root", type=Path, required=True)
    parser.add_argument("--caller-holds-locks", action="store_true", required=True)
    args = parser.parse_args()
    ref = file_reference(args.policy)
    if ref["sha256"] != args.policy_sha256:
        raise CapacityProofError("PROBE_POLICY_SHA_CONFLICT")
    result = locked_runtime_probe(json.loads(args.policy.read_bytes()), tdx_root=args.tdx_root)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
