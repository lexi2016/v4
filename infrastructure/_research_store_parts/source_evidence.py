"""infrastructure.research_store: source_evidence (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__verify_source_ref_body(_v4_scope, /, cls, ref, *, expected_target_trade_date):
    path_value = ref.get("path")
    if not _v4_global(_v4_scope, 'isinstance')(path_value, _v4_global(_v4_scope, 'str')) or not path_value:
        raise _v4_global(_v4_scope, 'ValueError')("selection source path is missing")
    path = _v4_global(_v4_scope, 'Path')(path_value)
    if not path.is_file() or path.is_symlink():
        raise _v4_global(_v4_scope, 'ValueError')("selection source file is unavailable")
    raw = path.read_bytes()
    raw_sha = _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest()
    if raw_sha != _v4_global(_v4_scope, 'str')(ref.get("raw_sha256") or "").lower():
        raise _v4_global(_v4_scope, 'ValueError')("selection source raw SHA mismatch")
    try:
        document = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
    except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'ValueError')("selection source JSON is invalid") from error
    if ref.get("type") == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'):
        _v4_global(_v4_scope, 'validate_research_supply_envelope')(
            document,
            expected_target_trade_date=expected_target_trade_date,
        )
        pointer = ref.get("json_pointer")
        if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 're').fullmatch(
            r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
        ):
            raise _v4_global(_v4_scope, 'ValueError')("research supply source JSON pointer must target event card")
        selected = cls._pointer_value(document, pointer)
        if not _v4_global(_v4_scope, 'isinstance')(selected, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("research supply selected card is invalid")
        if ref.get("source_date") != document.get("source_date"):
            raise _v4_global(_v4_scope, 'ValueError')("research supply source date mismatch")
        if (
            expected_target_trade_date is not None
            and document.get("target_trade_date") != expected_target_trade_date
        ):
            raise _v4_global(_v4_scope, 'ValueError')("research supply target date mismatch")
        if ref.get("frozen_payload_sha256") != document.get("frozen_payload_sha256"):
            raise _v4_global(_v4_scope, 'ValueError')("research supply frozen SHA mismatch")
        source_time = ref.get("source_time")
        if source_time != document.get("generated_at"):
            raise _v4_global(_v4_scope, 'ValueError')("research supply source_time does not match envelope")
        receipt_path_value = ref.get("supply_receipt_path")
        if not _v4_global(_v4_scope, 'isinstance')(receipt_path_value, _v4_global(_v4_scope, 'str')) or not receipt_path_value:
            raise _v4_global(_v4_scope, 'ValueError')("research supply receipt path is missing")
        receipt_path = _v4_global(_v4_scope, 'Path')(receipt_path_value)
        if not receipt_path.is_file() or receipt_path.is_symlink():
            raise _v4_global(_v4_scope, 'ValueError')("research supply receipt is unavailable")
        receipt_raw = receipt_path.read_bytes()
        receipt_sha = _v4_global(_v4_scope, 'hashlib').sha256(receipt_raw).hexdigest()
        if receipt_sha != _v4_global(_v4_scope, 'str')(ref.get("supply_receipt_sha256") or "").lower():
            raise _v4_global(_v4_scope, 'ValueError')("research supply receipt SHA mismatch")
        try:
            receipt = _v4_global(_v4_scope, 'json').loads(receipt_raw.decode("utf-8"))
        except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
            raise _v4_global(_v4_scope, 'ValueError')("research supply receipt is invalid JSON") from error
        _v4_global(_v4_scope, 'validate_research_supply_receipt')(
            receipt,
            envelope=document,
            artifact_path=_v4_global(_v4_scope, 'str')(path),
            artifact_sha256=raw_sha,
        )
        return {
            "card": selected,
            "document": document,
            "supply_receipt": receipt,
            "kind": _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'),
        }
    pointer = _v4_global(_v4_scope, 'str')(ref.get("json_pointer") or "")
    if not _v4_global(_v4_scope, 're').fullmatch(
        r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection source JSON pointer must target frozen event card")
    selected = cls._pointer_value(document, pointer)
    frozen_payload = cls._pointer_value(document, "/frozen_payload")
    if not _v4_global(_v4_scope, 'isinstance')(selected, _v4_global(_v4_scope, 'Mapping')) or not selected.get("event_id") or not _v4_global(_v4_scope, 'isinstance')(selected.get("entities"), _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("selection source selected card is invalid")
    frozen = _v4_global(_v4_scope, 'hashlib').sha256(
        _v4_global(_v4_scope, 'json').dumps(
            frozen_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if frozen != _v4_global(_v4_scope, 'str')(ref.get("frozen_payload_sha256") or "").lower():
        raise _v4_global(_v4_scope, 'ValueError')("selection source frozen SHA mismatch")
    source_date = _v4_global(_v4_scope, 'str')(ref.get("source_date") or "")
    document_source_date = document.get("source_date")
    if document_source_date is None and _v4_global(_v4_scope, 'isinstance')(frozen_payload, _v4_global(_v4_scope, 'Mapping')):
        document_source_date = frozen_payload.get("source_date")
    if document_source_date is None or _v4_global(_v4_scope, 'str')(document_source_date) != source_date:
        raise _v4_global(_v4_scope, 'ValueError')("selection source date mismatch")
    document_target_date = document.get("target_trade_date")
    if document_target_date is None and _v4_global(_v4_scope, 'isinstance')(frozen_payload, _v4_global(_v4_scope, 'Mapping')):
        document_target_date = frozen_payload.get("target_trade_date")
    if document_target_date is None:
        raise _v4_global(_v4_scope, 'ValueError')("selection source target date is missing")
    if (
        expected_target_trade_date is not None
        and _v4_global(_v4_scope, 'str')(document_target_date) != expected_target_trade_date
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection source target date mismatch")
    document_generated_at = document.get("generated_at")
    if document_generated_at is None:
        raise _v4_global(_v4_scope, 'ValueError')("selection source generated_at is missing")
    try:
        expected_time = _v4_global(_v4_scope, 'datetime').fromisoformat(
            _v4_global(_v4_scope, 'str')(ref.get("source_time") or "").replace("Z", "+00:00")
        )
        actual_time = _v4_global(_v4_scope, 'datetime').fromisoformat(
            _v4_global(_v4_scope, 'str')(document_generated_at).replace("Z", "+00:00")
        )
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("selection source generated_at is invalid") from error
    if (
        expected_time.tzinfo is None
        or expected_time.utcoffset() is None
        or actual_time.tzinfo is None
        or actual_time.utcoffset() is None
        or expected_time.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
        != actual_time.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection source_time does not match source envelope")
    return {"card": selected, "document": document}


def _ResearchSelectionStore__source_ref_identity_body(_v4_scope, /, cls, ref):
    """Return immutable locator fields used by formal proof bindings."""

    return _v4_global(_v4_scope, 'tuple')(
        cls._selection_identity_text(ref.get(field))
        for field in (
            "path",
            "raw_sha256",
            "frozen_payload_sha256",
            "json_pointer",
            "source_date",
            "source_time",
        )
    )


def _ResearchSelectionStore__verify_formal_candidate_bindings_body(_v4_scope, /, cls, document, *, candidates_by_id, candidate_ids, label):
    """Bind formal proof rows to the exact frozen source locators."""

    bindings = document.get("candidate_bindings")
    if not _v4_global(_v4_scope, 'isinstance')(bindings, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(bindings) != _v4_global(_v4_scope, 'len')(candidate_ids):
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding is incomplete")
    seen: list[str] = []
    for binding in bindings:
        if not _v4_global(_v4_scope, 'isinstance')(binding, _v4_global(_v4_scope, 'Mapping')) or not {
            "candidate_id",
            "eligibility",
            "pit_status",
            "source_refs",
        }.issubset(binding):
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding is invalid")
        candidate_id = binding.get("candidate_id")
        if candidate_id not in candidates_by_id or candidate_id in seen:
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding identity is invalid")
        seen.append(candidate_id)
        candidate = candidates_by_id[candidate_id]
        if (
            binding.get("eligibility") != candidate.get("eligibility")
            or binding.get("pit_status") != candidate.get("pit_status")
        ):
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source proof status mismatch")
        source_refs = binding.get("source_refs")
        candidate_refs = candidate.get("source_refs")
        if (
            not _v4_global(_v4_scope, 'isinstance')(source_refs, _v4_global(_v4_scope, 'list'))
            or not _v4_global(_v4_scope, 'isinstance')(candidate_refs, _v4_global(_v4_scope, 'list'))
            or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) for ref in source_refs)
            or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) for ref in candidate_refs)
        ):
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding refs are invalid")
        if [cls._source_ref_identity(ref) for ref in source_refs] != [
            cls._source_ref_identity(ref) for ref in candidate_refs
        ]:
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding refs mismatch")
    if seen != candidate_ids:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding order mismatch")


def _ResearchSelectionStore__verify_auxiliary_ref_body(_v4_scope, /, cls, ref, label, *, schema_version, expected_type, source_date, target_trade_date, candidate_ids, source_sha256, expected_run_id):
    if not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(ref.get("path"), _v4_global(_v4_scope, 'str')) or not ref["path"]:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} reference is missing")
    path = _v4_global(_v4_scope, 'Path')(ref["path"])
    if not path.is_file() or path.is_symlink() or cls._raw_sha(path) != _v4_global(_v4_scope, 'str')(ref.get("sha256") or "").lower():
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} reference SHA mismatch")
    if schema_version is None and expected_type is None:
        return None
    try:
        document = _v4_global(_v4_scope, 'json').loads(path.read_bytes().decode("utf-8"))
    except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document is not valid JSON") from error
    if not _v4_global(_v4_scope, 'isinstance')(document, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document is not an object")
    required = {
        "schema_version",
        "type",
        "source_sha256",
        "source_date",
        "target_trade_date",
        "run_id",
        "candidate_ids",
    }
    if not required.issubset(document):
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document schema is incomplete")
    if schema_version is not None and document.get("schema_version") != schema_version:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document schema is invalid")
    if expected_type is not None and document.get("type") != expected_type:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document type is invalid")
    if source_sha256 is not None and document.get("source_sha256") != source_sha256:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document source binding mismatch")
    if source_date is not None and document.get("source_date") != source_date:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document source date mismatch")
    if target_trade_date is not None and document.get("target_trade_date") != target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document target date mismatch")
    if expected_run_id is not None and document.get("run_id") != expected_run_id:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document run binding mismatch")
    if candidate_ids is not None and document.get("candidate_ids") != candidate_ids:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} document candidate binding mismatch")
    return document
