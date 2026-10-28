"""infrastructure.research_store: overlay_references (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __manager_overlay_changed_paths_body(_v4_scope, /, before, after, prefix):
    """Return deterministic leaf/container paths for an evidence diff."""

    changed: list[str] = []
    if _v4_global(_v4_scope, 'isinstance')(before, _v4_global(_v4_scope, 'Mapping')) and _v4_global(_v4_scope, 'isinstance')(after, _v4_global(_v4_scope, 'Mapping')):
        for key in _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(before) | _v4_global(_v4_scope, 'set')(after)):
            path = f"{prefix}.{key}" if prefix else _v4_global(_v4_scope, 'str')(key)
            if key not in before or key not in after:
                changed.append(path)
            else:
                changed.extend(_v4_global(_v4_scope, '_manager_overlay_changed_paths')(before[key], after[key], path))
        return changed
    if _v4_global(_v4_scope, 'isinstance')(before, _v4_global(_v4_scope, 'list')) and _v4_global(_v4_scope, 'isinstance')(after, _v4_global(_v4_scope, 'list')):
        if before != after:
            changed.append(prefix)
        return changed
    if before != after:
        changed.append(prefix)
    return changed


def _ResearchSelectionStore__read_manager_overlay_json_ref_body(_v4_scope, /, cls, ref, *, label):
    if not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(ref) != {"path", "raw_sha256"}:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} reference fields are invalid",
        )
    path_value = ref.get("path")
    raw_sha = ref.get("raw_sha256")
    if (
        not _v4_global(_v4_scope, 'isinstance')(path_value, _v4_global(_v4_scope, 'str'))
        or not path_value
        or not _v4_global(_v4_scope, 'isinstance')(raw_sha, _v4_global(_v4_scope, 'str'))
        or not _v4_global(_v4_scope, '_SHA256').fullmatch(raw_sha.lower())
    ):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} reference is invalid",
        )
    path = _v4_global(_v4_scope, 'Path')(path_value)
    if not path.is_file() or path.is_symlink():
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} file is unavailable",
        )
    raw = path.read_bytes()
    actual_sha = _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest()
    if actual_sha != raw_sha.lower():
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} raw SHA mismatch",
        )
    try:
        document = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
    except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} JSON is invalid",
        ) from error
    if not _v4_global(_v4_scope, 'isinstance')(document, _v4_global(_v4_scope, 'Mapping')):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} document is not an object",
        )
    return _v4_global(_v4_scope, 'dict')(document), actual_sha


def _ResearchSelectionStore__read_manager_overlay_supply_ref_body(_v4_scope, /, cls, ref, *, source_date, target_trade_date, label):
    if not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(ref) != _v4_global(_v4_scope, '_MANAGER_OVERLAY_SUPPLY_REF_FIELDS'):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} fields are invalid",
        )
    for field in ("path", "run_id", "source_date", "target_trade_date"):
        if not _v4_global(_v4_scope, 'isinstance')(ref.get(field), _v4_global(_v4_scope, 'str')) or not ref[field]:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} {field} is invalid",
            )
    for field in ("raw_sha256", "frozen_payload_sha256"):
        if not _v4_global(_v4_scope, 'isinstance')(ref.get(field), _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SHA256').fullmatch(ref[field].lower()):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} {field} is invalid",
            )
    path = _v4_global(_v4_scope, 'Path')(ref["path"])
    if not path.is_file() or path.is_symlink():
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} file is unavailable",
        )
    raw = path.read_bytes()
    if _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest() != ref["raw_sha256"].lower():
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} raw SHA mismatch",
        )
    try:
        document = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
    except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} JSON is invalid",
        ) from error
    if not _v4_global(_v4_scope, 'isinstance')(document, _v4_global(_v4_scope, 'Mapping')):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} document is not an object",
        )
    try:
        _v4_global(_v4_scope, 'validate_research_supply_envelope')(
            document,
            expected_source_date=source_date,
            expected_target_trade_date=target_trade_date,
            expected_run_id=ref["run_id"],
        )
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} envelope is invalid: {error}",
        ) from error
    if (
        document.get("frozen_payload_sha256")
        != ref["frozen_payload_sha256"].lower()
        or document.get("source_date") != ref["source_date"]
        or document.get("target_trade_date") != ref["target_trade_date"]
    ):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} binding mismatch",
        )
    return _v4_global(_v4_scope, 'dict')(document)


def _ResearchSelectionStore__read_manager_overlay_decision_body(_v4_scope, /, cls, payload, *, source_envelope, candidate_ids, label):
    ref = payload.get("manager_decision_ref")
    try:
        document, raw_sha = cls._read_manager_overlay_json_ref(ref, label=label)
        _v4_global(_v4_scope, 'validate_manager_research_decision')(
            document,
            candidate_ids=candidate_ids,
            supply_envelope=source_envelope,
        )
    except _v4_global(_v4_scope, 'ValueError') as error:
        if _v4_global(_v4_scope, 'str')(error).startswith("SOURCE_SUCCESSOR_PROOF_INVALID:"):
            raise
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} validation failed: {error}",
        ) from error
    if payload.get("manager_decision_ref", {}).get("raw_sha256") != raw_sha:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} product binding mismatch",
        )
    return document, raw_sha


def _ResearchSelectionStore__product_supply_refs_body(_v4_scope, /, cls, payload, *, label):
    result: dict[str, Mapping[str, Any]] = {}
    candidates = payload.get("research_candidates")
    if not _v4_global(_v4_scope, 'isinstance')(candidates, _v4_global(_v4_scope, 'list')):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"{label} candidates are invalid",
        )
    for candidate in candidates:
        candidate_id = _v4_global(_v4_scope, 'str')(candidate.get("candidate_id") or "")
        refs = candidate.get("source_refs")
        if not _v4_global(_v4_scope, 'isinstance')(refs, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(refs) != 1 or not _v4_global(_v4_scope, 'isinstance')(refs[0], _v4_global(_v4_scope, 'Mapping')):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} source binding is not one frozen supply ref per card",
            )
        ref = refs[0]
        if ref.get("type") != _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} source binding type is invalid",
            )
        if candidate_id in result:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} candidate is duplicated",
            )
        result[candidate_id] = ref
    return result


def _ResearchSelectionStore__manager_overlay_expected_projections_body(_v4_scope, /, decision):
    expected: dict[str, dict[str, Any]] = {}
    for role, field in (("CORE", "core"), ("CONDITIONAL", "conditional")):
        for order, row in _v4_global(_v4_scope, 'enumerate')(decision[field], 1):
            expected[_v4_global(_v4_scope, 'str')(row["candidate_id"])] = {
                "schema_version": decision["schema_version"],
                "phase": decision["phase"],
                "decision_state": decision["decision_state"],
                "source_date": decision["source_date"],
                "target_trade_date": decision["target_trade_date"],
                "run_id": decision["run_id"],
                "generated_at": decision["generated_at"],
                "cutoff_at": decision["cutoff_at"],
                "role": role,
                "order": order,
                "reason": row["reason"],
            }
    return expected


def _ResearchSelectionStore__validate_manager_overlay_proof_shape_body(_v4_scope, /, cls, proof, *, source_date, target_trade_date):
    if _v4_global(_v4_scope, 'set')(proof) != _v4_global(_v4_scope, '_MANAGER_OVERLAY_PROOF_FIELDS'):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof fields are not fixed",
        )
    if (
        proof.get("schema_version") != _v4_global(_v4_scope, '_MANAGER_OVERLAY_PROOF_SCHEMA_VERSION')
        or proof.get("type") != _v4_global(_v4_scope, '_MANAGER_OVERLAY_PROOF_TYPE')
        or proof.get("rule_id") != _v4_global(_v4_scope, '_MANAGER_OVERLAY_RULE_ID')
        or proof.get("rule_version") != _v4_global(_v4_scope, '_MANAGER_OVERLAY_RULE_VERSION')
        or proof.get("source_date") != source_date
        or proof.get("target_trade_date") != target_trade_date
    ):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof identity or rule binding is invalid",
        )
    candidate_ids = proof.get("candidate_ids")
    if (
        not _v4_global(_v4_scope, 'isinstance')(candidate_ids, _v4_global(_v4_scope, 'list'))
        or _v4_global(_v4_scope, 'len')(candidate_ids) != 124
        or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) or not item for item in candidate_ids)
        or candidate_ids != _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(candidate_ids))
        or proof.get("candidate_set_sha256")
        != cls._canonical_sha(candidate_ids)
    ):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof candidate set is invalid",
        )
    records = proof.get("records")
    if not _v4_global(_v4_scope, 'isinstance')(records, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(records) != _v4_global(_v4_scope, 'len')(candidate_ids):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof records are incomplete",
        )
    if proof.get("envelope_changed_paths") != _v4_global(_v4_scope, 'sorted')(
        _v4_global(_v4_scope, 'set')(proof.get("envelope_changed_paths") or [])
    ):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof envelope paths are not sorted and unique",
        )
    if not _v4_global(_v4_scope, 'set')(proof["envelope_changed_paths"]).issubset(
        _v4_global(_v4_scope, 'MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS')
    ):
        raise cls._manager_overlay_error(
            "OVERLAY_MUTATION_OUT_OF_SCOPE",
            "proof expands the envelope allowlist",
        )
    safety = proof.get("safety")
    expected_safety = {
        "RESEARCH_ONLY": True,
        "WATCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if _v4_global(_v4_scope, 'set')(safety or {}) != _v4_global(_v4_scope, '_MANAGER_OVERLAY_SAFETY_FIELDS') or safety != expected_safety:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof safety is invalid",
        )


def _ResearchSelectionStore__manager_overlay_time_body(_v4_scope, /, value, field):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid manager overlay {field}")
    try:
        parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(value.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid manager overlay {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid manager overlay {field} timezone")
    return parsed.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
