"""ops.publish_research_panel_runtime_receipt: a_receipts (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __publish_a_body(_v4_scope, /, business_date, producer_receipt_root, selector_pointer, backtest_pointer, formula_generation_pointer, *, owner_bound):
    try:
        source = _v4_global(_v4_scope, '_exact_a_producer_receipt')(
            producer_receipt_root,
            "A",
            business_date,
            owner_bound=owner_bound,
        )
        source_sha = _v4_global(_v4_scope, '_sha256')(source)
        receipt = _v4_global(_v4_scope, '_read_json')(source)
        if receipt.get("target_date") != business_date:
            raise _v4_global(_v4_scope, 'EvidenceError')("A_RECEIPT_DATE_MISMATCH")
        if receipt.get("status") != "READY":
            raise _v4_global(_v4_scope, 'EvidenceError')(f"A_PRODUCER_NOT_READY:{receipt.get('status')}")
        if not _v4_global(_v4_scope, '_safe_false')(receipt):
            raise _v4_global(_v4_scope, 'EvidenceError')("A_RECEIPT_SAFETY_MISMATCH")
        _v4_global(_v4_scope, '_validate_date_fields')(receipt, business_date, prefix="A_RECEIPT")
        _v4_global(_v4_scope, '_validate_hash_fields')(receipt, prefix="A_RECEIPT", allow_empty=True)
        selector = _v4_global(_v4_scope, '_pointer_evidence')(selector_pointer, business_date, "selector")
        backtest = _v4_global(_v4_scope, '_pointer_evidence')(backtest_pointer, business_date, "backtest")
        generation = None
        if formula_generation_pointer is not None:
            try:
                generation = _v4_global(_v4_scope, 'read_formula_generation')(
                    formula_generation_pointer,
                    expected_target_date=business_date,
                    require_source=True,
                )
            except (_v4_global(_v4_scope, 'FormulaGenerationError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
                raise _v4_global(_v4_scope, 'EvidenceError')(f"A_FORMULA_GENERATION_INVALID:{error}") from error
            if (
                _v4_global(_v4_scope, 'Path')(selector["artifact_path"]).resolve() != generation["selector"]
                or _v4_global(_v4_scope, 'Path')(backtest["artifact_path"]).resolve() != generation["backtest"]
            ):
                raise _v4_global(_v4_scope, 'EvidenceError')("A_FORMULA_GENERATION_POINTER_PROJECTION_MISMATCH")
            producer_generation = receipt.get("generation")
            formula_detail = receipt.get("formula")
            nested_generation = (
                formula_detail.get("generation_pointer")
                if _v4_global(_v4_scope, 'isinstance')(formula_detail, _v4_global(_v4_scope, 'Mapping'))
                else None
            )
            if producer_generation is not None and not _v4_global(_v4_scope, 'isinstance')(producer_generation, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'EvidenceError')("A_PRODUCER_GENERATION_INVALID")
            if nested_generation is not None and not _v4_global(_v4_scope, 'isinstance')(nested_generation, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'EvidenceError')("A_PRODUCER_GENERATION_INVALID")
            claims = [
                claim
                for claim in (producer_generation, nested_generation)
                if _v4_global(_v4_scope, 'isinstance')(claim, _v4_global(_v4_scope, 'Mapping'))
            ]
            if not claims:
                raise _v4_global(_v4_scope, 'EvidenceError')("A_PRODUCER_GENERATION_MISSING")
            if _v4_global(_v4_scope, 'len')(claims) == 2:
                for field in ("generation_id", "sha256", "path", "bytes"):
                    if field not in claims[0] or field not in claims[1]:
                        continue
                    left = claims[0].get(field)
                    right = claims[1].get(field)
                    if field == "sha256":
                        left = _v4_global(_v4_scope, 'str')(left or "").lower()
                        right = _v4_global(_v4_scope, 'str')(right or "").lower()
                    elif field == "path":
                        left = _v4_global(_v4_scope, 'str')(left or "")
                        right = _v4_global(_v4_scope, 'str')(right or "")
                    if left != right:
                        raise _v4_global(_v4_scope, 'EvidenceError')(f"A_PRODUCER_GENERATION_FIELDS_CONFLICT:{field}")
            for claim in claims:
                if (
                    _v4_global(_v4_scope, 'str')(claim.get("generation_id") or "") != generation["generation_id"]
                    or _v4_global(_v4_scope, 'str')(claim.get("sha256") or "").lower() != generation["sha256"]
                ):
                    raise _v4_global(_v4_scope, 'EvidenceError')("A_PRODUCER_GENERATION_MISMATCH")
                claimed_path = claim.get("path")
                if claimed_path not in (None, ""):
                    if not _v4_global(_v4_scope, 'isinstance')(claimed_path, _v4_global(_v4_scope, 'str')) or claimed_path != _v4_global(_v4_scope, 'str')(generation["path"]):
                        raise _v4_global(_v4_scope, 'EvidenceError')("A_PRODUCER_GENERATION_PATH_MISMATCH")
                claimed_bytes = claim.get("bytes")
                if claimed_bytes is not None:
                    if _v4_global(_v4_scope, 'type')(claimed_bytes) is not _v4_global(_v4_scope, 'int') or claimed_bytes != generation["bytes"]:
                        raise _v4_global(_v4_scope, 'EvidenceError')("A_PRODUCER_GENERATION_BYTES_MISMATCH")
            producer_generation = claims[0]
        reason = _v4_global(_v4_scope, '_nested_rebuild_reason')(receipt.get("sync", receipt))
        status = "PARTIAL" if reason else "READY"
        result = _v4_global(_v4_scope, '_base')("ashare_research_panel", business_date, source, source_sha, status=status, reason=reason or "READY")
        row_count, row_count_source, row_count_authority_file_count = _v4_global(_v4_scope, '_a_row_count')(receipt)
        coverage_unavailable = "coverage_rate" not in receipt or receipt.get("coverage_rate") is None
        coverage_rate = (
            0.0
            if coverage_unavailable
            else _v4_global(_v4_scope, '_finite_number')(receipt.get("coverage_rate"), "A_COVERAGE_RATE", maximum=1.0)
        )
        if row_count_source == "unavailable":
            result["reason"] = f"{result['reason']};A_ROW_COUNT_UNAVAILABLE"
        if coverage_unavailable:
            result["reason"] = f"{result['reason']};A_COVERAGE_UNAVAILABLE"
        result.update(
            {
                "row_count": row_count,
                "coverage_rate": coverage_rate,
                "row_count_source": row_count_source,
                "selector_pointer_path": selector["pointer_path"],
                "selector_artifact_path": selector["artifact_path"],
                "selector_artifact_sha256": selector["artifact_sha256"],
                "backtest_pointer_path": backtest["pointer_path"],
                "backtest_artifact_path": backtest["artifact_path"],
                "backtest_artifact_sha256": backtest["artifact_sha256"],
                "sync_authority_status": (receipt.get("sync") or {}).get("authority_status") if _v4_global(_v4_scope, 'isinstance')(receipt.get("sync"), _v4_global(_v4_scope, 'Mapping')) else None,
            }
        )
        if generation is not None:
            result["formula_generation"] = {
                "path": _v4_global(_v4_scope, 'str')(generation["path"]),
                "sha256": generation["sha256"],
                "bytes": generation["bytes"],
                "generation_id": generation["generation_id"],
                "target_date": generation["target_date"],
                "run_id": generation["run_id"],
                "selector_source": _v4_global(_v4_scope, 'str')(generation["selector_source"]),
                "selector_source_sha256": generation["selector_source_evidence"]["sha256"],
                "selector_sidecar": _v4_global(_v4_scope, 'str')(generation["selector_sidecar"]),
                "selector_sidecar_sha256": generation["selector_sidecar_evidence"]["sha256"],
            }
        if row_count_authority_file_count is not None:
            result["row_count_authority_file_count"] = row_count_authority_file_count
        return result
    except (_v4_global(_v4_scope, 'EvidenceError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        try:
            source = _v4_global(_v4_scope, '_exact_a_producer_receipt')(
                producer_receipt_root,
                "A",
                business_date,
                owner_bound=owner_bound,
            )
            source_sha = _v4_global(_v4_scope, '_sha256')(source)
        except _v4_global(_v4_scope, 'EvidenceError'):
            source = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').path.abspath(_v4_global(_v4_scope, 'os').path.expanduser(_v4_global(_v4_scope, 'str')(producer_receipt_root)))) / f"a-{business_date}.json"
            source_sha = ""
        return _v4_global(_v4_scope, '_base')("ashare_research_panel", business_date, source, source_sha, status="CANNOT_CONFIRM", reason=_v4_global(_v4_scope, 'str')(error))
