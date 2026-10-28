"""infrastructure.research_store: source_invalidation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__source_scope_from_evidence_value_body(_v4_scope, /, value):
    """Normalize a dispatcher/hourly pointer value to the scope enum."""

    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')):
        return _v4_global(_v4_scope, '_selection_market_name')(value)
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
        normalized = [_v4_global(_v4_scope, '_selection_market_name')(item) for item in value]
        if _v4_global(_v4_scope, 'any')(scope is None for scope in normalized):
            return None
        scopes = _v4_global(_v4_scope, 'set')(normalized)
        if _v4_global(_v4_scope, 'len')(scopes) == 1:
            return _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(scopes))
        if _v4_global(_v4_scope, 'len')(scopes) > 1:
            return "MIXED"
        return None
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        for field in ("market_scope", "source_scope", "scope", "eligible_markets", "markets"):
            if field in value:
                return _v4_global(_v4_scope, 'ResearchSelectionStore')._source_scope_from_evidence_value(
                    value[field]
                )
    return None


def _ResearchSelectionStore__verify_source_scope_evidence_body(_v4_scope, /, cls, record):
    """Verify every immutable evidence reference in one invalidation."""

    for ref in record["evidence_refs"]:
        path = _v4_global(_v4_scope, 'Path')(ref["path"])
        if not path.is_file() or path.is_symlink():
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence is unavailable")
        raw = path.read_bytes()
        if _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest() != _v4_global(_v4_scope, 'str')(ref["raw_sha256"]).lower():
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence SHA mismatch")
        try:
            document = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
        except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence is invalid JSON") from error
        observed = cls._source_scope_from_evidence_value(
            cls._pointer_value(document, ref["json_pointer"])
        )
        if observed != ref["observed_source_scope"]:
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence scope mismatch")


def _ResearchSelectionStore__read_source_scope_invalidations_body(_v4_scope, /, self, target_trade_date):
    """Read and verify append-only scope records for one exact target date."""

    prefix = f"{self._SELECTION_ROOT}/{target_trade_date}/invalidations/"
    manifest = self._manifest()
    manifest_paths = {
        relative
        for relative in manifest["entries"]
        if relative.startswith(prefix)
    }
    directory = self._path(prefix)
    if not directory.exists():
        if manifest_paths:
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation manifest mismatch")
        return []
    if not directory.is_dir() or directory.is_symlink():
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation directory is invalid")
    actual_paths: set[str] = _v4_global(_v4_scope, 'set')()
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation directory is invalid")
        actual_paths.add(f"{prefix}{path.name}")
    if actual_paths != manifest_paths:
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation manifest mismatch")

    records: list[dict[str, Any]] = []
    for relative in _v4_global(_v4_scope, 'sorted')(manifest_paths):
        path = self._path(relative)
        if not path.is_file() or path.is_symlink():
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation is unavailable")
        raw = path.read_bytes()
        digest = _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest()
        if manifest["entries"].get(relative) != digest:
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation manifest mismatch")
        try:
            record = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
        except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation is invalid JSON") from error
        if not _v4_global(_v4_scope, 'isinstance')(record, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation is not an object")
        try:
            _v4_global(_v4_scope, 'validate_selection_source_scope_invalidation')(
                record,
                expected_target_trade_date=target_trade_date,
            )
            expected_id = _v4_global(_v4_scope, 'selection_source_scope_invalidation_id')(record)
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'ValueError')(
                f"selection source-scope invalidation is invalid: {error}"
            ) from error
        if path.stem != expected_id or self._canonical_sha(record) != digest:
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation bytes mismatch")
        records.append(_v4_global(_v4_scope, 'dict')(record))
    return records


def _ResearchSelectionStore__assert_source_scope_not_invalidated_body(_v4_scope, /, self, payload, artifact_sha):
    records = self._read_source_scope_invalidations(
        _v4_global(_v4_scope, 'str')(payload["target_trade_date"])
    )
    for record in records:
        self._verify_source_scope_evidence(record)
        if (
            record["prior_run_id"] != payload.get("run_id")
            or _v4_global(_v4_scope, 'str')(record["prior_product_sha256"]).lower() != artifact_sha.lower()
        ):
            continue
        if record["source_date"] != payload.get("source_date"):
            raise _v4_global(_v4_scope, 'ValueError')("SOURCE_SCOPE_INVALIDATED: source date binding mismatch")
        raise _v4_global(_v4_scope, 'ValueError')(
            "SOURCE_SCOPE_INVALIDATED: upstream market scope invalidation "
            "matched prior run and product SHA"
        )


def _ResearchSelectionStore_publish_source_scope_invalidation_body(_v4_scope, /, self, record):
    """Append one independently attested upstream scope invalidation.

        The record is content-addressed and indexed by the selection manifest;
        it never changes an existing product, receipt, or current pointer.
        """

    target_trade_date = _v4_global(_v4_scope, 'validate_selection_source_scope_invalidation')(record)
    invalidation_id = _v4_global(_v4_scope, 'str')(record["invalidation_id"]).lower()
    expected_id = _v4_global(_v4_scope, 'selection_source_scope_invalidation_id')(record)
    if invalidation_id != expected_id:
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation id mismatch")
    relative = self._source_scope_invalidation_relative(
        target_trade_date,
        invalidation_id,
    )
    body = _v4_global(_v4_scope, 'dict')(record)
    self._verify_source_scope_evidence(body)
    digest = self._canonical_sha(body)
    path = self._path(relative)
    with self._lock():
        manifest = self._manifest()
        entries = _v4_global(_v4_scope, 'dict')(manifest["entries"])
        existing = entries.get(relative)
        if existing is not None:
            if existing != digest:
                raise _v4_global(_v4_scope, 'ValueError')("conflicting selection source-scope invalidation")
            if (
                not path.is_file()
                or path.is_symlink()
                or self._raw_sha(path) != digest
                or self._read(relative) != body
            ):
                raise _v4_global(_v4_scope, 'ValueError')(
                    "selection source-scope invalidation integrity mismatch"
                )
        else:
            if path.exists():
                raise _v4_global(_v4_scope, 'ValueError')(
                    "orphan selection source-scope invalidation"
                )
            self._write(relative, body)
            entries[relative] = digest
            self._write_manifest({**manifest, "entries": entries})
    return {
        "target_trade_date": target_trade_date,
        "invalidation_id": invalidation_id,
        "record_path": relative,
        "record_sha256": digest,
        "schema_version": _v4_global(_v4_scope, 'SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION'),
        "type": _v4_global(_v4_scope, 'SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE'),
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
