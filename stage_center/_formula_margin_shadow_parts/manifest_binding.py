"""stage_center.formula_margin_shadow: manifest_binding (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __verified_manifest_binding_body(_v4_scope, /, value, label, *, require_artifact):
    """Return a small, hash-bound manifest descriptor for a capture input."""

    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} is required for a selector capture")
    binding = _v4_global(_v4_scope, 'dict')(value)
    version = _v4_global(_v4_scope, 'str')(
        binding.get("source_version")
        or binding.get("manifest_version")
        or binding.get("version")
        or ""
    ).strip()
    digest = binding.get(
        "manifest_sha256",
        binding.get("sha256", binding.get("input_sha256")),
    )
    if not version:
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} version is required for a selector capture")
    if not _v4_global(_v4_scope, '_is_sha')(digest):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} SHA is required for a selector capture")
    binding["version"] = version
    binding["sha256"] = _v4_global(_v4_scope, 'str')(digest).lower()
    artifact_record = _v4_global(_v4_scope, '_checked_file_artifact')(
        binding.get("artifact"),
        f"{label} artifact",
        expected_sha=binding["sha256"],
        required=require_artifact,
    )
    if artifact_record is not None:
        binding["artifact"] = artifact_record
    return binding


def __formula_manifest_states_body(_v4_scope, /, manifest):
    """Extract explicit per-code H/N/U states without calculating formulas."""

    if not _v4_global(_v4_scope, 'isinstance')(manifest, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest is required for a selector capture")
    formula_input_sha = manifest.get("input_sha256", manifest.get("input_sha"))
    formula_rule_sha = manifest.get("rule_sha256", manifest.get("rule_sha"))
    if not _v4_global(_v4_scope, '_is_sha')(formula_input_sha) or not _v4_global(_v4_scope, '_is_sha')(formula_rule_sha):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest input_sha256/rule_sha256 are required")
    # ``manifest_sha256`` may identify a surrounding manifest.  The formula
    # state artifact itself must nevertheless be bound to input_sha256, and
    # its rule bytes must be bound to rule_sha256.  Do not let a manifest
    # descriptor SHA silently stand in for either artifact.
    descriptor = _v4_global(_v4_scope, 'dict')(manifest)
    descriptor.pop("artifact", None)
    descriptor.pop("rule_artifact", None)
    binding = _v4_global(_v4_scope, '_verified_manifest_binding')(descriptor, "formula_manifest", require_artifact=False)
    binding["input_sha256"] = _v4_global(_v4_scope, 'str')(formula_input_sha).lower()
    binding["rule_sha256"] = _v4_global(_v4_scope, 'str')(formula_rule_sha).lower()
    artifact_record = _v4_global(_v4_scope, '_checked_file_artifact')(
        manifest.get("artifact"),
        "formula state artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(formula_input_sha).lower(),
        required=True,
    )
    rule_artifact_record = _v4_global(_v4_scope, '_checked_file_artifact')(
        manifest.get("rule_artifact"),
        "formula rule artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(formula_rule_sha).lower(),
        required=True,
    )
    binding["artifact"] = artifact_record
    binding["rule_artifact"] = rule_artifact_record
    source: Any = manifest.get("states")
    if source is None:
        source = manifest.get("rows")
    if source is None:
        source = manifest.get("by_code")
    if source is None and _v4_global(_v4_scope, 'all')(key in manifest for key in ("f1_state", "f2_state", "f3_state", "f4_state")):
        source = [manifest]
    if _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'Mapping')):
        iterable = [_v4_global(_v4_scope, 'dict')(value, security_id=key) if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) else value for key, value in source.items()]
    elif _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'list')):
        iterable = source
    else:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest states/rows are required")
    states: dict[str, dict[str, Any]] = {}
    for raw in iterable:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest state rows must be objects")
        code = _v4_global(_v4_scope, '_canonical_code')(raw.get("security_id", raw.get("code")))
        if code in states:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"duplicate formula_manifest state: {code}")
        state_row = {
            f"f{i}_state": _v4_global(_v4_scope, '_formula_state')(raw, f"f{i}_state")
            for i in _v4_global(_v4_scope, 'range')(1, 5)
        }
        states[code] = state_row
    if not states:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest contains no per-code states")
    artifact_record = binding.get("artifact")
    if not _v4_global(_v4_scope, 'isinstance')(artifact_record, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest actual artifact is required")
    artifact_payload = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(artifact_record["path"])))
    if not _v4_global(_v4_scope, 'isinstance')(artifact_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest artifact must contain an object")
    artifact_source: Any = artifact_payload.get("states")
    if artifact_source is None:
        artifact_source = artifact_payload.get("rows")
    if artifact_source is None:
        artifact_source = artifact_payload.get("by_code")
    if _v4_global(_v4_scope, 'isinstance')(artifact_source, _v4_global(_v4_scope, 'Mapping')):
        artifact_iterable = [
            _v4_global(_v4_scope, 'dict')(value, security_id=key) if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) else value
            for key, value in artifact_source.items()
        ]
    elif _v4_global(_v4_scope, 'isinstance')(artifact_source, _v4_global(_v4_scope, 'list')):
        artifact_iterable = artifact_source
    else:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest artifact states/rows are required")
    artifact_states: dict[str, dict[str, str]] = {}
    for raw in artifact_iterable:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest artifact state rows must be objects")
        code = _v4_global(_v4_scope, '_canonical_code')(raw.get("security_id", raw.get("code")))
        artifact_states[code] = {
            f"f{i}_state": _v4_global(_v4_scope, '_formula_state')(raw, f"f{i}_state")
            for i in _v4_global(_v4_scope, 'range')(1, 5)
        }
    if artifact_states != states:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest states do not match the verified artifact bytes")
    return states, binding
