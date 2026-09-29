"""stage_center.formula_margin_shadow: snapshot_freeze (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __provenance_material_body(_v4_scope, /, built):
    """Read all consumed source bytes before publishing an invocation freeze."""

    receipt = built.get("receipt")
    root_meta = built.get("root_metadata")
    if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(root_meta, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("built shadow metadata is incomplete")
    capture_receipt = receipt.get("capture_time_receipt")
    if not _v4_global(_v4_scope, 'isinstance')(capture_receipt, _v4_global(_v4_scope, 'Mapping')) or capture_receipt.get("invocation_verified") is not True:
        return {}, None
    source = root_meta.get("production_source_artifact")
    binding = root_meta.get("production_binding")
    d1 = root_meta.get("d1_manifest")
    formula = root_meta.get("formula_manifest_binding")
    if not _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(binding, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(d1, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(formula, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("invocation-verified provenance bindings are incomplete")
    artifacts: dict[str, Mapping[str, Any]] = {
        "production_source": source,
        "production_rule": binding.get("rule_artifact"),
        "d1_manifest": d1.get("artifact"),
        "formula_state": formula.get("artifact"),
        "formula_rule": formula.get("rule_artifact"),
    }
    material: dict[str, dict[str, Any]] = {}
    for name, artifact in artifacts.items():
        if not _v4_global(_v4_scope, 'isinstance')(artifact, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{name} provenance artifact is missing")
        encoded = _v4_global(_v4_scope, '_read_exact_artifact')(artifact, f"{name} provenance artifact")
        file_name, _ = _v4_global(_v4_scope, 'PROVENANCE_FILES')[name]
        material[name] = {
            "path": f"provenance/{file_name}",
            "sha256": _v4_global(_v4_scope, 'sha256_bytes')(encoded),
            "bytes": _v4_global(_v4_scope, 'len')(encoded),
            "_encoded": encoded,
            "external_path": _v4_global(_v4_scope, 'str')(artifact.get("path") or ""),
        }
    selector_result = root_meta.get("selector_result")
    if not _v4_global(_v4_scope, 'isinstance')(selector_result, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("invocation-verified selector result is missing")
    selector_bytes = _v4_global(_v4_scope, 'canonical_json')(_v4_global(_v4_scope, 'dict')(selector_result))
    selector_sha = _v4_global(_v4_scope, 'sha256_bytes')(selector_bytes)
    if selector_sha != _v4_global(_v4_scope, 'str')(capture_receipt.get("selector_result_sha256") or "").lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector result hash does not match capture receipt")
    material["selector_result"] = {
        "path": "selector_result.json",
        "sha256": selector_sha,
        "bytes": _v4_global(_v4_scope, 'len')(selector_bytes),
        "_encoded": selector_bytes,
    }
    return material, _v4_global(_v4_scope, 'dict')(selector_result)


def __freeze_snapshot_internal_body(_v4_scope, /, payload, output_root, *, require_full_pool, allow_invocation_verified):
    if require_full_pool is not True:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("persistent freeze requires the complete 100-row D1 pool")
    raw_rows = payload.get("rows") if _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')) else None
    if not _v4_global(_v4_scope, 'isinstance')(raw_rows, _v4_global(_v4_scope, 'Sequence')) or _v4_global(_v4_scope, 'isinstance')(raw_rows, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'))) or _v4_global(_v4_scope, 'len')(raw_rows) != _v4_global(_v4_scope, 'POOL_LIMIT'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("persistent freeze requires the complete 100-row D1 pool")
    built = _v4_global(_v4_scope, 'build_shadow')(
        payload,
        require_full_pool=True,
        require_artifacts=True,
        allow_invocation_verified=allow_invocation_verified,
    )
    root_meta = built["root_metadata"]
    invocation_verified = _v4_global(_v4_scope, 'bool')(root_meta.get("invocation_verified"))
    if invocation_verified and not allow_invocation_verified:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("INVOCATION_VERIFIED_RECEIPT_REQUIRES_SELECTOR_CAPTURE")
    material, selector_result = _v4_global(_v4_scope, '_provenance_material')(built)
    output_path = _v4_global(_v4_scope, '_ensure_output_root')(output_root)
    date_root = output_path / root_meta["trade_date"]
    if date_root.is_symlink():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("shadow date root cannot be symlinked")
    run_root = date_root / root_meta["stage"]
    if run_root.is_symlink():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("shadow run root cannot be symlinked")
    run_root.mkdir(parents=True, exist_ok=True)
    built_receipt = built.get("receipt", {}).get("capture_time_receipt")
    expected_paths = (
        run_root / "members.json",
        run_root / "baseline_top10.json",
        run_root / "candidate_top10.json",
        run_root / "selection_receipt.json",
        *((run_root / "capture_time_receipt.json",) if _v4_global(_v4_scope, 'isinstance')(built_receipt, _v4_global(_v4_scope, 'Mapping')) else ()),
        *_v4_global(_v4_scope, 'tuple')(run_root / _v4_global(_v4_scope, 'str')(detail["path"]) for detail in material.values()),
    )
    if _v4_global(_v4_scope, 'any')(path.exists() or path.is_symlink() for path in expected_paths):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("refusing to overwrite an existing frozen run")
    members_sha = _v4_global(_v4_scope, '_immutable_json')(run_root / "members.json", built["members"])
    baseline_sha = _v4_global(_v4_scope, '_immutable_json')(run_root / "baseline_top10.json", built["baseline"])
    candidate_sha = _v4_global(_v4_scope, '_immutable_json')(run_root / "candidate_top10.json", built["candidate"])
    receipt = _v4_global(_v4_scope, 'dict')(built["receipt"])
    receipt["artifacts"] = {
        "members": {"path": "members.json", "sha256": members_sha},
        "baseline": {"path": "baseline_top10.json", "sha256": baseline_sha},
        "candidate": {"path": "candidate_top10.json", "sha256": candidate_sha},
    }
    artifact_result: dict[str, str] = {
        "members": members_sha,
        "baseline": baseline_sha,
        "candidate": candidate_sha,
    }
    if _v4_global(_v4_scope, 'isinstance')(built_receipt, _v4_global(_v4_scope, 'Mapping')):
        capture_receipt_sha = _v4_global(_v4_scope, '_immutable_json')(run_root / "capture_time_receipt.json", _v4_global(_v4_scope, 'dict')(built_receipt))
        receipt["artifacts"]["capture_time_receipt"] = {
            "path": "capture_time_receipt.json",
            "sha256": capture_receipt_sha,
        }
        artifact_result["capture_time_receipt"] = capture_receipt_sha
    if material:
        provenance_receipt: dict[str, dict[str, Any]] = {}
        for name, detail in material.items():
            path = run_root / _v4_global(_v4_scope, 'str')(detail["path"])
            sha = _v4_global(_v4_scope, '_immutable_bytes')(path, detail["_encoded"])
            if sha != detail["sha256"]:
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"sealed {name} provenance SHA mismatch")
            clean = {key: value for key, value in detail.items() if key not in {"_encoded"}}
            provenance_receipt[name] = clean
        receipt["provenance"] = provenance_receipt
        receipt["artifacts"]["selector_result"] = provenance_receipt["selector_result"]
        artifact_result["selector_result"] = provenance_receipt["selector_result"]["sha256"]
    receipt_without_self_hash = _v4_global(_v4_scope, 'dict')(receipt)
    receipt["receipt_payload_sha256"] = _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, 'canonical_json')(receipt_without_self_hash))
    receipt_sha = _v4_global(_v4_scope, '_immutable_json')(run_root / "selection_receipt.json", receipt)
    artifact_result["receipt"] = receipt_sha
    return {
        "status": "FROZEN",
        "run_root": _v4_global(_v4_scope, 'str')(run_root),
        "artifacts": artifact_result,
        "baseline_codes": built["baseline"]["codes"],
        "candidate_codes": built["candidate"]["codes"],
        "changed_in": built["receipt"]["selection"]["changed_in"],
        "changed_out": built["receipt"]["selection"]["changed_out"],
        "capture_origin": root_meta.get("capture_origin"),
        "invocation_verified": invocation_verified,
        "safety": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'SAFETY_FLAGS')),
    }


def _freeze_snapshot_body(_v4_scope, /, payload, output_root, *, require_full_pool):
    """Direct engineering freeze; it cannot prove a selector invocation."""

    return _v4_global(_v4_scope, '_freeze_snapshot_internal')(
        payload,
        output_root,
        require_full_pool=require_full_pool,
        allow_invocation_verified=False,
    )
