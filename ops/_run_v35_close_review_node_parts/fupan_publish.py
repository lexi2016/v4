"""ops.run_v35_close_review_node: fupan_publish (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __fupan_publish_body(_v4_scope, /, *, data_root, date, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    payload_rel = f"a_share_reviews/{date}.json"
    receipt_rel = f"a_share_reviews/receipts/{date}.json"
    manifest_rel = "a_share_reviews/manifest.json"
    payload_path = _v4_global(_v4_scope, 'resolve_owned_path')(data_root, payload_rel)
    receipt_path = _v4_global(_v4_scope, 'resolve_owned_path')(data_root, receipt_rel)
    manifest_path = _v4_global(_v4_scope, 'resolve_owned_path')(data_root, manifest_rel)
    artifacts = {
        "payload": _v4_global(_v4_scope, 'str')(payload_path),
        "receipt": _v4_global(_v4_scope, 'str')(receipt_path),
        "manifest": _v4_global(_v4_scope, 'str')(manifest_path),
    }
    missing = [
        name
        for name, path in (
            ("payload", payload_path),
            ("receipt", receipt_path),
            ("manifest", manifest_path),
        )
        if not path.is_file()
    ]
    if missing:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_EVIDENCE_MISSING",
            "missing " + ", ".join(missing),
            artifacts,
        )
    try:
        with _v4_global(_v4_scope, 'open')(payload_path, "r", encoding="utf-8") as handle:
            payload = _v4_global(_v4_scope, 'json').load(handle)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_PAYLOAD_UNREADABLE",
            f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
            artifacts,
        )
    try:
        with _v4_global(_v4_scope, 'open')(receipt_path, "r", encoding="utf-8") as handle:
            receipt = _v4_global(_v4_scope, 'json').load(handle)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_RECEIPT_UNREADABLE",
            f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
            artifacts,
        )
    try:
        with _v4_global(_v4_scope, 'open')(manifest_path, "r", encoding="utf-8") as handle:
            manifest = _v4_global(_v4_scope, 'json').load(handle)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_MANIFEST_UNREADABLE",
            f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
            artifacts,
        )
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')) or payload.get("trade_date") != date:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_PAYLOAD_DATE_INVALID",
            "payload trade_date mismatch",
            artifacts,
        )
    if payload.get("source_role") != "V3_5_NATIVE_CLOSE_MODEL":
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_PAYLOAD_SOURCE_ROLE_INVALID",
            f"source_role {payload.get('source_role')!r}",
            artifacts,
        )
    if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'dict')) or receipt.get("trade_date") != date:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_RECEIPT_DATE_INVALID",
            "receipt trade_date mismatch",
            artifacts,
        )
    if not _v4_global(_v4_scope, 'isinstance')(manifest, _v4_global(_v4_scope, 'dict')) or payload_rel not in manifest:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_MANIFEST_MISSING_PAYLOAD",
            "manifest lacks payload entry",
            artifacts,
        )
    return (
        "SUCCESS",
        "REVIEW_ARTIFACT_MATERIALIZED",
        "authoritative review evidence materialized",
        artifacts,
    )


def __verify_fupan_8771_body(_v4_scope, /, *, data_root, date, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    if not _v4_global(_v4_scope, '_validate_loopback_url')(loopback_base_url):
        return (
            "FAIL",
            "URL_REJECTED",
            "non-loopback or non-8873 or credential-bearing base URL",
            {},
        )
    probes = (
        (
            "review_endpoint",
            _v4_global(_v4_scope, '_join_url')(loopback_base_url, f"/api/v3/review?date={date}"),
        ),
        ("root_endpoint", _v4_global(_v4_scope, '_join_url')(loopback_base_url, "/")),
    )
    artifacts: dict[str, Any] = {}
    for name, url in probes:
        if not _v4_global(_v4_scope, '_validate_loopback_url')(url):
            return ("FAIL", "URL_REJECTED", f"probe URL rejected: {url}", {})
        try:
            status = _v4_global(_v4_scope, '_http_status')(url, http_getter)
        except _v4_global(_v4_scope, 'HttpVerifyFailed') as error:
            return ("FAIL", "HTTP_VERIFY_FAILED", f"{name}: {error}", {})
        if status != 200:
            return (
                "FAIL",
                "HTTP_VERIFY_FAILED",
                f"{name} returned HTTP {status}",
                {},
            )
        artifacts[name] = url
    return (
        "SUCCESS",
        "HTTP_200_CONFIRMED",
        "both loopback endpoints returned HTTP 200",
        artifacts,
    )
