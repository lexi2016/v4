#!/usr/bin/env python3
"""Read-only compatibility validator for the frozen experiment registry boundary.

The validator deliberately does not call the official registry writer or its
whole-history schema validator. Immutable legacy schema debt is checked by an
exact 644-event byte boundary and a debt fingerprint. The exact current
1726-event snapshot is then pinned byte-for-byte; its existing schema debt is
reported as pre-existing and is never upgraded to PASS. Only the suffix after
line 1726 is validated by the official event and correction validators.
Explicit deferred debt blocks remain exact policy records; they never broaden
either immutable boundary or grandfather an event with a different missing
field set.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "contracts" / "EXPERIMENT_REGISTRY_APPEND_COMPATIBILITY_POLICY_V1.json"


class AppendCompatibilityError(ValueError):
    """A fail-closed validation error with a stable machine-readable prefix."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppendCompatibilityError(f"POLICY_LOAD_FAILED:{exc}") from exc
    if not isinstance(policy, dict):
        raise AppendCompatibilityError("POLICY_NOT_OBJECT")
    return policy


POLICY = _load_policy()
BUILDER_PATH = Path(POLICY["official_builder"]["path"])
EXPECTED_BUILDER_SHA256 = POLICY["official_builder"]["sha256"]


def _load_official_builder() -> Any:
    try:
        actual_sha = _sha256_bytes(BUILDER_PATH.read_bytes())
    except OSError as exc:
        raise AppendCompatibilityError(f"OFFICIAL_BUILDER_READ_FAILED:{exc}") from exc
    if actual_sha != EXPECTED_BUILDER_SHA256:
        raise AppendCompatibilityError(
            f"OFFICIAL_BUILDER_SHA256_MISMATCH:{actual_sha}:{EXPECTED_BUILDER_SHA256}"
        )
    spec = importlib.util.spec_from_file_location(
        "experiment_registry_official_builder_v1", BUILDER_PATH
    )
    if spec is None or spec.loader is None:
        raise AppendCompatibilityError("OFFICIAL_BUILDER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OFFICIAL = _load_official_builder()


def _fail(code: str, *parts: Any) -> None:
    suffix = ":" + ":".join(str(part) for part in parts) if parts else ""
    raise AppendCompatibilityError(code + suffix)


def _read_canonical_events(raw: bytes) -> list[dict[str, Any]]:
    if not isinstance(raw, bytes):
        _fail("RAW_NOT_BYTES")
    if not raw:
        _fail("REGISTRY_EMPTY")
    if not raw.endswith(b"\n"):
        _fail("REGISTRY_NOT_NEWLINE_TERMINATED")
    lines = raw.split(b"\n")
    if lines[-1] != b"":
        _fail("REGISTRY_FINAL_DELIMITER_INVALID")
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines[:-1]):
        if not line:
            _fail("BLANK_REGISTRY_LINE", index)
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            _fail("REGISTRY_NOT_UTF8", index, exc)
        try:
            event = json.loads(text)
        except json.JSONDecodeError as exc:
            _fail("INVALID_REGISTRY_JSON", index, exc.msg)
        if not isinstance(event, dict):
            _fail("EVENT_NOT_OBJECT", index)
        if _canonical_json(event) != text:
            _fail("NON_CANONICAL_REGISTRY_LINE", index)
        events.append(event)
    return events


def _legacy_debt_fields(event: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """Mirror the official debt predicates, including nested metric fields."""

    required = tuple(OFFICIAL.REQUIRED_FIELDS)
    missing = [field for field in required if field not in event]
    if missing:
        return "REQUIRED_FIELDS_MISSING", missing

    input_identity = event.get("input_identity")
    null_reasons: Mapping[str, Any] = {}
    if isinstance(input_identity, dict) and isinstance(input_identity.get("null_reasons"), dict):
        null_reasons = input_identity["null_reasons"]

    null_missing: list[str] = []
    for field in required:
        if field in {"event_sha256", "previous_event_sha256"}:
            continue
        if event.get(field) is None and field not in null_reasons:
            null_missing.append(field)

    metrics = event.get("deterministic_metrics")
    if isinstance(metrics, dict):
        for field in ("truth_positive_denominator", "selection_slots"):
            dotted = f"deterministic_metrics.{field}"
            if field not in metrics:
                null_missing.append(dotted)
            elif metrics[field] is None and dotted not in null_reasons:
                null_missing.append(dotted)
    elif metrics is None and "deterministic_metrics" not in null_reasons:
        null_missing.append("deterministic_metrics")

    if null_missing:
        return "NULL_REASON_MISSING", null_missing
    return None, []


def _debt_records(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        kind, fields = _legacy_debt_fields(event)
        if kind is not None:
            records.append(
                {
                    "index_0": index,
                    "index_1": index + 1,
                    "kind": kind,
                    "fields": fields,
                }
            )
    return records


def _debt_records_sha256(events: Iterable[Mapping[str, Any]]) -> str:
    payload = _canonical_json(_debt_records(events)).encode("utf-8")
    return _sha256_bytes(payload)


def _ranges_one_based(values: Iterable[int]) -> list[list[int]]:
    ordered = sorted(values)
    if not ordered:
        return []
    result: list[list[int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        result.append([start, previous])
        start = previous = value
    result.append([start, previous])
    return result


def _validate_legacy_debt_fingerprint(prefix_events: list[dict[str, Any]]) -> dict[str, Any]:
    debt = POLICY["legacy_schema_debt"]
    records = _debt_records(prefix_events)
    required = [record["index_1"] for record in records if record["kind"] == "REQUIRED_FIELDS_MISSING"]
    null_reason = [record["index_1"] for record in records if record["kind"] == "NULL_REASON_MISSING"]
    missing_ids = [
        index + 1
        for index, event in enumerate(prefix_events)
        if "registry_event_id" not in event or event.get("registry_event_id") is None
    ]
    nonempty_ids = [event.get("registry_event_id") for event in prefix_events if event.get("registry_event_id")]
    observed = {
        "events_with_debt": len(records),
        "required_fields_missing": len(required),
        "null_reason_missing": len(null_reason),
        "missing_or_null_registry_event_id": len(missing_ids),
        "nonempty_registry_event_id": len(nonempty_ids),
        "required_fields_missing_ranges": _ranges_one_based(required),
        "null_reason_missing_ranges": _ranges_one_based(null_reason),
        "records_sha256": _debt_records_sha256(prefix_events),
    }
    expected = {
        key: debt[key]
        for key in (
            "events_with_debt",
            "required_fields_missing",
            "null_reason_missing",
            "missing_or_null_registry_event_id",
            "nonempty_registry_event_id",
            "required_fields_missing_ranges",
            "null_reason_missing_ranges",
            "records_sha256",
        )
    }
    if observed != expected:
        _fail("LEGACY_SCHEMA_DEBT_FINGERPRINT_MISMATCH", _canonical_json(observed))
    if len(set(nonempty_ids)) != len(nonempty_ids):
        _fail("LEGACY_NONEMPTY_REGISTRY_EVENT_ID_DUPLICATE")
    return observed


def _deferred_debts() -> list[dict[str, Any]]:
    """Return the frozen debt blocks in policy order.

    The original ``deferred_suffix_debt`` key is retained byte-for-byte in
    meaning for compatibility with the first repair.  New blocks must be
    listed explicitly under ``additional_deferred_suffix_debts`` so a policy
    review can see the exact extra boundary instead of an open-ended rule.
    """

    blocks: list[dict[str, Any]] = []
    original = POLICY.get("deferred_suffix_debt")
    if original is not None:
        if not isinstance(original, dict):
            _fail("DEFERRED_SUFFIX_POLICY_INVALID")
        blocks.append(original)
    additional = POLICY.get("additional_deferred_suffix_debts", [])
    if not isinstance(additional, list):
        _fail("ADDITIONAL_DEFERRED_SUFFIX_POLICY_INVALID")
    for block in additional:
        if not isinstance(block, dict):
            _fail("ADDITIONAL_DEFERRED_SUFFIX_POLICY_INVALID")
        blocks.append(block)
    return blocks


def _deferred_suffix_targets_for_debt(debt: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    if not isinstance(debt, dict):
        return {}
    targets = debt.get("targets")
    if not isinstance(targets, list):
        _fail("DEFERRED_SUFFIX_POLICY_INVALID")
    expected_count = debt.get("event_count")
    if not isinstance(expected_count, int) or expected_count != len(targets) or expected_count <= 0:
        _fail("DEFERRED_SUFFIX_TARGET_COUNT_INVALID")
    result: dict[int, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict):
            _fail("DEFERRED_SUFFIX_TARGET_INVALID")
        line = target.get("line")
        if not isinstance(line, int) or line in result:
            _fail("DEFERRED_SUFFIX_TARGET_LINE_INVALID", line)
        result[line] = target
    lines = sorted(result)
    line_range = debt.get("line_range_1_based")
    if (
        not isinstance(line_range, list)
        or len(line_range) != 2
        or not all(isinstance(value, int) for value in line_range)
        or line_range[0] > line_range[1]
        or lines != list(range(line_range[0], line_range[1] + 1))
    ):
        _fail("DEFERRED_SUFFIX_TARGET_LINES_INVALID")
    if len(lines) != expected_count:
        _fail("DEFERRED_SUFFIX_TARGET_COUNT_INVALID")
    return result


def _deferred_suffix_targets() -> dict[int, dict[str, Any]]:
    """Return the original fourteen-event target map for compatibility."""

    debt = POLICY.get("deferred_suffix_debt")
    if not isinstance(debt, dict):
        return {}
    return _deferred_suffix_targets_for_debt(debt)


def _validate_deferred_block_anchor(
    raw: bytes,
    events: list[dict[str, Any]],
    debt: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    anchor = debt.get("anchor")
    if not isinstance(anchor, dict):
        _fail("DEFERRED_SUFFIX_ANCHOR_POLICY_INVALID")
    try:
        count = int(anchor["event_count"])
        size = int(anchor["size_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        _fail("DEFERRED_SUFFIX_ANCHOR_POLICY_INVALID", exc)
    if len(events) < count:
        return {}
    prefix_raw = raw[:size]
    if len(prefix_raw) != size:
        _fail("DEFERRED_SUFFIX_ANCHOR_SIZE_MISMATCH", len(prefix_raw), debt.get("block_id", ""))
    observed_sha = _sha256_bytes(prefix_raw)
    if observed_sha != anchor["sha256"]:
        _fail("DEFERRED_SUFFIX_ANCHOR_SHA256_MISMATCH", observed_sha)
    if prefix_raw.count(b"\n") != count:
        _fail("DEFERRED_SUFFIX_ANCHOR_NEWLINE_COUNT_MISMATCH", prefix_raw.count(b"\n"))
    if events[count - 1].get("event_sha256") != anchor["head_event_sha256"]:
        _fail("DEFERRED_SUFFIX_ANCHOR_HEAD_MISMATCH", events[count - 1].get("event_sha256"))
    targets = _deferred_suffix_targets_for_debt(debt)
    missing_fields_exactly = list(debt.get("missing_fields_exactly", []))
    for line, target in targets.items():
        if line > len(events):
            _fail("DEFERRED_SUFFIX_TARGET_LINE_MISSING", line)
        event = events[line - 1]
        if event.get("registry_event_id") != target.get("registry_event_id"):
            _fail("DEFERRED_SUFFIX_TARGET_ID_MISMATCH", line)
        if event.get("execution_id") != target.get("execution_id"):
            _fail("DEFERRED_SUFFIX_TARGET_EXECUTION_MISMATCH", line)
        if event.get("event_type") != target.get("event_type"):
            _fail("DEFERRED_SUFFIX_TARGET_EVENT_TYPE_MISMATCH", line)
        if event.get("event_sha256") != target.get("event_sha256"):
            _fail("DEFERRED_SUFFIX_TARGET_SHA_MISMATCH", line)
        missing = [field for field in OFFICIAL.REQUIRED_FIELDS if field not in event]
        if missing != missing_fields_exactly:
            _fail("DEFERRED_SUFFIX_MISSING_FIELD_SCOPE_INVALID", line, missing)
    decorated: dict[int, dict[str, Any]] = {}
    for line, target in targets.items():
        decorated[line] = {
            **target,
            "_deferred_block_id": debt.get("block_id", "deferred_suffix_debt"),
            "_deferred_debt": debt,
            "_deferred_missing_fields": missing_fields_exactly,
        }
    return decorated


def _validate_deferred_anchor(raw: bytes, events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for debt in _deferred_debts():
        block_targets = _validate_deferred_block_anchor(raw, events, debt)
        for line, target in block_targets.items():
            if line in merged:
                _fail("DEFERRED_SUFFIX_TARGET_LINE_OVERLAP", line)
            merged[line] = target
    return merged


def _validate_grandfathered_current_snapshot(raw: bytes, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify the exact current snapshot before enforcing the strict suffix.

    The 644-event prefix remains the original schema-debt boundary.  The
    current root snapshot is a second immutable boundary: its bytes and chain
    identity are pinned, while its pre-existing missing fields stay
    ``CANNOT_CONFIRM``.  Only lines after the snapshot are subject to the
    official event and correction validators.
    """

    snapshot = POLICY.get("grandfathered_current_snapshot")
    if not isinstance(snapshot, dict):
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_POLICY_MISSING")
    anchor = snapshot.get("anchor")
    if not isinstance(anchor, dict):
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_ANCHOR_INVALID")
    try:
        count = int(anchor["event_count"])
        size = int(anchor["size_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_ANCHOR_INVALID", exc)
    if count <= 0 or size <= 0:
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_ANCHOR_INVALID")
    if len(events) < count:
        _fail("REGISTRY_EVENT_COUNT_BELOW_GRANDFATHERED_SNAPSHOT", len(events), count)
    snapshot_raw = raw[:size]
    if len(snapshot_raw) != size:
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_SIZE_MISMATCH", len(snapshot_raw), size)
    observed_sha = _sha256_bytes(snapshot_raw)
    if observed_sha != anchor.get("sha256"):
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_SHA256_MISMATCH", observed_sha)
    if snapshot_raw.count(b"\n") != count:
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_NEWLINE_COUNT_MISMATCH", snapshot_raw.count(b"\n"), count)
    observed_head = events[count - 1].get("event_sha256")
    if observed_head != anchor.get("head_event_sha256"):
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_HEAD_MISMATCH", observed_head)
    line_range = snapshot.get("line_range_1_based")
    if line_range != [645, count]:
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_LINE_RANGE_INVALID", line_range)
    suffix_start = snapshot.get("strict_suffix_start_line_1_based")
    if suffix_start != count + 1:
        _fail("GRANDFATHERED_CURRENT_SNAPSHOT_SUFFIX_START_INVALID", suffix_start)
    return {
        "event_count": count,
        "size_bytes": size,
        "sha256": observed_sha,
        "head_event_sha256": observed_head,
        "line_range_1_based": line_range,
        "strict_suffix_start_line_1_based": suffix_start,
        "preexisting_schema_status": snapshot.get(
            "preexisting_schema_status", "FULL_LEGACY_SCHEMA_VALIDATION=CANNOT_CONFIRM_PREEXISTING_DEBT"
        ),
    }


def _validate_required_deferred_corrections(
    events: list[dict[str, Any]],
    targets: dict[int, dict[str, Any]],
) -> None:
    if not targets:
        return
    blocks: dict[str, dict[str, Any]] = {}
    for target in targets.values():
        block_id = str(target.get("_deferred_block_id", "deferred_suffix_debt"))
        block = blocks.setdefault(block_id, {"debt": target["_deferred_debt"], "targets": []})
        block["targets"].append(target)

    for block in blocks.values():
        debt = block["debt"]
        block_targets = block["targets"]
        required_fields = list(debt.get("required_correction_fields_exactly", []))
        suffix = debt.get("correction_id_suffix")
        if not isinstance(suffix, str) or not suffix:
            _fail("DEFERRED_SUFFIX_CORRECTION_SUFFIX_INVALID")
        by_sha = {target["event_sha256"]: target for target in block_targets}
        by_id = {target["registry_event_id"]: target for target in block_targets}
        event_by_sha = {
            event.get("event_sha256"): event
            for event in events
            if isinstance(event.get("event_sha256"), str)
        }
        expected_ids = {target["registry_event_id"] + suffix for target in block_targets}
        seen: dict[str, list[dict[str, Any]]] = {event_id: [] for event_id in expected_ids}
        anchor_count = int(debt["anchor"]["event_count"])
        for event in events[anchor_count:]:
            metrics = event.get("deterministic_metrics")
            if not isinstance(metrics, dict):
                continue
            target_sha = metrics.get("corrects_event_sha256")
            target_id = metrics.get("corrects_registry_event_id")
            if target_sha not in by_sha and target_id not in by_id:
                continue
            if target_sha not in by_sha or target_id != by_sha[target_sha]["registry_event_id"]:
                _fail("DEFERRED_CORRECTION_TARGET_INVALID", event.get("registry_event_id"))
            expected_id = target_id + suffix
            if event.get("registry_event_id") != expected_id:
                _fail("DEFERRED_CORRECTION_ID_INVALID", event.get("registry_event_id"))
            if event.get("route_id") != debt.get("route_id"):
                _fail("DEFERRED_CORRECTION_ROUTE_INVALID", event.get("registry_event_id"))
            if event.get("execution_id") != by_id[target_id]["execution_id"]:
                _fail("DEFERRED_CORRECTION_EXECUTION_INVALID", event.get("registry_event_id"))
            if metrics.get("corrected_fields") != required_fields:
                _fail("DEFERRED_CORRECTION_FIELDS_INVALID", event.get("registry_event_id"))
            config_null_reason = debt.get("config_null_reason")
            if config_null_reason is not None:
                target_event = event_by_sha.get(target_sha)
                target_safety = target_event.get("safety") if isinstance(target_event, dict) else None
                if not isinstance(target_safety, dict):
                    _fail("DEFERRED_CORRECTION_TARGET_SAFETY_INVALID", event.get("registry_event_id"))
                expected_corrected_values = {
                    "config_sha256": None,
                    "config_sha256_reason": config_null_reason,
                    "research_only": target_safety.get("RESEARCH_ONLY"),
                    "production_allowed": target_safety.get("production_allowed"),
                    "buy_gate_updated": target_safety.get("buy_gate_updated"),
                    "orders_sent": target_safety.get("orders_sent"),
                }
                if any(
                    expected_corrected_values[field] is None
                    for field in ("research_only", "production_allowed", "buy_gate_updated", "orders_sent")
                ):
                    _fail("DEFERRED_CORRECTION_TARGET_SAFETY_INVALID", event.get("registry_event_id"))
                input_identity = event.get("input_identity")
                null_reasons = input_identity.get("null_reasons") if isinstance(input_identity, dict) else None
                if not isinstance(null_reasons, dict) or null_reasons.get("config_sha256") != config_null_reason:
                    _fail("DEFERRED_CORRECTION_CONFIG_NULL_REASON_INVALID", event.get("registry_event_id"))
                if not isinstance(input_identity, dict) or input_identity.get("corrected_values") != expected_corrected_values:
                    _fail("DEFERRED_CORRECTION_INPUT_IDENTITY_VALUES_INVALID", event.get("registry_event_id"))
                if metrics.get("corrected_values") != expected_corrected_values:
                    _fail("DEFERRED_CORRECTION_METRIC_VALUES_INVALID", event.get("registry_event_id"))
                if any(
                    event.get(field) != expected_corrected_values[field]
                    for field in ("research_only", "production_allowed", "buy_gate_updated", "orders_sent")
                ) or event.get("config_sha256") is not None:
                    _fail("DEFERRED_CORRECTION_TOP_LEVEL_VALUES_INVALID", event.get("registry_event_id"))
            seen[expected_id].append(event)
        missing = sorted(event_id for event_id, matches in seen.items() if not matches)
        duplicate = sorted(event_id for event_id, matches in seen.items() if len(matches) > 1)
        if missing:
            _fail("REQUIRED_CORRECTION_SET_MISSING", ",".join(missing))
        if duplicate:
            _fail("REQUIRED_CORRECTION_SET_DUPLICATE", ",".join(duplicate))


def _validate_chain_and_suffix(
    events: list[dict[str, Any]],
    prefix_count: int,
    deferred_targets: dict[int, dict[str, Any]] | None = None,
) -> None:
    previous_sha = OFFICIAL.ZERO_SHA256
    prior_events_by_sha: dict[str, dict[str, Any]] = {}
    nonempty_ids: set[str] = set()
    execution_ids: dict[str, int] = {}
    for index, event in enumerate(events):
        expected_previous = previous_sha
        if event.get("previous_event_sha256") != expected_previous:
            _fail("PREVIOUS_HASH_INVALID", index)
        try:
            computed_sha = OFFICIAL._event_sha256(event)
        except Exception as exc:  # pragma: no cover - defensive boundary
            _fail("EVENT_HASH_COMPUTE_FAILED", index, exc)
        if event.get("event_sha256") != computed_sha:
            _fail("EVENT_HASH_INVALID", index)

        registry_event_id = event.get("registry_event_id")
        if registry_event_id is None or registry_event_id == "":
            if index >= prefix_count:
                _fail("SUFFIX_REGISTRY_EVENT_ID_MISSING", index)
        elif not isinstance(registry_event_id, str):
            _fail("REGISTRY_EVENT_ID_INVALID", index)
        elif registry_event_id in nonempty_ids:
            _fail("REGISTRY_EVENT_ID_DUPLICATE", index, registry_event_id)
        else:
            nonempty_ids.add(registry_event_id)

        execution_id = event.get("execution_id")
        deferred_target = (deferred_targets or {}).get(index + 1)
        if index >= prefix_count:
            try:
                if deferred_target is not None:
                    missing = [field for field in OFFICIAL.REQUIRED_FIELDS if field not in event]
                    if missing != list(deferred_target.get("_deferred_missing_fields", [])):
                        _fail("DEFERRED_SUFFIX_MISSING_FIELD_SCOPE_INVALID", index + 1, missing)
                else:
                    OFFICIAL._validate_event(event, previous_sha, index)
                    OFFICIAL._validate_correction_event(event, prior_events_by_sha, index)
            except Exception as exc:
                if isinstance(exc, AppendCompatibilityError):
                    raise
                _fail("SUFFIX_OFFICIAL_VALIDATION_FAILED", index, exc)
            if execution_id in execution_ids and not OFFICIAL._execution_reuse_allowed(event):
                _fail("EXECUTION_ID_REUSE_NOT_LIFECYCLE", index, execution_id)
        if execution_id is not None:
            execution_ids.setdefault(execution_id, index)
        prior_events_by_sha[event["event_sha256"]] = event
        previous_sha = event["event_sha256"]
    _validate_required_deferred_corrections(events, deferred_targets or {})


def validate_registry_bytes(raw: bytes, *, source: str = "<bytes>") -> dict[str, Any]:
    """Validate current raw bytes or a post-append candidate entirely in memory."""

    events = _read_canonical_events(raw)
    legacy = POLICY["legacy_prefix"]
    prefix_size = int(legacy["size_bytes"])
    prefix_count = int(legacy["event_count"])
    if len(events) < prefix_count:
        _fail("REGISTRY_EVENT_COUNT_BELOW_LEGACY_BOUNDARY", len(events))
    prefix_raw = raw[:prefix_size]
    if len(prefix_raw) != prefix_size:
        _fail("LEGACY_PREFIX_SIZE_MISMATCH", len(prefix_raw))
    if _sha256_bytes(prefix_raw) != legacy["sha256"]:
        _fail("LEGACY_PREFIX_SHA256_MISMATCH", _sha256_bytes(prefix_raw))
    if prefix_raw.count(b"\n") != prefix_count:
        _fail("LEGACY_PREFIX_NEWLINE_COUNT_MISMATCH", prefix_raw.count(b"\n"))
    prefix_events = events[:prefix_count]
    if prefix_events[-1].get("event_sha256") != legacy["head_event_sha256"]:
        _fail("LEGACY_PREFIX_HEAD_MISMATCH", prefix_events[-1].get("event_sha256"))
    debt_observed = _validate_legacy_debt_fingerprint(prefix_events)
    current_snapshot = _validate_grandfathered_current_snapshot(raw, events)
    deferred_targets = _validate_deferred_anchor(raw, events)
    _validate_chain_and_suffix(events, current_snapshot["event_count"], deferred_targets)
    result = {
        "source": source,
        "events": len(events),
        "legacy_prefix_events": prefix_count,
        "suffix_events": len(events) - prefix_count,
        "legacy_prefix_sha256": _sha256_bytes(prefix_raw),
        "grandfathered_current_snapshot": current_snapshot,
        "strict_suffix_start_line_1_based": current_snapshot["strict_suffix_start_line_1_based"],
        "registry_sha256": _sha256_bytes(raw),
        "registry_bytes": len(raw),
        "newline_terminated": True,
        "legacy_debt": debt_observed,
        "deferred_suffix_debt": {
            "target_events": len(deferred_targets),
            "required_corrections": len(deferred_targets) if deferred_targets else 0,
            "required_corrections_satisfied": bool(deferred_targets),
        },
        "FULL_LEGACY_SCHEMA_VALIDATION": "CANNOT_CONFIRM_PREEXISTING_DEBT",
        "APPEND_COMPATIBILITY": "PASS",
        "official_builder_sha256": EXPECTED_BUILDER_SHA256,
    }
    return result


def validate_registry_path(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        _fail("REGISTRY_READ_FAILED", candidate, exc)
    return validate_registry_bytes(raw, source=str(candidate))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path, help="raw registry or candidate bytes to validate")
    args = parser.parse_args(argv)
    try:
        result = validate_registry_path(args.registry)
    except AppendCompatibilityError as exc:
        print(json.dumps({"APPEND_COMPATIBILITY": "CANNOT_CONFIRM", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
