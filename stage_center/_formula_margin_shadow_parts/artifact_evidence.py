"""stage_center.formula_margin_shadow: artifact_evidence (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __source_binding_body(_v4_scope, /, metadata, *, require_artifacts, require_run_id):
    source_version = _v4_global(_v4_scope, 'str')(metadata.get("source_version") or "").strip()
    input_sha = metadata.get("input_sha256", metadata.get("input_sha"))
    rule_sha = metadata.get("rule_sha256", metadata.get("rule_sha"))
    comparator_version = _v4_global(_v4_scope, 'str')(metadata.get("comparator_version") or "").strip()
    run_id = _v4_global(_v4_scope, 'str')(metadata.get("run_id") or "").strip()
    if not source_version:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("production source_version is required")
    if not _v4_global(_v4_scope, '_is_sha')(input_sha):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("production input_sha256 is required")
    if not _v4_global(_v4_scope, '_is_sha')(rule_sha):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("production rule_sha256 is required")
    if comparator_version != _v4_global(_v4_scope, 'COMPARATOR_VERSION'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(
            f"comparator_version must be {_v4_global(_v4_scope, 'COMPARATOR_VERSION')}, got {comparator_version!r}"
        )
    if require_run_id and not run_id:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("production run_id is required for baseline binding")
    rule_artifact = _v4_global(_v4_scope, '_checked_file_artifact')(
        metadata.get("rule_artifact"),
        "rule_artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(rule_sha).lower(),
        required=require_artifacts,
    )
    return {
        "source_version": source_version,
        "input_sha256": _v4_global(_v4_scope, 'str')(input_sha).lower(),
        "rule_sha256": _v4_global(_v4_scope, 'str')(rule_sha).lower(),
        "comparator_version": comparator_version,
        "run_id": run_id,
        "rule_artifact": rule_artifact,
    }


def __checked_file_artifact_body(_v4_scope, /, artifact, label, *, expected_sha, required):
    if artifact is None:
        if required:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} actual artifact bytes are required")
        return None
    if not _v4_global(_v4_scope, 'isinstance')(artifact, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} must be an object")
    path = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(artifact.get("path") or "")).expanduser()
    declared = artifact.get("sha256", artifact.get("manifest_sha256"))
    if not path.is_file() or path.is_symlink() or not _v4_global(_v4_scope, '_is_sha')(declared):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} path/SHA is invalid")
    actual = _v4_global(_v4_scope, 'sha256_file')(path)
    if actual != _v4_global(_v4_scope, 'str')(declared).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} SHA mismatch")
    if expected_sha is not None and actual != _v4_global(_v4_scope, 'str')(expected_sha).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} SHA is not bound to the declared input SHA")
    return {"path": _v4_global(_v4_scope, 'str')(path.resolve()), "sha256": actual, "bytes": path.stat().st_size}


def __formula_provenance_body(_v4_scope, /, metadata, trade_date, cutoff, *, require_artifact):
    raw = metadata.get("formula_provenance")
    if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_provenance is required; formula states cannot be inferred")
    source_version = _v4_global(_v4_scope, 'str')(raw.get("source_version") or raw.get("version") or "").strip()
    input_sha = raw.get("input_sha256", raw.get("input_sha"))
    rule_sha = raw.get("rule_sha256", raw.get("rule_sha"))
    if not source_version:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula source_version is required")
    if _v4_global(_v4_scope, 'any')(token in source_version.upper() for token in ("LEGACY", "ARCHIVE", "HISTORICAL", "FIXTURE", "REPLAY", "PROXY")):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("legacy/archive/proxy formula state cannot be a forward input")
    if not _v4_global(_v4_scope, '_is_sha')(input_sha) or not _v4_global(_v4_scope, '_is_sha')(rule_sha):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula input_sha256 and rule_sha256 must be SHA-256")
    asof_value = raw.get("source_asof", raw.get("asof"))
    frozen_value = raw.get("frozen_at", raw.get("formula_frozen_at"))
    asof = _v4_global(_v4_scope, '_parse_timestamp')(asof_value, trade_date, "formula source_asof")
    frozen = _v4_global(_v4_scope, '_parse_timestamp')(frozen_value, trade_date, "formula frozen_at")
    if asof > cutoff or frozen > cutoff:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula source_asof/frozen_at is after the stage cutoff")
    # A same-day formula source is allowed only up to the cutoff.  A date-only
    # D/D-1 source is therefore naturally safe, while a post-cutoff T source
    # is rejected.
    if asof.strftime("%Y%m%d") > trade_date or frozen.strftime("%Y%m%d") > trade_date:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula provenance uses a future trade date")
    artifact_record = _v4_global(_v4_scope, '_checked_file_artifact')(
        raw.get("artifact"),
        "formula artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(input_sha).lower(),
        required=require_artifact,
    )
    rule_artifact_record = _v4_global(_v4_scope, '_checked_file_artifact')(
        raw.get("rule_artifact"),
        "formula rule artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(rule_sha).lower(),
        required=require_artifact,
    )
    return {
        "source_version": source_version,
        "input_sha256": _v4_global(_v4_scope, 'str')(input_sha).lower(),
        "rule_sha256": _v4_global(_v4_scope, 'str')(rule_sha).lower(),
        "source_asof": asof.isoformat(),
        "frozen_at": frozen.isoformat(),
        "artifact": artifact_record,
        "rule_artifact": rule_artifact_record,
    }


def __verify_formula_artifact_rows_body(_v4_scope, /, artifact, rows):
    """Ensure persisted formula states agree with the verified artifact bytes."""

    if not _v4_global(_v4_scope, 'isinstance')(artifact, _v4_global(_v4_scope, 'Mapping')):
        return
    artifact_payload = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(artifact["path"])))
    if not _v4_global(_v4_scope, 'isinstance')(artifact_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula artifact must contain an object")
    source = artifact_payload.get("states")
    if source is None:
        source = artifact_payload.get("rows")
    if source is None:
        source = artifact_payload.get("by_code")
    if _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'Mapping')):
        iterable = [_v4_global(_v4_scope, 'dict')(value, security_id=key) if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) else value for key, value in source.items()]
    elif _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'list')):
        iterable = source
    else:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula artifact states/rows are required")
    actual: dict[str, tuple[str, str, str, str]] = {}
    for raw in iterable:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("formula artifact state rows must be objects")
        code = _v4_global(_v4_scope, '_canonical_code')(raw.get("security_id", raw.get("code")))
        actual[code] = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, '_formula_state')(raw, f"f{i}_state") for i in _v4_global(_v4_scope, 'range')(1, 5))
    expected = {
        _v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code"))): _v4_global(_v4_scope, 'tuple')(
            _v4_global(_v4_scope, '_formula_state')(row, f"f{i}_state") for i in _v4_global(_v4_scope, 'range')(1, 5)
        )
        for row in rows
    }
    if actual != expected:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula states do not match the verified artifact bytes")


def __source_artifact_check_body(_v4_scope, /, metadata, *, expected_sha, required):
    return _v4_global(_v4_scope, '_checked_file_artifact')(
        metadata.get("source_artifact"),
        "source_artifact",
        expected_sha=expected_sha,
        required=required,
    )


def __verify_source_artifact_rows_body(_v4_scope, /, artifact, rows):
    """Check the selector snapshot's member identities and shared inputs."""

    if not _v4_global(_v4_scope, 'isinstance')(artifact, _v4_global(_v4_scope, 'Mapping')):
        return
    payload = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(artifact["path"])))
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact must contain an object")
    source_rows = payload.get("rows", payload.get("members"))
    if not _v4_global(_v4_scope, 'isinstance')(source_rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact rows are required")
    source_by_code: dict[str, Mapping[str, Any]] = {}
    for raw in source_rows:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact rows must be objects")
        code = _v4_global(_v4_scope, '_canonical_code')(raw.get("security_id", raw.get("code")))
        if code in source_by_code:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"duplicate source_artifact row: {code}")
        source_by_code[code] = raw
    expected_by_code = {
        _v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code"))): row
        for row in rows
    }
    if _v4_global(_v4_scope, 'set')(source_by_code) != _v4_global(_v4_scope, 'set')(expected_by_code):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact rows do not match the snapshot members")
    shared_keys = (
        "stage_score",
        "pct_chg",
        "volume_ratio",
        "candidate_bucket",
        "trade_status_contract",
        "stage_price",
        "price_ts",
    )
    for code, source in source_by_code.items():
        expected = expected_by_code[code]
        for key in shared_keys:
            if key not in source or source.get(key) in (None, "") or key not in expected or expected.get(key) in (None, ""):
                continue
            left = source.get(key)
            right = expected.get(key)
            if key in {"stage_score", "pct_chg", "volume_ratio", "stage_price"}:
                if _v4_global(_v4_scope, 'abs')(_v4_global(_v4_scope, '_finite')(left) - _v4_global(_v4_scope, '_finite')(right)) > 1e-12:
                    raise _v4_global(_v4_scope, 'ShadowInvalid')(f"source_artifact {key} mismatch: {code}")
            elif left != right:
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"source_artifact {key} mismatch: {code}")
