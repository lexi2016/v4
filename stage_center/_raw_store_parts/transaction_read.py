"""stage_center.raw_store: transaction_read (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _RawStore__verify_run_paths_body(_v4_scope, /, self, *, trade_date, stage_id, market, run_id, expected_owner):
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_stage')(stage_id)
    role = self._role(stage_id, market)
    _v4_global(_v4_scope, '_validate_slug')(run_id, "run_id")
    prefix = f"runs/{trade_date}/{role}/{run_id}"
    run_dir = _v4_global(_v4_scope, '_safe_relative')(self.root, prefix)
    artifact = _v4_global(_v4_scope, '_safe_relative')(self.root, f"{prefix}/artifact.csv")
    manifest_path = _v4_global(_v4_scope, '_safe_relative')(self.root, f"{prefix}/manifest.json")
    receipt_path = _v4_global(_v4_scope, '_safe_relative')(self.root, f"{prefix}/receipt.json")
    if not run_dir.is_dir() or not _v4_global(_v4_scope, 'all')(path.is_file() for path in (artifact, manifest_path, receipt_path)):
        raise _v4_global(_v4_scope, 'RawStoreError')("run trio incomplete")
    manifest = _v4_global(_v4_scope, '_read_json')(manifest_path)
    receipt = _v4_global(_v4_scope, '_read_json')(receipt_path)
    if manifest.get("schema_version") != _v4_global(_v4_scope, 'RAW_MANIFEST_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'RawStoreError')("manifest schema mismatch")
    if receipt.get("schema_version") != _v4_global(_v4_scope, 'RAW_RECEIPT_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'RawStoreError')("receipt schema mismatch")
    for payload, label in ((manifest, "manifest"), (receipt, "receipt")):
        if payload.get("owner") != expected_owner:
            raise _v4_global(_v4_scope, 'RawStoreError')(f"{label} owner mismatch")
        if payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id or payload.get("market") != market:
            raise _v4_global(_v4_scope, 'RawStoreError')(f"{label} identity mismatch")
        if payload.get("run_id") != run_id:
            raise _v4_global(_v4_scope, 'RawStoreError')(f"{label} run_id mismatch")
        for key in _v4_global(_v4_scope, 'SAFETY_FLAGS'):
            if payload.get(key) is not False:
                raise _v4_global(_v4_scope, 'RawStoreError')(f"{label} safety flag {key!r} must be false")
    expected_artifact = f"{prefix}/artifact.csv"
    if manifest.get("artifact_relative") != expected_artifact:
        raise _v4_global(_v4_scope, 'RawStoreError')("manifest artifact path mismatch")
    if receipt.get("artifact_relative") != expected_artifact:
        raise _v4_global(_v4_scope, 'RawStoreError')("receipt artifact path mismatch")
    actual_artifact_sha = _v4_global(_v4_scope, '_sha_file')(artifact)
    if manifest.get("artifact_sha256") != actual_artifact_sha or receipt.get("artifact_sha256") != actual_artifact_sha:
        raise _v4_global(_v4_scope, 'RawStoreError')("artifact sha mismatch")
    with artifact.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = _v4_global(_v4_scope, 'csv').DictReader(stream)
        if _v4_global(_v4_scope, 'tuple')(reader.fieldnames or ()) != _v4_global(_v4_scope, 'ARTIFACT_FIELDS'):
            raise _v4_global(_v4_scope, 'RawStoreError')("raw artifact fields mismatch")
        rows = _v4_global(_v4_scope, 'list')(reader)
    row_count = _v4_global(_v4_scope, 'len')(rows)
    if manifest.get("row_count") != row_count or receipt.get("row_count") != row_count:
        raise _v4_global(_v4_scope, 'RawStoreError')("row_count mismatch")
    canonical_manifest_sha = _v4_global(_v4_scope, 'canonical_sha')(manifest)
    if receipt.get("manifest_sha256") != canonical_manifest_sha:
        raise _v4_global(_v4_scope, 'RawStoreError')("manifest sha mismatch")
    status = receipt.get("status")
    if status not in _v4_global(_v4_scope, 'RAW_STATUSES') or manifest.get("status") != status:
        raise _v4_global(_v4_scope, 'RawStoreError')("raw status mismatch")
    row_values = []
    for index, artifact_row in enumerate(rows):
        raw_flag = artifact_row.get("temporal_cutoff_safe")
        if raw_flag not in {"True", "False"}:
            raise _v4_global(_v4_scope, 'RawStoreError')(
                f"row {index}: temporal_cutoff_safe must be serialized as True or False"
            )
        row_values.append({
            field: (raw_flag == "True" if field == "temporal_cutoff_safe" else artifact_row.get(field))
            for field in _v4_global(_v4_scope, 'RAW_FIELDS')
        })
    source_evidence = manifest.get("source_evidence")
    cannot_confirm = manifest.get("cannot_confirm")
    requested_rows = manifest.get("requested_rows")
    missing_symbols = manifest.get("missing_symbols")
    if (
        receipt.get("source_id") != manifest.get("source_id")
        or receipt.get("source_status") != manifest.get("source_status")
        or receipt.get("source_evidence") != source_evidence
        or receipt.get("cannot_confirm") != cannot_confirm
        or receipt.get("requested_rows") != requested_rows
        or receipt.get("missing_symbols") != missing_symbols
    ):
        raise _v4_global(_v4_scope, 'RawStoreError')("raw source evidence identity mismatch")
    evidence_items = source_evidence if isinstance(source_evidence, list) else []
    mode_items = [
        str(item) for item in evidence_items
        if str(item).startswith(_v4_global(_v4_scope, 'HISTORICAL_OBSERVATION_MODE_EVIDENCE_PREFIX'))
    ]
    legacy_mode_present = _v4_global(_v4_scope, 'HK_0930_TDX_RESEARCH_MODE_EVIDENCE') in evidence_items
    has_temporal_false = any(row["temporal_cutoff_safe"] is False for row in row_values)
    allow_temporal_false_observation = False
    if mode_items or legacy_mode_present or has_temporal_false:
        contract = None
        if len(mode_items) == 1:
            contract = mode_items[0].split("=", 1)[1]
        elif legacy_mode_present:
            contract = _v4_global(_v4_scope, 'HK_0930_TDX_RESEARCH_CONTRACT')
        allow_temporal_false_observation = _v4_global(
            _v4_scope, '_allows_temporal_false_observation'
        )(
            contract=contract,
            trade_date=trade_date,
            stage_id=stage_id,
            market=market,
            source_id=manifest.get("source_id"),
            source_status=manifest.get("source_status"),
            rows=row_values,
            requested_rows=requested_rows,
            missing_symbols=missing_symbols or (),
            cannot_confirm=cannot_confirm or (),
            source_evidence=evidence_items,
        )
        if not allow_temporal_false_observation:
            raise _v4_global(_v4_scope, 'RawStoreError')(
                "temporal-false raw rows lack the exact historical research contract"
            )
        if (
            status != "PARTIAL_WITH_ROWS"
            or manifest.get("temporal_cutoff_safe") is not False
            or receipt.get("temporal_cutoff_safe") is not False
        ):
            raise _v4_global(_v4_scope, 'RawStoreError')(
                "historical temporal-false observation must remain PARTIAL and unsafe"
            )
    _validated_rows, row_issues = _v4_global(_v4_scope, 'validate_rows')(
        row_values,
        trade_date=trade_date,
        stage_id=stage_id,
        market=market,
        allow_temporal_false_observation=allow_temporal_false_observation,
    )
    if row_issues or len(_validated_rows) != row_count:
        raise _v4_global(_v4_scope, 'RawStoreError')(
            "raw artifact row validation failed: " + "; ".join(row_issues[:3])
        )
    if status == "READY" and (row_count <= 0 or manifest.get("temporal_cutoff_safe") is not True):
        raise _v4_global(_v4_scope, 'RawStoreError')("READY lacks rows or temporal proof")
    if status == "READY_EMPTY" and row_count != 0:
        raise _v4_global(_v4_scope, 'RawStoreError')("READY_EMPTY contains rows")
    if status == "PARTIAL_WITH_ROWS" and row_count <= 0:
        raise _v4_global(_v4_scope, 'RawStoreError')("PARTIAL_WITH_ROWS lacks rows")
    return {
        "owner": expected_owner,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": market,
        "role": role,
        "run_id": run_id,
        "status": status,
        "artifact_relative": expected_artifact,
        "manifest_relative": f"{prefix}/manifest.json",
        "receipt_relative": f"{prefix}/receipt.json",
        "artifact_sha256": actual_artifact_sha,
        "manifest_sha256": canonical_manifest_sha,
        "receipt_sha256": _v4_global(_v4_scope, 'canonical_sha')(receipt),
        "receipt_file_sha256": _v4_global(_v4_scope, '_sha_file')(receipt_path),
        "row_count": row_count,
        "requested_rows": manifest.get("requested_rows", row_count),
        "source_rows": manifest.get("source_rows", row_count),
        "coverage_ratio": manifest.get("coverage_ratio", 1.0),
        "missing_symbols": _v4_global(_v4_scope, 'list')(manifest.get("missing_symbols", [])),
        "source_evidence": _v4_global(_v4_scope, 'list')(manifest.get("source_evidence", [])),
        "cannot_confirm": _v4_global(_v4_scope, 'list')(manifest.get("cannot_confirm", [])),
        "calendar": _v4_global(_v4_scope, 'dict')(manifest.get("calendar", _v4_global(_v4_scope, 'calendar_provenance')())),
        "source_id": receipt.get("source_id"),
        "source_status": receipt.get("source_status"),
        "idempotency_key": receipt.get("idempotency_key"),
        "window": receipt.get("window"),
        "cutoff_at": receipt.get("cutoff_at"),
    }


def _RawStore__verify_bundle_body(_v4_scope, /, self, trade_date, stage_id, bundle_id):
    prefix = f"bundle_runs/{trade_date}/{stage_id}/{bundle_id}"
    receipt_relative = f"{prefix}/receipt.json"
    receipt_path = _v4_global(_v4_scope, '_safe_relative')(self.root, receipt_relative)
    if not receipt_path.is_file():
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle receipt missing")
    receipt = _v4_global(_v4_scope, '_read_json')(receipt_path)
    if receipt.get("schema_version") != _v4_global(_v4_scope, 'RAW_BUNDLE_SCHEMA_VERSION') or receipt.get("owner") != "stage_center":
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle receipt schema/owner mismatch")
    if receipt.get("trade_date") != trade_date or receipt.get("stage_id") != stage_id or receipt.get("bundle_id") != bundle_id:
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle receipt identity mismatch")
    if receipt.get("receipt_relative") != receipt_relative:
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle receipt path mismatch")
    for key in _v4_global(_v4_scope, 'SAFETY_FLAGS'):
        if receipt.get(key) is not False:
            raise _v4_global(_v4_scope, 'RawStoreError')(f"bundle receipt safety flag {key!r} must be false")
    markets = receipt.get("markets")
    if not _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle markets missing")
    expected_markets = _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, '_expected_bundle_markets')(stage_id, trade_date))
    if _v4_global(_v4_scope, 'set')(markets) != expected_markets:
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle market set mismatch")
    observed_statuses: set[str] = _v4_global(_v4_scope, 'set')()
    for market, entry in markets.items():
        if not _v4_global(_v4_scope, 'isinstance')(entry, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'RawStoreError')("bundle market entry malformed")
        verified = self.verify_run(trade_date, stage_id, market, _v4_global(_v4_scope, 'str')(entry.get("run_id")))
        if entry.get("receipt_sha256") != verified["receipt_sha256"] or entry.get("manifest_sha256") != verified["manifest_sha256"]:
            raise _v4_global(_v4_scope, 'RawStoreError')("bundle market SHA mismatch")
        observed_statuses.add(verified["status"])
    if observed_statuses == {"READY"}:
        expected_status = "READY"
    elif observed_statuses == {"READY_EMPTY"}:
        expected_status = "READY_EMPTY"
    elif observed_statuses == {"CANNOT_CONFIRM"} and _v4_global(_v4_scope, 'all')(
        self.verify_run(trade_date, stage_id, market, _v4_global(_v4_scope, 'str')(markets[market].get("run_id")))["row_count"] == 0
        for market in markets
    ):
        expected_status = "CANNOT_CONFIRM"
    else:
        expected_status = "PARTIAL_WITH_ROWS"
    if receipt.get("status") != expected_status:
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle status summary mismatch")
    if receipt.get("calendar") != _v4_global(_v4_scope, 'calendar_provenance')():
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle calendar provenance mismatch")
    return {
        "receipt": receipt,
        "receipt_sha256": _v4_global(_v4_scope, 'canonical_sha')(receipt),
        "receipt_file_sha256": _v4_global(_v4_scope, '_sha_file')(receipt_path),
        "receipt_relative": receipt_relative,
    }
