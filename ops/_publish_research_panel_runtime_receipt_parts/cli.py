"""ops.publish_research_panel_runtime_receipt: cli (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __assert_no_symlink_ancestors_body(_v4_scope, /, path):
    absolute = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').path.abspath(_v4_global(_v4_scope, 'str')(path)))
    current = _v4_global(_v4_scope, 'Path')(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = _v4_global(_v4_scope, 'os').lstat(current)
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            continue
        except _v4_global(_v4_scope, 'OSError') as error:
            raise _v4_global(_v4_scope, 'EvidenceError')("PATH_UNSAFE") from error
        if _v4_global(_v4_scope, 'stat').S_ISLNK(metadata.st_mode):
            raise _v4_global(_v4_scope, 'EvidenceError')("PATH_UNSAFE")


def __atomic_json_body(_v4_scope, /, path, payload):
    _v4_global(_v4_scope, '_assert_no_symlink_ancestors')(path.parent)
    if path.is_symlink():
        raise _v4_global(_v4_scope, 'EvidenceError')(f"OUTPUT_PATH_UNSAFE:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (_v4_global(_v4_scope, 'json').dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    handle, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(handle, "wb") as output:
            output.write(encoded)
            output.flush()
            _v4_global(_v4_scope, 'os').fsync(output.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __normalise_artifact_date_body(_v4_scope, /, value):
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'datetime'), _v4_global(_v4_scope, 'date_type'))):
        text = value.isoformat()
    else:
        text = _v4_global(_v4_scope, 'str')(value).strip()
    compact = _v4_global(_v4_scope, 're').sub(r"[^0-9]", "", text)
    candidate = compact[:8]
    if not _v4_global(_v4_scope, '_DATE').fullmatch(candidate):
        raise _v4_global(_v4_scope, 'EvidenceError')("POINTER_DATE_INVALID")
    try:
        _v4_global(_v4_scope, 'datetime').strptime(candidate, "%Y%m%d")
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'EvidenceError')("POINTER_DATE_INVALID") from error
    return candidate


def __artifact_dates_body(_v4_scope, /, path):
    """Read all valid date-column values from a pointed artifact."""

    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as parquet

            schema_names = _v4_global(_v4_scope, 'set')(parquet.read_schema(path).names)
            date_column = _v4_global(_v4_scope, 'next')(
                (name for name in ("trade_date", "target_date", "business_date", "signal_date") if name in schema_names),
                None,
            )
            if date_column is None:
                return _v4_global(_v4_scope, 'set')()
            values = parquet.read_table(path, columns=[date_column]).column(date_column).to_pylist()
            return {_v4_global(_v4_scope, '_normalise_artifact_date')(value) for value in values if value is not None}
        except _v4_global(_v4_scope, 'Exception') as error:
            raise _v4_global(_v4_scope, 'EvidenceError')(f"POINTER_ARTIFACT_UNREADABLE:{path}") from error
    try:
        payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'EvidenceError')(f"POINTER_ARTIFACT_UNREADABLE:{path}") from error
    values: set[str] = _v4_global(_v4_scope, 'set')()

    def visit(value: Any) -> None:
        if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
            for key, child in value.items():
                if key in _v4_global(_v4_scope, '_DATE_FIELDS') and child not in (None, ""):
                    if _v4_global(_v4_scope, 'isinstance')(child, _v4_global(_v4_scope, 'list')):
                        values.update(_v4_global(_v4_scope, '_normalise_artifact_date')(item) for item in child if item not in (None, ""))
                    else:
                        values.add(_v4_global(_v4_scope, '_normalise_artifact_date')(child))
                if _v4_global(_v4_scope, 'isinstance')(child, _v4_global(_v4_scope, 'Mapping') | _v4_global(_v4_scope, 'list')):
                    visit(child)
        elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
            for child in value:
                visit(child)

    visit(payload)
    return values


def __pointer_evidence_body(_v4_scope, /, pointer, business_date, role):
    if pointer is None:
        raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_MISSING")
    try:
        pointer_path = _v4_global(_v4_scope, '_allowed_input_path')(pointer)
    except _v4_global(_v4_scope, 'EvidenceError') as error:
        try:
            lexical_pointer = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').path.abspath(_v4_global(_v4_scope, 'os').path.expanduser(_v4_global(_v4_scope, '_path_text')(pointer))))
        except (_v4_global(_v4_scope, 'EvidenceError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            lexical_pointer = None
        if lexical_pointer is not None and lexical_pointer.is_symlink():
            raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_UNAVAILABLE") from error
        raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_UNSAFE") from error
    if pointer_path.is_symlink() or not pointer_path.is_file():
        raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_UNAVAILABLE")
    try:
        raw = pointer_path.read_text(encoding="utf-8-sig").strip()
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError')) as error:
        raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_UNREADABLE") from error
    target_text = raw
    if raw.startswith("{"):
        try:
            pointer_payload = _v4_global(_v4_scope, 'json').loads(raw)
        except _v4_global(_v4_scope, 'json').JSONDecodeError as error:
            raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_MALFORMED") from error
        if not _v4_global(_v4_scope, 'isinstance')(pointer_payload, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_MALFORMED")
        target_text = _v4_global(_v4_scope, 'str')(
            pointer_payload.get("artifact_path")
            or pointer_payload.get("path")
            or pointer_payload.get("target")
            or ""
        )
    if not target_text:
        raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_TARGET_MISSING")
    try:
        target = _v4_global(_v4_scope, 'Path')(target_text).expanduser()
        if not target.is_absolute():
            target = pointer_path.parent / target
        target = _v4_global(_v4_scope, '_allowed_input_path')(target)
    except (_v4_global(_v4_scope, 'EvidenceError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_TARGET_UNSAFE") from error
    if target.is_symlink() or not target.is_file():
        raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_TARGET_UNAVAILABLE")
    dates = _v4_global(_v4_scope, '_artifact_dates')(target)
    if not dates:
        raise _v4_global(_v4_scope, 'EvidenceError')(f"{role.upper()}_POINTER_DATE_COLUMN_MISSING")
    minimum, maximum = _v4_global(_v4_scope, 'min')(dates), _v4_global(_v4_scope, 'max')(dates)
    if maximum > business_date:
        raise _v4_global(_v4_scope, 'EvidenceError')(
            f"{role.upper()}_POINTER_DATE_AFTER_TARGET:min={minimum}:max={maximum}:count={_v4_global(_v4_scope, 'len')(dates)}"
        )
    if maximum < business_date:
        raise _v4_global(_v4_scope, 'EvidenceError')(
            f"{role.upper()}_POINTER_DATE_BEFORE_TARGET:min={minimum}:max={maximum}:count={_v4_global(_v4_scope, 'len')(dates)}"
        )
    return {
        "pointer_path": _v4_global(_v4_scope, 'str')(pointer_path),
        "artifact_path": _v4_global(_v4_scope, 'str')(target),
        "artifact_sha256": _v4_global(_v4_scope, '_sha256')(target),
        "artifact_date": business_date,
    }


def __a_row_count_body(_v4_scope, /, receipt):
    if "row_count" in receipt and receipt.get("row_count") is not None:
        return _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_finite_number')(receipt.get("row_count"), "A_ROW_COUNT", integer=True)), "receipt.row_count", None
    formula = receipt.get("formula")
    sync = receipt.get("sync")
    authority = formula.get("authority") if _v4_global(_v4_scope, 'isinstance')(formula, _v4_global(_v4_scope, 'Mapping')) else None
    selector_rows = authority.get("selector_increment_rows") if _v4_global(_v4_scope, 'isinstance')(authority, _v4_global(_v4_scope, 'Mapping')) else None
    file_count = sync.get("target_date_file_count") if _v4_global(_v4_scope, 'isinstance')(sync, _v4_global(_v4_scope, 'Mapping')) else None
    if selector_rows is not None and file_count is not None:
        projected = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_finite_number')(selector_rows, "A_SELECTOR_INCREMENT_ROWS", integer=True))
        verified_files = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_finite_number')(file_count, "A_TARGET_DATE_FILE_COUNT", integer=True))
        if verified_files > 0:
            return projected, "formula.authority.selector_increment_rows", verified_files
    return 0, "unavailable", None


def __nested_rebuild_reason_body(_v4_scope, /, value):
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        if value.get("authority_status") == "REBUILD_REQUIRED":
            return "SYNC_AUTHORITY_REBUILD_REQUIRED"
        if value.get("quarantined_rebuild_symbols") not in (None, 0, "0"):
            return "SYNC_QUARANTINED_REBUILD_SYMBOLS"
        if value.get("rebuild_candidates_promoted") is False:
            return "SYNC_REBUILD_CANDIDATES_NOT_PROMOTED"
        for key, child in value.items():
            reason = _v4_global(_v4_scope, '_nested_rebuild_reason')(child)
            if reason:
                return reason
    elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
        for child in value:
            reason = _v4_global(_v4_scope, '_nested_rebuild_reason')(child)
            if reason:
                return reason
    return ""


def __base_body(_v4_scope, /, node_id, business_date, source, source_sha, *, status, reason):
    return {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA'),
        "node_id": node_id,
        "business_date": business_date,
        "status": status,
        "effective_status": status,
        "reason": reason,
        "source_receipt_path": _v4_global(_v4_scope, 'str')(source),
        "source_receipt_sha256": source_sha,
        "row_count": 0,
        "coverage_rate": 0.0,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }


def __close_review_evidence_body(_v4_scope, /, business_date, review_path, receipt_path):
    if review_path is None or receipt_path is None:
        raise _v4_global(_v4_scope, 'EvidenceError')("HK_CLOSE_REVIEW_RECEIPT_MISSING")
    review = _v4_global(_v4_scope, '_allowed_input_path')(review_path)
    receipt = _v4_global(_v4_scope, '_allowed_input_path')(receipt_path)
    payload = _v4_global(_v4_scope, '_read_json')(review)
    if payload.get("trade_date") != business_date:
        raise _v4_global(_v4_scope, 'EvidenceError')("HK_CLOSE_REVIEW_DATE_MISMATCH")
    if payload.get("status") != "MODEL_REVIEW_READY":
        raise _v4_global(_v4_scope, 'EvidenceError')(f"HK_CLOSE_REVIEW_NOT_READY:{payload.get('status')}")
    if not _v4_global(_v4_scope, '_safe_false')(payload):
        raise _v4_global(_v4_scope, 'EvidenceError')("HK_CLOSE_REVIEW_SAFETY_MISMATCH")
    review_sha = _v4_global(_v4_scope, '_sha256')(review)
    receipt_payload = _v4_global(_v4_scope, '_read_json')(receipt)
    if (
        receipt_payload.get("trade_date") != business_date
        or receipt_payload.get("source_sha256") != review_sha
        or _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(receipt_payload.get("payload_path") or "")).name != review.name
    ):
        raise _v4_global(_v4_scope, 'EvidenceError')("HK_CLOSE_REVIEW_RECEIPT_MISMATCH")
    return {
        "close_review_path": _v4_global(_v4_scope, 'str')(review),
        "close_review_sha256": review_sha,
        "close_review_receipt_path": _v4_global(_v4_scope, 'str')(receipt),
        "close_review_receipt_sha256": _v4_global(_v4_scope, '_sha256')(receipt),
    }


def __existing_hashes_body(_v4_scope, /, path, existing):
    hashes = _v4_global(_v4_scope, 'set')()
    current = existing.get("canonical_sha256")
    if _v4_global(_v4_scope, 'isinstance')(current, _v4_global(_v4_scope, 'str')) and _v4_global(_v4_scope, '_SHA256').fullmatch(current):
        hashes.add(current.lower())
    try:
        hashes.add(_v4_global(_v4_scope, '_sha256')(path).lower())
    except _v4_global(_v4_scope, 'EvidenceError'):
        pass
    for field in ("receipt_sha256", "canonical_sha256"):
        raw = existing.get(field)
        if _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'str')) and _v4_global(_v4_scope, '_SHA256').fullmatch(raw):
            hashes.add(raw.lower())
    return hashes


def __commit_lane_body(_v4_scope, /, destination, attempted, *, supersedes_sha256):
    candidate = _v4_global(_v4_scope, 'dict')(attempted)
    candidate["canonical_sha256"] = _v4_global(_v4_scope, '_canonical_sha')(candidate)
    candidate.setdefault("attempt_status", candidate.get("status"))
    candidate.setdefault("degradation_rejected", False)
    candidate.setdefault("conflict_rejected", False)
    candidate.setdefault("supersession_rejected", False)
    candidate.setdefault("no_op", False)
    _v4_global(_v4_scope, '_assert_no_symlink_ancestors')(destination.parent)
    if destination.is_symlink():
        raise _v4_global(_v4_scope, 'EvidenceError')(f"OUTPUT_PATH_UNSAFE:{destination}")
    if not destination.exists():
        candidate["publication_status"] = "PUBLISHED"
        _v4_global(_v4_scope, '_atomic_json')(destination, candidate)
        return candidate
    existing = _v4_global(_v4_scope, '_read_json')(destination)
    existing_status = _v4_global(_v4_scope, 'str')(existing.get("effective_status") or existing.get("status") or "")
    if existing_status not in _v4_global(_v4_scope, '_STATUS_RANK') or existing.get("business_date") != candidate.get("business_date") or existing.get("node_id") != candidate.get("node_id"):
        candidate.update(
            {
                "attempt_status": candidate.get("status"),
                "reason": "CONFLICT_REJECTED:EXISTING_RECEIPT_IDENTITY_INVALID",
                "conflict_rejected": True,
                "publication_status": "CONFLICT_REJECTED",
            }
        )
        return candidate
    existing_canonical = _v4_global(_v4_scope, 'str')(existing.get("canonical_sha256") or _v4_global(_v4_scope, '_canonical_sha')(existing))
    if existing_canonical == candidate["canonical_sha256"]:
        candidate.update(
            {
                "no_op": True,
                "publication_status": "NOOP",
                "effective_status": existing_status or candidate.get("status"),
            }
        )
        return candidate
    candidate_status = _v4_global(_v4_scope, 'str')(candidate.get("status") or "")
    existing_rank = _v4_global(_v4_scope, '_STATUS_RANK').get(existing_status, -1)
    candidate_rank = _v4_global(_v4_scope, '_STATUS_RANK').get(candidate_status, -1)
    if existing_rank == candidate_rank:
        candidate.update(
            {
                "status": existing_status or candidate_status,
                "effective_status": existing_status or candidate_status,
                "attempt_status": candidate_status,
                "reason": f"CONFLICT_REJECTED:{candidate.get('reason') or 'PROVENANCE_CHANGED'}",
                "conflict_rejected": True,
                "publication_status": "CONFLICT_REJECTED",
            }
        )
        return candidate
    if candidate_rank > existing_rank:
        if supersedes_sha256 is None or supersedes_sha256 not in _v4_global(_v4_scope, '_existing_hashes')(destination, existing):
            candidate.update(
                {
                    "status": existing_status or candidate_status,
                    "effective_status": existing_status or candidate_status,
                    "attempt_status": candidate_status,
                    "reason": f"SUPERSESSION_REJECTED:{candidate.get('reason') or 'SUPERSEDES_SHA256_REQUIRED'}",
                    "supersession_rejected": True,
                    "publication_status": "SUPERSESSION_REJECTED",
                }
            )
            return candidate
        candidate["supersedes_sha256"] = supersedes_sha256
        candidate["publication_status"] = "PUBLISHED"
        _v4_global(_v4_scope, '_atomic_json')(destination, candidate)
        return candidate
    candidate.update(
        {
            "status": existing_status or candidate_status,
            "effective_status": existing_status or candidate_status,
            "attempt_status": candidate_status,
            "reason": f"DEGRADATION_REJECTED:{candidate.get('reason') or 'STATUS_REGRESSION'}",
            "degradation_rejected": True,
            "publication_status": "DEGRADATION_REJECTED",
        }
    )
    return candidate


def _main_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description="Publish research-panel runtime evidence metadata")
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--producer-receipt-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--a-producer-receipt-root", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--selector-pointer", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--backtest-pointer", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--formula-generation-pointer", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--close-review-path", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--close-review-receipt", dest="close_review_receipt_path", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--supersedes-sha256")
    try:
        args = parser.parse_args(argv)
        result = _v4_global(_v4_scope, 'publish_research_panel_status')(
            business_date=args.date,
            data_root=args.data_root,
            producer_receipt_root=args.producer_receipt_root,
            a_producer_receipt_root=args.a_producer_receipt_root,
            selector_pointer=args.selector_pointer,
            backtest_pointer=args.backtest_pointer,
            formula_generation_pointer=args.formula_generation_pointer,
            close_review_path=args.close_review_path,
            close_review_receipt_path=args.close_review_receipt_path,
            supersedes_sha256=args.supersedes_sha256,
        )
        _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(result, ensure_ascii=False, sort_keys=True))
        rejected = _v4_global(_v4_scope, 'any')(
            lane.get(flag) is True
            for lane in result["lanes"].values()
            for flag in ("degradation_rejected", "conflict_rejected", "supersession_rejected")
        )
        return 0 if not rejected and result["lanes"]["A"]["status"] in {"READY", "PARTIAL"} and result["lanes"]["HK"]["status"] == "READY" else 2
    except _v4_global(_v4_scope, 'Exception') as error:
        _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps({"schema_version": _v4_global(_v4_scope, 'SCHEMA'), "status": "CANNOT_CONFIRM", "reason": _v4_global(_v4_scope, 'str')(error), **_v4_global(_v4_scope, 'SAFETY_FLAGS')}, ensure_ascii=False))
        return 2
