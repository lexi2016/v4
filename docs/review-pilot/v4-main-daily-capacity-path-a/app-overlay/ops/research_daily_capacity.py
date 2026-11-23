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
import struct
from pathlib import Path
import threading


SCHEMA = "v4.daily_incremental_capacity.v1"
PLAN_SCHEMA = "v4.daily_incremental_write_plan.v1"
PHASES = {"qfq", "daily_product", "top200"}
INDEPENDENT_CONSUMERS = {"adjustment_snapshot", "formula_supplements"}
CONSUMER_PEAK_BYTES = {"adjustment_snapshot": 536870912, "formula_supplements": 1260912640}
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


def reviewed_configuration(policy):
    governance = policy.get("governance")
    config = governance.get("incremental_capacity") if isinstance(governance, dict) else None
    if not isinstance(config, dict):
        raise CapacityProofError("INCREMENTAL_CAPACITY_POLICY_NOT_ENABLED")
    if config.get("schema") != SCHEMA or config.get("enabled") is not True:
        raise CapacityProofError("INCREMENTAL_CAPACITY_POLICY_NOT_ENABLED")
    if not isinstance(config.get("phases"), dict) or set(config["phases"]) != PHASES:
        raise CapacityProofError("INCREMENTAL_CAPACITY_PHASES_REQUIRED")
    for limits in config["phases"].values():
        validate_limits(limits)
    reference = config.get("reviewed_limits")
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not isinstance(reference["sha256"], str) or len(reference["sha256"]) != 64):
        raise CapacityProofError("INCREMENTAL_LIMIT_REVIEW_REQUIRED")
    try:
        checked = file_reference(reference["path"])
        review = json.loads(Path(reference["path"]).read_bytes())
    except (OSError, TypeError, ValueError) as error:
        raise CapacityProofError("INCREMENTAL_LIMIT_REVIEW_INVALID") from error
    if checked["sha256"] != reference["sha256"]:
        raise CapacityProofError("INCREMENTAL_LIMIT_REVIEW_CHANGED")
    if (not isinstance(review, dict) or review.get("schema") != "v4.daily_incremental_limits_review.v1"
            or review.get("phase_limits") != config["phases"]
            or review.get("evidence_scope") not in {"ISOLATED_FIXTURE", "PRODUCTION_REVIEWED"}):
        raise CapacityProofError("INCREMENTAL_LIMIT_REVIEW_CONFLICT")
    # This SHA-bound file configures limits, not business-source authorization.
    # Runtime plans independently capture and revalidate the actual writer bytes.
    legacy_fixture = (review["evidence_scope"] == "ISOLATED_FIXTURE"
                      and "consumers" not in config and "downstream_outputs" not in config)
    if not legacy_fixture:
        if (review.get("consumer_limits") != config.get("consumers")
                or review.get("downstream_outputs") != config.get("downstream_outputs")):
            raise CapacityProofError("INDEPENDENT_CONSUMER_REVIEW_CONFLICT")
        consumers = config.get("consumers")
        if not isinstance(consumers, dict) or set(consumers) != INDEPENDENT_CONSUMERS:
            raise CapacityProofError("INDEPENDENT_CONSUMER_LIMITS_REQUIRED")
        for name, expected in CONSUMER_PEAK_BYTES.items():
            item = consumers[name]
            required = {"peak_bytes", "output_roots"} if name == "adjustment_snapshot" else {
                "peak_bytes", "output_roots", "shared_product_roots", "mode", "limits"}
            if (not isinstance(item, dict) or set(item) != required
                    or type(item.get("peak_bytes")) is not int or item["peak_bytes"] != expected):
                raise CapacityProofError("INDEPENDENT_CONSUMER_LIMIT_INVALID:" + name)
            exact_roots(item["output_roots"], required=name == "adjustment_snapshot" or item.get("mode") == "ENABLED")
            if name == "formula_supplements":
                if item["mode"] not in {"DISABLED", "ENABLED"}:
                    raise CapacityProofError("FORMULA_SUPPLEMENTS_MODE_REQUIRED")
                exact_roots(item["shared_product_roots"], required=item["mode"] == "ENABLED")
                if item["mode"] == "DISABLED" and (item["output_roots"] or item["shared_product_roots"]):
                    raise CapacityProofError("DISABLED_OUTPUT_ROOTS_MUST_BE_EMPTY")
                if item["mode"] == "ENABLED":
                    validate_limits(item["limits"])
                    if maximum_limit_bytes(item["limits"]) != item["peak_bytes"]:
                        raise CapacityProofError("FORMULA_SUPPLEMENTS_PEAK_CONFLICT")
        outputs = config.get("downstream_outputs")
        if not isinstance(outputs, dict) or set(outputs) != {"statistics"}:
            raise CapacityProofError("DOWNSTREAM_OUTPUT_CHOICE_REQUIRED")
        stats = outputs["statistics"]
        if (not isinstance(stats, dict) or set(stats) != {"mode", "output_roots"}
                or stats["mode"] not in {"DISABLED", "ENABLED"}):
            raise CapacityProofError("STATISTICS_MODE_REQUIRED")
        exact_roots(stats["output_roots"], required=stats["mode"] == "ENABLED")
        if stats["mode"] == "DISABLED" and stats["output_roots"]:
            raise CapacityProofError("DISABLED_OUTPUT_ROOTS_MUST_BE_EMPTY")
        if stats["mode"] == "ENABLED":
            raise CapacityProofError("STATISTICS_ENABLED_WRITER_NOT_REVIEWED")
    return config, review, legacy_fixture


def exact_roots(roots, *, required=True):
    if (not isinstance(roots, list) or (required and not roots)
            or any(not isinstance(root, str) for root in roots) or len(set(roots)) != len(roots)):
        raise CapacityProofError("EXACT_OUTPUT_ROOTS_REQUIRED")
    for root in roots:
        path = Path(root)
        if not path.is_absolute() or path.is_symlink() or str(path.resolve()) != root:
            raise CapacityProofError("EXACT_OUTPUT_ROOT_INVALID")
    return list(roots)


def independent_consumers(policy):
    config, _, legacy = reviewed_configuration(policy)
    return None if legacy else config["consumers"]


def _root_device(path):
    path = Path(path)
    while not path.exists():
        path = path.parent
    return path.stat().st_dev


def check_pool_roots(policy, roots):
    """Check every prospective owner root before mkdir, including other APFS members."""
    exact_roots(list(map(str, roots)))
    members = policy['governance'].get('pool_member_devices')
    if members is None:
        members = [Path(policy['data_root']).stat().st_dev]
    if not isinstance(members, list) or not members or any(type(device) is not int for device in members):
        raise CapacityProofError('VERIFIED_POOL_MEMBER_DEVICES_REQUIRED')
    if any(_root_device(root) not in members for root in roots):
        raise CapacityProofError('OUTPUT_OUTSIDE_VERIFIED_SHARED_POOL')


def snapshot_output_roots(policy, *, tdx_root, receipt_root, output_root):
    consumers = independent_consumers(policy)
    if consumers is None:
        return None
    from ops.research_panel_qfq import input_path
    if receipt_root is None or output_root is None:
        raise CapacityProofError('ADJUSTMENT_SNAPSHOT_RUNTIME_ROOTS_REQUIRED')
    exact_roots([str(tdx_root), str(receipt_root), str(output_root)])
    actual = input_path(Path(policy['data_root'])).parent
    expected = {actual, Path(tdx_root).parent/'adjustment_inputs/futu_rehab', Path(receipt_root)/'a_sync_authority'}
    approved = [Path(path) for path in consumers['adjustment_snapshot']['output_roots']]
    if Path(output_root) != actual or set(approved) != expected:
        raise CapacityProofError('ADJUSTMENT_SNAPSHOT_OUTPUT_ROOT_BINDING_CONFLICT')
    check_pool_roots(policy, approved)
    return tuple(approved)


def formula_output_roots(policy, *, formula_root, product_root):
    consumers = independent_consumers(policy)
    if consumers is None:
        return None
    choice = consumers['formula_supplements']
    if choice['mode'] == 'DISABLED':
        return ()
    if (choice['output_roots'] != [str(formula_root)] or choice['shared_product_roots'] != [str(product_root)]):
        raise CapacityProofError('SUPPLEMENT_OUTPUT_ROOT_NOT_APPROVED')
    roots = [Path(formula_root), Path(product_root)]
    check_pool_roots(policy, roots)
    return tuple(roots)


def runtime_root_bindings(policy, *, tdx_root, receipt_root, daily_product_root, api_host_binding):
    """Resolve the same roots the scheduler and SHA-pinned API binding supply."""
    consumers = independent_consumers(policy)
    if consumers is None:
        return None
    if receipt_root is None or daily_product_root is None:
        raise CapacityProofError('CAPACITY_RUNTIME_ROOT_INPUTS_REQUIRED')
    from ops.research_panel_qfq import input_path
    snapshot_output_roots(policy,tdx_root=tdx_root,receipt_root=receipt_root,
                          output_root=input_path(Path(policy['data_root'])).parent)
    exact_roots([str(daily_product_root)])
    product = Path(daily_product_root)/'daily_products/a_share'
    if str(product) not in policy['governance'].get('product_output_roots', []):
        raise CapacityProofError('DAILY_PRODUCT_RUNTIME_ROOT_NOT_APPROVED')
    check_pool_roots(policy, [product])
    binding_ref = None
    if consumers['formula_supplements']['mode'] == 'ENABLED':
        if (not isinstance(api_host_binding, dict) or set(api_host_binding) != {'path', 'sha256'}
                or not isinstance(api_host_binding['sha256'], str) or len(api_host_binding['sha256']) != 64):
            raise CapacityProofError('FORMULA_HOST_BINDING_REFERENCE_REQUIRED')
        try:
            checked = file_reference(api_host_binding['path'])
            binding = json.loads(Path(api_host_binding['path']).read_bytes())
        except (OSError, TypeError, ValueError) as error:
            raise CapacityProofError('FORMULA_HOST_BINDING_INVALID') from error
        if checked['sha256'] != api_host_binding['sha256']:
            raise CapacityProofError('FORMULA_HOST_BINDING_SHA_DRIFT')
        from ops.research_panel_formula_groups_daily import FORMULA_SHA256, FLAGS
        if (not isinstance(binding,dict) or binding.get('schema') != 'V4_MAC_WORKBENCH_BINDING_V1'
                or binding.get('candidate_group_formula_sha256') != FORMULA_SHA256
                or not isinstance(binding.get('candidate_group_overrides'),dict)
                or not isinstance(binding.get('formula_groups_root'),str)
                or any(binding.get(key) is not value for key,value in FLAGS.items())):
            raise CapacityProofError('FORMULA_HOST_BINDING_INVALID')
        if file_reference(api_host_binding['path']) != checked:
            raise CapacityProofError('FORMULA_HOST_BINDING_MOVED')
        formula_output_roots(policy,formula_root=Path(binding['formula_groups_root']),product_root=product)
        binding_ref = dict(api_host_binding)
    return dict(tdx_root=str(tdx_root),receipt_root=str(receipt_root),daily_product_root=str(daily_product_root),
                api_host_binding=binding_ref)


def downstream_root(policy, name, root):
    """Select an exact reviewed root before the owner creates any output."""
    config, _, legacy = reviewed_configuration(policy)
    if legacy:
        return root
    item = config["downstream_outputs"][name]
    if item["mode"] == "DISABLED":
        return None
    if root is None or str(Path(root)) not in item["output_roots"]:
        raise CapacityProofError("DOWNSTREAM_OUTPUT_ROOT_NOT_APPROVED:" + name)
    exact_roots([str(root)])
    return root


def phase_limits(policy, phase):
    config, _, legacy = reviewed_configuration(policy)
    if phase == "formula_supplements":
        limits = (config["phases"]["daily_product"] if legacy
                  else config["consumers"][phase]["limits"])
        if not legacy and config["consumers"][phase]["mode"] != "ENABLED":
            raise CapacityProofError("FORMULA_SUPPLEMENTS_DISABLED")
    elif phase in PHASES:
        limits = config["phases"][phase]
    else:
        raise CapacityProofError("INCREMENTAL_CAPACITY_PHASES_REQUIRED")
    validate_limits(limits)
    return limits


def maximum_limit_bytes(limits):
    return (limits["fixed_bytes"] + limits["max_symbols"] * limits["per_symbol_bytes"]
            + limits["max_changed_rows"] * limits["per_changed_row_bytes"])


def validate_limits(limits):
    fields = {"fixed_bytes", "per_symbol_bytes", "per_changed_row_bytes", "max_file_bytes", "max_symbols",
              "max_changed_rows", "max_revised_symbols", "max_files", "max_files_per_symbol", "max_response_bytes", "max_response_items", "receipt_bytes"}
    if (not isinstance(limits, dict) or set(limits) != fields or any(type(value) is not int or value < 0 for value in limits.values())
            or any(limits[name] <= 0 for name in
                   ("fixed_bytes", "max_file_bytes", "max_files", "max_files_per_symbol", "max_response_bytes", "max_response_items", "receipt_bytes"))
            or limits['receipt_bytes'] > limits['fixed_bytes']):
        raise CapacityProofError("INCREMENTAL_LIMITS_INVALID")


def retained_reactivation_proofs(policy, target, source_identity, classifications, codes):
    """Verify the original retained prefix plus one exact official target bar.

    This is a bounded full-prefix recomputation, still classified NEW and still
    charged for every selected row. It never admits an unobserved stock/history.
    """
    from ops._a_share_daily_sync_parts.official_daily_package import OfficialDailyPackage
    references, buffers = {}, {}
    def read(reference):
        path = reference['path']
        if path not in buffers:
            actual = file_reference(path)
            raw = Path(path).read_bytes()
            if actual['sha256'] != reference['sha256'] or sha256(raw).hexdigest() != actual['sha256']:
                raise CapacityProofError('RETAINED_REACTIVATION_SOURCE_CHANGED')
            references[path], buffers[path] = actual, raw
        elif references[path]['sha256'] != reference['sha256']:
            raise CapacityProofError('RETAINED_REACTIVATION_SOURCE_CONFLICT')
        return buffers[path]
    def document(reference):return json.loads(read(reference))
    def package(sync, date):
        official = sync['official_daily_source']
        result = OfficialDailyPackage(official['input_ref'], date)
        if (official['source_kind'] != 'TDX_OFFICIAL_G4DAY' or str(sync['target_date']) != str(date)
                or official['package'] != result.package_ref or official['previous_session'] != result.previous):
            raise CapacityProofError('RETAINED_REACTIVATION_OFFICIAL_SOURCE_CONFLICT')
        for reference in (result.input_ref, result.package_ref, result.calendar_ref, result.calendar_adapter_ref):read(reference)
        return result
    def sync_row(sync, code):
        market = {'SZ':0, 'SH':1, 'BJ':2}[code[-2:]]
        rows = [row for row in sync['symbol_reconciliation']
                if int(row['market']) == market and str(row['symbol']).zfill(6) == code[:6]]
        if len(rows) != 1:raise CapacityProofError('RETAINED_REACTIVATION_SYNC_SCOPE_CONFLICT')
        return market, rows[0]
    def roles(item):
        refs = item['raw_files']; result = {r['source_role']:r for r in refs}
        if len(result) != len(refs) or 'native' not in result or not set(result) <= {'archive','native'}:
            raise CapacityProofError('RETAINED_REACTIVATION_RAW_ROLES_INVALID')
        return result
    def dates(raw):
        if not raw or len(raw) % 32:raise CapacityProofError('RETAINED_REACTIVATION_RAW_BOUNDARY')
        values = [struct.unpack_from('<I',raw,i)[0]for i in range(0,len(raw),32)]
        if values != sorted(set(values)) or values[0] <= 19000101:
            raise CapacityProofError('RETAINED_REACTIVATION_RAW_KEYS_INVALID')
        return values
    try:
        evidence_ref = policy['governance']['incremental_capacity']['retained_reactivation_evidence']
        evidence = document(evidence_ref)
        context = source_identity['retained_reactivation_context']
        snapshot = document(context['snapshot'])
        prior_ref = context['previous_snapshot']; prior = document(prior_ref)
        parent = document(evidence['previous_generation'])
        if (evidence.get('schema') != 'qfq_retained_native_recovery_v1' or evidence['target_date'] != target
                or evidence['previous_snapshot'] != prior_ref or snapshot['asof_date'] != target
                or context['snapshot']['sha256'] != source_identity['snapshot_sha256']
                or parent['status'] != 'READY' or parent['adjustment_snapshot'] != prior_ref
                or parent['input_sha256'] != digest(prior) or parent['asof_date'] != prior['asof_date']
                or parent['candidate_sha256'] != source_identity['baseline']
                or set(context['baseline_generations']) != {'selector','backtest'}
                or set(context['baseline_generations'].values()) != {parent['generation_id']}):
            raise CapacityProofError('RETAINED_REACTIVATION_BASELINE_CONFLICT')
        cache_ref = snapshot['research_cache_configuration']
        if cache_ref not in snapshot['source_files']:raise CapacityProofError('RETAINED_REACTIVATION_CURRENT_SOURCE_UNBOUND')
        cache = document(cache_ref); current_sync = document(cache['prequery_sync_ref'])
        today = package(current_sync,target)
        proofs = {}
        for code in codes:
            entry = evidence['symbols'][code]
            source = document(entry['source_snapshot']); generation = document(entry['source_generation'])
            pins = ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')
            if any(not isinstance(source_identity['source_semantics'].get(key),str)
                   or record.get(key) != source_identity['source_semantics'][key]
                   for record in (parent,generation) for key in pins):
                raise CapacityProofError('RETAINED_REACTIVATION_RULE_CHANGE_FULL_REBUILD_REQUIRED')
            if (code not in prior.get('retained_history_codes',[]) or code in prior['symbols']
                    or code in prior.get('quarantine_symbols',{}) or generation['status'] != 'READY'
                    or generation['adjustment_snapshot'] != entry['source_snapshot'] or generation['input_sha256'] != digest(source)
                    or generation['asof_date'] != source['asof_date'] or parent['baseline_panel_sha256'] != generation['candidate_sha256']
                    or entry['retained_sync_ref'] not in prior['source_files']
                    or prior['history_retention_binding'] != source['history_retention_binding']):
                raise CapacityProofError('RETAINED_REACTIVATION_PRIOR_SCOPE_CONFLICT')
            skip_sync = document(entry['retained_sync_ref']); skipped = package(skip_sync,prior['asof_date'])
            market, skip_row = sync_row(skip_sync,code); _, row = sync_row(current_sync,code)
            before, after = source['symbols'][code], snapshot['symbols'][code]
            old_refs, new_refs = roles(before), roles(after)
            old_native, new_native = old_refs['native'], new_refs['native']
            old_raw, new_raw = read(old_native), read(new_native)
            old_dates, new_dates = dates(old_raw), dates(new_raw)
            absent = skipped.rows.get((market,code[:6]))
            no_bar = absent is None or (all(absent[0][k] == 0 for k in ('open','high','low'))
                                       and absent[0]['vol'] == 0 and absent[0]['amount'] == 0)
            bar, _, shares = today.rows[(market,code[:6])]
            target_raw = struct.pack('<IIIIIfII',target,*(round(float(bar[k])*100)for k in ('open','high','low','close')),
                                     float(bar['amount']),shares,0)
            live_ref = new_native['original_ref']['current_native']; live = read(live_ref)
            if (today.previous != prior['asof_date'] or skipped.previous != source['asof_date']
                    or today.calendar_ref != skipped.calendar_ref or today.calendar_adapter_ref != skipped.calendar_adapter_ref
                    or not no_bar or skip_row.get('classification') != 'QUARANTINED' or skip_row.get('quarantine') is not True
                    or skip_row.get('reason_code') != 'TARGET_DATE_MISSING' or skip_row.get('target_date_ready') is not False
                    or skip_row.get('last_date_before') != source['asof_date'] or skip_row.get('last_date_after') != source['asof_date']
                    or skip_row.get('source_sha256_before') != old_native['sha256'] or skip_row.get('source_sha256_after') != old_native['sha256']
                    or row.get('classification') != 'ACCEPTED' or row.get('target_date_ready') is not True
                    or row.get('path') != live_ref['path'] or row.get('source_sha256_after') != live_ref['sha256']
                    or live[-32:] != target_raw or new_raw != old_raw+target_raw or old_dates[-1] != source['asof_date']
                    or new_dates[-1] != target or {k:v for k,v in old_refs.items()if k!='native'} != {k:v for k,v in new_refs.items()if k!='native'}
                    or any(before.get(k) != after.get(k) for k in ('raw_resolution','history_start_date','compute_start_date','source_config','source_policy'))
                    or before.get('raw_resolution') != 'ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2'):
                raise CapacityProofError('RETAINED_REACTIVATION_EXACT_APPEND_UNPROVED')
            selected = set()
            for reference in new_refs.values():selected.update(d for d in dates(read(reference))if d<=target)
            count = source_identity['changed_rows_by_symbol'][code]
            classification_sha = source_identity['classification_dependencies'][code]
            if (type(count) is not int or count != len(selected) or classifications[code] != 'NEW_OR_MISSING_HISTORY'
                    or not isinstance(classification_sha,str) or len(classification_sha) != 64):
                raise CapacityProofError('RETAINED_REACTIVATION_FULL_CENSUS_REQUIRED')
            proofs[code] = dict(source_snapshot=entry['source_snapshot'],source_native_sha256=old_native['sha256'],
                current_native_sha256=new_native['sha256'],changed_rows=count,classification_sha256=classification_sha)
        check_inputs(list(references.values()))
        return proofs, list(references.values())
    except (KeyError, TypeError, ValueError, OSError, struct.error) as error:
        if isinstance(error,CapacityProofError):raise
        raise CapacityProofError('RETAINED_REACTIVATION_EVIDENCE_REQUIRED') from error


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
    if classifications and any(value == 'RULE_REVISION' for value in classifications.values()):
        raise CapacityProofError("INCREMENTAL_SCOPE_EXCEEDED_FULL_REBUILD_REQUIRED")
    restored = sorted(code for code,kind in (classifications or {}).items()if kind=='NEW_OR_MISSING_HISTORY')
    if restored:
        if (phase != 'qfq' or not set(restored)<=set(scope)
                or changed_rows != sum(source_identity.get('changed_rows_by_symbol',{}).values())
                or revised_symbols != sum(kind not in {'APPEND','UNCHANGED'} for kind in classifications.values())):
            raise CapacityProofError('INCREMENTAL_SCOPE_EXCEEDED_FULL_REBUILD_REQUIRED')
        proofs, extra = retained_reactivation_proofs(policy,target,source_identity,classifications,restored)
        references = [*references,*extra]
        source_identity = {**source_identity,'retained_reactivation_proofs':proofs}
    review_reference = file_reference(policy["governance"]["incremental_capacity"]["reviewed_limits"]["path"])
    references = list({ref["path"]: ref for ref in [*references, review_reference]}.values())
    check_inputs(references)
    predicted = (limits["fixed_bytes"] + len(scope) * limits["per_symbol_bytes"]
                 + changed_rows * limits["per_changed_row_bytes"])
    if phase == "formula_supplements":
        consumers = independent_consumers(policy)
        if consumers is not None:
            predicted = consumers[phase]["peak_bytes"]
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
                                        target=target, operation="adjustment_snapshot",
                                        output_root=snapshot_path.parent) as input_claim:
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
    source_semantics = delta.classification_source_semantics(vars(module),dict(driver_sha256=module.sha(kwargs["driver_path"]),
                            formula_sha256=module.sha(kwargs["formula_path"]),
                            field_contract_sha256=module.sha(kwargs["contract_csv"]),
                            user_formula_sha256=module.USER_FORMULA_SHA))
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
                                           classification_dependencies=classification_dependencies,
                                           retained_reactivation_context=dict(snapshot=file_reference(snapshot_path),
                                               previous_snapshot=old_refs[0],baseline_generations={role:value['generation_id']for role,value in contracts.items()})), references=refs,
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
    # The same Reader validates bounded stock batches without constructing bars
    # or repeating both complete pair-closure checks for every individual stock.
    counts = (context.row_counts(selected) if callable(getattr(context,'row_counts',None))
              else {symbol:len(context.read(symbol)[0]) for symbol in selected})
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


# Plan2 P0 accepts the existing instrumented phase writers. Their numeric,
# output-root, in-flight and registry/disk checks remain executable below.
INSTRUMENTED_WRITER_PHASES = frozenset(PHASES)
ACCEPTED_WRITER_PHASES = frozenset(PHASES)


def require_writer_coverage(phase):
    if ("daily_product" if phase == "formula_supplements" else phase) not in INSTRUMENTED_WRITER_PHASES:
        raise CapacityProofError("INCREMENTAL_PRODUCT_WRITER_COVERAGE_NOT_PROVEN:" + phase)


def writer_sources():
    names = ("research_daily_capacity", "research_storage_governance", "research_panel_daily_product",
             "research_storage_retention", "research_panel_qfq", "research_panel_delta", "research_panel_logical",
             "research_panel_adjustment_inputs", "research_panel_tdx_adjustment_inputs", "research_panel_daily_source",
             "research_panel_factor_cache", "research_storage_pair", "materialize_workbench_v192_assets",
             "research_panel_formula_groups_daily", "_formula_groups_daily_parts/workbench_supplements",
             "research_daily_product_parallel", "research_panel_history_checkpoint", "research_panel_chart_blocks",
             "render_original_formula_projection", "research_storage_compaction", "materialize_workbench_score_action",
             "workbench_score_calculation",
             "complete_workbench_v192_assets", "build_mac_workbench", "research_panel_top200", "research_panel_f10",
             "bootstrap_stock_event_history", "sync_stock_history_completion")
    root = Path(__file__).resolve().parent
    return {name:sha256((root / (name + ".py")).read_bytes()).hexdigest() for name in names}


def locked_runtime_probe(policy, *, tdx_root, receipt_root=None, daily_product_root=None, api_host_binding=None):
    """Read-only probe. Caller MUST hold role, pool-writer and registry locks.

    Does not reacquire Registry.transaction, mkdir, create a claim or persist a
    receipt. Frozen registry bytes are checked before and after the root walk.
    """
    from ops import research_storage_governance as governance
    config = governance.configuration(policy)
    if config is None:
        raise CapacityProofError("GOVERNANCE_REQUIRED")
    runtime_inputs = runtime_root_bindings(policy,tdx_root=tdx_root,receipt_root=receipt_root,
                                          daily_product_root=daily_product_root,api_host_binding=api_host_binding)
    registry = governance.Registry(config, policy["data_root"])
    before = file_reference(registry.path)
    state = registry.read()
    if any(row["state"] in {"RUNNING", "VALIDATING"} for row in state["tasks"].values()):
        raise CapacityProofError("ACTIVE_EXECUTOR_OR_UNRECONCILED_RUNNING_ROW")
    resident = ordinary_resident_bytes(governance, config, state)
    peaks = maximum_phase_bytes(policy)
    native = governance.input_forecast(tdx_root)["predicted_bytes"]
    consumers = independent_consumers(policy)
    components = dict(native_input=native,
                      adjustment_snapshot=native if consumers is None else consumers['adjustment_snapshot']['peak_bytes'],
                      qfq=peaks['qfq'], daily_product=peaks['daily_product'],
                      formula_supplements=(peaks['daily_product'] if consumers is None else
                          consumers['formula_supplements']['peak_bytes'] if consumers['formula_supplements']['mode'] == 'ENABLED' else 0),
                      top200=peaks['top200'])
    if consumers is not None and consumers['formula_supplements']['mode'] == 'ENABLED':
        phase_limits(policy, 'formula_supplements')
    # Successful consumers leave retained files resident. The complete schedule
    # needs their summed bounds, including the separately owned supplement.
    peaks['input'] = components['native_input'] + components['adjustment_snapshot']
    peaks['daily_product'] = components['daily_product'] + components['formula_supplements']
    if runtime_inputs is not None:
        final_inputs = runtime_root_bindings(policy,tdx_root=tdx_root,receipt_root=receipt_root,
            daily_product_root=daily_product_root,api_host_binding=api_host_binding)
        if final_inputs != runtime_inputs:
            raise CapacityProofError('CAPACITY_RUNTIME_ROOT_INPUTS_CHANGED')
    after = file_reference(registry.path)
    if before != after:
        raise CapacityProofError("LOCKED_REGISTRY_CHANGED_DURING_PROBE")
    review_path = policy['governance']['incremental_capacity']['reviewed_limits']['path']
    scope = json.loads(Path(review_path).read_bytes())['evidence_scope']
    unproven = sorted(PHASES - (INSTRUMENTED_WRITER_PHASES if scope == 'ISOLATED_FIXTURE' else ACCEPTED_WRITER_PHASES))
    return dict(schema="v4.daily_capacity_locked_probe.v1",
                registry_sha256=before["sha256"], policy_sha256=digest(policy),
                category_used_bytes=resident, phase_peak_bytes=peaks,
                consumer_peak_bytes=components, runtime_inputs=runtime_inputs,
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
    parser.add_argument("--receipt-root", type=Path)
    parser.add_argument("--daily-product-root", type=Path)
    parser.add_argument("--api-host-binding", type=Path)
    parser.add_argument("--api-host-binding-sha256")
    parser.add_argument("--caller-holds-locks", action="store_true", required=True)
    args = parser.parse_args()
    ref = file_reference(args.policy)
    if ref["sha256"] != args.policy_sha256:
        raise CapacityProofError("PROBE_POLICY_SHA_CONFLICT")
    binding = (dict(path=str(args.api_host_binding),sha256=args.api_host_binding_sha256)
               if args.api_host_binding is not None or args.api_host_binding_sha256 is not None else None)
    result = locked_runtime_probe(json.loads(args.policy.read_bytes()), tdx_root=args.tdx_root,
        receipt_root=args.receipt_root,daily_product_root=args.daily_product_root,api_host_binding=binding)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
