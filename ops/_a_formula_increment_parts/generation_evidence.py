"""ops.a_formula_increment: generation_evidence (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __copy_generation_owned_file_body(_v4_scope, /, source, destination, *, role, expected_sha256):
    """Copy one validated input document below the generation output root.

    The strict generation reader intentionally rejects provenance files that
    resolve outside the pointer's output root.  Keep the source bytes intact,
    but publish an owned copy beside the generated artifacts so an offline
    replay remains self-contained and its original digest is still auditable.
    """

    raw_source = _v4_global(_v4_scope, 'Path')(source).expanduser()
    if _v4_global(_v4_scope, '_path_has_symlink')(raw_source) or raw_source.is_symlink():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} source is symlinked")
    source_path = _v4_global(_v4_scope, '_resolved')(raw_source)
    if not source_path.is_file() or source_path.is_symlink():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} source is missing or not regular")
    raw = source_path.read_bytes()
    actual_sha256 = _v4_global(_v4_scope, '_sha256_bytes')(raw)
    if expected_sha256 is not None and actual_sha256 != _v4_global(_v4_scope, 'str')(expected_sha256).lower():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} source SHA mismatch")

    destination = _v4_global(_v4_scope, '_resolved')(destination)
    if destination.exists() or destination.is_symlink():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} owned destination already exists")
    if _v4_global(_v4_scope, '_path_has_symlink')(destination.parent):
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} owned destination has symlink ancestry")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _v4_global(_v4_scope, 'SafeRoot')(destination.parent).write_bytes(destination.name, raw)
    if destination.is_symlink() or not destination.is_file() or destination.read_bytes() != raw:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} owned copy readback mismatch")
    return {
        "path": _v4_global(_v4_scope, 'str')(destination),
        "bytes": _v4_global(_v4_scope, 'len')(raw),
        "sha256": actual_sha256,
        "source_path": _v4_global(_v4_scope, 'str')(source_path),
    }


def __prepare_generation_owned_evidence_body(_v4_scope, /, run_dir, manifest, *, target_date):
    """Bind the input manifest and its sync receipt to this generation.

    ``a_formula_input_manifest`` records the receipt under
    ``sync_receipt_path``; accepted-only manifests use the older
    ``source_receipt_path`` spelling.  Both names are accepted as source
    provenance, then normalized to the strict generation reader's
    ``sync_receipt_*`` fields while preserving the original source SHA.
    """

    source = manifest.get("source")
    if not _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source identity is missing")
    receipt_path_value = source.get("sync_receipt_path") or source.get("source_receipt_path")
    receipt_sha_value = source.get("sync_receipt_sha256") or source.get("source_receipt_sha256")
    if not _v4_global(_v4_scope, 'isinstance')(receipt_path_value, _v4_global(_v4_scope, 'str')) or not receipt_path_value.strip():
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt path is missing")
    if not _v4_global(_v4_scope, 'isinstance')(receipt_sha_value, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-fA-F]{64}", receipt_sha_value):
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt SHA is invalid")

    manifest_source = _v4_global(_v4_scope, '_resolved')(manifest["_manifest_path"])
    receipt_source = _v4_global(_v4_scope, 'Path')(receipt_path_value).expanduser()
    if not receipt_source.is_absolute():
        receipt_source = manifest_source.parent / receipt_source
    if _v4_global(_v4_scope, '_path_has_symlink')(receipt_source) or receipt_source.is_symlink():
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt is missing or symlinked")
    receipt_source = _v4_global(_v4_scope, '_resolved')(receipt_source)
    if _v4_global(_v4_scope, '_path_has_symlink')(receipt_source) or receipt_source.is_symlink() or not receipt_source.is_file():
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt is missing or symlinked")
    try:
        receipt_raw = receipt_source.read_bytes()
    except _v4_global(_v4_scope, 'OSError') as error:
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt is unreadable") from error
    try:
        receipt_payload = _v4_global(_v4_scope, 'json').loads(receipt_raw.decode("utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt is unreadable") from error
    if not _v4_global(_v4_scope, 'isinstance')(receipt_payload, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'str')(receipt_payload.get("status") or "").upper() not in {"READY", "PASS"}:
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt is not READY")
    try:
        receipt_target = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'str')(receipt_payload.get("target_date") or "").replace("-", ""))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt target date is invalid") from error
    if receipt_target != _v4_global(_v4_scope, 'int')(target_date):
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt target date mismatch")
    if _v4_global(_v4_scope, 'any')(receipt_payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise _v4_global(_v4_scope, 'AuthorityError')("input manifest source sync receipt safety flags are not false")

    owned_manifest = _v4_global(_v4_scope, '_copy_generation_owned_file')(
        manifest_source,
        run_dir / "input-manifest.json",
        role="input manifest",
    )
    owned_receipt = _v4_global(_v4_scope, '_copy_generation_owned_file')(
        receipt_source,
        run_dir / "sync-receipt.json",
        role="sync receipt",
        expected_sha256=receipt_sha_value,
    )

    normalized_source = _v4_global(_v4_scope, 'dict')(source)
    # Keep the generation self-contained for both the current and legacy
    # source field spellings.  The raw input manifest remains byte-identical;
    # this only changes the generation metadata that points to its owned copy.
    normalized_source["sync_receipt_path"] = owned_receipt["path"]
    normalized_source["sync_receipt_sha256"] = owned_receipt["sha256"]
    if "source_receipt_path" in normalized_source:
        normalized_source["source_receipt_path"] = owned_receipt["path"]
    if "source_receipt_sha256" in normalized_source:
        normalized_source["source_receipt_sha256"] = owned_receipt["sha256"]
    return normalized_source, owned_manifest, owned_receipt
