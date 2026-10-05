"""ops.publish_research_panel_runtime_receipt: hk_receipts (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __publish_hk_body(_v4_scope, /, business_date, producer_receipt_root, close_review_path, close_review_receipt_path):
    try:
        source = _v4_global(_v4_scope, '_exact_producer_receipt')(producer_receipt_root, "HK", business_date)
        source_sha = _v4_global(_v4_scope, '_sha256')(source)
        receipt = _v4_global(_v4_scope, '_read_json')(source)
        if receipt.get("target_date") != business_date:
            raise _v4_global(_v4_scope, 'EvidenceError')("HK_RECEIPT_DATE_MISMATCH")
        if receipt.get("status") != "READY":
            raise _v4_global(_v4_scope, 'EvidenceError')(f"HK_PRODUCER_NOT_READY:{receipt.get('status')}")
        if not _v4_global(_v4_scope, '_safe_false')(receipt):
            raise _v4_global(_v4_scope, 'EvidenceError')("HK_RECEIPT_SAFETY_MISMATCH")
        _v4_global(_v4_scope, '_validate_date_fields')(receipt, business_date, prefix="HK_RECEIPT")
        _v4_global(_v4_scope, '_validate_hash_fields')(receipt, prefix="HK_RECEIPT")
        authority = receipt.get("authority")
        if authority is not None:
            if not _v4_global(_v4_scope, 'isinstance')(authority, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'EvidenceError')("HK_AUTHORITY_INVALID")
            _v4_global(_v4_scope, '_validate_date_fields')(authority, business_date, prefix="HK_AUTHORITY")
            _v4_global(_v4_scope, '_validate_hash_fields')(authority, prefix="HK_AUTHORITY")
        row_count = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_finite_number')(receipt.get("row_count"), "HK_ROW_COUNT", integer=True))
        coverage_rate = _v4_global(_v4_scope, '_finite_number')(receipt.get("coverage_rate"), "HK_COVERAGE_RATE", maximum=1.0)
        digest = _v4_global(_v4_scope, 'next')(
            (_v4_global(_v4_scope, 'str')(receipt.get(field)) for field in ("sha256", "panel_sha256", "source_sha256") if receipt.get(field) not in (None, "")),
            "",
        )
        if row_count <= 0 or coverage_rate <= 0.0 or not _v4_global(_v4_scope, '_SHA256').fullmatch(digest):
            raise _v4_global(_v4_scope, 'EvidenceError')("HK_PRODUCER_ARTIFACT_NOT_READY")
        close = _v4_global(_v4_scope, '_close_review_evidence')(business_date, close_review_path, close_review_receipt_path)
        result = _v4_global(_v4_scope, '_base')("hkconnect_research_panel", business_date, source, source_sha, status="READY", reason="READY")
        result.update({"row_count": row_count, "coverage_rate": coverage_rate, "producer_artifact_sha256": digest, **close})
        return result
    except (_v4_global(_v4_scope, 'EvidenceError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        try:
            source = _v4_global(_v4_scope, '_exact_producer_receipt')(producer_receipt_root, "HK", business_date)
            source_sha = _v4_global(_v4_scope, '_sha256')(source)
        except _v4_global(_v4_scope, 'EvidenceError'):
            source = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').path.abspath(_v4_global(_v4_scope, 'os').path.expanduser(_v4_global(_v4_scope, 'str')(producer_receipt_root)))) / f"hk-{business_date}.json"
            source_sha = ""
        return _v4_global(_v4_scope, '_base')("hkconnect_research_panel", business_date, source, source_sha, status="CANNOT_CONFIRM", reason=_v4_global(_v4_scope, 'str')(error))
