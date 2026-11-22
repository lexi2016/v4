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
import threading


SCHEMA = "v4.daily_incremental_capacity.v1"
PLAN_SCHEMA = "v4.daily_incremental_write_plan.v1"
PHASES = {"qfq", "daily_product", "top200"}
_PLAN = ContextVar("v4_daily_incremental_write_plan", default=None)
_WRITER = ContextVar("v4_daily_incremental_writer", default=None)
_PREPAID = ContextVar("v4_daily_incremental_prepaid", default=None)
_ACTIVE_WRITE = ContextVar("v4_daily_incremental_active_write", default=None)
_WORKER_PLAN = None
_WORKER_ROOTS = ()
_CONTROL = ContextVar('v4_daily_incremental_control_writes',default=False)


class CapacityProofError(ValueError):
    pass


def propagate_capacity_error(error):
    """Capacity failures must reach the phase owner, including through futures."""
    from ops.research_storage_retention import RetentionError
    if isinstance(error, CapacityProofError) or current_plan() is not None and isinstance(error, RetentionError):
        raise error


class WriteBudget:
    """One immutable phase or one submitted symbol's allocation allowance.

    Allocation is conservatively cumulative, including temporary copies. A
    worker never mutates the shared registry. Its parent retains its whole slot
    until it has reconciled the completed worker's actual files.
    """
    def __init__(self, plan, *, claim=None, symbol=None, roots=()):
        self.plan = plan
        self.claim = claim
        self.symbol = symbol
        self.roots = tuple(Path(root).resolve() for root in roots)
        self.limit = symbol_slot(plan, symbol) if symbol is not None else plan["predicted_bytes"]
        self.spent = 0
        self.inflight = 0
        self.inflight_files = 0
        self.file_count = 0
        self.control_remaining = plan['limits']['receipt_bytes'] if symbol is None else 0
        self.paths = set()
        self.mutex = threading.RLock()

    def path(self, path):
        path = Path(path)
        if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
            raise CapacityProofError("CAPACITY_OUTPUT_PATH_CONFLICT")
        if not self.roots or not any(path.is_relative_to(root) for root in self.roots):
            raise CapacityProofError("CAPACITY_OUTPUT_OUTSIDE_OWNED_ROOT")
        return path

    def charge(self, path, size, *, copies=1):
        path = self.path(path)
        if type(copies) is not int or copies < 1:
            raise CapacityProofError("CAPACITY_COPY_COUNT_INVALID")
        check_serialized_write(size, plan=self.plan)
        allocation = ((size + 4095) // 4096) * 4096 * copies
        with self.mutex:
            control = _CONTROL.get() and self.symbol is None
            if control and allocation > self.control_remaining:
                raise CapacityProofError('INCREMENTAL_RECEIPT_SLOT_EXCEEDED')
            count = self.file_count + copies
            ceiling = self.plan['limits']['max_files_per_symbol'] if self.symbol is not None else self.plan['limits']['max_files']
            if count + self.inflight_files > ceiling:
                raise CapacityProofError("INCREMENTAL_FILE_COUNT_EXCEEDED")
            if self.spent + self.inflight + allocation + (0 if control else self.control_remaining) > self.limit:
                raise CapacityProofError("INCREMENTAL_WRITE_SLOT_EXCEEDED")
            if self.claim is not None:
                self.claim.watch(path)
                self.claim.checkpoint(incoming=self.inflight + allocation)
            self.spent += allocation
            if control:self.control_remaining -= allocation
            self.file_count = count
            self.paths.add(str(path))
        return path

    def observe(self, path):
        if self.claim is not None:
            with self.mutex:
                self.claim.observe(path)
                self.claim.checkpoint(incoming=self.inflight)

    def reserve(self, symbol):
        amount = symbol_slot(self.plan, symbol)
        with self.mutex:
            if self.spent + self.inflight + amount + self.control_remaining > self.limit:
                raise CapacityProofError("INCREMENTAL_INFLIGHT_SLOT_EXCEEDED")
            files = self.plan['limits']['max_files_per_symbol']
            if self.file_count + self.inflight_files + files > self.plan['limits']['max_files']:
                raise CapacityProofError('INCREMENTAL_INFLIGHT_FILE_COUNT_EXCEEDED')
            if self.claim is None:
                raise CapacityProofError("PARENT_CLAIM_REQUIRED_FOR_WORKER")
            self.claim.checkpoint(incoming=self.inflight + amount)
            self.inflight += amount
            self.inflight_files += files
        return amount

    def settle(self, amount, outcome=None, *, failed=False):
        with self.mutex:
            if outcome is not None:
                if (outcome.get("plan_sha256") != self.plan["plan_sha256"]
                        or type(outcome.get("spent")) is not int
                        or not 0 <= outcome["spent"] <= amount
                        or type(outcome.get('file_count')) is not int
                        or not 0 <= outcome['file_count'] <= self.plan['limits']['max_files_per_symbol']):
                    raise CapacityProofError("WORKER_WRITE_ACCOUNTING_CONFLICT")
                paths = [self.path(path) for path in outcome["paths"]]
                for path in paths:
                    # The submitted slot owns its newly generated outputs. Old
                    # inodes retain the original Claim baseline on recovery.
                    if path not in self.claim.baselines:
                        self.claim.baselines[path] = (0, 0)
                    self.claim.observe(path)
                self.spent += outcome["spent"]
                self.file_count += outcome['file_count']
                self.paths.update(map(str, paths))
            if failed or outcome is not None and outcome.get('error') is not None:
                # A killed worker may not return accounting. Reconcile every
                # permitted root before releasing its conservative full slot.
                from ops.research_storage_governance import billing_files
                for root in self.roots:
                    if root.exists():
                        for path in billing_files(root):
                            if path not in self.claim.baselines:
                                self.claim.baselines[path] = (0, 0)
                            self.claim.observe(path)
                if outcome is None:self.spent += amount
            self.inflight -= amount
            self.inflight_files -= self.plan['limits']['max_files_per_symbol']
            if self.inflight < 0:
                raise CapacityProofError("INCREMENTAL_INFLIGHT_ACCOUNTING_CONFLICT")
            self.claim.checkpoint(incoming=self.inflight)


def symbol_slot(plan, symbol):
    if symbol not in plan["scope"]:
        raise CapacityProofError("CAPACITY_SYMBOL_OUTSIDE_SCOPE")
    counts = plan["source_identity"].get("changed_rows_by_symbol", {})
    if symbol not in counts or type(counts[symbol]) is not int or counts[symbol] < 0:
        raise CapacityProofError("CAPACITY_SYMBOL_ROW_COUNT_REQUIRED")
    return plan["limits"]["per_symbol_bytes"] + counts[symbol] * plan["limits"]["per_changed_row_bytes"]


@contextmanager
def writer_scope(plan, *, claim=None, symbol=None, roots=()):
    with write_scope(plan):
        writer = WriteBudget(plan, claim=claim, symbol=symbol, roots=roots)
        token = _WRITER.set(writer)
        try:
            yield writer
        finally:
            _WRITER.reset(token)


def current_writer():
    return _WRITER.get()


@contextmanager
def control_writes():
    token = _CONTROL.set(True)
    try:yield
    finally:_CONTROL.reset(token)


def require_managed_entry():
    from ops.research_storage_governance import configured_policy
    policy = configured_policy()
    if policy and enabled(policy) and current_writer() is None:
        raise CapacityProofError("INCREMENTAL_ENTRY_REQUIRES_MANAGED_CLAIM")


def response_limits():
    require_managed_entry()
    plan = current_plan()
    return plan["limits"] if plan is not None else None


@contextmanager
def serialized_write(path, raw, *, copies=1):
    """Guard the actual buffer before mkdir, temporary creation or replacement."""
    writer = current_writer()
    if current_plan() is not None and writer is None:
        raise CapacityProofError("INCREMENTAL_WRITER_CONTEXT_REQUIRED")
    if writer is None:
        yield
        return
    prepaid = _PREPAID.get() or {}
    key = (str(Path(path)), sha256(raw).hexdigest())
    outer = _ACTIVE_WRITE.get()
    if outer is not None and outer[:2] == key and outer[2] >= copies:
        yield
        return
    credit = prepaid.get(key)
    if credit is not None:
        if credit[0] < 1 or credit[1] < copies:
            raise CapacityProofError("INCREMENTAL_PREPAID_WRITE_CONFLICT")
        credit[0] -= 1
    else:
        writer.charge(path, len(raw), copies=copies)
    token = _ACTIVE_WRITE.set((*key, copies))
    try:
        yield
    finally:
        _ACTIVE_WRITE.reset(token)
        writer.observe(path)


@contextmanager
def prepaid_writes(items):
    """Reserve forward and exact rollback buffers before the first publication."""
    writer = current_writer()
    if writer is None:
        yield
        return
    pending = {}
    total = 0
    for path, raw, copies in items:
        writer.path(path)
        check_serialized_write(len(raw), plan=writer.plan)
        key = (str(Path(path)), sha256(raw).hexdigest())
        slot = pending.setdefault(key, [0, copies])
        if slot[1] != copies:
            raise CapacityProofError("INCREMENTAL_PREPAID_COPY_CONFLICT")
        slot[0] += 1
        total += ((len(raw) + 4095) // 4096) * 4096 * copies
    with writer.mutex:
        count = sum(value[0] * value[1] for value in pending.values())
        control = _CONTROL.get() and writer.symbol is None
        if control and total > writer.control_remaining:
            raise CapacityProofError('INCREMENTAL_RECEIPT_SLOT_EXCEEDED')
        if (writer.spent + writer.inflight + total + (0 if control else writer.control_remaining) > writer.limit
                or writer.file_count + writer.inflight_files + count > writer.plan["limits"]["max_files"]):
            raise CapacityProofError("INCREMENTAL_PUBLICATION_CONTROL_SLOT_EXCEEDED")
        if writer.claim is not None:
            for path, _, _ in items:
                writer.claim.watch(path)
            writer.claim.checkpoint(incoming=writer.inflight + total)
        writer.spent += total
        if control:writer.control_remaining -= total
        writer.file_count += count
    token = _PREPAID.set(pending)
    try:
        yield
    finally:
        _PREPAID.reset(token)


def initialize_worker(initializer, initargs, plan, roots):
    """Verify shared source/input bytes once per actual spawned process."""
    global _WORKER_PLAN, _WORKER_ROOTS
    validate_plan(plan)
    if initializer is not None:
        initializer(*initargs)
    _WORKER_PLAN, _WORKER_ROOTS = plan, roots


def run_worker(function, args, kwargs, plan_sha256, symbol):
    """Picklable spawn entry. The same actual owner function performs all work."""
    plan = _WORKER_PLAN
    if plan is None or plan['plan_sha256'] != plan_sha256:
        raise CapacityProofError('WORKER_PLAN_NOT_INITIALIZED_OR_CONFLICT')
    with writer_scope(plan, symbol=symbol, roots=_WORKER_ROOTS) as writer:
        value = error = None
        try:
            value = function(*args, **kwargs)
        except BaseException as failure:
            error = failure
        return dict(value=value, error=error, plan_sha256=plan["plan_sha256"],
                    spent=writer.spent, file_count=writer.file_count, paths=sorted(writer.paths))


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
              "max_changed_rows", "max_revised_symbols", "max_files", "max_files_per_symbol", "max_response_bytes", "max_response_items", "receipt_bytes"}
    if (set(limits) != fields or any(type(value) is not int or value < 0 for value in limits.values())
            or any(limits[name] <= 0 for name in
                   ("fixed_bytes", "max_file_bytes", "max_files", "max_files_per_symbol", "max_response_bytes", "max_response_items", "receipt_bytes"))
            or limits['receipt_bytes'] > limits['fixed_bytes']):
        raise CapacityProofError("INCREMENTAL_LIMITS_INVALID")
    if (review.get("schema") != "v4.daily_incremental_limits_review.v1"
            or review.get("status") != "PASS" or review.get("phase_limits") != config["phases"]
            or review.get("evidence_scope") not in {"ISOLATED_FIXTURE", "PRODUCTION_REVIEWED"}
            or review.get("source_bindings") != writer_sources()):
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
                 predicted_bytes=predicted, policy_sha256=digest(policy),
                 evidence_scope=json.loads(Path(review_reference["path"]).read_bytes())["evidence_scope"],
                 source_bindings=writer_sources())
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
    if plan.get("source_bindings") != writer_sources():
        raise CapacityProofError("INCREMENTAL_WRITER_SOURCE_CHANGED")
    return plan


@contextmanager
def write_scope(plan):
    """Keep the same immutable plan at all existing owner write boundaries."""
    if plan is not _WORKER_PLAN:
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


def product_plan(policy, context, phase, *, symbols=None, history_dates=(), extra_references=()):
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
    counts = {symbol:len(context.read(symbol)[0]) for symbol in selected}
    rows = sum(counts.values())
    references = [file_reference(Path(ref["path"])) for ref in
                  (context.receipt_ref, context.snapshot_ref, context.config_ref, context.reader_ref,*extra_references)]
    references = list({ref["path"]: ref for ref in references}.values())
    context.unchanged()
    return build_plan(policy, phase, target=context.target, scope=selected,
                      source_identity={**context.identity, "changed_rows_by_symbol":counts}, references=references,
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
INSTRUMENTED_WRITER_PHASES = frozenset(PHASES)
ACCEPTED_WRITER_PHASES = frozenset()


def require_writer_coverage(phase):
    if phase not in INSTRUMENTED_WRITER_PHASES:
        raise CapacityProofError("INCREMENTAL_PRODUCT_WRITER_COVERAGE_NOT_PROVEN:" + phase)


def writer_sources():
    names = ("research_daily_capacity", "research_storage_governance", "research_panel_daily_product",
             "research_storage_retention", "research_panel_qfq", "research_panel_delta", "research_panel_logical",
             "research_panel_adjustment_inputs", "research_panel_tdx_adjustment_inputs", "research_panel_daily_source",
             "research_panel_factor_cache", "research_storage_pair", "materialize_workbench_v192_assets",
             "research_panel_formula_groups_daily", "_formula_groups_daily_parts/workbench_supplements",
             "research_daily_product_parallel", "research_panel_history_checkpoint", "research_panel_chart_blocks",
             "render_original_formula_projection", "research_storage_compaction", "materialize_workbench_score_action",
             "complete_workbench_v192_assets", "build_mac_workbench", "research_panel_top200", "research_panel_f10",
             "bootstrap_stock_event_history", "sync_stock_history_completion")
    root = Path(__file__).resolve().parent
    return {name:sha256((root / (name + ".py")).read_bytes()).hexdigest() for name in names}


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
    native = governance.input_forecast(tdx_root)["predicted_bytes"]
    components = dict(native_input=native,adjustment_snapshot=native,qfq=peaks['qfq'],
                      daily_product=peaks['daily_product'],formula_supplements=peaks['daily_product'],
                      top200=peaks['top200'])
    # Successful consumers leave retained files resident. The complete schedule
    # needs their summed bounds, including the separately owned supplement.
    peaks['input'] = components['native_input'] + components['adjustment_snapshot']
    peaks['daily_product'] = components['daily_product'] + components['formula_supplements']
    after = file_reference(registry.path)
    if before != after:
        raise CapacityProofError("LOCKED_REGISTRY_CHANGED_DURING_PROBE")
    review_path = policy['governance']['incremental_capacity']['reviewed_limits']['path']
    scope = json.loads(Path(review_path).read_bytes())['evidence_scope']
    unproven = sorted(PHASES - (INSTRUMENTED_WRITER_PHASES if scope == 'ISOLATED_FIXTURE' else ACCEPTED_WRITER_PHASES))
    return dict(schema="v4.daily_capacity_locked_probe.v1",
                registry_sha256=before["sha256"], policy_sha256=digest(policy),
                category_used_bytes=resident, phase_peak_bytes=peaks,
                consumer_peak_bytes=components,
                predicted_peak_bytes=sum(peaks.values()),
                eligibility="CANNOT_CONFIRM" if unproven else "PASS_ISOLATED_FIXTURE" if scope == 'ISOLATED_FIXTURE' else "PASS",
                evidence_scope=scope,
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
